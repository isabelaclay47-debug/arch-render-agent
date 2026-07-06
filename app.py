# -*- coding: utf-8 -*-
"""
建筑渲染智能体 — 本地网页服务

流程：需求+原图(+意向图) → 导演对话扩写全面提示词 → ChatGPT 生图
     → 与原图对比查篡改 → 自动修订提示词 → 每 5 轮暂停等建筑师点评
     → 点评期可在图上圈选区域做局部修改（只改圈内，不动周边）
     → 点"满意"后最终图输出到桌面。
"""
import base64
import os
import shutil
import subprocess
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image

import prompt_engine as pe
from chatgpt_client import CDP_PORT, ChatGPTClient, ChatGPTError

try:
    import winreg
except ImportError:
    winreg = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(APP_DIR, "workspace")
os.makedirs(WORKSPACE, exist_ok=True)

# 每几张图暂停一次等建筑师点评：由界面传入，默认 1（出一张就停，最省额度）
DEFAULT_REVIEW_EVERY = 1

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CHROME_PROFILE = os.path.join(APP_DIR, "chrome-profile")

app = Flask(__name__)

# ---------------- 会话状态（单会话即可） ----------------
S = {
    # idle/connecting/running/waiting_clarification/waiting_feedback/editing/done/error
    "state": "idle",
    "session_id": None,
    "iteration": 0,
    "items": [],              # [{iter, image, kind, analysis, verdict, prompt}]
    "logs": [],
    "questions": "",          # AI 反问建筑师的问题（waiting_clarification 时非空）
    "error": "",
    "final_path": "",
}
_lock = threading.Lock()
_feedback_event = threading.Event()
# type: continue(带点评继续) / satisfied(满意结束) / edit(局部修改)
_feedback = {"type": "continue", "text": "", "edit": None}
_finish_now = threading.Event()
_nudge = threading.Event()  # 人工干预：让正在等待的浏览器操作立刻刷新重查


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with _lock:
        S["logs"].append(line)
        S["logs"][:] = S["logs"][-200:]
    print(line)


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
        wsl_home = _wsl_windows_home()
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


def save_image_optimized(file_storage, dest_noext: str) -> str:
    """压缩上传图：长边≤2000px、JPEG。生图模型吃不下原始大图，
    且 Playwright 无法向 CDP 浏览器传输超过 50MB 的文件。"""
    img = Image.open(file_storage.stream)
    img = img.convert("RGB")
    img.thumbnail((2000, 2000), Image.LANCZOS)
    out = dest_noext + ".jpg"
    img.save(out, "JPEG", quality=88)
    return out


def add_item(i, image, kind, analysis, verdict, prompt):
    with _lock:
        S["items"].append({"iter": i, "image": image, "kind": kind,
                           "analysis": analysis, "verdict": verdict, "prompt": prompt})


# ---------------- 主循环线程 ----------------

