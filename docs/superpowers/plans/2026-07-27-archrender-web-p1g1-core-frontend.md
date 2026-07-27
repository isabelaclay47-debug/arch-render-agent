# ArchRender Web — P1g-1 核心出图前端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做出一个访客能真正用的最小可上线网页：上传底图 → 确认闸门（看导演中文复述、改英文提示词）→ 选引擎 → 开始出图 → 画廊看图并下载。

**Architecture:** 纯 vanilla HTML/CSS/JS 单页（无构建步骤，与老 `ArchRenderAgent` 前端一致），由现有 FastAPI 应用用 `StaticFiles` 托管；前端只调用 P1f 已有的 REST 路由 + 本计划新增的一个下载路由。出图任务当前是**请求内同步跑**（P1f 现状），所以前端用"提交→转圈→拿结果"的模型，不需要 SSE；真 SSE/异步 worker、区域涂改 canvas 留给 P1g-2。

**Tech Stack:** FastAPI + Starlette `StaticFiles`；前端 vanilla JS（`fetch`）；后端集成测试用 `fastapi.testclient.TestClient`；前端端到端测试用 Playwright（superpowers:webapp-testing）驱动真 uvicorn + 假引擎/假导演脑。

**运行后端测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`。当前基线：**89 passed + 3 skipped**。

**⚠️ 提交前必查**：本仓库 `master` 曾被多会话并发提交撞车。每次 `git commit`/`push` 前先 `git fetch && git status -sb` 确认无其它会话在推。

---

## 关键约束（写代码前先读）

- **不改动已绿的 89 个测试**：`create_app` 现有签名 `create_app(*, manager, blob_store, engine, brain)` 被所有 API 测试以"不传前端目录"的方式调用。新增的 `frontend_dir` 参数**必须有默认值 `None`**，为 `None` 时不挂载 StaticFiles → 现有测试行为不变。
- **老 `app.py`（ArchRenderAgent）永不碰**；本计划只在 `archrender-web` 仓库里加文件。
- **API key 永不进前端**：前端只调本站路由，provider key 只在后端环境变量。
- **同步出图的现实**：真引擎一轮 1–3 分钟，同步请求会超时——这是 P1g-2/异步 worker 要解决的。本计划所有端到端测试都用**假引擎**（毫秒级返回），前端布线因此可完整验证；真上线前必须补异步层（见文末"交给 P1g-2"）。

---

## 文件结构（P1g-1）

```
archrender-web/
  backend/api/app.py        # 修改：加 GET /jobs/{jid}/rounds/{i} 下载路由；create_app 加可选 frontend_dir 挂载
  backend/api/main.py       # 新建：生产 ASGI 入口（真件装配 + 挂前端），供 uvicorn 起
  frontend/index.html       # 新建：SPA 外壳（上传/确认/引擎/画廊四段）
  frontend/style.css        # 新建：样式
  frontend/app.js           # 新建：全部前端逻辑（fetch 调 API + 渲染）
  tests/test_api_download.py    # 新建：下载路由的 TestClient 集成测试（Task 1）
  tests/test_api_static.py      # 新建：前端托管的 TestClient 测试（Task 2）
  tests/e2e/conftest.py         # 新建：起 uvicorn + 假件的 Playwright fixture（Task 3）
  tests/e2e/test_flow.py        # 新建：上传→确认→出图→下载 端到端（Task 3、4）
```

每个文件一个清晰职责：`app.py` 只加路由与挂载；`main.py` 只做生产装配；`index.html` 只做结构；`app.js` 只做交互逻辑；`style.css` 只做样式。

---

### Task 1: 下载路由 `GET /jobs/{jid}/rounds/{i}`

前端画廊要能显示/下载每一轮的渲染图。P1f 把图片字节存进了 BlobStore（key 形如 `sessions/{sid}/{jid}/round{i}.png`），但没有取回字节的 HTTP 路由。本任务补上：按 job 的第 `i` 轮（1-based）取 `round_blob_keys[i-1]` 的字节，作为 PNG 返回。

**Files:**
- Modify: `backend/api/app.py`（在 `get_job` 之后、`return app` 之前加路由；顶部 import 加 `Response`）
- Test: `tests/test_api_download.py`

- [ ] **Step 1: 写失败测试** `tests/test_api_download.py`:

```python
import sqlite3
from fastapi.testclient import TestClient
from backend.storage.repo import SqliteRepo
from backend.storage.manager import SqliteSessionManager
from backend.storage.blobs import LocalBlobStore
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.brain.base import FaithfulnessVerdict
from backend.api.app import create_app


