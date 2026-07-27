# ArchRender 云端网站（P0+P1）设计文档

- 日期：2026-07-21
- 状态：已通过头脑风暴、用户已认可整体设计，待用户复审本文档
- 范围：P0（核心抽取）+ P1（新公网页面 + 云端出图）。P2/P3 仅描述边界，不在本次实现内。

---

## 1. 背景与目标

现有 `ArchRenderAgent`（`app.py` 单体 Flask）是一个**本地、自带 ChatGPT/Gemini 订阅**的工具：在用户本机接管已登录的 Chrome（CDP 调试端口 9333），用用户自己的会员额度出建筑渲染图。它无法做成公开网址（127.0.0.1 只本机有效 + 单会话 + 自带账号）。

**本次目标**：做一个**全新的公开网站**，访客打开网址即可出图，**无需本地部署**。后端用平台 API key 出图（按量付费，不再受订阅"次数用完"限制）。同时**保留**"用户用自己的会员、驱动浏览器出图"这条路（延后到 P3，以本地连接器形态回归）。

### 决策记录（用户拍板）

- 面向对象：**公开给别人用**（不只是自己）。
- 计费模式：**接受改用 API key**（推翻原"只用订阅"的约束，本项目专属例外）。
- 两条路共存形态：**一个网站、页内切换引擎**；且是**一个全新的页面**。
- 第一片先做：**P0 + P1**（先把网址做出来能出图），账号/计费延后。
- 云端出图引擎：**Gemini 图像 API（nano-banana / gemini-2.5-flash-image）+ OpenAI（gpt-image-2）两个都接**，页内选。
- 导演脑（读图/写词/查篡改）：**Claude 视觉 API**（与出图引擎解耦）。
- 首版厚度：**尽量完整搬过来**（确认闸门 + 自动多轮迭代 + 忠实度比对 + 区域涂改编辑器）。
- 后端架构：**方案 B——全新云后端，只搬核心；老 `app.py` 原封不动，留给 P3。**
- 后端框架：**FastAPI**（新建，不复用 Flask）。
- P1 成本护栏：**每 Session 轮数上限 + 全站每日调用硬上限**，先不做账号。

### 产品模式（两种并存，用户按"有无自带会员"页内切换）

两种模式平起平坐，同一网站页内切换，共用同一套导演脑与 UI（靠 `ImageEngine` 可插拔接口区分）：

- **模式 A · 自带会员·浏览器模式**：用户**有**自己的 ChatGPT/Gemini 订阅套餐 → 用他自己的会员**驱动本机浏览器**出图。**零 API 花销**（烧用户自己的订阅），保留老本地版灵魂。→ 由 `BrowserEngine` 实现，**建设排在 P3**（技术最硬：公网页面需打通 https↔localhost 驱动本机 Chrome）。
- **模式 B · 套餐模式（调 API）**：用户**没有**自己的会员账号 → 买**平台套餐/会员**，后端**调用 API**（Gemini/OpenAI 出图 + Claude 导演）替他出图；平台付 API 成本，按次向用户收费赚差价。→ 由 `GeminiEngine`/`OpenAIEngine` 实现（**P1**）+ 会员计费（**P2**）。

> 说明：浏览器模式（A）排在 P3 只是**建设顺序**问题，产品定位上它与套餐模式（B）同等重要，不是边角功能。

---

## 2. 架构总览

```
   浏览器(访客) ──▶ 新前端 SPA（上传/确认闸门/进度/区域涂改/看图下载）
                     │  JSON API + SSE(进度推送)
                     ▼
   新云后端 (Python / FastAPI)
     ├─ 会话/任务层        存 DB + 对象存储
     ├─ 编排层(导演循环)    复用 prompt_engine + ArchiPrompt 库
     ├─ DirectorBrain(接口) = ClaudeBrain（视觉：读图/写词/忠实度比对）
     └─ ImageEngine(接口)   = GeminiEngine | OpenAIEngine（P3 再加 BrowserEngine）

   老 app.py（浏览器版）── 原封不动，留给 P3「自带会员」
```

