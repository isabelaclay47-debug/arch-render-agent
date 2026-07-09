# -*- coding: utf-8 -*-
"""免 VPN 在线更新：镜像源优先级 / 逐源回退 / 代理注入 / 全失败时的友好提示与落盘。
全程 monkeypatch，不走真实网络。"""
import app as appmod


# ---- 源优先级：Gitee → ghproxy(套 GitHub 原址) → 直连 origin ----
def test_git_sources_order_without_gitee(monkeypatch):
    monkeypatch.setattr(appmod, "GITEE_REMOTE", "")
    monkeypatch.setattr(appmod, "GHPROXY_PREFIXES", ("https://p1/", "https://p2/"))
    monkeypatch.setattr(appmod, "_origin_url",
                        lambda: "https://github.com/u/arch-render-agent.git")
    labels = [lbl for lbl, _ in appmod._git_sources()]
    urls = [u for _, u in appmod._git_sources()]
    assert labels == ["ghproxy", "ghproxy", "直连 GitHub"]
    assert urls[0] == "https://p1/https://github.com/u/arch-render-agent.git"
    assert urls[-1] == "https://github.com/u/arch-render-agent.git"   # 直连垫底


def test_git_sources_gitee_first_when_configured(monkeypatch):
    monkeypatch.setattr(appmod, "GITEE_REMOTE", "https://gitee.com/u/arch-render-agent.git")
    monkeypatch.setattr(appmod, "_origin_url",
                        lambda: "https://github.com/u/arch-render-agent.git")
    srcs = appmod._git_sources()
    assert srcs[0] == ("Gitee 镜像", "https://gitee.com/u/arch-render-agent.git")


def test_git_sources_empty_when_no_origin(monkeypatch):
    monkeypatch.setattr(appmod, "GITEE_REMOTE", "")
    monkeypatch.setattr(appmod, "_origin_url", lambda: "")
    assert appmod._git_sources() == []


# ---- 逐源回退：第一个源失败自动换下一个，直到成功 ----
def test_git_net_falls_back_to_next_source(monkeypatch):
    monkeypatch.setattr(appmod, "_git_sources",
                        lambda: [("A", "urlA"), ("B", "urlB")])
    seen = []

    def fake_git(args, timeout=60):
        seen.append(args)
        # 第一个源(urlA)失败，第二个源(urlB)成功
        return (0, "") if "urlB" in args else (128, "could not resolve host")

    monkeypatch.setattr(appmod, "_git", fake_git)
    code, out, label = appmod._git_net(["fetch", "__URL__", "main"])
    assert code == 0 and label == "B"
    assert seen[0][1] == "urlA" and seen[1][1] == "urlB"   # __URL__ 被替换


def test_git_net_all_fail_reports_last(monkeypatch):
    monkeypatch.setattr(appmod, "_git_sources", lambda: [("A", "urlA")])
    monkeypatch.setattr(appmod, "_git", lambda args, timeout=60: (128, "boom"))
    code, out, label = appmod._git_net(["fetch", "__URL__", "main"])
    assert code != 0 and label == "" and "boom" in out


def test_git_net_no_sources(monkeypatch):
    monkeypatch.setattr(appmod, "_git_sources", lambda: [])
    code, out, label = appmod._git_net(["fetch", "__URL__", "main"])
    assert code != 0 and "origin" in out


# ---- 代理注入：git/ollama 子进程也能走系统代理 ----
def test_proxy_env_keeps_existing(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://existing:1")
    env = appmod._proxy_env()
    assert env["HTTPS_PROXY"] == "http://existing:1"   # 已有的不覆盖


def test_proxy_env_injects_system_proxy(monkeypatch):
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    import urllib.request
    monkeypatch.setattr(urllib.request, "getproxies",
                        lambda: {"https": "http://sys:8", "http": "http://sys:8"})
    env = appmod._proxy_env()
    assert env["HTTPS_PROXY"] == "http://sys:8"
    assert env["HTTP_PROXY"] == "http://sys:8"


# ---- 全失败时：友好提示 + 落盘，不再是裸 git 输出 ----
def test_update_check_all_sources_fail_is_friendly_and_logged(tmp_path, monkeypatch):
    appmod.app.config["TESTING"] = True
    c = appmod.app.test_client()
    monkeypatch.setattr(appmod, "_update_branch", lambda: ("main", 0, ""))
    monkeypatch.setattr(appmod, "_git_net",
                        lambda args, timeout=60: (1, "[直连 GitHub] could not resolve host", ""))
    logged = {}
    monkeypatch.setattr(appmod, "_net_log", lambda m: logged.setdefault("m", m))
    j = c.get("/api/update_check").get_json()
    assert j["ok"] is False
    assert "镜像" in j["msg"] and "logs/app.log" in j["msg"]   # 友好、指向日志
    assert "could not resolve host" in logged["m"]             # 详情落盘可回溯


# ==== Part B：本地模型免 VPN（ModelScope 优先 → 官方源兜底） ====
def test_pull_model_prefers_modelscope(monkeypatch):
    monkeypatch.setattr(appmod, "MODELSCOPE_SOURCES",
                        {"moondream": "modelscope.cn/ggml-org/moondream2-20250414-GGUF"})
    calls = []
    monkeypatch.setattr(appmod, "_run_pull",
                        lambda exe, ref: (calls.append(ref) or (0, "success")))
    monkeypatch.setattr(appmod, "_vlog", lambda m: None)
    appmod._pull_model("ollama", "moondream")
    assert calls == ["modelscope.cn/ggml-org/moondream2-20250414-GGUF"]   # 只用了魔搭，没碰官方


def test_pull_model_falls_back_to_official(monkeypatch):
    monkeypatch.setattr(appmod, "MODELSCOPE_SOURCES", {"moondream": "modelscope.cn/x/moondream"})
    calls = []

    def fake_pull(exe, ref):
        calls.append(ref)
        return (0, "ok") if ref == "moondream" else (1, "connection refused")

    monkeypatch.setattr(appmod, "_run_pull", fake_pull)
    monkeypatch.setattr(appmod, "_vlog", lambda m: None)
    appmod._pull_model("ollama", "moondream")
    assert calls == ["modelscope.cn/x/moondream", "moondream"]   # 魔搭失败 → 退回官方名


def test_pull_model_raises_when_all_fail(monkeypatch):
    monkeypatch.setattr(appmod, "MODELSCOPE_SOURCES", {"moondream": "modelscope.cn/x/moondream"})
    monkeypatch.setattr(appmod, "_run_pull", lambda exe, ref: (1, "network down"))
    monkeypatch.setattr(appmod, "_vlog", lambda m: None)
    import pytest
    with pytest.raises(RuntimeError, match="都没成功"):
        appmod._pull_model("ollama", "moondream")


def test_installer_urls_prefer_domestic_mirror():
    urls = appmod.OLLAMA_INSTALLER_URLS_WIN
    assert "github.com" in urls[0]        # 首选国内可达的 ghproxy 镜像
    assert urls[-1] == "https://ollama.com/download/OllamaSetup.exe"   # 直连垫底


def test_modelscope_sources_cover_all_choices():
    # 每个可选模型都要有对应的免 VPN 魔搭源，否则无 VPN 用户拉不到
    for name in appmod.OLLAMA_MODEL_CHOICES:
        assert name in appmod.MODELSCOPE_SOURCES
