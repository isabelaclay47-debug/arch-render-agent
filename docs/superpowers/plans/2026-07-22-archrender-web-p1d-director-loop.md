# ArchRender Web — P1d 完整导演循环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把单轮 `run_one_round` 扩成完整导演循环：多轮 出图→忠实度→refine/redraw 分支（每轮把上轮的中文修正词译成英文再喂引擎），加区域编辑（mask→`engine.edit`），加确认闸门（understand→可编辑英文词）。

**Architecture:** 全部是引擎/导演脑无关的**纯编排函数**，靠注入的 `ImageEngine`/`DirectorBrain` 工作，单测用既有 `FakeImageEngine`/`FakeDirectorBrain`（脚本化 verdict + chat 回复），零 API。循环是**有界**的（跑 `n_rounds` 轮就返回全部轮次结果）——"每 N 张暂停"由调用方取 `n_rounds=N` 实现，人工闸门/续跑留给 P1f，本层不管异步。refine=在上一版增量改（输入上轮渲染图），redraw=从底图重画（输入底图），两者都用 `refine_message(fix_en)` 承载修正；`check_faithfulness` 恒以底图为基准。

**Tech Stack:** Python 3.10+，pytest。复用 `backend/core/prompt_engine`（`generation_message`/`refine_message`/`translate_instruction_prompt`/`regional_edit_message`/`director_system_prompt`）、`backend/engines`、`backend/brain`。

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`。P1d 开始前基线：**61 passed + 3 skipped**。

---

## 文件结构（P1d）

```
backend/orchestrator/
  director_loop.py   # 既有 run_one_round 保留不动；追加 RoundResult + run_rounds + apply_regional_edit + confirm_understanding
tests/
  test_director_loop_rounds.py     # Task 1
  test_director_regional_edit.py   # Task 2
  test_director_confirm_gate.py    # Task 3
```

不改动：`app.py`、`prompt_engine`、`storage`、既有 `run_one_round` 及其测试。

---

### Task 1: 多轮循环 run_rounds（refine/redraw 分支 + 逐轮译词）

**Files:**
- Modify (APPEND): `backend/orchestrator/director_loop.py`
- Test: `tests/test_director_loop_rounds.py`

- [ ] **Step 1: 写失败测试** `tests/test_director_loop_rounds.py`:
```python
from pathlib import Path
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.brain.base import FaithfulnessVerdict
from backend.orchestrator.director_loop import run_rounds, RoundResult


def test_round1_generates_from_base():
    pass  # placeholder，见下具体断言


def test_three_rounds_refine_then_redraw(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"BASE")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(
        # 第1轮判 refine（改上一版），第2轮判 redraw（回底图），第3轮 refine
        faithfulness_verdicts=[
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="增强清水混凝土质感"),
            FaithfulnessVerdict(tampered=True, action="redraw", fix_instruction_zh="楼层被改回底图重画"),
            FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="微调光线"),
        ],
        # 每次进入下一轮前把中文修正词译成英文（第2、3轮各一次）
        chat_replies=["enhance concrete texture", "redraw from base fixing floors"],
    )

    results = run_rounds(
        brain, engine,
        base_image=base, prompt_en="a modern concrete house",
        out_dir=tmp_path, n_rounds=3,
    )

    # 返回 3 个 RoundResult，迭代号 1..3
    assert [r.iteration for r in results] == [1, 2, 3]
    assert all(isinstance(r, RoundResult) for r in results)
    assert results[0].verdict.action == "refine"
    assert results[1].verdict.action == "redraw"

    # 引擎调用：3 次 generate，产物 round1/2/3.png
    kinds = [c[0] for c in engine.calls]
    assert kinds == ["generate", "generate", "generate"]
    assert [r.render for r in results] == [
        tmp_path / "round1.png", tmp_path / "round2.png", tmp_path / "round3.png"
    ]

    # 第1轮：从底图生成，提示词含原始英文意图
    assert engine.calls[0][2] == [base]
    assert "a modern concrete house" in engine.calls[0][1]

    # 第2轮 refine：输入=上一轮渲染图（round1），提示词含译好的英文修正
    assert engine.calls[1][2] == [tmp_path / "round1.png"]
    assert "enhance concrete texture" in engine.calls[1][1]

    # 第3轮 redraw：输入=底图，提示词含译好的英文修正
    assert engine.calls[2][2] == [base]
    assert "redraw from base fixing floors" in engine.calls[2][1]

    # 忠实度恒以底图为基准比对每轮渲染图
    assert [c[0] for c in brain.faithfulness_calls] == [base, base, base]
    assert [c[2] for c in brain.faithfulness_calls] == [1, 2, 3]


def test_single_round_equivalent_to_generate_from_base(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"B")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(
        faithfulness_verdicts=[FaithfulnessVerdict(tampered=False, action="refine", fix_instruction_zh="ok")]
    )
    results = run_rounds(brain, engine, base_image=base, prompt_en="x", out_dir=tmp_path, n_rounds=1)
    assert len(results) == 1
    assert results[0].iteration == 1
    assert engine.calls[0][2] == [base]
    # 只一轮时不需要译词（brain.chat 未被调用）
    assert brain.chat_calls == []
