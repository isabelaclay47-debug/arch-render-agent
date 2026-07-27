# ArchRender Web — P0 核心抽取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `archrender-web/backend` 新项目骨架，把皇冠资产 `prompt_engine.py` 原样搬入，并定义两个可插拔接口 `ImageEngine` / `DirectorBrain` + 各自的假实现 + 一个用假实现即可端到端跑通的"单轮出图"编排接缝——全部有测试覆盖，不触真 API、不碰老 `app.py`。

**Architecture:** 方案 B。新后端围绕两个抽象接口构建：`ImageEngine`（出图：`generate`/`edit`）与 `DirectorBrain`（导演脑：`chat`/`check_faithfulness`）。`prompt_engine.py`（纯函数、仅依赖 `re`）作为共享核心被两侧复用。P0 只交付接口 + 假实现 + 编排接缝，真引擎（Gemini/OpenAI）、真导演脑（Claude）、会话/异步/前端都留给 P1。

**Tech Stack:** Python 3.10+，pytest，`abc`/`dataclasses`（标准库）。无第三方运行时依赖。

---

## 文件结构（P0 创建/修改）

```
archrender-web/
  pyproject.toml                         # 项目 + pytest 配置
  backend/
    __init__.py
    core/
      __init__.py
      prompt_engine.py                   # 从 ArchRenderAgent 原样拷贝（仅依赖 re）
    engines/
      __init__.py
      base.py                            # ImageEngine ABC
      fake.py                            # FakeImageEngine（测试用）
    brain/
      __init__.py
      base.py                            # DirectorBrain ABC + FaithfulnessVerdict
      fake.py                            # FakeDirectorBrain（测试用）
    orchestrator/
      __init__.py
      director_loop.py                   # run_one_round 接缝
  tests/
    __init__.py
    test_core_prompt_engine.py
    test_engines_fake.py
    test_brain_fake.py
    test_orchestrator_seam.py
```

老 `ArchRenderAgent/app.py`、`gemini_client.py`、`chatgpt_client.py` 一律不动。

---

### Task 1: 项目骨架 + pytest 能跑

**Files:**
- Create: `archrender-web/pyproject.toml`
- Create: `archrender-web/backend/__init__.py`（空）
- Create: `archrender-web/tests/__init__.py`（空）
- Test: `archrender-web/tests/test_smoke.py`

- [ ] **Step 1: 写失败测试**

`archrender-web/tests/test_smoke.py`:
```python
def test_backend_package_importable():
    import backend  # noqa: F401
    assert True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd archrender-web && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend'`

- [ ] **Step 3: 写最小实现**

`archrender-web/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "archrender-web"
version = "0.0.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`archrender-web/backend/__init__.py`: 空文件。
`archrender-web/tests/__init__.py`: 空文件。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd archrender-web && python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd archrender-web
git init 2>/dev/null || true
git add pyproject.toml backend/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold archrender-web backend + pytest"
```

---

### Task 2: 原样搬入 prompt_engine（特征测试锁定行为）

`prompt_engine.py` 仅 `import re`、无外部数据文件，可直接整文件拷贝。特征测试（characterization test）证明搬家后行为不变。

**Files:**
- Create: `archrender-web/backend/core/__init__.py`（空）
- Create: `archrender-web/backend/core/prompt_engine.py`（拷贝自 `ArchRenderAgent/prompt_engine.py`）
- Test: `archrender-web/tests/test_core_prompt_engine.py`

- [ ] **Step 1: 写失败测试**

`archrender-web/tests/test_core_prompt_engine.py`:
```python
from backend.core import prompt_engine


def test_generation_message_embeds_prompt_and_returns_str():
    msg = prompt_engine.generation_message("a modern concrete house", quality="标准", ratio="跟随原图")
    assert isinstance(msg, str)
    assert "a modern concrete house" in msg


def test_parse_director_reply_returns_dict():
    result = prompt_engine.parse_director_reply("任意文本")
    assert isinstance(result, dict)


def test_director_system_prompt_nonempty():
    assert isinstance(prompt_engine.director_system_prompt(), str)
    assert len(prompt_engine.director_system_prompt()) > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd archrender-web && python -m pytest tests/test_core_prompt_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.core'`

- [ ] **Step 3: 写最小实现（拷贝文件）**

