"""Gemini 抓图鲁棒性（Image#5 假死修复）：图还在加载时不误判假死；抓不到图时落盘快照。

真机 Gemini 页面无法在 CI 里跑，用假 page 桩验证新逻辑的行为契约。"""

import os

from gemini_client import GeminiClient


class FakePage:
    def __init__(self, result=None, raise_=False):
        self._result = result
        self._raise = raise_
        self.reloaded = False

    def evaluate(self, script, *a, **k):
        if self._raise:
            raise RuntimeError("boom")
        return self._result


def _client():
    return GeminiClient(log=lambda *a, **k: None)


def test_image_pending_true_when_img_still_loading():
    assert _client()._image_loading_pending(FakePage(True)) is True


def test_image_pending_false_when_nothing_loading():
    assert _client()._image_loading_pending(FakePage(False)) is False


def test_image_pending_false_on_evaluate_error():
    # evaluate 抛错也必须优雅返回 False，绝不让探测本身把生成流程带崩
    assert _client()._image_loading_pending(FakePage(raise_=True)) is False


def test_dump_dom_writes_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    page = FakePage({"html": "<model-response>x</model-response>",
                     "imgs": [{"alt": "AI 生成", "w": 1024, "h": 768}]})
    path = _client()._dump_dom(page, "测试原因")
    assert path is not None
    assert os.path.exists(path)
    body = open(path, encoding="utf-8").read()
    assert "测试原因" in body
    assert "model-response" in body
    assert "AI 生成" in body


def test_dump_dom_returns_none_on_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _client()._dump_dom(FakePage(raise_=True), "x") is None


def test_download_blob_image_via_inpage(tmp_path):
    """真机根因回归：Gemini 生成图 src 是 blob:https://gemini.google.com/…。
    blob 不能走 page.request.get，必须走页内 fetch/canvas；能落盘且不误触 request。"""
    import base64
    big = b"\x89PNG\r\n" + b"x" * 20000   # >10000 字节，过阈值
    data_url = "data:image/png;base64," + base64.b64encode(big).decode()

    class Handle:
        def evaluate(self, script, *a, **k):
            # 取 src 的那次返回 blob URL；取字节的那次（脚本含 canvas 兜底）返回 data URL
            return data_url if "canvas" in script else "blob:https://gemini.google.com/abc"

    class Req:
        def get(self, *a, **k):
            raise AssertionError("blob src 绝不该走 page.request.get")

    class Page:
        request = Req()
        url = "https://gemini.google.com/app"

    c = _client()
    c._last_image_handle = lambda _p: Handle()
    out = tmp_path / "o.png"
    assert c.download_last_image(Page(), str(out)) is True
    assert out.read_bytes() == big


def test_fetch_http_image_uses_request_with_referer():
    """http(s) 生成图仍走 Playwright request 并带 referer（绕 CORS/画布污染）。"""
    class Resp:
        ok = True
        def body(self): return b"y" * 30000
    seen = {}
    class Req:
        def get(self, src, headers=None):
            seen["headers"] = headers or {}
            return Resp()
    class Page:
        request = Req()
        url = "https://gemini.google.com/app"
    raw = _client()._fetch_image_bytes(Page(), object(), "https://lh3.googleusercontent.com/x")
    assert raw == b"y" * 30000
    assert "referer" in seen["headers"]


def test_chatgpt_image_pending_same_race_guard():
    # ChatGPT 引擎有同一加载竞态，护栏行为须一致：图在解码→True；无图→False；出错→False
    from chatgpt_client import ChatGPTClient
    c = ChatGPTClient(log=lambda *a, **k: None)
    assert c._image_loading_pending(FakePage(True)) is True
    assert c._image_loading_pending(FakePage(False)) is False
    assert c._image_loading_pending(FakePage(raise_=True)) is False
