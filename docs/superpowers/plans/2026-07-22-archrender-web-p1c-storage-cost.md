# ArchRender Web — P1c 会话与存储 + 成本日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ArchRender Web 加上会话/任务的数据模型、本地存储（SQLite 关系数据 + 本地目录对象存储）、以及逐 Job 的用量→美元成本记录，为 P1d 完整导演循环与 P1e 异步/成本护栏打底。

**Architecture:** 同 P1a/P1b 的注入式风格。数据模型是纯 `@dataclass`（无 IO）；对象存储走 `BlobStore` Protocol + `LocalBlobStore`（本地目录起步，P1e/云端可换 S3）；关系存储走 `SqliteRepo`，构造时**注入 `sqlite3.Connection`**（单测用 `:memory:`，零磁盘、零全局状态）；成本计算是纯函数 `estimate_cost(usage, engine, pricing=PRICING)`，**费率表可注入**，故单测与真实费率解耦、只验算式。

**Tech Stack:** Python 3.10+，标准库 `sqlite3` / `dataclasses` / `enum` / `json`（P1c 不引第三方），pytest。

**成本取向（设计决策）**：费率常量集中在 `backend/storage/pricing.py` 的 `PRICING` 一处，带 `TODO` 标注——上线前用各 provider 官方价核对更新。导演脑 Claude 费率取自 `claude-api` skill（`claude-sonnet-5`：输入 \$3 / 输出 \$15 每百万 token）；出图单张费率为占位值，待用户按实际套餐确认。

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（裸 `python -m pytest` 会失败）。P1c 开始前基线：**32 passed + 3 skipped**。

---

## 文件结构（P1c）

```
backend/storage/
  __init__.py        # 新增：空包标识
  models.py          # 新增：Session / Job / JobStatus / Usage / StorageError
  blobs.py           # 新增：BlobStore Protocol + LocalBlobStore（本地目录）
  repo.py            # 新增：SqliteRepo（注入 sqlite3.Connection；建表 + 存取 Session/Job）
  pricing.py         # 新增：PRICING 费率表 + estimate_cost（图张数 + token → USD）
tests/
  test_storage_models.py
  test_blobs.py
  test_repo.py
  test_pricing.py
```

**不改动**：老 `app.py`、`prompt_engine`、既有 `backend/brain`、`backend/engines`、`backend/orchestrator`。P1c 是纯新增子包 `backend/storage`。

---

### Task 1: 数据模型 Session / Job / JobStatus / Usage

纯数据（无 IO）：会话、任务、任务状态枚举、用量累加器。用 `@dataclass`，时间戳用 UTC ISO 字符串（跨 SQLite 存取稳定）。

**Files:**
- Create: `backend/storage/__init__.py`（空文件）
- Create: `backend/storage/models.py`
- Test: `tests/test_storage_models.py`

- [ ] **Step 1: 写失败测试** `tests/test_storage_models.py`:
```python
from backend.storage.models import Session, Job, JobStatus, Usage


def test_session_defaults_and_fields():
    s = Session(id="s1", base_blob_key="sessions/s1/base.png", prompt_en="a house")
    assert s.id == "s1"
    assert s.base_blob_key == "sessions/s1/base.png"
    assert s.prompt_en == "a house"
    assert s.engine == "gemini"          # 默认引擎
    assert s.quality == "标准" and s.ratio == "跟随原图"
    assert isinstance(s.created_at, str) and "T" in s.created_at   # ISO 时间戳


def test_job_defaults():
    j = Job(id="j1", session_id="s1")
    assert j.status is JobStatus.PENDING
    assert j.round_blob_keys == []
    assert isinstance(j.usage, Usage)
    assert j.usage.images == 0


def test_jobstatus_is_str_enum():
    # 是 str 子类，方便直接落库/序列化成 "pending"
    assert JobStatus.RUNNING == "running"
    assert JobStatus("done") is JobStatus.DONE


def test_usage_accumulators():
    u = Usage()
    u.add_image()
    u.add_image(2)
    u.add_director_tokens(1000, 200)
    u.add_director_tokens(500, 50)
    assert u.images == 3
    assert u.director_input_tokens == 1500
    assert u.director_output_tokens == 250


def test_two_jobs_do_not_share_usage():
    # dataclass 默认可变默认值陷阱的回归测试：每个 Job 应有独立 Usage/list
    a, b = Job(id="a", session_id="s"), Job(id="b", session_id="s")
    a.usage.add_image()
    a.round_blob_keys.append("k")
    assert b.usage.images == 0
    assert b.round_blob_keys == []
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: backend.storage.models）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_storage_models.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`backend/storage/__init__.py`：空文件。

`backend/storage/models.py`:
```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class StorageError(RuntimeError):
    """存储层统一错误类型。"""