```bash
cd archrender-web
mkdir -p backend/core
: > backend/core/__init__.py
cp ../prompt_engine.py backend/core/prompt_engine.py
```
（不修改 `prompt_engine.py` 任何一行——它只依赖 `re`。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd archrender-web && python -m pytest tests/test_core_prompt_engine.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd archrender-web
git add backend/core/__init__.py backend/core/prompt_engine.py tests/test_core_prompt_engine.py
git commit -m "feat: vendor prompt_engine into backend/core with characterization tests"
```

---

### Task 3: 定义 ImageEngine 接口 + FakeImageEngine

`ImageEngine` 抽象"出图"这一步：拿一段提示词文本 + 若干输入图 → 产出一张图。`generate` 从底图出图，`edit` 对上一版做（可带 mask 的）局部编辑。假实现把一张 1x1 PNG 写到 out_path，供上层测试。

**Files:**
- Create: `archrender-web/backend/engines/__init__.py`（空）
- Create: `archrender-web/backend/engines/base.py`
- Create: `archrender-web/backend/engines/fake.py`
- Test: `archrender-web/tests/test_engines_fake.py`

- [ ] **Step 1: 写失败测试**

`archrender-web/tests/test_engines_fake.py`:
```python
from pathlib import Path
from backend.engines.fake import FakeImageEngine


def test_fake_generate_writes_file_and_records_call(tmp_path):
    eng = FakeImageEngine()
    base = tmp_path / "base.png"
    base.write_bytes(b"basepng")
    out = tmp_path / "round1.png"

    result = eng.generate("prompt text", [base], out_path=out)

    assert result == out
    assert out.exists()
    assert eng.calls == [("generate", "prompt text", [base], out)]


def test_fake_edit_writes_file_and_records_call(tmp_path):
    eng = FakeImageEngine()
    prev = tmp_path / "prev.png"
    prev.write_bytes(b"prevpng")
    mask = tmp_path / "mask.png"
    mask.write_bytes(b"maskpng")
    out = tmp_path / "edited.png"

    result = eng.edit(prev, mask, "fix the roof", out_path=out)

    assert result == out
    assert out.exists()
    assert eng.calls == [("edit", "fix the roof", [prev, mask], out)]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd archrender-web && python -m pytest tests/test_engines_fake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.engines.fake'`

- [ ] **Step 3: 写最小实现**

`archrender-web/backend/engines/base.py`:
```python
from abc import ABC, abstractmethod
from pathlib import Path


class ImageEngineError(RuntimeError):
    """出图引擎的统一错误类型（真实现遇到 API/浏览器失败时抛出）。"""


class ImageEngine(ABC):
    """可插拔出图引擎。P1 的 Gemini/OpenAI、P3 的 Browser 都实现本接口。"""

    name: str = "base"

    @abstractmethod
    def generate(self, prompt_text: str, input_images: list[Path], *, out_path: Path) -> Path:
        """从底图 + 提示词出一张新图，写到 out_path，返回 out_path。"""

    @abstractmethod
    def edit(self, prev_image: Path, mask: Path | None, prompt_text: str, *, out_path: Path) -> Path:
        """对 prev_image 做（可选 mask 限定区域的）局部编辑，写到 out_path，返回 out_path。"""
```

`archrender-web/backend/engines/fake.py`:
```python
from pathlib import Path
from backend.engines.base import ImageEngine

# 最小合法 PNG（1x1 透明像素）
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c6360000002000100"
    "05fe02fea7c1a4a80000000049454e44ae426082"
)


class FakeImageEngine(ImageEngine):
    """测试用假引擎：写一张 1x1 PNG 并记录每次调用，不触任何 API。"""

    name = "fake"

    def __init__(self):
        self.calls: list[tuple] = []

    def generate(self, prompt_text: str, input_images: list[Path], *, out_path: Path) -> Path:
        self.calls.append(("generate", prompt_text, list(input_images), out_path))
        out_path.write_bytes(_PNG_1x1)
        return out_path

    def edit(self, prev_image: Path, mask: Path | None, prompt_text: str, *, out_path: Path) -> Path:
        images = [prev_image] + ([mask] if mask is not None else [])
        self.calls.append(("edit", prompt_text, images, out_path))
        out_path.write_bytes(_PNG_1x1)
        return out_path
```

`archrender-web/backend/engines/__init__.py`: 空文件。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd archrender-web && python -m pytest tests/test_engines_fake.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
cd archrender-web
git add backend/engines/
git add tests/test_engines_fake.py
git commit -m "feat: ImageEngine interface + FakeImageEngine"
```

---

### Task 4: 定义 DirectorBrain 接口 + FakeDirectorBrain

`DirectorBrain` 抽象"导演脑"：`chat` 是通用的一次多模态问答（读图/写词都靠它，配 `prompt_engine` 造的 system/message），`check_faithfulness` 拿底图和渲染图比对、判定该增量修还是从底图重画。返回结构化 `FaithfulnessVerdict`。

**Files:**
- Create: `archrender-web/backend/brain/__init__.py`（空）
- Create: `archrender-web/backend/brain/base.py`
- Create: `archrender-web/backend/brain/fake.py`
- Test: `archrender-web/tests/test_brain_fake.py`

- [ ] **Step 1: 写失败测试**

`archrender-web/tests/test_brain_fake.py`:
```python
from pathlib import Path
from backend.brain.base import FaithfulnessVerdict
from backend.brain.fake import FakeDirectorBrain


