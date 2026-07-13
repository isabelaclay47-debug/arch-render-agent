# -*- coding: utf-8 -*-
"""ChatGPT + Gemini 两个 client 共享同一个 sync_playwright（同一线程只能有一个实例）。
复现并防回归：用户报的「Playwright Sync API inside the asyncio loop」——根因是
两个 client 各自 sync_playwright().start()，同线程双实例冲突。"""
import pytest

import chatgpt_client
import gemini_client


class _FakePW:
    """假 playwright：connect_over_cdp 到此为止，证明用了传入的共享 pw、没起第二个。"""
    def __init__(self):
        self.stopped = False

    class chromium:  # noqa: N801
        @staticmethod
        def connect_over_cdp(url):
            raise RuntimeError("reached-connect_over_cdp")

    def stop(self):
        self.stopped = True


def test_gemini_connect_reuses_shared_pw_and_never_starts_second(monkeypatch):
    started = {"v": False}

    def _boom():
        started["v"] = True
        raise AssertionError("绝不能在共享 pw 时再起第二个 sync_playwright")

    monkeypatch.setattr(gemini_client, "sync_playwright", _boom)
    c = gemini_client.GeminiClient(model=None, log=lambda *a: None)
    with pytest.raises(RuntimeError, match="reached-connect_over_cdp"):
        c.connect(pw=_FakePW())         # 传入共享 pw
    assert started["v"] is False        # 没有第二次 start → 不会撞 asyncio loop
    assert c._owns_pw is False          # 共享者不拥有 pw


def test_chatgpt_connect_reuses_shared_pw_and_never_starts_second(monkeypatch):
    started = {"v": False}

    def _boom():
        started["v"] = True
        raise AssertionError("绝不能在共享 pw 时再起第二个 sync_playwright")

    monkeypatch.setattr(chatgpt_client, "sync_playwright", _boom)
    c = chatgpt_client.ChatGPTClient(log=lambda *a: None)
    with pytest.raises(RuntimeError, match="reached-connect_over_cdp"):
        c.connect(director_only=True, pw=_FakePW())
    assert started["v"] is False
    assert c._owns_pw is False


@pytest.mark.parametrize("mod,cls", [(gemini_client, "GeminiClient"),
                                     (chatgpt_client, "ChatGPTClient")])
def test_close_only_stops_pw_it_owns(mod, cls):
    c = getattr(mod, cls)(log=lambda *a: None)
    pw = _FakePW()
    c._pw = pw
    c._owns_pw = False        # 共用的 pw
    c.close()
    assert pw.stopped is False   # 不能关掉别人的 pw（否则连累另一个 client）
    c._owns_pw = True
    c.close()
    assert pw.stopped is True     # 自己拥有的才关
