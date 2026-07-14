# -*- coding: utf-8 -*-
"""首次安装向导：核心依赖必装；可选组件（本地画质增强/去水印）**首次询问一次**，
把选择记进 .setup_state.json，**之后自动应用、不再问**——对应用户诉求「装插件第一次问、
之后不问」。跨平台、纯 Python、UTF-8 安全（一键启动脚本调用它，避免在 .bat/.command 里
写脆弱的交互逻辑）。

用法：
    python scripts/setup_wizard.py            # 首次会问一次可选组件；之后按记录自动装
    python scripts/setup_wizard.py --yes      # 非交互：可选组件也装（无人值守/CI）
    python scripts/setup_wizard.py --core-only # 只装核心，忽略可选（也会记住）
"""
import json
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(APP_DIR, ".setup_state.json")
CORE_REQ = os.path.join(APP_DIR, "requirements-core.txt")
OPTIONAL_REQ = os.path.join(APP_DIR, "requirements-optional.txt")


def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _pip_install(req_file: str) -> bool:
    if not os.path.isfile(req_file):
        return False
    print(f"安装依赖：{os.path.basename(req_file)} …")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", req_file])
    return r.returncode == 0


def _decide_optional(state: dict, argv) -> bool:
    """决定是否安装可选组件。返回 True=装。
    优先级：命令行开关 > 已记住的选择 > 首次交互询问（无 TTY 则默认不装、但仍记住）。"""
    if "--yes" in argv:
        return True
    if "--core-only" in argv:
        return False
    if "optional" in state:            # 已问过 → 直接用记住的选择，不再打扰
        return bool(state["optional"])
    # 首次：交互询问一次
    if sys.stdin and sys.stdin.isatty():
        try:
            ans = input(
                "是否安装【本地画质增强 / 去水印】可选组件？（约几百 MB，离线、可选；\n"
                "  不装也不影响出图，只是没有本地超分/去水印。只问这一次）[y/N] ").strip().lower()
            return ans in ("y", "yes", "是")
        except EOFError:
            return False
    return False                        # 无交互环境：首次默认不装，但下面会记住这个决定


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    state = _load_state()

    # 1) 核心依赖：每次都确保就位
    if not _pip_install(CORE_REQ):
        print("[警告] 核心依赖安装未成功，请检查网络后重试。")
        return 1

    # 2) 可选组件：首次问一次并记住，之后按记录自动执行、不再问
    want_optional = _decide_optional(state, argv)
    first_time = "optional" not in state
    state["optional"] = want_optional
    _save_state(state)                  # 记住选择——关键：以后不再询问

    if want_optional:
        ok = _pip_install(OPTIONAL_REQ)
        print("可选组件已安装。" if ok else "[提示] 可选组件安装未完全成功，主流程不受影响。")
    else:
        msg = "（本次跳过可选组件" + ("，已记住选择，以后不再询问" if first_time else "") + "）"
        print(msg + " 想以后安装：删掉 .setup_state.json 再启动，或 pip install -r requirements-optional.txt")
    print("环境准备完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
