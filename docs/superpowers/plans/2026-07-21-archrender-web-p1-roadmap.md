# ArchRender Web — P1 路线图（子计划分解）

> P1 太大、横跨多个独立子系统，按 writing-plans 纪律拆成有序子计划。每份子计划自身产出可运行、可测试的软件，各有独立的 设计→计划→实现 循环。本文件只做分解与排序；每份子计划另起一份完整 TDD 计划文档。

**前置**：P0 已完成（`/mnt/c/Users/Andy/archrender-web`，11 测试绿）。已有接口契约：
- `ImageEngine.generate(prompt_text, input_images, *, out_path) -> Path` / `.edit(prev_image, mask, prompt_text, *, out_path) -> Path`
- `DirectorBrain.chat(system, message, images) -> str` / `.check_faithfulness(base, render, iteration) -> FaithfulnessVerdict`
- `orchestrator.director_loop.run_one_round(...) -> (Path, FaithfulnessVerdict)`

---

## 子计划分解（按依赖/建设顺序）

| 子计划 | 交付 | 依赖 | 产出可测软件 |
|---|---|---|---|
| **P1a · 真·出图引擎** | `GeminiEngine` + `OpenAIEngine` 实现 `ImageEngine`（可注入 client，mock 传输层做单测；真 API 冒烟测默认 skip） | P0 | ✅ 两个引擎通过接口一致性测试 |
| **P1b · 真·导演脑** | `ClaudeBrain` 实现 `DirectorBrain`（Claude 视觉 API，可注入 client；understand/写词/忠实度比对；prompt caching 挂载点） | P0 | ✅ ClaudeBrain 通过接口测试（mock API） |
| **P1c · 会话与存储 + 成本日志** | `Session`/`Job` 数据模型、DB（起步 SQLite）、对象存储（起步本地目录）、**逐 Job 用量/成本记录**（图张数+token→美元） | P0 | ✅ 存取会话/图片/成本可测 |
| **P1d · 完整导演循环** | 把 `run_one_round` 扩成多轮：出图→忠实度→refine/redraw 分支→每 N 张暂停；区域编辑（mask→`engine.edit`）；确认闸门（understand→可编辑英文词） | P1a,P1b,P1c | ✅ 多轮循环用真引擎/假引擎均可测 |
| **P1e · 异步任务层** | 队列 + worker 池（按 provider 并发匀速取活）+ SSE 进度推送 + 429 退避重试 + 每用户并发上限（公平）+ 每日硬上限（成本护栏） | P1c,P1d | ✅ 并发/限流/排队行为可测 |
| **P1f · FastAPI 接口层** | REST 路由（建会话/上传/确认/开始/暂停操作/下载）+ SSE 端点；API key 走服务端环境变量 | P1c,P1d,P1e | ✅ 路由集成测试 |
| **P1g · 全新前端 SPA** | 上传/确认闸门/进度/**区域涂改 canvas**/画廊下载；页内引擎切换（Gemini/OpenAI）；中英切换 | P1f | ✅ 前端端到端（webapp-testing） |

**关键路径**：P1a+P1b（并行）→ P1c → P1d → P1e → P1f → P1g。
P1a 与 P1b 无相互依赖，可并行推进；两者都只是"实现 P0 已定的接口"，风险最低，故排最前。

---

## 每份子计划的通用约束

- **不烧真 API 做单测**：所有引擎/导演脑通过**依赖注入**接受一个 client，单测注入假 client 返回已知字节/文本；真 API 调用另置一个**默认 skip、需环境变量 key 才跑**的冒烟测。
- **provider API 具体形状**（端点/参数/返回）在实现时用 context7 查实时官方文档核对，不凭记忆写死。
- **成本护栏贯穿**：P1c 起就逐 Job 记成本；P1e 加每日硬上限 + 每用户并发上限。
- **老 `app.py` 永不改动**；`prompt_engine` 只读复用。
- 每子计划自带 TDD 任务（先失败测试→最小实现→通过→提交）。

---

## 交付节奏建议

先做 **P1a**（本路线图配套已写出完整 TDD 计划：`2026-07-21-archrender-web-p1a-image-engines.md`）。P1a 跑通后，再依次为 P1b…P1g 各写一份完整计划并执行。这样每一步都有可运行成果、进度可随时落盘、token 中断可无缝续接。
