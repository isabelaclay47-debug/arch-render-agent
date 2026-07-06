# 建筑渲染智能体 · ArchRenderAgent

**[English](README.md) · 中文**

用**你自己的 ChatGPT 账号额度**，自动完成「理解需求 → 组织提示词 → 生图 → 对比原图查篡改 → 迭代优化」的建筑渲染循环。你随时可以圈选局部修改、按点评继续，或提前输出。

> **这是一个本地工具，自带 ChatGPT 使用。** 它在你本机接管一个你已登录的 Chrome，用你的 ChatGPT 订阅出图——不上传到任何第三方服务器，也不共享账号。想用它的人，各自把仓库 clone 到自己电脑、用自己的 ChatGPT 登录跑起来即可（因此**不是**一个大家共用的网址）。生图功能需要能在 ChatGPT 网页里生成图片的账号（通常是 Plus/Pro）。

---

## 快速开始

**前置条件**：Python 3.10+、Google Chrome、一个能在网页版 ChatGPT 生图的账号。

### Windows（最简单：双击一下全自动）
**双击 `双击启动.bat`** 即可——它会自动检查 Python、装依赖、打开专用 Chrome、启动服务并打开操作页 http://127.0.0.1:5001 。首次运行会稍慢（装依赖 1–3 分钟），并弹出一个 Chrome 让你**登录一次 `chatgpt.com`**（这个窗口整个过程别关，可最小化）。
> 没装 Python？脚本会自动打开下载页；安装时记得勾选 **“Add Python to PATH”**，装完再双击一次。
> 想分步来的高级用户，也可以分别用 `start_chrome.bat` + `run.bat`。

### macOS（双击一下全自动）
**双击 `双击启动-Mac.command`** 即可（首次若提示“无法打开”，右键 → 打开 → 允许一次）。它会自动建环境、装依赖、打开专用 Chrome 让你登录 `chatgpt.com`、启动服务并打开操作页。

### Linux / 手动方式
```bash
# 1) 装依赖（首次）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) 启动一个带调试端口的专用 Chrome，并在里面登录 chatgpt.com（这个窗口别关）
#    macOS:
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-profile" \
  --no-first-run --no-default-browser-check https://chatgpt.com/
#    Linux:
google-chrome --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-profile" \
  --no-first-run --no-default-browser-check https://chatgpt.com/

# 3) 另开一个终端，启动服务
source .venv/bin/activate
python app.py
# 浏览器打开 http://127.0.0.1:5001
```
> Playwright 只是**接管你已开的 Chrome**（CDP），不需要 `playwright install` 下载浏览器内核。

打开页面后，右上角有「检测」按钮确认 ChatGPT 登录状态为绿色即可开始。

---

## 使用流程

1. 填**需求描述**、上传**原图**（必传，会被严格忠实）、可选上传若干**意向图**（只借鉴氛围/材质/光线）。设定画质、画幅、以及**「几张一停」**（默认 1 张一停，最省额度）。
2. **确认关卡**：AI 先用中文**讲解它对你需求的理解**，并给一份**可编辑的中文提示词**。你核对有没有理解偏差——
   - 「就用这份，开始生图」→ 开始出图；
   - 改动中文 / 写一句意见后点「让 AI 按我的修改再调整」→ AI 重新对齐，再确认。
   - （需求真有歧义时，AI 会先**反问**你，答清再继续——这些都不消耗生图额度。）
3. **自动迭代**：ChatGPT 生图 → 与原图对比查篡改/画质 → 判断「精修上一张」还是「从原图重画」。每几张暂停等你点评。
4. **点评暂停时**你可以：
   - 写点评 →「按点评继续」；
   - 点某张图下的「📋 把这条评价填入点评框」，把 AI 的自测评价一键当点评；
   - 点「🖌 圈选局部修改」→ 用**手画 / 直线 / 框选 / 多边形套索 / 涂抹 / 橡皮擦**标红要改的区域 + 写指令 → AI 只改标记区、不动周边；
   - 点「满意，输出到桌面」→ 最终图存到桌面；随时可「提前结束」拿当前最新图。
5. 所有过程图与提示词记录保存在 `workspace/会话时间戳/`，可回溯。

---

## 工作原理

- **导演对话**（一个 ChatGPT 会话）全程负责：理解需求 → 按 ArchiPrompt 框架 + 专业储备库组织提示词 → 每轮拿生成图与原图逐项对比查篡改 → 修订。
- **中英分离**：网站上你只跟中文打交道；真正发给 ChatGPT 的是**英文提示词**（图像模型对英文更稳）。
- **双路径迭代**（省额度 + 缺陷不反复）：局部瑕疵在上一张基础上**增量精修**（其余逐像素保留），形体被明显篡改或需全局大改才**从原图重画**；QC 每轮拿新图与原图对比，发现漂移自动回退重画。
- **底线固化**：每条发给生图的英文指令都强制附带「不改建筑细节 / 提高画质保证细节 / 直线要直 / 文字端正 / 分类负向词」——用户没说也照加。
- **健壮性**：文本步骤（导演对话）等不到回复会自动刷新重发，不会一卡就杀掉整单。
- 你的点评是最高优先级修改依据。

---

## 常见问题

- **连不上 Chrome 调试端口** — 没启动带 `--remote-debugging-port=9333` 的专用 Chrome，或它被关了。
- **找不到输入框 / 未登录** — 那个 Chrome 里没登录 chatgpt.com，或弹了人机验证，去处理一下。
- **生图很慢 / 等不到图** — ChatGPT 生图本身要 1–3 分钟/张；额度用尽会一直等不到，去 Chrome 里确认。
- **ChatGPT 改版导致选择器失效** — 修改 `chatgpt_client.py` 顶部的 `SEL` 字典即可。

## 依赖与兼容性

Python 3.10+，见 `requirements.txt`（Flask / Pillow / requests / playwright）。支持 Windows、macOS、Linux、WSL。Playwright 只接管现有 Chrome，无需下载浏览器内核。

## 许可证

[MIT](LICENSE) —— 自由使用、修改、商用，保留版权声明即可。
