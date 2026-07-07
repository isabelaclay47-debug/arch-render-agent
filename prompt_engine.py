# -*- coding: utf-8 -*-
"""
提示词引擎：建筑渲染提示词的组织逻辑。

中英分工（关键）：
  · 导演对话的**指令**用中文（导演读中文需求、用中文推理）；
  · 导演的**产出**分双语——给建筑师看的用中文（理解讲解 / 中文提示词 / 查篡改分析），
    真正发给 ChatGPT 生图的用英文（英文提示词 / 精修指令），图像模型吃英文更稳；
  · 每条发给生图模型的指令都在代码层强制附带一套英文"底线"（质量 + 负向 + 直线要直 +
    忠实性），用户没说也照加。

组织框架（ArchiPrompt）：主体/图纸类型 → 风格 → 材质 → 光线时段 → 相机镜头 →
  氛围环境 → 渲染质感，先锁形体再定氛围。

导演对话(director chat)负责：理解需求 → 产出双语提示词 → 对比生成图与原图查篡改
  → 判断精修/重画 → 迭代修订。
"""

import re

# ======================================================================
#  一、导演的中文参照知识（导演读它来组织提示词，不直接发给生图模型）
# ======================================================================

# 忠实性硬约束——只写模型默认不保证的事
FIDELITY_RULES = """【忠实性约束】
1. 建筑的形体、层数、开窗、柱网、屋顶线和标志性构件（格栅/连廊/坡道/雨棚等）必须与原图完全一致，不得增删、移位或变形；
2. 直线保持笔直、竖线保持垂直——建筑边线、窗框竖梃、栏杆、分缝不得弯曲、鼓胀或透视扭曲；
3. 图中所有文字（标识、门头、指示牌、幕墙 logo 等）必须保持原有内容、字形清晰端正，绝不允许扭曲、变形或变成乱码；无法写清楚的文字宁可保持原样不动；
4. 只提升：材质真实感、光影、天空、配景（人/树/车）和画面质感。"""

# 提示词骨架——按 ArchiPrompt 框架排序，先锁主体再定氛围
PROMPT_SKELETON = """【建筑渲染提示词骨架】按此顺序写具体、可执行的描述，不堆空洞形容词：
① 主体与图纸类型：建筑类型/体量/层数 + 是渲染表现图还是图纸表达（总平/平/立/剖/轴测）
② 建筑风格与气质：现代/极简/参数化/新中式/工业等，或参照意向图的事务所气质
③ 材质（要精确命名，别只说"石头/木头"）：如清水混凝土(board-formed concrete)、焦杉木(Shou Sugi Ban)、锌板立边咬合(zinc standing seam)、耐候钢(Corten)、Low-E 玻璃、穿孔铝板等
④ 光线与时段：黄金时刻侧光 / 正午硬光 / 蓝调黄昏 / 夜景灯光 / 阴天漫射 / 雨后，天气与云、光比与阴影方向
⑤ 相机镜头：等效焦距(24mm 大场景 / 35mm 街景 / 50mm 标准 / 85mm 局部)、机位高度、一/两/三点透视、移轴校正竖线、前中后景层次
⑥ 环境配景：比例正确、与季节/地域/时段一致的人物·树种·车辆·铺装，密度适中不喧宾夺主
⑦ 风格氛围与渲染质感：写实建筑摄影感/杂志编辑感/胶片感/竞赛展板，自然 HDR、专业后期，避免 CG 塑料感"""

