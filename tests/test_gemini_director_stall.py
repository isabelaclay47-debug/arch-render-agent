# -*- coding: utf-8 -*-
"""Gemini 导演文字生成"被刷新掐断"根因回归（Image#7 / dump 20260727_094829 实证）。

真实证据：导演（Gemini 全包）首轮/QC 的文字回复被记成**空白的**「你已让系统停止这条回答」，
上层因此报"两次都没给出可用英文提示词"（一开始就报错），或 QC 解析出空分析（未解析出分析内容）。

根因：gemini_client._wait_reply_done 的**阶段一**在 Gemini Pro 思考期（>RELOAD_INTERVAL 秒仍
未出现回复容器、且思考期无可匹配的停止键）误判"页面卡住"→ page.reload() → 把正在思考的回答
刷掉 → Gemini 显示"你已让系统停止这条回答"。刷新对文本导演是**破坏性**的（既掐断又丢上下文）。

对照 chatgpt_client._wait_reply_done（成熟参考）：文本必须**非空且稳定**才返回、空回复抛错让
send() 自愈重试、刷新有 AUTO_RELOAD_CAP 上限。本测试把 gemini 对齐这套成熟行为，并额外要求
识别"你已让系统停止"这类停止消息、绝不把它当成有效回复返回。
"""
import threading

import gemini_client as gc
from gemini_client import GeminiClient, GeminiError


_now = [1000.0]


class _Loc:
    def __init__(self, count=0, visible=False, text=""):
        self._count, self._visible, self._text = count, visible, text

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def is_visible(self):
        return self._visible

    def inner_text(self):
        return self._text


class _BasePage:
    """假 page 基类：wait_for_timeout 推进假时钟，记录 reload 次数。"""
    def __init__(self, alive=True):
        self.reloads = 0
        self.closed = False
        self._alive = alive

    def reload(self, **k):
        self.reloads += 1

    def wait_for_timeout(self, ms):
        _now[0] += ms / 1000.0

    def evaluate(self, *a, **k):
        if not self._alive:
            raise RuntimeError("target closed")
        return False   # aria-busy 查询默认 False（思考期无 aria-busy 也不该被刷新掐断）

    def close(self):
        self.closed = True

    def goto(self, *a, **k):
        pass


def _client():
    c = GeminiClient(log=lambda *a, **k: None)
    c.cancel = None
    c.nudge = None
    return c


class _ThinkingThenReplyPage(_BasePage):
    """页面活着，但 Gemini Pro 长时间"思考"：前 thinking_ticks 拍没有回复容器、
    不流式、无 aria-busy；之后出现一条稳定的正常回复。模拟真实思考期。"""
    def __init__(self, thinking_ticks, reply_text):
        super().__init__(alive=True)
        self.thinking_ticks = thinking_ticks
        self.reply_text = reply_text
        self.ticks = 0

    def wait_for_timeout(self, ms):
        super().wait_for_timeout(ms)
        self.ticks += 1

    def locator(self, sel):
        if self.ticks < self.thinking_ticks:
            return _Loc(count=0, visible=False, text="")     # 思考期：容器未出现
        return _Loc(count=1, visible=False, text=self.reply_text)  # 回复已完成、稳定


def test_director_text_does_not_reload_live_page_while_thinking(monkeypatch):
    """核心回归：文本导演在**活着**的页面思考期，绝不能自动刷新（刷新=掐断=你已让系统停止）。
    思考 thinking_ticks 拍（远超 RELOAD_INTERVAL）后正常出回复 → 应返回该回复且 reloads==0。"""
    monkeypatch.setattr(gc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    page = _ThinkingThenReplyPage(thinking_ticks=int(GeminiClient.RELOAD_INTERVAL) + 40,
                                  reply_text="<理解>看懂了</理解><英文提示词>a full english paragraph</英文提示词>")
    client = _client()
    client._wait_reply_done(page, before_count=0, timeout=100000, expect_image=False)
    assert page.reloads == 0, f"活着的页面思考期被刷新了 {page.reloads} 次——会掐断生成"


class _StopMessagePage(_BasePage):
    """回复容器已出现，但内容是 Gemini 的停止消息、且不流式。"""
    def locator(self, sel):
        return _Loc(count=1, visible=False, text="Gemini 说\n你已让系统停止这条回答")


def test_director_text_raises_on_stop_message_never_returns_it(monkeypatch):
    """回复是"你已让系统停止这条回答"这类停止消息时，绝不当作有效回复返回，
    而是抛 GeminiError 让 send() 自愈重试（否则上层拿到停止消息→解析空→报错）。"""
    import pytest
    monkeypatch.setattr(gc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    with pytest.raises(GeminiError):
        _client()._wait_reply_done(_StopMessagePage(), before_count=0, timeout=30, expect_image=False)


class _EmptyReplyPage(_BasePage):
    """容器出现但文字始终为空、不流式——绝不返回空串（上层会当成"提示词缺失"）。"""
    def locator(self, sel):
        return _Loc(count=1, visible=False, text="")


def test_director_text_never_returns_empty(monkeypatch):
    monkeypatch.setattr(gc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    import pytest
    with pytest.raises(GeminiError):
        _client()._wait_reply_done(_EmptyReplyPage(), before_count=0, timeout=30, expect_image=False)


def test_looks_stopped_detects_gemini_stop_messages():
    c = _client()
    assert c._looks_stopped("Gemini 说\n你已让系统停止这条回答") is True
    assert c._looks_stopped("你已停止生成") is True
    assert c._looks_stopped("You stopped this response") is True
    assert c._looks_stopped("这是一段正常的分析：形体一致，光影自然。") is False
    assert c._looks_stopped("") is False


class _DeadThenReloadDeadPage(_BasePage):
    """一直死（evaluate 抛错）：文本路径应有界地刷新/升级并最终抛错，绝不无限刷或干等到超时。"""
    def __init__(self):
        super().__init__(alive=False)

    def locator(self, sel):
        return _Loc(count=0, visible=False, text="")


def test_dead_page_text_is_bounded_and_raises(monkeypatch):
    """死页面：文本路径必须有界收敛（抛 GeminiError），不无限刷新、不磨到大超时。"""
    import pytest
    monkeypatch.setattr(gc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    page = _DeadThenReloadDeadPage()
    with pytest.raises(GeminiError):
        _client()._wait_reply_done(page, before_count=0, timeout=100000, expect_image=False)
    assert page.reloads <= GeminiClient.AUTO_RELOAD_CAP + 1, \
        f"死页面刷新次数应有界(<= AUTO_RELOAD_CAP)，实际 {page.reloads}"