def test_fake_chat_returns_scripted_reply_and_records_call(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    brain = FakeDirectorBrain(chat_replies=["understood: a house"])

    reply = brain.chat("sys prompt", "user message", [img])

    assert reply == "understood: a house"
    assert brain.chat_calls == [("sys prompt", "user message", [img])]


def test_fake_check_faithfulness_defaults_to_clean_refine(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"b")
    render = tmp_path / "r.png"; render.write_bytes(b"r")
    brain = FakeDirectorBrain()

    verdict = brain.check_faithfulness(base, render, iteration=1)

    assert isinstance(verdict, FaithfulnessVerdict)
    assert verdict.tampered is False
    assert verdict.action == "refine"


def test_fake_check_faithfulness_can_be_scripted_to_redraw(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"b")
    render = tmp_path / "r.png"; render.write_bytes(b"r")
    verdict_in = FaithfulnessVerdict(tampered=True, action="redraw", fix_instruction_zh="楼层数被改了，从底图重画")
    brain = FakeDirectorBrain(faithfulness_verdicts=[verdict_in])

    verdict = brain.check_faithfulness(base, render, iteration=1)

    assert verdict.action == "redraw"
    assert verdict.tampered is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd archrender-web && python -m pytest tests/test_brain_fake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.brain.base'`

- [ ] **Step 3: 写最小实现**

`archrender-web/backend/brain/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class DirectorBrainError(RuntimeError):
    """导演脑的统一错误类型。"""


@dataclass
class FaithfulnessVerdict:
    tampered: bool          # 是否检测到对建筑几何的篡改
    action: str             # "refine"（增量修上一版） | "redraw"（从底图重画）
    fix_instruction_zh: str = ""   # 给下一轮的中文修正指令（可空）


class DirectorBrain(ABC):
    """导演脑：读图/写提示词/忠实度比对。P1 用 ClaudeBrain 实现；P3 可用浏览器 ChatGPT 实现。"""

    name: str = "base"

    @abstractmethod
    def chat(self, system: str, message: str, images: list[Path]) -> str:
        """一次多模态问答：给定 system 提示 + 用户 message + 若干图，返回文本回复。"""

    @abstractmethod
    def check_faithfulness(self, base: Path, render: Path, iteration: int) -> FaithfulnessVerdict:
        """比对底图与渲染图，判定是否篡改及下一步动作。"""
```

`archrender-web/backend/brain/fake.py`:
```python
from pathlib import Path
from backend.brain.base import DirectorBrain, FaithfulnessVerdict


class FakeDirectorBrain(DirectorBrain):
    """测试用假导演脑：按脚本返回，不触任何 API。"""

    name = "fake"

    def __init__(self, chat_replies=None, faithfulness_verdicts=None):
        self._chat_replies = list(chat_replies or [])
        self._verdicts = list(faithfulness_verdicts or [])
        self.chat_calls: list[tuple] = []
        self.faithfulness_calls: list[tuple] = []

    def chat(self, system: str, message: str, images: list[Path]) -> str:
        self.chat_calls.append((system, message, list(images)))
        if self._chat_replies:
            return self._chat_replies.pop(0)
        return ""

    def check_faithfulness(self, base: Path, render: Path, iteration: int) -> FaithfulnessVerdict:
        self.faithfulness_calls.append((base, render, iteration))
        if self._verdicts:
            return self._verdicts.pop(0)
        return FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="")
```

`archrender-web/backend/brain/__init__.py`: 空文件。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd archrender-web && python -m pytest tests/test_brain_fake.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
cd archrender-web
git add backend/brain/
git add tests/test_brain_fake.py
git commit -m "feat: DirectorBrain interface + FaithfulnessVerdict + FakeDirectorBrain"
```

---

### Task 5: 编排接缝 run_one_round（用假实现端到端跑通）

这是 P0 的收口：一个不依赖任何真 API 的"单轮出图"函数，把 `prompt_engine`（造消息）→ `ImageEngine`（出图）→ `DirectorBrain`（忠实度比对）串起来。它证明整套可插拔架构在真引擎接入前就已成立。

**Files:**
- Create: `archrender-web/backend/orchestrator/__init__.py`（空）
- Create: `archrender-web/backend/orchestrator/director_loop.py`
- Test: `archrender-web/tests/test_orchestrator_seam.py`

- [ ] **Step 1: 写失败测试**

`archrender-web/tests/test_orchestrator_seam.py`:
```python
from pathlib import Path
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.brain.base import FaithfulnessVerdict
from backend.orchestrator.director_loop import run_one_round


def test_run_one_round_wires_engine_and_brain(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"basepng")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(
        faithfulness_verdicts=[FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="ok")]
    )

    render, verdict = run_one_round(
        brain, engine,
        base_image=base, prompt_en="a modern concrete house",
        iteration=1, out_dir=tmp_path,
    )

    # 引擎被调用出图，产出文件存在
    assert render.exists()
    assert render == tmp_path / "round1.png"
    # 传给引擎的消息里带了英文提示词（prompt_engine.generation_message 的产物）
    assert engine.calls[0][0] == "generate"
    assert "a modern concrete house" in engine.calls[0][1]
    assert engine.calls[0][2] == [base]
    # 导演脑对底图与渲染图做了忠实度比对
    assert brain.faithfulness_calls == [(base, render, 1)]
    assert verdict.action == "refine"


