# ArchRender Web — P1a 真·出图引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 P0 已定的 `ImageEngine` 接口后面接上真·出图引擎——一个引擎无关的 `ApiImageEngine`（负责文件↔字节的搬运与错误映射）+ 两个真 client（Gemini 图像 / OpenAI gpt-image）+ 一个引擎工厂。单测全程注入假 client、不烧一分钱 API；真 API 只由默认 skip、需 key 才跑的冒烟测覆盖。

**Architecture:** DRY——两家 provider 的差异只在"怎么调 API"，文件↔字节搬运/错误处理完全相同，所以抽出单一 `ApiImageEngine(ImageEngine)` 包裹一个满足 `ImageBackendClient` 协议的 client；`GeminiImageClient` / `OpenAIImageClient` 是两个薄 client。工厂 `get_image_engine(name)` 按名装配。

**Tech Stack:** Python 3.10+，pytest，`typing.Protocol`。真 client 用各家官方 SDK 或 httpx（实现时定）。**provider 的请求/返回形状必须用 context7 mcp 查实时官方文档核对，不得凭记忆写死。**

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（裸 `python -m pytest` 会失败；若见 "No tests collected" 是代理干扰，改用 `uv run --with pytest python -m pytest -v`）。

---

## 文件结构（P1a）

```
backend/engines/
  base.py            # 既有 ImageEngine ABC + ImageEngineError；本计划追加 ImageBackendClient Protocol
  api_engine.py      # 新增：ApiImageEngine(ImageEngine)，包裹任意 client
  clients/
    __init__.py
    fake.py          # 新增：FakeBackendClient（测试用）
    gemini.py        # 新增：GeminiImageClient（真，google-genai / httpx）
    openai.py        # 新增：OpenAIImageClient（真，gpt-image）
  factory.py         # 新增：get_image_engine(name) -> ImageEngine
tests/
  test_api_engine.py
  test_engine_factory.py
  test_real_clients_smoke.py   # 默认 skip，需 GEMINI_API_KEY / OPENAI_API_KEY
```

---

### Task 1: ImageBackendClient 协议 + ApiImageEngine + FakeBackendClient

引擎无关的搬运层：`ApiImageEngine` 把 `ImageEngine.generate/edit`（收发文件 Path）翻译成 `ImageBackendClient.create_image/edit_image`（收发 bytes），并把 client 抛的异常统一映射成 `ImageEngineError`。这是 P1a 里最有价值、且完全不需要真 API 的部分。

**Files:**
- Modify: `backend/engines/base.py`（在文件末尾追加 `ImageBackendClient` Protocol）
- Create: `backend/engines/api_engine.py`
- Create: `backend/engines/clients/__init__.py`（空）
- Create: `backend/engines/clients/fake.py`
- Test: `tests/test_api_engine.py`

- [ ] **Step 1: 写失败测试** `tests/test_api_engine.py`:
```python
import pytest
from pathlib import Path
from backend.engines.api_engine import ApiImageEngine
from backend.engines.base import ImageEngine, ImageEngineError
from backend.engines.clients.fake import FakeBackendClient


def _write(p: Path, data: bytes) -> Path:
    p.write_bytes(data)
    return p


def test_api_engine_is_imageengine():
    assert issubclass(ApiImageEngine, ImageEngine)


def test_generate_reads_inputs_calls_client_writes_output(tmp_path):
    client = FakeBackendClient(result=b"RENDERED")
    eng = ApiImageEngine(client, name="gemini")
    base = _write(tmp_path / "base.png", b"BASEBYTES")
    out = tmp_path / "round1.png"

    result = eng.generate("a concrete house", [base], out_path=out)

    assert result == out
    assert out.read_bytes() == b"RENDERED"
    # client 收到 (prompt, [底图字节])
    assert client.create_calls == [("a concrete house", [b"BASEBYTES"])]
    assert eng.name == "gemini"


def test_edit_passes_prev_and_mask_bytes(tmp_path):
    client = FakeBackendClient(result=b"EDITED")
    eng = ApiImageEngine(client, name="openai")
    prev = _write(tmp_path / "prev.png", b"PREV")
    mask = _write(tmp_path / "mask.png", b"MASK")
    out = tmp_path / "e.png"

    result = eng.edit(prev, mask, "fix roof", out_path=out)

    assert result == out
    assert out.read_bytes() == b"EDITED"
    assert client.edit_calls == [(b"PREV", b"MASK", "fix roof")]


def test_edit_allows_none_mask(tmp_path):
    client = FakeBackendClient(result=b"EDITED")
    eng = ApiImageEngine(client, name="openai")
    prev = _write(tmp_path / "prev.png", b"PREV")
    out = tmp_path / "e.png"

    eng.edit(prev, None, "brighten", out_path=out)

    assert client.edit_calls == [(b"PREV", None, "brighten")]


def test_client_failure_maps_to_ImageEngineError(tmp_path):
    client = FakeBackendClient(raise_exc=ValueError("boom"))
    eng = ApiImageEngine(client, name="gemini")
    base = _write(tmp_path / "base.png", b"B")
    out = tmp_path / "o.png"

    with pytest.raises(ImageEngineError):
        eng.generate("x", [base], out_path=out)
    # 失败时不留半截文件
    assert not out.exists()
```

