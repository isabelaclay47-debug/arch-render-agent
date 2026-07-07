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
