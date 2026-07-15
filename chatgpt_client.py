# -*- coding: utf-8 -*-
"""
ChatGPT 网页驱动：通过 CDP 接管一个已登录的 Chrome，
在真实页面里发消息、传图、等回复、下载生成图。

前提：Chrome 以 --remote-debugging-port=9222 启动（用 start_chrome.bat），
并且该 Chrome 里已登录 chatgpt.com。

页面结构随 ChatGPT 改版可能变化，所有选择器集中在 SEL 里便于修补。
"""
import base64
import time

from playwright.sync_api import sync_playwright

CDP_PORT = 9333  # 用冷门端口，避免和其他调试工具抢默认的 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
CHATGPT_URL = "https://chatgpt.com/"

SEL = {
    "editor": "#prompt-textarea",
    "send": 'button[data-testid="send-button"], #composer-submit-button, '
            'button[aria-label*="发送"], button[aria-label*="Send"]',
    "stop": 'button[data-testid="stop-button"], '
            'button[aria-label*="停止"], button[aria-label*="Stop"]',
    "assistant": '[data-message-author-role="assistant"]',
    "file_input": 'input[type="file"]',
}

TEXT_TIMEOUT = 300      # 纯文本回复最长等待（秒）
IMAGE_TIMEOUT = 600     # 生图最长等待（秒）


class ChatGPTError(RuntimeError):
    pass


class GenStalledError(ChatGPTError):
    """生图经过多次自愈（刷新/新开对话/重连）仍未出图。

    与普通 ChatGPTError 的区别：这是**可恢复**的——上层应把会话停在"待重试"
    状态而不是判定失败结束，用户点一下即可再战。对应需求③/⑦：会话绝不能结束。
    """


class GenCancelled(ChatGPTError):
    """用户点了「提前结束」（#6b）——应**立即**中止当前等待：不重试、不算错误，
    交由上层正常收尾（输出已完成的最后一张成品）。协作式取消，2 秒内响应。"""


