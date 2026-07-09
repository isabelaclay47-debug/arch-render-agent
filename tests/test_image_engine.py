# -*- coding: utf-8 -*-
"""生图引擎切换（ChatGPT / Gemini nano-banana）的选择与守卫逻辑。"""
import app as appmod


def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_default_engine_is_chatgpt():
    appmod.set_image_engine("chatgpt")
    assert appmod.get_image_engine() == "chatgpt"


def test_set_engine_gemini_and_back():
    try:
        assert appmod.set_image_engine("gemini") == "gemini"
        assert appmod.get_image_engine() == "gemini"
    finally:
        appmod.set_image_engine("chatgpt")


def test_set_engine_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        appmod.set_image_engine("midjourney")


def test_status_exposes_engine():
    appmod.set_image_engine("chatgpt")
    r = client().get("/api/status")
    assert r.status_code == 200
    assert r.get_json()["image_engine"] == "chatgpt"


def test_set_engine_endpoint_when_idle():
    appmod.S["state"] = "idle"
    try:
        r = client().post("/api/set_engine", json={"engine": "gemini"})
        assert r.status_code == 200 and r.get_json()["engine"] == "gemini"
        assert client().get("/api/status").get_json()["image_engine"] == "gemini"
    finally:
        appmod.set_image_engine("chatgpt")


def test_set_engine_blocked_while_running():
    appmod.S["state"] = "running"
    try:
        r = client().post("/api/set_engine", json={"engine": "gemini"})
        assert r.status_code == 400
        assert appmod.get_image_engine() == "chatgpt"   # 没被改动
    finally:
        appmod.S["state"] = "idle"


def test_gemini_client_shares_stalled_error():
    # Gemini 生图卡死必须命中 app.py 的 except GenStalledError（否则会话会被误判结束）
    import gemini_client
    from chatgpt_client import GenStalledError
    assert gemini_client.GenStalledError is GenStalledError
