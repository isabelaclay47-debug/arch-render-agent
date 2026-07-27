# ArchRender Web — P1e 异步任务层（护栏与策略） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 实现异步任务层里**可纯单测的策略/护栏逻辑**：按 provider 分道的任务队列、每用户并发上限（公平）、每日成本硬上限（成本护栏）、429 指数退避重试。

**Scope（明确边界）:** 真正的 asyncio worker 事件循环 + SSE 进度推送属集成级、难纯单测，**留给 P1f**（FastAPI 层）用本层这些同步组件拼装。本计划只做无副作用、可注入、可确定性测试的部分——即路线图 P1e 里"429 退避 / 每用户并发上限 / 每日硬上限 / 排队"这几项的**核心状态机**。

**Architecture:** 全部是内存态、无 IO 的小组件，靠注入（`sleep`、`day`、`max_*`）做确定性测试；与 P1c 的 `estimate_cost`、`SessionManager` 组合即可在 P1f 里驱动真 worker。

**Tech Stack:** Python 3.10+ 标准库（`collections`、`time`），pytest。无第三方。

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`。P1e 前基线：**66 passed + 3 skipped**。

---

## 文件结构（P1e）

```
backend/tasks/
  __init__.py
  queue.py         # JobQueue（按 provider 分道 FIFO）
  concurrency.py   # ConcurrencyGuard（每用户在跑上限）
  cost_cap.py      # DailyCostCap（每日美元硬上限）
  retry.py         # retry_with_backoff（429 指数退避，sleep 可注入）
tests/
  test_task_queue.py
  test_concurrency_guard.py
  test_daily_cost_cap.py
  test_retry_backoff.py
```

不改动既有任何文件；纯新增子包 `backend/tasks`。

---

### Task 1: JobQueue（按 provider 分道 FIFO）

**Files:** Create `backend/tasks/__init__.py`（空）, `backend/tasks/queue.py`; Test `tests/test_task_queue.py`

- [ ] **Step 1: 写失败测试** `tests/test_task_queue.py`:
```python
from backend.tasks.queue import JobQueue


def test_fifo_per_provider():
    q = JobQueue()
    q.enqueue("j1", "gemini")
    q.enqueue("j2", "gemini")
    assert q.dequeue("gemini") == "j1"
    assert q.dequeue("gemini") == "j2"
    assert q.dequeue("gemini") is None


def test_lanes_are_isolated_by_provider():
    q = JobQueue()
    q.enqueue("g1", "gemini")
    q.enqueue("o1", "openai")
    assert q.dequeue("openai") == "o1"
    assert q.size("gemini") == 1
    assert q.dequeue("gemini") == "g1"


def test_size_and_pending_snapshot():
    q = JobQueue()
    q.enqueue("a", "gemini"); q.enqueue("b", "gemini")
    assert q.size("gemini") == 2
    assert q.pending("gemini") == ["a", "b"]
    assert q.size("openai") == 0 and q.pending("openai") == []
```

- [ ] **Step 2: 运行确认 FAIL** — `uv run python -m pytest tests/test_task_queue.py -v`（ModuleNotFoundError）

- [ ] **Step 3: 实现** `backend/tasks/__init__.py`（空文件）; `backend/tasks/queue.py`:
```python
from collections import deque, defaultdict


class JobQueue:
    """按 provider 分道的内存 FIFO 队列：worker 从自己 provider 的道里匀速取活，
    避免一家 provider 的活堵住另一家。"""

    def __init__(self):
        self._lanes: dict[str, deque] = defaultdict(deque)

    def enqueue(self, job_id: str, provider: str) -> None:
        self._lanes[provider].append(job_id)

    def dequeue(self, provider: str) -> str | None:
        lane = self._lanes.get(provider)
        return lane.popleft() if lane else None

    def size(self, provider: str) -> int:
        return len(self._lanes.get(provider, ()))

    def pending(self, provider: str) -> list[str]:
        return list(self._lanes.get(provider, ()))
```

- [ ] **Step 4: 运行确认 PASS**（3 passed）
- [ ] **Step 5: 全量 + 提交**（预期 69 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/tasks/__init__.py backend/tasks/queue.py tests/test_task_queue.py
git commit -m "feat: JobQueue (per-provider FIFO lanes)"
```

---

### Task 2: ConcurrencyGuard（每用户在跑上限，公平）

**Files:** Create `backend/tasks/concurrency.py`; Test `tests/test_concurrency_guard.py`

