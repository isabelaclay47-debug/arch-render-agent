# -*- coding: utf-8 -*-
import app as appmod


def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_helper_build_returns_bilingual_prompt():
    c = client()
    r = c.post("/api/helper_build", json={
        "intent": "黄昏暖光",
        "image_desc": "modern glass building at dusk",
        "presets": ["低反射 Low-E 玻璃"],
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "黄昏暖光" in data["prompt_zh"]
    assert "modern glass building at dusk" in data["prompt_en"]
    assert appmod.pe.GENERATION_BASICS in data["prompt_en"]


def test_helper_build_empty_ok():
    c = client()
    r = c.post("/api/helper_build", json={"intent": "", "image_desc": "", "presets": []})
    assert r.status_code == 200
    assert r.get_json()["prompt_en"].strip()


def test_helper_refine_blocked_when_rendering():
    c = client()
    appmod.S["state"] = "running"           # 模拟主渲染进行中
    try:
        r = c.post("/api/helper_refine", data={"draft_prompt": "x"})
        assert r.status_code == 409
        assert r.get_json()["ok"] is False
    finally:
        appmod.S["state"] = "idle"


def test_helper_refine_requires_chatgpt_ready(monkeypatch):
    c = client()
    appmod.S["state"] = "idle"
    # 强制 chrome 检测为未就绪
    monkeypatch.setattr(appmod, "_helper_chatgpt_ready", lambda: False)
    r = c.post("/api/helper_refine", data={"draft_prompt": "x"})
    assert r.status_code == 400
    assert "ChatGPT" in r.get_json()["msg"]
