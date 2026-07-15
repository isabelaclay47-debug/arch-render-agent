# ArchRenderAgent — 完整交接（给 codex / 下一位）

> 更新：2026-07-15，前任 Claude(Opus 4.8)。仓库 `/mnt/c/Users/Andy/ArchRenderAgent`（= Windows 同一份文件）。
> Flask 服务 127.0.0.1:5001。**分支 `main` 与 `feat/prompt-helper` 同为 `89b7480`，均已推 origin。**
> 用户是建筑设计师、**非程序员**、国内、多数内测机**无 VPN**、多平台（Win/Mac/Linux 都有）、中文交流。
> **读这一份就够**：「已完成」别重做，「未完成/阻塞」是要接着做的，每项都写了「怎么做」。

---

## 0. 铁律（用户明确要求，务必遵守）
1. **干一个验一个**：每做完一项当场实测再进下一项，别堆一堆没验证的改动。
2. **功能必须"页面上真能用、能看到"**，不是摆设（用户被"看着做了其实没用"坑过多次）。
3. **诚实审计**：判断"做没做"只看代码里有没有，别信描述；没验证过就说没验证过。
4. **改完必重启 Windows 服务才生效**（`debug=False` 不热重载；`/mnt/c` 与 Windows 同一份文件，
   **不必 pull**）。页面标题旁有版本号可核对新旧。静态文件(helper.js/css/i18n.js)即时，但 **app.py 要重启**。
5. 提交只提相关文件、写清 message、结尾加 `Co-Authored-By`。
6. **密码红线**：不收集/不存/不传任何账号密码到仓库或对话。需登录的操作，凭据由用户**直接**给你。

## 1. 环境坑（踩过别重复）
- 跑单测：`uv run python -m pytest tests/ -q`（当前 **136 全绿**）。
- 基础 uv 环境**无 numpy/onnxruntime/cv2**（在 `.venv-win`）；`import image_enhance` 会失败——故意用来测"缺依赖优雅跳过"。
- **RTK 代理**会把 `python3 -c` 改写成要 `uv run`，且搅乱 `grep` 管道输出——读代码用 Read/带文件的 grep，
  别靠 grep 管道；要 `python3 -c` 先写脚本文件再 `uv run python 文件`（脚本放仓库根或加 `PYTHONPATH=.`）。
- **本地 → api.github.com TLS 握手超时**（实测仍然如此）：`gh release`/`gh api` **发不出去**。
  `git push` 到 github.com **能通但偶发 sideband 断连**（重试 1-2 次即成）。→ **发布只能靠 GitHub 服务器侧 CI**。
- **验证手段（我这边 WSL 能做的）**：① `app.app.test_client()` in-process 打路由（不碰用户 Windows 实服务）；
  ② node + 最小 DOM 桩加载 `static/i18n.js` 测 `I18N.t()`（见下）；③ pytest。
  **碰不到**：真机浏览器渲染、真机 Chrome/CDP 生成、真实 Gemini/ChatGPT DOM、真实下载安装 → 这些必须用户在 Windows 上验。
- **WSL2 localhost 转发**：从 WSL `curl 127.0.0.1:5001` 会打到用户 Windows 实服务。只读 GET 可诊断；**切勿 POST**。
- Windows 一键 `.bat` 是 **GBK+CRLF**；用 Edit(UTF-8) 改会损坏，要字节级 `bytes.replace` 或 gbk 读写。app.py/js/py 都是 UTF-8。

## 2. 本会话已完成（2026-07-15，7 提交在 `d93587f..89b7480`，**别重做**）
| 提交 | 内容 | 验证 |
|---|---|---|
| `d8ae749` | **VPN 网络自检**(`/api/net_check` 纯 socket:443 TCP 探测，不发请求/不带凭据/不配网) + **英文版机制根治** + **Gemini 假死修复** | in-process/node桩/单测 |
| `7ba944f` | VPN 自检扩到助手页(`?target=chatgpt`) + **原生打包就绪**(app.py 冻结态路径) + `ArchRenderAgent.spec` | 130 测试零回归 |
| `2751c85` | **ChatGPT 引擎同步修假死竞态**(与 Gemini 一致) | 单测 |
| `4b226c3` | README 中英对齐现状 | — |
| `42f3f30` | **「测试连接」按钮加可见反馈**(原来点了 8s 无提示像死按钮) | i18n 单测 |
| `89b7480` | **土星通讯(VPN) 一键安装**(连不上时用户自愿装，后端按系统下发；链接待填) | 5 单测 |

