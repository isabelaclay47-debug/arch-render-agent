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