# 从主流 ArchViz 与 AI 生图提示词实践蒸馏、并结合 2026 最新公开指南丰富的专业储备库。
# 库是"参照"不是"模板"：导演按每个项目挑相关的几条融进提示词，不整段塞入。
ARCHVIZ_DISTILLED_LIBRARY = """【建筑提示词专业储备库】

A. 图纸表达
- 总平面图：用地边界、建筑轮廓、道路与人行流线、景观分区、入口节点、北向与比例尺；风格可选白底竞赛图 / 淡彩分析图 / 深色总图 / 出版级矢量图。
- 平面图：墙体线宽层级、门窗洞口、核心筒、家具尺度、流线箭头、功能分区色块、房间标签清晰可读。
- 立面图：轴网、楼层线、开窗节奏、材料分缝、阴影厚度、门头与标识清晰，正投影不透视变形。
- 剖面图 / 剖透视：楼板厚度、层高、楼梯坡道、结构与空间关系、采光路径、人物尺度、室内外高差。
- 轴测 / 爆炸轴测：几何准确、构件分层、结构/表皮/机电/景观关系清楚，克制阴影、高可读标签。
- 分析图：日照/风环境/流线/视线/景观结构，图解语言干净、图例清晰、低饱和配色。

B. 渲染场景与光线
- 写实日景：自然白天、柔和阴影、真实玻璃反射、材质细节到位、人车密度适中、专业建筑摄影后期。
- 黄金时刻：低角度暖光、长阴影、玻璃冷暖反差、天空渐变、材质边缘高光；温暖但不电影化过度。
- 蓝调黄昏 / 夜景：室内暖光外透、立面灯光层次、路灯与车灯反射、玻璃深色透明感、天空保留蓝调；避免霓虹与过曝。
- 正午硬光：强方向光、短硬阴影、高对比，适合表现体量与阴影关系；注意别让高光溢出。
- 阴天 / 漫射光：柔和无向光、饱和度略低、材质本色真实，适合冷静克制的表现。
- 雨后 / 湿地面：地面轻微镜面反射、水迹克制、天空漫射、饱和度略高，建筑轮廓保持干净。
- 雾景 / 雪景：空气透视拉开层次 / 积雪与融雪痕迹真实，注意屋面与地面积雪的物理逻辑。
- 鸟瞰城市：屋顶第五立面关系、道路网、绿化水体、周边体量与城市尺度清晰，避免玩具模型感。
- 室内：优先自然采光 + 实用光源（落地窗漫射光 + 暖色重点照明），避免均匀顶光、避免"打光如样板房"的塑料感。

C. 材质与细节（精确命名 + 常见失真雷区）
- 玻璃幕墙：Low-E 低反射玻璃、室内暗部层次、竖梃横梁清晰、反射遵循真实天空与周边环境；忌纯蓝假玻璃、忌镜面死板。
- 石材立面：浅米白/灰白石材、细微颗粒、分缝对齐、边缘倒角、柱脚接触阴影；忌塑料白墙、忌无缝完美。
- 清水混凝土(board-formed concrete)：模板木纹或拉片孔、微小色差、真实粗糙度、边角克制磨损；忌均匀脏污、忌水泥灰死板。
- 金属 / 铝板 / 耐候钢：拉丝或阳极氧化质感、锈色渐变(Corten)、板缝准确、边缘高光、反射柔和；忌镜面化、忌塑料反光。
- 木材 / 焦杉木(Shou Sugi Ban)：木纹方向与格栅间距一致、阴影节奏、暖色不过饱和、炭化肌理真实；忌橡皮擦般均匀。
- 砖 / 陶土板 / 穿孔板：砌筑或排布规律、灰缝深度、透光与阴影、单元错缝真实；忌贴图重复感。
- 绿植 / 水景 / 铺装：树种与地域季节一致、投影方向与主光一致、水面反射与波纹克制、铺装拼缝比例正确。

D. 构图与相机
- 人视街景：35–50mm 等效焦距，竖线垂直（移轴校正），两点透视自然，前景留出人行尺度。
- 大场景 / 沿街：24–28mm 广角拉开纵深，但控制边缘畸变，保持建筑竖线不外扩。
- 局部 / 细部：85mm 压缩空间、浅景深突出材质节点。
- 建筑杂志摄影：画面干净、曝光均衡、自然 HDR、轻微景深、边缘锐利但不过度锐化、编辑级构图。
- 竞赛展板风：留白克制、线面层级清楚、颜色低饱和、文字可读、图面秩序强。

E. 风格与氛围参照（中性描述，不点名抄袭）
- 极简克制、体量与光影为主角（近 SANAA/极简事务所气质）；
- 粗野有力、清水混凝土与厚重体量（近粗野主义）；
- 参数化流线、连续表皮（近 Zaha 气质）；
- 温暖在地、自然材料与手工感；
- 胶片颗粒 / 杂志编辑 / 纪实摄影等画面调性。

F. 负向约束（分类"绝不允许"）
- 形体篡改类：改体量/层数/开窗/柱网/屋顶线/道路/楼梯/坡道/栏杆/场地高差/标识文字；凭空加减楼层或构件。
- 几何失真类：直线变弯、竖线外扩、窗框扭曲、透视鼓胀、漂浮建筑、错误阴影方向。
- 材质失真类：CG 塑料感、假蓝玻璃、镜面死板、贴图重复、样板房打光。
- 曝光后期类：过度锐化、强 HDR 光晕、过饱和、高光溢出、暗部死黑、廉价滤镜感。
- 风格跑偏类：卡通、插画、手绘草图、概念拼贴、奇幻建筑（除非明确要求）。
- 文字类：乱码、扭曲、错字、无意义字符。"""


