# ArchRenderAgent — 完整交接（给 codex / 下一位）

> 更新：2026-07-16，前任 Claude(Opus 4.8)。仓库 `/mnt/c/Users/Andy/ArchRenderAgent`（= Windows 同一份文件）。
> Flask 服务 127.0.0.1:5001。**只剩 `main` 分支**（僵尸 `feat/prompt-helper` 已删；已全推 origin）。
> 用户：建筑设计师、**非程序员**、国内、多数内测机**无 VPN**、Win/Mac/Linux 都有、中文交流。
> **读这一份就够**：「已完成」别重做，每项都写了「怎么做」。测试 **136 全绿**。
> **2026-07-16 大进展**：workflow scope 已授权、发布不再阻塞；已发 `v1.2.0`/`v1.2.1`/`v1.2.2`(Latest，源码包)+ native-v* 原生包 CI；
> 土星通讯「连上却报连不上」已根治(穿代理+TLS 握手)；连不上弹窗(主页+助手页)已加；GitHub 简介/homepage/topics/README 已梳理。

---

## 0. 铁律（用户明确要求，务必遵守）
1. **干一个验一个**：每做完一项当场实测再进下一项，别堆没验证的改动。
2. **功能必须"页面上真能用、能看到"**（用户被"看着做了其实没用"坑过多次）。
3. **诚实审计**：判断"做没做"只看代码，别信描述；没验证过就说没验证过。
4. **改完必重启 Windows 服务才生效**（`debug=False` 不热重载；`/mnt/c` 与 Windows 同一份文件，**不必 pull**）。
   页面标题旁有版本号可核对。静态文件(js/css/i18n.js)即时，但 **app.py 要重启**。
5. 提交只提相关文件、写清 message、结尾加 `Co-Authored-By`。
6. **密码红线**：不收集/存/传任何账号密码。需登录的操作凭据由用户**直接**给你。

## 1. 环境坑（踩过别重复）
- 跑单测：`uv run python -m pytest tests/ -q`（**136 全绿**）。
- 基础 uv 环境**无 numpy/onnxruntime/cv2**（在 `.venv-win`）；`import image_enhance` 会失败——故意测"缺依赖优雅跳过"。
- **RTK 代理**改写 `python3 -c`→要 `uv run`，且搅乱 `grep` 管道输出——读代码用 Read/带文件名的 grep；
  要跑脚本先写文件再 `PYTHONPATH=. uv run python 文件`（`import app` 需 cwd=仓库或设 PYTHONPATH）。
- **本地→api.github.com TLS 握手超时（实测仍如此）**：`gh release`/`gh api` **发不出去**。
  `git push` 到 github.com **能通但偶发 sideband 断连**（`for i in 1 2 3; do git push...; done` 重试即成）。
  → **发布只能靠 GitHub 服务器侧 CI**（绕开本地网络）。
- **验证手段（WSL 能做的）**：① `app.app.test_client()` in-process 打路由；② node + 最小 DOM 桩加载 `static/i18n.js`
  测 `I18N.t()`（桩见 scratchpad 里 i18n_harness.js 思路：stub localStorage/document/window/MutationObserver）；③ pytest。
  **碰不到**：真机浏览器渲染、真机 Chrome/CDP 生成、真实 Gemini/ChatGPT DOM、真实下载安装、window.open → 必须用户在 Windows 验。
- **WSL2 localhost 转发**：从 WSL `curl 127.0.0.1:5001` 会打到用户 Windows 实服务。只读 GET 可诊断；**切勿 POST**。
- Windows `.bat` 是 **GBK+CRLF**；Edit(UTF-8) 改会损坏，要字节级 `bytes.replace` 或 gbk 读写。app.py/js/py 都是 UTF-8。

## 2. 本会话已完成（9 提交 `d93587f..a5f160a`，都已推 main+feat，**别重做**）
| 提交 | 内容 | 验证 |
|---|---|---|
| `d8ae749` | VPN 网络自检 + 英文版机制根治 + Gemini 假死修复 | in-process/node桩/单测 |
| `7ba944f` | VPN 扩助手页 + 原生打包就绪(冻结态路径) + `ArchRenderAgent.spec` | 130 零回归 |
| `2751c85` | ChatGPT 引擎同步修假死竞态(与 Gemini 一致) | 单测 |
| `4b226c3` | README 中英对齐现状 | — |
| `42f3f30` | 「测试连接」按钮加可见反馈(原来点了 8s 无提示像死按钮) | i18n 单测 |
| `89b7480` | 土星通讯(VPN)一键安装框架(后端按系统下发) | 5 单测 |
| `5832f55` | 交接文档(旧版，本次已被此文件覆盖) | — |
| `1226323` | net_check 并行探测(8s→4s) + 土星按钮扩助手页 | 136 |
| `a5f160a` | 土星通讯改为**打开面板页**(用户给的是 tuxingss.com 面板链接非安装包) | 136 |

