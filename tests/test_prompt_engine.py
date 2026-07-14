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


def test_generation_multi_generic_enumerates_all_refs():
    # "不定义每张"：两张通用参考图
    msg = pe.generation_message_multi("PROMPT_BODY", ["generic", "generic"])
    assert "I uploaded 3 images" in msg           # 底图 + 2 参考
    assert "Image 2 is a general REFERENCE" in msg
    assert "Image 3 is a general REFERENCE" in msg
    assert "no questions, no explanation" in msg  # 防"分析而非生成"
    assert "do NOT describe or analyze" in msg
    assert pe.GENERATION_BASICS in msg
    assert "PROMPT_BODY" in msg


def test_generation_multi_defined_roles_render_distinct_text():
    # "定义每张"：材质 + 氛围
    msg = pe.generation_message_multi("BODY", ["material", "mood"])
    assert "Image 2 is a MATERIAL sample" in msg
    assert "Image 3 is a MOOD" in msg


def test_generation_multi_unknown_role_falls_back_to_generic():
    msg = pe.generation_message_multi("BODY", ["banana"])
    assert "Image 2 is a general REFERENCE" in msg   # 未知角色回退通用，不崩


def test_ref_role_labels_cover_all_english_roles():
    # 前端下拉/后端校验用的中文标签，必须与英文角色一一对应
    assert set(pe.REF_ROLE_LABELS) == set(pe.REF_ROLE_EN)


def test_director_prompt_has_architectural_read_step():
    # 建筑专用识图：动笔前必须"先读原图"抽建筑关键事实（强化忠实度），
    # 而不是泛泛描述"一栋现代建筑"。
    sp = pe.director_system_prompt()
    assert pe.ARCH_READ_STEP in sp
    for kw in ("先读原图", "体量", "开窗", "标志性构件", "材质"):
        assert kw in sp


def test_arch_read_step_requires_facts_in_understanding_and_prompt():
    # 识别到的建筑事实要写进<理解>让建筑师复核，也要"钉死"进英文提示词保忠实
    step = pe.ARCH_READ_STEP
    assert "<理解>" in step
    assert "英文提示词" in step


def test_helper_understand_prompt_is_understanding_only():
    # 第一步只出理解、先不写提示词（对话确认式的前半段）
    p = pe.helper_understand_prompt("黄昏暖光")
    assert "<理解>" in p and "先不要写提示词" in p
    assert "黄昏暖光" in p
    assert "英文提示词" not in p     # 这一步不产提示词


def test_helper_generate_after_confirm_uses_confirmed_understanding():
    # 第二步以"已确认的理解"为准绳产出双语提示词
    p = pe.helper_generate_after_confirm_prompt("两栋石材办公楼，六层，竖向开窗", intent="加行人")
    assert "两栋石材办公楼，六层，竖向开窗" in p
    assert "加行人" in p
    assert pe._BILINGUAL_OUTPUT_SPEC in p
