# -*- coding: utf-8 -*-
"""本地识图模型「切换」：用户能在已装的多个视觉模型间选择，不再被固定优先级压死。
背景 bug：_pick_vision_model 按固定优先级(qwen 在 moondream 前)自动挑，两个都装时
永远只用 qwen，moondream 装了也用不上、切不了。这里约束"尊重用户选择"。"""
import app as appmod


# ---------- picker：prefer 尊重用户选择 ----------

def test_prefer_overrides_fixed_priority():
    # 两个都装，用户选 moondream → 必须用 moondream，而不是优先级更高的 qwen
    got = appmod._pick_vision_model(["moondream:latest", "qwen2.5vl:3b"], prefer="moondream")
    assert got == "moondream:latest"


def test_prefer_matches_key_with_tag():
    # 用户选择项是带标签的 key（qwen2.5vl:3b），要能匹配到实际库名
    got = appmod._pick_vision_model(["moondream:latest", "qwen2.5vl:3b"], prefer="qwen2.5vl:3b")
    assert got == "qwen2.5vl:3b"


def test_prefer_ignored_when_not_pulled():
    # 用户选的模型没装 → 退回按优先级自动挑，不至于识图不了
    got = appmod._pick_vision_model(["qwen2.5vl:3b"], prefer="moondream")
    assert got == "qwen2.5vl:3b"


def test_no_prefer_keeps_legacy_priority():
    # 不传 prefer：保持老行为（qwen 优先），别破坏既有逻辑
    got = appmod._pick_vision_model(["moondream:latest", "qwen2.5vl:3b"])
    assert got == "qwen2.5vl:3b"


# ---------- 选择状态 get/set ----------

def test_get_set_vision_model_roundtrip():
    old = appmod.get_vision_model()
    try:
        assert appmod.set_vision_model("moondream") == "moondream"
        assert appmod.get_vision_model() == "moondream"
        # 空字符串 = 回到自动挑
        assert appmod.set_vision_model("") == ""
        assert appmod.get_vision_model() == ""
    finally:
        appmod.set_vision_model(old)


# ---------- 已装视觉模型清单（供前端下拉） ----------

def test_available_lists_only_vision_models():
    got = appmod._vision_models_available(
        ["moondream:latest", "qwen2.5vl:3b", "llama3:8b", "nomic-embed-text"])
    assert "moondream:latest" in got and "qwen2.5vl:3b" in got
    assert "llama3:8b" not in got and "nomic-embed-text" not in got


# ---------- status 与切换 API ----------

def _client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_vision_status_exposes_selected_and_available():
    old = appmod.get_vision_model()
    try:
        appmod.set_vision_model("moondream")
        data = _client().get("/api/vision_status").get_json()
        assert data["selected_model"] == "moondream"
        assert "available" in data          # 供前端渲染切换下拉
    finally:
        appmod.set_vision_model(old)


def test_set_vision_model_api():
    old = appmod.get_vision_model()
    try:
        r = _client().post("/api/set_vision_model", json={"model": "qwen2.5vl:3b"})
        assert r.get_json()["ok"] is True
        assert appmod.get_vision_model() == "qwen2.5vl:3b"
    finally:
        appmod.set_vision_model(old)
