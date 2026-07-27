# ArchRender Web — P1b 真导演脑 ClaudeBrain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 在 P0 已定的 `DirectorBrain` 接口后面接上真导演脑 `ClaudeBrain`（Claude 视觉 API：读图/写词/忠实度比对）。同 P1a 模式：注入式 `caller` → 单测 mock、零 API 花销；真 API 只由默认 skip、需 `ANTHROPIC_API_KEY` 才跑的冒烟测覆盖。

**Architecture:** `ClaudeBrain(caller=None, model="claude-sonnet-5")` 实现 `DirectorBrain`。`caller` 满足一个 `ClaudeCaller` 契约（`call(system, message, images_bytes) -> str`），把"多模态一次问答"这件事隔离出去；`_RealClaudeCaller` 用 anthropic SDK 实现（惰性、import 不需 key）。`check_faithfulness` 复用 `prompt_engine` 造 QC 提示词、追加一行严格输出指令，再用独立可测的 `_parse_verdict` 解析成 `FaithfulnessVerdict`。

**成本取向（已批准的设计决策）**：导演脑默认用便宜档 `claude-sonnet-5`（视觉强、比 Opus 便宜），构造参数可改。prompt caching 挂载点留在 `_RealClaudeCaller`（固定 system + ArchiPrompt 大库走缓存），P1b 先不强制启用、留 TODO 注释即可。

**Tech Stack:** Python 3.10+，pytest，anthropic SDK。**Claude messages/视觉 API 形状实现时用 claude-api skill 或 context7 核对，不凭记忆写死。**

**运行测试**：`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（裸 `python -m pytest` 会失败；若见 "No tests collected" 用 `uv run --with pytest python -m pytest -v`）。

---

## 文件结构（P1b）

```
backend/brain/
  base.py            # 既有 DirectorBrain ABC + FaithfulnessVerdict + DirectorBrainError（本计划末尾追加 ClaudeCaller Protocol）
  claude.py          # 新增：ClaudeBrain + _parse_verdict + _RealClaudeCaller
  fake_caller.py     # 新增：FakeCaller（测试用注入件，区别于既有 fake.py 的 FakeDirectorBrain）
tests/
  test_claude_brain.py
  test_claude_verdict_parse.py
  test_real_clients_smoke.py   # 追加 Claude 冒烟测（默认 skip）
```

---

### Task 1: ClaudeCaller 协议 + ClaudeBrain.chat + FakeCaller

先把"多模态一次问答"隔离成注入件，实现 `chat`（读图→字节→caller→文本）。忠实度解析留到 Task 2。

**Files:**
- Modify (APPEND ONLY): `backend/brain/base.py`
- Create: `backend/brain/claude.py`
- Create: `backend/brain/fake_caller.py`
- Test: `tests/test_claude_brain.py`

- [ ] **Step 1: 写失败测试** `tests/test_claude_brain.py`:
```python
from pathlib import Path
from backend.brain.claude import ClaudeBrain
from backend.brain.base import DirectorBrain
from backend.brain.fake_caller import FakeCaller


def _img(p: Path, data: bytes = b"IMG") -> Path:
    p.write_bytes(data)
    return p


def test_claude_brain_is_directorbrain():
    assert issubclass(ClaudeBrain, DirectorBrain)


def test_chat_reads_images_and_delegates_to_caller(tmp_path):
    caller = FakeCaller(replies=["understood: a house"])
    brain = ClaudeBrain(caller=caller, model="claude-sonnet-5")
    a = _img(tmp_path / "a.png", b"AAA")

    reply = brain.chat("sys", "describe", [a])

    assert reply == "understood: a house"
    # caller 收到 (system, message, [图片字节])
    assert caller.calls == [("sys", "describe", [b"AAA"])]
    assert brain.model == "claude-sonnet-5"


def test_chat_default_model_is_configurable():
    brain = ClaudeBrain(caller=FakeCaller())
    assert brain.model == "claude-sonnet-5"
```

- [ ] **Step 2: 运行确认 FAIL**（ModuleNotFoundError: backend.brain.claude）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_claude_brain.py -v`

- [ ] **Step 3: 实现**

