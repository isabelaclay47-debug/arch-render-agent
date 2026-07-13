# -*- coding: utf-8 -*-
"""本地模型下载的健壮性：进度实时刷新（\\r 断行）、Windows 隐藏黑窗、版本标记回显。
对应用户报的「下载卡死在一个黑终端、不知道下没下」。"""
import io
import os

import app as appmod


def test_iter_progress_splits_on_carriage_return():
    # ollama pull 的进度用 \r 覆盖刷新同一行、不换行——必须按 \r 断，才能实时看到进度
    stream = io.StringIO("pulling manifest\rdownloading  10%\rdownloading  55%\rdownloading 100%\nsuccess\n")
    out = list(appmod._iter_progress(stream))
    assert out == ["pulling manifest", "downloading  10%", "downloading  55%",
                   "downloading 100%", "success"]


def test_iter_progress_skips_blank_fragments():
    stream = io.StringIO("\r\r  \nreal\r\n")
    assert list(appmod._iter_progress(stream)) == ["real"]


def test_no_window_kwargs_hides_console_on_windows_only():
    kw = appmod._no_window_kwargs()
    if os.name == "nt":
        assert kw.get("creationflags") == 0x08000000   # CREATE_NO_WINDOW，抑制黑终端
    else:
        assert kw == {}


def test_status_exposes_build_marker():
    appmod.app.config["TESTING"] = True
    data = appmod.app.test_client().get("/api/status").get_json()
    assert data.get("build")                      # 版本标记必须回显，供确认重启是否生效
    assert data["build"].startswith("v")