class JobStatus(str, Enum):
    """任务状态。继承 str，可直接落库/序列化为字面量。"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


def _now_iso() -> str:
    """UTC ISO 时间戳，跨 SQLite 存取稳定。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Usage:
    """逐 Job 用量累加器：出图张数 + 导演脑 token。"""

    images: int = 0
    director_input_tokens: int = 0
    director_output_tokens: int = 0

    def add_image(self, n: int = 1) -> None:
        self.images += n

    def add_director_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.director_input_tokens += input_tokens
        self.director_output_tokens += output_tokens


@dataclass
class Session:
    """一次用户交互会话：一张底图 + 已确认的英文提示词 + 出图设置。"""

    id: str
    base_blob_key: str                 # 底图在对象存储里的 key
    prompt_en: str = ""
    engine: str = "gemini"             # gemini | openai
    quality: str = "标准"
    ratio: str = "跟随原图"
    created_at: str = field(default_factory=_now_iso)


@dataclass
class Job:
    """会话下的一个出图任务：跑一次（多轮）导演循环，产出若干渲染图并累计用量。"""

    id: str
    session_id: str
    status: JobStatus = JobStatus.PENDING
    round_blob_keys: list[str] = field(default_factory=list)  # 各轮渲染图 key
    usage: Usage = field(default_factory=Usage)
    created_at: str = field(default_factory=_now_iso)
```

- [ ] **Step 4: 运行确认 PASS**（5 passed）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_storage_models.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 37 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/storage/__init__.py backend/storage/models.py tests/test_storage_models.py
git commit -m "feat: storage data models (Session/Job/JobStatus/Usage)"
```

---

### Task 2: 对象存储 BlobStore Protocol + LocalBlobStore

图片字节的存取抽象。Protocol 屏蔽本地目录 vs 云端 S3 差异；起步用本地目录实现。key 用 `/` 分层（如 `sessions/s1/base.png`），映射到 `base_dir` 下的子路径。

**Files:**
- Create: `backend/storage/blobs.py`
- Test: `tests/test_blobs.py`

- [ ] **Step 1: 写失败测试** `tests/test_blobs.py`:
```python
import pytest
from backend.storage.blobs import BlobStore, LocalBlobStore
from backend.storage.models import StorageError


def test_localblobstore_is_blobstore(tmp_path):
    assert isinstance(LocalBlobStore(tmp_path), BlobStore)


def test_put_then_get_roundtrip(tmp_path):
    store = LocalBlobStore(tmp_path)
    store.put("sessions/s1/base.png", b"PNGDATA")
    assert store.get("sessions/s1/base.png") == b"PNGDATA"
    assert store.exists("sessions/s1/base.png")


def test_put_creates_nested_dirs(tmp_path):
    store = LocalBlobStore(tmp_path)
    store.put("a/b/c/d.bin", b"x")
    assert (tmp_path / "a" / "b" / "c" / "d.bin").read_bytes() == b"x"


def test_get_missing_raises_storageerror(tmp_path):
    store = LocalBlobStore(tmp_path)
    assert not store.exists("nope/x.png")
    with pytest.raises(StorageError):
        store.get("nope/x.png")


def test_key_cannot_escape_base_dir(tmp_path):
    # 防目录穿越：绝对路径/.. 都不许逃出 base_dir
    store = LocalBlobStore(tmp_path)
    with pytest.raises(StorageError):
        store.put("../evil.png", b"x")
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: backend.storage.blobs）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_blobs.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** `backend/storage/blobs.py`:
```python
from pathlib import Path
from typing import Protocol, runtime_checkable

from backend.storage.models import StorageError