- [ ] **Step 2: 运行确认 FAIL**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_api_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.engines.api_engine'`

- [ ] **Step 3: 实现**

在 `backend/engines/base.py` **末尾追加**（不改已有内容）:
```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class ImageBackendClient(Protocol):
    """出图后端 client 协议：收发原始字节，屏蔽各 provider 差异。"""

    def create_image(self, prompt: str, images: list[bytes]) -> bytes: ...
    def edit_image(self, prev_image: bytes, mask: bytes | None, prompt: str) -> bytes: ...
```

`backend/engines/api_engine.py`:
```python
from pathlib import Path
from backend.engines.base import ImageEngine, ImageEngineError, ImageBackendClient


class ApiImageEngine(ImageEngine):
    """引擎无关的 API 出图引擎：文件↔字节搬运 + 错误统一映射。

    provider 差异全在注入的 client 里，本类对 Gemini/OpenAI 通用。
    """

    def __init__(self, client: ImageBackendClient, *, name: str):
        self._client = client
        self.name = name

    def generate(self, prompt_text: str, input_images: list[Path], *, out_path: Path) -> Path:
        images = [p.read_bytes() for p in input_images]
        try:
            data = self._client.create_image(prompt_text, images)
        except Exception as e:  # 统一映射，避免 provider 异常泄漏到上层
            raise ImageEngineError(f"{self.name} create_image failed: {e}") from e
        out_path.write_bytes(data)
        return out_path

    def edit(self, prev_image: Path, mask: Path | None, prompt_text: str, *, out_path: Path) -> Path:
        prev = prev_image.read_bytes()
        mask_bytes = mask.read_bytes() if mask is not None else None
        try:
            data = self._client.edit_image(prev, mask_bytes, prompt_text)
        except Exception as e:
            raise ImageEngineError(f"{self.name} edit_image failed: {e}") from e
        out_path.write_bytes(data)
        return out_path
```

`backend/engines/clients/__init__.py`: 空文件。

`backend/engines/clients/fake.py`:
```python
class FakeBackendClient:
    """测试用假 client：返回固定字节或抛指定异常，并记录调用。"""

    def __init__(self, result: bytes = b"FAKEIMG", raise_exc: Exception | None = None):
        self._result = result
        self._raise = raise_exc
        self.create_calls: list[tuple] = []
        self.edit_calls: list[tuple] = []

    def create_image(self, prompt: str, images: list[bytes]) -> bytes:
        self.create_calls.append((prompt, list(images)))
        if self._raise:
            raise self._raise
        return self._result

    def edit_image(self, prev_image: bytes, mask: bytes | None, prompt: str) -> bytes:
        self.edit_calls.append((prev_image, mask, prompt))
        if self._raise:
            raise self._raise
        return self._result
```

- [ ] **Step 4: 运行确认 PASS**（5 passed）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_api_engine.py -v`

- [ ] **Step 5: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 16 passed：P0 的 11 + 本任务 5）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/engines/base.py backend/engines/api_engine.py backend/engines/clients/ tests/test_api_engine.py
git commit -m "feat: ApiImageEngine wraps injectable ImageBackendClient (provider-agnostic)"
```

---

### Task 2: GeminiImageClient（真，注入式传输，冒烟测默认 skip）

薄 client，把 `create_image/edit_image` 翻译成 Gemini 图像 API 调用。为可单测，构造函数接受一个可选 `transport`（默认真实 SDK/HTTP，测试注入假的）。**实现前必须用 context7 mcp 查 `google-genai` 或 Gemini REST 图像生成/编辑的当前请求与返回形状，按查到的写，不要凭记忆。**

**Files:**
- Create: `backend/engines/clients/gemini.py`
- Test: `tests/test_real_clients_smoke.py`（本任务先建，含 Gemini 冒烟测；OpenAI 冒烟测 Task 3 追加）

