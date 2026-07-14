# -*- coding: utf-8 -*-
"""发布打包 + 首次安装向导（可选组件首次问、之后不问）。"""
import importlib.util
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wizard_remembers_choice_and_stops_asking():
    w = _load("setup_wizard")
    # 已记住 optional=True → 不管有没有 TTY，都直接返回记住的选择（不再询问）
    assert w._decide_optional({"optional": True}, []) is True
    assert w._decide_optional({"optional": False}, []) is False


def test_wizard_cli_flags_override():
    w = _load("setup_wizard")
    assert w._decide_optional({}, ["--yes"]) is True
    assert w._decide_optional({}, ["--core-only"]) is False


def test_make_release_builds_zip_with_start_here():
    m = _load("make_release")
    files = m._tracked_files()
    assert "app.py" in files and "requirements-core.txt" in files
    out = m.build("windows", files, "test")
    try:
        assert os.path.isfile(out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            assert any("先看我-Windows.txt" in n for n in names)   # 平台说明在包里
            assert any(n.endswith("/app.py") for n in names)        # 源码在包里
            assert not any("/.git/" in n for n in names)            # 不打包 .git
    finally:
        if os.path.isfile(out):
            os.remove(out)