def _client(tmp_path):
    repo = SqliteRepo(sqlite3.connect(":memory:")); repo.create_tables()
    manager = SqliteSessionManager(repo)
    blobs = LocalBlobStore(tmp_path / "blobs")
    brain = FakeDirectorBrain(
        chat_replies=["<理解>ok</理解>", "enhance"],
        faithfulness_verdicts=[
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="x"),
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="y"),
        ],
    )
    app = create_app(manager=manager, blob_store=blobs, engine=FakeImageEngine(), brain=brain)
    return TestClient(app), manager, blobs


def _run_one_job(client):
    sid = client.post("/sessions", files={"base": ("b.png", b"BASE", "image/png")},
                      data={"intent_zh": "x"}).json()["session_id"]
    client.post(f"/sessions/{sid}/confirm", json={"prompt_en": "a modern concrete house"})
    return client.post(f"/sessions/{sid}/jobs", json={"n_rounds": 2}).json()["job_id"]


def test_download_round_returns_png_bytes(tmp_path):
    client, _, blobs = _client(tmp_path)
    jid = _run_one_job(client)
    resp = client.get(f"/jobs/{jid}/rounds/1")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 0


def test_download_missing_job_404(tmp_path):
    client, _, _ = _client(tmp_path)
    assert client.get("/jobs/nope/rounds/1").status_code == 404


def test_download_round_out_of_range_404(tmp_path):
    client, _, _ = _client(tmp_path)
    jid = _run_one_job(client)
    assert client.get(f"/jobs/{jid}/rounds/99").status_code == 404
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/test_api_download.py -v`
  Expected: FAIL（路由不存在 → 404 不匹配 / 或返回体不对）

- [ ] **Step 3: 实现** — `backend/api/app.py`

顶部 import 从 fastapi 追加 `Response`：
```python
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response
```

在 `get_job` 之后、`return app` 之前加：
```python
    @app.get("/jobs/{jid}/rounds/{i}")
    def download_round(jid: str, i: int):
        try:
            job = manager.get_job(jid)
        except StorageError:
            raise HTTPException(status_code=404, detail="job not found")
        if i < 1 or i > len(job.round_blob_keys):
            raise HTTPException(status_code=404, detail="round out of range")
        data = blob_store.get(job.round_blob_keys[i - 1])
        return Response(content=data, media_type="image/png")
```

- [ ] **Step 4: 运行确认 PASS** — `uv run python -m pytest tests/test_api_download.py -v`
  Expected: 3 passed

- [ ] **Step 5: 全量 + 提交**
```bash
cd /mnt/c/Users/Andy/archrender-web
git fetch && git status -sb          # 确认无其它会话在推 master
uv run python -m pytest -q           # 预期 92 passed + 3 skipped
git add backend/api/app.py tests/test_api_download.py
git commit -m "feat: GET /jobs/{jid}/rounds/{i} download route (round image bytes)"
```

---

### Task 2: 用 FastAPI 托管前端外壳 + 静态资源

前端是纯静态文件。让 `create_app` 可选地把 `frontend/` 目录挂在 `/`（`html=True` → `/` 返回 `index.html`）。默认不挂载，保护现有测试。

**Files:**
- Modify: `backend/api/app.py`（`create_app` 加 `frontend_dir` 参数 + 末尾挂载；顶部 import StaticFiles）
- Create: `frontend/index.html`, `frontend/style.css`（`app.js` 在 Task 3/4 填逻辑，本任务先建空壳能加载）
- Test: `tests/test_api_static.py`

- [ ] **Step 1: 写失败测试** `tests/test_api_static.py`:

```python
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from backend.storage.repo import SqliteRepo
from backend.storage.manager import SqliteSessionManager
from backend.storage.blobs import LocalBlobStore
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.api.app import create_app

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _app(tmp_path, frontend_dir=None):
    repo = SqliteRepo(sqlite3.connect(":memory:")); repo.create_tables()
    return create_app(
        manager=SqliteSessionManager(repo),
        blob_store=LocalBlobStore(tmp_path / "b"),
        engine=FakeImageEngine(),
        brain=FakeDirectorBrain(chat_replies=["<理解>ok</理解>"]),
        frontend_dir=frontend_dir,
    )