class ChatGPTClient:
    def __init__(self, cdp_url: str = CDP_URL, log=print, nudge=None, cancel=None):
        self.cdp_url = cdp_url
        self.log = log
        self.cancel = cancel  # threading.Event：用户点「提前结束」时置位，等待循环即时中止(#6b)
        self.nudge = nudge  # threading.Event：用户点"人工干预"按钮时置位
        self._pw = None
        self._owns_pw = True        # 是否由本 client 创建/负责关闭 playwright（gemini 共用时为 False）
        self._browser = None
        self._ctx = None
        self._director_only = False
        self.director_page = None   # 导演对话：全程一个会话
        self.gen_page = None        # 生成对话：每轮新开会话

    # ---------- 连接与页面管理 ----------

    def connect(self, director_only: bool = False, pw=None):
        """pw：可传入一个已启动的 sync_playwright（与 GeminiClient 共用）。
        同一线程只能有一个 sync_playwright 实例，两个 client 接管同一个 Chrome 时必须共用，
        否则第二个 .start() 会抛「Playwright Sync API inside the asyncio loop」。"""
        self._director_only = director_only
        self._owns_pw = pw is None
        self._pw = pw or sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception as e:
            raise ChatGPTError(
                f"连不上 Chrome 调试端口({self.cdp_url})。请先运行 start_chrome.bat "
                f"并在弹出的 Chrome 里登录 chatgpt.com。原始错误：{e}"
            )
        if not self._browser.contexts:
            raise ChatGPTError(f"{CDP_PORT} 端口上的浏览器没有可用上下文——"
                               "可能被其他调试程序占用，请关掉后用 start_chrome.bat 重启。")
        self._ctx = self._browser.contexts[0]
        try:
            self.director_page = self._ctx.new_page()
            if not director_only:
                self.gen_page = self._ctx.new_page()
        except Exception as e:
            raise ChatGPTError(f"无法在被接管的浏览器里开新页面——{CDP_PORT} 端口可能被"
                               f"其他程序（而非专用 Chrome）占用。原始错误：{e}")
        self._open_chat(self.director_page)
        self._check_logged_in(self.director_page)
        if not director_only:
            self._open_chat(self.gen_page)  # 立即导航，别留一个吓人的 about:blank
        self.log("已接管 Chrome，ChatGPT 登录状态正常。可以把专用 Chrome 最小化，回操作页面看进度。")

    def _page_alive(self, page) -> bool:
        """页面/上下文/浏览器是否还活着（一次极廉价的 eval 探活）。"""
        if page is None:
            return False
        try:
            page.evaluate("1")
            return True
        except Exception:
            return False

    def _reconnect(self):
        """整体重连：CDP 断开 / 标签被关（Target page/context/browser closed）时的兜底。

        重建 pw→browser→context→pages。注意：导演对话页会因此丢失原有对话上下文——
        这是硬崩溃下的无奈代价，但比整个任务结束要好；仅在页面确实死掉时才走这条路。
        """
        self.log("检测到浏览器/页面已断开，正在重连专用 Chrome 并重开页面…")
        # 不 stop 再 start playwright：可能与 GeminiClient 共用同一个 pw，停掉会连累对方，
        # 且同一线程无法再起第二个 sync_playwright。CDP 断开只需重新 connect_over_cdp 拿新 browser。
        if self._pw is None:
            self._pw = sync_playwright().start()
            self._owns_pw = True
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        if not self._browser.contexts:
            raise ChatGPTError("重连后浏览器没有可用上下文——请检查专用 Chrome 是否还开着。")
        self._ctx = self._browser.contexts[0]
        self.director_page = self._ctx.new_page()
        self._open_chat(self.director_page)
        if not self._director_only:
            self.gen_page = self._ctx.new_page()
            self._open_chat(self.gen_page)
        self.log("已重连 ChatGPT，继续任务。")

    def _current_page(self, role: str):
        """按角色取当前页（重连后引用会变，始终以 self.* 为准）。"""
        return self.gen_page if role == "gen" else self.director_page

    def _raise_if_cancelled(self):
        """协作式取消(#6b)：用户点「提前结束」→ 立即抛 GenCancelled 中止当前等待，
        不重试、不算错误。所有可能长时间阻塞的循环都要调它，才能做到 2 秒内响应。"""
        if self.cancel is not None and self.cancel.is_set():
            raise GenCancelled("用户提前结束，已中止当前 ChatGPT 等待。")

    def _recover_before_retry(self, role: str, attempt: int, max_attempts: int,
                              expect_image: bool, force_reconnect: bool = False):
        """一次自愈：页面死了就整体重连；否则——生图开新对话（新标签重发），
        文本只刷新（保住导演对话上下文，绝不新开对话）。对应需求：开新页面 + 重试结合。"""
        kind = "生图" if expect_image else "文本"
        self.log(f"{kind}这一步没成功，自动干预后重试（第 {attempt + 1}/{max_attempts} 次）…")
        page = self._current_page(role)
        if force_reconnect or not self._page_alive(page):
            try:
                self._reconnect()
                return
            except Exception as e:
                self.log(f"重连失败（{e}），改为刷新页面再试一次。")
                page = self._current_page(role)
        try:
            if role == "gen":
                # 第一次卡死换新标签救；换标签还不行（attempt>=2）→ 关掉所有页重开
                # （需求#5：同页无限刷新救不活时，自动关掉所有 ChatGPT 页再开新的，而不是干等/堆标签）。
                if attempt >= 2:
                    self.close_all_and_reopen_gen()
                else:
                    self.new_generation_chat()  # 生图：换个干净的新对话重发，救活假死的标签
            elif page is not None:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
        except Exception:
            pass

    def close(self):
        try:
            if self._pw and self._owns_pw:   # 只有创建者才关，避免关掉与 Gemini 共用的 pw
                self._pw.stop()
        except Exception:
            pass

    def _open_chat(self, page):
        page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

    def _check_logged_in(self, page):
        try:
            page.wait_for_selector(SEL["editor"], timeout=20000)
        except Exception:
            raise ChatGPTError(
                "ChatGPT 页面上找不到输入框——多半是未登录或弹了验证。"
                "请到那个 Chrome 窗口里登录/处理后重试。"
            )

    def new_director_chat(self):
        self._open_chat(self.director_page)

    def new_generation_chat(self):
        """每轮生成都换一个**全新标签页**再导航——旧标签生成一两张后 ChatGPT 常
        连接重置/假死（用户实测：一个窗口约 2 张图就开始报错）。换新标签最干净。
        瞬时错误自动换标签重试；彻底失败抛 GenStalledError（可恢复，不结束会话）。"""
        old = self.gen_page
        self.gen_page = self._open_fresh_gen_chat()
        if old is not None and old is not self.gen_page:
            try:
                old.close()   # 关掉用旧了的标签，避免标签堆积
            except Exception:
                pass

    def new_generation_window(self):
        """比换标签更狠一档：另开一个**真·新浏览器窗口**再导航。用于生图反复卡死、
        换新标签也救不活（整窗假死）时——对应需求：卡死几分钟干预不成功就直接开新窗户。"""
        self.log("换新标签仍未出图，改为**另开一个新窗口**重试…")
        old = self.gen_page
        self.gen_page = self._open_fresh_gen_window()
        if old is not None and old is not self.gen_page:
            try:
                old.close()
            except Exception:
                pass

    def close_all_and_reopen_gen(self):
        """需求#5：生图反复卡死时的最狠兜底——关掉当前浏览器上下文里**所有** ChatGPT 页，
        再重开干净的导演页 + 生图页。专治"同一标签无限刷新救不活 / 多个假死标签堆积"的死循环，
        比"换新标签/新窗口"彻底（那两个会把旧的坏标签留在原地继续堆）。
        代价：导演对话上下文会重置——但这是死循环下的可接受取舍，功能不中断优先。"""
        self.log("生图反复卡死——关闭所有 ChatGPT 页、重开干净页面重试（#5 关页重开兜底）…")
        try:
            pages = list(self._ctx.pages)
        except Exception:
            self._reconnect()   # 上下文都没了 → 整体重连
            return
        for p in pages:
            try:
                p.close()
            except Exception:
                pass
        try:
            self.director_page = self._ctx.new_page()
            self._open_chat(self.director_page)
            if not self._director_only:
                self.gen_page = self._ctx.new_page()
                self._open_chat(self.gen_page)
        except Exception as e:
            self.log(f"关页后重开失败（{str(e)[:70]}），改为整体重连。")
            self._reconnect()

    def _alive_opener(self):
        """找一个还活着的页面当 window.open 的发起者；都死了返回 None。"""
        for p in (self.director_page, self.gen_page):
            if self._page_alive(p):
                return p
        try:
            for p in self._ctx.pages:
                if self._page_alive(p):
                    return p
        except Exception:
            pass
        return None

    def _open_fresh_gen_window(self, tries: int = 2):
        """用一个活着的页面 window.open 出一个新窗口并导航到 ChatGPT 新对话。
        开窗失败退回新标签逻辑；页面全死则整体重连。"""
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
                        "() => window.open('" + CHATGPT_URL + "','_blank','width=1400,height=1000')")
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
        """开一个全新标签页并导航到 ChatGPT 新对话。ERR_CONNECTION_RESET 等瞬时错误
        自动换新标签重试；上下文都没了则整体重连；全失败抛 GenStalledError。"""
        last = None
        for i in range(tries):
            try:
                page = self._ctx.new_page()
            except Exception as e:               # 上下文/浏览器没了 → 整体重连，用重连后的 gen_page
                last = e
                try:
                    self._reconnect()
                    return self.gen_page
                except Exception as e2:
                    last = e2
                    time.sleep(1.5)
                    continue
            try:
                page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                return page
            except Exception as e:
                last = e
                self.log(f"打开 ChatGPT 新对话失败（{str(e)[:70]}），换个新标签重试（{i + 1}/{tries}）…")
                try:
                    page.close()
                except Exception:
                    pass
                time.sleep(1.5)
        raise GenStalledError(
            f"多次开 ChatGPT 新对话都连接失败（{last}）——已暂停但未结束，可点「刷新 / 重试本轮」再试，"
            "或看专用 Chrome 是否断网/被限速。")

    # ---------- 发消息 ----------

    def send(self, page, text: str, image_paths=None, expect_image=False) -> str:
        """发一条消息（可带图），阻塞等回复完成，返回回复文本。自愈式重试。

        无论文本还是生图，等不到回复都会自动干预后重试（默认 3 次）：
          · 页面/浏览器死了（Target page/context/browser closed）→ 整体重连；
          · 生图卡死 → 换一个新对话重发（救活假死的标签，代价是重复扣额度，用户已认可）；
          · 文本卡死 → 只刷新页面重发（保住导演对话上下文，绝不新开对话）。
        生图 3 次自愈仍不出图 → 抛 GenStalledError，上层停在"待重试"而非结束会话。
        """
        image_paths = image_paths or []
        timeout = IMAGE_TIMEOUT if expect_image else TEXT_TIMEOUT
        max_attempts = 3
        # 角色决定自愈方式：gen 可开新对话重发，director 必须保住上下文只刷新
        role = "gen" if page is self.gen_page else "director"
        last_err = None

        for attempt in range(1, max_attempts + 1):
            self._raise_if_cancelled()       # 尝试之间也响应提前结束(#6b)
            page = self._current_page(role)  # 重连后引用会变，每次都取最新的
            try:
                before = page.locator(SEL["assistant"]).count()
                if image_paths:
                    self._attach_files(page, image_paths)
                editor = page.locator(SEL["editor"])
                editor.click()
                page.keyboard.insert_text(text)
                page.wait_for_timeout(500)
                self._click_send(page, before)
                self._wait_reply_done(page, before, timeout, expect_image)
                return self.last_reply_text(page)
            except GenCancelled:
                raise                        # 提前结束：不重试、不吞，直接上抛让上层收尾(#6b)
            except ChatGPTError as e:
                last_err = e
                if attempt < max_attempts:
                    self._recover_before_retry(role, attempt, max_attempts, expect_image)
            except Exception as e:
                # Playwright 抛的非 ChatGPTError（标签被关、CDP 断开等）→ 强制重连再试
                last_err = ChatGPTError(f"页面操作异常：{e}")
                if attempt < max_attempts:
                    self._recover_before_retry(role, attempt, max_attempts, expect_image,
                                               force_reconnect=True)
        if expect_image:
            raise GenStalledError(
                f"生图连续 {max_attempts} 次自愈仍未出图（{last_err}）。可能额度用尽或排队——"
                "任务已暂停但未结束，可点「刷新 ChatGPT / 重试本轮」再试。")
        raise last_err

    def _attach_files(self, page, paths):
        inputs = page.locator(SEL["file_input"])
        if inputs.count() == 0:
            raise ChatGPTError("页面上找不到文件上传入口(input[type=file])，可能界面改版了。")
        inputs.first.set_input_files(paths)
        # 等上传处理完：发送按钮从禁用变为可用
        deadline = time.time() + 120
        while time.time() < deadline:
            self._raise_if_cancelled()   # 上传可能等 2 分钟，也要能被提前结束打断(#6b)
            btn = page.locator(SEL["send"]).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    return
            except Exception:
                pass
            page.wait_for_timeout(1000)
        raise ChatGPTError("图片上传后 2 分钟内发送按钮仍不可用，上传可能失败。")

    def _editor_text(self, page) -> str:
        try:
            return (page.locator(SEL["editor"]).first.inner_text() or "").strip()
        except Exception:
            return ""

    def _submitted(self, page, before_count: int) -> bool:
        """判断提示词是否真的发出去了：输入框已清空 / 出现停止按钮 / 新回复出现，任一即算。
        （关键：过去只点一次不验证，点空了也照样去等回复→无限刷新空等。）"""
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
        """发送并**确认发送生效**：点按钮 → 验证；没生效就换招（回车/再点）重试。
        真发不出去才抛错，让上层自愈——而不是傻等一个从没发出去的回复。"""
        # 1) 等发送按钮从禁用变可用（打字后 React 需要一点时间才 enable）
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                btn = page.locator(SEL["send"]).first
                if btn.is_visible() and btn.is_enabled():
                    break
            except Exception:
                pass
            page.wait_for_timeout(300)
        # 2) 多策略尝试提交，每次后验证是否真的发出去了
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
        raise ChatGPTError(
            "提示词已输入但多次尝试都没能发送出去（发送按钮点击未生效）。已自动重试。")

    RELOAD_INTERVAL = 90   # 页面无动静（非流式）超过这个秒数就自动刷新（ChatGPT 网页时不时假死）
    STUCK_CEILING = 180    # 生图即使一直显示"生成中"，超过这个秒数仍没出图也强制刷新一次——
                           # 破解"页面一直转圈假思考、自动刷新永不触发"导致干等到总超时的假死。
    AUTO_RELOAD_CAP = 1    # 同一坏死标签最多"就地自动刷新"这么多次；再卡就升级为「关掉所有页重开」(#5)——
                           # 破解"对中毒标签每 90s 刷一次、磨完 600s 才升级"造成的无限刷新死循环。

    def _wait_reply_done(self, page, before_count: int, timeout: int, expect_image: bool):
        deadline = time.time() + timeout
        last_activity = time.time()
        last_reload = time.time()   # 上次刷新/本步开始的时刻；**不被流式指示重置**，专供强制上限用
        auto_reloads = 0            # 自动"卡死刷新"次数；超过 AUTO_RELOAD_CAP 就抛错让上层关页重开(#5)

        def reload_page(reason: str):
            nonlocal last_activity, last_reload
            self.log(f"{reason}，自动刷新 ChatGPT 页面重新检查…")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            last_activity = time.time()
            last_reload = time.time()

        def stuck_escalate(reason: str):
            """自动卡死兜底：同一坏死标签先就地刷新一次；再卡（超过 AUTO_RELOAD_CAP）就抛错，
            让上层 send() 走到「关掉所有 ChatGPT 页重开」(#5)，而不是对中毒标签无限刷新。"""
            nonlocal auto_reloads
            if auto_reloads >= self.AUTO_RELOAD_CAP:
                raise ChatGPTError(
                    f"{reason}：同页自动刷新 {auto_reloads} 次仍无进展，需关闭所有 ChatGPT 页重开。")
            auto_reloads += 1
            reload_page(reason)

        def force_ceiling() -> bool:
            """生图即使页面一直"生成中"，超过 STUCK_CEILING 秒仍没出图就强制干预一次。
            这条不看 is_streaming（转圈也照样干预），是真正的"卡死自动干预"兜底。"""
            if (expect_image and self._last_image_handle(page) is None
                    and time.time() - last_reload > self.STUCK_CEILING):
                stuck_escalate(f"生图已超过 {self.STUCK_CEILING}s 仍未出图，排除页面假死")
                return True
            return False

        def check_nudge() -> bool:
            # 人工干预=用户给了一次全新机会：重置自动刷新计数，只就地刷新、不升级
            nonlocal auto_reloads
            if self.nudge and self.nudge.is_set():
                self.nudge.clear()
                auto_reloads = 0
                reload_page("收到人工干预信号")
                return True
            return False

        def is_streaming() -> bool:
            try:
                return page.locator(SEL["stop"]).first.is_visible()
            except Exception:
                return False

        # 阶段一：等新的助手消息出现
        while time.time() < deadline:
            self._raise_if_cancelled()   # 用户提前结束 → 立即中止(#6b)
            if page.locator(SEL["assistant"]).count() > before_count:
                break
            if expect_image and self._last_image_handle(page) is not None:
                return
            if is_streaming():
                last_activity = time.time()  # 在思考/输出中，不算卡死
            check_nudge()
            if time.time() - last_activity > self.RELOAD_INTERVAL:
                stuck_escalate("回复迟迟未出现，页面可能卡住")
            else:
                force_ceiling()   # 生图转圈假死的强制上限（不看 is_streaming）
            page.wait_for_timeout(1000)
        else:
            raise ChatGPTError(f"等了 {timeout}s 没有等到回复开始，请看 Chrome 里是否有异常弹窗。")

        # 阶段二：等流式输出/生图结束：停止按钮消失并保持消失
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
                need = 8 if expect_image else 3  # 生图有分段渲染，多等几拍
                if quiet >= need:
                    if expect_image:
                        if self._last_image_handle(page) is not None:
                            return
                        # 输出停了却没抓到图：先看是不是图还在解码（naturalWidth=0）——是则继续等它
                        # load 完，别急着刷新（假死误判的常见来源）。真没图再走原来的刷新兜底。
                        if self._image_loading_pending(page):
                            last_activity = time.time()
                        elif time.time() - last_activity > self.RELOAD_INTERVAL:
                            stuck_escalate("生成似乎结束但图片没出现，页面可能假死")
                            quiet = 0
                    else:
                        # 文本：流式停了，但必须**真的有文字**才算完成。空文本几乎都是
                        # "助手容器已建、内容还没渲染进来"的竞态——导演首轮带图上传尤其常见。
                        # 若此时返回空串，上层会判成"英文提示词偏短/缺失（空）"(Image#9)。
                        # 所以空就继续等；久久为空再刷新，绝不返回空。
                        if self.last_reply_text(page).strip():
                            return
                        quiet = 0
                        if time.time() - last_activity > self.RELOAD_INTERVAL:
                            stuck_escalate("回复容器已出现但文字始终为空，页面可能假死")
            if force_ceiling():   # 一直"生成中"转圈也照样兜底强制刷新
                quiet = 0
            page.wait_for_timeout(1000)
        if expect_image:
            raise ChatGPTError(f"等了 {timeout}s 图片仍未生成完成（可能额度用尽或排队），请到 Chrome 里确认。")
        # 文本：走到这里=超时仍没拿到非空回复 → 抛错让 send() 自愈重试，绝不返回空串
        # （空串会被上层当成"提示词缺失"，是 Image#9 报错的根）。
        if not self.last_reply_text(page).strip():
            raise ChatGPTError(f"等了 {timeout}s 助手回复仍为空（网页可能假死或未真正生成），已自动重试。")

    # ---------- 读回复 ----------

    def last_reply_text(self, page) -> str:
        msgs = page.locator(SEL["assistant"])
        if msgs.count() == 0:
            return ""
        return msgs.last.inner_text()

    def _last_image_handle(self, page):
        """找生成图。

        ChatGPT 生图结果有时不挂在 data-message-author-role=assistant 容器下，
        而是独立的图片卡片；因此先查最后一条助手消息，查不到再扫描页面可见大图。
        """
        best, best_area = None, 0

        def consider(imgs, require_generated_alt=False):
            nonlocal best, best_area
            for i in range(imgs.count()):
                h = imgs.nth(i)
                try:
                    dims = h.evaluate(
                        """el => ({
                            w: el.naturalWidth,
                            h: el.naturalHeight,
                            cw: el.clientWidth,
                            ch: el.clientHeight,
                            alt: el.alt || "",
                            role: el.closest("[data-message-author-role]")?.getAttribute("data-message-author-role") || "",
                            y: el.getBoundingClientRect().y
                        })"""
                    )
                    if dims["role"] == "user":
                        continue
                    alt = dims["alt"].lower()
                    if require_generated_alt and "生成" not in alt and "generated" not in alt:
                        continue
                    area = dims["w"] * dims["h"]
                    visible_area = dims["cw"] * dims["ch"]
                    if dims["w"] < 256 or dims["h"] < 256 or visible_area < 40000:
                        continue
                    # 聊天历史里可能有旧图；优先页面较靠下、面积较大的可见生成图。
                    score = area + max(0, dims["y"]) * 1000
                    if score > best_area:
                        best, best_area = h, score
                except Exception:
                    continue

        msgs = page.locator(SEL["assistant"])
        if msgs.count():
            consider(msgs.last.locator("img"))
        if best is None:
            consider(page.locator('img[alt*="生成"], img[alt*="generated" i]'),
                     require_generated_alt=True)
        if best is None:
            consider(page.locator("img"))
        return best

    def _image_loading_pending(self, page) -> bool:
        """生成流已停，但最后一条助手消息（或带「生成」alt 的图）里存在 <img> 却尚未加载完成
        （complete=false 或 naturalWidth=0）。这是「假死」误判的常见来源：图其实在、只是还没
        解码好。返回 True 时应继续等它 load 完，别急着刷新把已到的图刷掉。"""
        try:
            return bool(page.evaluate(
                """() => {
                    const notLoaded = el => {
                        const src = el.currentSrc || el.src || '';
                        return src && (!el.complete || el.naturalWidth === 0);
                    };
                    const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
                    if (msgs.length) {
                        for (const el of msgs[msgs.length - 1].querySelectorAll('img')) {
                            if (notLoaded(el)) return true;
                        }
                    }
                    for (const el of document.querySelectorAll('img[alt*="生成"], img[alt*="generated" i]')) {
                        if (el.closest('[data-message-author-role="user"]')) continue;
                        if (notLoaded(el)) return true;
                    }
                    return false;
                }"""))
        except Exception:
            return False

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
        if len(raw) < 10000:  # 太小说明抓到的是图标/占位图
            return False
        with open(save_path, "wb") as f:
            f.write(raw)
        return True