两个可插拔接口是脊梁：

- **`ImageEngine`**：`generate(base_img, prompt, refs) -> img`、`edit(prev_img, mask, prompt) -> img`。
  实现：`GeminiEngine`、`OpenAIEngine`；P3 追加 `BrowserEngine`（第三实现，接口不变）。
- **`DirectorBrain`**：`understand(brief, images) -> 中文复述+英文提示词`、`check_faithfulness(base, render) -> 篡改判定/修正指令`。
  实现：`ClaudeBrain`（Claude 视觉 API）。

**为什么方案 B**：现有 `app.py`（124KB）是单用户、内存单会话，公网多人会串号；从头用会话存储 + 异步任务模型最省后患，且老程序保持可用、正好当 P3 的浏览器版底座。皇冠资产 `prompt_engine.py` + ArchiPrompt 提示词库 100% 复用。

---

## 3. 关键新增：有状态会话 + 异步任务

本地版没有、云端必须补的部分，也是"完整搬过来"最大的工作量。

- **Session（会话）**：一次出图项目。存底图、参考图、确认后的英文提示词、每轮历史、当前渲染图。落 **DB（记录/状态）+ 对象存储（图片）**，不再是内存对象。
- **Job（任务）**：出图 1–3 分钟，必须**异步**。前端提交 → 后端入队 → 后台 worker 跑导演循环 → **SSE 实时推进度**（第几轮 / 在比对 / 出图中 / 暂停待审）。刷新或换设备可续。
- **并发 / 限流 / 公平（多人同时用不摆烂）**：绝不同步直调 API（会 429 风暴）。**worker 池按 provider 允许的并发匀速取活**；满载时新任务**排队**，SSE 显示排位/预计等待，而非失败；**429 自动指数退避重试**，不丢任务；设**每用户并发上限**做公平调度，防一个用户占满全部产能。产能不足时的扩展杠杆：向 provider 升配额/高档 tier、**多 key 轮询池**、**双 provider（Gemini+OpenAI）合并产能择优路由**、横向加 worker、**付费会员优先队列（P2）**。"按时"= 诚实展示排位 + 真实 ETA + 进度推送，而非同步阻塞。
- **导演脑记忆改为显式重建**：每轮调用 Claude API 时把该 Session 历史（底图+上一版+反馈）作为消息重新拼入，配 **prompt caching** 缓存固定的 ArchiPrompt 大库——既省钱又无状态、天然可水平扩展。

---

## 4. 数据流（一次完整出图）

1. 上传底图 + 参考图 → 存对象存储，建 Session。
2. **确认闸门**：`ClaudeBrain.understand()` → 中文复述 + 可编辑英文提示词（复用 `prompt_engine` 的 ArchiPrompt 框架 + 库）。用户改词 → 重新 sync。**此步不出图、不花出图钱。**
3. 用户点开始 → 建 Job → 后台 worker：
   `ImageEngine.generate()` 出图 → `ClaudeBrain.check_faithfulness(底图, 渲染)` 抓篡改 →
   决定**增量修上一版** vs **从底图重画** → 每 N 张暂停，SSE 通知前端。
4. 暂停时用户可：给反馈继续 / 一键粘贴 AI 自评 / **区域涂改**（前端 canvas 出 mask → `ImageEngine.edit(上一版, mask, 词)`）/ 完成下载 / 停止。
5. 每轮图与词落对象存储，可回看。

---

## 5. 出错处理

- **图像 API 失败/超时/限流**：Job 层重试 + 指数退避；连续失败 → SSE 报"这轮失败可重试"，不崩整个 Session（对应老版"一次卡顿不该毁全程"）。
- **导演脑拒答/异常**：降级为"跳过本轮忠实度检查、继续出图"并标注，不阻断。
- **成本护栏（P1 即上）**：每 Session **轮数上限** + 全站**每日调用硬上限**，兜住"未做计费前别人猛点烧钱"。

