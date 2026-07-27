# ArchRender Web — P1f FastAPI 接口层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 用 FastAPI 把前面五块拼成 HTTP 接口：建会话+上传底图+确认闸门、确认英文提示词、起任务跑导演循环并落盘算成本、查会话/任务。

**Scope:** 本计划做**同步可集成测试的 REST 路由**（`fastapi.testclient.TestClient`，注入假引擎/假导演脑 + `:memory:` 存储 + tmp 对象目录，零网络）。真 SSE 流式进度、独立 asyncio worker 池留作 P1f-后续（起步用请求内同步跑 `run_rounds`——假引擎毫秒级返回，够验证布线）。

**Architecture:** `create_app(*, manager, blob_store, engine, brain)` 应用工厂，全部依赖注入 → 测试塞假件、生产塞真件。编排层函数收 `Path`、API 层收 bytes：上传字节存进 `BlobStore` 持久化，同时落一份临时文件喂给收 `Path` 的 `confirm_understanding`/`run_rounds`；产出的渲染图再读回字节存进 BlobStore、用 `SessionManager.record_round/add_usage` 落盘，`estimate_cost` 出账。

**Tech Stack:** FastAPI + Starlette，`python-multipart`（文件上传），`httpx`（TestClient），pytest。

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`。P1f 前基线：**81 passed + 3 skipped**。

---

## 文件结构（P1f）

```
backend/api/
  __init__.py
  app.py             # create_app(manager, blob_store, engine, brain) + 路由
backend/storage/
  manager.py         # 追加 set_prompt（确认后把英文提示词落到会话）
tests/
  test_api_sessions.py   # Task 1
  test_api_jobs.py       # Task 2
```

---

### Task 1: create_app + 会话/确认路由

**Files:** Create `backend/api/__init__.py`（空）, `backend/api/app.py`; Modify `backend/storage/manager.py`; Test `tests/test_api_sessions.py`

- [ ] **Step 1: 写失败测试** `tests/test_api_sessions.py`:
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


def _client(tmp_path, brain=None):
    repo = SqliteRepo(sqlite3.connect(":memory:")); repo.create_tables()
    manager = SqliteSessionManager(repo)
    blobs = LocalBlobStore(tmp_path / "blobs")
    engine = FakeImageEngine()
    brain = brain or FakeDirectorBrain(chat_replies=["<理解>6层清水混凝土住宅</理解>"])
    app = create_app(manager=manager, blob_store=blobs, engine=engine, brain=brain)
    return TestClient(app), manager, blobs


def test_create_session_uploads_base_and_returns_understanding(tmp_path):
    client, manager, blobs = _client(tmp_path)
    resp = client.post(
        "/sessions",
        files={"base": ("base.png", b"PNGBYTES", "image/png")},
        data={"intent_zh": "现代清水混凝土住宅", "engine_name": "openai"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["understanding"] == "<理解>6层清水混凝土住宅</理解>"
    sid = body["session_id"]
    # 会话已落库，底图字节进了对象存储
    s = manager.get_session(sid)
    assert s.engine == "openai"
    assert blobs.get(s.base_blob_key) == b"PNGBYTES"


def test_confirm_stores_prompt_en(tmp_path):
    client, manager, _ = _client(tmp_path)
    sid = client.post(
        "/sessions",
        files={"base": ("b.png", b"X", "image/png")},
        data={"intent_zh": "x"},
    ).json()["session_id"]

    resp = client.post(f"/sessions/{sid}/confirm", json={"prompt_en": "A modern concrete house"})
    assert resp.status_code == 200
    assert manager.get_session(sid).prompt_en == "A modern concrete house"


def test_get_session_returns_info(tmp_path):
    client, _, _ = _client(tmp_path)
    sid = client.post("/sessions", files={"base": ("b.png", b"X", "image/png")}, data={"intent_zh": "x"}).json()["session_id"]
    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid


def test_get_missing_session_404(tmp_path):
    client, _, _ = _client(tmp_path)
    assert client.get("/sessions/nope").status_code == 404


def test_confirm_missing_session_404(tmp_path):
    client, _, _ = _client(tmp_path)
    assert client.post("/sessions/nope/confirm", json={"prompt_en": "x"}).status_code == 404
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/test_api_sessions.py -v`

- [ ] **Step 3: 实现**

