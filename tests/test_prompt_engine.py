# -*- coding: utf-8 -*-
import prompt_engine as pe


def test_build_prompt_locally_returns_three_parts():
    out = pe.build_prompt_locally(
        intent="黄昏暖光，玻璃幕墙要有真实反射",
        image_desc="A modern glass office building, dusk",
        preset_texts=["低反射 Low-E 玻璃，竖梃清晰"],
    )
    assert set(out) == {"understanding_zh", "prompt_zh", "prompt_en"}


def test_build_prompt_locally_injects_english_baseline():
    out = pe.build_prompt_locally("随便", "", [])
    # 英文提示词必须强制附带通用底线（和主功能同一套）
    assert pe.GENERATION_BASICS in out["prompt_en"]


def test_build_prompt_locally_includes_user_and_presets():
    out = pe.build_prompt_locally(
        intent="加行人和行道树",
        image_desc="street view",
        preset_texts=["石材立面细节：分缝对齐"],
    )
    assert "加行人和行道树" in out["prompt_zh"]
    assert "石材立面细节：分缝对齐" in out["prompt_zh"]
    assert "street view" in out["prompt_en"]


def test_build_prompt_locally_handles_empty_gracefully():
    out = pe.build_prompt_locally("", "", [])
    assert out["prompt_zh"].strip()      # 不因空输入而产出空串
    assert out["prompt_en"].strip()
