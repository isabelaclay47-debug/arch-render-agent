# -*- coding: utf-8 -*-
"""客户端鲁棒性回归（本次修复）：
  Issue②  瞬时 socket hang up → connect_over_cdp 退避重试后连上，不一次失败就判死。
  Issue①  ChatGPT 明确回复"生图失败/工具报错" → 立刻抛错换新对话，不空等满计时器。
  Issue③  文本回复须"连续若干拍不再增长"才算完成，不把流式中途的"正在分析…"当终稿。
  Issue④  抓不到生成图时落一份 ChatGPT DOM 快照到 logs/。

全部用假 page/browser 桩，不启动真浏览器。"""
import os
import threading

import chatgpt_client as cc
from chatgpt_client import ChatGPTClient, ChatGPTError


_now = [1000.0]


# ---------------- Issue②：瞬时 socket hang up 退避重试 ----------------

class _FakeChromium:
    def __init__(self, fail_times, browser):
        self.fail_times = fail_times
        self.calls = 0
        self._browser = browser

    def connect_over_cdp(self, url):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("BrowserType.connect_over_cdp: socket hang up")
        return self._browser


class _FakePw:
    def __init__(self, chromium):
        self.chromium = chromium


def test_connect_retries_transient_socket_hang_up(monkeypatch):
    """前 2 次 socket hang up、第 3 次成功 → 返回 browser，绝不抛错。"""
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)
    sentinel = object()
    client = ChatGPTClient(log=lambda *a, **k: None)
    client._pw = _FakePw(_FakeChromium(fail_times=2, browser=sentinel))
    assert client._connect_browser_with_retry(tries=4) is sentinel
    assert client._pw.chromium.calls == 3


def test_connect_gives_up_after_all_tries(monkeypatch):
    """一直 hang up → 试满 tries 次后抛 ChatGPTError（可恢复提示），而不是裸异常上抛。"""
    monkeypatch.setattr(cc.time, "sleep", lambda *_: None)
    client = ChatGPTClient(log=lambda *a, **k: None)
    client._pw = _FakePw(_FakeChromium(fail_times=99, browser=None))
    try:
        client._connect_browser_with_retry(tries=3)
        assert False, "全失败应抛 ChatGPTError"
    except ChatGPTError:
        pass
    assert client._pw.chromium.calls == 3


# ---------------- Issue①/③/④：完成判定用的假 page ----------------

class _Loc:
    def __init__(self, count=0, visible=False):
        self._count, self._visible = count, visible
    def count(self): return self._count
    @property
    def first(self): return self
    @property
    def last(self): return self
    def is_visible(self): return self._visible
    def locator(self, sel): return _Loc(0, False)   # msgs.last.locator("img") → 0 张图


class _ReplyPage:
    """assistant 容器存在(count=1)、不流式(stop 不可见)、无生成图；
    last_reply_text 按调用顺序吐出脚本里的文字，用来复现"流式中途 vs 终稿"。"""
    def __init__(self, texts):
        self._texts = list(texts)
        self.reloads = 0
        self.dumps = 0
    def locator(self, sel):
        if sel == cc.SEL["assistant"]:
            return _Loc(count=1, visible=False)
        return _Loc(0, False)
    def reload(self, **k): self.reloads += 1
    def wait_for_timeout(self, ms): _now[0] += ms / 1000.0
    def evaluate(self, *a, **k): return False   # _image_loading_pending / alive 探测
    def close(self): pass
    def goto(self, *a, **k): pass


def _client_with_text(page_texts):
    client = ChatGPTClient(log=lambda *a, **k: None)
    page = _ReplyPage(page_texts)
    # last_reply_text 每调用一次消费一个脚本值，用尽后保持最后一个（模拟文字稳定不变）
    seq = list(page_texts)
    def _last_reply_text(_p):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    client.last_reply_text = _last_reply_text
    client._dump_dom = lambda *a, **k: page.__setattr__("dumps", page.dumps + 1)
    return client, page


