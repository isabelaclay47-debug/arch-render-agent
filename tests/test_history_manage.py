# -*- coding: utf-8 -*-
"""历史管理（收藏 / 删除+回收站 / 互传）测试。
全程把 workspace 及派生目录指到临时目录，绝不碰用户真实历史数据。"""
import io
import json
import os

import app as appmod
from PIL import Image


def _isolate(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(appmod, "WORKSPACE", str(ws))
    monkeypatch.setattr(appmod, "TRASH_DIR", str(ws / "_trash"))
    monkeypatch.setattr(appmod, "FAV_FILE", str(ws / "_favorites.json"))
    monkeypatch.setattr(appmod, "HANDOFF_DIR", str(ws / "_handoff"))
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client(), ws


def _make_session(ws, name, n=2):
    d = ws / name
    d.mkdir()
    for i in range(1, n + 1):
        Image.new("RGB", (300, 200), (i * 40, 80, 120)).save(d / f"iter_{i:02d}.png")
    (d / "meta.json").write_text(
        json.dumps({"requirement": f"需求-{name}", "created": "2026-07-07 10:00"}),
        encoding="utf-8")
    return d


def test_history_skips_underscore_dirs(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "20260707_100000")
    (ws / "_trash").mkdir()
    _make_session(ws / "_trash", "20260707_090000")  # 回收站里的不该出现在历史
    sessions = c.get("/api/history").get_json()["sessions"]
    names = [s["session"] for s in sessions]
    assert "20260707_100000" in names
    assert all(not n.startswith("_") for n in names)


def test_history_includes_requirement(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "20260707_100000")
    s = c.get("/api/history").get_json()["sessions"][0]
    assert s["requirement"] == "需求-20260707_100000"


def test_favorite_toggle_and_list(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "sessA")
    c.post("/api/favorite", json={"session": "sessA", "image": "iter_01.png", "on": True})
    favs = c.get("/api/favorites").get_json()["favorites"]
    assert {"session": "sessA", "image": "iter_01.png"} in favs
    # 历史里该图标记为收藏
    s = next(x for x in c.get("/api/history").get_json()["sessions"] if x["session"] == "sessA")
    assert "iter_01.png" in s["favorites"]
    # 取消收藏
    c.post("/api/favorite", json={"session": "sessA", "image": "iter_01.png", "on": False})
    assert c.get("/api/favorites").get_json()["favorites"] == []


def test_delete_session_to_trash_and_restore(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "sessDel")
    r = c.post("/api/history_delete", json={"session": "sessDel"})
    assert r.status_code == 200
    assert not (ws / "sessDel").exists()                 # 原位置已移走
    assert c.get("/api/history").get_json()["sessions"] == []
    tid = c.get("/api/trash").get_json()["items"][0]["id"]
    c.post("/api/trash_restore", json={"id": tid})
    assert (ws / "sessDel").exists()                     # 恢复回原处
    assert c.get("/api/trash").get_json()["items"] == []


def test_delete_single_image_and_empty_trash(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "sessImg", n=2)
    c.post("/api/history_delete", json={"session": "sessImg", "image": "iter_01.png"})
    assert not (ws / "sessImg" / "iter_01.png").exists()
    assert (ws / "sessImg" / "iter_02.png").exists()     # 另一张还在
    assert len(c.get("/api/trash").get_json()["items"]) == 1
    c.post("/api/trash_empty")
    assert c.get("/api/trash").get_json()["items"] == []
    # 清空后回收站里不应再残留任何被删的图目录（manifest.json 允许留存）
    leftovers = [n for n in os.listdir(ws / "_trash") if n != "manifest.json"]
    assert leftovers == []


def test_delete_rejects_path_traversal(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "real")
    sentinel = tmp_path / "OUTSIDE.txt"          # workspace 之外的东西
    sentinel.write_text("x")
    for evil in ["..", "../", "..\\", "../../", "_trash"]:
        r = c.post("/api/history_delete", json={"session": evil})
        assert r.status_code in (400, 404), f"{evil!r} 未被拦截"
    assert sentinel.exists()                     # 外部文件毫发无损
    assert (tmp_path / "workspace").exists()      # workspace 本身没被移走


def test_handoff_roundtrip(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    _make_session(ws, "sessH")
    # 从 workspace 图发给 render
    r = c.post("/api/handoff", data={"to": "render", "from": "sessH/iter_01.png"})
    assert r.get_json()["ok"] is True
    got = c.get("/api/handoff/render")
    assert got.status_code == 200 and got.data[:2] == b"\xff\xd8"  # JPEG 魔数
    c.post("/api/handoff_clear", json={"to": "render"})
    assert c.get("/api/handoff/render").status_code == 404


def test_handoff_upload_to_helper(tmp_path, monkeypatch):
    c, ws = _isolate(tmp_path, monkeypatch)
    buf = io.BytesIO()
    Image.new("RGB", (200, 150), (10, 20, 30)).save(buf, "PNG")
    buf.seek(0)
    r = c.post("/api/handoff", data={"to": "helper", "image": (buf, "x.png")},
               content_type="multipart/form-data")
    assert r.get_json()["ok"] is True
    assert c.get("/api/handoff/helper").status_code == 200
