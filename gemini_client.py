# -*- coding: utf-8 -*-
"""
Gemini（nano-banana）网页驱动：通过 CDP 接管一个已登录的 Chrome，
在 gemini.google.com 里发消息、传图、等生成、下载生成图。**用订阅额度、零 API key**。

只负责「生图 / 局部改图」这一角色（对应 ChatGPTClient 的 gen_page 部分）；
理解、扩写提示词、篡改检查等文本推理仍走 ChatGPTClient 的导演对话。
两个 client 接管的是**同一个** Chrome（同一 CDP 端口、同一 context），只是各开自己的标签页。

前提：Chrome 以 --remote-debugging-port=9333 启动（start_chrome.bat），
并且该 Chrome 里已登录 gemini.google.com，且当前对话已选中 nano-banana 生图模型。

⚠ 选择器校准：下面 SEL 里的选择器是**基于 Gemini 网页常见结构的初值**。
Gemini 是专有网页、会改版，务必在 Windows 上对着已登录的 gemini.google.com、
用开发者工具（F12）核对/修补这些选择器。本文件设计为「只改 SEL、不改逻辑」即可跑通。
"""
import base64
import time

from playwright.sync_api import sync_playwright

# 复用 chatgpt_client 的 GenStalledError：app.py 用「except GenStalledError」把会话停在
# 「待重试」而非结束。Gemini 生图卡死也必须命中同一处理，所以两边共用同一个异常类。
from chatgpt_client import GenStalledError, GenCancelled

# 与 chatgpt_client 共用同一个被接管的 Chrome（同端口同 context，各开各的标签）
CDP_PORT = 9333
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
GEMINI_URL = "https://gemini.google.com/app"

# —— 选择器：editor/send/upload 已对着实时 gemini.google.com（中文界面）核对确认；
#    stop/assistant 待一次真实生成时最终校准（逗号分隔=多候选，命中任一即可）——
SEL = {
    # 输入框（已确认）：Gemini 富文本编辑器 .ql-editor
    "editor": 'div.ql-editor[contenteditable="true"], rich-textarea div[contenteditable="true"], '
              'div[contenteditable="true"][role="textbox"]',
    # 发送按钮（已确认）：aria-label「发送」；结构兜底 .send-button-container button
    "send": 'button[aria-label*="发送"], button[aria-label*="Send"], .send-button-container button',
    # 生成中/停止按钮（待最终校准）：生成时发送键常变为「停止」
    "stop": 'button[aria-label*="停止"], button[aria-label*="Stop"], button[aria-label*="取消"], '
            'button.stop-button',
    # 模型回复容器（已确认）
    "assistant": "model-response, .response-container",
    # 生成图（已确认）：alt「，AI 生成」、img.image 在 single-image.generated-image 内
    "gen_image": 'generated-image img.image, single-image.generated-image img, img[alt*="AI 生成"], generated-image img',
    # 上传入口（已确认）：先点「上传和工具/添加文件」按钮，再选「上传文件」，才出 input[type=file]
    "upload": 'button[aria-label*="上传"], button[aria-label*="添加文件"], button[aria-label*="添加"]',
    # 上传菜单里的「上传文件」项（待最终校准）
    "upload_item": 'button:has-text("上传文件"), [role="menuitem"]:has-text("上传"), '
                   'button:has-text("上传图片")',
    # 传图 input（点了上传后才出现/可用）
    "file_input": 'input[type="file"]',
    # 模型选择器入口（待真机校准）：Gemini 顶栏的模型切换按钮，点开后出模型菜单
    "model_switcher": 'button[aria-label*="模型"], button[aria-label*="切换模型"], '
                      'button[aria-label*="model" i], bard-mode-switcher button, '
                      '.gds-mode-switch-button, .logo-pill-btn',
}

