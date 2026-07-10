# -*- coding: utf-8 -*-
"""单张按需画质增强（页面上「提升并查看」）+ 完成时增强并页面可见。

测试环境无 numpy/onnxruntime → import image_enhance 失败，走「缺依赖优雅跳过」路径：
仍复制出副本（页面有图看），只是不真超分。这恰好能稳定验证管道接线，不碰重模型。
"""
import os
import shutil

import app as appmod

_REAL_IMG = "workspace/20260710_113834/iter_01.png"


def _client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_enhance_to_graceful_makes_copy(tmp_path):
    dst = str(tmp_path / "out.png")
    r = appmod._enhance_to(_REAL_IMG, dst, "2k", dewm=False)
    assert os.path.isfile(dst), "缺依赖也要产出副本，页面才有图可看"
    assert r["from"], "应读到原图尺寸"
    assert r["to"] == "" and r["skipped"], "无 onnx 时不真超分，但要优雅跳过而非崩"


def test_enhance_job_updates_state(tmp_path):
    dst = str(tmp_path / "job.png")
    appmod._run_enhance_job(_REAL_IMG, dst, "/images/x/job.png", "2k", False, "k1")
    assert appmod._enh_job["done"] and appmod._enh_job["ok"]
    assert appmod._enh_job["url"].endswith("job.png")
    assert os.path.isfile(dst)


def test_enhance_image_validations():
    c = _client()
    # 图不存在 → 400
    assert c.post("/api/enhance_image",
                  json={"session": "nope", "image": "nope.png", "quality": "2k"}).status_code == 400
    # 1K 原生无需增强 → 400（用真实存在的图，确保过了 isfile 检查才触发这条）
    assert c.post("/api/enhance_image",
                  json={"session": "20260710_113834", "image": "iter_01.png",
                        "quality": "1k"}).status_code == 400
    # 未知档位 → 400
    assert c.post("/api/enhance_image",
                  json={"session": "20260710_113834", "image": "iter_01.png",
                        "quality": "16k"}).status_code == 400


def test_enhance_image_cache_hit(tmp_path):
    """已存在 _enh_{q}_{img} 时秒回 cached=True，不重复跑。"""
    sess_dir = os.path.join(appmod.WORKSPACE, "20260710_113834")
    if not os.path.isdir(sess_dir):
        return  # 无该会话则跳过（不同机器）
    cached = os.path.join(sess_dir, "_enh_4k_iter_01.png")
    shutil.copyfile(os.path.join(sess_dir, "iter_01.png"), cached)
    try:
        j = _client().post("/api/enhance_image",
                           json={"session": "20260710_113834", "image": "iter_01.png",
                                 "quality": "4k"}).get_json()
        assert j["ok"] and j["cached"] and j["url"].endswith("_enh_4k_iter_01.png")
    finally:
        os.remove(cached)


def test_enhance_status_shape():
    j = _client().get("/api/enhance_status").get_json()
    assert {"active", "done", "ok", "url", "from", "to"}.issubset(j.keys())


def test_deliver_final_copies_into_session(tmp_path, monkeypatch):
    """完成收尾：把最终图按档位增强一份到会话目录（页面 /images 可取），并 state=done。
    无 onnx 时增强退化为副本，final_{q}.png 仍应存在（页面有图），state 正确。"""
    sess = tmp_path / "sess_x"
    sess.mkdir()
    shutil.copyfile(_REAL_IMG, sess / "iter_01.png")
    monkeypatch.setattr(appmod, "desktop_path", lambda: str(tmp_path))
    appmod.S["items"] = [{"iter": 1, "image": "iter_01.png", "kind": "auto",
                          "analysis": "", "verdict": "", "prompt": ""}]
    appmod.set_quality("2k")
    try:
        appmod._deliver_final(str(sess))
        assert appmod.S["state"] == "done"
        assert appmod.S["final_path"] and os.path.isfile(appmod.S["final_path"])
        assert os.path.isfile(str(sess / "final_2k.png")), "会话目录要有增强副本，页面才看得到"
    finally:
        appmod.set_quality("1k")
        appmod.S["items"] = []
