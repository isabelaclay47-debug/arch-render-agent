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


class ChatGPTClient:
    def __init__(self, cdp_url: str = CDP_URL, log=print, nudge=None):
        self.cdp_url = cdp_url
        self.log = log
        self.nudge = nudge  # threading.Event：用户点"人工干预"按钮时置位
        self._pw = None
        self._browser = None
        self._ctx = None
        self.director_page = None   # 导演对话：全程一个会话
        self.gen_page = None        # 生成对话：每轮新开会话

    # ---------- 连接与页面管理 ----------

    def connect(self):
        self._pw = sync_playwright().start()
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
            self.gen_page = self._ctx.new_page()
        except Exception as e:
            raise ChatGPTError(f"无法在被接管的浏览器里开新页面——{CDP_PORT} 端口可能被"
                               f"其他程序（而非专用 Chrome）占用。原始错误：{e}")
        self._open_chat(self.director_page)
        self._check_logged_in(self.director_page)
        self._open_chat(self.gen_page)  # 立即导航，别留一个吓人的 about:blank
        self.log("已接管 Chrome，ChatGPT 登录状态正常。可以把专用 Chrome 最小化，回操作页面看进度。")

    def close(self):
        try:
            if self._pw:
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
        self._open_chat(self.gen_page)

    # ---------- 发消息 ----------

    def send(self, page, text: str, image_paths=None, expect_image=False) -> str:
        """发一条消息（可带图），阻塞等回复完成，返回回复文本。

        文本步骤（导演对话）等不到回复时会自动"刷新+重发"，因为最常见的失败是
        消息压根没发出去（发送按钮没触发/被弹窗挡住），重发不消耗生图额度、能救回大多数卡死；
        生图步骤重发会重复扣额度，只尝试一次。
        """
        image_paths = image_paths or []
        timeout = IMAGE_TIMEOUT if expect_image else TEXT_TIMEOUT
        max_attempts = 1 if expect_image else 3
        last_err = None

        for attempt in range(1, max_attempts + 1):
            before = page.locator(SEL["assistant"]).count()
            if image_paths:
                self._attach_files(page, image_paths)
            editor = page.locator(SEL["editor"])
            editor.click()
            page.keyboard.insert_text(text)
            page.wait_for_timeout(500)
            self._click_send(page)
            try:
                self._wait_reply_done(page, before, timeout, expect_image)
                return self.last_reply_text(page)
            except ChatGPTError as e:
                last_err = e
                if attempt < max_attempts:
                    self.log(f"这一步 {timeout}s 没等到回复（多半消息没发出去），"
                             f"刷新页面后重发（第 {attempt + 1}/{max_attempts} 次）…")
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)
        raise last_err

    def _attach_files(self, page, paths):
        inputs = page.locator(SEL["file_input"])
        if inputs.count() == 0:
            raise ChatGPTError("页面上找不到文件上传入口(input[type=file])，可能界面改版了。")
        inputs.first.set_input_files(paths)
        # 等上传处理完：发送按钮从禁用变为可用
        deadline = time.time() + 120
        while time.time() < deadline:
            btn = page.locator(SEL["send"]).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    return
            except Exception:
                pass
            page.wait_for_timeout(1000)
        raise ChatGPTError("图片上传后 2 分钟内发送按钮仍不可用，上传可能失败。")

    def _click_send(self, page):
        btn = page.locator(SEL["send"]).first
        try:
            if btn.is_visible() and btn.is_enabled():
                btn.click()
                return
        except Exception:
            pass
        page.keyboard.press("Enter")  # 兜底

    RELOAD_INTERVAL = 90  # 页面无动静超过这个秒数就自动刷新（ChatGPT 网页时不时假死）

    def _wait_reply_done(self, page, before_count: int, timeout: int, expect_image: bool):
        deadline = time.time() + timeout
        last_activity = time.time()

        def reload_page(reason: str):
            nonlocal last_activity
            self.log(f"{reason}，自动刷新 ChatGPT 页面重新检查…")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            last_activity = time.time()

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

        # 阶段一：等新的助手消息出现
        while time.time() < deadline:
            if page.locator(SEL["assistant"]).count() > before_count:
                break
            if expect_image and self._last_image_handle(page) is not None:
                return
            if is_streaming():
                last_activity = time.time()  # 在思考/输出中，不算卡死
            check_nudge()
            if time.time() - last_activity > self.RELOAD_INTERVAL:
                reload_page("回复迟迟未出现，页面可能卡住")
            page.wait_for_timeout(1000)
        else:
            raise ChatGPTError(f"等了 {timeout}s 没有等到回复开始，请看 Chrome 里是否有异常弹窗。")

        # 阶段二：等流式输出/生图结束：停止按钮消失并保持消失
        quiet = 0
        while time.time() < deadline:
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
                    if not expect_image or self._last_image_handle(page) is not None:
                        return
                    # 输出停了却没有图——典型的网页假死，刷新一下图往往就出来了
                    if time.time() - last_activity > self.RELOAD_INTERVAL:
                        reload_page("生成似乎结束但图片没出现，页面可能假死")
                        quiet = 0
            page.wait_for_timeout(1000)
        if expect_image:
            raise ChatGPTError(f"等了 {timeout}s 图片仍未生成完成（可能额度用尽或排队），请到 Chrome 里确认。")

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