def test_run_one_round_redraw_verdict_is_propagated(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"b")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(
        faithfulness_verdicts=[FaithfulnessVerdict(tampered=True, action="redraw", fix_instruction_zh="楼层被改")]
    )

    render, verdict = run_one_round(
        brain, engine, base_image=base, prompt_en="x", iteration=2, out_dir=tmp_path,
    )

    assert render == tmp_path / "round2.png"
    assert verdict.action == "redraw"
    assert verdict.tampered is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd archrender-web && python -m pytest tests/test_orchestrator_seam.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.orchestrator.director_loop'`

- [ ] **Step 3: 写最小实现**

`archrender-web/backend/orchestrator/director_loop.py`:
```python
from pathlib import Path
from backend.core import prompt_engine
from backend.engines.base import ImageEngine
from backend.brain.base import DirectorBrain, FaithfulnessVerdict


def run_one_round(
    brain: DirectorBrain,
    engine: ImageEngine,
    *,
    base_image: Path,
    prompt_en: str,
    iteration: int,
    out_dir: Path,
    quality: str = "标准",
    ratio: str = "跟随原图",
) -> tuple[Path, FaithfulnessVerdict]:
    """单轮：造消息 → 出图 → 忠实度比对。返回 (渲染图路径, 判定)。

    这是引擎无关的接缝——换真 Gemini/OpenAI/Claude 时本函数一行不用改。
    """
    message = prompt_engine.generation_message(prompt_en, quality=quality, ratio=ratio)
    out_path = out_dir / f"round{iteration}.png"
    render = engine.generate(message, [base_image], out_path=out_path)
    verdict = brain.check_faithfulness(base_image, render, iteration)
    return render, verdict
```

`archrender-web/backend/orchestrator/__init__.py`: 空文件。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd archrender-web && python -m pytest tests/test_orchestrator_seam.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 全量测试 + 提交**

Run: `cd archrender-web && python -m pytest -v`
Expected: 全部 PASS（smoke 1 + core 3 + engines 2 + brain 3 + orchestrator 2 = 11 passed）

```bash
cd archrender-web
git add backend/orchestrator/ tests/test_orchestrator_seam.py
git commit -m "feat: engine-agnostic run_one_round seam wired end-to-end with fakes"
```

---

## P0 完成判据

- `cd archrender-web && python -m pytest -v` → 11 passed。
- `backend/core/prompt_engine.py` 与老 `ArchRenderAgent/prompt_engine.py` 字节一致（`diff` 无输出）。
- 老 `app.py` / `gemini_client.py` / `chatgpt_client.py` 未被改动。
- 已具备两个可插拔接口 + 假实现 + 引擎无关编排接缝——P1 接真引擎/导演脑/会话/异步/前端时，直接实现接口即可，不改本接缝。

## 交给 P1 的接口契约（供下一份计划引用）

- `ImageEngine.generate(prompt_text, input_images, *, out_path) -> Path`
- `ImageEngine.edit(prev_image, mask, prompt_text, *, out_path) -> Path`
- `DirectorBrain.chat(system, message, images) -> str`
- `DirectorBrain.check_faithfulness(base, render, iteration) -> FaithfulnessVerdict`
- `orchestrator.director_loop.run_one_round(brain, engine, *, base_image, prompt_en, iteration, out_dir, quality, ratio) -> (Path, FaithfulnessVerdict)`