# ======================================================================
#  二、导演对话函数（中文指令，双语产出）
# ======================================================================

_BILINGUAL_OUTPUT_SPEC = """请严格按以下格式输出，不要输出其他内容（三段都要有）：
<理解>
（用中文向建筑师复述你对他意图的理解：他想要什么效果、你打算怎么处理、有哪些是你替他补的专业决定；让他一眼看出有没有理解偏差。3~6 句话，说人话。）
</理解>
<中文提示词>
（完整的中文版生图提示词，具体、可执行，供建筑师阅读与修改。）
</中文提示词>
<英文提示词>
(The full English generation prompt, faithfully matching the Chinese one above. Describe scene/style/materials/lighting/camera/atmosphere concretely. Do NOT repeat the universal quality/fidelity baseline — the system appends it automatically. English only.)
</英文提示词>"""


def director_system_prompt() -> str:
    """导演对话开场：定义身份、知识、工作方式与双语输出格式。"""
    return f"""你现在是一位资深建筑可视化(ArchViz)提示词导演。我会给你：建筑师的想法（可能只有寥寥几句）、一张必须严格忠实的"原图"（底图），可能还有若干"意向图"（只借鉴氛围/材质/光线，不借鉴形体）。

你的核心任务：把建筑师的想法**扩写成一份全面的生图提示词**——
- 建筑师明确提到的要求，逐条落实、写具体；
- 建筑师没提到的维度，由你凭专业经验替他做出最贴合其意图的决定并补全，不留空白；
- 有意向图时，先读懂它的光线/色调/材质气质，转译成文字写进提示词。

覆盖维度参考：
{PROMPT_SKELETON}

可调用的专业储备库：
{ARCHVIZ_DISTILLED_LIBRARY}

{FIDELITY_RULES}

【先判断，再动笔】写提示词之前，先判断是否存在**会直接影响出图方向**的关键疑问——比如时段/氛围前后矛盾、意向图气质和文字要求冲突、原图某部位看不懂、不确定最想提升哪方面。有则只输出：
<反问>
（最多 3 个问题，每行一个，问得具体，让建筑师一句话就能答清）
</反问>
无关紧要的细节（配景密度、云形这类）自己专业判断，不要为问而问。

需求明确时，{_BILINGUAL_OUTPUT_SPEC}"""


def clarification_answer_prompt(answers: str) -> str:
    """把建筑师对反问的回答送回导演对话。"""
    return f"""建筑师对你的疑问回答如下：

{answers}

请据此继续完成任务。如果仍有会影响出图方向的关键不明之处，可再次用 <反问>…</反问> 提问（尽量一次问清）。否则{_BILINGUAL_OUTPUT_SPEC}"""


def adjust_prompt(edited_zh: str, note: str = "") -> str:
    """建筑师在确认关卡里改了中文提示词/提了意见后，让导演重新对齐三段产出。"""
    note_block = f"\n\n建筑师另外补充的意见：\n{note}" if note.strip() else ""
    return f"""建筑师看过你的理解和中文提示词后，把中文提示词调整为下面这版（这是他最想要的方向，以此为准）：

【建筑师确认/修改后的中文提示词】
{edited_zh}{note_block}

请据此重新给出三段产出：更新后的<理解>要简述你如何落实他的调整；<中文提示词>在他这版基础上润色完善（保持他的意图，别擅自改回）；<英文提示词>与最终中文严格对应。如果他的调整里有会影响出图方向的关键歧义，才用 <反问>…</反问> 先问清。

{_BILINGUAL_OUTPUT_SPEC}"""


