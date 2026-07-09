# -*- coding: utf-8 -*-
"""本地识图模型识别：pull 成功后必须能被认出来，否则会误判成“下载失败”。"""
import app as appmod


def test_pick_qwen_hyphen_insensitive():
    # 用户选“推荐”的 qwen2.5vl:3b（Ollama 库名无连字符），历史上 hint 带连字符匹配不到 → 误判失败
    assert appmod._pick_vision_model(["qwen2.5vl:3b"]) == "qwen2.5vl:3b"


def test_pick_moondream_default():
    assert appmod._pick_vision_model(["moondream:latest"]) == "moondream:latest"


def test_pick_prefers_stronger_model_order():
    # qwen 排在 moondream 前面：两个都装时优先更强的建筑识别模型
    got = appmod._pick_vision_model(["moondream:latest", "qwen2.5vl:3b"])
    assert got == "qwen2.5vl:3b"


def test_pick_none_when_no_vision_model():
    assert appmod._pick_vision_model(["llama3:8b", "nomic-embed-text"]) == ""


def test_pick_empty_list():
    assert appmod._pick_vision_model([]) == ""