def run_session(requirement: str, base_image: str, ref_images: list, sess_dir: str,
                quality: str, ratio: str, review_every: int = DEFAULT_REVIEW_EVERY):
    client = ChatGPTClient(log=log, nudge=_nudge)
    try:
        with _lock:
            S["state"] = "connecting"
        log(f"正在连接 Chrome（调试端口 {CDP_PORT}）…")
        client.connect()
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

        prompt = reply.strip()
        # 首版偶尔过短：模型可能只回了句客套、或网页把输出截断了。别直接判败——
        # 先把原始回复记进日志，再追一刀要求它直接给全文。
        if len(prompt) < 60:
            log(f"首版提示词偏短（{len(prompt)} 字），原始回复：{prompt[:120] or '（空）'}")
            log("追问一次，要求导演直接输出完整提示词…")
            reply = client.send(
                client.director_page,
                "请直接输出你要用于生成的完整建筑渲染提示词本身：中文、具体、不少于 150 字，"
                "覆盖光线时段/材质细节/环境配景/相机质感，末尾附忠实性约束。"
                "不要任何解释或客套，也不要反问。")
            prompt = reply.strip()
        if len(prompt) < 60:
            raise ChatGPTError(
                f"导演对话两次都没返回像样的首版提示词（拿到：{prompt[:80] or '空'}）。"
                "多半是 ChatGPT 网页异常或未真正登录——请到专用 Chrome 窗口看一眼是否有弹窗/验证，再重试。")
        log("第一版提示词已生成。")

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
            else:
                log(f"第 {i} 轮：从原图底图重画（约 1-3 分钟）…")
                gen_msg = pe.generation_message(prompt, quality, ratio)
                gen_base = fidelity_base
            client.new_generation_chat()
            client.send(client.gen_page, gen_msg,
                        image_paths=[gen_base], expect_image=True)
            img_path = os.path.join(sess_dir, f"iter_{i:02d}.png")
            if not client.download_last_image(client.gen_page, img_path):
                raise ChatGPTError(f"第 {i} 轮没有拿到生成图，可能生图额度已用尽。")
            last_gen = img_path
            log(f"第 {i} 轮出图完成，对比原图检查篡改与画质…")
            qc_reply = client.send(client.director_page, pe.qc_and_revise_prompt(i),
                                   image_paths=[fidelity_base, img_path])
            parsed = pe.parse_director_reply(qc_reply)
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
            log(f"第 {i} 轮检查完成（下一轮将{mode_label}）：{(parsed['verdict'] or '无结论')[:80]}")

        def edit_round(edit):
            """一轮局部修改：只改红色标记区域，QC 检查周边有没有被动。"""
            nonlocal fidelity_base, last_gen, next_mode, refine_instruction
            src = os.path.join(sess_dir, edit["source_image"])
            marked = edit["marked_path"]
            instruction = edit["instruction"]
            log(f"第 {i} 轮（局部修改）：只修改标记区域——{instruction[:50]}…")
            client.new_generation_chat()
            client.send(client.gen_page, pe.regional_edit_message(instruction),
                        image_paths=[src, marked], expect_image=True)
            img_path = os.path.join(sess_dir, f"iter_{i:02d}.png")
            if not client.download_last_image(client.gen_page, img_path):
                raise ChatGPTError(f"局部修改第 {i} 轮没有拿到生成图。")
            log("局部修改出图完成，检查标记区域外是否被动…")
            qc_reply = client.send(client.director_page,
                                   pe.regional_qc_message(instruction),
                                   image_paths=[src, img_path])
            parsed = pe.parse_director_reply(qc_reply)
            add_item(i, f"iter_{i:02d}.png", "edit",
                     parsed["analysis"] or "（未解析出分析内容）",
                     parsed["verdict"], f"（局部修改）{instruction}")
            # 建筑师批准的修改结果成为新的忠实性参照与后续底图；下一轮从它重画一次校准
            fidelity_base = img_path
            last_gen = img_path
            next_mode = "redraw"
            refine_instruction = ""
            log(f"局部修改检查完成：{(parsed['verdict'] or '无结论')[:80]}")

        finished = False
        while not finished:
            # 一批自动迭代：每 review_every 张暂停一次等点评（建筑师在界面上设定）
            for _ in range(max(1, review_every)):
                i += 1
                with _lock:
                    S["iteration"] = i
                gen_round()
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
                    edit_round(_feedback["edit"])
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
                        log("提示词已按点评修订。")
                    else:
                        log("警告：点评后未解析出新提示词，沿用上一版。")
                    # 点评是方向性调整，下一轮从原图按新提示词重画，不在旧图上精修
                    next_mode = "redraw"
                    refine_instruction = ""
                break

        # 输出最终图到桌面
        if not S["items"]:
            raise ChatGPTError("任务结束时还没有任何生成图，无图可输出。")
        last_img = os.path.join(sess_dir, S["items"][-1]["image"])
        out = os.path.join(desktop_path(),
                           f"渲染结果_{datetime.now().strftime('%m%d_%H%M')}.png")
        shutil.copyfile(last_img, out)
        with _lock:
            S["state"] = "done"
            S["final_path"] = out
        log(f"完成！最终图已放到桌面：{out}")

    except ChatGPTError as e:
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
        client.close()