def qc_and_revise_prompt(iteration: int) -> str:
    """把生成结果发回导演：查篡改 + 判断"精修/重画" + 给出对应修改依据（分析中文、指令英文）。"""
    return f"""这是第 {iteration} 轮的结果（第一张为忠实性参照的原图底图，第二张为本轮生成图）。请执行三步：

第一步【篡改检查】逐项对比生成图与原图底图：
- 建筑形体/轮廓/层数、开窗位置与比例是否一致？有没有凭空增删体块、构件、楼层？
- 直线是否仍笔直、竖线是否仍垂直？有没有弯曲、鼓胀、透视扭曲？
- 视角与透视是否偏移？特殊构件（格栅/连廊/坡道等）是否保留？
- 图中文字是否清晰端正、有没有扭曲变形或乱码？
- 画质评价：光影是否自然、材质是否真实、配景是否得当、有无过曝/塑料感。

第二步【判断下一步怎么走】——这一步决定省不省额度：
- 选「精修」：建筑形体与原图基本一致，剩下主要是**局部瑕疵**（个别文字/某处材质/某个构件/局部配景/某处光影）。在本轮这张图基础上只改这些局部，**不要推倒重画**，已画好的部分逐像素保留。
- 选「重画」：仅当**建筑形体被明显篡改**（层数/开窗/体块变了、透视偏了），或主要问题是**全局性的**（整体光线/氛围/构图方向不对，非大改不可）时，才从原图底图按修订后的完整英文提示词重画。

第三步【给出修改依据】
- 若选「精修」：用**英文**列出这张图上具体待修的局部缺陷清单（供在这张图基础上增量修改，其余保持不变），每条聚焦一个部位、说清怎么改。
- 若选「重画」：给出完整的**英文**下一轮提示词（把被篡改的部位用明确语言锁定、画质不足处加强；不必重复通用质量/忠实底线，系统会自动附带）。

请严格按以下格式输出，不要输出其他内容：
<分析>
（中文：篡改点与画质问题的逐条清单，每条一行，格式：[严重/中等/轻微] 问题描述）
</分析>
<忠实度>一致 | 轻微偏移 | 明显篡改</忠实度>
<下一步>精修 | 重画</下一步>
<结论>
（中文一句话：本轮是否可接受，最大的问题是什么）
</结论>
<精修指令>
(English fix list — only if 下一步 is 精修; otherwise leave empty)
</精修指令>
<新提示词>
(Full English redraw prompt — only if 下一步 is 重画; otherwise leave empty)
</新提示词>"""


def feedback_prompt(user_feedback: str) -> str:
    """把建筑师点评注入导演对话，要求据此修订双语提示词。"""
    return f"""建筑师本人看过目前的过程图后，给出如下点评，这是最高优先级的修改依据，必须逐条落实：

【建筑师点评】
{user_feedback}

请据此修订提示词。如果某条点评有歧义、看不懂指的是画面哪个部位，不要猜——只输出 <反问>…</反问>（最多 3 个具体问题）。点评清楚时，严格按以下格式输出，不要输出其他内容：
<分析>
（中文：你如何理解并落实每条点评，逐条列出）
</分析>
<中文提示词>
（完整的中文版下一轮提示词）
</中文提示词>
<新提示词>
(Full English next-round prompt matching the Chinese one; do not repeat the universal baseline.)
</新提示词>"""


def translate_instruction_prompt(zh_instruction: str) -> str:
    """把建筑师用中文写的"局部修改指令"翻成英文，供发给生图模型。"""
    return f"""请把下面这条建筑图局部修改指令**翻译成地道的英文**，只翻译、不扩写、不解释，保留其精确含义：

{zh_instruction}

只输出：
<英文提示词>
(the English translation)
</英文提示词>"""


def regional_qc_message(instruction: str) -> str:
    """局部修改后的检查：只允许标记区域变化（中文分析给建筑师看）。"""
    return f"""这是一次局部修改的检查。第一张是修改前的图，第二张是修改后的图。当时的修改指令是：「{instruction}」，且只允许改动图中被红色标记过的那个区域。请逐项检查：
- 标记区域内：修改指令是否达成？
- 标记区域外：有没有任何内容被顺带改动（建筑/天空/配景/色调）？
- 直线是否仍笔直、文字是否仍清晰端正、没有变形或乱码？

请严格按以下格式输出，不要输出其他内容：
<分析>
（中文：逐条清单，格式：[严重/中等/轻微] 问题描述；没有问题就写"未发现问题"）
</分析>
<结论>
（中文一句话：这次局部修改是否合格）
</结论>"""


# ======================================================================
#  三、发给"生成对话"的英文指令（含始终强制的英文底线）
# ======================================================================