在 `backend/storage/manager.py` 的 `SessionManager` ABC 加抽象方法、`SqliteSessionManager` 加实现：
```python
    # ABC 里加：
    @abstractmethod
    def set_prompt(self, session_id: str, prompt_en: str) -> Session: ...

    # SqliteSessionManager 里加：
    def set_prompt(self, session_id, prompt_en):
        s = self._repo.get_session(session_id)
        s.prompt_en = prompt_en
        self._repo.save_session(s)
        return s
```

`backend/api/__init__.py`：空文件。

`backend/api/app.py`:
```python
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from backend.storage.models import StorageError
from backend.orchestrator.director_loop import confirm_understanding


class ConfirmBody(BaseModel):
    prompt_en: str


def create_app(*, manager, blob_store, engine, brain) -> FastAPI:
    app = FastAPI(title="ArchRender Web")

    def _tmp_write(data: bytes, name: str = "base.png") -> Path:
        p = Path(tempfile.mkdtemp()) / name
        p.write_bytes(data)
        return p

    @app.post("/sessions")
    async def create_session(
        base: UploadFile = File(...),
        intent_zh: str = Form(""),
        engine_name: str = Form("gemini"),
    ):
        data = await base.read()
        key = f"bases/{uuid.uuid4()}.png"
        blob_store.put(key, data)
        understanding = confirm_understanding(brain, base_image=_tmp_write(data), intent_zh=intent_zh)
        s = manager.create_session(key, engine=engine_name)
        return {"session_id": s.id, "understanding": understanding}

    @app.post("/sessions/{sid}/confirm")
    def confirm(sid: str, body: ConfirmBody):
        try:
            s = manager.set_prompt(sid, body.prompt_en)
        except StorageError:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": s.id, "prompt_en": s.prompt_en}

    @app.get("/sessions/{sid}")
    def get_session(sid: str):
        try:
            s = manager.get_session(sid)
        except StorageError:
            raise HTTPException(status_code=404, detail="session not found")
        return {"id": s.id, "prompt_en": s.prompt_en, "engine": s.engine,
                "base_blob_key": s.base_blob_key}

    return app
```

- [ ] **Step 4: 运行确认 PASS**（5 passed）
- [ ] **Step 5: 全量 + 提交**（预期 86 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/api/__init__.py backend/api/app.py backend/storage/manager.py tests/test_api_sessions.py
git commit -m "feat: FastAPI app factory + session create/confirm/get routes"
```

---

### Task 2: 起任务路由（跑 run_rounds、落盘、算成本）+ 查任务

**Files:** Modify `backend/api/app.py`; Test `tests/test_api_jobs.py`

- [ ] **Step 1: 写失败测试** `tests/test_api_jobs.py`:
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
        chat_replies=["<理解>ok</理解>", "enhance texture"],
        faithfulness_verdicts=[
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="改质感"),
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="ok"),
        ],
    )
    app = create_app(manager=manager, blob_store=blobs, engine=FakeImageEngine(), brain=brain)
    return TestClient(app), manager, blobs


def _new_session(client):
    sid = client.post("/sessions", files={"base": ("b.png", b"BASE", "image/png")}, data={"intent_zh": "x"}).json()["session_id"]
    client.post(f"/sessions/{sid}/confirm", json={"prompt_en": "a modern concrete house"})
    return sid


def test_start_job_runs_rounds_and_records(tmp_path):
    client, manager, blobs = _client(tmp_path)
    sid = _new_session(client)

    resp = client.post(f"/sessions/{sid}/jobs", json={"n_rounds": 2})
    assert resp.status_code == 200
    body = resp.json()
    jid = body["job_id"]
    assert len(body["rounds"]) == 2
    assert body["rounds"][0]["iteration"] == 1
    assert body["cost_usd"] >= 0

    # 落盘：job 有 2 个渲染图 key，且字节能从对象存储取回
    job = manager.get_job(jid)
    assert len(job.round_blob_keys) == 2
    assert all(blobs.exists(k) for k in job.round_blob_keys)
    assert job.usage.images == 2


def test_start_job_missing_session_404(tmp_path):
    client, _, _ = _client(tmp_path)
    assert client.post("/sessions/nope/jobs", json={"n_rounds": 1}).status_code == 404


def test_get_job_returns_status_and_cost(tmp_path):
    client, _, _ = _client(tmp_path)
    sid = _new_session(client)
    jid = client.post(f"/sessions/{sid}/jobs", json={"n_rounds": 1}).json()["job_id"]
    resp = client.get(f"/jobs/{jid}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == jid
    assert "cost_usd" in resp.json()
```

