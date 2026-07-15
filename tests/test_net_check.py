"""VPN 安全版：网络自检端点 /api/net_check 的行为。

只探测 TCP 连通性、绝不分发/配置 VPN（合规红线）。测试用 monkeypatch 替掉真实 socket
探测，既快又不依赖外网。"""

import app as app_module


def _client():
    return app_module.app.test_client()


def test_reachable_when_all_hosts_connect(monkeypatch):
    monkeypatch.setattr(app_module, "_host_reachable", lambda host, *a, **k: True)
    monkeypatch.setattr(app_module, "get_image_engine", lambda: "chatgpt")
    r = _client().get("/api/net_check")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["reachable"] is True
    assert j["unreachable"] == []
    assert j["hosts"] == {"chatgpt.com": True}


def test_unreachable_lists_the_failing_host(monkeypatch):
    monkeypatch.setattr(app_module, "_host_reachable",
                        lambda host, *a, **k: host != "chatgpt.com")
    monkeypatch.setattr(app_module, "get_image_engine", lambda: "chatgpt")
    j = _client().get("/api/net_check").get_json()
    assert j["reachable"] is False
    assert j["unreachable"] == ["chatgpt.com"]


def test_gemini_engine_also_requires_google(monkeypatch):
    monkeypatch.setattr(app_module, "_host_reachable", lambda host, *a, **k: True)
    monkeypatch.setattr(app_module, "get_image_engine", lambda: "gemini")
    j = _client().get("/api/net_check").get_json()
    assert set(j["hosts"]) == {"gemini.google.com", "chatgpt.com"}
    assert j["reachable"] is True


def test_target_chatgpt_overrides_render_engine(monkeypatch):
    # 助手页 chat 模式：即便主页渲染引擎是 gemini，target=chatgpt 也只探 chatgpt.com
    monkeypatch.setattr(app_module, "_host_reachable", lambda host, *a, **k: True)
    monkeypatch.setattr(app_module, "get_image_engine", lambda: "gemini")
    j = _client().get("/api/net_check?target=chatgpt").get_json()
    assert set(j["hosts"]) == {"chatgpt.com"}


def test_probe_never_raises_on_bad_host(monkeypatch):
    # 真实探测：不可解析的主机必须优雅返回 False，不抛异常
    assert app_module._host_reachable("nonexistent.invalid", timeout=1) is False