@runtime_checkable
class BlobStore(Protocol):
    """对象存储契约：按 key 存取原始字节。本地目录/云端 S3 都实现本协议。"""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    """本地目录对象存储：key（'/' 分层）映射到 base_dir 下的相对路径。"""

    def __init__(self, base_dir: Path | str):
        self._base = Path(base_dir).resolve()

    def _path(self, key: str) -> Path:
        p = (self._base / key).resolve()
        # 防目录穿越：解析后必须仍在 base_dir 之内
        if self._base not in p.parents and p != self._base:
            raise StorageError(f"非法 key（逃出存储根目录）：{key!r}")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        try:
            return p.read_bytes()
        except FileNotFoundError as e:
            raise StorageError(f"对象不存在：{key!r}") from e

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
```

- [ ] **Step 4: 运行确认 PASS**（5 passed）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_blobs.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 42 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/storage/blobs.py tests/test_blobs.py
git commit -m "feat: BlobStore protocol + LocalBlobStore (path-traversal safe)"
```

---

### Task 3: 关系存储 SqliteRepo（注入 connection）

Session/Job 的持久化。构造时注入 `sqlite3.Connection`（单测用 `sqlite3.connect(":memory:")`）。`round_blob_keys` 序列化为 JSON 文本列；`usage` 拆成三个整数列；`status` 存 `JobStatus` 的字面量。

**Files:**
- Create: `backend/storage/repo.py`
- Test: `tests/test_repo.py`

- [ ] **Step 1: 写失败测试** `tests/test_repo.py`:
```python
import sqlite3
import pytest
from backend.storage.models import Session, Job, JobStatus, Usage, StorageError
from backend.storage.repo import SqliteRepo


def _repo() -> SqliteRepo:
    repo = SqliteRepo(sqlite3.connect(":memory:"))
    repo.create_tables()
    return repo


def test_save_and_get_session_roundtrip():
    repo = _repo()
    s = Session(id="s1", base_blob_key="sessions/s1/base.png", prompt_en="a house", engine="openai")
    repo.save_session(s)
    got = repo.get_session("s1")
    assert got == s   # dataclass 相等：所有字段一致（含 created_at）


def test_get_missing_session_raises():
    repo = _repo()
    with pytest.raises(StorageError):
        repo.get_session("nope")


def test_save_and_get_job_preserves_status_keys_usage():
    repo = _repo()
    repo.save_session(Session(id="s1", base_blob_key="k"))
    j = Job(id="j1", session_id="s1", status=JobStatus.RUNNING)
    j.round_blob_keys.extend(["sessions/s1/j1/round1.png", "sessions/s1/j1/round2.png"])
    j.usage = Usage(images=2, director_input_tokens=1500, director_output_tokens=250)
    repo.save_job(j)

    got = repo.get_job("j1")
    assert got.status is JobStatus.RUNNING
    assert got.round_blob_keys == ["sessions/s1/j1/round1.png", "sessions/s1/j1/round2.png"]
    assert got.usage == Usage(images=2, director_input_tokens=1500, director_output_tokens=250)


def test_save_job_is_upsert():
    repo = _repo()
    repo.save_session(Session(id="s1", base_blob_key="k"))
    j = Job(id="j1", session_id="s1")
    repo.save_job(j)
    j.status = JobStatus.DONE
    j.usage.add_image(5)
    repo.save_job(j)              # 再存一次应覆盖，而非报主键冲突
    got = repo.get_job("j1")
    assert got.status is JobStatus.DONE
    assert got.usage.images == 5


def test_list_jobs_for_session_in_insertion_order():
    repo = _repo()
    repo.save_session(Session(id="s1", base_blob_key="k"))
    repo.save_session(Session(id="s2", base_blob_key="k"))
    repo.save_job(Job(id="j1", session_id="s1"))
    repo.save_job(Job(id="j2", session_id="s1"))
    repo.save_job(Job(id="jx", session_id="s2"))
    ids = [j.id for j in repo.list_jobs("s1")]
    assert ids == ["j1", "j2"]
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: backend.storage.repo）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_repo.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** `backend/storage/repo.py`:
```python
import json
import sqlite3

from backend.storage.models import Session, Job, JobStatus, Usage, StorageError


