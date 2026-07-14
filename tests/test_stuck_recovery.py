# -*- coding: utf-8 -*-
"""#5 卡死关页重开 + 反无限刷新兜底。

不启动真浏览器：用假 page/context 驱动，验证三件事——
  1. _wait_reply_done 对坏死标签"就地刷新至多 AUTO_RELOAD_CAP 次"就抛错，绝不无限刷；
  2. _recover_before_retry 在 attempt>=2 时升级到「关掉所有页重开」；
  3. close_all_and_reopen_gen 真的关掉所有旧页并重开干净页。
"""
import threading

import chatgpt_client as cc
from chatgpt_client import ChatGPTClient, ChatGPTError, GenCancelled


# 共享假时钟：假 page 的 wait_for_timeout 推进它，monkeypatch time.time 读它
_now = [1000.0]


class FakeLocator:
    def __init__(self, count=0, visible=False):
        self._count, self._visible = count, visible

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    def is_visible(self):
        return self._visible


class FakePage:
    """一个永远不出回复、也不流式的坏死标签。"""
    def __init__(self, alive=True):
        self.reloads = 0
        self.closed = False
        self._alive = alive

    def locator(self, sel):
        return FakeLocator(0, False)   # assistant=0、stop 不可见 → 卡死

    def reload(self, **k):
        self.reloads += 1

    def wait_for_timeout(self, ms):
        _now[0] += ms / 1000.0

    def evaluate(self, *a, **k):
        if not self._alive:
            raise RuntimeError("target closed")
        return 1

    def close(self):
        self.closed = True

    def goto(self, *a, **k):
        pass


def test_wait_reply_stops_after_reload_cap(monkeypatch):
    """坏死标签：就地刷新恰好 AUTO_RELOAD_CAP 次后抛 ChatGPTError，而非磨到 600s 或无限刷。"""
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    client = ChatGPTClient(log=lambda *a, **k: None)
    page = FakePage()
    try:
        # 大 timeout：若逻辑退化成"磨到超时"，reloads 会远超 CAP；正确逻辑应尽早抛错
        client._wait_reply_done(page, before_count=0, timeout=100000, expect_image=False)
        assert False, "坏死标签应当抛 ChatGPTError，不能干等/无限刷"
    except ChatGPTError:
        pass
    assert page.reloads == ChatGPTClient.AUTO_RELOAD_CAP, \
        f"应恰好就地刷新 {ChatGPTClient.AUTO_RELOAD_CAP} 次就升级，实际刷了 {page.reloads} 次"


def test_recover_escalates_to_close_all(monkeypatch):
    """gen 角色：attempt 1 换新标签；attempt>=2 升级为关掉所有页重开(#5)。"""
    client = ChatGPTClient(log=lambda *a, **k: None)
    calls = []
    client.new_generation_chat = lambda: calls.append("new_chat")
    client.close_all_and_reopen_gen = lambda: calls.append("close_all")
    client.gen_page = FakePage()
    client.director_page = FakePage()
    client._recover_before_retry("gen", attempt=1, max_attempts=3, expect_image=True)
    client._recover_before_retry("gen", attempt=2, max_attempts=3, expect_image=True)
    assert calls == ["new_chat", "close_all"]


def test_close_all_and_reopen_gen_closes_every_page():
    """关掉上下文里所有旧页，重开全新的导演页 + 生图页。"""
    client = ChatGPTClient(log=lambda *a, **k: None)
    old1, old2, old3 = FakePage(), FakePage(), FakePage()
    fresh = [FakePage(), FakePage()]

    class FakeCtx:
        pages = [old1, old2, old3]

        def new_page(self):
            return fresh.pop(0)

    client._ctx = FakeCtx()
    client._director_only = False
    client._open_chat = lambda p: None
    client.close_all_and_reopen_gen()

    assert old1.closed and old2.closed and old3.closed, "所有旧页都应被关闭"
    assert client.director_page not in (old1, old2, old3)
    assert client.gen_page not in (old1, old2, old3)
    assert client.director_page is not client.gen_page


# ---------------- #6b 提前结束：协作式取消，立即中止不重试 ----------------

def test_wait_reply_cancels_immediately(monkeypatch):
    """cancel 事件置位 → _wait_reply_done 立刻抛 GenCancelled，一次刷新都不做。"""
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    cancel = threading.Event()
    cancel.set()
    client = ChatGPTClient(log=lambda *a, **k: None, cancel=cancel)
    page = FakePage()
    try:
        client._wait_reply_done(page, before_count=0, timeout=600, expect_image=True)
        assert False, "cancel 置位时应立即抛 GenCancelled"
    except GenCancelled:
        pass
    assert page.reloads == 0, "提前结束应立即中止，不该再刷新页面"


def test_send_does_not_retry_on_cancel():
    """cancel 置位时 send 直接抛 GenCancelled（而非降级成 GenStalledError 或触发自愈重试）。"""
    cancel = threading.Event()
    cancel.set()
    client = ChatGPTClient(log=lambda *a, **k: None, cancel=cancel)
    client.gen_page = FakePage()
    client.director_page = FakePage()
    recovered = []
    client._recover_before_retry = lambda *a, **k: recovered.append(1)
    try:
        client.send(client.gen_page, "画一张图", expect_image=True)
        assert False, "cancel 置位时 send 应抛 GenCancelled"
    except GenCancelled:
        pass
    assert recovered == [], "提前结束不应触发任何自愈重试"


# ---------------- Image#9：导演空回复绝不返回空串 ----------------

class _MsgLoc:
    def __init__(self, count, text="", visible=False):
        self._count, self._text, self._visible = count, text, visible
    def count(self): return self._count
    @property
    def first(self): return self
    @property
    def last(self): return self
    def is_visible(self): return self._visible
    def inner_text(self): return self._text


class EmptyReplyPage:
    """助手容器已出现(count=1)但文字始终为空、且不流式——复现导演首轮空回复竞态。"""
    def __init__(self):
        self.reloads = 0
        self.closed = False
    def locator(self, sel):
        if sel == cc.SEL["assistant"]:
            return _MsgLoc(count=1, text="", visible=False)   # 容器在、文字空
        return _MsgLoc(count=0, text="", visible=False)       # stop 不可见=不流式
    def reload(self, **k): self.reloads += 1
    def wait_for_timeout(self, ms): _now[0] += ms / 1000.0
    def evaluate(self, *a, **k): return 1
    def close(self): self.closed = True
    def goto(self, *a, **k): pass


def test_wait_reply_never_returns_empty_text(monkeypatch):
    """文本回复容器出现但文字为空时，绝不返回空串（会害上层判成"英文提示词缺失"），
    而是抛 ChatGPTError 让 send 自愈重试。"""
    import pytest
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    client = ChatGPTClient(log=lambda *a, **k: None)
    with pytest.raises(ChatGPTError):
        client._wait_reply_done(EmptyReplyPage(), before_count=0, timeout=30, expect_image=False)
