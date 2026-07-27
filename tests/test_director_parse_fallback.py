# -*- coding: utf-8 -*-
"""Bug3「未解析出分析内容」：QC 分析展示兜底 + parse_director_reply 容错。

根因是导演回复被中断/空（已在 test_gemini_director_stall 修）。此处再加两层防御：
  1. analysis_for_display：解析不出结构化 <分析> 时，展示裁剪后的**原始回复**，
     让建筑师至少看到导演原话，而不是无用的"（未解析出分析内容）"占位。
  2. parse_director_reply 容忍全角尖括号 ＜分析＞…＜/分析＞（IME/模型偶发）。
"""
import prompt_engine as pe


def test_analysis_prefers_structured():
    assert pe.analysis_for_display("[中等] 左侧建筑窗户偏移", "原始回复全文") == "[中等] 左侧建筑窗户偏移"


def test_analysis_falls_back_to_raw_reply_when_empty():
    raw = "我看了两张图，形体基本一致，光影自然，仅右下角招牌文字略糊。"
    out = pe.analysis_for_display("", raw)
    assert raw in out
    assert "未解析出分析内容" not in out   # 有原话时绝不再显示无用占位


def test_analysis_truncates_long_raw():
    raw = "长" * 5000
    out = pe.analysis_for_display("", raw, limit=1200)
    assert len(out) < 1500


def test_analysis_placeholder_only_when_nothing():
    assert pe.analysis_for_display("", "") == "（未解析出分析内容）"
    assert pe.analysis_for_display(None, None) == "（未解析出分析内容）"


def test_parse_tolerates_fullwidth_brackets():
    reply = "＜分析＞[轻微] 天空偏灰＜/分析＞＜忠实度＞一致＜/忠实度＞＜下一步＞精修＜/下一步＞"
    parsed = pe.parse_director_reply(reply)
    assert parsed["analysis"] == "[轻微] 天空偏灰"
    assert parsed["fidelity"] == "一致"
    assert parsed["next_step"] == "精修"


def test_parse_standard_tags_still_work():
    reply = "<分析>形体一致</分析><结论>可接受</结论><下一步>精修</下一步><精修指令>fix sky</精修指令>"
    parsed = pe.parse_director_reply(reply)
    assert parsed["analysis"] == "形体一致"
    assert parsed["verdict"] == "可接受"
    assert parsed["refine_instruction"] == "fix sky"