- [ ] **Step 1: 写单测（注入假 transport，验证翻译逻辑）** — 追加到 `tests/test_api_engine.py` 或新建 `tests/test_gemini_client.py`:
```python
from backend.engines.clients.gemini import GeminiImageClient


class _StubTransport:
    def __init__(self):
        self.calls = []
    def generate_image_bytes(self, prompt, images, mask=None, prev=None):
        self.calls.append((prompt, images, mask, prev))
        return b"GEMINI_PNG"


def test_gemini_create_image_delegates_to_transport():
    t = _StubTransport()
    c = GeminiImageClient(transport=t)
    out = c.create_image("a house", [b"BASE"])
    assert out == b"GEMINI_PNG"
    assert t.calls == [("a house", [b"BASE"], None, None)]


def test_gemini_edit_image_delegates_with_prev_and_mask():
    t = _StubTransport()
    c = GeminiImageClient(transport=t)
    out = c.edit_image(b"PREV", b"MASK", "fix")
    assert out == b"GEMINI_PNG"
    assert t.calls == [("fix", [], b"MASK", b"PREV")]
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: gemini）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_gemini_client.py -v`

- [ ] **Step 3: 实现** `backend/engines/clients/gemini.py`：
  - 定义内部 `_RealGeminiTransport`：用 context7 查到的官方形状，调 gemini-2.5-flash-image（nano-banana）做图生图/编辑，取回图片字节。构造需 `GEMINI_API_KEY`（读环境变量）。
  - `GeminiImageClient(transport=None)`：`transport or _RealGeminiTransport()`；`create_image`/`edit_image` 委托给 transport 的 `generate_image_bytes(...)`（签名如 stub 所示：prompt, images, mask, prev）。
  - 依赖（google-genai 或 httpx）用 `uv add` 加入。
  （实现细节以 context7 查到的官方文档为准；对外方法签名固定为上面 stub 约定的形状。）

- [ ] **Step 4: 运行确认 PASS**（2 passed）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_gemini_client.py -v`

- [ ] **Step 5: 建冒烟测（默认 skip）** `tests/test_real_clients_smoke.py`:
```python
import os
import pytest
from pathlib import Path
from backend.engines.api_engine import ApiImageEngine
from backend.engines.clients.gemini import GeminiImageClient


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="需要 GEMINI_API_KEY 才跑真 API")
def test_gemini_real_generate(tmp_path):
    eng = ApiImageEngine(GeminiImageClient(), name="gemini")
    base = tmp_path / "base.png"; base.write_bytes(Path("tests/fixtures/base.png").read_bytes())
    out = tmp_path / "out.png"
    eng.generate("a photorealistic modern concrete house, dusk", [base], out_path=out)
    assert out.exists() and out.stat().st_size > 1000
```
（需准备 `tests/fixtures/base.png` 小样图；无 key 时该测自动 skip，不影响绿。）

- [ ] **Step 6: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 18 passed + 1 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/engines/clients/gemini.py tests/test_gemini_client.py tests/test_real_clients_smoke.py tests/fixtures/ pyproject.toml uv.lock
git commit -m "feat: GeminiImageClient (injectable transport) + skip-by-default real smoke test"
```

---

### Task 3: OpenAIImageClient（真，gpt-image，同 Task 2 模式）

与 Task 2 完全同构，只换 provider。**实现前用 context7 mcp 查 OpenAI 图像（gpt-image-2）生成/编辑的当前请求与返回形状。**

**Files:**
- Create: `backend/engines/clients/openai.py`
- Test: `tests/test_openai_client.py` + 追加到 `tests/test_real_clients_smoke.py`

