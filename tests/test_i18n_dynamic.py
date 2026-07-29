# -*- coding: utf-8 -*-
"""Bug2「英文版要全方位」：JS 动态渲染的中文（结果卡标签 + 状态日志）必须能翻成英文。

test_i18n.py 只扫**静态 HTML**（跳过 <script>），覆盖不到运行时由 JS 拼出来的结果卡、
以及后端 log() 推到状态面板的中文（Image#4/#5 里露的就是这些）。此处用一个**复刻
translateCore（EXACT→DYNAMIC→PHRASES 拼接→残留汉字判泄漏）** 的迷你模拟器，对一批真实
运行时字符串断言"切 EN 后不残留中文"，锁死已修好的泄漏点不再回归。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
HAN = re.compile(r"[㐀-鿿]")


def _build():
    exact = {}
    ex = JS[JS.index("const EXACT"):JS.index("const DYNAMIC")]
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', ex):
        k = m.group(1).replace('\\"', '"').replace('\\\\', '\\')
        if HAN.search(k):
            exact[k] = m.group(2)
    dyn = []
    db = JS[JS.index("const DYNAMIC"):JS.index("const PHRASES")]
    for m in re.finditer(r'\[\/(.+?)\/,', db):
        try:
            dyn.append(re.compile(m.group(1).replace('\\/', '/')))
        except re.error:
            pass
    phrases = sorted((k for k in exact if HAN.search(k)), key=len, reverse=True)
    return exact, dyn, phrases


EXACT, DYN, PHRASES = _build()


def _translate_core(value):
    """复刻 static/i18n.js 的 translateCore（够用即可：判断是否还残留中文）。"""
    if not value or not HAN.search(value):
        return value
    n = re.sub(r"\s+", " ", value).strip()
    if n in EXACT:
        return EXACT[n]
    for p in DYN:
        if p.match(n):
            return "<dynamic-ok>"
    out = n
    for src in PHRASES:
        if src in out:
            out = out.replace(src, EXACT[src])
    return out   # 若仍含中文即视为泄漏


def _leaks(s):
    """模拟 t()：按行翻译，任一行译后仍残留中文即算泄漏。"""
    for line in s.split("\n"):
        core = line.strip()
        if HAN.search(core) and HAN.search(_translate_core(core)):
            return True
    return False


# 真实运行时串（含占位处用真实样例值），全部必须能翻译干净
RUNTIME_STRINGS = [
    # —— 结果卡（Image#5 露的「本轮后的提示词」就在这）——
    "本轮后的提示词",
    "本轮的修改指令",
    "（未解析出分析内容）",
    "（未按标准格式返回，以下为导演原始回复）",
    "第 3 轮 · 自动迭代",
    "第 2 轮 · 局部修改",
    # —— 检查结果摘要状态灯（新增：卡片顶部一眼看到本轮结论）——
    "明显篡改 · 严重×1 中等×2",
    "需精修 · 中等×2 轻微×3",
    "小瑕疵 · 轻微×1",
    "检查通过",
    "检查未完成",
    "已检查",
    # —— 状态日志：启动 / 引擎 / 模型（Image#4 露的「无需切换」在这）——
    "生图引擎：Gemini 全包——理解/提示词/查篡改/翻译与生图都由 Gemini 完成，全程不启动 ChatGPT。",
    "生图引擎：Gemini（nano-banana）生图；ChatGPT 只做文本推理（理解/提示词/查篡改）。",
    "已接管 Chrome，Gemini 全包：一个页做导演文字推理、一个页专门生图，全程不启动 ChatGPT。",
    "已接管 Chrome，Gemini（nano-banana）登录状态正常，用于生图。",
    "Gemini 已是「3.1 Pro」，无需切换。",
    "已在 Gemini 网页切到模型「2.5 Pro」。",
    "没找到 Gemini 模型切换按钮——请在输入框右侧的模型按钮手动切到「3.1 Pro」再继续。",
    # —— 状态日志：重连 / 换页 / 抓图快照 ——
    "检测到浏览器/页面已断开，正在重连专用 Chrome 并重开 Gemini 页面…",
    "已重连 Gemini，继续任务。",
    "换新标签仍未出图，改为**另开一个新窗口**重试…",
    "开新窗口多次失败，退回新标签方式。",
    "连接调试端口失败（socket hang up），1/4 退避重试…",
    "重连失败（target closed），改为刷新/换新对话再试一次。",
    "文字这一步没成功，自动干预后重试（第 2/3 次）…",
    "（未定位到生成图 <img>——落 DOM 快照供修选择器）",
    "已去除本轮生成图的 Gemini 水印。",
    # —— 迭代进度（Image#4 状态面板）——
    "第 1 轮：从原图底图重画（约 1-3 分钟）…",
    "第 3 轮出图完成，对比原图检查篡改与画质…",
    "已完成 5 轮，等待建筑师点评（可圈选图片做局部修改）…",
    # —— STATUS 面板：状态标签 + 轮次（index.html 拼 stateNames + " · 第 N 轮"）——
    # 用户 Image#3/#5：「迭代运行中 · 第 1 轮」「等待你的点评 · 第 1 轮」全露中文。
    # 每个 stateNames 值 + 轮次都必须翻干净（含标签自带 " · " 的 stalled）。
    "迭代运行中 · 第 1 轮",
    "等待你的点评 · 第 1 轮",
    "等你确认提示词 · 第 2 轮",
    "AI 有疑问，等你回答 · 第 1 轮",
    "局部修改中 · 第 3 轮",
    "已暂停 · 待重试 · 第 4 轮",
    "连接 Chrome 中… · 第 1 轮",
    # —— 完成交付日志（Image#5：桌面路径 + 超分尾注要翻；英文会话文件名已英文）——
    "完成！最终图已放到桌面：C:\\Users\\Andy\\Desktop\\render_result_0729_1124.png",
    "完成！最终图已放到桌面：C:\\Users\\Andy\\Desktop\\render_result_0729_1124.png（已超分 1024x1024 → 4096x4096）",
]


def test_runtime_dynamic_strings_all_translate():
    leaked = [s for s in RUNTIME_STRINGS if _leaks(s)]
    assert not leaked, "英文模式下仍会露中文（未补 i18n）：\n" + "\n".join(leaked)
