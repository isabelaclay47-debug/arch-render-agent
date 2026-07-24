# -*- coding: utf-8 -*-
"""Gemini 导演空回复根因回归（Image#4）：Gemini 的发送键与停止键是**同一个按钮**
（SEL['send'] 含 .send-button-container button；生成时该按钮原地变「停止」）。
_click_send 旧实现常规 click 发出去后、还没确认提交，就**立刻 JS 二次点击同一个按钮**——
此刻它已是停止键 → 把刚发起的生成掐断 → 回复为空、页面显示「你已让系统停止这条回答」。

本测试用假 page 复现"二次点击"：只要发送发生后又点了一次按钮，就记为把生成停掉。
修好后 _click_send 必须**只点一次**、靠确认窗口等提交生效，绝不二次点同一个按钮。"""
import gemini_client as gc
from gemini_client import GeminiClient


class _FakeBtn:
    def __init__(self, page):
        self.page = page

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def click(self, timeout=None):
        self.page._register_click()

    def evaluate(self, _js):
        self.page._register_click()   # JS click 也算一次真实点击


class _FakeLoc:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return _FakeBtn(self.page) if self.kind == "send" else self

    def is_visible(self):          # 停止键可见性
        return self.page._sent_ready()

    def count(self):               # 助手回复数（一直 0，逼流程靠别的信号判提交）
        return 0

    def click(self, *a, **k):      # 输入框 click（回车兜底用）
        pass

    def inner_text(self):          # 输入框文本：提交后清空
        return "" if self.page._sent_ready() else "some english prompt paragraph"


class _FakeKeyboard:
    def press(self, *a, **k):
        pass


class _FakePage:
    """按钮点击驱动的状态机：首击=发送；发送后若再点一次=点到停止键=掐断生成。
    _sent_ready() 需要在首击后至少走一个 wait_for_timeout「tick」才为真——
    这正是旧代码抢跑（首击后 tick 之前就二次点击）的时间窗。"""
    def __init__(self):
        self.clicks = 0
        self.ticks = 0
        self._first_click_tick = None
        self.keyboard = _FakeKeyboard()

    def _register_click(self):
        self.clicks += 1
        if self._first_click_tick is None:
            self._first_click_tick = self.ticks

    def _sent_ready(self):
        return self._first_click_tick is not None and self.ticks > self._first_click_tick

    def locator(self, sel):
        if "发送" in sel or "send" in sel.lower():
            return _FakeLoc(self, "send")
        if "停止" in sel or "stop" in sel.lower():
            return _FakeLoc(self, "stop")
        if "contenteditable" in sel or "editor" in sel:
            return _FakeLoc(self, "editor")
        return _FakeLoc(self, "assistant")

    def wait_for_timeout(self, _ms):
        self.ticks += 1


def _new_client():
    c = GeminiClient(log=lambda *a, **k: None)
    c.cancel = None
    c.nudge = None
    return c


def test_click_send_does_not_double_click_into_stop():
    """发送只应发生一次：靠确认窗口等提交生效，绝不二次点同一个按钮把生成掐断。"""
    page = _FakePage()
    client = _new_client()
    client._click_send(page, before_count=0)
    assert page.clicks == 1, f"发送键被点了 {page.clicks} 次——二次点击会点到停止键掐断生成"
