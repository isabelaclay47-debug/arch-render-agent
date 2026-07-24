# -*- coding: utf-8 -*-
"""
建筑渲染智能体 — 本地网页服务

流程：需求+原图(+意向图) → 导演对话扩写全面提示词 → ChatGPT 生图
     → 与原图对比查篡改 → 自动修订提示词 → 每 5 轮暂停等建筑师点评
     → 点评期可在图上圈选区域做局部修改（只改圈内，不动周边）
     → 点"满意"后最终图输出到桌面。
"""
import base64
import json
import os
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
import threading
import time
from datetime import datetime

import requests
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from PIL import Image

import prompt_engine as pe
from chatgpt_client import (CDP_PORT, ChatGPTClient, ChatGPTError,
                            GenStalledError, GenCancelled)
from gemini_client import GeminiClient, GeminiError

try:
    import winreg
except ImportError:
    winreg = None

# ---- Windows GBK 崩溃根治 ----
# 本进程由 supervisor 以子进程拉起，stdout 被重定向到 logs\app.log。子进程会按
# Windows 系统 locale（双击启动.bat 里 chcp 936 = GBK/cp936）自己决定 stdout 编码，
# supervisor 那侧的 encoding=utf-8 传不进来。于是日志里的 ⚠🔍 等字符一 print 就抛
# UnicodeEncodeError('gbk' codec can't encode character '⚠')，而 log() 在生成
# 循环里被调用 → 整轮生图被当成「未预期的错误」失败。强制本进程走 UTF-8 根治。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 资源/数据目录解析——同时兼容「源码直接跑」与「PyInstaller 打包后的原生 exe」。
# · 非冻结（源码/一键脚本）：APP_DIR=RES_DIR=本文件所在目录（与历史行为完全一致）。
# · 冻结（原生安装包）：可写数据(workspace 等)放 exe 同级目录（持久，_MEIPASS 退出即删不能放这）；
#   只读打包资源(templates/static)在解包临时目录 sys._MEIPASS。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))   # 可写、持久
    RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)                  # 只读打包资源
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = APP_DIR
WORKSPACE = os.path.join(APP_DIR, "workspace")
os.makedirs(WORKSPACE, exist_ok=True)