- [ ] **Step 1: 写单测** `tests/test_openai_client.py`（结构同 Task2 的 gemini 单测，把 `GeminiImageClient` 换成 `OpenAIImageClient`、返回字节改 `b"OPENAI_PNG"`；`_StubTransport` 同款）:
```python
from backend.engines.clients.openai import OpenAIImageClient


class _StubTransport:
    def __init__(self):
        self.calls = []
    def generate_image_bytes(self, prompt, images, mask=None, prev=None):
        self.calls.append((prompt, images, mask, prev))
        return b"OPENAI_PNG"


def test_openai_create_image_delegates_to_transport():
    t = _StubTransport()
    c = OpenAIImageClient(transport=t)
    assert c.create_image("a house", [b"BASE"]) == b"OPENAI_PNG"
    assert t.calls == [("a house", [b"BASE"], None, None)]


def test_openai_edit_image_delegates_with_prev_and_mask():
    t = _StubTransport()
    c = OpenAIImageClient(transport=t)
    assert c.edit_image(b"PREV", b"MASK", "fix") == b"OPENAI_PNG"
    assert t.calls == [("fix", [], b"MASK", b"PREV")]
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: openai client）
- [ ] **Step 3: 实现** `backend/engines/clients/openai.py`：`_RealOpenAITransport`（context7 查到的 gpt-image-2 形状，需 `OPENAI_API_KEY`）+ `OpenAIImageClient(transport=None)`，委托同 Task2。依赖用 `uv add`。
- [ ] **Step 4: 运行确认 PASS**（2 passed）
- [ ] **Step 5: 追加冒烟测** 到 `tests/test_real_clients_smoke.py`（`@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), ...)`，用 `OpenAIImageClient()`，其余同 Gemini 冒烟测）。
- [ ] **Step 6: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 20 passed + 2 skipped）
```bash
git add backend/engines/clients/openai.py tests/test_openai_client.py tests/test_real_clients_smoke.py pyproject.toml uv.lock
git commit -m "feat: OpenAIImageClient (injectable transport) + skip-by-default real smoke test"
```

---

### Task 4: 引擎工厂 get_image_engine(name)

按名装配引擎，供上层（P1d/P1f）用字符串选引擎。工厂用一个可覆盖的注册表，单测注入假 client 工厂，避免需要真 key。

**Files:**
- Create: `backend/engines/factory.py`
- Test: `tests/test_engine_factory.py`

- [ ] **Step 1: 写失败测试** `tests/test_engine_factory.py`:
```python
import pytest
from backend.engines.factory import get_image_engine, KNOWN_ENGINES
from backend.engines.base import ImageEngine
from backend.engines.clients.fake import FakeBackendClient


def test_known_engines_lists_both():
    assert set(KNOWN_ENGINES) == {"gemini", "openai"}


def test_get_image_engine_builds_named_engine_with_injected_client():
    eng = get_image_engine("gemini", client_factory=lambda: FakeBackendClient())
    assert isinstance(eng, ImageEngine)
    assert eng.name == "gemini"


def test_get_image_engine_rejects_unknown():
    with pytest.raises(ValueError):
        get_image_engine("midjourney", client_factory=lambda: FakeBackendClient())
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: factory）
- [ ] **Step 3: 实现** `backend/engines/factory.py`:
```python
from backend.engines.api_engine import ApiImageEngine
from backend.engines.base import ImageEngine

KNOWN_ENGINES = ("gemini", "openai")


def _default_client_factory(name: str):
    if name == "gemini":
        from backend.engines.clients.gemini import GeminiImageClient
        return GeminiImageClient()
    if name == "openai":
        from backend.engines.clients.openai import OpenAIImageClient
        return OpenAIImageClient()
    raise ValueError(f"unknown engine: {name}")


def get_image_engine(name: str, *, client_factory=None) -> ImageEngine:
    """按名装配出图引擎。client_factory 可注入（测试用），默认用真 client。"""
    if name not in KNOWN_ENGINES:
        raise ValueError(f"unknown engine: {name!r}, expected one of {KNOWN_ENGINES}")
    client = client_factory() if client_factory is not None else _default_client_factory(name)
    return ApiImageEngine(client, name=name)
```

- [ ] **Step 4: 运行确认 PASS**（3 passed）
- [ ] **Step 5: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 23 passed + 2 skipped）
```bash
git add backend/engines/factory.py tests/test_engine_factory.py
git commit -m "feat: get_image_engine factory (gemini|openai, injectable client)"
```

---

## P1a 完成判据

- `uv run python -m pytest -v` → 23 passed + 2 skipped（两个真 API 冒烟测在无 key 时 skip）。
- `ApiImageEngine` 通过 `issubclass(..., ImageEngine)`，且 generate/edit 正确搬运字节、失败映射 `ImageEngineError` 且不留半截文件。
- 两个真 client 的对外方法签名与 stub 约定一致；真 API 形状已用 context7 核对。
- 老 `app.py` 未改动。

## 交给后续子计划的接口

- `backend.engines.factory.get_image_engine(name, *, client_factory=None) -> ImageEngine`
- `ImageBackendClient` 协议（`create_image` / `edit_image`）——P3 的 `BrowserEngine` 也可走 `ApiImageEngine` 或自实现 `ImageEngine`。
