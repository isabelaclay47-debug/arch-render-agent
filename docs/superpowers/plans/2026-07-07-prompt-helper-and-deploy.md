# 提示词助手页 + 拖拽上传 + 开机自启 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给没有 ChatGPT 账号/VPN 的人一个能识图、能生成中英专业提示词的助手页（默认 ChatGPT、可切本地），并加全站拖拽上传与手动开机自启。

**Architecture:** 复用现有 Flask + prompt_engine 知识底座。助手页默认走服务器端导演对话（`/api/helper_refine`）；切「本地」时浏览器用 transformers.js 跑 Florence-2-large 识图，再由服务器端确定性拼装（`/api/helper_build`），全程离线免 VPN。拖拽是纯前端；开机自启是手动 `.bat`/`.command` 脚本注册计划任务/launchd。

**Tech Stack:** Python 3 / Flask / Pillow / Playwright（已有）；pytest（新增，测试用）；transformers.js + Florence-2-large ONNX（浏览器，新增）；Windows schtasks / macOS launchd。

参考 spec：`docs/superpowers/specs/2026-07-07-prompt-helper-and-deploy-design.md`

---

## 文件结构

- 修改 `prompt_engine.py` — 新增 `build_prompt_locally()` 确定性拼装（纯逻辑，可单测）。
- 修改 `app.py` — 新增 `/helper`、`/api/helper_build`、`/api/helper_refine`、`/vendor/...`、`/models/...` 路由；helper_refine 的忙/未就绪守卫与临时图安全落盘。
- 修改 `chatgpt_client.py` — `connect(director_only=False)` 参数，一次性精修只开导演页。
- 新建 `templates/helper.html` — 助手页（引擎切换、拖拽、储备库勾选、Florence 识图、结果复制）。
- 新建 `scripts/fetch_assets.py` — 从国内镜像下载 transformers.js 运行库 + Florence-2 权重到 `static/vendor/`、`models/`。
- 修改 `templates/index.html` — 原图/意向图 drop 区加拖拽。
- 修改 `双击启动.bat` / `双击启动-Mac.command` — 首次运行调用 `fetch_assets.py`。
- 新建 `开机自启-开.bat` / `开机自启-关.bat` / `开机自启-开-Mac.command` / `开机自启-关-Mac.command`。
- 新建 `tests/test_prompt_engine.py`、`tests/test_helper_api.py`。
- 修改 `requirements.txt` — 新增 `pytest`（dev）。
- 修改 `.gitignore` — 忽略 `models/`、`static/vendor/`（体积大，走安装下载）。

**执行顺序**：先做独立小功能（Phase 1 拖拽、Phase 2 开机自启）拿到快速可用成果，再做助手页（Phase 3 本地引擎 → Phase 4 后端 → Phase 5 前端 → Phase 6 模型资产）。

---

## Phase 1 — 全站拖拽上传（纯前端，最快见效）

### Task 1: 主页原图/意向图支持拖拽

**Files:**
- Modify: `templates/index.html`（`preview` 函数附近的 `<script>`，及两个 `.drop` 元素）

- [ ] **Step 1: 给两个 drop 区加 id**

把 `templates/index.html` 里两处 `.drop` 开标签改成带 id（便于绑定拖拽）：

原图那个：
```html
      <div class="drop" id="baseDrop" onclick="baseInput.click()">
```
意向图那个：
```html
      <div class="drop" id="refDrop" onclick="refInput.click()">
```

- [ ] **Step 2: 加拖拽高亮样式**

在 `<style>` 末尾（`</style>` 前）加：
```css
  .drop.dragover { border-color: var(--wine); color: var(--wine); background: #fff; }
```

- [ ] **Step 3: 加拖拽绑定函数并调用**

在 `templates/index.html` 的 `<script>` 里，`function preview(...)` 定义之后加：
```javascript
// 拖拽上传：把拖入的文件塞进对应 <input type=file> 再走既有 preview
function enableDrop(dropId, input, boxId) {
  const drop = $(dropId);
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation(); drop.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation(); drop.classList.remove("dragover");
  }));
  drop.addEventListener("drop", e => {
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    const dt = new DataTransfer();
    const list = input.multiple ? files : [files[0]];
    for (const f of list) if (f.type.startsWith("image/")) dt.items.add(f);
    input.files = dt.files;
    preview(input, boxId);
  });
}
enableDrop("baseDrop", $("baseInput"), "baseThumbs");
enableDrop("refDrop", $("refInput"), "refThumbs");
```

- [ ] **Step 4: 手动验证**

启动服务（`.venv/bin/python supervisor.py &`，等 5001 起来），浏览器开 `http://127.0.0.1:5001/`：
- 从文件管理器拖一张图到「原图」框 → 框高亮、松手后出现缩略图、提示变「已选 1 张」。
- 拖多张到「意向图」框 → 多张缩略图出现。
Expected：拖拽与点击选择行为一致。