- [ ] **Step 1: 写失败测试** `tests/test_concurrency_guard.py`:
```python
from backend.tasks.concurrency import ConcurrencyGuard


def test_acquire_up_to_limit_then_refuse():
    g = ConcurrencyGuard(max_per_user=2)
    assert g.try_acquire("u1") is True
    assert g.try_acquire("u1") is True
    assert g.try_acquire("u1") is False    # 到上限，拒绝
    assert g.active("u1") == 2


def test_release_frees_a_slot():
    g = ConcurrencyGuard(max_per_user=1)
    assert g.try_acquire("u1") is True
    assert g.try_acquire("u1") is False
    g.release("u1")
    assert g.try_acquire("u1") is True


def test_users_are_independent():
    g = ConcurrencyGuard(max_per_user=1)
    assert g.try_acquire("u1") is True
    assert g.try_acquire("u2") is True     # 不同用户互不占用
    assert g.active("u1") == 1 and g.active("u2") == 1


def test_release_below_zero_is_safe():
    g = ConcurrencyGuard(max_per_user=1)
    g.release("u1")                        # 没占用也不报错/不变负
    assert g.active("u1") == 0
```

- [ ] **Step 2: 运行确认 FAIL**
- [ ] **Step 3: 实现** `backend/tasks/concurrency.py`:
```python
from collections import defaultdict


class ConcurrencyGuard:
    """每用户"在跑任务数"上限。保证公平：单个用户占不满整个 worker 池。"""

    def __init__(self, max_per_user: int):
        self._max = max_per_user
        self._active: dict[str, int] = defaultdict(int)

    def try_acquire(self, user_id: str) -> bool:
        if self._active[user_id] >= self._max:
            return False
        self._active[user_id] += 1
        return True

    def release(self, user_id: str) -> None:
        if self._active[user_id] > 0:
            self._active[user_id] -= 1

    def active(self, user_id: str) -> int:
        return self._active[user_id]
```

- [ ] **Step 4: 运行确认 PASS**（4 passed）
- [ ] **Step 5: 全量 + 提交**（预期 73 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/tasks/concurrency.py tests/test_concurrency_guard.py
git commit -m "feat: ConcurrencyGuard (per-user in-flight limit)"
```

---

### Task 3: DailyCostCap（每日美元硬上限）

**Files:** Create `backend/tasks/cost_cap.py`; Test `tests/test_daily_cost_cap.py`

- [ ] **Step 1: 写失败测试** `tests/test_daily_cost_cap.py`:
```python
import pytest
from backend.tasks.cost_cap import DailyCostCap, DailyCostExceeded


def test_under_limit_allows_and_accumulates():
    cap = DailyCostCap(daily_limit_usd=10.0)
    assert cap.can_spend("2026-07-22", 4.0) is True
    cap.record("2026-07-22", 4.0)
    cap.record("2026-07-22", 3.0)
    assert cap.spent("2026-07-22") == 7.0


def test_boundary_exact_limit_allowed():
    cap = DailyCostCap(daily_limit_usd=10.0)
    cap.record("d", 10.0)
    assert cap.spent("d") == 10.0
    assert cap.can_spend("d", 0.01) is False


def test_over_limit_refused_and_record_raises():
    cap = DailyCostCap(daily_limit_usd=5.0)
    cap.record("d", 4.5)
    assert cap.can_spend("d", 1.0) is False
    with pytest.raises(DailyCostExceeded):
        cap.record("d", 1.0)
    assert cap.spent("d") == 4.5          # 拒绝的花费不计入


def test_days_are_isolated():
    cap = DailyCostCap(daily_limit_usd=5.0)
    cap.record("2026-07-22", 5.0)
    assert cap.can_spend("2026-07-23", 5.0) is True   # 新的一天重置
```

- [ ] **Step 2: 运行确认 FAIL**
- [ ] **Step 3: 实现** `backend/tasks/cost_cap.py`:
```python
from collections import defaultdict


class DailyCostExceeded(RuntimeError):
    """当日累计成本已达每日硬上限。"""


class DailyCostCap:
    """每日成本硬上限（美元）。按 day 键累计；超限拒绝。day 由外部传入
    （如 'YYYY-MM-DD'）以便确定性测试，也便于对齐用户所在时区。"""

    def __init__(self, daily_limit_usd: float):
        self._limit = daily_limit_usd
        self._spent: dict[str, float] = defaultdict(float)

    def can_spend(self, day: str, amount_usd: float) -> bool:
        return self._spent[day] + amount_usd <= self._limit

    def record(self, day: str, amount_usd: float) -> None:
        if not self.can_spend(day, amount_usd):
            raise DailyCostExceeded(f"{day} 已达每日上限 ${self._limit}")
        self._spent[day] += amount_usd

    def spent(self, day: str) -> float:
        return self._spent[day]
