# -*- coding: utf-8 -*-
"""8K 画质档位：端点契约 / 白名单 / status 回显 / _maybe_enhance 优雅跳过。
不触发真实超分（不加载模型），全部快而稳。"""
import app as appmod


def _client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_set_quality_whitelist():
    assert appmod.set_quality("4k") == "4k"
    assert appmod.set_quality("1K") == "1k"          # 大小写归一
    for bad in ("", "16k", "hd", "bad;rm"):
        try:
            appmod.set_quality(bad); assert False, f"应拒绝 {bad}"
        except ValueError:
            pass
    appmod.set_quality("1k")                          # 复位默认


def test_set_quality_endpoint():
    c = _client()
    r = c.post("/api/set_quality", json={"quality": "8k"})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "quality": "8k"}
    r = c.post("/api/set_quality", json={"quality": "nope"})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    appmod.set_quality("1k")


def test_status_echoes_quality():
    c = _client()
    appmod.set_quality("2k")
    j = c.get("/api/status").get_json()
    assert j.get("quality") == "2k"
    appmod.set_quality("1k")


def test_maybe_enhance_noop_on_1k_chatgpt(monkeypatch):
    # 1k + 非 gemini：应零开销直接返回，绝不 import image_enhance
    appmod.set_quality("1k")
    monkeypatch.setattr(appmod, "get_image_engine", lambda: "chatgpt")
    called = {"n": 0}
    import builtins
    real_import = builtins.__import__
    def spy(name, *a, **k):
        if name == "image_enhance":
            called["n"] += 1
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", spy)
    appmod._maybe_enhance("/nonexistent.png")
    assert called["n"] == 0        # 没碰增强模块


def test_maybe_enhance_graceful_when_module_missing(monkeypatch):
    # 高档位但 image_enhance import 失败：只 log 跳过，不抛异常
    appmod.set_quality("4k")
    monkeypatch.setattr(appmod, "get_image_engine", lambda: "chatgpt")
    import builtins
    real_import = builtins.__import__
    def boom(name, *a, **k):
        if name == "image_enhance":
            raise ImportError("no onnxruntime")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", boom)
    appmod._maybe_enhance("/whatever.png")   # 不应抛
    appmod.set_quality("1k")