**细节（关键，避免重复劳动）：**
- **英文版**：codex 的 `static/i18n.js` 字典**本已地道**（体检 539 条零客观缺陷，别重译）。用户报的"文字丑/语病"真因是
  **运行时兜底**：未命中字典的中文被替换成字面 `[untranslated]` 标记 + 碎句拼接造成中式语序语病。
  已根治：兜底残留中文时**回退原文**（`i18n.js` translateCore 末尾 `if (HAN.test(out)) return value;`），删了 `[untranslated]`/`HAN_RUN`。
  **新增 UI 中文串必须加进 `i18n.js` EXACT 字典**，否则 `test_i18n.py::test_visible_static_chinese...` 会挂。
- **Gemini/ChatGPT 假死**（用户 Image#5）：根因=生成流已停但生成图 `<img>` **尚未解码完**(`naturalWidth=0`)，
  抓图的 ≥256px 门槛抓不到 → 误判假死去 `reload` → 循环 → 整轮重试(第2/3次)。
  两个 client 都加了 `_image_loading_pending(page)`：图还在加载则继续等，别刷。Gemini 还加了 `_dump_dom()`：
  抓不到图时把最后一条回复 DOM+所有图信息落盘 `logs/gemini_dump_*.html`。**"Gemini 已是3.5 Flash 无需切换"是正常的**（按 "Flash" 子串匹配跳过切换），不是 bug。
- **VPN 安全版**：`/api/net_check`（主页按引擎探 chatgpt.com[+gemini.google.com]；助手页 `?target=chatgpt`）。
  连不上→页面顶部提示条（`#netBanner`/`#netBannerText`），含「测试连接」(有反馈) 和「一键安装土星通讯」(见下)。
- **土星通讯一键安装**：`app.py` 里 `SATURN_INSTALLERS={windows/mac/linux: ""}`（**空=按钮不显示=不改现状**）；
  `_current_os()` 判系统；`/api/saturn_status`(是否配+进度)、`/api/saturn_install`(后台线程下载并启动安装程序)。
  前端 `installSaturn()` 轮询进度。**只等用户给三平台真实下载直链填进 `SATURN_INSTALLERS` 即激活**，无需改别的。
- **原生打包就绪**：`app.py` 冻结态(`sys.frozen`)把可写数据(workspace)放 exe 同级、只读资源(templates/static/vendor)
  从 `sys._MEIPASS` 读；**非冻结态与原行为逐字节一致**(130 测试验证)。`ArchRenderAgent.spec` 利用「本 app 只 CDP 接管
  用户 Chrome、从不 `.launch()`」→ **无需打包 chromium**，大幅简化。

## 3. 用户已拍板的设计决定（按这个做，别再问）
- **英文版**：整站中/EN 可切，选择记 localStorage——**已做**（codex `d93587f` + 我修机制）。新增串记得进字典。
- **VPN**：走**安全版 + 土星通讯自愿安装**。net_check 只探连通性、绝不替用户配置系统网络；土星通讯是
  **用户自愿点按钮**才下载安装（不强制、不自动）。这是用户 2026-07-15 明确要的（覆盖了更早"通用提示不放链接"的选择）。
- **土星通讯安装方式**：一键下载+打开安装程序（像装 Ollama）；**后端判系统、只下发对应平台包**；三平台都要。
- **助手页对话确认**：跟随所选引擎——**已做**（codex `314b7f5`）。

## 4. 阻塞中（**等用户两件事，别自己硬试**）
### ① 缺 `workflow` scope → 发布(源码包)和原生包 CI 都推不了
- 现象：`git` token scope 只有 `gist, read:org, repo`，**没 workflow**；推 `.github/workflows/*.yml` 会被 GitHub 拒。
- 而 api.github.com 从本地 TLS 超时，**本地 `gh release create` 发不出去**，所以发布**只能靠 CI 在 GitHub 服务器侧跑**。
- `.github/workflows/`（`release.yml` 源码包发布 + `native.yml` 原生 .exe/.dmg 构建）**已在磁盘、未跟踪**，等 scope 才能推。
- **解锁动作（只有用户能跑，浏览器 OAuth，我们替代不了）**：
  ```
  ! gh auth refresh -s workflow -h github.com
  ```
  用户跑完、授权后 → 你就能：`git add .github && git commit && git push`（推工作流）→ 打 tag 触发 CI。
### ② 土星通讯三平台下载直链未提供
- `app.py` `SATURN_INSTALLERS` 三个值是空的（Windows/Mac/Linux）。**问用户要真实直链**填进去即激活。
  某平台没有就留空（该系统不显示安装按钮）。填完在 Windows 上真机点一次「一键安装」验证下载+启动安装程序。