- [ ] **Step 5: 提交**
```bash
git add templates/index.html
git commit -m "feat: 主页原图/意向图支持拖拽上传"
```

---

## Phase 2 — 开机自启（手动开关脚本）

### Task 2: Windows 开机自启开/关脚本

**Files:**
- Create: `开机自启-开.bat`, `开机自启-关.bat`

- [ ] **Step 1: 写「开」脚本**

`开机自启-开.bat`：
```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 开机自启 - 开
set "PYW=%~dp0.venv-win\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv-win\Scripts\python.exe"
if not exist "%PYW%" (
  echo 还没安装环境，请先双击「双击启动.bat」跑一次，再来开启自启。
  pause & exit /b 1
)
echo 正在注册「登录时自动在后台启动建筑渲染智能体」...
schtasks /Create /TN "ArchRenderAgent" /TR "\"%PYW%\" \"%~dp0supervisor.py\"" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 ( echo 注册失败（可能需要允许权限）。 & pause & exit /b 1 )
echo 完成：下次登录 Windows 就会自动在后台待命。要关闭请双击「开机自启-关.bat」。
pause
```

- [ ] **Step 2: 写「关」脚本**

`开机自启-关.bat`：
```bat
@echo off
chcp 65001 >nul
title 开机自启 - 关
echo 正在取消开机自启...
schtasks /Delete /TN "ArchRenderAgent" /F
if errorlevel 1 ( echo 未找到自启任务，或已经关闭。 ) else ( echo 已取消开机自启。 )
pause
```

- [ ] **Step 3: 手动验证（Windows）**

双击 `开机自启-开.bat` → 提示注册成功；运行 `schtasks /Query /TN ArchRenderAgent` 能查到。
双击 `开机自启-关.bat` → 再 `schtasks /Query /TN ArchRenderAgent` 应报「找不到」。
Expected：开→有任务，关→无任务。（若无 Windows 环境，此步在部署机上验收。）

- [ ] **Step 4: 提交**
```bash
git add 开机自启-开.bat 开机自启-关.bat
git commit -m "feat: Windows 手动开机自启开/关脚本（默认不自启）"
```

### Task 3: macOS 开机自启开/关脚本

**Files:**
- Create: `开机自启-开-Mac.command`, `开机自启-关-Mac.command`

- [ ] **Step 1: 写「开」脚本**

`开机自启-开-Mac.command`：
```bash
#!/bin/bash
cd "$(dirname "$0")" || exit 1
PLIST="$HOME/Library/LaunchAgents/com.archrender.agent.plist"
PY="$PWD/.venv/bin/python"
if [ ! -x "$PY" ]; then echo "请先双击「双击启动-Mac.command」装好环境再来。"; read -n 1; exit 1; fi
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.archrender.agent</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$PWD/supervisor.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>$PWD</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST" && echo "已开启开机自启。要关闭请双击「开机自启-关-Mac.command」。"
read -n 1
```

- [ ] **Step 2: 写「关」脚本**

`开机自启-关-Mac.command`：
```bash
#!/bin/bash
PLIST="$HOME/Library/LaunchAgents/com.archrender.agent.plist"
launchctl unload "$PLIST" 2>/dev/null
rm -f "$PLIST" && echo "已取消开机自启。" || echo "本来就没开启。"
read -n 1
```

- [ ] **Step 3: 赋可执行权限并验证**
```bash
chmod +x 开机自启-开-Mac.command 开机自启-关-Mac.command
```
（macOS 部署机上）双击「开」→ `launchctl list | grep archrender` 有条目；双击「关」→ 该条目消失。

- [ ] **Step 4: 提交**
```bash
git add 开机自启-开-Mac.command 开机自启-关-Mac.command
git commit -m "feat: macOS 手动开机自启开/关脚本（launchd）"
```

---

## Phase 3 — 本地提示词拼装（纯 Python，TDD）

### Task 4: 安装 pytest 并建测试目录

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`

- [ ] **Step 1: requirements 加 pytest**

`requirements.txt` 末尾追加一行：
```
pytest>=8,<9
```

- [ ] **Step 2: 装依赖 + 建目录**
```bash
.venv/bin/python -m pip install "pytest>=8,<9"
mkdir -p tests && touch tests/__init__.py
```
Expected：pytest 安装成功。

- [ ] **Step 3: 提交**
```bash
git add requirements.txt tests/__init__.py
git commit -m "chore: 引入 pytest 与 tests 目录"
```

### Task 5: `build_prompt_locally` 确定性拼装

**Files:**
- Modify: `prompt_engine.py`（在文件末尾"四、解析"之前或之后新增一节）
- Test: `tests/test_prompt_engine.py`

- [ ] **Step 1: 写失败测试**

`tests/test_prompt_engine.py`：
```python
# -*- coding: utf-8 -*-
import prompt_engine as pe