APPEND 到 `backend/brain/base.py` 末尾（不改已有内容）:
```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClaudeCaller(Protocol):
    """导演脑的多模态一次问答契约：给定 system + message + 图片字节，返回文本。"""

    def call(self, system: str, message: str, images: list[bytes]) -> str: ...
```

`backend/brain/fake_caller.py`:
```python
class FakeCaller:
    """测试用注入件：按脚本返回文本并记录调用，不触任何 API。"""

    def __init__(self, replies=None):
        self._replies = list(replies or [])
        self.calls: list[tuple] = []

    def call(self, system: str, message: str, images: list[bytes]) -> str:
        self.calls.append((system, message, list(images)))
        if self._replies:
            return self._replies.pop(0)
        return ""
```

`backend/brain/claude.py`（本任务只写到 chat；check_faithfulness 与 _parse_verdict / _RealClaudeCaller 由 Task 2/3 补）:
```python
from pathlib import Path
from backend.brain.base import DirectorBrain, FaithfulnessVerdict, ClaudeCaller


class ClaudeBrain(DirectorBrain):
    """真导演脑：Claude 视觉 API。多模态问答隔离到可注入的 caller。"""

    name = "claude"

    def __init__(self, caller: ClaudeCaller | None = None, model: str = "claude-sonnet-5"):
        self.model = model
        self._caller = caller if caller is not None else _RealClaudeCaller(model)

    def chat(self, system: str, message: str, images: list[Path]) -> str:
        image_bytes = [p.read_bytes() for p in images]
        return self._caller.call(system, message, image_bytes)

    def check_faithfulness(self, base: Path, render: Path, iteration: int) -> FaithfulnessVerdict:
        raise NotImplementedError  # Task 2 实现


class _RealClaudeCaller:
    """占位：Task 3 用 anthropic SDK 实现。"""

    def __init__(self, model: str):
        self._model = model

    def call(self, system: str, message: str, images: list[bytes]) -> str:
        raise NotImplementedError  # Task 3 实现
```

- [ ] **Step 4: 运行确认 PASS**（3 passed）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_claude_brain.py -v`

- [ ] **Step 5: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 26 passed + 2 skipped：P1a 的 23+2 + 本任务 3）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/brain/base.py backend/brain/claude.py backend/brain/fake_caller.py tests/test_claude_brain.py
git commit -m "feat: ClaudeBrain.chat via injectable ClaudeCaller + FakeCaller"
```

---

### Task 2: 忠实度判定解析 _parse_verdict + check_faithfulness

`check_faithfulness` 复用 `prompt_engine.qc_and_revise_prompt(iteration)` 造 QC 指令，追加一行严格机器可读输出要求，把 base+render 两张图交给 caller，再用独立可测的 `_parse_verdict` 解析成 `FaithfulnessVerdict`。

**Files:**
- Modify: `backend/brain/claude.py`（实现 check_faithfulness + 新增模块级 `_parse_verdict`）
- Test: `tests/test_claude_verdict_parse.py`
- Test: `tests/test_claude_brain.py`（追加 check_faithfulness 的委托测试）

- [ ] **Step 1: 写失败测试** `tests/test_claude_verdict_parse.py`:
```python
from backend.brain.claude import _parse_verdict, _VERDICT_INSTRUCTION
from backend.brain.base import FaithfulnessVerdict


def test_parse_refine_clean():
    text = "分析：材质需要更真实。\nTAMPERED: no\nACTION: refine\nFIX: 增强清水混凝土质感"
    v = _parse_verdict(text)
    assert isinstance(v, FaithfulnessVerdict)
    assert v.tampered is False
    assert v.action == "refine"
    assert "清水混凝土" in v.fix_instruction_zh


def test_parse_redraw_tampered():
    text = "楼层数被改。\nTAMPERED: yes\nACTION: redraw\nFIX: 楼层从6层被改成8层，从底图重画"
    v = _parse_verdict(text)
    assert v.tampered is True
    assert v.action == "redraw"
    assert "重画" in v.fix_instruction_zh


def test_parse_defaults_to_refine_when_action_missing():
    # 没有明确 ACTION 时保守取 refine、不判篡改（避免误重画）
    v = _parse_verdict("看起来不错，没什么问题。")
    assert v.action == "refine"
    assert v.tampered is False


def test_verdict_instruction_is_nonempty_str():
    assert isinstance(_VERDICT_INSTRUCTION, str) and len(_VERDICT_INSTRUCTION) > 0
```