```

- [ ] **Step 2: 运行确认 FAIL**（ImportError: run_rounds / RoundResult）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_loop_rounds.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** — APPEND 到 `backend/orchestrator/director_loop.py`（既有 import 已含 prompt_engine/ImageEngine/DirectorBrain/FaithfulnessVerdict；补一个 dataclass import）:
```python
from dataclasses import dataclass


@dataclass
class RoundResult:
    iteration: int
    render: Path
    verdict: FaithfulnessVerdict


def _translate_fix(brain: DirectorBrain, fix_zh: str) -> str:
    """把中文修正词译成英文（喂引擎前）。空则返回空串、不调用 brain。"""
    if not fix_zh.strip():
        return ""
    system = prompt_engine.director_system_prompt()
    return brain.chat(system, prompt_engine.translate_instruction_prompt(fix_zh), [])


def run_rounds(
    brain: DirectorBrain,
    engine: ImageEngine,
    *,
    base_image: Path,
    prompt_en: str,
    out_dir: Path,
    n_rounds: int,
    quality: str = "标准",
    ratio: str = "跟随原图",
) -> list[RoundResult]:
    """有界多轮导演循环。

    第1轮：从底图按原始英文意图生成。
    第 k(≥2) 轮：按上一轮 verdict 应用修正——refine 改上一版（输入上轮渲染图）、
    redraw 从底图重画（输入底图）；两者提示词都用译好的英文修正词。
    每轮都以底图为基准做忠实度比对。返回各轮 RoundResult。
    """
    results: list[RoundResult] = []
    prev_render: Path | None = None
    prev_verdict: FaithfulnessVerdict | None = None

    for i in range(1, n_rounds + 1):
        out_path = out_dir / f"round{i}.png"
        if i == 1:
            message = prompt_engine.generation_message(prompt_en, quality=quality, ratio=ratio)
            render = engine.generate(message, [base_image], out_path=out_path)
        else:
            fix_en = _translate_fix(brain, prev_verdict.fix_instruction_zh)
            message = prompt_engine.refine_message(fix_en, quality=quality)
            source = prev_render if prev_verdict.action == "refine" else base_image
            render = engine.generate(message, [source], out_path=out_path)

        verdict = brain.check_faithfulness(base_image, render, i)
        results.append(RoundResult(iteration=i, render=render, verdict=verdict))
        prev_render, prev_verdict = render, verdict

    return results
```

- [ ] **Step 4: 运行确认 PASS**（去掉占位 `test_round1_generates_from_base` 或让其 pass；3 tests）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_loop_rounds.py -v`
Expected: PASS

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 64 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/orchestrator/director_loop.py tests/test_director_loop_rounds.py
git commit -m "feat: run_rounds multi-round director loop (refine/redraw + zh->en fix)"
```

---

### Task 2: 区域编辑 apply_regional_edit（mask → engine.edit）

用户圈选区域 + 中文指令 → 译成英文 → `engine.edit(prev_image, mask, regional_edit_message(en))`。

**Files:**
- Modify (APPEND): `backend/orchestrator/director_loop.py`
- Test: `tests/test_director_regional_edit.py`

- [ ] **Step 1: 写失败测试** `tests/test_director_regional_edit.py`:
```python
from pathlib import Path
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.orchestrator.director_loop import apply_regional_edit


def test_regional_edit_translates_and_calls_engine_edit(tmp_path):
    prev = tmp_path / "round3.png"; prev.write_bytes(b"PREV")
    mask = tmp_path / "mask.png"; mask.write_bytes(b"MASK")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(chat_replies=["change window to wood frame"])

    out = apply_regional_edit(
        brain, engine,
        prev_image=prev, mask=mask, instruction_zh="把窗户改成木框",
        out_path=tmp_path / "edit1.png",
    )

    assert out == tmp_path / "edit1.png" and out.exists()
    # 调 engine.edit，带 prev + mask，提示词含译好的英文
    kind, prompt_text, images, out_path = engine.calls[0]
    assert kind == "edit"
    assert images == [prev, mask]
    assert "change window to wood frame" in prompt_text


def test_regional_edit_without_mask_passes_none(tmp_path):
    prev = tmp_path / "r.png"; prev.write_bytes(b"P")
    engine = FakeImageEngine()
    brain = FakeDirectorBrain(chat_replies=["brighten"])
    apply_regional_edit(
        brain, engine, prev_image=prev, mask=None,
        instruction_zh="调亮", out_path=tmp_path / "e.png",
    )
    kind, _, images, _ = engine.calls[0]
    assert kind == "edit"
    assert images == [prev]   # 无 mask 时 FakeImageEngine 只记 prev
