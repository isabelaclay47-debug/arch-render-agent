# -*- coding: utf-8 -*-
"""Gemini 全包分工（选谁只启动谁）：
  · 设置开关读写；_login_targets 按分工只要求登录该启动的站点；
  · GeminiClient 作导演时按 page 判角色：director 只刷新保上下文、gen 才换对话/新窗口。"""
import app
from gemini_client import GeminiClient


class _FakePage:
    def __init__(self, alive=True):
        self.reloads = 0
        self._alive = alive
    def reload(self, **k): self.reloads += 1
    def wait_for_timeout(self, ms): pass
    def evaluate(self, *a, **k):
        if not self._alive:
            raise RuntimeError("closed")
        return 1
    def close(self): pass
    def goto(self, *a, **k): pass


def test_selfrun_toggle_accepts_bool_and_strings():
    try:
        assert app.set_gemini_selfrun(False) is False and app.get_gemini_selfrun() is False
        assert app.set_gemini_selfrun(True) is True and app.get_gemini_selfrun() is True
        assert app.set_gemini_selfrun("0") is False
        assert app.set_gemini_selfrun("on") is True
    finally:
        app.set_gemini_selfrun(True)   # 恢复默认


def test_login_targets_respects_selfrun():
    try:
        app.set_image_engine("gemini")
        app.set_gemini_selfrun(True)
        assert [t[0] for t in app._login_targets()] == ["Gemini"]        # 全包只登 Gemini
        app.set_gemini_selfrun(False)
        assert [t[0] for t in app._login_targets()] == ["Gemini", "ChatGPT"]  # 借 ChatGPT 两个都登
        app.set_image_engine("chatgpt")
        assert [t[0] for t in app._login_targets()] == ["ChatGPT"]
    finally:
        app.set_image_engine("chatgpt")
        app.set_gemini_selfrun(True)


def test_current_page_routes_by_role():
    c = GeminiClient(log=lambda *a, **k: None)
    c.gen_page, c.director_page = "GEN", "DIR"
    assert c._current_page("gen") == "GEN"
    assert c._current_page("director") == "DIR"
    c.director_page = None                        # 只当画手：director 回落到 gen
    assert c._current_page("director") == "GEN"


def test_recover_director_only_reloads_never_new_chat():
    """导演文字失败：只刷新、绝不新开对话（否则丢理解/提示词上下文）。"""
    c = GeminiClient(log=lambda *a, **k: None)
    calls = []
    c.new_generation_chat = lambda: calls.append("new_chat")
    c.new_generation_window = lambda: calls.append("new_window")
    dp = _FakePage()
    c.director_page, c.gen_page = dp, _FakePage()
    c._recover_before_retry("director", attempt=1, max_attempts=3, expect_image=False)
    assert calls == [] and dp.reloads == 1


def test_recover_gen_escalates_chat_then_window():
    """生图失败：先换新对话，attempt>=2 升级另开新窗口。"""
    c = GeminiClient(log=lambda *a, **k: None)
    calls = []
    c.new_generation_chat = lambda: calls.append("new_chat")
    c.new_generation_window = lambda: calls.append("new_window")
    c.gen_page, c.director_page = _FakePage(), None
    c._recover_before_retry("gen", 1, 3, True)
    c._recover_before_retry("gen", 2, 3, True)
    assert calls == ["new_chat", "new_window"]