def test_build_prompt_locally_returns_three_parts():
    out = pe.build_prompt_locally(
        intent="黄昏暖光，玻璃幕墙要有真实反射",
        image_desc="A modern glass office building, dusk",
        preset_texts=["低反射 Low-E 玻璃，竖梃清晰"],
    )
    assert set(out) == {"understanding_zh", "prompt_zh", "prompt_en"}


def test_build_prompt_locally_injects_english_baseline():
    out = pe.build_prompt_locally("随便", "", [])
    # 英文提示词必须强制附带通用底线（和主功能同一套）
    assert pe.GENERATION_BASICS in out["prompt_en"]


def test_build_prompt_locally_includes_user_and_presets():
    out = pe.build_prompt_locally(
        intent="加行人和行道树",
        image_desc="street view",
        preset_texts=["石材立面细节：分缝对齐"],
    )
    assert "加行人和行道树" in out["prompt_zh"]
    assert "石材立面细节：分缝对齐" in out["prompt_zh"]
    assert "street view" in out["prompt_en"]


def test_build_prompt_locally_handles_empty_gracefully():
    out = pe.build_prompt_locally("", "", [])
    assert out["prompt_zh"].strip()      # 不因空输入而产出空串
    assert out["prompt_en"].strip()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_prompt_engine.py -v`
Expected: FAIL，`AttributeError: module 'prompt_engine' has no attribute 'build_prompt_locally'`

- [ ] **Step 3: 实现**

在 `prompt_engine.py` 末尾追加：
```python
# ======================================================================
#  五、本地确定性拼装（助手页"本地模式"：无 LLM、不联网）
# ======================================================================

def build_prompt_locally(intent: str, image_desc: str, preset_texts=None) -> dict:
    """把「用户想法 + 本地识图描述 + 勾选的储备库文本」确定性地拼装成中英双语提示词。
    与自动生成共用同一套专业知识底座（骨架 / 储备库 / 英文底线），但不调用任何 LLM。"""
    preset_texts = [t.strip() for t in (preset_texts or []) if t and t.strip()]
    intent = (intent or "").strip()
    image_desc = (image_desc or "").strip()

    # 中文提示词：想法 + 识图 + 勾选模块，按可读顺序组织
    zh_parts = []
    if intent:
        zh_parts.append(f"【建筑师想法】{intent}")
    if image_desc:
        zh_parts.append(f"【底图画面】{image_desc}")
    if preset_texts:
        zh_parts.append("【专业要求】\n- " + "\n- ".join(preset_texts))
    if not zh_parts:
        zh_parts.append("在严格保持原图建筑形体的前提下，提升材质真实感、光影与画面质感，"
                        "达到专业建筑摄影质感。")
    prompt_zh = "\n".join(zh_parts)

    # 英文提示词：把可英文化的部分并入，末尾强制附加通用英文底线
    en_bits = []
    if image_desc:
        en_bits.append(f"Base scene: {image_desc}.")
    if intent:
        en_bits.append(f"Architect's intent (translate faithfully): {intent}.")
    if preset_texts:
        en_bits.append("Professional requirements: " + " ".join(preset_texts))
    en_head = " ".join(en_bits) if en_bits else (
        "Improve material realism, lighting and overall quality while keeping the "
        "building form pixel-faithful to the base image.")
    prompt_en = f"{en_head}\n\n{GENERATION_BASICS}"

    understanding_zh = (
        "我据此把你的想法、底图画面和勾选的专业模块，整理成了下面这份完整的中英提示词——"
        "你可以直接复制英文版拿去生图工具里用。")
    return {"understanding_zh": understanding_zh,
            "prompt_zh": prompt_zh, "prompt_en": prompt_en}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_prompt_engine.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**
```bash
git add prompt_engine.py tests/test_prompt_engine.py
git commit -m "feat: 本地确定性提示词拼装 build_prompt_locally + 单测"
```

---

## Phase 4 — 助手页后端

### Task 6: `chatgpt_client.connect` 支持只开导演页

**Files:**
- Modify: `chatgpt_client.py:51-73`（`connect` 方法）

- [ ] **Step 1: 改 connect 签名与逻辑**