追加到 `tests/test_claude_brain.py`:
```python
def test_check_faithfulness_sends_two_images_and_parses(tmp_path):
    caller = FakeCaller(replies=["TAMPERED: yes\nACTION: redraw\nFIX: 从底图重画"])
    brain = ClaudeBrain(caller=caller)
    base = _img(tmp_path / "base.png", b"BASE")
    render = _img(tmp_path / "r.png", b"RENDER")

    verdict = brain.check_faithfulness(base, render, iteration=2)

    assert verdict.action == "redraw"
    assert verdict.tampered is True
    # caller 收到两张图（底图在前、渲染图在后）
    assert caller.calls[0][2] == [b"BASE", b"RENDER"]
```

- [ ] **Step 2: 运行确认 FAIL**（ImportError: _parse_verdict / NotImplementedError）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_claude_verdict_parse.py tests/test_claude_brain.py -v`

- [ ] **Step 3: 实现** — 在 `backend/brain/claude.py`：

顶部补 import：`from backend.core import prompt_engine`

新增模块级常量与解析器（放在 ClaudeBrain 类之前）:
```python
import re

_VERDICT_INSTRUCTION = (
    "\n\n【严格输出格式，最后三行必须是】\n"
    "TAMPERED: yes 或 no（是否篡改了建筑几何/楼层/开窗/文字/直线）\n"
    "ACTION: refine 或 redraw（refine=在上一版上增量修；redraw=从底图重画）\n"
    "FIX: 一句中文修正指令"
)


