# 发布交接（给 codex）— ArchRenderAgent

> 目的：把「GitHub 页面填写 + Release 发布 + 宣传」这类后期工作交接给 codex。
> 本文档**不含任何账号密码**——见下方「凭据」一节。

## ⚠️ 凭据边界（务必先读）
- 本文档及仓库里**不写、不存任何账号/密码/token**。
- 需要登录的操作（GitHub 发布、社交平台宣传等），由**用户把凭据直接提供给你（codex）**，
  不经过 Claude、不落盘进仓库。
- 若某步需要 `GITHUB_TOKEN` 等，请用户用环境变量临时注入，用完即清，别写进任何文件。

## 一、仓库与现状
- Repo：`https://github.com/isabelaclay47-debug/arch-render-agent`
- 默认分支 `main` 与 `feat/prompt-helper` 均已推到最新（本轮 7 提交，`00d09a0`）。
- 版本：见 `VERSION`（当前 1.2.0）。测试：`uv run python -m pytest tests/ -q`（应全绿）。
- 部署模型：用户机器从 `/mnt/c/...`（= Windows 同一份文件）跑，改代码后**需重启 Windows 服务**才生效
  （页面标题旁有版本号可核对）。

## 二、生成发布包
```
python scripts/make_release.py          # 产出 dist/ArchRenderAgent-windows-<ver>.zip 与 -mac-<ver>.zip
```
- 只打包 git 跟踪、且用户运行所需的文件；模型/venv/登录态/测试/开发文档**不进包**。
- **每个平台包只含本平台启动脚本**：Windows 包只有 `.bat`，Mac 包只有 `.command`——
  不再 Win/Mac 混在一起（用户明确反馈过"里面全是 mac"）。
- 每个 zip 顶层有「① 先看我-<平台>.txt」，非技术用户照做即可（双击对应启动脚本）。
- 模型（超分/去水印/本地识图）首次使用时自动从免 VPN 源下载。

**Release 页面务必把两个包分开、清楚标注平台**，让用户一眼下到自己系统的那个：
- `ArchRenderAgent-windows-<ver>.zip` —— Windows 用户下这个
- `ArchRenderAgent-mac-<ver>.zip` —— macOS 用户下这个

## 三、codex 待办（后期发布/宣传）
1. **GitHub Release**：给当前版本打 tag（如 `v1.2.0`），上传上面两个 zip，写 Release Notes
   （可基于本仓 `git log` 与 `HANDOFF.md`/进度整理）。
2. **仓库门面**：填 About（一句话描述 + 关键词 topics）、完善 `README.md`/`README.zh-CN.md`
   的截图与「快速开始」，确认 `LICENSE` 合适。
3. **宣传**：按用户要求在其指定渠道发布（用户提供各平台凭据）。文案可强调：
   建筑渲染智能体、本地离线识图免账号免 VPN、ChatGPT/Gemini 双引擎、超分+去水印。

## 四、已完成（本轮）
- 修 Windows GBK 日志崩溃（整轮生图失败的根因）。
- Gemini 模型切换按钮识别、去水印/画质默认提示词、建筑专用识图。
- 本地识图模型「切换」（两个模型都能装、随时切）+ 旧后端提示 + 长名匹配。
- 助手页改为「看图→对话确认→再生成」（跟随所选引擎）。
- director 空回复根治（英文提示词缺失）。
- 打包：`scripts/make_release.py`、首次安装向导 `scripts/setup_wizard.py`
  （可选组件首次问、之后不问）、启动脚本已接入向导。

## 五、尚未完成（Claude 继续做，别与你重叠）
- **整站英文版**可切换（i18n，进行中/待做）。
- **VPN 安全版**：网络自检 + 引导用户自备（不分发/不自动配网）。
- 这两项由 Claude 负责实现；codex 专注发布与宣传。