# 每条生图指令都强制附带的英文底线——质量 + 负向 + 直线要直 + 忠实性。
# 用户没说也照加（#7 需求）。图像模型吃英文更稳，所以这里用英文。
GENERATION_BASICS = """[NON-NEGOTIABLE BASELINE — always enforce, even if not explicitly asked]
- Do NOT alter the building's form, geometry, floor count, window layout, structural members, facade divisions, roofline or column grid — keep them pixel-faithful to the base image.
- Keep every straight architectural line perfectly straight and every vertical perfectly vertical: no bowing, warping, curved window frames/mullions, or perspective distortion.
- Maximize image quality and preserve fine detail: crisp, sharp material textures, clean edges, no smudging, blur, noise, banding, or AI artifacts.
- Physically realistic materials and light: avoid plastic/CG look, fake blue glass, mirror-flat surfaces, repeated-texture tiling, oversaturation, harsh clipped shadows, blown highlights, crushed blacks, HDR halos, and over-sharpening.
- Keep all text/signage/logos legible and undistorted — never garbled.
- Photorealistic architectural photography — not cartoon, illustration, sketch, or concept art."""

# 画质档位 → 追加英文措辞
QUALITY_HINTS = {
    "标准": "",
    "高清": "Render at high resolution with dense detail: sharp material textures, clean edges, no smudging or noise.",
    "极致": "Render at maximum resolution and detail density: material textures stay crisp when zoomed in, "
            "glass reflections, brushed metal and stone grain fully resolved, clean edges, zero smudging, noise or artifacts.",
}

# 画幅 → 追加英文措辞。跟随原图时也明确写"比例不变"（实测模型不总会自动沿用底图画幅）。
RATIO_HINTS = {
    "跟随原图": "Keep the exact aspect ratio of the uploaded base image — do not crop, pad, stretch or change the aspect ratio.",
    "横版": "Use a landscape 1536x1024 canvas.",
    "竖版": "Use a portrait 1024x1536 canvas.",
    "方形": "Use a square 1024x1024 canvas.",
}


def generation_message(prompt_en: str, quality: str = "标准", ratio: str = "跟随原图") -> str:
    """发给"生成对话"的英文消息：底图 + 英文提示词（+ 画质/画幅）+ 英文底线。"""
    extras = " ".join(x for x in (QUALITY_HINTS.get(quality, ""),
                                  RATIO_HINTS.get(ratio, "")) if x)
    return f"""Using the architectural base image I uploaded, generate one photorealistic architectural render following the prompt below. Output the image directly — no questions, no explanation. {extras}

{prompt_en}

{GENERATION_BASICS}"""


def refine_message(fix_instruction_en: str, quality: str = "标准") -> str:
    """增量精修英文指令：以"上一张生成图"为底，只改 QC 列出的局部缺陷，其余逐像素保留。

    这是省额度、消除"问题反复出现"的关键——不推倒重画，而是在已有成果上打补丁。
    不指定画幅（沿用上一张），指定画幅会诱导模型整张重画。
    """
    hint = QUALITY_HINTS.get(quality, "")
    hint_line = f" {hint}" if hint else ""
    return f"""This is your previous architectural render. Make an INCREMENTAL edit on THIS image — output the edited image directly, no questions, no explanation, do NOT regenerate from scratch.{hint_line}

[Fix ONLY the following; keep everything else pixel-identical]
{fix_instruction_en}

[Iron rules]
1. Everything not listed above — building form/floors/windows/members, composition, camera, sky, entourage, overall color and lighting mood — must stay pixel-identical to this image; do not touch or re-render it.
2. Keep straight lines straight and text legible — no bowing, warping or garbling.
3. Apply only the listed local improvements; do not change the overall look or composition.
{GENERATION_BASICS}"""


def regional_edit_message(instruction_en: str) -> str:
    """局部修改英文指令：第 1 张为待改图，第 2 张为红色标记版（只改标记区）。"""
    return f"""I uploaded two images: the first is the image to edit; the second marks, in red, the ONLY region you may change. Output the edited image directly — no questions, no explanation.

[Edit instruction — apply ONLY inside the red-marked region]
{instruction_en}

[Iron rules]
1. Everything OUTSIDE the red mark must stay pixel-identical to the first image — building, sky, entourage, color and composition included.
2. The red marks themselves must NOT appear in the output.
3. Keep straight lines straight and all text legible and undistorted.
{GENERATION_BASICS}"""


# ======================================================================
#  四、解析
# ======================================================================

