# -*- coding: utf-8 -*-
"""第 7 轮功能补充的可单测部分：
   ② meta 持久化(初始命令+最后一版提示词) / 历史返回
   ③⑦ GenStalledError 类型契约
   ④ 助手页改稿模式提示词
   ⑤ 在线更新端点契约
全程隔离到临时 workspace，绝不碰真实历史。"""
import json

import app as appmod
import prompt_engine as pe
from chatgpt_client import ChatGPTError, GenStalledError


def _client(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setattr(appmod, "WORKSPACE", str(ws))
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client(), ws


# ---- ② meta：初始命令 + 最后一版提示词 ----
def test_update_meta_merges_and_keeps_initial_command(tmp_path):
    d = tmp_path / "sess"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"requirement": "初始命令X"}), encoding="utf-8")
    appmod._update_meta(str(d), last_prompt_zh="中文提示词V2", last_prompt_en="EN v2")
    appmod._update_meta(str(d), last_prompt_zh="中文提示词V3")  # 再更新一版
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["requirement"] == "初始命令X"          # 初始命令始终保留
    assert meta["last_prompt_zh"] == "中文提示词V3"     # 覆盖成最后一版
    assert meta["last_prompt_en"] == "EN v2"           # 未传的字段不被清空


def test_update_meta_ignores_empty_fields(tmp_path):
    d = tmp_path / "sess"
    d.mkdir()
    appmod._update_meta(str(d), last_prompt_zh="A", last_prompt_en="")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["last_prompt_zh"] == "A"
    assert "last_prompt_en" not in meta               # 空字段不写入


def test_history_returns_last_prompt(tmp_path, monkeypatch):
    from PIL import Image
    c, ws = _client(tmp_path, monkeypatch)
    d = ws / "20260707_120000"
    d.mkdir()
    Image.new("RGB", (200, 150), (100, 120, 140)).save(d / "iter_01.png")
    (d / "meta.json").write_text(json.dumps(
        {"requirement": "建筑师初始命令", "last_prompt_zh": "最后中文", "last_prompt_en": "final EN"},
        ensure_ascii=False), encoding="utf-8")
    sess = c.get("/api/history").get_json()["sessions"][0]
    assert sess["requirement"] == "建筑师初始命令"
    assert sess["last_prompt_zh"] == "最后中文"
    assert sess["last_prompt_en"] == "final EN"


# ---- ③⑦ 自愈：GenStalledError 是可恢复的 ChatGPTError 子类 ----
def test_gen_stalled_is_recoverable_subclass():
    assert issubclass(GenStalledError, ChatGPTError)
    # 上层用 except GenStalledError 能在 except ChatGPTError 之前拦下重试
    try:
        raise GenStalledError("stall")
    except GenStalledError as e:
        assert "stall" in str(e)


# ---- ④ 助手页改稿模式 ----
def test_helper_refine_prompt_revision_mode():
    p = pe.helper_refine_prompt("草稿", prev_zh="上一版中文提示词", feedback="太商业了要住宅感")
    assert "上一版中文提示词" in p
    assert "太商业了要住宅感" in p
    assert "不满意" in p


def test_helper_refine_prompt_first_pass_ignores_empty_feedback():
    p = pe.helper_refine_prompt("我的草稿")
    assert "我的草稿" in p
    assert "上一版" not in p


# ---- ⑤ 在线更新端点契约 ----
def test_update_check_shape(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    j = c.get("/api/update_check").get_json()
    assert "ok" in j
    if j["ok"]:
        assert set(("current", "branch", "behind", "has_update")).issubset(j)


def test_update_apply_refused_while_busy(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    appmod.S["state"] = "running"
    try:
        r = c.post("/api/update_apply")
        assert r.status_code == 400
        assert "渲染" in r.get_json()["msg"]
    finally:
        appmod.S["state"] = "idle"


def test_helper_vision_degrades_without_ollama(tmp_path, monkeypatch):
    import io
    from PIL import Image
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "_ollama_models", lambda: [])   # 强制"没装 Ollama"
    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (150, 150, 150)).save(buf, "PNG")
    buf.seek(0)
    r = c.post("/api/helper_vision", data={"image": (buf, "t.png")},
               content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] is False
    assert j["reason"] == "no_ollama" and "Ollama" in j["msg"]


def test_pick_vision_model_prefers_known_vlm():
    assert appmod._pick_vision_model(["llama3:8b", "qwen2.5-vl:7b"]) == "qwen2.5-vl:7b"
    assert appmod._pick_vision_model(["llama3:8b"]) == ""


# ---- ⑤ 依赖变化则自动 pip install（契约层面）----
def test_update_check_reports_deps_changed(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    j = c.get("/api/update_check").get_json()
    if j["ok"]:
        assert "deps_changed" in j        # 字段存在，供前端提示


# ---- ④ 一键装本地识图：状态 + 安全名 + 同意后触发（不真下载）----
def test_safe_model_name_whitelist():
    assert appmod._safe_model_name("qwen2.5vl:3b") == "qwen2.5vl:3b"
    assert appmod._safe_model_name("moondream") == "moondream"
    assert appmod._safe_model_name("bad name;rm -rf") == ""     # 拒绝空格/分号/注入
    assert appmod._safe_model_name("") == ""


def test_vision_status_offers_install_when_absent(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod, "_ollama_models", lambda: [])
    monkeypatch.setattr(appmod, "_ollama_exe", lambda: "")
    monkeypatch.setattr(appmod, "_ollama_up", lambda: False)
    j = c.get("/api/vision_status").get_json()
    assert j["ready"] is False and j["installed"] is False
    assert appmod.OLLAMA_DEFAULT_MODEL in j["choices"]


def test_vision_setup_consented_starts_without_downloading(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    called = {}
    # 用桩替换真正的安装/下载，绝不在测试里跑安装程序
    monkeypatch.setattr(appmod, "_run_vision_setup", lambda model: called.setdefault("m", model))
    appmod._vision_setup["active"] = False
    r = c.post("/api/vision_setup", json={"model": "moondream"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # active 已被端点置位，桩函数会被后台线程调用
    import time
    time.sleep(0.1)
    assert called.get("m") == "moondream"
    appmod._vision_setup.update({"active": False, "stage": "idle", "log": []})