# ---------------- 路由 ----------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    if S["state"] in ("connecting", "running", "waiting_clarification",
                      "waiting_feedback", "editing"):
        return jsonify({"ok": False, "msg": "已有任务在运行"}), 400

    requirement = request.form.get("requirement", "").strip()
    base = request.files.get("base_image")
    if not requirement or not base:
        return jsonify({"ok": False, "msg": "需求描述和原图都是必填的"}), 400

    sess_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    sess_dir = os.path.join(WORKSPACE, sess_id)
    os.makedirs(sess_dir, exist_ok=True)

    try:
        base_path = save_image_optimized(base, os.path.join(sess_dir, "base"))
        ref_paths = []
        for j, f in enumerate(request.files.getlist("ref_images")):
            if f and f.filename:
                ref_paths.append(
                    save_image_optimized(f, os.path.join(sess_dir, f"ref_{j}")))
    except Exception as e:
        return jsonify({"ok": False, "msg": f"图片无法读取：{e}"}), 400

    with _lock:
        S.update({"state": "connecting", "session_id": sess_id, "iteration": 0,
                  "items": [], "logs": [], "questions": "",
                  "error": "", "final_path": ""})
    _feedback_event.clear()
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
                           review_every),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify(S)


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

    _feedback["type"] = "edit"
    _feedback["text"] = ""
    _feedback["edit"] = {"source_image": os.path.basename(source_image),
                         "marked_path": marked_path,
                         "instruction": instruction}
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


@app.route("/api/chrome_status")
def api_chrome_status():
    """检测专用 Chrome 与 ChatGPT 登录状态：chrome_off / not_logged_in / ready。"""
    if S["state"] in ("connecting", "running", "waiting_clarification",
                      "waiting_feedback", "editing"):
        return jsonify({"status": "ready", "detail": "渲染任务运行中，连接正常"})
    try:
        _local_get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
    except Exception:
        return jsonify({"status": "chrome_off", "detail": "专用 Chrome 未启动"})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            page = None
            for c in browser.contexts:
                page = next((p for p in c.pages if "chatgpt.com" in p.url), None)
                if page:
                    break
            if page is None:
                try:
                    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                    page = ctx.new_page()
                    page.goto("https://chatgpt.com/", wait_until="domcontentloaded",
                              timeout=30000)
                except Exception:
                    return jsonify({"status": "conflict",
                                    "detail": f"{CDP_PORT} 端口被另一个调试浏览器占用——"
                                              "关掉那个程序后再点「检测」"})
            try:
                page.wait_for_selector("#prompt-textarea", timeout=8000)
                return jsonify({"status": "ready", "detail": "ChatGPT 已登录，就绪"})
            except Exception:
                return jsonify({"status": "not_logged_in",
                                "detail": "Chrome 已启动，但 ChatGPT 未登录（去那个窗口登录一次）"})
    except Exception as e:
        return jsonify({"status": "chrome_off", "detail": f"连接失败：{e}"})


@app.route("/api/launch_chrome", methods=["POST"])
def api_launch_chrome():
    """一键启动带调试端口的专用 Chrome。"""
    chrome = _find_chrome()
    if not chrome:
        return jsonify({"ok": False,
                        "msg": "没找到 Chrome，请确认已安装 Google Chrome"}), 400
    subprocess.Popen([chrome, f"--remote-debugging-port={CDP_PORT}",
                      f"--user-data-dir={_chrome_profile_arg(chrome)}",
                      "--no-first-run", "--no-default-browser-check",
                      "https://chatgpt.com/"])
    return jsonify({"ok": True})


@app.route("/api/nudge", methods=["POST"])
def api_nudge():
    """ChatGPT 网页卡死时的人工干预：让程序立刻刷新页面重新检查，然后继续任务。"""
    if S["state"] not in ("connecting", "running", "editing"):
        return jsonify({"ok": False, "msg": "现在没有正在等待的浏览器操作"}), 400
    log("收到人工干预：将刷新 ChatGPT 页面并重新检查结果。")
    _nudge.set()
    return jsonify({"ok": True})


@app.route("/api/finish_now", methods=["POST"])
def api_finish_now():
    _finish_now.set()
    _feedback_event.set()  # 如果正卡在点评等待，也放行
    return jsonify({"ok": True})


@app.route("/images/<sess>/<name>")
def images(sess, name):
    return send_from_directory(os.path.join(WORKSPACE, sess), name)


if __name__ == "__main__":
    print("建筑渲染智能体启动：http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