```

- [ ] **Step 2: 运行确认 FAIL**（ImportError: apply_regional_edit）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_regional_edit.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** — APPEND 到 `backend/orchestrator/director_loop.py`:
```python
def apply_regional_edit(
    brain: DirectorBrain,
    engine: ImageEngine,
    *,
    prev_image: Path,
    mask: Path | None,
    instruction_zh: str,
    out_path: Path,
) -> Path:
    """区域编辑：中文指令译英文 → engine.edit(prev, mask, 英文区域编辑提示词)。"""
    instruction_en = _translate_fix(brain, instruction_zh)
    message = prompt_engine.regional_edit_message(instruction_en)
    return engine.edit(prev_image, mask, message, out_path=out_path)
```

- [ ] **Step 4: 运行确认 PASS**（2 tests）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_regional_edit.py -v`
Expected: PASS

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 66 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/orchestrator/director_loop.py tests/test_director_regional_edit.py
git commit -m "feat: apply_regional_edit (mask -> engine.edit with translated instruction)"
```

---

### Task 3: 确认闸门 confirm_understanding（understand → 可编辑英文词）

出图前先让导演脑"复述理解"（读底图 + 中文意图 → 一段可给用户确认/编辑的英文提示词）。用户确认/改完的英文词，才喂进 `run_rounds` 的 `prompt_en`。

**Files:**
- Modify (APPEND): `backend/orchestrator/director_loop.py`
- Test: `tests/test_director_confirm_gate.py`

- [ ] **Step 1: 写失败测试** `tests/test_director_confirm_gate.py`:
```python
from pathlib import Path
from backend.engines.fake import FakeImageEngine
from backend.brain.fake import FakeDirectorBrain
from backend.orchestrator.director_loop import confirm_understanding


def test_confirm_understanding_reads_base_and_returns_english(tmp_path):
    base = tmp_path / "base.png"; base.write_bytes(b"BASE")
    brain = FakeDirectorBrain(chat_replies=["A modern concrete house at dusk, photorealistic."])

    prompt_en = confirm_understanding(brain, base_image=base, intent_zh="现代清水混凝土住宅，黄昏")

    assert prompt_en == "A modern concrete house at dusk, photorealistic."
    # 把底图交给导演脑读（chat 收到底图）
    system, message, images = brain.chat_calls[0]
    assert images == [base]
    assert "现代清水混凝土" in message  # 中文意图进了消息
```

- [ ] **Step 2: 运行确认 FAIL**（ImportError: confirm_understanding）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_confirm_gate.py -v`
Expected: FAIL

- [ ] **Step 3: 实现** — APPEND 到 `backend/orchestrator/director_loop.py`:
```python
def confirm_understanding(
    brain: DirectorBrain,
    *,
    base_image: Path,
    intent_zh: str,
) -> str:
    """确认闸门：导演脑读底图 + 中文意图，产出一段可编辑的英文提示词供用户确认。"""
    system = prompt_engine.director_system_prompt()
    message = prompt_engine.helper_understand_prompt(intent_zh)
    return brain.chat(system, message, [base_image])
```

> 注：`helper_understand_prompt(intent: str = "")` 已在 prompt_engine 中；它造"复述理解"提示词。若其文案未含原始中文意图，测试里 `"现代清水混凝土" in message` 会失败——那时改用 `prompt_engine.adjust_prompt`/直接拼接，或在 helper 里带上 intent。实现时以实际函数产出的字符串为准，必要时在本函数内把 `intent_zh` 追加进 message 以保证可测。

- [ ] **Step 4: 运行确认 PASS**（1 test）

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_director_confirm_gate.py -v`
Expected: PASS

- [ ] **Step 5: 全量 + 提交**

Run: `cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 67 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/orchestrator/director_loop.py tests/test_director_confirm_gate.py
git commit -m "feat: confirm_understanding gate (base + zh intent -> editable EN prompt)"
```

---

## P1d 完成判据

- `uv run python -m pytest -v` → **67 passed + 3 skipped**。
- `run_rounds` 多轮：第1轮从底图生成；refine 改上一版、redraw 回底图；逐轮把中文修正词经 `brain.chat` 译英文再喂引擎；每轮以底图为基准比对。
- `apply_regional_edit`：中文指令译英文 → `engine.edit(prev, mask, 区域编辑提示词)`；无 mask 传 None。
- `confirm_understanding`：导演脑读底图 + 中文意图 → 返回可编辑英文提示词。
- 既有 `run_one_round` 及其测试未改动。

## 交给后续子计划的接口

- `run_rounds(...) -> list[RoundResult]` —— P1e 每 N 轮暂停 = 取 `n_rounds=N` 分批调用 + 用 `SessionManager.record_round`/`add_usage` 落盘；P1f 路由暴露"开始/继续"。
- `apply_regional_edit(...)` / `confirm_understanding(...)` —— P1f 的"确认闸门"与"区域涂改"端点直接调。
- 成本：P1e 在每轮后用 `estimate_cost` 累计（出图张数 = 轮数；导演 token 来自真 caller 的 usage）。
```