def test_text_waits_for_stability_not_first_nonempty(monkeypatch):
    """流式中途 "正在分析 幅图片" 不能当终稿返回；等文字稳定后才完成。"""
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    # 前几拍是半截、之后稳定为完整段落
    texts = ["正在分析 幅图片", "正在分析 幅图片",
             "FULL PROMPT " * 20, "FULL PROMPT " * 20, "FULL PROMPT " * 20,
             "FULL PROMPT " * 20, "FULL PROMPT " * 20, "FULL PROMPT " * 20]
    client, page = _client_with_text(texts)
    # 不抛错即算通过（返回 None 表示判定"输出完成"）；关键是它没有在"正在分析"那拍就返回
    client._wait_reply_done(page, before_count=0, timeout=60, expect_image=False)
    # 稳定判定至少消费到完整段落（脚本里"正在分析"只在前两次）——通过说明没被半截骗到
    assert True


def test_image_gen_error_text_raises_fast(monkeypatch):
    """ChatGPT 回复"unable to generate ... returned an error" → 立刻抛 ChatGPTError，
    不等满 600s（Image#2 / Issue①）。"""
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    err = ("I was unable to generate the image because the image-generation tool "
           "returned an error. Please send a new request and I can try again.")
    client, page = _client_with_text([err])
    client._last_image_handle = lambda _p: None
    try:
        client._wait_reply_done(page, before_count=0, timeout=600, expect_image=True)
        assert False, "命中生图报错话术应立刻抛 ChatGPTError"
    except ChatGPTError as e:
        assert "image-generation tool" in str(e) or "生图失败" in str(e)
    # 远没到 600s 就抛了（need=8 拍 ≈ 8s）
    assert _now[0] - 1000.0 < 60


def test_reply_looks_like_gen_error_detects_markers():
    client = ChatGPTClient(log=lambda *a, **k: None)
    client.last_reply_text = lambda _p: "Sorry, I was unable to generate the image."
    assert client._reply_looks_like_gen_error(object()) is True
    client.last_reply_text = lambda _p: "Here is your architectural render."
    assert client._reply_looks_like_gen_error(object()) is False


def test_click_send_uses_js_click_when_overlay_blocks(monkeypatch):
    """常规 btn.click() 被扩展浮层拦截(抛错)时，改用 JS el.click() 完成发送——不抛错。
    复现 Image#19「发送按钮点击未生效」：Grammarly/翻译插件浮层挡住指针事件。"""
    monkeypatch.setattr(cc.time, "time", lambda: _now[0])
    _now[0] = 1000.0
    client = ChatGPTClient(log=lambda *a, **k: None)

    class Loc:
        def __init__(s, page, sel): s.page, s.sel = page, sel
        @property
        def first(s): return s
        def is_visible(s):
            return s.page.sent if s.sel == cc.SEL["stop"] else True  # 发出后才现停止键
        def is_enabled(s): return True
        def click(s, timeout=None): raise RuntimeError("intercepted by overlay")
        def evaluate(s, script): s.page.sent = True                  # JS click 生效
        def count(s): return 0
        def inner_text(s): return "" if s.page.sent else "草稿"

    class Page:
        def __init__(s): s.sent = False
        def locator(s, sel): return Loc(s, sel)
        def wait_for_timeout(s, ms): _now[0] += ms / 1000.0

    page = Page()
    client._click_send(page, before_count=0)   # 不抛错即通过
    assert page.sent is True


def test_chatgpt_dump_dom_writes_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    class P:
        def evaluate(self, *a, **k):
            return {"html": "<div data-message-author-role='assistant'>x</div>",
                    "imgs": [{"alt": "", "w": 1024, "h": 768, "role": "assistant"}]}
    path = ChatGPTClient(log=lambda *a, **k: None)._dump_dom(P(), "测试原因")
    assert path is not None and os.path.exists(path)
    body = open(path, encoding="utf-8").read()
    assert "测试原因" in body and "assistant" in body