把 `def connect(self):` 改为 `def connect(self, director_only: bool = False):`，并把开 gen_page 的两处放到条件里。定位现有：
```python
        try:
            self.director_page = self._ctx.new_page()
            self.gen_page = self._ctx.new_page()
        except Exception as e:
```
改为：
```python
        try:
            self.director_page = self._ctx.new_page()
            if not director_only:
                self.gen_page = self._ctx.new_page()
        except Exception as e:
```
并把结尾：
```python
        self._open_chat(self.director_page)
        self._check_logged_in(self.director_page)
        self._open_chat(self.gen_page)  # 立即导航，别留一个吓人的 about:blank
```
改为：
```python
        self._open_chat(self.director_page)
        self._check_logged_in(self.director_page)
        if not director_only:
            self._open_chat(self.gen_page)  # 立即导航，别留一个吓人的 about:blank
```

- [ ] **Step 2: 冒烟：导入无误**

Run: `.venv/bin/python -c "import chatgpt_client; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**
```bash
git add chatgpt_client.py
git commit -m "feat: ChatGPTClient.connect 支持 director_only（一次性精修不开生图页）"
```

### Task 7: `/api/helper_build` 端点（本地拼装，TDD）

**Files:**
- Modify: `app.py`（新增路由，`/api/history` 附近）
- Test: `tests/test_helper_api.py`

- [ ] **Step 1: 写失败测试**

`tests/test_helper_api.py`：
```python
# -*- coding: utf-8 -*-
import json
import app as appmod