def parse_director_reply(text: str) -> dict:
    """解析导演对话的结构化标签，宽容缺段。

    返回字段：
      understanding 理解 / prompt_zh 中文提示词 / prompt_en 英文提示词
      analysis 分析 / verdict 结论 / fidelity 忠实度 / next_step 下一步
      refine_instruction 精修指令 / new_prompt 新提示词(英文重画)
    """
    def grab(tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
        return m.group(1).strip() if m else ""

    understanding = grab("理解")
    prompt_zh = grab("中文提示词")
    prompt_en = grab("英文提示词")
    analysis = grab("分析")
    verdict = grab("结论")
    new_prompt = grab("新提示词")
    fidelity = grab("忠实度")            # 一致 / 轻微偏移 / 明显篡改
    next_step = grab("下一步")           # 精修 / 重画
    refine_instruction = grab("精修指令")

    found_any = any([understanding, prompt_zh, prompt_en, analysis, verdict,
                     new_prompt, fidelity, next_step, refine_instruction])
    if not found_any:
        # 模型完全没按标签输出：取最后一个标签后的全部内容兜底当英文提示词
        tail = re.split(r"</?[^>]+>", text)[-1].strip()
        if len(tail) > 80:
            prompt_en = tail
    return {"understanding": understanding, "prompt_zh": prompt_zh,
            "prompt_en": prompt_en, "analysis": analysis, "verdict": verdict,
            "new_prompt": new_prompt, "fidelity": fidelity,
            "next_step": next_step, "refine_instruction": refine_instruction}


def extract_questions(text: str) -> str:
    """提取导演对话的 <反问> 内容；没有反问时返回空串。"""
    m = re.search(r"<反问>(.*?)</反问>", text, re.S)
    return m.group(1).strip() if m else ""


def helper_refine_prompt(draft: str) -> str:
    """助手页精修：让导演看用户上传的图 + 草稿，产出专业版三段提示词。"""
    draft_block = f"\n\n【用户的初步想法/草稿】\n{draft}" if draft.strip() else ""
    return f"""你是资深建筑可视化提示词导演。用户上传了一张图作为底图参照。请**仔细看图**，
识别建筑类型、材质、光线、构图与风格，结合用户草稿，产出一份专业、具体、可执行的生图提示词。{draft_block}

{_BILINGUAL_OUTPUT_SPEC}"""


# ======================================================================
#  五、本地确定性拼装（助手页"本地模式"：无 LLM、不联网）
# ======================================================================

def build_prompt_locally(intent: str, image_desc: str, preset_texts=None) -> dict:
    """把「用户想法 + 本地识图描述 + 勾选的储备库文本」确定性地拼装成中英双语提示词。
    与自动生成共用同一套专业知识底座（骨架 / 储备库 / 英文底线），但不调用任何 LLM。"""
    preset_texts = [t.strip() for t in (preset_texts or []) if t and t.strip()]
    intent = (intent or "").strip()
    image_desc = (image_desc or "").strip()

    # 中文提示词：想法 + 识图 + 勾选模块，按可读顺序组织
    zh_parts = []
    if intent:
        zh_parts.append(f"【建筑师想法】{intent}")
    if image_desc:
        zh_parts.append(f"【底图画面】{image_desc}")
    if preset_texts:
        zh_parts.append("【专业要求】\n- " + "\n- ".join(preset_texts))
    if not zh_parts:
        zh_parts.append("在严格保持原图建筑形体的前提下，提升材质真实感、光影与画面质感，"
                        "达到专业建筑摄影质感。")
    prompt_zh = "\n".join(zh_parts)

    # 英文提示词：把可英文化的部分并入，末尾强制附加通用英文底线
    en_bits = []
    if image_desc:
        en_bits.append(f"Base scene: {image_desc}.")
    if intent:
        en_bits.append(f"Architect's intent (translate faithfully): {intent}.")
    if preset_texts:
        en_bits.append("Professional requirements: " + " ".join(preset_texts))
    en_head = " ".join(en_bits) if en_bits else (
        "Improve material realism, lighting and overall quality while keeping the "
        "building form pixel-faithful to the base image.")
    prompt_en = f"{en_head}\n\n{GENERATION_BASICS}"

    understanding_zh = (
        "我据此把你的想法、底图画面和勾选的专业模块，整理成了下面这份完整的中英提示词——"
        "你可以直接复制英文版拿去生图工具里用。")
    return {"understanding_zh": understanding_zh,
            "prompt_zh": prompt_zh, "prompt_en": prompt_en}