**关键细节（避免重复劳动）：**
- **英文版**：codex 的 `static/i18n.js` 字典**本已地道**（体检 539 条零客观缺陷，别重译）。用户报的"文字丑/语病"真因是
  **运行时兜底**吐字面 `[untranslated]` 标记 + 碎句拼接(中式语序)。已根治：`translateCore` 末尾 `if (HAN.test(out)) return value;`
  （残留中文回退原文），删了 `[untranslated]`/`HAN_RUN`。**新增 UI 中文串必须进 `i18n.js` EXACT 字典**，
  否则 `tests/test_i18n.py::test_visible_static_chinese...` 会挂（它校验 index.html/helper.html 每个可见中文都是字典 key）。
- **Gemini/ChatGPT 假死**（用户 Image#5）：根因=生成流已停但生成图 `<img>` **尚未解码完**(`naturalWidth=0`)，
  抓图 ≥256px 门槛抓不到 → 误判假死去 `reload` → 循环 → 整轮重试(第2/3次)。两 client 都加 `_image_loading_pending(page)`：
  图还在加载则继续等。Gemini 还加 `_dump_dom()`：抓不到图时落盘 `logs/gemini_dump_*.html`（供校准 `SEL["gen_image"]`）。
  **"Gemini 已是3.5 Flash 无需切换"是正常的**（按 "Flash" 子串匹配跳过切换），别当 bug"修"。
- **VPN 自检**：`/api/net_check`（`_host_reachable` 纯 socket:443 TCP 探测，**并行**，不发请求/不带凭据/不配网）；
  主页按引擎探 chatgpt.com[+gemini.google.com]，助手页 `?target=chatgpt`。连不上→页顶提示条 `#netBanner`/`#netBannerText`。
- **「测试连接」按钮**：有可见反馈（检测中/✓已连通/仍连不上/检测失败）——原来点了无反馈像死按钮，用户报过。
- **土星通讯(VPN)配置**：用户给的是**面板页** `https://tuxingss.com/#/dashboard`（在 `app.py` `SATURN_DASHBOARD_URL`）。
  连不上→提示条出「配置土星通讯」按钮(主页+助手页) → `installSaturn()` 前端 `window.open` 面板页，用户在其中登录、
  按自己系统下载安装客户端、连上后点「测试连接」。`/api/saturn_status` 回 `dashboard_url`/`installer_configured`/`configured`。
  **保留了直链安装路径**：`SATURN_INSTALLERS={win/mac/linux:""}` 若日后填真实安装包直链，按钮自动改回
  后端下载+启动安装程序(`/api/saturn_install`→`_run_saturn_install`→`_download_file`+`_launch_installer`)。`_current_os()` 判系统。
- **原生打包就绪**：`app.py` 冻结态(`sys.frozen`)把可写数据(workspace)放 exe 同级、只读资源(templates/static/vendor)
  从 `sys._MEIPASS` 读；**非冻结态逐字节同原行为**(130 测试验证)。`ArchRenderAgent.spec` 利用「本 app 只 CDP 接管
  用户 Chrome、从不 `.launch()`」→ **无需打包 chromium**。

## 3. 用户已拍板（按这个做，别再问）
- **英文版**：整站中/EN 可切、记 localStorage——已做。新增串进字典。
- **VPN**：安全版自检 + **土星通讯自愿配置**（打开面板页）。net_check 只探连通性、绝不替用户配系统网络；
  土星通讯是**用户自愿点按钮**才打开面板（不强制、不自动装）。
- **土星通讯**：用户给了面板链接 tuxingss.com/#/dashboard，故走「打开面板」；后端判系统。三平台都要。
- **助手页对话确认**：跟随所选引擎——已做(codex `314b7f5`)。

## 4. 阻塞中（2026-07-16：原硬阻塞已全解）
### ✅ 已解锁：`workflow` scope 已授权
- 原缺 `workflow` scope（token 只有 `gist,read:org,repo`），推 `.github/workflows/*.yml` 被拒。
- 解法（已完成）：后台起 `gh auth refresh -s workflow -h github.com`、抓一次性码给用户浏览器 login/device 输码授权即可
  （**交互式、要用户浏览器**，但可后台起+读输出文件拿码转达用户，不必让用户自己敲）。现 token 已含 workflow。
- 意外之喜：本会话里 api.github.com **本地居然通了**，`gh run/release/repo edit` 都能用（此前一直 TLS 超时）。
  但**别赖它**——发布仍走 CI（推 `v*`/`native-v*` tag 触发）最稳。
- `.github/workflows/` 两个 workflow 已提交 main 并跑通（release.yml 源码包 / native.yml 原生包→Actions Artifacts）。

> 注：土星通讯面板链接已接好；「连上却报连不上」已根治（见 §2 关键细节）。直链安装包仍是可选增强。