class SqliteRepo:
    """Session/Job 的 SQLite 持久化。注入 connection，便于单测用 :memory:。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                base_blob_key TEXT NOT NULL,
                prompt_en TEXT NOT NULL,
                engine TEXT NOT NULL,
                quality TEXT NOT NULL,
                ratio TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                round_blob_keys TEXT NOT NULL,      -- JSON list
                images INTEGER NOT NULL,
                director_input_tokens INTEGER NOT NULL,
                director_output_tokens INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    # ---- Session ----
    def save_session(self, s: Session) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions "
            "(id, base_blob_key, prompt_en, engine, quality, ratio, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s.id, s.base_blob_key, s.prompt_en, s.engine, s.quality, s.ratio, s.created_at),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> Session:
        row = self._conn.execute(
            "SELECT id, base_blob_key, prompt_en, engine, quality, ratio, created_at "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise StorageError(f"会话不存在：{session_id!r}")
        return Session(
            id=row[0], base_blob_key=row[1], prompt_en=row[2], engine=row[3],
            quality=row[4], ratio=row[5], created_at=row[6],
        )

    # ---- Job ----
    def save_job(self, j: Job) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(id, session_id, status, round_blob_keys, images, "
            " director_input_tokens, director_output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                j.id, j.session_id, j.status.value, json.dumps(j.round_blob_keys),
                j.usage.images, j.usage.director_input_tokens,
                j.usage.director_output_tokens, j.created_at,
            ),
        )
        self._conn.commit()

    def _row_to_job(self, row) -> Job:
        return Job(
            id=row[0], session_id=row[1], status=JobStatus(row[2]),
            round_blob_keys=json.loads(row[3]),
            usage=Usage(images=row[4], director_input_tokens=row[5], director_output_tokens=row[6]),
            created_at=row[7],
        )

    def get_job(self, job_id: str) -> Job:
        row = self._conn.execute(
            "SELECT id, session_id, status, round_blob_keys, images, "
            "director_input_tokens, director_output_tokens, created_at "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise StorageError(f"任务不存在：{job_id!r}")
        return self._row_to_job(row)

    def list_jobs(self, session_id: str) -> list[Job]:
        rows = self._conn.execute(
            "SELECT id, session_id, status, round_blob_keys, images, "
            "director_input_tokens, director_output_tokens, created_at "
            "FROM jobs WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return [self._row_to_job(r) for r in rows]
```

> 说明：`jobs` 表主键是 TEXT，故 SQLite 仍为每行维护隐式 `rowid`，`list_jobs` 直接 `ORDER BY rowid` 即插入序，无需额外列。注意 `INSERT OR REPLACE` 覆盖时该行 rowid 会变大（先删后插），故"多次 upsert 后仍严格保持原序"不保证——P1c 只需"同一 session 内新建任务按序返回"，测试也只覆盖此场景；严格队列顺序等 P1e 引入显式序号列。

- [ ] **Step 4: 运行确认 PASS**（5 passed）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_repo.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 47 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/storage/repo.py tests/test_repo.py
git commit -m "feat: SqliteRepo for Session/Job (injectable connection)"
```

---

### Task 4: 成本记账 pricing.PRICING + estimate_cost

逐 Job 用量→美元。费率表集中一处、可注入，故单测注入已知费率验算式、与真实费率脱钩。

**Files:**
- Create: `backend/storage/pricing.py`
- Test: `tests/test_pricing.py`

- [ ] **Step 1: 写失败测试** `tests/test_pricing.py`:
```python
from backend.storage.models import Usage
from backend.storage.pricing import PRICING, estimate_cost


_KNOWN = {
    "image_usd": {"gemini": 0.04, "openai": 0.10},
    "director_usd_per_mtok": {"input": 3.0, "output": 15.0},
}


def test_image_only_cost_with_injected_pricing():
    u = Usage(images=3)
    assert estimate_cost(u, "gemini", pricing=_KNOWN) == 0.12   # 3 * 0.04


def test_tokens_only_cost_with_injected_pricing():
    u = Usage(director_input_tokens=1_000_000, director_output_tokens=100_000)
    # 1e6 * 3/1e6 + 1e5 * 15/1e6 = 3.0 + 1.5 = 4.5
    assert estimate_cost(u, "gemini", pricing=_KNOWN) == 4.5


def test_combined_cost_and_engine_specific_image_rate():
    u = Usage(images=2, director_input_tokens=500_000, director_output_tokens=0)
    # openai 图价 0.10：2*0.10 + 0.5e6*3/1e6 = 0.20 + 1.5 = 1.70
    assert estimate_cost(u, "openai", pricing=_KNOWN) == 1.70


def test_unknown_engine_raises_keyerror():
    import pytest
    with pytest.raises(KeyError):
        estimate_cost(Usage(images=1), "midjourney", pricing=_KNOWN)


def test_default_pricing_table_has_required_shape():
    assert set(PRICING) == {"image_usd", "director_usd_per_mtok"}
    assert "gemini" in PRICING["image_usd"] and "openai" in PRICING["image_usd"]
    assert set(PRICING["director_usd_per_mtok"]) == {"input", "output"}
    # 默认费率为正数
    assert all(v > 0 for v in PRICING["image_usd"].values())
    assert all(v > 0 for v in PRICING["director_usd_per_mtok"].values())
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: backend.storage.pricing）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_pricing.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** `backend/storage/pricing.py`:
```python
from backend.storage.models import Usage

# 费率（美元）。TODO: 上线前用各 provider 官方价核对/更新。
# 导演脑 Claude 费率取自 claude-api skill：claude-sonnet-5 = 输入 $3 / 输出 $15 每百万 token。
# 出图单张为占位值，待按实际套餐确认。
PRICING = {
    "image_usd": {
        "gemini": 0.039,   # TODO 确认实际费率
        "openai": 0.040,   # TODO 确认实际费率
    },
    "director_usd_per_mtok": {
        "input": 3.00,
        "output": 15.00,
    },
}


def estimate_cost(usage: Usage, engine: str, pricing: dict = PRICING) -> float:
    """把一个 Job 的用量换算成美元。费率表可注入，便于测试与套餐切换。"""
    image_cost = pricing["image_usd"][engine] * usage.images
    input_cost = pricing["director_usd_per_mtok"]["input"] * usage.director_input_tokens / 1_000_000
    output_cost = pricing["director_usd_per_mtok"]["output"] * usage.director_output_tokens / 1_000_000
    return round(image_cost + input_cost + output_cost, 6)
```

- [ ] **Step 4: 运行确认 PASS**（5 passed）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_pricing.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 52 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/storage/pricing.py tests/test_pricing.py
git commit -m "feat: per-Job cost estimation (PRICING table + estimate_cost)"
```

---

## P1c 完成判据

- `uv run python -m pytest -v` → **52 passed + 3 skipped**（新增 20 个 P1c 测试；3 skipped 仍是真 API 冒烟测）。
- `Session`/`Job`/`JobStatus`/`Usage` 为纯 `@dataclass`；两个 Job 不共享可变默认值。
- `LocalBlobStore` 实现 `BlobStore`；put/get 往返、嵌套目录自动建、缺失报 `StorageError`、防目录穿越。
- `SqliteRepo` 注入 connection；Session/Job 存取往返保真（status/round_blob_keys/usage 全部还原）；`save_job` 为 upsert；`list_jobs` 按插入序。
- `estimate_cost` 用注入费率验算式通过；`PRICING` 形状正确、费率为正、带 `TODO` 待确认标注。
- 老 `app.py`、`prompt_engine`、既有 brain/engines/orchestrator 未改动。

## 交给后续子计划的接口

- `Session(id, base_blob_key, prompt_en, engine, quality, ratio)` / `Job(id, session_id, status, round_blob_keys, usage)` —— P1d 循环把每轮渲染图 key 追加进 `job.round_blob_keys`、把用量累进 `job.usage`。
- `BlobStore`（`put`/`get`/`exists`）—— P1d 存底图/各轮渲染图；P1e/云端换 S3 实现同协议即可。
- `SqliteRepo`（`save_session`/`get_session`/`save_job`/`get_job`/`list_jobs`）—— P1e 异步 worker 取活/回写状态、P1f 路由读写会话。
- `estimate_cost(usage, engine)` —— P1e 每日硬上限 + 每用户成本护栏据此累计。
```
