# -*- coding: utf-8 -*-
"""附件抢跑回归（Image#3）：ChatGPT 乐观 UI——文件还在上传、发送键就已可用，
导致 send() 在附件飞行途中就把消息发了，ChatGPT 丢附件后反过来索要图片：
    "Please upload the original 1528 × 1029 base image and the reference image..."
这条是一条**正常完成**的回复，过去被当成功文本返回，浪费一整轮。

本测试锁两件事：
  1) _reply_looks_like_missing_upload 能识别"对方在索要图片"的话术；
  2) 带图 send() 命中该话术时抛可重试错→走自愈重挂图重发，最终返回真回复，
     而不是把"请上传图片"当成功返回。

全部用假 page/桩，不启动真浏览器。"""
import chatgpt_client as cc
from chatgpt_client import ChatGPTClient, ChatGPTError


# ---- 真实 dump 里出现过的三段"索要图片"话术（logs/chatgpt_dump_20260723_*.html）----
DUMP_PHRASES = [
    "Please upload the two images in this chat—the original 1528 × 1029 base and "
    "the reference image—so I can edit the correct source.",
    "Please upload the original 1528 × 1029 base image and the reference image in "
    "this conversation. I cannot perform or verify exact binary-mask compositing, "
    "protected-pixel identity, or return the unchanged base without access to the "
    "original raster, so I will not generate an approximate replacement.",
    "请先上传原图和参考图，我这边没有收到图片。",
]

NORMAL_REPLIES = [
    "好的，我看到了两张图：一张 1528×1029 的底图和一张参考图。现在开始分析。",
    "I can see both images. Let me plan the regional edit now.",
]


def test_matcher_flags_missing_upload_phrases():
    client = ChatGPTClient(log=lambda *a, **k: None)
    for p in DUMP_PHRASES:
        assert client._reply_looks_like_missing_upload(p), f"应判定为索要图片：{p[:40]}"


def test_matcher_ignores_normal_replies():
    client = ChatGPTClient(log=lambda *a, **k: None)
    for p in NORMAL_REPLIES:
        assert not client._reply_looks_like_missing_upload(p), f"误报：{p[:40]}"


# ---------------- 集成：带图 send() 命中索要图片 → 自愈重试 ----------------

class _FakeLocator:
    def __init__(self, count=0):
        self._count = count

    def count(self):
        return self._count

    def click(self, *a, **k):
        pass


class _FakeKeyboard:
    def insert_text(self, *a, **k):
        pass


class _FakePage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()

    def locator(self, *_a, **_k):
        return _FakeLocator(0)

    def wait_for_timeout(self, *_a, **_k):
        pass


def test_send_retries_when_reply_demands_upload(monkeypatch):
    """第一轮附件抢跑→回复索要图片；第二轮重挂图后拿到正常回复。
    send() 必须走自愈重试、返回正常回复，且重新调用了 _attach_files。"""
    page = _FakePage()
    client = ChatGPTClient(log=lambda *a, **k: None)
    client.gen_page = None
    client.director_page = page

    attach_calls = {"n": 0}
    recover_calls = {"n": 0}
    replies = iter([DUMP_PHRASES[1], NORMAL_REPLIES[0]])

    client._raise_if_cancelled = lambda: None
    client._current_page = lambda role: page
    client._attach_files = lambda p, paths: attach_calls.__setitem__("n", attach_calls["n"] + 1)
    client._click_send = lambda p, before: None
    client._wait_reply_done = lambda *a, **k: None
    client.last_reply_text = lambda p: next(replies)
    client._recover_before_retry = lambda *a, **k: recover_calls.__setitem__("n", recover_calls["n"] + 1)

    out = client.send(page, "分析这两张图", image_paths=["/tmp/base.png", "/tmp/ref.png"])

    assert out == NORMAL_REPLIES[0], "应返回重试后的正常回复，而非索要图片话术"
    assert attach_calls["n"] == 2, "两轮都应重新挂图"
    assert recover_calls["n"] == 1, "第一轮命中索要图片应触发一次自愈"


def test_send_returns_normal_reply_without_retry(monkeypatch):
    """正常一次成功：不重试、不自愈、直接返回。"""
    page = _FakePage()
    client = ChatGPTClient(log=lambda *a, **k: None)
    client.gen_page = None
    client.director_page = page

    attach_calls = {"n": 0}
    recover_calls = {"n": 0}

    client._raise_if_cancelled = lambda: None
    client._current_page = lambda role: page
    client._attach_files = lambda p, paths: attach_calls.__setitem__("n", attach_calls["n"] + 1)
    client._click_send = lambda p, before: None
    client._wait_reply_done = lambda *a, **k: None
    client.last_reply_text = lambda p: NORMAL_REPLIES[1]
    client._recover_before_retry = lambda *a, **k: recover_calls.__setitem__("n", recover_calls["n"] + 1)

    out = client.send(page, "分析", image_paths=["/tmp/base.png"])

    assert out == NORMAL_REPLIES[1]
    assert attach_calls["n"] == 1
    assert recover_calls["n"] == 0
