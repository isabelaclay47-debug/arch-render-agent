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