```

- [ ] **Step 4: 运行确认 PASS**（4 passed）
- [ ] **Step 5: 全量 + 提交**（预期 77 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/tasks/cost_cap.py tests/test_daily_cost_cap.py
git commit -m "feat: DailyCostCap (per-day USD hard cap)"
```

---

### Task 4: retry_with_backoff（429 指数退避，sleep 可注入）

**Files:** Create `backend/tasks/retry.py`; Test `tests/test_retry_backoff.py`

- [ ] **Step 1: 写失败测试** `tests/test_retry_backoff.py`:
```python
import pytest
from backend.tasks.retry import retry_with_backoff


class Rate(Exception):
    pass


def _recorder():
    delays = []
    return delays, (lambda d: delays.append(d))


def test_success_first_try_no_sleep():
    delays, sleep = _recorder()
    out = retry_with_backoff(lambda: "ok", is_retryable=lambda e: True, sleep=sleep)
    assert out == "ok"
    assert delays == []


def test_retries_then_succeeds_with_exponential_delays():
    delays, sleep = _recorder()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Rate()
        return "done"

    out = retry_with_backoff(
        flaky, is_retryable=lambda e: isinstance(e, Rate),
        max_attempts=5, base_delay=1.0, sleep=sleep,
    )
    assert out == "done"
    assert calls["n"] == 3
    assert delays == [1.0, 2.0]      # 指数退避：1, 2


def test_non_retryable_reraises_immediately():
    delays, sleep = _recorder()
    with pytest.raises(ValueError):
        retry_with_backoff(
            lambda: (_ for _ in ()).throw(ValueError("nope")),
            is_retryable=lambda e: isinstance(e, Rate), sleep=sleep,
        )
    assert delays == []


def test_exhausts_attempts_then_reraises():
    delays, sleep = _recorder()

    def always():
        raise Rate()

    with pytest.raises(Rate):
        retry_with_backoff(
            always, is_retryable=lambda e: True,
            max_attempts=3, base_delay=1.0, sleep=sleep,
        )
    assert delays == [1.0, 2.0]      # 3 次尝试之间睡 2 次
```

- [ ] **Step 2: 运行确认 FAIL**
- [ ] **Step 3: 实现** `backend/tasks/retry.py`:
```python
import time


def retry_with_backoff(
    fn,
    *,
    is_retryable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep=time.sleep,
):
    """调用 fn()；命中可重试错误（如 429/RateLimit）则指数退避后重试，
    超过 max_attempts 或遇不可重试错误则原样重抛。sleep 可注入以便测试。

    退避序列：base_delay * 2**0, 2**1, ...（第 n 次失败后睡 base_delay*2**(n-1)）。
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            if attempt >= max_attempts or not is_retryable(e):
                raise
            sleep(base_delay * (2 ** (attempt - 1)))
```

- [ ] **Step 4: 运行确认 PASS**（4 passed）
- [ ] **Step 5: 全量 + 提交**（预期 81 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/tasks/retry.py tests/test_retry_backoff.py
git commit -m "feat: retry_with_backoff (exponential 429 retry, injectable sleep)"
```

---

## P1e 完成判据

- `uv run python -m pytest -v` → **81 passed + 3 skipped**。
- `JobQueue`：按 provider 分道 FIFO，道间隔离。
- `ConcurrencyGuard`：每用户在跑上限，公平；release 安全不变负。
- `DailyCostCap`：按天累计、边界=上限放行、超限 `can_spend=False` 且 `record` 抛 `DailyCostExceeded`、跨天重置。
- `retry_with_backoff`：首次成功不睡；可重试错误指数退避；不可重试立即重抛；超次数重抛；delays 确定。
- 未改动任何既有文件。

## 交给 P1f 的接口

- P1f 的 FastAPI 层用这四件组合出真 worker：入队 `JobQueue.enqueue` → worker 循环 `dequeue(provider)` → `ConcurrencyGuard.try_acquire(user)` 通过才起跑 → 每轮出图前 `DailyCostCap.can_spend(day, estimate_cost(...))` 把关、之后 `record` → provider 调用包在 `retry_with_backoff` 里 → 进度经 SSE 推送、`SessionManager.record_round/add_usage` 落盘。
- SSE 端点、asyncio worker 池、真事件循环在 P1f 实现（本层组件都是同步、可被 async worker 直接调用）。
```