TEXT_TIMEOUT = 300
IMAGE_TIMEOUT = 600


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    """只实现「生图角色」需要的接口，与 ChatGPTClient 的 gen 部分同构：
    connect / new_generation_chat / gen_page / send(expect_image) / download_last_image / close。"""

    def __init__(self, cdp_url: str = CDP_URL, log=print, nudge=None, cancel=None, model=None):
        self.cdp_url = cdp_url
        self.log = log
        self.nudge = nudge          # threading.Event：用户点「人工干预」时置位
        self.cancel = cancel        # threading.Event：用户点「提前结束」时置位，等待循环即时中止(#6b)
        self.model = (model or "").strip() or None   # 用户选的 Gemini 生图模型，None=用页面当前默认
        self._pw = None
        self._owns_pw = True        # 是否由本 client 负责关闭 playwright；与 ChatGPT 共用时为 False
        self._browser = None
        self._ctx = None
        self.gen_page = None        # 生成对话页

    # ---------- 连接与页面管理 ----------

    def connect(self, pw=None):
        """pw：与 ChatGPTClient 共用的已启动 sync_playwright（必须共用——同一线程
        无法起第二个 sync_playwright，否则抛「Playwright Sync API inside the asyncio loop」）。"""
        self._owns_pw = pw is None
        self._pw = pw or sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            raise GeminiError(
                f"连不上 Chrome 调试端口({self.cdp_url})。请先运行 start_chrome.bat "
                f"并在弹出的 Chrome 里登录 gemini.google.com。原始错误：{e}")
        if not self._browser.contexts:
            raise GeminiError(f"{CDP_PORT} 端口上的浏览器没有可用上下文，请关掉占用后重启专用 Chrome。")
        self._ctx = self._browser.contexts[0]
        self.gen_page = self._ctx.new_page()
        self._open_chat(self.gen_page)
        self._check_logged_in(self.gen_page)
        self.select_model(self.gen_page)
        self.log("已接管 Chrome，Gemini（nano-banana）登录状态正常，用于生图。")

    def _open_chat(self, page):
        page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

    def select_model(self, page):
        """尽力把 Gemini 网页切到用户选的生图模型（self.model）。best-effort：
        找不到模型选择器或菜单项时**不报错**，只 log 明确指示用户手动切——这样即便
        Gemini 改版 DOM，功能也不是摆设（用户知道该做什么）。返回 True=已点选/无需切。"""
        if not self.model:
            return True
        try:
            # 已在目标模型？菜单入口文本常含当前模型名，含目标名就当已选中
            try:
                switcher = page.query_selector(SEL["model_switcher"])
                if switcher and self.model.lower() in (switcher.inner_text() or "").lower():
                    self.log(f"Gemini 已是「{self.model}」，无需切换。")
                    return True
            except Exception:
                switcher = None
            if not switcher:
                self.log(f"没找到 Gemini 模型切换按钮——请在 Gemini 页面顶部手动切到「{self.model}」再继续。")
                return False
            switcher.click()
            page.wait_for_timeout(800)
            # 菜单里点包含目标模型名的项（宽松：短名如「2.5 Flash Image」也命中）
            short = self.model.replace("Gemini", "").strip()
            item = None
            for txt in (self.model, short):
                try:
                    item = page.query_selector(
                        f'[role="menuitem"]:has-text("{txt}"), button:has-text("{txt}"), '
                        f'[role="option"]:has-text("{txt}")')
                except Exception:
                    item = None
                if item:
                    break
            if item:
                item.click()
                page.wait_for_timeout(1200)
                self.log(f"已在 Gemini 网页切到模型「{self.model}」。")
                return True
            # 展开了菜单但没匹配到项：收起菜单，指示手动
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            self.log(f"Gemini 模型菜单里没找到「{self.model}」——请手动在页面上切换该模型。")
            return False
        except Exception as e:
            self.log(f"切换 Gemini 模型时出错（{str(e)[:60]}）——请手动切到「{self.model}」，不影响其它功能。")
            return False

    def _check_logged_in(self, page):
        try:
            page.wait_for_selector(SEL["editor"], timeout=20000)
        except Exception:
            raise GeminiError(
                "Gemini 页面上找不到输入框——多半是未登录、弹了验证，或选择器需要校准。"
                "请到那个 Chrome 窗口里登录 gemini.google.com 后重试。")

    def _page_alive(self, page) -> bool:
        if page is None:
            return False
        try:
            page.evaluate("1")
            return True
        except Exception:
            return False

    def _reconnect(self):
        self.log("检测到浏览器/页面已断开，正在重连专用 Chrome 并重开 Gemini 页面…")
        # 不 stop 再 start playwright：与 ChatGPT 共用同一个 pw，停掉会连累对方，且同一线程
        # 无法再起第二个 sync_playwright。CDP 断开只需重新 connect_over_cdp 拿新 browser。
        if self._pw is None:
            self._pw = sync_playwright().start()
            self._owns_pw = True
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        if not self._browser.contexts:
            raise GeminiError("重连后浏览器没有可用上下文——请检查专用 Chrome 是否还开着。")
        self._ctx = self._browser.contexts[0]
        self.gen_page = self._ctx.new_page()
        self._open_chat(self.gen_page)
        self.select_model(self.gen_page)
        self.log("已重连 Gemini，继续任务。")

    def new_generation_chat(self):
        """每轮生成换一个全新标签页再导航——旧标签生成几次后网页常假死/连接重置，换新标签最干净。"""
        old = self.gen_page
        self.gen_page = self._open_fresh_gen_chat()
        self.select_model(self.gen_page)
        if old is not None and old is not self.gen_page:
            try:
                old.close()
            except Exception:
                pass

    def new_generation_window(self):
        """比换标签更狠一档：另开一个真·新浏览器窗口再导航。用于生图反复卡死、
        换新标签也救不活时——对应需求：卡死几分钟干预不成功就直接开新窗户。"""
        self.log("换新标签仍未出图，改为**另开一个新窗口**重试…")
        old = self.gen_page
        self.gen_page = self._open_fresh_gen_window()
        self.select_model(self.gen_page)
        if old is not None and old is not self.gen_page:
            try:
                old.close()
            except Exception:
                pass

    def _alive_opener(self):
        if self._page_alive(self.gen_page):
            return self.gen_page
        try:
            for p in self._ctx.pages:
                if self._page_alive(p):
                    return p
        except Exception:
            pass
        return None

    def _open_fresh_gen_window(self, tries: int = 2):
        last = None
        for i in range(tries):
            opener = self._alive_opener()
            if opener is None:
                try:
                    self._reconnect()
                    return self.gen_page
                except Exception as e:
                    last = e
                    time.sleep(1.5)
                    continue
            try:
                with self._ctx.expect_page(timeout=20000) as pinfo:
                    opener.evaluate(
                        "() => window.open('" + GEMINI_URL + "','_blank','width=1400,height=1000')")
                page = pinfo.value
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                return page
            except Exception as e:
                last = e
                self.log(f"开新窗口失败（{str(e)[:70]}），重试（{i + 1}/{tries}）…")
                time.sleep(1.5)
        self.log("开新窗口多次失败，退回新标签方式。")
        return self._open_fresh_gen_chat()

    def _open_fresh_gen_chat(self, tries: int = 3):
        last = None
        for i in range(tries):
            try:
                page = self._ctx.new_page()
            except Exception as e:               # 上下文/浏览器没了 → 整体重连
                last = e
                try:
                    self._reconnect()
                    return self.gen_page
                except Exception as e2:
                    last = e2
                    time.sleep(1.5)
                    continue
            try:
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                return page
            except Exception as e:
                last = e
                self.log(f"打开 Gemini 新对话失败（{str(e)[:70]}），换个新标签重试（{i + 1}/{tries}）…")
                try:
                    page.close()
                except Exception:
                    pass
                time.sleep(1.5)
        raise GenStalledError(
            f"多次开 Gemini 新对话都连接失败（{last}）——已暂停但未结束，可点「刷新 / 重试本轮」再试。")

    def close(self):
        try:
            if self._pw and self._owns_pw:   # 只有创建者才关，避免关掉与 ChatGPT 共用的 pw
                self._pw.stop()
        except Exception:
            pass

    def _current_gen_page(self):
        return self.gen_page

    # ---------- 发消息 / 生图 ----------

    def send(self, page, text: str, image_paths=None, expect_image=False) -> str:
        """发一条消息（带底图/标记图），阻塞等生成完成。返回回复文本（生图时通常为空串）。
        自愈式重试：页面死了整体重连；生图卡死换新对话重发；3 次仍失败抛 GenStalledError。
        为与 ChatGPTClient.send 同签名，expect_image 保留；本 client 主要用于 expect_image=True。"""
        image_paths = image_paths or []
        timeout = IMAGE_TIMEOUT if expect_image else TEXT_TIMEOUT
        max_attempts = 3
        last_err = None

        for attempt in range(1, max_attempts + 1):
            self._raise_if_cancelled()       # 尝试之间也响应提前结束(#6b)
            page = self._current_gen_page()
            try:
                before = page.locator(SEL["assistant"]).count()
                if image_paths:
                    self._attach_files(page, image_paths)
                editor = page.locator(SEL["editor"]).first
                editor.click()
                page.keyboard.insert_text(text)
                page.wait_for_timeout(500)
                self._click_send(page, before)
                self._wait_reply_done(page, before, timeout, expect_image)
                return self.last_reply_text(page)
            except GenCancelled:
                raise                        # 提前结束：不重试、不吞，直接上抛让上层收尾(#6b)
            except GeminiError as e:
                last_err = e
                if attempt < max_attempts:
                    self._recover_before_retry(attempt, max_attempts, expect_image)
            except Exception as e:
                last_err = GeminiError(f"页面操作异常：{e}")
                if attempt < max_attempts:
                    self._recover_before_retry(attempt, max_attempts, expect_image, force_reconnect=True)
        if expect_image:
            raise GenStalledError(
                f"Gemini 生图连续 {max_attempts} 次自愈仍未出图（{last_err}）。可能额度用尽或排队——"
                "任务已暂停但未结束，可点「刷新 / 重试本轮」再试。")
        raise last_err

    def _recover_before_retry(self, attempt, max_attempts, expect_image, force_reconnect=False):
        self.log(f"生图这一步没成功，自动干预后重试（第 {attempt + 1}/{max_attempts} 次）…")
        page = self._current_gen_page()
        if force_reconnect or not self._page_alive(page):
            try:
                self._reconnect()
                return
            except Exception as e:
                self.log(f"重连失败（{e}），改为换新对话再试一次。")
        try:
            # 换标签还救不活（attempt>=2）→ 直接另开新窗口（卡死几分钟干预不成功就开新窗户）
            if attempt >= 2:
                self.new_generation_window()
            else:
                self.new_generation_chat()   # 生图：换个干净的新对话重发，救活假死的标签
        except Exception:
            pass

    def _attach_files(self, page, paths):
        # Gemini 没有常驻 input[type=file]：点「上传和工具」→「上传文件」触发原生文件框，
        # 用 expect_file_chooser 截获后 set_files（一次可多选）。页面已有 input 则直接用（改版兜底）。
        existing = page.locator(SEL["file_input"])
        if existing.count() > 0:
            existing.first.set_input_files(paths)
        else:
            page.locator(SEL["upload"]).first.click()       # 打开「上传和工具」菜单
            page.wait_for_timeout(600)
            try:
                with page.expect_file_chooser(timeout=30000) as fc:
                    page.locator(SEL["upload_item"]).first.click()   # 点「上传文件」
                fc.value.set_files(paths)
            except Exception as e:
                raise GeminiError(f"上传文件时没弹出文件选择框（{str(e)[:60]}）——上传菜单选择器可能需校准。")
        # 等上传处理完：缩略图出现 / 发送按钮可用
        deadline = time.time() + 120
        while time.time() < deadline:
            btn = page.locator(SEL["send"]).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    return
            except Exception:
                pass
            page.wait_for_timeout(1000)
        raise GeminiError("图片上传后 2 分钟内发送按钮仍不可用，上传可能失败。")

    def _editor_text(self, page) -> str:
        try:
            return (page.locator(SEL["editor"]).first.inner_text() or "").strip()
        except Exception:
            return ""

    def _submitted(self, page, before_count: int) -> bool:
        """提示词是否真发出去了：出现停止按钮 / 新回复出现 / 输入框已清空，任一即算。
        与 ChatGPT 修复 1d0bd5e 同理：过去只点一次不验证，点空了也照样去等回复→无限刷新空等。"""
        try:
            if page.locator(SEL["stop"]).first.is_visible():
                return True
        except Exception:
            pass
        try:
            if page.locator(SEL["assistant"]).count() > before_count:
                return True
        except Exception:
            pass
        return self._editor_text(page) == ""

    def _click_send(self, page, before_count: int):
        """发送并**确认发送生效**：点按钮/回车 → 验证；没生效就换招（回车↔再点）重试。
        真发不出去才抛错让上层自愈——而不是傻等一个从没发出去的回复（#3 发送验证）。"""
        deadline = time.time() + 15
        while time.time() < deadline:          # 等发送键从禁用变可用（打字后需一点时间 enable）
            try:
                btn = page.locator(SEL["send"]).first
                if btn.is_visible() and btn.is_enabled():
                    break
            except Exception:
                pass
            page.wait_for_timeout(300)
        for _ in range(4):
            try:
                btn = page.locator(SEL["send"]).first
                if btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=4000)
                else:
                    page.locator(SEL["editor"]).first.click()
                    page.keyboard.press("Enter")
            except Exception:
                try:
                    page.locator(SEL["editor"]).first.click()
                    page.keyboard.press("Enter")
                except Exception:
                    pass
            vend = time.time() + 4
            while time.time() < vend:
                if self._submitted(page, before_count):
                    return
                page.wait_for_timeout(400)
        raise GeminiError(
            "提示词已输入但多次尝试都没能发送出去（发送按钮点击未生效）。已自动重试。")

    RELOAD_INTERVAL = 90
    STUCK_CEILING = 180

    def _raise_if_cancelled(self):
        """协作式取消(#6b)：用户点「提前结束」→ 立即抛 GenCancelled 中止当前等待。"""
        if self.cancel is not None and self.cancel.is_set():
            raise GenCancelled("用户提前结束，已中止当前 Gemini 等待。")

    def _wait_reply_done(self, page, before_count: int, timeout: int, expect_image: bool):
        deadline = time.time() + timeout
        last_activity = time.time()
        last_reload = time.time()

        def reload_page(reason: str):
            nonlocal last_activity, last_reload
            self.log(f"{reason}，自动刷新 Gemini 页面重新检查…")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            last_activity = time.time()
            last_reload = time.time()

        def force_ceiling() -> bool:
            if (expect_image and self._last_image_handle(page) is None
                    and time.time() - last_reload > self.STUCK_CEILING):
                reload_page(f"生图已超过 {self.STUCK_CEILING}s 仍未出图，强制刷新排除页面假死")
                return True
            return False

        def check_nudge() -> bool:
            if self.nudge and self.nudge.is_set():
                self.nudge.clear()
                reload_page("收到人工干预信号")
                return True
            return False

        def is_streaming() -> bool:
            try:
                return page.locator(SEL["stop"]).first.is_visible()
            except Exception:
                return False

        # 阶段一：等新的模型回复出现
        while time.time() < deadline:
            self._raise_if_cancelled()   # 用户提前结束 → 立即中止(#6b)
            if page.locator(SEL["assistant"]).count() > before_count:
                break
            if expect_image and self._last_image_handle(page) is not None:
                return
            if is_streaming():
                last_activity = time.time()
            check_nudge()
            if time.time() - last_activity > self.RELOAD_INTERVAL:
                reload_page("回复迟迟未出现，页面可能卡住")
            else:
                force_ceiling()
            page.wait_for_timeout(1000)
        else:
            raise GeminiError(f"等了 {timeout}s 没有等到回复开始，请看 Chrome 里是否有异常弹窗。")

        # 阶段二：等生成结束（停止按钮消失并保持消失）
        quiet = 0
        while time.time() < deadline:
            self._raise_if_cancelled()   # 用户提前结束 → 立即中止(#6b)
            if check_nudge():
                quiet = 0
            if expect_image and self._last_image_handle(page) is not None:
                return
            if is_streaming():
                quiet = 0
                last_activity = time.time()
            else:
                quiet += 1
                need = 8 if expect_image else 3
                if quiet >= need:
                    if not expect_image or self._last_image_handle(page) is not None:
                        return
                    if time.time() - last_activity > self.RELOAD_INTERVAL:
                        reload_page("生成似乎结束但图片没出现，页面可能假死")
                        quiet = 0
            if force_ceiling():
                quiet = 0
            page.wait_for_timeout(1000)
        if expect_image:
            raise GeminiError(f"等了 {timeout}s 图片仍未生成完成（可能额度用尽或排队），请到 Chrome 里确认。")

    # ---------- 读回复 / 下载图 ----------

    def last_reply_text(self, page) -> str:
        msgs = page.locator(SEL["assistant"])
        if msgs.count() == 0:
            return ""
        try:
            return msgs.last.inner_text()
        except Exception:
            return ""

    def _last_image_handle(self, page):
        """找 nano-banana 生成图。**关键**：Gemini 里用户上传的底图和模型生成图都是大 <img>，
        必须排除上传预览（alt=所上传图片的预览图 / img.preview-image / user-query-file-preview 内），
        只认模型生成图（alt 含 'AI 生成'，容器 generated-image/single-image）。"""
        # 首选：明确的生成图容器（已对实时页面确认）
        loc = page.locator(SEL["gen_image"])
        n = loc.count()
        if n:
            h = loc.nth(n - 1)         # 最后一个 = 最新一次生成
            try:
                d = h.evaluate("el => ({w: el.naturalWidth, h: el.naturalHeight})")
                if d["w"] >= 256 and d["h"] >= 256:
                    return h
            except Exception:
                pass
        # 兜底：扫所有大图，显式排除「上传预览」
        best, best_score = None, 0
        imgs = page.locator("img")
        for i in range(imgs.count()):
            h = imgs.nth(i)
            try:
                d = h.evaluate(
                    """el => ({
                        w: el.naturalWidth, h: el.naturalHeight,
                        alt: el.alt || '',
                        up: !!el.closest('user-query-file-preview')
                            || (typeof el.className==='string' && el.className.includes('preview-image')),
                        y: el.getBoundingClientRect().top
                    })""")
                if d["up"] or d["alt"] == "所上传图片的预览图":
                    continue
                if d["w"] < 256 or d["h"] < 256:
                    continue
                score = d["w"] * d["h"] + max(0, d["y"]) * 1000
                if score > best_score:
                    best, best_score = h, score
            except Exception:
                continue
        return best

    def download_last_image(self, page, save_path: str) -> bool:
        """把最后一条回复里的生成图存到本地。fetch 失败时用 canvas 兜底。"""
        handle = self._last_image_handle(page)
        if handle is None:
            return False
        data_url = handle.evaluate(
            """async el => {
                try {
                    const r = await fetch(el.src);
                    const b = await r.blob();
                    return await new Promise(res => {
                        const fr = new FileReader();
                        fr.onload = () => res(fr.result);
                        fr.readAsDataURL(b);
                    });
                } catch (e) {
                    const c = document.createElement('canvas');
                    c.width = el.naturalWidth; c.height = el.naturalHeight;
                    c.getContext('2d').drawImage(el, 0, 0);
                    return c.toDataURL('image/png');
                }
            }"""
        )
        if not data_url or "," not in data_url:
            return False
        raw = base64.b64decode(data_url.split(",", 1)[1])
        if len(raw) < 10000:
            return False
        with open(save_path, "wb") as f:
            f.write(raw)
        return True
