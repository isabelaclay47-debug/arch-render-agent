# -*- coding: utf-8 -*-
"""打发布包：把仓库里**被 git 跟踪的文件**（干净，不含 venv/models/缓存/登录态）打成
各平台 zip，放到 dist/。每个包顶层放一个平台专属「先看我」说明，让非技术用户一眼知道
双击哪个文件。模型（超分/去水印/本地识图）不进包——首次使用时自动按需下载（免 VPN 源）。

用法：
    python scripts/make_release.py            # 生成 Windows 与 Mac 两个 zip
    python scripts/make_release.py --platform windows
"""
import os
import subprocess
import sys
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(APP_DIR, "dist")


def _version() -> str:
    try:
        with open(os.path.join(APP_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def _tracked_files() -> list:
    """git 跟踪的文件列表（-z 防中文/空格名出错）。只打包这些，天然排除 venv/models/缓存。"""
    out = subprocess.run(["git", "-C", APP_DIR, "ls-files", "-z"],
                         capture_output=True)
    names = out.stdout.decode("utf-8", "replace").split("\0")
    return [n for n in names if n]


# 每平台顶层「先看我」——非技术用户照着做即可
START_HERE = {
    "windows": ("① 先看我-Windows.txt",
                "建筑渲染智能体 — Windows 使用说明\r\n"
                "========================================\r\n\r\n"
                "第一次使用：\r\n"
                "  1. 确保已装 Google Chrome（没有就先去 google.com/chrome 装）。\r\n"
                "  2. 双击『双击启动.bat』。首次会自动装好运行环境（1-3 分钟），\r\n"
                "     并弹出一次询问：要不要装『本地画质增强/去水印』可选组件（可选，只问这一次）。\r\n"
                "  3. 会自动打开一个专用 Chrome，请在里面登录 chatgpt.com（或 gemini.google.com），\r\n"
                "     登录后别关那个窗口。\r\n"
                "  4. 浏览器会自动打开 http://127.0.0.1:5001 —— 就能用了。\r\n\r\n"
                "以后每次：直接双击『双击启动.bat』即可（不会再问可选组件）。\r\n"
                "彻底停止：双击『停止服务.bat』。\r\n"
                "出问题看：logs\\app.log。\r\n\r\n"
                "没有账号/VPN？在页面里把引擎切到『本地大模型』，用本机离线识图，免账号免 VPN。\r\n"),
    "mac": ("① 先看我-Mac.txt",
            "建筑渲染智能体 — macOS 使用说明\n"
            "========================================\n\n"
            "第一次使用：\n"
            "  1. 确保已装 Google Chrome。\n"
            "  2. 双击『双击启动-Mac.command』。首次会自动装好运行环境（1-3 分钟），\n"
            "     并问一次要不要装『本地画质增强/去水印』可选组件（可选，只问这一次）。\n"
            "     （若提示“无法打开，因为来自身份不明的开发者”：右键→打开，或到\n"
            "      系统设置→隐私与安全性→仍要打开。）\n"
            "  3. 会打开一个专用 Chrome，请登录 chatgpt.com（或 gemini.google.com），别关那窗口。\n"
            "  4. 浏览器自动打开 http://127.0.0.1:5001 —— 就能用了。\n\n"
            "以后每次：直接双击『双击启动-Mac.command』即可。\n"
            "彻底停止：双击『停止服务-Mac.command』。\n"
            "出问题看：logs/app.log。\n\n"
            "没有账号/VPN？页面里把引擎切到『本地大模型』，本机离线识图，免账号免 VPN。\n"),
}


def build(platform: str, files: list, version: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    zip_path = os.path.join(DIST, f"ArchRenderAgent-{platform}-{version}.zip")
    top = f"ArchRenderAgent-{version}"        # 解压后顶层文件夹，避免解压一堆散文件
    fname, ftext = START_HERE[platform]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 「先看我」排在最前
        z.writestr(f"{top}/{fname}", ftext.encode("utf-8"))
        for rel in files:
            src = os.path.join(APP_DIR, rel)
            if os.path.isfile(src):
                z.write(src, f"{top}/{rel}")
    return zip_path


def main() -> int:
    argv = sys.argv[1:]
    version = _version()
    files = _tracked_files()
    if not files:
        print("[错误] 没拿到 git 跟踪文件列表——确认在仓库内且已 git add。")
        return 1
    plats = ["windows", "mac"]
    if "--platform" in argv:
        plats = [argv[argv.index("--platform") + 1]]
    for p in plats:
        path = build(p, files, version)
        size_mb = os.path.getsize(path) / 1024 / 1024
        print(f"✓ {p}: {path}  ({size_mb:.1f} MB, {len(files)} 文件)")
    print("完成。模型不在包内，用户首次用超分/去水印/本地识图时自动下载（免 VPN 源）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
