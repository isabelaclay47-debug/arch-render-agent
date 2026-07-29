# i18n 开发笔记（英文页去中文的坑与规约）

> 目标：**英文页(EN)不出现任何中文**。本文归类记录反复踩的坑、根因与规约，动 i18n
> 前必读，避免重新引入已修好的泄漏。

## 架构：中文是母语协议

- 服务端（`app.py` / `prompt_engine.py` / `gemini_client.py` …）**一律用中文**产出日志、
  文件名、导演对话。中文是"协议母语"。
- `static/i18n.js` 是**纯前端翻译层**：EN 模式下把 DOM 文本/属性、`alert/confirm`、状态
  日志按 **EXACT 字典 → DYNAMIC 正则 → PHRASES 短语拼接** 翻成英文。
- `templates/*.html` 里写中文；`i18n.js` 运行时替换。切换语言存 `localStorage["archrender.lang"]`。

分类：泄漏只会来自两类——**① 后端产出的语言（AI 给人看的文本 / 真实文件名）**，
**② 前端 i18n 覆盖不到的字符串**。下面按类记录。

## ① 后端语言相关（改后需重启服务）

### 坑 1：后端语言盲 → AI"给人看"的产出写死中文
导演对话（理解 / 工作提示词 / QC 分析）过去恒为中文，后端根本不知道页面语言。

**规约**：页面语言 `lang` 从 `/api/start` → `run_session()` → `pe.set_output_language(lang)`。
EN 时给导演各 prompt 追加英文强制指令（`prompt_engine._EN_OUTPUT_DIRECTIVE`）。
- **标签名保持中文**（`<理解>`/`<中文提示词>`/`<分析>` …）——解析靠它，别翻标签名。
- `<忠实度>`/`<下一步>` 的枚举值（一致/精修/重画…）是**机器令牌**，保持中文别翻。

### 坑 5：真实文件名/路径别只翻显示
桌面交付图后端命名 `渲染结果_MMDD_HHMM.png`。路径是**磁盘真名**，只翻显示会和真文件对不上。

**规约**：后端按 `lang` 命名（`_deliver_final(sess_dir, lang)`，EN 用 `render_result_` 前缀）；
前端把路径元素（如 `#finalPath`）加进 `SKIP_SELECTOR`（路径永不进字典翻译）。

## ② 前端 i18n 覆盖（改后浏览器硬刷新即生效）

### 坑 2：`t()` 按 `\n` 拆行
`t()` 先 `split("\n")` 再逐行翻译。HTML 源码里一句话跨多行、或句中插内联 `<b>`，会把句子
切成碎片，连接字（如"在"）单独成行、字典没有 → 漏译，还可能半中半英。

**规约**：**别让一句话跨源码行、别在句中用内联 `<b>`**。整句配一条 EXACT 词条。需要强调就
换措辞或把强调放句首/句尾。

### 坑 3：`SKIP_SELECTOR` 只保护正文，不该拦属性
`SKIP_SELECTOR`（`#requirement`/`#confirmNote` …）是为保护**用户输入/AI 正文**不被翻。但
`placeholder`/`title`/`aria-label`/`alt` 是**作者写死的界面文案**，必须翻。

**规约**：属性翻译走 `skippedForAttrs`（只认硬跳过容器 + `[data-i18n-skip]`），**不受 id 名单
管辖**；正文文本翻译才用 `skipped`（受 id 名单管辖）。别把 `translateAttrs` 改回 `skipped`。

### 坑 4：运行时拼接串带数字，进不了静态字典
如状态面板 `迭代运行中 · 第 1 轮`（`stateNames + " · 第 N 轮"` 拼的单个文本节点）。整串带
数字，EXACT 匹配不到；`translateCore` 兜底后残留中文就整串退回。

**规约**：这类用 **DYNAMIC 正则**。通配"标签 · 第 N 轮"已加：
`[/^(.+?)\s*·\s*第\s*(\d+)\s*轮$/, m => \`${translateCore(m[1])} · Round ${m[2]}\`]`
（非贪婪 + 标签递归 `translateCore`，自动覆盖所有状态，含自带 `·` 的"已暂停 · 待重试"）。

> 日志行前端会先剥掉 `[HH:MM:SS]` 时间戳，再对消息部分 `t()`（`index.html` renderLogs）。
> 所以 DYNAMIC 正则锚 `^消息开头` 即可，别把时间戳算进去。

## 加新翻译的顺序

1. 静态整句 / 固定短语 → 加 **EXACT**（`static/i18n.js` 顶部对象）。
2. 带变量（数字/路径/名字）的运行时串 → 加 **DYNAMIC**（正则 + 渲染函数，变量段按需
   `translateCore` 递归）。
3. AI 生成的"给人看"文本 → 不是字典问题，走 **①坑1** 的后端语言指令。

## 怎么验证（重要）

- **Python** `tests/test_i18n.py`：扫静态 HTML 的可见中文都有字典条目 + 属性翻译不变量。
- **Python** `tests/test_i18n_dynamic.py`：迷你模拟器跑一批真实运行时串，断言 EN 下不残留中文。
  ⚠️ 该模拟器对 DYNAMIC 命中只回 `<dynamic-ok>`，**只证明正则匹配、不证明标签本身译出**。
- **真 i18n.js**（补模拟器盲区）：无 jsdom，用 Node + 最小 DOM 桩 `vm.runInContext` 加载真
  `static/i18n.js`，驱动 `window.I18N.t()` / `window.I18N.translate(node)` 逐串核对英文。
  这是"标签是否真译出英文"的唯一可信手段。
- **后端日志审计法**（查状态栏泄漏）：用 Python `ast` 抓 `app.py`/`*_client.py` 里所有 `log()`
  首参（Constant / f-string / `+` 拼接都能重建），f-string 占位统一替 `3`，再逐条丢进上面
  的真 i18n.js `t()`，报残留汉字。注意 `{kind}`→`3` 会造成"3这一步没成功…"这类**替换假
  阳性**（真实值 文本/生图 已覆盖），核对时排除。`_net_log` 只写 `logs/app.log`、不上状态
  栏，可忽略。

## 生效方式速查

| 改动 | 生效 |
|---|---|
| ① 后端语言（AI 产出 / 文件名） | **重启 Windows 服务**，仅对重启后新任务生效 |
| ② 前端 `i18n.js` / `templates` | 浏览器 **Ctrl+Shift+R 硬刷新** |
