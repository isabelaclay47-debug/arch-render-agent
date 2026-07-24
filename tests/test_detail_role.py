# -*- coding: utf-8 -*-
"""细部·必须保留（多参照单输出强忠实）回归：
新增 detail 角色——细部图作为强忠实约束一起生图、并逐张进篡改检查。
纯 prompt_engine 逻辑，不启动浏览器。"""
import prompt_engine as pe


# ---------------- Task 1: detail 角色注册 ----------------

def test_detail_role_registered():
    assert pe.REF_ROLE_LABELS["detail"] == "细部·必须保留"
    en = pe.REF_ROLE_EN["detail"].lower()
    assert "faithfully reproduced" in en
    assert "must" in en


# ---------------- Task 2: 生图提示词按角色分流 ----------------

def test_generation_message_detail_is_faithful_others_not():
    msg = pe.generation_message_multi("PROMPT", ["material", "detail"]).lower()
    # footer 的分流约束：细部图强忠实（不只是角色行里的描述）
    assert "for detail images, faithfully reproduce" in msg
    # 非细部参照仍被明确禁止照抄形体
    assert "never copy their geometry" in msg


def test_generation_message_no_detail_keeps_blanket_rule():
    msg = pe.generation_message_multi("PROMPT", ["material", "mood"])
    assert "never copy a reference image" in msg.lower()
    assert "faithfully reproduce" not in msg.lower()


# ---------------- Task 3: QC 提示词 detail_count ----------------

def test_qc_prompt_mentions_details_when_present():
    p = pe.qc_and_revise_prompt(3, detail_count=2)
    assert "中间 2 张" in p
    assert "细部" in p
    assert "逐张核对" in p


def test_qc_prompt_backward_compatible_without_details():
    p = pe.qc_and_revise_prompt(3)  # detail_count 默认 0
    assert "第二张为本轮生成图" in p
    assert "细部" not in p


# ---------------- Task 4: qc_image_paths 图序组装 ----------------

def test_qc_image_paths_orders_base_details_output():
    got = pe.qc_image_paths(
        "base.png", "out.png",
        ref_images=["m.png", "d1.png", "d2.png", "mood.png"],
        ref_roles=["material", "detail", "detail", "mood"])
    assert got == ["base.png", "d1.png", "d2.png", "out.png"]


def test_qc_image_paths_no_details():
    got = pe.qc_image_paths("base.png", "out.png", ref_images=["m.png"], ref_roles=["material"])
    assert got == ["base.png", "out.png"]


def test_qc_image_paths_tolerates_missing_roles():
    got = pe.qc_image_paths("base.png", "out.png", ref_images=None, ref_roles=None)
    assert got == ["base.png", "out.png"]