def test_serves_index_at_root(tmp_path):
    client = TestClient(_app(tmp_path, frontend_dir=FRONTEND))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "ArchRender" in resp.text


def test_no_frontend_dir_leaves_root_unmounted(tmp_path):
    # 不传 frontend_dir 时不挂载：根路径没有 index（404），现有 API 测试行为不受影响
    client = TestClient(_app(tmp_path, frontend_dir=None))
    assert client.get("/").status_code == 404
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/test_api_static.py -v`
  Expected: FAIL（`create_app` 不接受 `frontend_dir` → TypeError）

- [ ] **Step 3a: 实现挂载** — `backend/api/app.py`

顶部 import 追加：
```python
from fastapi.staticfiles import StaticFiles
```

改 `create_app` 签名与结尾：
```python
def create_app(*, manager, blob_store, engine, brain, frontend_dir=None) -> FastAPI:
    app = FastAPI(title="ArchRender Web")
    # ... 现有所有路由不变 ...

    # 前端静态托管（放最后：API 路由先匹配，未命中才落到 SPA）
    if frontend_dir is not None:
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="spa")

    return app
```
> 注意：`app.mount("/", ...)` 必须在**所有 API 路由注册之后**、`return app` 之前。FastAPI 按注册顺序匹配，具名路由（`/sessions` 等）先于挂载的 catch-all。

- [ ] **Step 3b: 建前端外壳** — `frontend/index.html`:

```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArchRender · 云端出图</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header><h1>ArchRender · 云端建筑渲染</h1></header>

  <!-- 第①段：上传底图 + 意向 -->
  <section id="step-upload" class="card">
    <h2>① 上传底图</h2>
    <input type="file" id="baseInput" accept="image/*">
    <img id="basePreview" alt="" hidden>
    <label>想法（中文，可选）<input type="text" id="intentInput" placeholder="现代清水混凝土住宅"></label>
    <label>出图引擎
      <select id="engineSelect">
        <option value="gemini">Gemini</option>
        <option value="openai">OpenAI</option>
      </select>
    </label>
    <button id="createBtn">下一步：让 AI 读图</button>
  </section>

  <!-- 第②段：确认闸门 -->
  <section id="step-confirm" class="card" hidden>
    <h2>② 确认闸门</h2>
    <p>AI 对底图的理解：</p>
    <pre id="understanding"></pre>
    <label>英文提示词（可改）<textarea id="promptEn" rows="4"></textarea></label>
    <label>轮数 <input type="number" id="nRounds" value="1" min="1" max="5"></label>
    <button id="startBtn">开始出图</button>
    <span id="startStatus"></span>
  </section>

  <!-- 第③段：画廊 -->
  <section id="step-gallery" class="card" hidden>
    <h2>③ 出图结果</h2>
    <p id="costLine"></p>
    <div id="gallery"></div>
  </section>

  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3c: 建样式** — `frontend/style.css`:

```css
:root { --ink:#211E17; --wine:#8a2e2e; --sand:#cbb994; --paper:#f7f3ea; }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: var(--paper); color: var(--ink); }
header { background: var(--ink); color: var(--paper); padding: 14px 20px; }
header h1 { margin: 0; font-size: 18px; }
.card { max-width: 760px; margin: 18px auto; background: #fff; border: 1px solid var(--sand);
        border-radius: 6px; padding: 18px; }
.card h2 { margin-top: 0; }
.card label { display: block; margin: 10px 0; }
.card input[type=text], .card textarea, .card select { width: 100%; padding: 7px; margin-top: 3px; }
button { background: var(--wine); color: #fff; border: 0; border-radius: 4px;
         padding: 9px 16px; cursor: pointer; font-size: 14px; }
button:disabled { background: var(--sand); cursor: not-allowed; }
#basePreview { max-width: 100%; margin: 10px 0; border-radius: 4px; }
#understanding { background: var(--paper); padding: 10px; border-radius: 4px; white-space: pre-wrap; }
#gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.round { border: 1px solid var(--sand); border-radius: 4px; padding: 8px; }
.round img { width: 100%; border-radius: 3px; }
.round a { display: inline-block; margin-top: 6px; color: var(--wine); }
```