## 5. 未完成 — 接着做（授权/链接到位后）
### A) 发布源码包 Release（等 ① workflow scope）
- 授权后：`git add .github/workflows/release.yml && git commit -m "ci: 发布工作流" && git push origin main`
  → `git tag v1.2.0 && git push origin v1.2.0` → GitHub 侧 `release.yml` 跑 `scripts/make_release.py` 打三平台
  源码 zip + 删旧草稿 + 发正式 Release。（`dist/` 本地也已生成 3 个 zip，可 `python scripts/make_release.py` 重生。）
- 残留草稿 Release v1.2.0（上次超时留下）会被 workflow 的 `release delete ... || true` 自动清掉。
### B) 原生安装包 .exe/.dmg（等 ① workflow scope；独立工程，别指望一次成）
- 授权后推 `native.yml` + 打 `native-v1.2.0` tag → 触发 `native.yml`(matrix win/mac/linux) 用 `ArchRenderAgent.spec`
  跑 PyInstaller → **产物先作为 Actions Artifacts** 上传（不建 Release），下载实测通过再并入正式发布。
- **PyInstaller+Playwright 常需按 CI 日志迭代 1-2 轮**（隐藏依赖、driver 收集、Flask 冻结态找 templates）。
  已利用「无需打包 chromium」简化。若报找不到 templates/static → 检查 spec 的 datas 与 app.py 的 RES_DIR 逻辑。
### C) 土星通讯（等 ② 链接）
- 用户给链接 → 填 `SATURN_INSTALLERS` → 真机验一次。若某平台安装方式特殊(如 Linux .deb 要 sudo)，
  `_launch_installer()` 里按需调整（现在：win=`os.startfile`、mac=`open`、linux=`.AppImage` 直跑 / 其它 `xdg-open`）。

## 6. 待用户真机验证（我这边碰不到，用户"先不验真机"故留给他）
- VPN 提示条/「测试连接」反馈/「一键安装土星通讯」按钮在 Windows 上的显隐与点击。
- 切 EN 通读，若某句读着别扭截图发来精修（字典已很好，剩下点修）。
- Gemini/ChatGPT 真机出图，假死循环是否消失；**若仍抓不到图**，发 `logs/gemini_dump_*.html` 来精准修 `SEL["gen_image"]`。

## 7. 关键文件地图
- `app.py`(~118K) Flask 全部路由/主循环/本地视觉模型/画质增强调度/net_check/saturn/冻结态路径。
- `chatgpt_client.py` / `gemini_client.py` 网页驱动生图(CDP 接管已登录 Chrome)；各有 `_wait_reply_done`/`_last_image_handle`/`_image_loading_pending`。
- `prompt_engine.py` 提示词组织。 `image_enhance.py` 超分/去水印(onnx 按需下载)。 `supervisor.py` 常驻守护。
- `templates/index.html`(主页)、`templates/helper.html`+`static/helper.js`(助手页)、`static/i18n.js`(中/EN 运行时翻译层)。
- `scripts/make_release.py`(打源码包)、`scripts/setup_wizard.py`(首次安装向导，codex 快启改动经审=正确别动)、`scripts/fetch_assets.py`。
- `ArchRenderAgent.spec`(PyInstaller 原生打包)、`.github/workflows/{release,native}.yml`(**未跟踪待推**，需 workflow scope)。
- 进度记忆：`~/.claude/projects/-mnt-c-Users-Andy/memory/archrender-v1.2-progress.md`（append 别覆盖）。

## 8. codex 别碰/别重做清单
- 别重译 i18n 字典（已地道）；只在用户指出具体某句时点修，且新串必进字典。
- 别再"修"Gemini 的"3.5 Flash 无需切换"（那是正常行为）。
- 别动 `setup_wizard.py` 的快启逻辑（已审=正确）。
- 别把可写数据路径改回 `APP_DIR/__file__`（会破坏冻结态；现在的 `APP_DIR/RES_DIR` 拆分是对的）。
- 别本地 `gh release`（api.github.com 超时，白等）——发布走 CI。
- 别 force-push；main/feat 现同为 89b7480，都是纯 FF 上来的。

## 9. 一句话状态
代码全绿(136)已推 main+feat=89b7480；**发布 + 原生包都只差用户跑一次 `gh auth refresh -s workflow`**；
**土星通讯只差用户给三平台下载链接**；英文/Gemini/VPN 均已实现待用户真机验。
