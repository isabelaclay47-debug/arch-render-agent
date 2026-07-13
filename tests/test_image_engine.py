# -*- coding: utf-8 -*-
"""生图引擎切换（ChatGPT / Gemini nano-banana）的选择与守卫逻辑。"""
import app as appmod


def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_default_engine_is_chatgpt():
    appmod.set_image_engine("chatgpt")
    assert appmod.get_image_engine() == "chatgpt"


def test_set_engine_gemini_and_back():
    try:
        assert appmod.set_image_engine("gemini") == "gemini"
        assert appmod.get_image_engine() == "gemini"
    finally:
        appmod.set_image_engine("chatgpt")


def test_gemini_model_is_configurable_and_exposed_in_status():
    old = appmod.get_gemini_model()
    try:
        assert appmod.set_gemini_model("3.5 Flash") == "3.5 Flash"
        data = client().get("/api/status").get_json()
        assert data["gemini_model"] == "3.5 Flash"
    finally:
        appmod.set_gemini_model(old)


def test_set_engine_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        appmod.set_image_engine("midjourney")


def test_status_exposes_engine():
    appmod.set_image_engine("chatgpt")
    r = client().get("/api/status")
    assert r.status_code == 200
    assert r.get_json()["image_engine"] == "chatgpt"


def test_set_engine_endpoint_when_idle():
    appmod.S["state"] = "idle"
    try:
        r = client().post("/api/set_engine", json={"engine": "gemini"})
        assert r.status_code == 200 and r.get_json()["engine"] == "gemini"
        assert client().get("/api/status").get_json()["image_engine"] == "gemini"
    finally:
        appmod.set_image_engine("chatgpt")


def test_set_engine_blocked_while_running():
    appmod.S["state"] = "running"
    try:
        r = client().post("/api/set_engine", json={"engine": "gemini"})
        assert r.status_code == 400
        assert appmod.get_image_engine() == "chatgpt"   # 没被改动
    finally:
        appmod.S["state"] = "idle"


def test_gemini_client_shares_stalled_error():
    # Gemini 生图卡死必须命中 app.py 的 except GenStalledError（否则会话会被误判结束）
    import gemini_client
    from chatgpt_client import GenStalledError
    assert gemini_client.GenStalledError is GenStalledError


def test_login_targets_follow_engine():
    # ChatGPT 引擎只查 ChatGPT；Gemini 引擎要查 Gemini(出图)＋ChatGPT(导演)，且 Gemini 在前
    appmod.set_image_engine("chatgpt")
    t = appmod._login_targets()
    assert [x[0] for x in t] == ["ChatGPT"]
    try:
        appmod.set_image_engine("gemini")
        t = appmod._login_targets()
        assert [x[0] for x in t] == ["Gemini", "ChatGPT"]
        assert "gemini.google.com" in t[0][2]        # 启动时先弹 Gemini 让用户登
    finally:
        appmod.set_image_engine("chatgpt")


def test_set_gemini_model_rejects_unknown():
    import pytest
    with pytest.raises(ValueError):
        appmod.set_gemini_model("DALL-E 9")


def test_set_gemini_model_endpoint_blocked_while_running():
    appmod.S["state"] = "running"
    try:
        r = client().post("/api/set_gemini_model", json={"model": "3.1 Pro"})
        assert r.status_code == 400
    finally:
        appmod.S["state"] = "idle"


# ---- select_model best-effort：找不到选择器时不报错、只指示手动切 ----

class _FakeEl:
    def __init__(self, text="", found_item=False):
        self._text = text
        self.clicked = False
        self._found_item = found_item

    def inner_text(self):
        return self._text

    def click(self):
        self.clicked = True


class _FakePage:
    """驱动 select_model 的假页面：switcher=模型菜单入口元素或 None；
    item=菜单项元素或 None（query_selector 第二类调用返回它）。"""
    def __init__(self, switcher=None, item=None):
        self._switcher = switcher
        self._item = item
        self.escaped = False

    def query_selector(self, sel):
        if "model_switcher" in sel or "模型" in sel or "mode-switch" in sel or "logo-pill" in sel:
            return self._switcher
        return self._item      # 菜单项查询

    def wait_for_timeout(self, ms):
        pass

    class _KB:
        def __init__(self, page):
            self.page = page

        def press(self, key):
            self.page.escaped = True

    @property
    def keyboard(self):
        return _FakePage._KB(self)


def _gc(model):
    import gemini_client
    logs = []
    c = gemini_client.GeminiClient(log=lambda m: logs.append(m), model=model)
    return c, logs


def test_select_model_noop_when_unset():
    c, logs = _gc(None)
    assert c.select_model(_FakePage()) is True   # 未指定模型 → 直接放行


def test_select_model_missing_switcher_instructs_manual():
    c, logs = _gc("3.1 Pro")
    ok = c.select_model(_FakePage(switcher=None))
    assert ok is False                           # 找不到入口 → 不崩、返回 False
    assert any("手动" in m for m in logs)         # 明确指示用户手动切，不是摆设


def test_select_model_clicks_matching_menu_item():
    c, logs = _gc("3.1 Pro")
    switcher = _FakeEl(text="3.5 Flash")   # 当前是别的模型
    item = _FakeEl(text="3.1 Pro")
    ok = c.select_model(_FakePage(switcher=switcher, item=item))
    assert ok is True and item.clicked and switcher.clicked


def test_select_model_already_selected_skips():
    c, logs = _gc("3.1 Pro")
    switcher = _FakeEl(text="3.1 Pro")     # 入口文本已含目标模型
    ok = c.select_model(_FakePage(switcher=switcher, item=None))
    assert ok is True and switcher.clicked is False   # 已是目标 → 不点