- [ ] **Step 3d: 建空 `frontend/app.js`**（Task 3 填内容，先建占位使 `/app.js` 200）:
```javascript
// P1g-1 前端逻辑，Task 3/4 实现。
console.log("archrender web loaded");
```

- [ ] **Step 4: 运行确认 PASS** — `uv run python -m pytest tests/test_api_static.py -v`
  Expected: 2 passed

- [ ] **Step 5: 全量 + 提交**
```bash
cd /mnt/c/Users/Andy/archrender-web
git fetch && git status -sb
uv run python -m pytest -q           # 预期 94 passed + 3 skipped
git add backend/api/app.py frontend/ tests/test_api_static.py
git commit -m "feat: serve vanilla SPA shell via StaticFiles (optional frontend_dir)"
```

---

### Task 3: 前端逻辑（上/中）——上传建会话 + 确认闸门（Playwright e2e）

用 superpowers:webapp-testing 起一个**真 uvicorn**（装配假引擎/假导演脑 + `frontend_dir`），Playwright 打开 `/`，走：选文件 → 点"下一步" → 见到 AI 理解 → 英文词框自动填好。

**Files:**
- Create: `tests/e2e/conftest.py`（uvicorn + 假件 fixture）
- Create: `tests/e2e/test_flow.py`（第一条 e2e）
- Modify: `frontend/app.js`（上传 + 确认段逻辑）

- [ ] **Step 1: 起服务的 fixture** `tests/e2e/conftest.py`:

```python
import socket
import threading
import time
import sqlite3
from pathlib import Path

import pytest
import uvicorn

from backend.storage.repo import SqliteRepo
from backend.storage.manager import SqliteSessionManager
from backend.storage.blobs import LocalBlobStore
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.brain.base import FaithfulnessVerdict
from backend.api.app import create_app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@pytest.fixture
def live_server(tmp_path):
    repo = SqliteRepo(sqlite3.connect(":memory:", check_same_thread=False)); repo.create_tables()
    brain = FakeDirectorBrain(
        chat_replies=["<理解>6 层清水混凝土住宅，双拼体块</理解>",
                      "A six-storey fair-faced concrete housing block"],
        faithfulness_verdicts=[
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="改质感"),
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="ok"),
        ],
    )
    app = create_app(
        manager=SqliteSessionManager(repo),
        blob_store=LocalBlobStore(tmp_path / "blobs"),
        engine=FakeImageEngine(),
        brain=brain,
        frontend_dir=FRONTEND,
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):                       # 等就绪
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
```

- [ ] **Step 2: 写第一条 e2e（上传→确认）** `tests/e2e/test_flow.py`:

```python
from playwright.sync_api import sync_playwright


def test_upload_then_confirm_gate(live_server, tmp_path):
    png = tmp_path / "base.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)   # 假引擎不校验内容，字节即可
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(live_server)
        page.set_input_files("#baseInput", str(png))
        page.fill("#intentInput", "现代清水混凝土住宅")
        page.click("#createBtn")
        page.wait_for_selector("#step-confirm:not([hidden])")
        assert "清水混凝土" in page.inner_text("#understanding")
        # 英文词框应自动带出导演给的英文（第二条 chat_reply）
        assert page.input_value("#promptEn") != ""
        browser.close()
```
> 说明：假 `FakeImageEngine` 不解析图像内容，任意字节即可（上面 `write_bytes` 写的 PNG 魔数头足够走完流程）。

- [ ] **Step 3: 运行确认 FAIL** — `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/e2e/test_flow.py -v`
  Expected: FAIL（`app.js` 还没实现上传逻辑，`#step-confirm` 一直 hidden → `wait_for_selector` 超时）
  > 若报缺 playwright：`uv add --dev playwright && uv run playwright install chromium`。

- [ ] **Step 4: 实现 `frontend/app.js` 的上传+确认段**（覆盖占位内容）:

```javascript
const $ = id => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then(r => r.json());
let sessionId = null;

// 底图预览
$("baseInput").addEventListener("change", () => {
  const f = $("baseInput").files[0];
  if (!f) return;
  const img = $("basePreview");
  img.src = URL.createObjectURL(f);
  img.hidden = false;
});

// ① 上传 → 建会话 → 展示理解 + 英文词
$("createBtn").addEventListener("click", async () => {
  const f = $("baseInput").files[0];
  if (!f) { alert("请先选一张底图"); return; }
  $("createBtn").disabled = true;
  $("createBtn").textContent = "AI 读图中…";
  try {
    const fd = new FormData();
    fd.append("base", f);
    fd.append("intent_zh", $("intentInput").value);
    fd.append("engine_name", $("engineSelect").value);
    const r = await api("/sessions", { method: "POST", body: fd });
    sessionId = r.session_id;
    $("understanding").textContent = r.understanding || "(无)";
    // understanding 里若含英文提示词行则带出；否则留空让用户自己写
    $("promptEn").value = extractPromptEn(r.understanding);
    $("step-confirm").hidden = false;
    $("step-confirm").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    alert("建会话失败：" + e.message);
  } finally {
    $("createBtn").disabled = false;
    $("createBtn").textContent = "下一步：让 AI 读图";
  }
});

// 从导演回复里粗略抽英文提示词：取最后一段纯英文行，抽不到就空
function extractPromptEn(text) {
  if (!text) return "";
  const lines = text.split(/\n/).map(s => s.trim()).filter(Boolean);
  const en = lines.reverse().find(l => /^[\x00-\x7F]+$/.test(l) && l.length > 10);
  return en || "";
}
```

> 关于确认段：`confirm_understanding` 只返回一段中文理解（`FakeDirectorBrain` 的第一条 `chat_reply`）；e2e fixture 的第二条 `chat_reply` 是给 `run_rounds` 内部翻译用的，不一定回到 `/sessions` 响应里。因此测试里"英文词框非空"要靠 `extractPromptEn` 从 understanding 抽，或——更稳妥——把断言改成"用户能在 `#promptEn` 里手动输入"。实现时若 `understanding` 抽不出英文，测试用 `page.fill("#promptEn", "a concrete house")` 手填后再断言值非空（见下调整）。

调整后的 `test_flow.py` 确认断言（替换 Step 2 里最后两行）:
```python
        # 抽不到英文很正常：用户在闸门里自己敲英文词
        if page.input_value("#promptEn") == "":
            page.fill("#promptEn", "a six-storey concrete housing block")
        assert page.input_value("#promptEn") != ""
```

- [ ] **Step 5: 运行确认 PASS** — `uv run python -m pytest tests/e2e/test_flow.py -v`
  Expected: PASS

- [ ] **Step 6: 提交**
```bash
cd /mnt/c/Users/Andy/archrender-web
git fetch && git status -sb
git add frontend/app.js tests/e2e/
git commit -m "feat: frontend upload + confirmation gate (Playwright e2e)"
```

---

### Task 4: 前端逻辑（下）——确认英文词 → 开始出图 → 画廊 + 下载（Playwright e2e）

**Files:**
- Modify: `frontend/app.js`（追加 confirm+start+gallery 逻辑）
- Modify: `tests/e2e/test_flow.py`（追加完整链路 e2e）

- [ ] **Step 1: 写完整链路 e2e**（追加到 `tests/e2e/test_flow.py`）:

```python
def test_full_flow_generate_and_download(live_server, tmp_path):
    png = tmp_path / "base.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(live_server)
        page.set_input_files("#baseInput", str(png))
        page.click("#createBtn")
        page.wait_for_selector("#step-confirm:not([hidden])")
        if page.input_value("#promptEn") == "":
            page.fill("#promptEn", "a six-storey concrete housing block")
        page.fill("#nRounds", "2")
        page.click("#startBtn")
        # 出图完成 → 画廊出现 2 张图 + 每张一个下载链接
        page.wait_for_selector("#step-gallery:not([hidden])")
        page.wait_for_selector(".round img")
        assert page.locator(".round").count() == 2
        assert "美元" in page.inner_text("#costLine") or "$" in page.inner_text("#costLine")
        # 第一张图确实能取到字节（下载路由通）
        img_src = page.locator(".round img").first.get_attribute("src")
        resp = page.request.get(live_server + img_src)
        assert resp.status == 200
        assert resp.headers["content-type"] == "image/png"
        browser.close()
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/e2e/test_flow.py::test_full_flow_generate_and_download -v`
  Expected: FAIL（`#startBtn` 无逻辑 → 画廊不出现）