- [ ] **Step 2: 运行确认 FAIL**

- [ ] **Step 3: 实现** — 在 `backend/api/app.py` 的 `create_app` 内追加（用到 `run_rounds`、`estimate_cost`、`JobStatus`）:

顶部补 import：
```python
from backend.storage.models import JobStatus
from backend.storage.pricing import estimate_cost
from backend.orchestrator.director_loop import run_rounds
```

路由（放在 get_session 之后、return app 之前）:
```python
    class StartJobBody(BaseModel):
        n_rounds: int = 1

    @app.post("/sessions/{sid}/jobs")
    def start_job(sid: str, body: StartJobBody):
        try:
            s = manager.get_session(sid)
        except StorageError:
            raise HTTPException(status_code=404, detail="session not found")

        base_bytes = blob_store.get(s.base_blob_key)
        work = Path(tempfile.mkdtemp())
        base_path = work / "base.png"; base_path.write_bytes(base_bytes)

        job = manager.create_job(sid)
        results = run_rounds(
            brain, engine,
            base_image=base_path, prompt_en=s.prompt_en,
            out_dir=work, n_rounds=body.n_rounds,
        )
        for r in results:
            key = f"sessions/{sid}/{job.id}/round{r.iteration}.png"
            blob_store.put(key, r.render.read_bytes())
            manager.record_round(job.id, key, status=JobStatus.RUNNING)
            manager.add_usage(job.id, images=1)   # 每轮一张；导演 token 待真 caller 接上
        manager.get_job(job.id)  # ensure persisted
        # 收尾状态
        final = manager.record_round.__self__  # noop 占位（见下实现说明）
        cost = manager.get_cost_usd(job.id)
        return {
            "job_id": job.id,
            "rounds": [{"iteration": r.iteration, "action": r.verdict.action,
                        "tampered": r.verdict.tampered} for r in results],
            "cost_usd": cost,
        }

    @app.get("/jobs/{jid}")
    def get_job(jid: str):
        try:
            job = manager.get_job(jid)
        except StorageError:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job.id, "session_id": job.session_id,
                "status": job.status.value, "round_blob_keys": job.round_blob_keys,
                "cost_usd": manager.get_cost_usd(jid)}
```

> 实现说明：上面 `final = manager.record_round.__self__` 那行是**占位噪声，删掉**。收尾把 job 状态置 `DONE`：在循环后 `manager.record_round` 不接受纯状态更新，故直接取 job、改状态、经 repo 存——用 `job2 = manager.get_job(job.id); job2.status = JobStatus.DONE; manager._repo.save_job(job2)`，或给 manager 加一个 `set_status(job_id, status)` 小方法（推荐后者，别碰私有 `_repo`）。实现时选加 `set_status` 到 `SqliteSessionManager`（ABC 可不加，路由注入的是具体类），循环后调用它置 `DONE`，并在 `get_job` 返回里体现。

- [ ] **Step 4: 运行确认 PASS**（3 passed）
- [ ] **Step 5: 全量 + 提交**（预期 89 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/api/app.py backend/storage/manager.py tests/test_api_jobs.py
git commit -m "feat: start-job route (run_rounds + blob persist + cost) and get-job route"
```

---

## P1f 完成判据

- `uv run python -m pytest -v` → **89 passed + 3 skipped**。
- `POST /sessions`：多部件上传底图→存 BlobStore + 跑确认闸门→返回 understanding + session_id；会话落库。
- `POST /sessions/{sid}/confirm`：落英文提示词；缺会话 404。
- `POST /sessions/{sid}/jobs`：跑 `run_rounds`→各轮渲染图存 BlobStore + `record_round`/`add_usage`→返回轮次摘要 + `cost_usd`；缺会话 404。
- `GET /sessions/{sid}` / `GET /jobs/{jid}`：返回信息/成本；缺失 404。
- 全用 `TestClient` + 假件集成测试，零网络。

## 交给后续（P1f-后续 / P1g）的接口

- SSE 进度端点、独立 asyncio worker 池（从 `JobQueue` 取活、`ConcurrencyGuard` 限流、`DailyCostCap` 把关、provider 调用包 `retry_with_backoff`）——在真异步 worker 里替换本计划的"请求内同步跑 run_rounds"。
- 下载端点 `GET /blobs/{key}` 或 `GET /jobs/{jid}/rounds/{i}` 返回图片字节。
- 区域编辑端点调 `apply_regional_edit`。
- P1g 前端 SPA 消费这些路由 + SSE。
```
