# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 规格：把「建筑渲染智能体」打成各平台原生可执行（onedir，一个含 exe 的文件夹）。
#
# 关键简化：本 app **只通过 CDP 接管用户已装的 Chrome**（chatgpt_client/gemini_client 全程
# connect_over_cdp，从不 .launch()），所以**无需**打包 Playwright 的 chromium 浏览器
# （那是几百 MB、最难搞的部分）——只需带上 Playwright 的驱动即可跑 CDP。
# 首次用到的超分/去水印模型仍按需下载到 exe 同级目录（app.py 冻结态把可写数据放 exe 旁）。
#
# 用法：pyinstaller ArchRenderAgent.spec  → dist/ArchRenderAgent/（含可执行文件）。
# 这份 spec 跨平台通用：在 Windows 出 .exe、macOS 出可执行、Linux 出 ELF。
from PyInstaller.utils.hooks import collect_all

# 收集 Playwright 的数据/二进制/隐藏依赖（含 node 驱动）——CDP 客户端必需。
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=pw_binaries,
    # templates/ 与 static/ 打进包内（app.py 冻结态从 sys._MEIPASS 读它们）。
    datas=[("templates", "templates"), ("static", "static")] + pw_datas,
    # 本地模块 app.py 已直接 import，PyInstaller 一般能自动发现；显式列出更稳。
    # 不列 image_enhance：它依赖可选的 numpy/cv2/onnxruntime，属按需，缺了要优雅跳过。
    hiddenimports=["prompt_engine", "chatgpt_client", "gemini_client"] + pw_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ArchRenderAgent",
    console=True,          # 保留控制台窗口：本地服务日志可见，出问题好排查
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ArchRenderAgent",
)