## 5. 未完成 — 接着做（workflow scope 到位后）
### A) 发布源码包 Release
```
git add .github/workflows/release.yml && git commit -m "ci: 发布工作流" && git push origin main
git tag v1.2.0 && git push origin v1.2.0
```
→ GitHub 侧 `release.yml` 跑 `scripts/make_release.py` 打三平台源码 zip + 删旧草稿 + 发正式 Release。
（`dist/` 本地也已生成 3 个 zip：`ArchRenderAgent-{windows,mac,linux}-1.2.0.zip`；`python scripts/make_release.py` 可重生。）
残留草稿 Release v1.2.0 会被 workflow 的 `release delete ... || true` 自动清掉。
### B) 原生安装包 .exe/.dmg（独立工程，别指望一次成）
```
git add .github/workflows/native.yml && git commit -m "ci: 原生构建" && git push origin main
git tag native-v1.2.0 && git push origin native-v1.2.0
```
→ `native.yml`(matrix win/mac/linux) 用 `ArchRenderAgent.spec` 跑 PyInstaller → **产物作为 Actions Artifacts** 上传
（不建 Release），下载实测通过再并入正式发布。**PyInstaller+Playwright 常需按 CI 日志迭代 1-2 轮**
（隐藏依赖、driver 收集、Flask 冻结态找 templates）。已利用「无需打包 chromium」简化。
若报找不到 templates/static → 查 spec 的 `datas` 与 app.py 的 `RES_DIR` 逻辑。
### C) 土星通讯直链（可选增强）
若用户日后给三平台安装包**直链**，填 `app.py` `SATURN_INSTALLERS` 即从「打开面板」升级为「后端下载+启动安装程序」。
Linux .deb 需 sudo 之类特殊情况，在 `_launch_installer()` 里按需调整。

## 6. 待用户真机验证（WSL 碰不到，留给用户）
- VPN 提示条 / 「测试连接」反馈 / 「配置土星通讯」按钮 显隐与点击（点它应弹出 tuxingss.com 面板）。
- 切 EN 通读，某句别扭截图发来精修（字典已很好，剩点修）。
- Gemini/ChatGPT 真机出图，假死循环是否消失；**若仍抓不到图**，发 `logs/gemini_dump_*.html` 精准修 `SEL["gen_image"]`。

## 7. 关键文件地图
- `app.py`(~120K) Flask 路由/主循环/本地视觉模型/画质增强/net_check/saturn/冻结态路径。
  相关标识：`_host_reachable`/`_net_hosts_for_engine`/`api_net_check`、`_current_os`/`SATURN_*`/`api_saturn_status`/`api_saturn_install`、
  `APP_DIR`/`RES_DIR`(冻结态)、`Flask(__name__, template_folder=RES_DIR/...)`。
- `chatgpt_client.py`/`gemini_client.py` CDP 接管已登录 Chrome 生图；各有 `_wait_reply_done`/`_last_image_handle`/`_image_loading_pending`；
  gemini 另有 `_dump_dom`。`SEL` 选择器在文件顶部，会随网页改版失效，靠 `logs/gemini_dump_*.html` 校准。
- `prompt_engine.py` 提示词组织。 `image_enhance.py` 超分/去水印(onnx 按需下载)。 `supervisor.py` 常驻守护。
- `templates/index.html`(主页)、`templates/helper.html`+`static/helper.js`(助手页)、`static/i18n.js`(中/EN 运行时翻译层)。
- `scripts/make_release.py`(打源码包)、`scripts/setup_wizard.py`(首次向导，codex 快启改动经审=正确别动)、`scripts/fetch_assets.py`。
- `ArchRenderAgent.spec`(PyInstaller)、`.github/workflows/{release,native}.yml`(**未跟踪待推**，需 workflow scope)。
- 进度记忆：`~/.claude/projects/-mnt-c-Users-Andy/memory/archrender-v1.2-progress.md`（append 别覆盖）。

## 8. codex 别碰/别重做清单
- 别重译 i18n 字典（已地道）；只在用户指出具体某句时点修，新串必进字典。
- 别再"修"Gemini "3.5 Flash 无需切换"（正常行为）。
- 别动 `setup_wizard.py` 快启逻辑（已审=正确）。
- 别把可写数据路径改回 `APP_DIR/__file__`（会破坏冻结态；`APP_DIR/RES_DIR` 拆分是对的）。
- 别本地 `gh release`（api.github.com 超时，白等）——发布走 CI。
- 别 force-push；main/feat 现同为 `a5f160a`，纯 FF 上来的。

## 9. 一句话状态（2026-07-16）
代码全绿(136)、main 已推；**`v1.2.2` 为 Latest 源码包 Release，native-v* 原生包走 CI(Actions Artifacts)**；
土星通讯「连上却报连不上」已根治(穿代理+TLS 握手，真机+API 双验)；连不上弹窗(主页+助手页)已加；
GitHub 简介/homepage/topics/README「下载即用」已梳理、僵尸分支已删。**待用户真机验**：连不上弹窗断网弹出闭环、Gemini/ChatGPT 出图假死是否消失。