- [ ] **Step 3: 实现**（追加到 `frontend/app.js` 末尾）:

```javascript
// ② 确认英文词落库 → 起任务（同步跑，转圈等结果）→ 渲染画廊
$("startBtn").addEventListener("click", async () => {
  if (!sessionId) { alert("请先建会话"); return; }
  const promptEn = $("promptEn").value.trim();
  if (!promptEn) { alert("请填英文提示词"); return; }
  $("startBtn").disabled = true;
  $("startStatus").textContent = "出图中…（可能要一会儿）";
  try {
    await api(`/sessions/${sessionId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt_en: promptEn }),
    });
    const nRounds = parseInt($("nRounds").value, 10) || 1;
    const job = await api(`/sessions/${sessionId}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ n_rounds: nRounds }),
    });
    renderGallery(job);
  } catch (e) {
    alert("出图失败：" + e.message);
  } finally {
    $("startBtn").disabled = false;
    $("startStatus").textContent = "";
  }
});

function renderGallery(job) {
  const g = $("gallery");
  g.innerHTML = "";
  $("costLine").textContent = `本次成本：约 ${job.cost_usd} 美元（${job.rounds.length} 轮）`;
  job.rounds.forEach(r => {
    const url = `/jobs/${job.job_id}/rounds/${r.iteration}`;
    const div = document.createElement("div");
    div.className = "round";
    div.innerHTML =
      `<img src="${url}" alt="第 ${r.iteration} 轮">` +
      `<div>第 ${r.iteration} 轮 · ${r.tampered ? "⚠ 有篡改" : "✓ 忠实"}</div>` +
      `<a href="${url}" download="round${r.iteration}.png">下载这张</a>`;
    g.appendChild(div);
  });
  $("step-gallery").hidden = false;
  $("step-gallery").scrollIntoView({ behavior: "smooth" });
}
```

- [ ] **Step 4: 运行确认 PASS** — `uv run python -m pytest tests/e2e/test_flow.py -v`
  Expected: 2 passed（上传确认 + 完整链路）

- [ ] **Step 5: 全量 + 提交**
```bash
cd /mnt/c/Users/Andy/archrender-web
git fetch && git status -sb
uv run python -m pytest -q           # 后端 94 + e2e 2；e2e 需 chromium
git add frontend/app.js tests/e2e/test_flow.py
git commit -m "feat: confirm->generate->gallery+download frontend flow (e2e)"
```

---

### Task 5: 生产 ASGI 入口 `backend/api/main.py`

给 uvicorn 一个可起的 `app` 对象：装配**真** SqliteSessionManager + LocalBlobStore + 真引擎（`get_image_engine`）+ ClaudeBrain，读环境变量，挂前端。为后续真部署铺路（本任务只保证"能装配、能 import、结构正确"，不真调 provider）。

**Files:**
- Create: `backend/api/main.py`
- Test: `tests/test_main_wiring.py`

- [ ] **Step 1: 写测试** `tests/test_main_wiring.py`:

```python
from backend.api import main


def test_build_app_returns_fastapi_with_expected_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHRENDER_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("ARCHRENDER_BLOBS", str(tmp_path / "blobs"))
    # GeminiImageClient.__init__ 会 eager 读 GEMINI_API_KEY 并在缺失时 raise
    # （ClaudeBrain 是 lazy，构造不需要 key）。给个占位 key 让装配走通——
    # genai.Client(api_key=...) 只存 key、构造时不连网，不会真发请求。
    monkeypatch.setenv("GEMINI_API_KEY", "test-placeholder-key")
    app = main.build_app()
    routes = {r.path for r in app.routes}
    assert "/sessions" in routes
    assert "/jobs/{jid}/rounds/{i}" in routes
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/test_main_wiring.py -v`
  Expected: FAIL（`main` 模块/`build_app` 不存在）

- [ ] **Step 3: 实现** `backend/api/main.py`:

```python
"""生产 ASGI 入口：真件装配。用 `uvicorn backend.api.main:app` 起。

环境变量：
  ARCHRENDER_DB      SQLite 路径（默认 ./archrender.db）
  ARCHRENDER_BLOBS   对象存储目录（默认 ./blobs）
  ARCHRENDER_ENGINE  默认引擎 gemini|openai（默认 gemini）
  GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY  provider key（真出图才需）
"""
import os
import sqlite3
from pathlib import Path

from backend.storage.repo import SqliteRepo
from backend.storage.manager import SqliteSessionManager
from backend.storage.blobs import LocalBlobStore
from backend.engines.factory import get_image_engine
from backend.brain.claude import ClaudeBrain
from backend.api.app import create_app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def build_app():
    db_path = os.getenv("ARCHRENDER_DB", "archrender.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    repo = SqliteRepo(conn); repo.create_tables()
    manager = SqliteSessionManager(repo)
    blobs = LocalBlobStore(os.getenv("ARCHRENDER_BLOBS", "blobs"))
    engine = get_image_engine(os.getenv("ARCHRENDER_ENGINE", "gemini"))
    brain = ClaudeBrain()
    return create_app(manager=manager, blob_store=blobs, engine=engine,
                      brain=brain, frontend_dir=FRONTEND)


app = build_app()
```

> 已核对真实构造行为（截至本计划）：`ClaudeBrain()` → `_RealClaudeCaller` **惰性**建 `anthropic.Anthropic()`（首次 `.call()` 才连，构造不需要 key）；而 `GeminiImageClient.__init__` / `OpenAIImageClient.__init__` **eager** 读 `GEMINI_API_KEY`/`OPENAI_API_KEY` 并在缺失时 `raise`。因此 `build_app()` 用默认 gemini 引擎时**构造期就需要** `GEMINI_API_KEY` 在环境里（真出图时才真用它）。这解释了 Step 1 测试为何设占位 `GEMINI_API_KEY`。不改现有 client 代码（已测已提交）。

- [ ] **Step 4: 运行确认 PASS** — `uv run python -m pytest tests/test_main_wiring.py -v`
  Expected: PASS

- [ ] **Step 5: 本地手动起一次（人工验收，非自动测试）**
```bash
cd /mnt/c/Users/Andy/archrender-web
uv run uvicorn backend.api.main:app --port 8000
# 浏览器开 http://127.0.0.1:8000 → 看到上传页
```

- [ ] **Step 6: 全量 + 提交**
```bash
cd /mnt/c/Users/Andy/archrender-web
git fetch && git status -sb
uv run python -m pytest -q
git add backend/api/main.py tests/test_main_wiring.py
git commit -m "feat: production ASGI entrypoint (real deps + SPA mount)"
```

---

## P1g-1 完成判据

- `uv run python -m pytest -q` → 后端 **95 passed + 3 skipped**（89 基线 + Task1 三条 + Task2 两条 + Task5 一条）；`tests/e2e/` **2 passed**（需 chromium）。
- `uvicorn backend.api.main:app` 起得来，浏览器打开根路径见上传页。
- 端到端：上传底图 → 见 AI 中文理解 → 改/填英文词 → 选引擎 → 开始 → 画廊出图 → 每张可下载。
- 现有 89 个测试全部不受影响（`frontend_dir` 默认 `None`）。

## 交给 P1g-2 / 后续的接口

- **异步 worker + SSE 进度**：把 P1f 的"请求内同步跑 `run_rounds`"换成 P1e 的队列 + worker 池 + SSE；前端 `#startStatus` 升级成实时进度条与排位 ETA。真上线**必须**先做这个（同步请求扛不住 1–3 分钟真出图）。
- **区域涂改 canvas**：前端画 mask → 新 `POST /sessions/{sid}/edits`（调 `apply_regional_edit`）→ 画廊追加编辑轮。
- **中英切换**：搬 `ArchRenderAgent/static/i18n.js` 的运行时翻译层到本前端。
- **参考图/角色**、画质/比例选择：本计划先只做底图 happy path。
- **部署**（spec §8）：容器化 + 对象存储换云 + 入口/出海拓扑，另起部署子计划。
