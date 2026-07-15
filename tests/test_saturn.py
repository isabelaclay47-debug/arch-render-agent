"""土星通讯（VPN）一键安装：端点行为。

绝不触发真实下载/安装——用 monkeypatch 替掉。URL 未配置时安装按钮不出、install 返回 400；
配置后 install 起后台线程并返回 ok。后端判定当前系统、只下发对应平台。"""

import app as app_module


def _client():
    return app_module.app.test_client()


def test_current_os_is_one_of_three():
    assert app_module._current_os() in {"windows", "mac", "linux"}


def test_saturn_status_shape():
    j = _client().get("/api/saturn_status").get_json()
    assert j["ok"] is True
    assert j["os"] in {"windows", "mac", "linux"}
    assert j["name"] == "土星通讯"
    assert isinstance(j["configured"], bool)
    assert "setup" in j


def test_install_unconfigured_returns_400(monkeypatch):
    monkeypatch.setattr(app_module, "SATURN_INSTALLERS",
                        {"windows": "", "mac": "", "linux": ""})
    r = _client().post("/api/saturn_install")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_status_reports_configured_when_url_set(monkeypatch):
    os_key = app_module._current_os()
    monkeypatch.setattr(app_module, "SATURN_INSTALLERS",
                        {"windows": "", "mac": "", "linux": "", os_key: "https://example.test/x.exe"})
    j = _client().get("/api/saturn_status").get_json()
    assert j["configured"] is True


def test_install_configured_starts_without_real_download(monkeypatch):
    os_key = app_module._current_os()
    monkeypatch.setattr(app_module, "SATURN_INSTALLERS",
                        {"windows": "", "mac": "", "linux": "", os_key: "https://example.test/x.exe"})
    # 关键：替掉真正的下载/安装线程体，测试绝不联网、绝不运行安装程序
    monkeypatch.setattr(app_module, "_run_saturn_install", lambda url: None)
    r = _client().post("/api/saturn_install")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