def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_helper_build_returns_bilingual_prompt():
    c = client()
    r = c.post("/api/helper_build", json={
        "intent": "黄昏暖光",
        "image_desc": "modern glass building at dusk",
        "presets": ["低反射 Low-E 玻璃"],
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "黄昏暖光" in data["prompt_zh"]
    assert "modern glass building at dusk" in data["prompt_en"]
    assert appmod.pe.GENERATION_BASICS in data["prompt_en"]


def test_helper_build_empty_ok():
    c = client()
    r = c.post("/api/helper_build", json={"intent": "", "image_desc": "", "presets": []})
    assert r.status_code == 200
    assert r.get_json()["prompt_en"].strip()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_api.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现路由**

在 `app.py` 的 `@app.route("/api/history")` 定义**之前**加：
```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_api.py -v`
Expected: 2 passed
（注意：`helper_page` 路由此刻会因缺 `templates/helper.html` 在浏览器访问时报错，但 build 测试不触达它。）

- [ ] **Step 5: 提交**
```bash
git add app.py tests/test_helper_api.py
git commit -m "feat: /api/helper_build 本地提示词端点 + 测试"
```

### Task 8: `/api/helper_refine` 忙/未就绪守卫（TDD）

**Files:**
- Modify: `app.py`（新增路由）
- Test: `tests/test_helper_api.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_helper_api.py` 追加：
```python
def test_helper_refine_blocked_when_rendering(monkeypatch):
    c = client()
    appmod.S["state"] = "running"           # 模拟主渲染进行中
    try:
        r = c.post("/api/helper_refine", data={"draft_prompt": "x"})
        assert r.status_code == 409
        assert r.get_json()["ok"] is False
    finally:
        appmod.S["state"] = "idle"


def test_helper_refine_requires_chatgpt_ready(monkeypatch):
    c = client()
    appmod.S["state"] = "idle"
    # 强制 chrome 检测为未就绪
    monkeypatch.setattr(appmod, "_helper_chatgpt_ready", lambda: False)
    r = c.post("/api/helper_refine", data={"draft_prompt": "x"})
    assert r.status_code == 400
    assert "ChatGPT" in r.get_json()["msg"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_api.py -v`
Expected: FAIL（404 / 无 `_helper_chatgpt_ready`）

- [ ] **Step 3: 实现路由 + 就绪探测 + 一次性精修**

在 `app.py` 新增（`api_helper_build` 之后）：
```python
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
        return jsonify({"ok": False, "msg": "没检测到可用的 ChatGPT（需已启动专用 Chrome 并登录）"
                        "，可切到「本地」模式"}), 400

    draft = (request.form.get("draft_prompt") or "").strip()
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
                            pe.helper_refine_prompt(draft), image_paths=img_paths)
        parsed = pe.parse_director_reply(reply)
        return jsonify({"ok": True,
                        "understanding_zh": parsed["understanding"],
                        "prompt_zh": parsed["prompt_zh"],
                        "prompt_en": parsed["prompt_en"]})
    except ChatGPTError as e:
        return jsonify({"ok": False, "msg": str(e)}), 502
    finally:
        client.close()
```

在 `prompt_engine.py` 追加（供上面调用）：
```python
def helper_refine_prompt(draft: str) -> str:
    """助手页精修：让导演看用户上传的图 + 草稿，产出专业版三段提示词。"""
    draft_block = f"\n\n【用户的初步想法/草稿】\n{draft}" if draft.strip() else ""
    return f"""你是资深建筑可视化提示词导演。用户上传了一张图作为底图参照。请**仔细看图**，
识别建筑类型、材质、光线、构图与风格，结合用户草稿，产出一份专业、具体、可执行的生图提示词。{draft_block}

{_BILINGUAL_OUTPUT_SPEC}"""
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_api.py -v`
Expected: 4 passed

- [ ] **Step 5: 忽略临时目录并提交**

在 `.gitignore` 的 `workspace/` 已覆盖 `_helper`（它在 workspace 下），无需额外条目。
```bash
git add app.py prompt_engine.py tests/test_helper_api.py
git commit -m "feat: /api/helper_refine 借导演对话看图精修 + 忙/就绪守卫 + 测试"
```

---

## Phase 5 — 助手页前端

### Task 9: helper.html 骨架（引擎切换 + 储备库 + 结果复制）

**Files:**
- Create: `templates/helper.html`

- [ ] **Step 1: 写页面骨架**

`templates/helper.html`（复用主页色板；`PROMPT_LIBRARY` 内联复制一份，避免跨页依赖）：
```html
<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>提示词助手 · 建筑渲染</title>
<style>
  :root{--cream:#EFE8DB;--paper:#FAF6EE;--sand:#D5CBBA;--taupe:#A79C93;--wine:#5B4144;--ink:#48423B;}
  *{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--ink);
    font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;padding:26px;max-width:900px;margin:0 auto}
  h1{font-size:22px;color:var(--wine)} .card{background:var(--paper);border:1px solid var(--sand);
    border-radius:4px;padding:18px;margin-bottom:16px}
  textarea{width:100%;min-height:80px;border:1px solid var(--sand);border-radius:3px;padding:10px;font:13px/1.6 inherit}
  .drop{border:1px dashed var(--taupe);border-radius:3px;padding:22px;text-align:center;color:var(--taupe);cursor:pointer;background:#fff}
  .drop.dragover{border-color:var(--wine);color:var(--wine)} .drop img{max-width:220px;max-height:160px;margin-top:10px;border-radius:2px}
  .engine{display:flex;gap:8px;margin-bottom:12px} .engine button{padding:8px 16px;border:1px solid var(--sand);
    background:#fff;border-radius:999px;cursor:pointer;font-size:13px} .engine button.on{background:var(--wine);color:var(--cream);border-color:var(--wine)}
  .pills{display:flex;gap:6px;flex-wrap:wrap} .pills label{padding:6px 12px;border:1px solid var(--sand);border-radius:999px;font-size:12px;cursor:pointer}
  .pills input{display:none} .pills input:checked+span{color:var(--wine);font-weight:600}
  button.go{background:var(--wine);color:var(--cream);border:0;border-radius:3px;padding:12px 22px;font-size:14px;cursor:pointer;width:100%}
  pre{white-space:pre-wrap;background:#fff;border:1px solid var(--sand);border-radius:3px;padding:12px;font-size:12.5px}
  .muted{color:var(--taupe);font-size:12px} .hidden{display:none}
</style></head><body>
<h1>提示词助手 <span class="muted">— 拖图进来，帮你写出专业提示词</span></h1>

<div class="card">
  <div class="engine">
    <button id="engChat" class="on" onclick="setEngine('chat')">ChatGPT（专业级 · 需账号+VPN）</button>
    <button id="engLocal" onclick="setEngine('local')">本地（免账号/免 VPN）</button>
  </div>
  <div id="engHint" class="muted"></div>
</div>

<div class="card">
  <div class="drop" id="drop" onclick="fileInput.click()">
    <input type="file" id="fileInput" accept="image/*" class="hidden" onchange="onPick(this.files[0])">
    <span id="dropHint">点击或拖拽一张图片进来</span>
    <div id="dropPrev"></div>
  </div>
  <div id="descBox" class="muted" style="margin-top:8px"></div>
</div>

<div class="card">
  <label class="muted">你的想法（一句话即可）</label>
  <textarea id="intent" placeholder="例如：黄昏暖光，玻璃幕墙要有真实反射，前景加行人。"></textarea>
  <label class="muted" style="display:block;margin-top:10px">专业储备库（点选增强）</label>
  <div class="pills" id="presets"></div>
</div>

<button class="go" onclick="generate()">生成提示词</button>

<div class="card hidden" id="result" style="margin-top:16px">
  <div id="understanding" class="muted" style="margin-bottom:10px"></div>
  <label class="muted">中文提示词</label><pre id="zh"></pre>
  <label class="muted">英文提示词（复制这段拿去生图）</label><pre id="en"></pre>
  <button class="go" onclick="copyEn()" style="background:var(--ink)">📋 复制英文提示词</button>
</div>

<script src="/static/helper.js"></script>
</body></html>
```

- [ ] **Step 2: 手动验证页面可渲染**

启动服务后开 `http://127.0.0.1:5001/helper` → 页面出现（此时 `helper.js` 404、交互未通，属正常，下一步补）。
Expected：HTTP 200、布局正常显示。

- [ ] **Step 3: 提交**
```bash
git add templates/helper.html
git commit -m "feat: 助手页 helper.html 骨架（引擎切换/拖拽/储备库/结果）"
```

### Task 10: helper.js 交互（引擎切换、拖拽、生成、复制）

**Files:**
- Create: `static/helper.js`

- [ ] **Step 1: 写交互脚本（不含 Florence，先接通本地拼装与 ChatGPT 分支）**

`static/helper.js`：
```javascript
const $ = id => document.getElementById(id);
let engine = "chat", pickedFile = null, imageDesc = "";
const PRESETS = [
  ["写实日景","照片级建筑写实日景：自然白天漫射光，柔和阴影，真实玻璃反射，材质细节清晰，专业建筑摄影后期，避免CG塑料感。"],
  ["黄金时刻","黄金时刻建筑摄影：低角度暖光，长阴影，玻璃暖冷反差，天空轻微渐变，氛围温暖但不过度电影化。"],
  ["玻璃幕墙","玻璃幕墙细节：低反射 Low-E 玻璃，室内暗部层次可见，竖梃横梁清晰，不做假蓝玻璃。"],
  ["石材立面","石材立面细节：浅米白或灰白石材，细微颗粒、分缝对齐、边缘倒角，避免塑料白墙。"],
  ["清水混凝土","清水混凝土质感：模板缝、拉片孔、微小色差、真实粗糙度，避免脏污过度。"],
  ["杂志摄影","建筑杂志摄影质感：等效35-50mm，竖线垂直，自然HDR，轻微景深，边缘锐利但不过度锐化。"],
  ["形体锁定","硬性约束：建筑形体、层数、开窗、柱网、屋顶线、场地必须与原图一致，不得增删移动。"],
  ["负向质量","负向约束：禁止过度锐化、强HDR、CG塑料感、假蓝玻璃、乱码文字、弯曲窗框、漂浮建筑。"],
];
$("presets").innerHTML = PRESETS.map(([n,t],i)=>
  `<label><input type="checkbox" value="${i}"><span>${n}</span></label>`).join("");

function setEngine(e){
  engine=e;
  $("engChat").classList.toggle("on",e==="chat");
  $("engLocal").classList.toggle("on",e==="local");
  $("engHint").textContent = e==="chat"
    ? "将用 ChatGPT 看图并扩写（需已启动专用 Chrome 并登录）。"
    : "将在你的浏览器本地识图，不需要账号或 VPN。";
  if(e==="local" && pickedFile) runLocalVision(pickedFile);   // 切到本地即识图
}

function onPick(f){
  if(!f) return; pickedFile=f; imageDesc="";
  $("dropHint").textContent="已选择图片（可点击重选）";
  $("dropPrev").innerHTML=`<img src="${URL.createObjectURL(f)}">`;
  $("descBox").textContent="";
  if(engine==="local") runLocalVision(f);
}

// 拖拽
const drop=$("drop");
["dragenter","dragover"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("dragover");}));
["dragleave","drop"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove("dragover");}));
drop.addEventListener("drop",e=>{const f=e.dataTransfer.files[0]; if(f&&f.type.startsWith("image/")) onPick(f);});

function selectedPresets(){
  return [...document.querySelectorAll("#presets input:checked")].map(el=>PRESETS[+el.value][1]);
}

async function generate(){
  const intent=$("intent").value.trim();
  const presets=selectedPresets();
  if(engine==="local"){
    const r=await fetch("/api/helper_build",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({intent,image_desc:imageDesc,presets})});
    show(await r.json());
  }else{
    const fd=new FormData();
    fd.append("draft_prompt",[intent,...presets].filter(Boolean).join("\n"));
    if(pickedFile) fd.append("image",pickedFile);
    const r=await fetch("/api/helper_refine",{method:"POST",body:fd});
    if(r.status===409||r.status===400){ const j=await r.json(); alert(j.msg); return; }
    show(await r.json());
  }
}

function show(d){
  if(!d.ok && d.msg){ alert(d.msg); return; }
  $("result").classList.remove("hidden");
  $("understanding").textContent=d.understanding_zh||"";
  $("zh").textContent=d.prompt_zh||"";
  $("en").textContent=d.prompt_en||"";
}
function copyEn(){ navigator.clipboard.writeText($("en").textContent).then(()=>alert("已复制英文提示词")); }

// runLocalVision 由 Task 12 填充；先占位，本地模式暂用空描述也能拼装
async function runLocalVision(file){ /* Task 12 覆盖 */ }
setEngine("chat");
```

- [ ] **Step 2: 手动验证本地与 ChatGPT 两分支**

开 `http://127.0.0.1:5001/helper`：
- 切「本地」→ 拖图 → 写想法 → 勾选项 →「生成」→ 出现中英提示词、复制成功（识图描述暂空，属正常）。
- 切「ChatGPT」→ 若未启动专用 Chrome，「生成」应弹出「没检测到可用的 ChatGPT」。
Expected：两分支都按预期返回或给出明确提示。

- [ ] **Step 3: 提交**
```bash
git add static/helper.js
git commit -m "feat: 助手页交互（引擎切换/拖拽/本地拼装/ChatGPT 精修/复制）"
```

---

## Phase 6 — 本地视觉模型（Florence-2）与资产分发

### Task 11: 资产下载脚本 + 静态路由 + 启动器接线

**Files:**
- Create: `scripts/fetch_assets.py`
- Modify: `app.py`（`/vendor`、`/models` 静态路由）
- Modify: `.gitignore`、`双击启动.bat`、`双击启动-Mac.command`

- [ ] **Step 1: 忽略大资产**

`.gitignore` 追加：
```
# 助手页本地模型与运行库（体积大，安装时下载）
models/
static/vendor/
```

- [ ] **Step 2: 下载脚本（国内镜像优先）**

`scripts/fetch_assets.py`：
```python
# -*- coding: utf-8 -*-
"""下载助手页「本地模式」所需资产：transformers.js 运行库 + Florence-2-large ONNX。
优先国内镜像（ModelScope / hf-mirror），确保无 VPN 也能装。已存在则跳过。"""
import os
import sys
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(APP_DIR, "static", "vendor", "transformers")
MODEL = os.path.join(APP_DIR, "models", "florence2-large")

# 运行时执行阶段会把这些文件按 transformers.js 期望的目录布局摆放。
# 下面清单在执行时按所选镜像的实际路径补全（见 README 部署说明）。
ASSETS = {
    # 目标相对路径: [镜像候选URL...]
    os.path.join(VENDOR, "transformers.min.js"): [
        "https://hf-mirror.com/…/transformers.min.js",
    ],
}
# 说明：Florence-2-large 权重较大，推荐用 ModelScope 的 snapshot_download 拉整目录。


def _download(dst, urls):
    if os.path.isfile(dst) and os.path.getsize(dst) > 1000:
        print(f"跳过（已存在）: {dst}")
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for url in urls:
        try:
            print(f"下载 {url} …")
            urllib.request.urlretrieve(url, dst)
            return True
        except Exception as e:
            print(f"  失败：{e}")
    return False


def main():
    ok = True
    for dst, urls in ASSETS.items():
        ok = _download(dst, urls) and ok
    # 用 ModelScope SDK 拉 Florence-2（若已装）；否则打印手动指引
    if not os.path.isdir(MODEL) or not os.listdir(MODEL):
        try:
            from modelscope import snapshot_download
            snapshot_download("AI-ModelScope/Florence-2-large", local_dir=MODEL)
        except Exception as e:
            print(f"[需手动] 未能自动获取 Florence-2-large（{e}）。"
                  f"请从 ModelScope 下载 ONNX 版到 {MODEL}/。本地模式在此之前不可用，"
                  f"但 ChatGPT 模式与全站其它功能不受影响。")
            ok = False
    print("完成" if ok else "部分资产缺失（见上）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

> 执行者注：具体镜像 URL / ModelScope 仓库名在落地时以当时可直连的源为准；脚本已把"缺资产"降级为**仅本地模式不可用**，不阻断其它功能。

- [ ] **Step 3: 静态路由**

`app.py` 新增（`helper_page` 附近）：
```python
@app.route("/vendor/<path:sub>")
def vendor_assets(sub):
    return send_from_directory(os.path.join(APP_DIR, "static", "vendor"), sub)


@app.route("/models/<path:sub>")
def model_assets(sub):
    return send_from_directory(os.path.join(APP_DIR, "models"), sub)
```

- [ ] **Step 4: 启动器首次运行拉资产（非阻断）**

`双击启动.bat` 在"起服务"之前插入：
```bat
echo 检查助手页本地模型资产（首次较慢，缺失不影响主功能）...
".venv-win\Scripts\python.exe" scripts\fetch_assets.py
```
`双击启动-Mac.command` 同理，在起服务前加：
```bash
echo "检查助手页本地模型资产（首次较慢，缺失不影响主功能）..."
.venv/bin/python scripts/fetch_assets.py || true
```

- [ ] **Step 5: 验证路由与脚本可运行**

Run: `.venv/bin/python scripts/fetch_assets.py`（预期：打印下载/跳过/手动指引，退出码 0 或 1 均属已知分支）
启动服务后 `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/vendor/transformers/transformers.min.js`（有资产→200，无→404，均不崩服务）。

- [ ] **Step 6: 提交**
```bash
git add scripts/fetch_assets.py app.py .gitignore 双击启动.bat 双击启动-Mac.command
git commit -m "feat: 助手页本地模型资产下载脚本 + 静态路由 + 启动器接线"
```

### Task 12: 浏览器内 Florence-2 识图

**Files:**
- Modify: `static/helper.js`（替换 `runLocalVision` 占位）

- [ ] **Step 1: 实现本地识图**

把 `static/helper.js` 里的 `async function runLocalVision(file){ /* Task 12 覆盖 */ }` 替换为：
```javascript
let _florence = null;
async function loadFlorence(){
  if(_florence) return _florence;
  $("descBox").textContent="正在加载本地识图模型（首次较慢）…";
  const { AutoProcessor, AutoTokenizer, Florence2ForConditionalGeneration, RawImage, env }
    = await import("/vendor/transformers/transformers.min.js");
  env.allowRemoteModels=false;                 // 只用本地资产，不联网
  env.localModelPath="/models/";
  env.backends.onnx.wasm.wasmPaths="/vendor/transformers/";
  const id="florence2-large";
  const device = navigator.gpu ? "webgpu" : "wasm";
  const model=await Florence2ForConditionalGeneration.from_pretrained(id,{dtype:"fp32",device});
  const processor=await AutoProcessor.from_pretrained(id);
  const tokenizer=await AutoTokenizer.from_pretrained(id);
  _florence={model,processor,tokenizer,RawImage};
  return _florence;
}

async function runLocalVision(file){
  try{
    const {model,processor,tokenizer,RawImage}=await loadFlorence();
    $("descBox").textContent="识图中…";
    const task="<MORE_DETAILED_CAPTION>";
    const image=await RawImage.fromBlob(file);
    const vision=await processor(image);
    const prompts=processor.construct_prompts(task);
    const text=tokenizer(prompts);
    const out=await model.generate({...text,...vision,max_new_tokens:256});
    const decoded=tokenizer.batch_decode(out,{skip_special_tokens:false})[0];
    const res=processor.post_process_generation(decoded,task,image.size);
    imageDesc=(res[task]||"").trim();
    $("descBox").textContent="本地识图：" + (imageDesc||"（未能识别，可手动在想法里补充画面描述）");
  }catch(e){
    imageDesc="";
    $("descBox").textContent="本机无法本地识图（"+e.message+"）。可直接在想法里描述画面后生成。";
  }
}
```

- [ ] **Step 2: 手动验证（需已放置模型资产）**

放好 `models/florence2-large/` 后，开 `/helper` → 切「本地」→ 拖图 → 应显示「本地识图：…描述…」→「生成」后英文提示词里含该描述。
若模型缺失/设备弱 → 显示友好降级提示，仍可手动描述后生成，不崩。
Expected：有模型时出描述；无模型时优雅降级。

- [ ] **Step 3: 提交**
```bash
git add static/helper.js
git commit -m "feat: 助手页浏览器内 Florence-2 本地识图（离线/免VPN，失败优雅降级）"
```

---

## Phase 7 — 收尾集成

### Task 13: 主页加「提示词助手」入口 + 全量测试

**Files:**
- Modify: `templates/index.html`（页眉加链接）

- [ ] **Step 1: 页眉加入口**

在 `templates/index.html` 的 `.conn` 那块附近（右上角）加一个链接按钮：
```html
    <a class="btn-ghost" href="/helper" style="text-decoration:none">提示词助手（无需账号）</a>
```

- [ ] **Step 2: 跑全部单测**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全部 passed（prompt_engine 4 + helper_api 4）。

- [ ] **Step 3: 端到端冒烟（本地模式，模拟无网）**

启动 `supervisor.py`；开 `/helper` 本地模式，拖图→生成→复制。确认 `/`、`/api/status` 正常。

- [ ] **Step 4: 提交**
```bash
git add templates/index.html
git commit -m "feat: 主页加「提示词助手」入口"
```

---

## 自查对照（Spec 覆盖）

- 助手页 `/helper` 双引擎默认 ChatGPT/可切本地 → Task 7/8/9/10 ✓
- 本地识图 Florence-2、离线免 VPN → Task 11/12 ✓
- 本地确定性拼装复用知识底座 → Task 5 ✓
- helper_refine 忙时 409、就绪校验、图片安全落盘 → Task 8 ✓
- 全站拖拽上传 → Task 1（主页）/Task 10（助手页）✓
- 手动开机自启（默认不自启）→ Task 2/3 ✓
- 模型走国内镜像首次下载、缺失不阻断 → Task 11 ✓
- 验收标准 1–6 → 分别由 Task 12/8/8/1&10/2&3/8 覆盖 ✓
