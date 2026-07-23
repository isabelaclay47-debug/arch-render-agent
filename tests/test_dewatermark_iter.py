# -*- coding: utf-8 -*-
"""过程图去水印（Gemini 全程干净）：仅 gemini 引擎触发，只去水印不放大；
非 gemini 零开销跳过；出错时优雅吞掉，绝不影响出图流程。

测试环境无 numpy → 不能真 import image_enhance，用 sys.modules 注入假模块验证接线。"""
import sys
import types

import app


def _fake_ie(calls, raise_=False):
    m = types.ModuleType("image_enhance")
    def enhance_file(path, quality, dewatermark_wm, log):
        if raise_:
            raise RuntimeError("lama exploded")
        calls.append((quality, dewatermark_wm))
        return {"dewatermark": True, "upscaled_to": None, "skipped": []}
    m.enhance_file = enhance_file
    return m


def test_dewatermark_inplace_only_for_gemini(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "image_enhance", _fake_ie(calls))
    try:
        app.set_image_engine("chatgpt")
        app._dewatermark_inplace("x.png")
        assert calls == []                       # 非 gemini：完全不动，连 import 都不做

        app.set_image_engine("gemini")
        app._dewatermark_inplace("x.png")
        assert calls == [("1k", True)]           # gemini：只去水印(dewm=True)、不放大(1k)
    finally:
        app.set_image_engine("chatgpt")


def test_dewatermark_inplace_swallows_errors(monkeypatch):
    monkeypatch.setitem(sys.modules, "image_enhance", _fake_ie([], raise_=True))
    try:
        app.set_image_engine("gemini")
        app._dewatermark_inplace("x.png")        # 不抛错即通过（出图绝不被去水印带崩）
    finally:
        app.set_image_engine("chatgpt")
