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
            raise ChatGPTError(
                "导演对话两次都没给出可用的英文提示词。多半是 ChatGPT 网页异常或未真正登录——"
                "请到专用 Chrome 窗口看一眼是否有弹窗/验证，再重试。")
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
            # 发给生图的一律英文：先把中文修改指令翻成英文（纯文本，不耗生图额度）
            tr = client.send(client.director_page,
                             pe.translate_instruction_prompt(instruction))
            instruction_en = pe.parse_director_reply(tr)["prompt_en"] or instruction
            client.new_generation_chat()
            client.send(client.gen_page, pe.regional_edit_message(instruction_en),
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
                        if parsed["prompt_zh"]:
                            prompt_zh = parsed["prompt_zh"]
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
        for j, f in enumerate(request.files.getlist("ref_images")):
            if f and f.filename:
                ref_paths.append(
                    save_image_optimized(f, os.path.join(sess_dir, f"ref_{j}")))
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
                  "error": "", "final_path": ""})
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
    _confirm_event.set()   # 如果正卡在确认关卡，也放行
    return jsonify({"ok": True})


@app.route("/helper")
def helper_page():
    return render_template("helper.html")


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


@app.route("/api/history")
def api_history():
    """历史成图列表（痛点三）：扫 workspace，列出每个出过图的会话及其所有成图，
    最新的会话排在前面。供界面挑一张满意的当新底图。"""
    sessions = []
    if os.path.isdir(WORKSPACE):
        for name in sorted(os.listdir(WORKSPACE), reverse=True):
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
                "requirement": meta.get("requirement", ""),
                "created": meta.get("created", ""),
                "images": imgs,
                "count": len(imgs),
            })
    return jsonify({"sessions": sessions[:40]})  # 最近 40 个会话，避免列表过长


@app.route("/images/<sess>/<name>")
def images(sess, name):
    return send_from_directory(os.path.join(WORKSPACE, sess), name)


if __name__ == "__main__":
    print("建筑渲染智能体启动：http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