---

## 6. 成本控制与盈利地基

- **成本大头是"图像生成 × 轮数"**，导演脑是次要成本。
- 导演脑用**便宜档 Claude（Sonnet/Haiku）** + **prompt caching**（固定 ArchiPrompt 库缓存，重复调用几乎不再计费）压低单次成本。
- **用量/成本日志（P1 前置钩子）**：会话层逐 Job 记录 **图像 API 张数 + 导演脑 token → 折算美元**。这是 P2 会员按次定价（成本 + 利润，保证盈利）的地基，必须在 P1 就埋好。

---

## 7. 目录结构（新后端，不碰老 app.py）

```
archrender-web/
  backend/
    engines/        image_gemini.py  image_openai.py  base.py
    brain/          claude.py  base.py
    core/           prompt_engine.py(搬)  library/(搬 ArchiPrompt 库)
    orchestrator/   director_loop.py  faithfulness.py
    sessions/       models.py  store.py(DB+对象存储)  usage.py(成本日志)
    jobs/           queue.py  worker.py  sse.py
    api/            routes.py  app.py(FastAPI 入口)
  frontend/         新 SPA(上传/确认/进度/区域编辑/画廊)
  tests/
```

---

## 8. 部署与测试

- **部署**：后端容器（支持长请求 + 后台 worker，如 Render/Railway/Fly 或一台 VPS）；前端静态托管；对象存储放图。API key（Gemini/OpenAI/Anthropic）走服务端环境变量，**永不进前端**。
- **网络拓扑 / 免翻墙（对国内用户是核心优势）**：模式 B（调 API）里，够 OpenAI/Gemini/Anthropic 的是**服务器**、不是用户电脑，所以**用户端不需要翻墙**——这正是套餐模式相对模式 A（浏览器·用户需自己翻墙）和现有本地版的最大差异点。代价是"翻墙负担转移到服务器"：服务器必须能出海够到三个 provider。终局部署拆成两段——**入口**（前端 + API 网关，国内可访问，可能需 ICP 备案）+ **出海调用**（能够到 provider 的后端 worker）；用户全程只访问一个国内顺畅的入口，翻墙的脏活在后端消化。起步阶段可先纯海外托管（用户不用翻 AI，但访问海外域名体验看线路），再演进到"国内入口 + 海外出口"。
- **测试**：`ImageEngine`/`DirectorBrain` 用假实现做单测（不烧真 API）；编排循环用录制的假响应测"增量 vs 重画"分支；一条真 API 冒烟测。

---

## 9. 明确不做（留给后续阶段）

- **P2**：账号登录 + **会员制**（按次计价，成本 + 利润，保证盈利）+ 免费额度。放公网给公众前的必需闸门。
- **P3**：公网页面驱动**本机浏览器**出图（`BrowserEngine`，最硬骨头，需本地连接器打通 https↔localhost）。
- 接口已为二者预留：`BrowserEngine` 是 `ImageEngine` 第三实现；会话层可接账号；用量日志可接计费。

---

## 10. 阶段路线

| 阶段 | 内容 | 本文档 |
|---|---|---|
| **P0** | 抽核心：`prompt_engine` + 编排 → 引擎无关，定义 `ImageEngine`/`DirectorBrain` 接口 | ✅ 本次 |
| **P1** | 新公网 SPA + FastAPI 后端 + Gemini/OpenAI 云引擎 + 会话/异步任务 + 完整体验 + 成本护栏与日志 | ✅ 本次 |
| **P2** | 账号 + 会员按次计费（保证盈利） | ⏳ 后续 |
| **P3** | 自带会员·本地连接器·浏览器引擎 | ⏳ 后续 |