def _no_window_kwargs() -> dict:
    """Windows 上给子进程加 CREATE_NO_WINDOW，隐藏那个会弹出来的黑色控制台窗口。
    从无控制台的 GUI/pythonw 进程里 spawn 控制台程序（ollama.exe、git.exe）时，
    Windows 默认会弹一个空白黑框（stdout 被 PIPE 走→黑的），吓人且看着像卡死。"""
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def _app_build() -> str:
    """运行中这份代码的版本标记：VERSION + git 短 hash + 提交时间。
    专治「改完必须重启 Windows 服务、但没法确认现在跑的到底是不是新码」——
    界面会显示它，重启后对一眼版本号即知新旧（此坑反复让'修了却像没修'）。"""
    try:
        with open(os.path.join(APP_DIR, "VERSION"), encoding="utf-8") as f:
            ver = f.read().strip()
    except OSError:
        ver = "?"
    commit, when = "", ""
    try:
        out = subprocess.run(
            ["git", "-C", APP_DIR, "log", "-1", "--format=%h",
             "--date=format:%m-%d %H:%M"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace", **_no_window_kwargs())
        if out.returncode == 0:
            commit = (out.stdout or "").strip().split("\n")[0].strip()
        out2 = subprocess.run(
            ["git", "-C", APP_DIR, "log", "-1", "--date=format:%m-%d %H:%M",
             "--format=%cd"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace", **_no_window_kwargs())
        if out2.returncode == 0:
            when = (out2.stdout or "").strip().split("\n")[0].strip()
    except Exception:
        pass
    tag = f"v{ver}"
    if commit:
        tag += f" · {commit}"
    if when:
        tag += f" · {when}"
    return tag


APP_BUILD = _app_build()

# 每几张图暂停一次等建筑师点评：由界面传入，默认 1（出一张就停，最省额度）
DEFAULT_REVIEW_EVERY = 1

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CHROME_PROFILE = os.path.join(APP_DIR, "chrome-profile")

app = Flask(__name__,
            template_folder=os.path.join(RES_DIR, "templates"),
            static_folder=os.path.join(RES_DIR, "static"))

# ---------------- 会话状态（单会话即可） ----------------
S = {
    # idle/connecting/running/waiting_confirm/waiting_clarification/
    #   waiting_feedback/editing/done/error
    "state": "idle",
    "session_id": None,
    "iteration": 0,
    "items": [],              # [{iter, image, kind, analysis, verdict, prompt}]
    "logs": [],
    "questions": "",          # AI 反问建筑师的问题（waiting_clarification 时非空）
    "understanding": "",      # AI 对需求的中文讲解（waiting_confirm 时非空）
    "prompt_zh": "",          # 供建筑师阅读/编辑的中文提示词（waiting_confirm 时非空）
    "error": "",
    "final_path": "",
    "final_enhanced": None,    # 完成时最终图的增强信息 {url, from, to, quality}，供页面展示增强版大图
}
_lock = threading.Lock()
_feedback_event = threading.Event()
# type: continue(带点评继续) / satisfied(满意结束) / edit(局部修改)
_feedback = {"type": "continue", "text": "", "edit": None}
_confirm_event = threading.Event()
# action: confirm(就用这份去生图) / adjust(让AI按我的修改再调整一版)
_confirm = {"action": "confirm", "edited_zh": "", "note": ""}
_finish_now = threading.Event()
_nudge = threading.Event()  # 人工干预：让正在等待的浏览器操作立刻刷新重查

# 生图引擎：chatgpt(默认) 或 gemini（网页驱动 gemini.google.com 的 nano-banana）。
# 只切「生图/局部改图」这只手；理解/扩写提示词/查篡改等文本推理始终走 ChatGPT 导演对话。
_ENGINES = ("chatgpt", "gemini")
_image_engine = os.environ.get("ARA_IMAGE_ENGINE", "chatgpt").strip().lower()
if _image_engine not in _ENGINES:
    _image_engine = "chatgpt"


def get_image_engine() -> str:
    with _lock:
        return _image_engine


def set_image_engine(name: str) -> str:
    global _image_engine
    name = str(name or "").strip().lower()
    if name not in _ENGINES:
        raise ValueError(f"未知生图引擎：{name}（可选 {'/'.join(_ENGINES)}）")
    with _lock:
        _image_engine = name
    return name


# Gemini 生图模型（引擎=gemini 时才用）。用户在 gemini.google.com 有多个模型可选，
# 图像生成默认走 nano-banana=「Gemini 2.5 Flash Image」。选中的模型会在开对话后由
# GeminiClient.select_model() 尝试在网页上切换；DOM 变动/找不到时优雅指示用户手动切。
# 网页版 Gemini 实际模型名（2026-07 真机截图校准；随 Google 改版可能再变）。
# 出图（nano-banana）跑在 Flash 上，「3.5 Flash」是默认且全能项 → 出图就用它。
_GEMINI_MODELS = (
    "3.5 Flash",       # 全方位帮助，默认；出图就用它（推荐）
    "3.1 Flash-Lite",  # 极速回答
    "3.1 Pro",         # 高等数学与代码（推理向，出图弱）
)
_gemini_model = os.environ.get("ARA_GEMINI_MODEL", _GEMINI_MODELS[0]).strip()


def _canon_gemini_model(m: str):
    """大小写/空白无关地匹配到 _GEMINI_MODELS 里的规范写法；匹配不到返回 None。"""
    key = str(m or "").strip().lower()
    for name in _GEMINI_MODELS:
        if name.lower() == key:
            return name
    return None


if _canon_gemini_model(_gemini_model) is None:
    _gemini_model = _GEMINI_MODELS[0]
else:
    _gemini_model = _canon_gemini_model(_gemini_model)


def get_gemini_model() -> str:
    with _lock:
        return _gemini_model


def set_gemini_model(m: str) -> str:
    global _gemini_model
    canon = _canon_gemini_model(m)
    if canon is None:
        raise ValueError(f"未知 Gemini 模型：{m}（可选 {' / '.join(_GEMINI_MODELS)}）")
    with _lock:
        _gemini_model = canon
    return canon


# Gemini 分工（仅引擎=gemini 时有意义）——**默认且唯一对用户呈现的行为是「全包」**，界面不再给开关：
#   True（默认）＝Gemini 全包：选 Gemini 就**只启动 Gemini**，它既做文字推理（理解/提示词/
#     查篡改/翻译）又生图，只需登录 gemini.google.com，全程不碰 ChatGPT。
#   False＝Gemini 只生图、仍连 ChatGPT 当导演（旧行为）——保留为**隐藏兜底**，仅供
#     环境变量 ARA_GEMINI_SELFRUN=0 或调试用，普通用户无从触及。
def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y")


_gemini_selfrun = _truthy(os.environ.get("ARA_GEMINI_SELFRUN", "1"))


def get_gemini_selfrun() -> bool:
    with _lock:
        return _gemini_selfrun


def set_gemini_selfrun(on) -> bool:
    global _gemini_selfrun
    with _lock:
        _gemini_selfrun = _truthy(on)
        return _gemini_selfrun


# 画质档位（需求：本地 AI 超分到 1K/2K/4K/8K；gemini 引擎顺带去水印）。默认 1k=原生不放大。
_QUALITIES = ("1k", "2k", "4k", "8k")
_quality = os.environ.get("ARA_QUALITY", "1k").strip().lower()
if _quality not in _QUALITIES:
    _quality = "1k"


def get_quality() -> str:
    with _lock:
        return _quality


def set_quality(q: str) -> str:
    global _quality
    q = str(q or "").strip().lower()
    if q not in _QUALITIES:
        raise ValueError(f"未知画质：{q}（可选 {'/'.join(_QUALITIES)}）")
    with _lock:
        _quality = q
    return q


def _maybe_enhance(path: str):
    """对刚落盘的成图按当前画质档位做本地超分（gemini 引擎时顺带去水印）。
    1k 原生 + 非 gemini 时零开销直接返回；缺依赖/模型时优雅跳过，绝不影响出图。
    惰性 import image_enhance——缺 onnxruntime/opencv 也不能让整个 app 起不来。"""
    dewm = (get_image_engine() == "gemini")
    q = get_quality()
    if q == "1k" and not dewm:
        return
    try:
        import image_enhance
    except Exception as e:
        log(f"⚠ 画质增强不可用（缺依赖：{e}），已跳过，出图不受影响。")
        return
    try:
        log(f"本地画质增强中（{q.upper()}{'＋去水印' if dewm else ''}）…高档位需数分钟，请稍候。")
        r = image_enhance.enhance_file(path, quality=q, dewatermark_wm=dewm, log=log)
        if r.get("upscaled_to"):
            log(f"画质增强完成 → {r['upscaled_to']}")
        for s in r.get("skipped", []):
            log(f"（画质增强跳过：{s}）")
    except Exception as e:
        log(f"⚠ 画质增强出错，已保留原图：{e}")


def _dewatermark_inplace(path: str):
    """Gemini 引擎：把刚落盘的**过程图**就地去掉 nano-banana 水印(✦)，让 UI 全程看到的
    都是干净图。之前去水印只在最终交付时做，过程缩略图/圈选底图仍带 ✦，用户以为"去水印
    没开启"。非 gemini 或缺模型时零开销跳过；失败保留原图，绝不影响出图流程。"""
    if get_image_engine() != "gemini":
        return
    try:
        import image_enhance
    except Exception as e:
        log(f"⚠ 去水印不可用（缺依赖：{e}），已跳过。")
        return
    try:
        r = image_enhance.enhance_file(path, quality="1k", dewatermark_wm=True, log=log)
        if r.get("dewatermark"):
            log("已去除本轮生成图的 Gemini 水印。")
        for s in r.get("skipped", []):
            log(f"（去水印跳过：{s}）")
    except Exception as e:
        log(f"⚠ 去水印出错，已保留原图：{e}")


def _png_size(path):
    """快读 PNG 尺寸（W×H 字符串），失败返回空串。只读 24 字节，不解码整图。"""
    try:
        import struct
        with open(path, "rb") as f:
            f.read(16)
            w, h = struct.unpack(">II", f.read(8))
        return f"{w}×{h}"
    except Exception:
        return ""


def _enhance_to(src: str, dst: str, quality: str, dewm: bool, logfn=None):
    """把 src 复制到 dst 并**就地增强 dst**（按档位超分/去水印），原图 src 不动。
    返回 {from, to, skipped}。缺依赖/模型时优雅跳过（dst 保留为原图副本，仍可展示）。"""
    logfn = logfn or log
    result = {"from": _png_size(src), "to": "", "skipped": []}
    try:
        shutil.copyfile(src, dst)
    except OSError as e:
        result["skipped"].append(f"复制失败:{e}")
        return result
    try:
        import image_enhance
    except Exception as e:
        result["skipped"].append(f"缺依赖:{e}")
        return result
    r = image_enhance.enhance_file(dst, quality=quality, dewatermark_wm=dewm, log=logfn)
    if r.get("upscaled_to"):
        result["to"] = r["upscaled_to"].replace("x", "×")
    result["skipped"] += r.get("skipped", [])
    return result


def _deliver_final(sess_dir: str):
    """任务收尾：取最后一张成图 → 按当前画质档位增强一份到会话目录（页面可见）→
    再把增强版复制到桌面。state=done 并把增强信息写进 S，供完成卡在**页面上**展示大图。
    对应用户诉求：画质增强要在页面上真能看到，而不是只落一个桌面文件。"""
    if not S["items"]:
        raise ChatGPTError("任务结束时还没有任何生成图，无图可输出。")
    sess = os.path.basename(sess_dir.rstrip("/\\"))
    last = S["items"][-1]["image"]
    src = os.path.join(sess_dir, last)
    q = get_quality()
    dewm = (get_image_engine() == "gemini")
    enhanced = None
    deliver_src = src
    if q != "1k" or dewm:
        log(f"最终图按 {q.upper()} 画质本地增强中（高档位需数分钟）…")
        dst = os.path.join(sess_dir, f"final_{q}.png")
        info = _enhance_to(src, dst, q, dewm)
        if info.get("to") or (dewm and os.path.isfile(dst)):
            deliver_src = dst
            enhanced = {"url": f"/images/{sess}/final_{q}.png",
                        "from": info.get("from", ""), "to": info.get("to", ""),
                        "quality": q}
        for s in info.get("skipped", []):
            log(f"（画质增强跳过：{s}）")
    out = os.path.join(desktop_path(),
                       f"渲染结果_{datetime.now().strftime('%m%d_%H%M')}.png")
    shutil.copyfile(deliver_src, out)
    with _lock:
        S["state"] = "done"
        S["final_path"] = out
        S["final_enhanced"] = enhanced
    tail = f"（已超分 {enhanced['from']} → {enhanced['to']}）" if enhanced and enhanced.get("to") else ""
    log(f"完成！最终图已放到桌面：{out}{tail}")


# ---------------- 单张按需画质增强（页面上「提升并查看」）----------------
_enh_job = {"active": False, "done": False, "ok": False, "error": "",
            "url": "", "from": "", "to": "", "key": "", "log": []}
_enh_lock = threading.Lock()


def _enh_log(msg: str):
    with _enh_lock:
        _enh_job["log"].append(msg)
        _enh_job["log"][:] = _enh_job["log"][-20:]


def _run_enhance_job(src, dst, url, quality, dewm, key):
    try:
        info = _enhance_to(src, dst, quality, dewm, logfn=_enh_log)
        with _enh_lock:
            _enh_job.update({"active": False, "done": True, "ok": True, "url": url,
                             "from": info.get("from", ""), "to": info.get("to", ""),
                             "key": key})
    except Exception as e:
        with _enh_lock:
            _enh_job.update({"active": False, "done": True, "ok": False, "error": str(e)})


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _lock:
        S["logs"].append(line)
        S["logs"][:] = S["logs"][-200:]
    # 兜底：即使 stdout 编码异常也绝不让"打日志"这件小事崩掉生成流程。
    try:
        print(line)
    except Exception:
        try:
            sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
            sys.stdout.flush()
        except Exception:
            pass


def _wsl_windows_home() -> str:
    parts = os.path.normpath(APP_DIR).split(os.sep)
    if len(parts) >= 5 and parts[1:4] == ["mnt", "c", "Users"]:
        return os.path.join("/mnt/c/Users", parts[4])
    return ""


def _windows_to_wsl_path(path: str) -> str:
    if os.name == "nt" or len(path) < 3 or path[1:3] not in (":\\", ":/"):
        return path
    drive = path[0].lower()
    rest = path[3:].replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _wsl_to_windows_path(path: str) -> str:
    norm = path.replace("\\", "/")
    if os.name == "nt" or not norm.startswith("/mnt/") or len(norm) < 8:
        return path
    drive = norm[5].upper()
    if norm[6] != "/":
        return path
    return f"{drive}:\\" + norm[7:].replace("/", "\\")


def desktop_path() -> str:
    if winreg is not None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as k:
                val = winreg.QueryValueEx(k, "Desktop")[0]
            return os.path.expandvars(val)
        except OSError:
            pass

    candidates = []
    wsl_home = _wsl_windows_home()
    if wsl_home:
        candidates.append(os.path.join(wsl_home, "Desktop"))
    candidates.append(os.path.join(os.path.expanduser("~"), "Desktop"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    os.makedirs(candidates[0], exist_ok=True)
    return candidates[0]


def _local_get(url: str, timeout: int = 2):
    session = requests.Session()
    session.trust_env = False
    return session.get(url, timeout=timeout)


def _find_chrome() -> str:
    candidates = [os.path.expandvars(p) for p in CHROME_PATHS]
    if os.name != "nt":
        import shutil
        # 原生 macOS / Linux 的 Chrome/Chromium 位置——真机跑在 Mac/Linux 时靠这些，
        # 否则网页上「启动 Chrome 去登录」按钮(/api/launch_chrome)在非 Windows 上永远找不到 Chrome。
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
        for exe in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium", "chrome"):
            found = shutil.which(exe)
            if found:
                candidates.append(found)
        # 仅当确实在 WSL 里跑(能看到 /mnt/c)，才去 Windows 侧找 Chrome。
        wsl_home = _wsl_windows_home()
        if wsl_home or os.path.isdir("/mnt/c/Program Files"):
            candidates.extend([
                "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
                "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
            ])
            if wsl_home:
                candidates.append(os.path.join(
                    wsl_home, "AppData/Local/Google/Chrome/Application/chrome.exe"))

    seen = set()
    for path in candidates:
        check_path = _windows_to_wsl_path(path)
        if check_path in seen:
            continue
        seen.add(check_path)
        if os.path.isfile(check_path):
            return check_path
    return ""


def _chrome_profile_arg(chrome_path: str) -> str:
    if os.name != "nt" and chrome_path.startswith("/mnt/"):
        return _wsl_to_windows_path(CHROME_PROFILE)
    return CHROME_PROFILE


def ask_architect(questions: str) -> str:
    """把 AI 的反问抛给建筑师，阻塞等回答。提前结束时返回 None。"""
    with _lock:
        S["state"] = "waiting_clarification"
        S["questions"] = questions
    log("AI 对需求有疑问，先反问建筑师（不消耗生图额度）…")
    _feedback_event.wait()
    _feedback_event.clear()
    with _lock:
        S["questions"] = ""
    if _finish_now.is_set():
        return None
    return _feedback["text"]


def _optimize_image(img, dest_noext: str) -> str:
    """把一张 PIL 图压到长边≤2000px 的 JPEG。生图模型吃不下原始大图，
    且 Playwright 无法向 CDP 浏览器传输超过 50MB 的文件。"""
    img = img.convert("RGB")
    img.thumbnail((2000, 2000), Image.LANCZOS)
    out = dest_noext + ".jpg"
    img.save(out, "JPEG", quality=88)
    return out


def save_image_optimized(file_storage, dest_noext: str) -> str:
    """压缩上传图（来自表单文件）。"""
    return _optimize_image(Image.open(file_storage.stream), dest_noext)


def save_image_optimized_from_path(src_path: str, dest_noext: str) -> str:
    """压缩已存在的本地图（用于把历史成图当新底图）。"""
    return _optimize_image(Image.open(src_path), dest_noext)


def _safe_name(n) -> str:
    """把浏览器传来的单段名字消毒成安全的 workspace 子名：
    去目录、拒绝 . / .. / 空 / 下划线开头 / 含分隔符。非法返回空串。"""
    n = os.path.basename(str(n or ""))
    if not n or n in (".", "..") or n.startswith("_") or "/" in n or "\\" in n:
        return ""
    return n


def _within_workspace(path: str) -> bool:
    """确认解析后的真实路径仍落在 workspace 内（防残余穿越/符号链接）。"""
    try:
        root = os.path.realpath(WORKSPACE)
        return os.path.commonpath([root, os.path.realpath(path)]) == root
    except ValueError:
        return False


def _resolve_workspace_image(rel: str) -> str:
    """把浏览器传来的 "会话/图名" 安全地解析为 workspace 内的真实路径。
    只取两段 basename 拼进 WORKSPACE，并做 realpath 包含校验，杜绝 ../ 路径穿越；
    非法或不存在都返回空串。"""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if len(parts) < 2:
        return ""
    sess, name = os.path.basename(parts[-2]), os.path.basename(parts[-1])
    if sess in ("", ".", "..") or name in ("", ".", ".."):
        return ""
    path = os.path.join(WORKSPACE, sess, name)
    # 纵深防御：解析后的真实路径必须仍落在 workspace 内（防符号链接/残余穿越）
    try:
        root = os.path.realpath(WORKSPACE)
        if os.path.commonpath([root, os.path.realpath(path)]) != root:
            return ""
    except ValueError:  # 不同盘符等无法比较的情况
        return ""
    return path if os.path.isfile(path) else ""


def add_item(i, image, kind, analysis, verdict, prompt):
    with _lock:
        S["items"].append({"iter": i, "image": image, "kind": kind,
                           "analysis": analysis, "verdict": verdict, "prompt": prompt})


def _persist_item_prompt(sess_dir, image, prompt, analysis="", verdict="", kind="auto"):
    """把每张成图对应的提示词/篡改分析/结论持久化进 meta.json 的 items 映射，
    供「历史成图」逐图展示各自的详细提示词（会话结束后也不丢）。对应需求⑩。"""
    mp = os.path.join(sess_dir, "meta.json")
    meta = {}
    if os.path.isfile(mp):
        try:
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    items = meta.get("items")
    if not isinstance(items, dict):
        items = {}
    items[image] = {"prompt": prompt or "", "analysis": analysis or "",
                    "verdict": verdict or "", "kind": kind}
    meta["items"] = items
    try:
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError:
        pass


def _update_meta(sess_dir: str, **fields):
    """把若干字段并进会话 meta.json（历史列表要用：建筑师初始命令 + 最后一版提示词）。
    只写入非空字段，容忍文件缺失/损坏。对应需求②。"""
    mp = os.path.join(sess_dir, "meta.json")
    meta = {}
    if os.path.isfile(mp):
        try:
            with open(mp, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    meta.update({k: v for k, v in fields.items() if v})
    try:
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError:
        pass


# ---------------- 主循环线程 ----------------

def run_session(requirement: str, base_image: str, ref_images: list, sess_dir: str,
                quality: str, ratio: str, review_every: int = DEFAULT_REVIEW_EVERY,
                ref_roles: list = None):
    engine = get_image_engine()
    gemini_solo = (engine == "gemini" and get_gemini_selfrun())  # 选 Gemini 就只启动 Gemini
    client = None              # 导演（文字推理）client
    gen_client = None          # 生图专用 client；仅「借 ChatGPT 当导演」时与 client 分开
    try:
        with _lock:
            S["state"] = "connecting"
        log(f"正在连接 Chrome（调试端口 {CDP_PORT}）…")
        if gemini_solo:
            # 【Gemini 全包】只启动 Gemini：它既当导演（文字推理）又当画手（生图），只登录 gemini.google.com
            log("生图引擎：Gemini 全包——理解/提示词/查篡改/翻译与生图都由 Gemini 完成，全程不启动 ChatGPT。")
            gen_client = GeminiClient(log=log, nudge=_nudge, cancel=_finish_now,
                                      model=get_gemini_model())
            gen_client.connect(with_director=True)   # 自开导演页+生图页，不共用别人的 pw
            client = gen_client                      # 导演也用它（director_page 走文字，gen_page 走生图）
            gen = gen_client
        elif engine == "gemini":
            # 【借 ChatGPT 当导演】Gemini 只生图，ChatGPT 做文本推理（旧行为，两个都启动）
            client = ChatGPTClient(log=log, nudge=_nudge, cancel=_finish_now)
            client.connect(director_only=True)       # ChatGPT 只做文本推理，不开生图标签
            log("生图引擎：Gemini（nano-banana）生图；ChatGPT 只做文本推理（理解/提示词/查篡改）。")
            gen_client = GeminiClient(log=log, nudge=_nudge, cancel=_finish_now,
                                      model=get_gemini_model())
            gen_client.connect(pw=client._pw)        # 共用 ChatGPT 的 playwright，避免同线程双实例报错
            gen = gen_client
        else:
            # 【纯 ChatGPT】既当导演又当画手
            client = ChatGPTClient(log=log, nudge=_nudge, cancel=_finish_now)
            client.connect(director_only=False)
            gen = client
        with _lock:
            S["state"] = "running"

        # 1) 导演对话：把建筑师的想法扩写成全面提示词
        log("导演对话：理解想法、扩写第一版全面提示词…")
        intro = (
            pe.director_system_prompt()
            + "\n\n【建筑师的想法】\n" + requirement
            + "\n\n【图片说明】第 1 张是必须严格忠实的原图底图"
            + (f"，其余 {len(ref_images)} 张是仅供借鉴氛围/材质/光线的意向图。" if ref_images else "。")
        )
        reply = client.send(client.director_page, intro,
                            image_paths=[base_image] + ref_images)

        # AI 理解不了就反问建筑师，答清楚才开始消耗生图额度（最多 3 轮）
        for _ in range(3):
            questions = pe.extract_questions(reply)
            if not questions:
                break
            answers = ask_architect(questions)
            if answers is None:
                raise ChatGPTError("在回答 AI 反问前结束了任务，尚未生成任何图片。")
            log("收到回答，导演对话继续组织提示词…")
            with _lock:
                S["state"] = "running"
            reply = client.send(client.director_page,
                                pe.clarification_answer_prompt(answers))

        # 解析双语产出：中文讲解/中文提示词给建筑师看，英文提示词发给生图
        parsed = pe.parse_director_reply(reply)
        understanding = parsed["understanding"]
        prompt_zh = parsed["prompt_zh"]
        prompt = parsed["prompt_en"]   # 工作变量：发给生图模型的英文提示词

        # 英文提示词偶尔缺失/过短：模型漏标签或网页截断。别直接判败——追一刀要全文。
        if len(prompt) < 40:
            log(f"英文提示词偏短/缺失，原始回复：{reply[:120] or '（空）'}。追问一次…")
            reply = client.send(
                client.director_page,
                "刚才的输出不完整。请严格按 <理解>…</理解><中文提示词>…</中文提示词>"
                "<英文提示词>…</英文提示词> 三段重新输出，英文提示词必须是完整可用的英文段落。")
            parsed = pe.parse_director_reply(reply)
            understanding = parsed["understanding"] or understanding
            prompt_zh = parsed["prompt_zh"] or prompt_zh
            prompt = parsed["prompt_en"] or prompt
        if len(prompt) < 40:
            _dname = "Gemini" if gemini_solo else "ChatGPT"
            _dsite = "gemini.google.com" if gemini_solo else "chatgpt.com"
            # 取证：导演空回复这条路径过去不落 DOM 快照，导致每次都盲修。抓一份导演页快照，
            # 便于判断到底是"回复正常但抓取选择器没命中"还是"思考期被判完成→取到空"。
            try:
                client._dump_dom(client.director_page,
                                 f"导演两次都没给出可用英文提示词（{_dname}），最后原始回复={reply[:80]!r}")
            except Exception:
                pass
            raise ChatGPTError(
                f"导演对话两次都没给出可用的英文提示词。多半是 {_dname} 网页异常、未真正登录，"
                f"或回答被中途停止——请到专用 Chrome 窗口看一眼 {_dsite} 是否有弹窗/验证，再重试。"
                f"（已存页面快照到 logs/，发我可精准定位）")
        log("第一版提示词已生成。")

        def director_adjust(edited_zh: str, note: str):
            """建筑师在确认关卡改了中文/提了意见 → 导演重新对齐三段产出，返回(讲解,中文,英文)。"""
            with _lock:
                S["state"] = "running"
            log("建筑师调整了提示词，导演据此重新组织…")
            rep = client.send(client.director_page, pe.adjust_prompt(edited_zh, note))
            for _ in range(3):  # 调整里若有关键歧义，导演也会反问
                q = pe.extract_questions(rep)
                if not q:
                    break
                a = ask_architect(q)
                if a is None:
                    raise ChatGPTError("在确认提示词前结束了任务，尚未生成任何图片。")
                with _lock:
                    S["state"] = "running"
                rep = client.send(client.director_page, pe.clarification_answer_prompt(a))
            p = pe.parse_director_reply(rep)
            return (p["understanding"] or understanding,
                    p["prompt_zh"] or edited_zh or prompt_zh,
                    p["prompt_en"] or prompt)

        # 2) 确认关卡：给建筑师看中文讲解 + 可编辑中文提示词，确认或调整后再生图
        while True:
            with _lock:
                S["state"] = "waiting_confirm"
                S["understanding"] = understanding
                S["prompt_zh"] = prompt_zh
            log("等待建筑师确认理解与中文提示词（还没消耗生图额度）…")
            _confirm_event.wait()
            _confirm_event.clear()
            if _finish_now.is_set():
                raise ChatGPTError("在确认提示词前结束了任务，尚未生成任何图片。")
            edited = _confirm["edited_zh"].strip()
            note = _confirm["note"].strip()
            if _confirm["action"] == "confirm":
                # 若建筑师在框里改过中文，先让导演把英文同步到位再生图
                if edited and edited != prompt_zh.strip():
                    understanding, prompt_zh, prompt = director_adjust(edited, note)
                break
            # action == adjust：重新对齐后回到确认关卡再看一眼
            understanding, prompt_zh, prompt = director_adjust(edited or prompt_zh, note)
        with _lock:
            S["state"] = "running"
            S["understanding"] = ""
            S["prompt_zh"] = ""
        _update_meta(sess_dir, last_prompt_zh=prompt_zh, last_prompt_en=prompt)
        log("提示词已确认，开始生图。")

        # fidelity_base：QC 忠实性参照（新图始终和它对比查偏移）。初始=原图；
        #   建筑师批准的局部修改后更新为修改结果。
        # last_gen：上一张生成图，"精修"模式下作为增量修改的底图。
        # next_mode：下一轮走 "refine"(精修上一张) 还是 "redraw"(从原图重画)。
        # refine_instruction：QC 给出的本轮待修局部缺陷清单。
        fidelity_base = base_image
        last_gen = None
        next_mode = "redraw"      # 首轮无上一张可精修，从原图重画
        refine_instruction = ""
        i = 0

        def gen_round():
            """一轮自动迭代：按 next_mode 选择"精修上一张/从原图重画"→ 生图
            → 对比原图查篡改并判断下一步 → 更新精修清单或提示词。"""
            nonlocal prompt, next_mode, last_gen, refine_instruction
            if next_mode == "refine" and last_gen and refine_instruction:
                log(f"第 {i} 轮：在上一张基础上做增量精修（省额度，不推倒重画）…")
                gen_msg = pe.refine_message(refine_instruction, quality)
                gen_base = last_gen
                gen_imgs = [gen_base]   # 精修只发上一张，不掺参考图（避免破坏已成图）
            else:
                log(f"第 {i} 轮：从原图底图重画（约 1-3 分钟）…")
                gen_base = fidelity_base
                # 有意向/材质图时，连同底图一起真发给生图 AI（不再只发底图、靠文字想象材质），
                # 用逐张枚举角色的强祈使提示词，降低多图被"分析而非生成"的概率。
                if ref_images:
                    roles = list(ref_roles or []) + ["generic"] * max(0, len(ref_images) - len(ref_roles or []))
                    roles = roles[:len(ref_images)]
                    tags = "、".join(pe.REF_ROLE_LABELS.get(r, "通用参考") for r in roles)
                    log(f"　随底图一并发送 {len(ref_images)} 张参考图给生图 AI（{tags}）。")
                    gen_msg = pe.generation_message_multi(prompt, roles, quality, ratio)
                    gen_imgs = [gen_base] + ref_images
                else:
                    gen_msg = pe.generation_message(prompt, quality, ratio)
                    gen_imgs = [gen_base]
            gen.new_generation_chat()
            gen.send(gen.gen_page, gen_msg,
                     image_paths=gen_imgs, expect_image=True)
            img_path = os.path.join(sess_dir, f"iter_{i:02d}.png")
            if not gen.download_last_image(gen.gen_page, img_path):
                raise GenStalledError(f"第 {i} 轮似乎出图了但没抓到图片（页面可能假死）。")
            _dewatermark_inplace(img_path)   # gemini：过程图也去水印，UI 全程干净（含后续精修底图/QC）
            last_gen = img_path
            log(f"第 {i} 轮出图完成，对比原图检查篡改与画质…")
            # 图已成功落盘。QC（导演对话）若因网页异常失败，绝不能把这张图和整个会话一起丢掉——
            # 保留成图、给个兜底结论、下一轮从原图重画即可（需求③/⑦：会话不结束、成果不丢）。
            try:
                qc_imgs = pe.qc_image_paths(fidelity_base, img_path, ref_images, ref_roles)
                qc_reply = client.send(
                    client.director_page,
                    pe.qc_and_revise_prompt(i, detail_count=len(qc_imgs) - 2),
                    image_paths=qc_imgs)
                parsed = pe.parse_director_reply(qc_reply)
            except ChatGPTError as e:
                log(f"⚠ 出图成功但篡改检查时 ChatGPT 未响应（{e}）——已保留此图，下一轮从原图重画。")
                parsed = {"new_prompt": "", "fidelity": "", "next_step": "重画",
                          "refine_instruction": "",
                          "analysis": "（本轮出图成功，但对比检查时 ChatGPT 未响应，未能生成篡改报告）",
                          "verdict": "已保留此图，检查未完成"}
            if parsed["new_prompt"]:
                prompt = parsed["new_prompt"]  # 存好完整提示词，回退重画时用
            # 决定下一轮模式：形体明显篡改 或 导演判定需重画 → 从原图重画；否则精修
            drift = parsed["fidelity"] == "明显篡改"
            if drift or parsed["next_step"] == "重画":
                next_mode = "redraw"
                refine_instruction = ""
            else:
                next_mode = "refine"
                refine_instruction = parsed["refine_instruction"] or parsed["analysis"]
                if not refine_instruction:
                    next_mode = "redraw"  # 没拿到可精修的清单，兜底重画
            mode_label = "精修上一张" if next_mode == "refine" else "从原图重画"
            add_item(i, f"iter_{i:02d}.png", "auto",
                     parsed["analysis"] or "（未解析出分析内容）",
                     parsed["verdict"], prompt)
            _update_meta(sess_dir, last_prompt_zh=prompt_zh, last_prompt_en=prompt)
            _persist_item_prompt(sess_dir, f"iter_{i:02d}.png", prompt,
                                 parsed["analysis"], parsed["verdict"], "auto")
            log(f"第 {i} 轮检查完成（下一轮将{mode_label}）：{(parsed['verdict'] or '无结论')[:80]}")

        def edit_round(edit):
            """一轮局部修改：只改红色标记区域，QC 检查周边有没有被动。"""
            nonlocal fidelity_base, last_gen, next_mode, refine_instruction
            src = os.path.join(sess_dir, edit["source_image"])
            marked = edit["marked_path"]
            instruction = edit["instruction"]

            # 理解确认关卡：先让导演看[原图, 标记图]用中文复述对这次修改的理解，建筑师确认无误
            # 再真正生图（复用主流程确认关卡的 UI 与事件，避免误改浪费额度）。
            while True:
                with _lock:
                    S["state"] = "running"
                log("局部修改：先让导演复述对修改的理解，等你确认…")
                u_reply = client.send(client.director_page,
                                      pe.regional_understanding_prompt(instruction),
                                      image_paths=[src, marked])
                understanding = pe.parse_director_reply(u_reply)["understanding"] or u_reply.strip()
                with _lock:
                    S["state"] = "waiting_confirm"
                    S["understanding"] = understanding
                    S["prompt_zh"] = instruction
                _confirm_event.clear()
                _confirm_event.wait()
                _confirm_event.clear()
                if _finish_now.is_set():
                    with _lock:
                        S["state"] = "running"
                        S["understanding"] = ""
                        S["prompt_zh"] = ""
                    return   # 提前结束：放弃这次局部修改，交回外层正常收尾输出最新图
                edited = _confirm["edited_zh"].strip()
                if edited:
                    instruction = edited
                with _lock:
                    S["understanding"] = ""
                    S["prompt_zh"] = ""
                if _confirm["action"] == "confirm":
                    break
                # action == adjust：用建筑师改过的指令再让导演复述一遍理解

            with _lock:
                S["state"] = "editing"
            log(f"第 {i} 轮（局部修改）：只修改标记区域——{instruction[:50]}…")
            # 发给生图的一律英文：先把中文修改指令翻成英文（纯文本，不耗生图额度）
            tr = client.send(client.director_page,
                             pe.translate_instruction_prompt(instruction))
            instruction_en = pe.parse_director_reply(tr)["prompt_en"] or instruction
            gen.new_generation_chat()
            material_path = edit.get("material_path") or ""
            if material_path and os.path.isfile(material_path):
                # 材质换面：把材质样板作为第 3 张图，只把圈选区换成该材质
                gen.send(gen.gen_page,
                         pe.regional_edit_with_material_message(instruction_en),
                         image_paths=[src, marked, material_path], expect_image=True)
            else:
                gen.send(gen.gen_page, pe.regional_edit_message(instruction_en),
                         image_paths=[src, marked], expect_image=True)
            img_path = os.path.join(sess_dir, f"iter_{i:02d}.png")
            if not gen.download_last_image(gen.gen_page, img_path):
                raise GenStalledError(f"局部修改第 {i} 轮似乎出图了但没抓到图片（页面可能假死）。")
            _dewatermark_inplace(img_path)   # gemini：局改过程图也去水印
            log("局部修改出图完成，检查标记区域外是否被动…")
            qc_reply = client.send(client.director_page,
                                   pe.regional_qc_message(instruction),
                                   image_paths=[src, img_path])
            parsed = pe.parse_director_reply(qc_reply)
            add_item(i, f"iter_{i:02d}.png", "edit",
                     parsed["analysis"] or "（未解析出分析内容）",
                     parsed["verdict"], f"（局部修改）{instruction}")
            _persist_item_prompt(sess_dir, f"iter_{i:02d}.png",
                                 f"（局部修改）{instruction}",
                                 parsed["analysis"], parsed["verdict"], "edit")
            # 建筑师批准的修改结果成为新的忠实性参照与后续底图；下一轮从它重画一次校准
            fidelity_base = img_path
            last_gen = img_path
            next_mode = "redraw"
            refine_instruction = ""
            log(f"局部修改检查完成：{(parsed['verdict'] or '无结论')[:80]}")

        def run_step_with_recovery(step_fn) -> bool:
            """执行一轮生成；若生图多次自愈仍失败(GenStalledError)：
            先「自动干预」——自动刷新重试若干次（判断是 ChatGPT 网页假死还是真没出图，
            期间界面仍显示运行中、可随时点结束）；自动重试用完仍失败，才停在 'stalled'
            可恢复状态等用户手动「重试本轮」或「提前结束」，绝不让会话结束（需求③/⑦）。
            返回 True 表示用户选择结束任务。"""
            auto_retries_left = 2   # 卡死后自动再刷新重试的次数上限，用完才停下等人工
            while True:
                try:
                    step_fn()
                    return False
                except GenCancelled:
                    # 用户「提前结束」正好卡在生图等待里：丢弃这张、正常收尾（#6b）
                    log("已提前结束：放弃正在生成的这一张，输出已完成的最后一张成品。")
                    return True
                except GenStalledError as e:
                    if auto_retries_left > 0:
                        auto_retries_left -= 1
                        log(f"⚠ 生图卡住：{e} —— 自动刷新重试一轮"
                            f"（剩余自动重试 {auto_retries_left} 次）…")
                        if _finish_now.wait(timeout=2.0):  # 重试前留个可取消的小停顿
                            return True
                        _nudge.clear()
                        continue
                    with _lock:
                        S["state"] = "stalled"
                        S["error"] = str(e)
                    log(f"⚠ 自动重试用尽仍未出图，暂停等待手动重试或结束：{e}")
                    _nudge.clear()
                    while not _nudge.is_set() and not _finish_now.is_set():
                        _nudge.wait(timeout=1.0)
                    if _finish_now.is_set():
                        return True
                    _nudge.clear()
                    with _lock:
                        S["state"] = "running"
                        S["error"] = ""
                    log("收到重试指令，重开 ChatGPT 对话再生成一次…")

        finished = False
        while not finished:
            # 一批自动迭代：每 review_every 张暂停一次等点评（建筑师在界面上设定）
            for _ in range(max(1, review_every)):
                i += 1
                with _lock:
                    S["iteration"] = i
                if run_step_with_recovery(gen_round):
                    finished = True
                    break
                if _finish_now.is_set():
                    finished = True
                    break
            if finished:
                break

            # 点评阶段：可反复局部修改，直到"继续"或"满意"
            while True:
                with _lock:
                    S["state"] = "waiting_feedback"
                log(f"已完成 {i} 轮，等待建筑师点评（可圈选图片做局部修改）…")
                _feedback_event.wait()
                _feedback_event.clear()
                if _finish_now.is_set() or _feedback["type"] == "satisfied":
                    finished = True
                    break
                if _feedback["type"] == "edit":
                    with _lock:
                        S["state"] = "editing"
                    i += 1
                    with _lock:
                        S["iteration"] = i
                    edit = _feedback["edit"]
                    if run_step_with_recovery(lambda: edit_round(edit)):
                        finished = True
                        break
                    continue  # 回到点评阶段
                # type == continue：带点评继续自动迭代
                with _lock:
                    S["state"] = "running"
                if _feedback["text"].strip():
                    log("收到点评，导演对话据此修订提示词…")
                    fb_reply = client.send(client.director_page,
                                           pe.feedback_prompt(_feedback["text"]))
                    # 点评有歧义时 AI 也会反问，答清再改
                    for _ in range(3):
                        questions = pe.extract_questions(fb_reply)
                        if not questions:
                            break
                        answers = ask_architect(questions)
                        if answers is None:
                            finished = True
                            break
                        with _lock:
                            S["state"] = "running"
                        fb_reply = client.send(client.director_page,
                                               pe.clarification_answer_prompt(answers))
                    if finished:
                        break
                    parsed = pe.parse_director_reply(fb_reply)
                    if parsed["new_prompt"]:
                        prompt = parsed["new_prompt"]
                        if parsed["prompt_zh"]:
                            prompt_zh = parsed["prompt_zh"]
                        _update_meta(sess_dir, last_prompt_zh=prompt_zh, last_prompt_en=prompt)
                        log("提示词已按点评修订。")
                    else:
                        log("警告：点评后未解析出新提示词，沿用上一版。")
                    # 点评是方向性调整，下一轮从原图按新提示词重画，不在旧图上精修
                    next_mode = "redraw"
                    refine_instruction = ""
                break

        # 输出最终图到桌面（按画质档位增强，并在页面完成卡上展示增强版大图）
        _deliver_final(sess_dir)

    except GenCancelled:
        # 「提前结束」正好卡在文本推理阶段（没被 run_step_with_recovery 兜住）：
        # 不算错误——有成品就输出最后一张，没有就干净收尾（#6b）。
        try:
            _deliver_final(sess_dir)
            log("已提前结束（放弃了正在生成的那张，已交付此前完成的最后一张）。")
        except ChatGPTError:
            with _lock:
                S["state"] = "done"
            log("已提前结束（还没有生成任何图片）。")
        except Exception as e:
            with _lock:
                S["state"] = "error"
                S["error"] = str(e)
            log(f"提前结束收尾时出错：{e}")
    except (ChatGPTError, GeminiError) as e:
        with _lock:
            S["state"] = "error"
            S["error"] = str(e)
        log(f"出错：{e}")
    except Exception as e:
        with _lock:
            S["state"] = "error"
            S["error"] = f"未预期的错误：{e}"
        log(f"未预期的错误：{e}")
    finally:
        if client is not None:
            client.close()
        # 全包模式下 gen_client 与 client 是同一个对象，别重复关（pw 已停）
        if gen_client is not None and gen_client is not client:
            gen_client.close()


# ---------------- 路由 ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    if S["state"] in ("connecting", "running", "waiting_confirm",
                      "waiting_clarification", "waiting_feedback", "editing"):
        return jsonify({"ok": False, "msg": "已有任务在运行"}), 400

    requirement = request.form.get("requirement", "").strip()
    base = request.files.get("base_image")
    # base_from：把某张历史成图当新底图（痛点三）。二选一：上传新图 或 选历史图。
    base_from = request.form.get("base_from", "").strip()
    base_from_path = _resolve_workspace_image(base_from) if base_from else ""
    if not requirement or (not base and not base_from_path):
        return jsonify({"ok": False, "msg": "需求描述和原图都是必填的"
                        "（可上传新图，或从历史成图里挑一张当底图）"}), 400

    sess_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    sess_dir = os.path.join(WORKSPACE, sess_id)
    os.makedirs(sess_dir, exist_ok=True)

    try:
        if base:
            base_path = save_image_optimized(base, os.path.join(sess_dir, "base"))
        else:
            base_path = save_image_optimized_from_path(
                base_from_path, os.path.join(sess_dir, "base"))
        ref_paths = []
        ref_roles = []                                   # 每张参考图的角色（与 ref_paths 对齐）
        raw_roles = request.form.getlist("ref_roles")    # 前端逐图下拉传来，顺序同 ref_images
        _valid_roles = set(pe.REF_ROLE_LABELS.keys())
        for j, f in enumerate(request.files.getlist("ref_images")):
            if f and f.filename:
                ref_paths.append(
                    save_image_optimized(f, os.path.join(sess_dir, f"ref_{j}")))
                r = raw_roles[j] if j < len(raw_roles) else "generic"
                ref_roles.append(r if r in _valid_roles else "generic")  # 不定义就是 generic
    except Exception as e:
        return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400

    # 落一份会话元信息，供"历史成图"列表展示（不含图，随 workspace 一起留存）
    try:
        with open(os.path.join(sess_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"requirement": requirement,
                       "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "base_from": base_from if base_from_path else ""},
                      f, ensure_ascii=False)
    except OSError:
        pass

    with _lock:
        S.update({"state": "connecting", "session_id": sess_id, "iteration": 0,
                  "items": [], "logs": [], "questions": "",
                  "understanding": "", "prompt_zh": "",
                  "error": "", "final_path": "", "final_enhanced": None})
    _feedback_event.clear()
    _confirm_event.clear()
    _finish_now.clear()
    _nudge.clear()

    quality = request.form.get("quality", "标准")
    ratio = request.form.get("ratio", "跟随原图")
    try:
        review_every = int(request.form.get("review_every", DEFAULT_REVIEW_EVERY))
    except (TypeError, ValueError):
        review_every = DEFAULT_REVIEW_EVERY
    review_every = max(1, min(review_every, 10))  # 夹在 1~10 张之间
    threading.Thread(target=run_session,
                     args=(requirement, base_path, ref_paths, sess_dir, quality, ratio,
                           review_every, ref_roles),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with _lock:
        data = dict(S)
        data["image_engine"] = _image_engine   # 当前生图引擎，供前端切换开关回显
        data["quality"] = _quality             # 当前画质档位，供前端下拉回显
        data["gemini_model"] = _gemini_model   # 当前 Gemini 生图模型，引擎=gemini 时前端下拉回显
        data["gemini_models"] = list(_GEMINI_MODELS)  # 可选模型清单，供前端渲染下拉
        data["gemini_selfrun"] = _gemini_selfrun  # Gemini 全包 / 借 ChatGPT 当导演，供分工开关回显
        data["build"] = APP_BUILD              # 运行中代码版本标记，供确认「重启是否生效」
    return jsonify(data)


@app.route("/api/set_engine", methods=["POST"])
def api_set_engine():
    """切换生图引擎（chatgpt / gemini）。任务运行中不许切——本轮连接已建立，切了会乱。
    下次「开始渲染」时生效。"""
    if S["state"] not in ("idle", "done", "error"):
        return jsonify({"ok": False, "msg": "任务进行中不能切换生图引擎，请等本次结束或先结束任务"}), 400
    try:
        name = set_image_engine((request.get_json(silent=True) or {}).get("engine"))
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify({"ok": True, "engine": name})


@app.route("/api/set_gemini_model", methods=["POST"])
def api_set_gemini_model():
    """切换 Gemini 生图模型（引擎=gemini 时用）。任务运行中不许切——本轮连接已建立。
    下次「开始渲染」时由 GeminiClient.select_model() 在网页上尝试切换。"""
    if S["state"] not in ("idle", "done", "error"):
        return jsonify({"ok": False, "msg": "任务进行中不能切换模型，请等本次结束或先结束任务"}), 400
    try:
        m = set_gemini_model((request.get_json(silent=True) or {}).get("model"))
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify({"ok": True, "model": m})


@app.route("/api/set_gemini_selfrun", methods=["POST"])
def api_set_gemini_selfrun():
    """切换 Gemini 分工：全包（只启动 Gemini）/ 借 ChatGPT 当导演。任务运行中不许切——
    本轮连接已建立。下次「开始渲染」时生效。"""
    if S["state"] not in ("idle", "done", "error"):
        return jsonify({"ok": False, "msg": "任务进行中不能切换分工，请等本次结束或先结束任务"}), 400
    on = set_gemini_selfrun((request.get_json(silent=True) or {}).get("selfrun"))
    return jsonify({"ok": True, "selfrun": on})


@app.route("/api/set_quality", methods=["POST"])
def api_set_quality():
    """切换出图画质档位（1k/2k/4k/8k）。画质是逐图本地后处理，随时可改、下一张成图生效。"""
    try:
        q = set_quality((request.get_json(silent=True) or {}).get("quality"))
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    return jsonify({"ok": True, "quality": q})


@app.route("/api/enhance_image", methods=["POST"])
def api_enhance_image():
    """页面上「提升画质并查看」：按指定/当前档位，把某张成图本地 AI 超分成一份新文件，
    返回可在页面直接查看的 URL。已增强过的直接命中缓存秒回；否则异步跑（8K 需数分钟），
    前端轮询 /api/enhance_status 看进度。对应诉求：画质增强要在页面上真能用、能看到。"""
    data = request.get_json(silent=True) or {}
    sess = _safe_name(data.get("session"))
    image = _safe_name(data.get("image"))
    q = str(data.get("quality") or get_quality()).strip().lower()   # 只读校验，不改全局档位
    if q not in _QUALITIES:
        return jsonify({"ok": False, "msg": f"未知画质档位：{q}"}), 400
    src = os.path.join(WORKSPACE, sess, image) if (sess and image) else ""
    if not src or not os.path.isfile(src):
        return jsonify({"ok": False, "msg": "找不到这张图"}), 400
    if q == "1k" and get_image_engine() != "gemini":
        return jsonify({"ok": False, "msg": "当前是 1K 原生档，无需增强；把画质切到 2K/4K/8K 再试"}), 400
    dst_name = f"_enh_{q}_{image}"
    dst = os.path.join(WORKSPACE, sess, dst_name)
    url = f"/images/{sess}/{dst_name}"
    key = f"{sess}/{image}@{q}"
    if os.path.isfile(dst):                       # 缓存命中：秒回
        return jsonify({"ok": True, "cached": True, "url": url,
                        "from": _png_size(src), "to": _png_size(dst)})
    with _enh_lock:
        if _enh_job["active"]:
            return jsonify({"ok": False, "msg": "已有一张图在增强中，请等它完成再点"}), 409
        _enh_job.update({"active": True, "done": False, "ok": False, "error": "",
                         "url": "", "from": _png_size(src), "to": "", "key": key, "log": []})
    dewm = (get_image_engine() == "gemini")
    threading.Thread(target=_run_enhance_job,
                     args=(src, dst, url, q, dewm, key), daemon=True).start()
    return jsonify({"ok": True, "cached": False, "key": key})


@app.route("/api/enhance_status")
def api_enhance_status():
    """单张按需增强的进度/结果，供前端轮询。"""
    with _enh_lock:
        return jsonify(dict(_enh_job))


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    if S["state"] != "waiting_feedback":
        return jsonify({"ok": False, "msg": "当前不在点评阶段"}), 400
    data = request.get_json(force=True)
    _feedback["type"] = "satisfied" if data.get("satisfied") else "continue"
    _feedback["text"] = data.get("text", "")
    _feedback["edit"] = None
    _feedback_event.set()
    return jsonify({"ok": True})


@app.route("/api/confirm_prompt", methods=["POST"])
def api_confirm_prompt():
    """确认关卡：建筑师确认/调整中文提示词。adjust=True 表示让 AI 按修改再调整一版。"""
    if S["state"] != "waiting_confirm":
        return jsonify({"ok": False, "msg": "当前不在确认阶段"}), 400
    data = request.get_json(force=True)
    _confirm["action"] = "adjust" if data.get("adjust") else "confirm"
    _confirm["edited_zh"] = (data.get("edited_zh") or "").strip()
    _confirm["note"] = (data.get("note") or "").strip()
    _confirm_event.set()
    return jsonify({"ok": True})


@app.route("/api/regional_edit", methods=["POST"])
def api_regional_edit():
    """接收圈选标记图(dataURL) + 修改指令，触发一轮局部修改。"""
    if S["state"] != "waiting_feedback":
        return jsonify({"ok": False, "msg": "只能在点评暂停时做局部修改"}), 400
    data = request.get_json(force=True)
    instruction = (data.get("instruction") or "").strip()
    source_image = data.get("source_image") or ""
    data_url = data.get("marked") or ""
    if not instruction or "," not in data_url or not source_image:
        return jsonify({"ok": False, "msg": "标记图和修改指令都是必需的"}), 400

    sess_dir = os.path.join(WORKSPACE, S["session_id"])
    if not os.path.isfile(os.path.join(sess_dir, os.path.basename(source_image))):
        return jsonify({"ok": False, "msg": "找不到要修改的图"}), 400
    marked_path = os.path.join(
        sess_dir, f"marked_{datetime.now().strftime('%H%M%S')}.png")
    with open(marked_path, "wb") as f:
        f.write(base64.b64decode(data_url.split(",", 1)[1]))

    # 材质换面（素材·材质）：可选带一张材质样板图，只把圈选区换成该材质
    material_path = ""
    material = _safe_name(data.get("material"))
    if material:
        mp = os.path.join(ASSETS_DIR, material)
        if os.path.isfile(mp):
            material_path = mp

    _feedback["type"] = "edit"
    _feedback["text"] = ""
    _feedback["edit"] = {"source_image": os.path.basename(source_image),
                         "marked_path": marked_path,
                         "instruction": instruction,
                         "material_path": material_path}
    _feedback_event.set()
    return jsonify({"ok": True})


@app.route("/api/clarify", methods=["POST"])
def api_clarify():
    """建筑师回答 AI 的反问。"""
    if S["state"] != "waiting_clarification":
        return jsonify({"ok": False, "msg": "当前 AI 没有待回答的疑问"}), 400
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "msg": "回答不能为空"}), 400
    _feedback["type"] = "clarify"
    _feedback["text"] = text
    _feedback["edit"] = None
    _feedback_event.set()
    return jsonify({"ok": True})


def _login_targets():
    """按当前生图引擎返回需要检测/登录的站点：(名称, url匹配片段, 打开url, 就绪选择器)。
    · ChatGPT 引擎：只需 ChatGPT。
    · Gemini 全包（默认）：只需 Gemini——文字推理也归它，全程不碰 ChatGPT（选谁只登谁）。
    · Gemini 借 ChatGPT 当导演：需 Gemini(出图) ＋ ChatGPT(导演)。Gemini 放第一个先登。"""
    import gemini_client as gc
    chatgpt = ("ChatGPT", "chatgpt.com", "https://chatgpt.com/", "#prompt-textarea")
    gemini = ("Gemini", "gemini.google.com", gc.GEMINI_URL, gc.SEL["editor"])
    if get_image_engine() == "gemini":
        return [gemini] if get_gemini_selfrun() else [gemini, chatgpt]
    return [chatgpt]


def _probe_login(browser, name, match, goto_url, ready_sel):
    """在已接管的浏览器里找/开该站点标签，判断是否登录就绪。
    返回 (status, detail)：ready / not_logged_in / conflict。"""
    page = None
    for c in browser.contexts:
        page = next((p for p in c.pages if match in p.url), None)
        if page:
            break
    if page is None:
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            page.goto(goto_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return ("conflict", f"{CDP_PORT} 端口被另一个调试浏览器占用——关掉那个程序后再点「检测」")
    try:
        page.wait_for_selector(ready_sel, timeout=8000)
        return ("ready", f"{name} 已登录")
    except Exception:
        return ("not_logged_in", f"Chrome 已启动，但 {name} 未登录（去那个窗口登录一次）")


@app.route("/api/chrome_status")
def api_chrome_status():
    """检测专用 Chrome 与登录状态，按当前生图引擎决定查哪个站点（见 _login_targets）：
    chrome_off / conflict / not_logged_in / ready。"""
    if S["state"] in ("connecting", "running", "waiting_confirm",
                      "waiting_clarification", "waiting_feedback", "editing"):
        return jsonify({"status": "ready", "detail": "渲染任务运行中，连接正常"})
    try:
        _local_get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
    except Exception:
        return jsonify({"status": "chrome_off", "detail": "专用 Chrome 未启动"})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            targets = _login_targets()
            for name, match, goto_url, ready_sel in targets:
                st, detail = _probe_login(browser, name, match, goto_url, ready_sel)
                if st != "ready":
                    return jsonify({"status": st, "detail": detail})
            names = "、".join(t[0] for t in targets)
            return jsonify({"status": "ready", "detail": f"{names} 已登录，就绪"})
    except Exception as e:
        return jsonify({"status": "chrome_off", "detail": f"连接失败：{e}"})


@app.route("/api/launch_chrome", methods=["POST"])
def api_launch_chrome():
    """一键启动带调试端口的专用 Chrome，并按当前引擎打开需要登录的站点标签
    （Gemini 引擎会同时打开 Gemini 与 ChatGPT，Gemini 在前台先登）。"""
    chrome = _find_chrome()
    if not chrome:
        return jsonify({"ok": False,
                        "msg": "没找到 Chrome，请确认已安装 Google Chrome"}), 400
    urls = [t[2] for t in _login_targets()]
    # 禁用扩展：Grammarly/翻译类插件会往 ChatGPT/Gemini 输入框注入浮层，拦截发送按钮的
    # 指针事件（"发送按钮点击未生效"）、甚至改动 DOM 影响抓图。专用 Chrome 只用于自动化，
    # 关掉扩展最干净；登录 cookie 在 user-data-dir 里，不受影响。
    subprocess.Popen([chrome, f"--remote-debugging-port={CDP_PORT}",
                      f"--user-data-dir={_chrome_profile_arg(chrome)}",
                      "--disable-extensions",
                      "--disable-component-extensions-with-background-pages",
                      "--no-first-run", "--no-default-browser-check", *urls])
    return jsonify({"ok": True})


def _net_hosts_for_engine():
    """当前生图引擎需要能连通的外网主机（不含端口）。ChatGPT 引擎只需 chatgpt.com；
    Gemini 引擎还要 gemini.google.com（导演仍走 ChatGPT，故两者都要）。"""
    if get_image_engine() == "gemini":
        return ["gemini.google.com", "chatgpt.com"]
    return ["chatgpt.com"]


def _system_https_proxy():
    """当前生效的 HTTP(S) 系统代理 (host, port)，没有则 None。
    进程已带 HTTPS_PROXY 就用它；否则读系统代理（Windows 走注册表，与 _proxy_env 同源）。
    土星通讯等「系统代理/规则模式」就是往这里塞 127.0.0.1:端口——探测必须认它。"""
    url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not url:
        try:
            import urllib.request
            proxies = urllib.request.getproxies()
        except Exception:
            proxies = {}
        url = proxies.get("https") or proxies.get("http")
    if not url:
        return None
    # 只认 http(s) 代理的 CONNECT 隧道；socks 代理裸探测测不了，交回直连兜底。
    if "://" in url and not url.lower().startswith("http"):
        return None
    hostport = url.split("://", 1)[-1].rstrip("/")
    if "@" in hostport:                       # 去掉 user:pass@
        hostport = hostport.rsplit("@", 1)[-1]
    host, _, port = hostport.partition(":")
    if not host:
        return None
    try:
        return host, int(port) if port else 80
    except ValueError:
        return None


def _reachable_via_proxy(proxy, host, port, timeout):
    """穿过 HTTP 代理探目标是否**真**可达（=浏览器走法）：先 CONNECT 开隧道，再对目标做 TLS 握手。
    只看 CONNECT 200 不够——很多代理对任何主机(含不存在的)都先回 200 再去连上游，会假阳性；
    必须用 TLS 握手证实上游真的通。TLS 握手属传输层、不带凭据、不发任何应用层请求（合规红线）。"""
    import ssl
    try:
        with socket.create_connection(proxy, timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((f"CONNECT {host}:{port} HTTP/1.1\r\n"
                       f"Host: {host}:{port}\r\n\r\n").encode())
            resp = s.recv(256)
            if b" 200" not in resp.split(b"\r\n", 1)[0]:   # 只看状态行，别在整包里瞎匹配 200
                return False
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE    # 只问"能否与该站建立加密通道"，不校验证书链(探测非通信)
            with ctx.wrap_socket(s, server_hostname=host):
                pass                            # 握手成功即证上游真可达
        return True
    except Exception:
        return False


def _host_reachable(host, port=443, timeout=4.0):
    """连通性探测：先看真实出网路径能不能到 host:443，视为可达。
    有系统代理（土星通讯等规则模式）→ 穿代理 CONNECT 测，和 Chrome 生图同源；
    无代理（全局 TUN VPN / 裸网）→ 直连测。都只问「能不能到达」，不带凭据、不改系统网络（合规红线）。"""
    proxy = _system_https_proxy()
    if proxy:
        return _reachable_via_proxy(proxy, host, port, timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@app.route("/api/net_check")
def api_net_check():
    """VPN 安全版：静默探测当前引擎所需外网是否可达。
    能连 → 前端完全不打扰；连不上 → 前端弹一句合规提示 + 「测试连接」按钮。
    绝不分发/配置 VPN，只做连通性探测（合规红线，已与用户确认）。
    `?target=chatgpt`：助手页 ChatGPT 模式只依赖 chatgpt.com，与主页渲染引擎无关，用它覆盖。"""
    if request.args.get("target") == "chatgpt":
        hosts = ["chatgpt.com"]
    else:
        hosts = _net_hosts_for_engine()
    # 并行探测：多个站点同时探，连不上时总耗时≈单站超时(≈4s)而非累加(8s+)，按钮少等一半。
    with ThreadPoolExecutor(max_workers=max(1, len(hosts))) as ex:
        results = dict(zip(hosts, ex.map(_host_reachable, hosts)))
    return jsonify({
        "ok": True,
        "engine": get_image_engine(),
        "hosts": results,
        "reachable": all(results.values()),
        "unreachable": [h for h, ok in results.items() if not ok],
    })


# ─────────────────────────────────────────────────────────────────────────────
# 土星通讯（VPN）一键安装：连不上外网时，让用户**自愿**一键下载并打开安装程序。
# 后端在用户机器上跑，故自动判定当前系统、只下发对应平台的安装包（三平台都支持）。
#
# ⚠⚠ 待填：把三平台安装包的**真实直链**填到下面即可启用；某平台留空=该系统不显示安装
#     按钮（只保留"自备网络"提示）。填好后无需改其它任何代码，立即生效。
SATURN_NAME = "土星通讯"
# 面板/下载页：连不上外网时打开它，让用户登录、按自己系统下载并安装客户端、连上网络。
# 用户 2026-07-15 提供。留空=不显示「配置」按钮。
SATURN_DASHBOARD_URL = "https://tuxingss.com/#/dashboard"
# 直链安装包（可选、更省事）：若日后拿到三平台安装包**直链**填这里，按钮会改成
# 后端下载+自动打开安装程序；留空则回退为「打开面板页」。
SATURN_INSTALLERS = {
    "windows": "",   # 例：https://.../土星通讯-setup.exe
    "mac": "",       # 例：https://.../土星通讯.dmg 或 .pkg
    "linux": "",     # 例：https://.../土星通讯.AppImage 或 .deb
}

_saturn_setup = {"active": False, "stage": "", "msg": "", "done": False, "ok": False, "error": ""}
_saturn_lock = threading.Lock()


def _current_os() -> str:
    """当前运行系统：windows / mac / linux（后端在用户机上跑，判的就是用户的系统）。"""
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def _saturn_set(**kw):
    with _saturn_lock:
        _saturn_setup.update(kw)


def _download_file(url: str, dest: str, timeout: int = 900) -> str:
    """流式下载到 dest（先写 .part 再原子改名），失败抛异常。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(65536):
                if chunk:
                    f.write(chunk)
    os.replace(tmp, dest)
    return dest


def _launch_installer(path: str):
    """按当前系统打开下载好的安装程序，让用户点完成安装。"""
    system = _current_os()
    if system == "windows":
        os.startfile(path)                       # noqa: WPS  Windows 专有，仅此分支执行
    elif system == "mac":
        subprocess.Popen(["open", path])         # .dmg 挂载 / .pkg 起安装器
    else:
        try:
            os.chmod(path, 0o755)
        except Exception:
            pass
        if path.lower().endswith(".appimage"):
            subprocess.Popen([path])
        else:
            subprocess.Popen(["xdg-open", path])  # .deb/.run 等交给系统处理


def _run_saturn_install(url: str):
    try:
        _saturn_set(active=True, stage="downloading",
                    msg=f"正在下载 {SATURN_NAME} 安装包…", done=False, ok=False, error="")
        fname = (url.split("?")[0].rstrip("/").split("/")[-1] or "saturn-installer")
        dest = os.path.join(WORKSPACE, "_saturn", fname)
        _download_file(url, dest)
        _saturn_set(stage="launching",
                    msg=f"下载完成，正在打开 {SATURN_NAME} 安装程序，请按提示完成安装…")
        _launch_installer(dest)
        _saturn_set(stage="done", done=True, ok=True,
                    msg=f"{SATURN_NAME} 安装程序已打开。装好并连上网络后，回来点「测试连接」。")
    except Exception as e:
        _saturn_set(stage="error", done=True, ok=False, error=str(e),
                    msg=f"下载/打开 {SATURN_NAME} 失败：{e}")
    finally:
        with _saturn_lock:
            _saturn_setup["active"] = False


@app.route("/api/saturn_status")
def api_saturn_status():
    """当前系统的 土星通讯 配置情况 + 安装进度，供前端决定是否显示「配置」按钮、走哪条路。
    有直链安装包→后端下载安装；否则有面板页→前端打开面板让用户自助下载。"""
    system = _current_os()
    installer = SATURN_INSTALLERS.get(system, "")
    with _saturn_lock:
        setup = dict(_saturn_setup)
    return jsonify({"ok": True, "os": system, "name": SATURN_NAME,
                    "installer_configured": bool(installer),
                    "dashboard_url": SATURN_DASHBOARD_URL,
                    "configured": bool(installer or SATURN_DASHBOARD_URL),
                    "setup": setup})


@app.route("/api/saturn_install", methods=["POST"])
def api_saturn_install():
    """用户**自愿**点「一键安装土星通讯」后触发：下载当前系统对应安装包并打开安装程序。"""
    system = _current_os()
    url = SATURN_INSTALLERS.get(system, "")
    if not url:
        return jsonify({"ok": False,
                        "msg": f"暂未配置 {system} 版 {SATURN_NAME} 安装包"}), 400
    with _saturn_lock:
        if _saturn_setup["active"]:
            return jsonify({"ok": True, "msg": "安装已在进行中，请看进度。"})
    threading.Thread(target=_run_saturn_install, args=(url,), daemon=True).start()
    return jsonify({"ok": True, "msg": f"已开始下载 {SATURN_NAME}，界面会显示进度。"})


@app.route("/api/nudge", methods=["POST"])
def api_nudge():
    """ChatGPT 网页卡死时的人工干预：正在等待时刷新重查；'stalled' 暂停时重试本轮。"""
    if S["state"] not in ("connecting", "running", "editing", "stalled"):
        return jsonify({"ok": False, "msg": "现在没有正在等待的浏览器操作"}), 400
    if S["state"] == "stalled":
        log("收到重试指令：将重开 ChatGPT 对话再生成一次。")
    else:
        log("收到人工干预：将刷新 ChatGPT 页面并重新检查结果。")
    _nudge.set()
    return jsonify({"ok": True})


@app.route("/api/finish_now", methods=["POST"])
def api_finish_now():
    _finish_now.set()
    _feedback_event.set()  # 如果正卡在点评等待，也放行
    _confirm_event.set()   # 如果正卡在确认关卡，也放行
    return jsonify({"ok": True})


@app.route("/helper")
def helper_page():
    return render_template("helper.html")


@app.route("/vendor/<path:sub>")
def vendor_assets(sub):
    return send_from_directory(os.path.join(RES_DIR, "static", "vendor"), sub)


@app.route("/models/<path:sub>")
def model_assets(sub):
    return send_from_directory(os.path.join(APP_DIR, "models"), sub)


@app.route("/api/helper_build", methods=["POST"])
def api_helper_build():
    """助手页「本地模式」：把想法 + 识图描述 + 勾选模块本地拼装成中英提示词。不联网。"""
    data = request.get_json(force=True, silent=True) or {}
    presets = data.get("presets") or []
    if not isinstance(presets, list):
        presets = []
    out = pe.build_prompt_locally(
        intent=str(data.get("intent", "")),
        image_desc=str(data.get("image_desc", "")),
        preset_texts=[str(p) for p in presets],
    )
    return jsonify({"ok": True, **out})


def _helper_chatgpt_ready() -> bool:
    """轻量探测：CDP 端口能连上即视为可用（真正登录与否交给精修时报错）。"""
    try:
        _local_get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


@app.route("/api/helper_refine", methods=["POST"])
def api_helper_refine():
    """助手页「ChatGPT 引擎」：借导演对话看图 + 扩写，返回专业版中英提示词。
    不干扰主渲染：仅在无进行中的渲染时可用。"""
    if S["state"] in ("connecting", "running", "waiting_confirm",
                      "waiting_clarification", "waiting_feedback", "editing"):
        return jsonify({"ok": False, "msg": "当前正在渲染，稍后再用 ChatGPT 精修"}), 409
    if not _helper_chatgpt_ready():
        return jsonify({"ok": False,
                        "msg": "没检测到可用的 ChatGPT（需已启动专用 Chrome 并登录），可切到「本地」模式"}), 400

    draft = (request.form.get("draft_prompt") or "").strip()
    # 改稿模式（需求④）：带上一版提示词 + 用户不满意的意见 → 在原版基础上修订
    prev_zh = (request.form.get("prev_zh") or "").strip()
    feedback = (request.form.get("feedback") or "").strip()
    img = request.files.get("image")
    tmp_dir = os.path.join(WORKSPACE, "_helper")
    os.makedirs(tmp_dir, exist_ok=True)
    img_paths = []
    if img and img.filename:
        try:
            img_paths.append(save_image_optimized(
                img, os.path.join(tmp_dir, datetime.now().strftime("h_%H%M%S"))))
        except Exception as e:
            return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400

    client = ChatGPTClient(log=log)
    try:
        client.connect(director_only=True)
        reply = client.send(client.director_page,
                            pe.helper_refine_prompt(draft, prev_zh, feedback),
                            image_paths=img_paths)
        parsed = pe.parse_director_reply(reply)
        return jsonify({"ok": True,
                        "understanding_zh": parsed["understanding"],
                        "prompt_zh": parsed["prompt_zh"],
                        "prompt_en": parsed["prompt_en"]})
    except ChatGPTError as e:
        return jsonify({"ok": False, "msg": str(e)}), 502
    finally:
        client.close()


def _helper_busy() -> bool:
    return S["state"] in ("connecting", "running", "waiting_confirm",
                          "waiting_clarification", "waiting_feedback", "editing")


def _helper_save_image(img):
    """存助手页上传的图到 _helper 临时目录，返回路径列表（无图=空）。异常上抛。"""
    if not (img and img.filename):
        return []
    tmp_dir = os.path.join(WORKSPACE, "_helper")
    os.makedirs(tmp_dir, exist_ok=True)
    return [save_image_optimized(img, os.path.join(tmp_dir, datetime.now().strftime("h_%H%M%S")))]


@app.route("/api/helper_understand", methods=["POST"])
def api_helper_understand():
    """助手页·第一步（ChatGPT 引擎）：看图 + 想法 → 只给中文理解(+反问)，先不出提示词。
    对话确认式的前半段：让用户先确认 AI 有没有看懂，再进第二步生成。"""
    if _helper_busy():
        return jsonify({"ok": False, "msg": "当前正在渲染，稍后再用 ChatGPT 精修"}), 409
    if not _helper_chatgpt_ready():
        return jsonify({"ok": False,
                        "msg": "没检测到可用的 ChatGPT（需已启动专用 Chrome 并登录），可切到「本地」模式"}), 400
    intent = (request.form.get("intent") or "").strip()
    try:
        img_paths = _helper_save_image(request.files.get("image"))
    except Exception as e:
        return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400
    client = ChatGPTClient(log=log)
    try:
        client.connect(director_only=True)
        reply = client.send(client.director_page,
                            pe.helper_understand_prompt(intent), image_paths=img_paths)
        parsed = pe.parse_director_reply(reply)
        return jsonify({"ok": True,
                        "understanding_zh": parsed["understanding"],
                        "questions": pe.extract_questions(reply)})
    except ChatGPTError as e:
        return jsonify({"ok": False, "msg": str(e)}), 502
    finally:
        client.close()


@app.route("/api/helper_generate", methods=["POST"])
def api_helper_generate():
    """助手页·第二步（ChatGPT 引擎）：用户已认可/修正上一步的理解 → 据此产出双语提示词。
    以确认过的理解为准绳，确保提示词真正和底图/意图挂钩。"""
    if _helper_busy():
        return jsonify({"ok": False, "msg": "当前正在渲染，稍后再用 ChatGPT 精修"}), 409
    if not _helper_chatgpt_ready():
        return jsonify({"ok": False,
                        "msg": "没检测到可用的 ChatGPT（需已启动专用 Chrome 并登录），可切到「本地」模式"}), 400
    confirmed = (request.form.get("understanding") or "").strip()
    if not confirmed:
        return jsonify({"ok": False, "msg": "还没有已确认的画面理解，请先做第一步「看图理解」"}), 400
    intent = (request.form.get("intent") or "").strip()
    presets = request.form.getlist("presets")
    try:
        img_paths = _helper_save_image(request.files.get("image"))
    except Exception as e:
        return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400
    client = ChatGPTClient(log=log)
    try:
        client.connect(director_only=True)
        reply = client.send(
            client.director_page,
            pe.helper_generate_after_confirm_prompt(confirmed, intent, presets),
            image_paths=img_paths)
        parsed = pe.parse_director_reply(reply)
        return jsonify({"ok": True,
                        "understanding_zh": parsed["understanding"] or confirmed,
                        "prompt_zh": parsed["prompt_zh"],
                        "prompt_en": parsed["prompt_en"]})
    except ChatGPTError as e:
        return jsonify({"ok": False, "msg": str(e)}), 502
    finally:
        client.close()


# ======================================================================
#  本地视觉模型（Ollama）——真·本地部署、离线、零 API key 的识图引擎（需求④）
#  ChatGPT 是首选；这条是没 VPN/没账号时的兜底。未装 Ollama 时优雅降级 + 给一键指引。
# ======================================================================
OLLAMA_URL = "http://127.0.0.1:11434"
# 常见的本地视觉模型名（按识图效果优先排序）；按名字包含匹配已 pull 的模型。
# 注意 Ollama 的实际库名是 qwen2.5vl（无连字符），而选择项/习惯写法常带连字符，
# 故匹配时统一去掉 . 和 -（见 _pick_vision_model），否则 pull 成功也识别不到、误判成“下载失败”。
VISION_MODEL_HINTS = ("qwen2.5vl", "qwen2.5-vl", "qwen2-vl", "minicpm-v", "llama3.2-vision",
                      "llava", "bakllava", "moondream", "gemma3")
VISION_DESCRIBE_PROMPT = (
    "You are an architectural visualization assistant. Describe this architecture "
    "reference image factually and concisely for use as an image-generation base: "
    "building type and massing, number of visible floors, facade materials, window "
    "pattern, surroundings/entourage, camera angle, lighting and time of day. "
    "One dense paragraph, no preamble.")


def _ollama_models() -> list:
    """已 pull 的模型名列表；Ollama 没起/没装则返回空列表。"""
    try:
        r = _local_get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


def _norm_model(s) -> str:
    # 去掉 . - : 再做包含匹配：让 Ollama 库名 qwen2.5vl、写法 qwen2.5-vl、选择项 key
    # qwen2.5vl:3b、实际长名 ...Qwen2.5-VL-3B...:latest 都能互相对上（否则"装了却判成没装"）。
    return str(s or "").lower().replace("-", "").replace(".", "").replace(":", "")


def _pick_vision_model(models: list, prefer: str = "") -> str:
    """挑一个用于识图的已装视觉模型。
    prefer=用户显式选定的模型：只要它确实已 pull，就用它——**不被固定优先级压制**
    （历史 bug：qwen 优先级高于 moondream，两个都装时永远只用 qwen，选了 moondream 也没用）。
    prefer 为空或没装 → 退回按 VISION_MODEL_HINTS 优先级自动挑（老行为）。"""
    if prefer:
        p = _norm_model(prefer)
        for name in models:                       # 双向包含：key 带/不带标签都能对上
            n = _norm_model(name)
            if p and (p in n or n in p):
                return name
    for hint in VISION_MODEL_HINTS:
        h = _norm_model(hint)
        for name in models:
            if h in _norm_model(name):
                return name
    return ""


def _vision_models_available(models: list) -> list:
    """已 pull 且具备识图能力的模型名列表（供前端「切换本地模型」下拉）。"""
    out = []
    for name in models:
        n = _norm_model(name)
        if any(_norm_model(h) in n for h in VISION_MODEL_HINTS):
            out.append(name)
    return out


# ---- 一键安装本地识图（下载并静默安装 Ollama + 拉视觉模型），必须用户同意后才触发 ----
OLLAMA_DEFAULT_MODEL = "moondream"     # 小而快、库里稳定存在；进阶可选 qwen2.5vl
OLLAMA_MODEL_CHOICES = {               # 供前端选择：名字 → 大致体积说明
    "moondream": "约 1.7GB · 小而快，识图够用",
    "qwen2.5vl:3b": "约 3.2GB · 更强的建筑识别（推荐）",
}

# 用户选定的本地识图模型（空=按优先级自动挑）。两个都装时用它决定用哪个，实现「切换」。
_vision_model = os.environ.get("ARA_VISION_MODEL", "").strip()


def get_vision_model() -> str:
    with _lock:
        return _vision_model


def set_vision_model(name: str) -> str:
    """设定本地识图用哪个模型。空字符串=回到自动挑。非法名忽略（当成空）。"""
    global _vision_model
    name = _safe_model_name(name)
    with _lock:
        _vision_model = name
    return name
# 免 VPN 模型源：ModelScope(魔搭) 的 ollama 兼容 GGUF（都含视觉 projector 层，能识图）。
# 键与上面的选择项一一对应；`ollama pull modelscope.cn/...` 在国内免 VPN 即可下载。
# 拉不到（或本就有 VPN）时会自动退回 ollama 官方 registry（见 _pull_model）。
MODELSCOPE_SOURCES = {
    "moondream": "modelscope.cn/ggml-org/moondream2-20250414-GGUF",
    "qwen2.5vl:3b": "modelscope.cn/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
}
OLLAMA_WIN_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
# 安装包免 VPN 源：ghproxy 套 GitHub release → 直连 ollama.com 兜底(有VPN)。
OLLAMA_INSTALLER_URLS_WIN = (
    "https://ghfast.top/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe",
    "https://gh-proxy.com/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe",
    "https://ollama.com/download/OllamaSetup.exe",
)

_vision_setup = {"active": False, "stage": "idle", "log": [], "done": False,
                 "ok": False, "error": "", "model": ""}
_vision_setup_lock = threading.Lock()


def _vlog(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _vision_setup_lock:
        _vision_setup["log"].append(line)
        _vision_setup["log"][:] = _vision_setup["log"][-80:]
    print("[vision-setup]", line)


def _set_stage(stage: str):
    with _vision_setup_lock:
        _vision_setup["stage"] = stage


def _ollama_exe() -> str:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if os.name == "nt" and os.path.isfile(OLLAMA_WIN_EXE):
        return OLLAMA_WIN_EXE
    return ""


def _ollama_up() -> bool:
    try:
        _local_get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def _ollama_installed() -> bool:
    return bool(_ollama_exe()) or _ollama_up()


def _safe_model_name(n) -> str:
    n = str(n or "").strip()
    ok = n and len(n) < 60 and all(c.isalnum() or c in ".-:_/" for c in n)
    return n if ok else ""


@app.route("/api/vision_status")
def api_vision_status():
    """本地识图就绪状态 + 安装进度，供助手页展示与轮询。"""
    models = _ollama_models()
    selected = get_vision_model()
    model = _pick_vision_model(models, prefer=selected)
    available = _vision_models_available(models)
    with _vision_setup_lock:
        setup = dict(_vision_setup)
    return jsonify({
        "installed": _ollama_installed(),
        "running": _ollama_up(),
        "has_vision_model": bool(model),
        "model": model,                    # 实际生效（识图会用）的模型
        "selected_model": selected,        # 用户选定项（空=自动）——供切换下拉回显
        "available": available,            # 已装的视觉模型清单——供「切换本地模型」下拉
        "ready": bool(model),
        "os": os.name,
        "choices": OLLAMA_MODEL_CHOICES,
        "default_model": OLLAMA_DEFAULT_MODEL,
        "setup": setup,
    })


@app.route("/api/set_vision_model", methods=["POST"])
def api_set_vision_model():
    """切换本地识图模型：把已装的某个视觉模型设为当前用的那个（空=自动挑）。"""
    data = request.get_json(silent=True) or {}
    name = set_vision_model(data.get("model"))
    return jsonify({"ok": True, "model": name})


@app.route("/api/vision_setup", methods=["POST"])
def api_vision_setup():
    """用户同意后，一键：下载并静默安装 Ollama（如未装）→ 启动服务 → 拉视觉模型。
    这是**用户显式同意**才触发的重动作（会下载数百 MB~数 GB 并运行安装程序）。"""
    data = request.get_json(silent=True) or {}
    model = _safe_model_name(data.get("model")) or OLLAMA_DEFAULT_MODEL
    with _vision_setup_lock:
        if _vision_setup["active"]:
            return jsonify({"ok": True, "msg": "安装已在进行中，请看进度。"})
        _vision_setup.update({"active": True, "stage": "starting", "log": [],
                              "done": False, "ok": False, "error": "", "model": model})
    threading.Thread(target=_run_vision_setup, args=(model,), daemon=True).start()
    return jsonify({"ok": True, "msg": "已开始准备本地识图，界面会显示进度。"})


def _run_vision_setup(model: str):
    try:
        exe = _ollama_exe()
        if not exe and not _ollama_up():
            _set_stage("installing_ollama")
            _vlog("未检测到 Ollama，开始下载并安装（首次约几百 MB）…")
            if os.name == "nt":
                _install_ollama_windows()
            elif sys.platform == "darwin":
                raise RuntimeError(
                    "macOS 暂不支持自动安装 Ollama。请到 ollama.com 下载安装后，再点一次本按钮。")
            else:
                _install_ollama_linux()
            exe = _ollama_exe()
            if not exe and not _ollama_up():
                raise RuntimeError("Ollama 安装后仍未就绪，请手动确认安装。")
            _vlog("Ollama 安装完成。")

        _set_stage("starting")
        if not _ollama_up():
            _vlog("启动 Ollama 服务…")
            _start_ollama_serve(exe)
            _wait_ollama_up(60)

        _set_stage("pulling_model")
        _vlog(f"开始下载识图模型 {model}（较大、只需一次，之后离线复用）…")
        _pull_model(exe or "ollama", model)
        _vlog(f"识图模型 {model} 就绪，本地识图已可用。")
        with _vision_setup_lock:
            _vision_setup.update({"active": False, "stage": "done", "done": True, "ok": True})
    except Exception as e:
        _vlog(f"失败：{e}")
        with _vision_setup_lock:
            _vision_setup.update({"active": False, "stage": "error", "done": True,
                                  "ok": False, "error": str(e)})


def _install_ollama_windows():
    import tempfile
    import urllib.request
    tmp = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
    # 逐源尝试：ghproxy 国内可达 → 直连 ollama.com 兜底。任一成功即停。
    last_err = ""
    for url in OLLAMA_INSTALLER_URLS_WIN:
        label = "国内镜像" if "github.com" in url else "官方源"
        _vlog(f"下载 OllamaSetup.exe（{label}）…")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ara/1.0"})
            with urllib.request.urlopen(req, timeout=900) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(tmp) < 1_000_000:
                raise RuntimeError("安装包下载不完整")
            break
        except Exception as e:
            last_err = str(e)
            _vlog(f"该源失败（{e}），换下一个…")
    else:
        raise RuntimeError(f"Ollama 安装包全部源都下载失败：{last_err}。可手动到 ollama.com 装。")
    _vlog("运行安装程序（静默、无需管理员）…")
    subprocess.run([tmp, "/VERYSILENT", "/NORESTART"], timeout=900, **_no_window_kwargs())
    for _ in range(30):          # 等安装落地
        if _ollama_exe():
            return
        time.sleep(1)


def _install_ollama_linux():
    _vlog("运行官方安装脚本：curl -fsSL https://ollama.com/install.sh | sh …")
    p = subprocess.run("curl -fsSL https://ollama.com/install.sh | sh",
                       shell=True, timeout=900, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"安装脚本失败：{(p.stderr or '')[-200:]}")


def _start_ollama_serve(exe: str):
    # 注入系统代理：有 VPN/系统代理的用户，serve 拉官方 registry 才能走代理
    # （ollama 是 Go 程序，只认 HTTP(S)_PROXY 环境变量、不读 Windows 注册表系统代理）。
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": _ollama_env()}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        subprocess.Popen([exe or "ollama", "serve"], **kwargs)
    except Exception:
        pass  # Windows 安装后通常已自启服务，起不来也无妨，下一步 _wait_ollama_up 会判定


def _wait_ollama_up(timeout: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ollama_up():
            return
        time.sleep(1)
    raise RuntimeError("Ollama 服务启动超时，请手动运行 `ollama serve` 后重试。")


def _iter_progress(stream):
    """把 ollama 的输出按 \\r 或 \\n 切成一段段再吐出来。
    关键：`ollama pull` 的下载进度是用 \\r 回车**覆盖刷新同一行**、并不换行，
    若按 `for line in stream`（只在 \\n 断行）读，一层下完前收不到任何进度，
    UI 就一直空着、看着像卡死、用户不知道下没下。逐字符按 \\r/\\n 断即可实时刷新。"""
    buf = ""
    while True:
        ch = stream.read(1)
        if ch == "":
            break
        if ch in ("\r", "\n"):
            if buf.strip():
                yield buf.strip()
            buf = ""
        else:
            buf += ch
    if buf.strip():
        yield buf.strip()


def _run_pull(exe: str, ref: str):
    """跑一次 `ollama pull <ref>`，实时把进度写进 _vlog，返回 (返回码, 最后一行)。
    · 必须显式 UTF-8 解码：ollama 进度输出是 UTF-8，Windows 上 text=True 默认按 GBK
      解码会在遇到非 GBK 字节时崩（'gbk' codec can't decode byte 0x8b）；errors=replace 兜底。
    · 注入系统代理，让有 VPN 的用户拉官方 registry 也走代理。
    · Windows 加 CREATE_NO_WINDOW：否则会弹出一个空白黑色控制台（stdout 被 PIPE 走），
      吓人且看着像崩溃——这正是用户报的「下载卡死在一个黑终端」。
    · 进度用 _iter_progress 按 \\r 断行，实时刷新，不再看着卡死。"""
    proc = subprocess.Popen([exe, "pull", ref], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            encoding="utf-8", errors="replace", env=_ollama_env(),
                            **_no_window_kwargs())
    last = ""
    for line in _iter_progress(proc.stdout):
        if line and line != last:
            last = line
            _vlog(line[:120])
    proc.wait()
    return proc.returncode, last


def _pull_model(exe: str, model: str):
    """免 VPN 优先从 ModelScope(魔搭) 拉；失败（或本就有 VPN）再退回 ollama 官方 registry。
    两源都失败才报错。"""
    sources = []
    ms = MODELSCOPE_SOURCES.get(model)
    if ms:
        sources.append(("ModelScope 魔搭", ms))
    sources.append(("Ollama 官方源", model))   # 兜底：有 VPN 时可直连
    last_err = ""
    for label, ref in sources:
        _vlog(f"从「{label}」下载 {ref} …")
        code, last = _run_pull(exe, ref)
        if code == 0:
            _vlog(f"「{label}」下载完成。")
            return
        last_err = last or f"返回码 {code}"
        _vlog(f"「{label}」失败：{last_err[:120]}，换下一个源…")
    raise RuntimeError(f"模型下载失败（ModelScope 与官方源都没成功）：{last_err[-160:]}")


@app.route("/api/helper_vision", methods=["POST"])
def api_helper_vision():
    """本地识图：用本机 Ollama 的视觉模型描述底图，供助手页「本地」引擎拼装提示词。
    未装/未起 Ollama 或没有视觉模型时，返回 ok=False + 安装指引，前端优雅降级。"""
    models = _ollama_models()
    if not models:
        return jsonify({
            "ok": False,
            "reason": "no_ollama",
            "msg": "没检测到本地视觉模型。安装 Ollama（ollama.com）后执行一次："
                   "\n    ollama pull qwen2.5-vl\n即可离线识图、无需账号或 VPN。"
                   "在此之前，可直接在下方想法里描述画面，或改用 ChatGPT 引擎。"}), 200
    model = _pick_vision_model(models, prefer=get_vision_model())
    if not model:
        return jsonify({
            "ok": False,
            "reason": "no_vision_model",
            "msg": f"检测到 Ollama 但没有视觉模型（已装：{', '.join(models[:5])}）。"
                   "执行 `ollama pull qwen2.5-vl` 拉一个带识图能力的模型即可。"}), 200

    img = request.files.get("image")
    if not img or not img.filename:
        return jsonify({"ok": False, "msg": "没有收到图片"}), 400
    tmp_dir = os.path.join(WORKSPACE, "_helper")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        path = save_image_optimized(img, os.path.join(tmp_dir, datetime.now().strftime("v_%H%M%S")))
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        session = requests.Session()
        session.trust_env = False
        resp = session.post(f"{OLLAMA_URL}/api/generate", timeout=180, json={
            "model": model, "prompt": VISION_DESCRIBE_PROMPT,
            "images": [b64], "stream": False})
        desc = (resp.json().get("response") or "").strip()
        if not desc:
            return jsonify({"ok": False, "msg": "本地模型没返回描述，可重试或改用 ChatGPT 引擎"}), 200
        return jsonify({"ok": True, "model": model, "desc": desc})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"本地识图失败：{e}"}), 200


# ======================================================================
#  在线更新（需求⑤）：顶部「检查更新」按钮 → git pull + 重启，连网即得新版
# ======================================================================
def app_version() -> str:
    try:
        with open(os.path.join(APP_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


# —— 免 VPN 的联网源：Gitee 主镜像 → ghproxy 套 GitHub 原址 → 直连 GitHub ——
# 内测用户多半没 VPN，GitHub/registry.ollama.ai 连不上，故国内源优先、直连垫底。
# Gitee 仓库建好后把地址填进 GITEE_REMOTE（或用环境变量 ARA_GITEE_REMOTE），
# 形如 https://gitee.com/<你的用户名>/arch-render-agent.git；留空则自动跳过 Gitee。
GITEE_REMOTE = os.environ.get("ARA_GITEE_REMOTE", "").strip()
# ghproxy 公共代理（免注册、免VPN代理 GitHub）；多给几个互为兜底，挂了一个自动换下一个。
GHPROXY_PREFIXES = ("https://ghfast.top/", "https://gh-proxy.com/")


def _proxy_env() -> dict:
    """给 git/ollama 这类只认环境变量、不读 Windows 系统代理的子进程补上代理。
    进程已有 HTTP(S)_PROXY 就用它；否则读系统代理（Windows 走注册表）。
    这修复了「系统开了代理但 git/ollama 还是直连、连不上」的问题。"""
    env = dict(os.environ)
    if env.get("HTTPS_PROXY") or env.get("https_proxy"):
        return env
    try:
        import urllib.request
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    https = proxies.get("https") or proxies.get("http")
    http = proxies.get("http") or proxies.get("https")
    if https:
        env["HTTPS_PROXY"] = env["https_proxy"] = https
    if http:
        env["HTTP_PROXY"] = env["http_proxy"] = http
    # 本地回环永不走代理：否则 VPN 用户的 ollama pull 连本机 11434 会被代理拦掉（EOF）
    local = "127.0.0.1,localhost,0.0.0.0,::1"
    existing = env.get("NO_PROXY") or env.get("no_proxy") or ""
    merged = (existing + "," + local).strip(",") if existing else local
    env["NO_PROXY"] = env["no_proxy"] = merged
    return env


def _ollama_env() -> dict:
    """给 ollama serve / pull 子进程的环境：代理设置 + 强制回环地址。
    OLLAMA_HOST 强制 127.0.0.1:11434，让 serve 绑定处与 pull 客户端目标一致；
    否则用户机上 serve 绑 127.0.0.1、客户端却从环境继承到 0.0.0.0 → Head 0.0.0.0:11434 EOF。"""
    env = _proxy_env()
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    return env


def _net_log(msg: str):
    """把联网操作（更新/装模型）的失败详情落盘到 logs/app.log，便于事后回溯。
    （更新失败原来只 jsonify 给前端、不留痕，出了问题查不到，这里补上。）"""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [net] {msg}"
    try:
        os.makedirs(os.path.join(APP_DIR, "logs"), exist_ok=True)
        with open(os.path.join(APP_DIR, "logs", "app.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def _git(args: list, timeout: int = 60):
    """在 APP_DIR 里跑一条 git（固定参数，无 shell 注入），返回 (returncode, 输出)。
    注入系统代理环境变量，让有 VPN/系统代理的用户 git 子进程也能走代理。"""
    try:
        p = subprocess.run(["git", *args], cwd=APP_DIR, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=_proxy_env())
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "本机没装 git，无法在线更新。"
    except subprocess.TimeoutExpired:
        return 124, "git 操作超时（可能网络不通）。"
    except Exception as e:
        return 1, str(e)


def _origin_url() -> str:
    code, url = _git(["remote", "get-url", "origin"], timeout=10)
    return url.strip() if code == 0 else ""


def _git_sources() -> list:
    """按优先级返回 [(标签, 远端URL), ...]：Gitee 镜像 → ghproxy(套 GitHub 原址) → 直连 origin。
    国内无 VPN 用户靠前两者；有 VPN 用户任意其一都通，直连兜底。"""
    origin = _origin_url()
    srcs = []
    if GITEE_REMOTE:
        srcs.append(("Gitee 镜像", GITEE_REMOTE))
    if origin.startswith("https://github.com/"):
        for p in GHPROXY_PREFIXES:
            srcs.append(("ghproxy", p + origin))
    if origin:
        srcs.append(("直连 GitHub", origin))
    return srcs


def _git_net(op_args: list, timeout: int = 60):
    """联网 git 操作（fetch/pull/ls-remote）按镜像优先级逐源尝试，直到成功。
    op_args 里用占位符 '__URL__' 表示远端地址。返回 (code, out, 用到的源标签)。"""
    srcs = _git_sources()
    if not srcs:
        return 1, "读不到 origin 远端地址（仓库可能没 .git 或没配 origin）。", ""
    last = "所有源都失败"
    for label, url in srcs:
        args = [url if a == "__URL__" else a for a in op_args]
        code, out = _git(args, timeout=timeout)
        if code == 0:
            if label != "直连 GitHub":
                print(f"[update] 走「{label}」成功。")
            return code, out, label
        last = f"[{label}] {out}"
        print(f"[update] 「{label}」失败：{out[:200]}")
    return 1, last, ""


def _busy_rendering() -> bool:
    return S["state"] in ("connecting", "running", "waiting_confirm",
                          "waiting_clarification", "waiting_feedback", "editing", "stalled")


def _remote_has_branch(branch: str) -> bool:
    """远端是否存在该分支（判断内测分支被合并删除后要不要回退 main）。
    走镜像源，免 VPN 用户也能查；所有源都不通时返回 False（上层会回退 main）。"""
    code, out, _ = _git_net(["ls-remote", "--heads", "__URL__", branch], timeout=30)
    return code == 0 and bool(out.strip())


def _update_branch():
    """选定在线更新要追踪的分支：当前分支若在远端还存在就用它；否则（内测分支合并后
    被删）回退 main，避免老测试机点更新时 couldn't find remote ref 报错。
    返回 (branch, code, err)：code!=0 表示连当前分支都读不出（多半没 .git）。"""
    code, cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
    if code != 0:
        return "", code, cur
    cur = cur.strip() or "main"
    if cur != "main" and not _remote_has_branch(cur):
        return "main", 0, ""
    return cur, 0, ""


@app.route("/api/update_check")
def api_update_check():
    """查远端有没有新版：git fetch 后比对当前分支与 origin/当前分支。"""
    branch, code, err = _update_branch()
    if code != 0:
        _net_log(f"update_check 读取分支失败：{err}")
        msg = ("本机没装 git，无法在线更新。" if code == 127
               else f"读取分支失败：{err}")
        return jsonify({"ok": False, "msg": msg}), 200
    # 拉进本地 origin 跟踪 ref（带 refspec）：无论从哪个镜像拉，下面的落后数都算得准
    code, out, _label = _git_net(
        ["fetch", "--quiet", "__URL__", f"+{branch}:refs/remotes/origin/{branch}"],
        timeout=60)
    if code != 0:
        _net_log(f"update_check fetch 全部源失败：{out}")
        return jsonify({"ok": False, "msg":
            "检查更新失败：GitHub 和国内镜像都连不上。\n"
            "· 如果在国内、没开代理/VPN，可稍后再试或开代理后重试；\n"
            "· 若一直不行，请联系维护者。详情已记录到 logs/app.log。"}), 200
    _, behind = _git(["rev-list", "--count", f"HEAD..origin/{branch}"], timeout=15)
    _, changelog = _git(["log", "--oneline", "-20", f"HEAD..origin/{branch}"], timeout=15)
    _, changed = _git(["diff", "--name-only", f"HEAD..origin/{branch}"], timeout=15)
    deps_changed = any(f.strip() == "requirements.txt" for f in changed.splitlines())
    try:
        n = int(behind.strip())
    except ValueError:
        n = 0
    return jsonify({"ok": True, "current": app_version(), "branch": branch,
                    "behind": n, "changelog": changelog,
                    "deps_changed": deps_changed,   # 本次更新是否动了依赖
                    "has_update": n > 0})


def _restart_process():
    """延迟一点用 execv 就地重启：无论有没有 supervisor 都能加载新代码（PID 不变）。"""
    import time as _t
    _t.sleep(1.0)
    try:
        os.execv(sys.executable, [sys.executable, os.path.join(APP_DIR, "app.py")])
    except Exception:
        os._exit(3)  # execv 失败也退出，让 supervisor 用新代码重新拉起


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


@app.route("/api/update_apply", methods=["POST"])
def api_update_apply():
    """拉取新版并重启。渲染进行中拒绝，避免打断任务。
    若本次更新改了 requirements.txt，则先自动 pip install；装失败就**不重启**
    （避免重启到缺依赖、跑不起来的新代码），改为提示用户手动安装。"""
    if _busy_rendering():
        return jsonify({"ok": False, "msg": "有渲染任务在进行，请先结束/完成再更新"}), 400
    branch, _c, _e = _update_branch()
    branch = branch or "main"
    req_path = os.path.join(APP_DIR, "requirements.txt")
    before_req = _read_bytes(req_path)
    code, out, _label = _git_net(["pull", "--ff-only", "__URL__", branch], timeout=120)
    if code != 0:
        _net_log(f"update_apply pull 全部源失败：{out}")
        return jsonify({"ok": False, "msg":
            "更新失败：GitHub 和国内镜像都连不上，或本地有未提交改动挡住了合并。\n"
            "详情已记录到 logs/app.log。"}), 200
    if "Already up to date" in out or "已经是最新" in out:
        return jsonify({"ok": True, "updated": False, "msg": "已经是最新版本。", "log": out})

    deps_changed = _read_bytes(req_path) != before_req
    deps_installed = None
    if deps_changed:
        log("依赖有变化，正在自动安装新依赖（pip install -r requirements.txt）…")
        try:
            p = subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path],
                               cwd=APP_DIR, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600,
                               env=_proxy_env())
            deps_installed = p.returncode == 0
            pip_tail = (p.stdout + p.stderr).strip()[-600:]
        except Exception as e:
            deps_installed, pip_tail = False, str(e)
        if not deps_installed:
            # 依赖没装上就别重启——新代码可能因缺包崩溃，反而更糟
            log("⚠ 新依赖安装失败，已暂不重启。请手动运行 pip install -r requirements.txt 后重启。")
            return jsonify({
                "ok": False, "updated": True, "deps_changed": True, "deps_installed": False,
                "msg": "代码已更新，但新依赖自动安装失败。请手动运行 "
                       "`pip install -r requirements.txt` 后重启服务。",
                "log": pip_tail}), 200
        log("新依赖安装完成。")

    threading.Thread(target=_restart_process, daemon=True).start()
    msg = "已拉取新版" + ("（含新依赖，已自动安装）" if deps_changed else "") + \
          "，正在重启服务…约 3~5 秒后刷新页面即可。"
    return jsonify({"ok": True, "updated": True, "restarting": True,
                    "deps_changed": deps_changed, "deps_installed": deps_installed,
                    "msg": msg, "log": out})


# ---- 历史管理内部目录（一律以 _ 开头，历史列表自动跳过，避免自我列出）----
TRASH_DIR = os.path.join(WORKSPACE, "_trash")
FAV_FILE = os.path.join(WORKSPACE, "_favorites.json")
HANDOFF_DIR = os.path.join(WORKSPACE, "_handoff")


def _load_favorites() -> list:
    """收藏列表：[{session, image}]。文件缺失/损坏都返回空列表。"""
    try:
        with open(FAV_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_favorites(favs: list):
    os.makedirs(WORKSPACE, exist_ok=True)
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(favs, f, ensure_ascii=False)


@app.route("/api/history")
def api_history():
    """历史成图列表（痛点三）：扫 workspace，列出每个出过图的会话及其所有成图，
    最新的会话排在前面。供界面挑一张满意的当新底图。"""
    favs = {(fv.get("session"), fv.get("image")) for fv in _load_favorites()}
    sessions = []
    if os.path.isdir(WORKSPACE):
        for name in sorted(os.listdir(WORKSPACE), reverse=True):
            if name.startswith("_"):
                continue  # 跳过 _trash / _handoff 等内部目录
            d = os.path.join(WORKSPACE, name)
            if not os.path.isdir(d):
                continue
            imgs = sorted(f for f in os.listdir(d)
                          if f.startswith("iter_") and f.endswith(".png"))
            if not imgs:
                continue  # 没出过图的会话不进历史
            meta = {}
            mp = os.path.join(d, "meta.json")
            if os.path.isfile(mp):
                try:
                    with open(mp, encoding="utf-8") as f:
                        meta = json.load(f)
                except (OSError, ValueError):
                    meta = {}
            sessions.append({
                "session": name,
                "requirement": meta.get("requirement", ""),      # 建筑师最初的命令（需求②）
                "created": meta.get("created", ""),
                "last_prompt_zh": meta.get("last_prompt_zh", ""),  # 最后一版中文提示词
                "last_prompt_en": meta.get("last_prompt_en", ""),  # 最后一版英文提示词
                "images": imgs,
                "favorites": [im for im in imgs if (name, im) in favs],
                "count": len(imgs),
                # 需求⑩：每张成图各自的详细提示词/分析/结论（会话结束后仍可查）
                "item_meta": meta["items"] if isinstance(meta.get("items"), dict) else {},
            })
    return jsonify({"sessions": sessions[:40]})  # 最近 40 个会话，避免列表过长


@app.route("/api/favorites")
def api_favorites():
    """所有收藏的图（供顶部「重点」条展示）。过滤掉已被删除的。"""
    out = []
    for fv in _load_favorites():
        sess, img = fv.get("session"), fv.get("image")
        if sess and img and os.path.isfile(os.path.join(WORKSPACE, sess, img)):
            out.append({"session": sess, "image": img})
    return jsonify({"favorites": out})


@app.route("/api/favorite", methods=["POST"])
def api_favorite():
    """收藏/取消收藏一张图。入参 {session, image, on}。"""
    data = request.get_json(force=True, silent=True) or {}
    sess = _safe_name(data.get("session"))
    img = _safe_name(data.get("image"))
    on = bool(data.get("on", True))
    if not sess or not img:
        return jsonify({"ok": False, "msg": "缺少 session/image"}), 400
    # 收藏前校验图确实存在，避免把不存在的条目写进收藏文件攒垃圾
    if on and not os.path.isfile(os.path.join(WORKSPACE, sess, img)):
        return jsonify({"ok": False, "msg": "要收藏的图不存在"}), 404
    favs = _load_favorites()
    favs = [fv for fv in favs if not (fv.get("session") == sess and fv.get("image") == img)]
    if on:
        favs.append({"session": sess, "image": img})
    _save_favorites(favs)
    return jsonify({"ok": True, "on": on})


# ======================================================================
#  历史删除 + 回收站（单张 / 整会话都可删，均可恢复）
# ======================================================================

def _trash_manifest() -> list:
    try:
        with open(os.path.join(TRASH_DIR, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_trash_manifest(items: list):
    os.makedirs(TRASH_DIR, exist_ok=True)
    with open(os.path.join(TRASH_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


def _drop_favorites(session, image=None):
    """删除会话/图时同步清掉其收藏项。image 为 None 表示整会话。"""
    favs = _load_favorites()
    if image is None:
        favs = [fv for fv in favs if fv.get("session") != session]
    else:
        favs = [fv for fv in favs
                if not (fv.get("session") == session and fv.get("image") == image)]
    _save_favorites(favs)


@app.route("/api/history_delete", methods=["POST"])
def api_history_delete():
    """把一个会话或单张图移入回收站（不真删，可恢复）。入参 {session[, image]}。"""
    data = request.get_json(force=True, silent=True) or {}
    sess = _safe_name(data.get("session"))
    image = _safe_name(data.get("image")) if data.get("image") else ""
    if not sess:
        return jsonify({"ok": False, "msg": "无效的会话"}), 400
    if data.get("image") and not image:
        return jsonify({"ok": False, "msg": "无效的图片名"}), 400
    sess_dir = os.path.join(WORKSPACE, sess)
    if not os.path.isdir(sess_dir) or not _within_workspace(sess_dir):
        return jsonify({"ok": False, "msg": "找不到该会话"}), 404
    tid = datetime.now().strftime("%Y%m%d%H%M%S_") + os.urandom(2).hex()
    dst = os.path.join(TRASH_DIR, tid)
    os.makedirs(TRASH_DIR, exist_ok=True)
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    manifest = _trash_manifest()
    try:
        if image:  # 删单张
            src = os.path.join(sess_dir, image)
            if not os.path.isfile(src):
                return jsonify({"ok": False, "msg": "找不到该图"}), 404
            os.makedirs(dst, exist_ok=True)
            shutil.move(src, os.path.join(dst, image))
            manifest.append({"id": tid, "type": "image", "session": sess,
                             "image": image, "when": when})
            _drop_favorites(sess, image)
        else:       # 删整会话
            shutil.move(sess_dir, dst)
            manifest.append({"id": tid, "type": "session", "session": sess,
                             "when": when})
            _drop_favorites(sess)
    except OSError as e:
        return jsonify({"ok": False, "msg": f"删除失败：{e}"}), 500
    _save_trash_manifest(manifest)
    return jsonify({"ok": True, "id": tid})


@app.route("/api/trash")
def api_trash():
    """回收站列表，最新在前。每项给一张可预览的缩略图。"""
    items = []
    for it in reversed(_trash_manifest()):
        tid = it.get("id", "")
        if it.get("type") == "image":
            thumb = f"/trash_images/{tid}/{it.get('image')}"
        else:
            d = os.path.join(TRASH_DIR, tid)
            first = ""
            if os.path.isdir(d):
                names = sorted(f for f in os.listdir(d)
                               if f.startswith("iter_") and f.endswith(".png"))
                first = names[0] if names else ""
            thumb = f"/trash_images/{tid}/{first}" if first else ""
        items.append({**it, "thumb": thumb})
    return jsonify({"items": items})


@app.route("/api/trash_restore", methods=["POST"])
def api_trash_restore():
    """从回收站恢复一项到原位置。入参 {id}。"""
    tid = os.path.basename(str((request.get_json(force=True, silent=True) or {}).get("id", "")))
    manifest = _trash_manifest()
    entry = next((x for x in manifest if x.get("id") == tid), None)
    if not entry:
        return jsonify({"ok": False, "msg": "回收站里没有这一项"}), 404
    src = os.path.join(TRASH_DIR, tid)
    try:
        if entry["type"] == "image":
            sess_dir = os.path.join(WORKSPACE, entry["session"])
            os.makedirs(sess_dir, exist_ok=True)
            shutil.move(os.path.join(src, entry["image"]),
                        os.path.join(sess_dir, entry["image"]))
            if os.path.isdir(src) and not os.listdir(src):
                os.rmdir(src)
        else:
            dst = os.path.join(WORKSPACE, entry["session"])
            if os.path.exists(dst):
                return jsonify({"ok": False, "msg": "原会话已存在同名，无法恢复"}), 409
            shutil.move(src, dst)
    except OSError as e:
        return jsonify({"ok": False, "msg": f"恢复失败：{e}"}), 500
    _save_trash_manifest([x for x in manifest if x.get("id") != tid])
    return jsonify({"ok": True})


@app.route("/api/trash_empty", methods=["POST"])
def api_trash_empty():
    """彻底清空回收站（真删，不可恢复）。"""
    if os.path.isdir(TRASH_DIR):
        for name in os.listdir(TRASH_DIR):
            p = os.path.join(TRASH_DIR, name)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
    _save_trash_manifest([])
    return jsonify({"ok": True})


@app.route("/trash_images/<tid>/<name>")
def trash_images(tid, name):
    return send_from_directory(os.path.join(TRASH_DIR, os.path.basename(tid)), name)


# ======================================================================
#  两页互传底图（渲染器 ⇄ 提示词助手）
# ======================================================================

@app.route("/api/handoff", methods=["POST"])
def api_handoff():
    """把一张图暂存给另一页取用。form: to=helper|render，
    图片来源二选一：上传 image / 或 from='会话/图名' 的 workspace 图。"""
    to = request.form.get("to", "")
    if to not in ("helper", "render"):
        return jsonify({"ok": False, "msg": "to 必须是 helper 或 render"}), 400
    os.makedirs(HANDOFF_DIR, exist_ok=True)
    dest_noext = os.path.join(HANDOFF_DIR, to)
    try:
        img = request.files.get("image")
        if img and img.filename:
            save_image_optimized(img, dest_noext)
        else:
            src = _resolve_workspace_image(request.form.get("from", ""))
            if not src:
                return jsonify({"ok": False, "msg": "没有可传的图"}), 400
            save_image_optimized_from_path(src, dest_noext)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400
    return jsonify({"ok": True})


@app.route("/api/handoff/<to>")
def api_handoff_get(to):
    """目标页取暂存图；不存在返回 404（页面据此判断有没有待接收的图）。"""
    if to not in ("helper", "render"):
        return jsonify({"ok": False}), 404
    path = os.path.join(HANDOFF_DIR, f"{to}.jpg")
    if not os.path.isfile(path):
        return jsonify({"ok": False}), 404
    # 读进内存再返回、立即释放文件句柄：否则 Windows 上句柄未放，
    # 紧接着的 handoff_clear 删不掉（WinError 32 被占用），暂存图残留、下次又自动填。
    with open(path, "rb") as f:
        data = f.read()
    return Response(data, mimetype="image/jpeg")


@app.route("/api/handoff_clear", methods=["POST"])
def api_handoff_clear():
    """目标页取走后清掉暂存图，避免下次打开又自动填。"""
    to = (request.get_json(force=True, silent=True) or {}).get("to", "")
    if to in ("helper", "render"):
        try:
            os.remove(os.path.join(HANDOFF_DIR, f"{to}.jpg"))
        except OSError:
            pass
    return jsonify({"ok": True})


# ======================================================================
#  素材库：导入本地图片长期存起来，供 ①当意向图 ②配景贴图 ③材质换面（需求⑧素材）
# ======================================================================
ASSETS_DIR = os.path.join(WORKSPACE, "_assets")
ASSET_CATEGORIES = ("意向", "配景", "材质")


def _asset_manifest() -> list:
    try:
        with open(os.path.join(ASSETS_DIR, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_asset_manifest(items: list):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    with open(os.path.join(ASSETS_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


def _save_asset_image(file_storage, dest_noext: str) -> str:
    """存素材图：配景等带透明通道的 PNG **保留透明**（否则贴图会出现黑底），其余压成 JPEG。长边≤2000。"""
    img = Image.open(file_storage.stream)
    img.thumbnail((2000, 2000), Image.LANCZOS)
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        out = dest_noext + ".png"
        img.convert("RGBA").save(out, "PNG")
    else:
        out = dest_noext + ".jpg"
        img.convert("RGB").save(out, "JPEG", quality=88)
    return out


@app.route("/api/assets")
def api_assets():
    """素材列表，可按 ?category= 过滤。最新在前，每项给缩略图 URL（已过滤掉丢失文件）。"""
    cat = request.args.get("category", "")
    out = []
    for it in reversed(_asset_manifest()):
        if cat and it.get("category") != cat:
            continue
        f = it.get("file", "")
        if f and os.path.isfile(os.path.join(ASSETS_DIR, f)):
            out.append({**it, "url": f"/asset_images/{f}"})
    return jsonify({"categories": list(ASSET_CATEGORIES), "assets": out})


@app.route("/api/asset_import", methods=["POST"])
def api_asset_import():
    """导入一张/多张图片存进素材库。form: category(意向/配景/材质) + images(可多张)。"""
    category = request.form.get("category", "")
    if category not in ASSET_CATEGORIES:
        return jsonify({"ok": False, "msg": "分类必须是 意向/配景/材质"}), 400
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        return jsonify({"ok": False, "msg": "没有可导入的图片"}), 400
    os.makedirs(ASSETS_DIR, exist_ok=True)
    manifest = _asset_manifest()
    added = 0
    for f in files:
        aid = datetime.now().strftime("%Y%m%d%H%M%S_") + os.urandom(3).hex()
        try:
            path = _save_asset_image(f, os.path.join(ASSETS_DIR, aid))
        except Exception:
            continue  # 跳过读不了的单张，不影响其余
        manifest.append({"id": aid, "category": category,
                         "name": _safe_name(f.filename) or "素材",
                         "file": os.path.basename(path),
                         "when": datetime.now().strftime("%Y-%m-%d %H:%M")})
        added += 1
    _save_asset_manifest(manifest)
    if not added:
        return jsonify({"ok": False, "msg": "导入失败：图片都无法读取"}), 400
    return jsonify({"ok": True, "added": added})


@app.route("/api/asset_delete", methods=["POST"])
def api_asset_delete():
    """从素材库删除一项（真删——素材是可反复导入的资源，不进回收站）。入参 {id}。"""
    aid = _safe_name((request.get_json(force=True, silent=True) or {}).get("id"))
    if not aid:
        return jsonify({"ok": False, "msg": "无效的素材 id"}), 400
    manifest = _asset_manifest()
    entry = next((x for x in manifest if x.get("id") == aid), None)
    if not entry:
        return jsonify({"ok": False, "msg": "素材不存在"}), 404
    try:
        fp = os.path.join(ASSETS_DIR, entry.get("file", ""))
        if entry.get("file") and os.path.isfile(fp):
            os.remove(fp)
    except OSError:
        pass
    _save_asset_manifest([x for x in manifest if x.get("id") != aid])
    return jsonify({"ok": True})


@app.route("/asset_images/<name>")
def asset_images(name):
    return send_from_directory(ASSETS_DIR, os.path.basename(name))


@app.route("/images/<sess>/<name>")
def images(sess, name):
    return send_from_directory(os.path.join(WORKSPACE, sess), name)


if __name__ == "__main__":
    print(f"建筑渲染智能体启动：http://127.0.0.1:5001  ｜ 版本 {APP_BUILD}")
    app.run(host="127.0.0.1", port=5001, debug=False)