def _parse_verdict(text: str) -> "FaithfulnessVerdict":
    def grab(tag: str) -> str:
        m = re.search(rf"{tag}\s*:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    action = grab("ACTION").lower()
    action = "redraw" if action.startswith("redraw") else "refine"  # 缺省保守取 refine
    tampered = grab("TAMPERED").lower().startswith(("y", "是", "true"))
    return FaithfulnessVerdict(tampered=tampered, action=action, fix_instruction_zh=grab("FIX"))
```

实现 `ClaudeBrain.check_faithfulness`（替换 Task1 的 NotImplementedError）:
```python
    def check_faithfulness(self, base: Path, render: Path, iteration: int) -> FaithfulnessVerdict:
        system = prompt_engine.director_system_prompt()
        message = prompt_engine.qc_and_revise_prompt(iteration) + _VERDICT_INSTRUCTION
        text = self._caller.call(system, message, [base.read_bytes(), render.read_bytes()])
        return _parse_verdict(text)
```

- [ ] **Step 4: 运行确认 PASS**（parse 4 + brain 追加 1 = 之前 3 变 4）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_claude_verdict_parse.py tests/test_claude_brain.py -v`

- [ ] **Step 5: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 31 passed + 2 skipped：上一步 26 + 本任务新增 parse 4 + brain 1）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/brain/claude.py tests/test_claude_verdict_parse.py tests/test_claude_brain.py
git commit -m "feat: ClaudeBrain.check_faithfulness + _parse_verdict"
```

---

### Task 3: _RealClaudeCaller（anthropic SDK 视觉，惰性，冒烟测默认 skip）

用真 anthropic SDK 实现 `_RealClaudeCaller.call`。**实现前用 claude-api skill（或 context7）核对 messages + 视觉图片块 + 取回文本的当前形状。**

**Files:**
- Modify: `backend/brain/claude.py`（实现 `_RealClaudeCaller`）
- Test: `tests/test_real_clients_smoke.py`（追加 Claude 冒烟测）

- [ ] **Step 1: 写单测（注入假底层 SDK，验证组装逻辑）** 追加到 `tests/test_claude_brain.py`:
```python
def test_real_caller_builds_image_blocks_and_returns_text(monkeypatch):
    import backend.brain.claude as mod

    captured = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            class _Block: 
                type = "text"; text = "OK-REPLY"
            class _Resp:
                content = [_Block()]
            return _Resp()

    class _FakeAnthropic:
        def __init__(self, **kw): self.messages = _FakeMessages()

    # 注入假 SDK 工厂，避免真 key/网络
    caller = mod._RealClaudeCaller("claude-sonnet-5", client_factory=lambda: _FakeAnthropic())
    out = caller.call("SYS", "MSG", [b"\x89PNG-bytes"])

    assert out == "OK-REPLY"
    assert captured["model"] == "claude-sonnet-5"
    assert captured["system"] == "SYS"
    # 用户消息里应含文本 + 至少一个 image 块
    user_content = captured["messages"][0]["content"]
    types = [b.get("type") for b in user_content]
    assert "text" in types and "image" in types
```

- [ ] **Step 2: 运行确认 FAIL**（NotImplementedError / TypeError: client_factory）
- [ ] **Step 3: 实现** `_RealClaudeCaller`（替换 Task1 占位）:
  - `__init__(self, model, client_factory=None)`: 存 model + client_factory（默认惰性建真 `anthropic.Anthropic()`；import 本模块不需 key）。
  - `call(system, message, images)`: 把每张图片字节 base64 编码成 image 块 `{"type":"image","source":{"type":"base64","media_type":"image/png","data": <b64>}}`，与 `{"type":"text","text": message}` 组成 user content；调 `client.messages.create(model=self._model, max_tokens=..., system=system, messages=[{"role":"user","content": content}], thinking={"type":"adaptive"})`；从 `response.content` 里拼接 `type=="text"` 的块文本返回。**具体参数（max_tokens、thinking、模型能力）以 claude-api skill 为准。** 惰性建 client：首次 call 时若无 `ANTHROPIC_API_KEY` 且无注入 factory，则 `anthropic.Anthropic()` 让 SDK 自行解析凭据（不要在 import 或 __init__ 报错）。
  - 依赖：`uv add anthropic`。
- [ ] **Step 4: 运行确认 PASS**（1 passed）
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest tests/test_claude_brain.py -v`
- [ ] **Step 5: 冒烟测（默认 skip）** 追加到 `tests/test_real_clients_smoke.py`:
```python
from backend.brain.claude import ClaudeBrain


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="需要 ANTHROPIC_API_KEY 才跑真 API")
def test_claude_real_faithfulness(tmp_path):
    brain = ClaudeBrain()
    base = tmp_path / "base.png"; base.write_bytes(_FIXTURE.read_bytes())
    render = tmp_path / "render.png"; render.write_bytes(_FIXTURE.read_bytes())
    verdict = brain.check_faithfulness(base, render, iteration=1)
    assert verdict.action in ("refine", "redraw")
```
- [ ] **Step 6: 全量 + 提交**
`cd /mnt/c/Users/Andy/archrender-web && uv run python -m pytest -v`（预期 32 passed + 3 skipped）
```bash
cd /mnt/c/Users/Andy/archrender-web
git add backend/brain/claude.py tests/test_claude_brain.py tests/test_real_clients_smoke.py pyproject.toml uv.lock
git commit -m "feat: _RealClaudeCaller (anthropic vision, lazy) + skip-by-default smoke test"
```

---

## P1b 完成判据

- `uv run python -m pytest -v` → 32 passed + 3 skipped（三个真 API 冒烟测无 key 时 skip）。
- `ClaudeBrain` 是 `DirectorBrain` 子类；`chat` 委托 caller；`check_faithfulness` 送双图并正确解析 refine/redraw/tampered。
- `_RealClaudeCaller` 的图片块/文本组装经注入假 SDK 验证；真形状用 claude-api skill 核对；import/构造不需 key。
- 默认模型 `claude-sonnet-5`（可配置，成本取向）；prompt caching 留 TODO 挂载点。
- 老 `app.py` 未改动。

## 交给后续子计划的接口

- `ClaudeBrain(caller=None, model="claude-sonnet-5")` 实现 `DirectorBrain`。
- `ClaudeCaller` 协议（`call(system, message, images) -> str`）——P3 浏览器版导演也可自实现。
- 与 P1a 的 `get_image_engine` 一起，P1d 的完整导演循环即可用真引擎+真导演脑装配。
