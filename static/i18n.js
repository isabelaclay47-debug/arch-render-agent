/* Arch Render Agent — browser-side bilingual UI (ZH / EN).
   The service keeps Chinese as its canonical protocol language; this layer translates
   every user-facing DOM mutation, alert, confirmation, status and error in English mode. */
(function () {
  "use strict";

  const STORAGE_KEY = "archrender.lang";
  const HAN = /[\u3400-\u9fff]/;
  let language = localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh";

  const EXACT = {
    /* Shared shell */
    "建筑渲染智能体": "Architectural Rendering Agent",
    "提示词助手 · 建筑渲染": "Prompt Assistant · Architectural Rendering",
    "当前运行的代码版本。改完代码必须重启本服务才生效——重启后来这里对一眼版本号，就知道新码有没有跑起来。": "Currently running build. Restart the service after a code update, then check this build number to confirm the new version is active.",
    "想法 → AI 扩写全面提示词 → 生图 → 对比查篡改 → 自动迭代 · 每 5 轮请你点评 · 满意后输出到桌面": "Idea → AI expands the prompt → Generate → Fidelity check → Automatic iteration · Review at your chosen interval · Export when approved",
    "检测 ChatGPT 连接中…": "Checking the ChatGPT connection…",
    "检测": "Check",
    "启动 Chrome 去登录": "Launch Chrome to sign in",
    "提示词助手（无需账号）": "Prompt Assistant (no account required)",
    "本功能需要你自备可访问 ChatGPT / Google 的网络环境。请自行配置好网络后，点「测试连接」。": "This feature needs your own network connection to ChatGPT and Google. Set up your connection, then click Test connection.",
    "还连不上外网": "Can't reach the internet yet",
    "本工具需要能访问 ChatGPT / Google 的网络。可用「土星通讯」配置，或用你自己的网络；配好后点「测试连接」。": "This tool needs a network that can reach ChatGPT / Google. Set one up with 土星通讯 (VPN) or use your own; then click Test connection.",
    "稍后": "Later",
    "测试连接": "Test connection",
    "检测网络中…（约几秒）": "Checking the connection… (a few seconds)",
    "✓ 已连通，可以开始使用了。": "✓ Connected. You're ready to go.",
    "仍然连不上 chatgpt.com——请确认已配置并连上可访问它的网络后再试。": "Still can't reach chatgpt.com — set up and connect to a network that can reach it, then try again.",
    "配置土星通讯": "Set up 土星通讯 (VPN)",
    "已打开土星通讯页面：请在其中登录、按你的系统下载并安装客户端，连上网络后回来点「测试连接」。": "Opened the 土星通讯 (VPN) page. Sign in there, download and install the client for your system, connect, then come back and click Test connection.",
    "打开失败：": "Couldn't open: ",
    "已开始下载 土星通讯，界面会显示进度。": "Downloading 土星通讯 (VPN); progress will appear here.",
    "正在下载 土星通讯 安装包…": "Downloading the 土星通讯 (VPN) installer…",
    "下载完成，正在打开 土星通讯 安装程序，请按提示完成安装…": "Download complete. Opening the 土星通讯 (VPN) installer — follow its prompts to finish.",
    "土星通讯 安装程序已打开。装好并连上网络后，回来点「测试连接」。": "The 土星通讯 (VPN) installer is open. Once it's installed and connected, come back and click Test connection.",
    "启动安装失败：": "Couldn't start the installer: ",
    "连网检查并更新到最新版": "Check online and update to the latest version",
    "检查更新": "Check for updates",
    "检查中…": "Checking…",
    "更新中…": "Updating…",
    "生图引擎": "Image engine",
    "Gemini 模型": "Gemini model",
    "分工": "Roles",
    "Gemini 全包（只启动 Gemini）": "Gemini does everything (Gemini only)",
    "借 ChatGPT 当导演": "Use ChatGPT as director",
    "切换分工失败": "Failed to switch roles",
    "Gemini 分工：全包＝选 Gemini 就只启动 Gemini，理解/提示词/查篡改/翻译与生图都由它做，只登录 gemini.google.com；借 ChatGPT＝Gemini 只生图、仍连 ChatGPT 做文字推理（需同时登录 ChatGPT）。任务进行中不可切，下次「开始渲染」生效。": "Gemini roles. \"Gemini does everything\": choosing Gemini launches Gemini only — understanding, prompts, fidelity checks, translation and image generation are all done by Gemini, and you only sign in to gemini.google.com. \"Use ChatGPT as director\": Gemini generates images while ChatGPT handles text reasoning (requires signing in to ChatGPT too). Cannot switch during a task; applies to the next render.",
    "画质": "Output quality",
    "1K · 原生": "1K · Native",
    "生图用哪家：ChatGPT，或 Gemini 的 nano-banana（都走你的订阅、免 API key）。任务进行中不可切，下次「开始渲染」生效。文本推理始终走 ChatGPT。": "Choose ChatGPT or Gemini nano-banana for image generation. Both use your subscription and require no API key. You cannot switch during a task; the choice applies to the next render. Text reasoning always uses ChatGPT.",
    "Gemini 用哪个生图模型（登录后自动切到该模型再跑；若网页版式变动切不了，会提示你在 Gemini 页面手动切一次）。任务进行中不可切，下次「开始渲染」生效。": "Choose the Gemini image model. After sign-in, the app switches to it automatically. If Gemini's page changes, you will be asked to switch once manually. You cannot switch during a task; the choice applies to the next render.",
    "最终输出图的画质：本地 AI 超分（Swin2SR），离线免账号。1K=原生不放大；2K/4K/8K 会在出图后本地放大补细节（高档位需数分钟）。只增强最终交付图，不影响过程与生图速度。": "Final output quality via local AI upscaling (Swin2SR), offline and account-free. 1K keeps the native size; 2K/4K/8K upscale locally after generation. Higher settings may take several minutes. Only the final delivery is enhanced, so generation speed is unaffected.",

    /* Main form */
    "Ⅰ · 需求": "Ⅰ · BRIEF",
    "建筑师的想法": "Design intent",
    "— 寥寥几句即可，AI 会扩写成全面提示词": "— A few words are enough; AI will expand them into a complete prompt",
    "例如：黄昏暖光，玻璃幕墙要有真实反射，前景加行人和行道树，接近杂志摄影感。": "Example: warm dusk light, realistic curtain-wall reflections, pedestrians and street trees in the foreground, with an editorial photography feel.",
    "提示词储备库": "Prompt library",
    "— 点选后插入到上面的想法里": "— Select a module and insert it into the brief above",
    "选择一个模块预览内容。": "Select a module to preview it.",
    "插入选中模块": "Insert selected module",
    "插入推荐组合": "Insert recommended set",
    "已选历史成图当新底图，将在": "A previous render is selected as the new base and will continue in a",
    "全新对话": "new conversation",
    "里接着迭代": "for further iteration",
    "改为上传新图": "Upload a new image instead",
    "原图": "Base image",
    "— 必传，建筑形体将被严格锁定": "— Required; building geometry will be strictly locked",
    "点击选择原图": "Click to choose a base image",
    "✏️ 标注底图": "✏️ Annotate base image",
    "— 箭头/文字/椭圆/画笔 · 可改颜色粗细": "— Arrows, text, ellipses and brush · Adjustable color and width",
    "意向图": "Reference images",
    "— 可选多张；每张可选角色（通用/材质/氛围/换入内容/图纸），不选=通用参考，会连同底图一起发给生图 AI": "— Optional, multiple allowed. Assign each a role (general/material/mood/content/drawing). Unassigned images are general references and are sent to the image AI with the base image.",
    "点击选择意向图": "Click to choose reference images",
    "素材库": "Asset library",
    "— 导入本地图片存起来随时复用": "— Import local images and reuse them at any time",
    "意向": "References",
    "配景": "Entourage",
    "材质": "Materials",
    "+ 导入": "+ Import",
    "生成画质": "Generation quality",
    "标准": "Standard",
    "高清": "High",
    "极致": "Ultra",
    "极致细节": "Ultra detail",
    "画幅": "Aspect ratio",
    "跟随原图": "Match base image",
    "横版": "Landscape",
    "竖版": "Portrait",
    "方形": "Square",
    "几张一停等我点评": "Pause for review after",
    "1张一停": "Every image",
    "2张": "2 images",
    "3张": "3 images",
    "5张": "5 images",
    "每出这么多张就暂停等你点评。张数越少越省生图额度、越早纠偏；越多越自动化。": "The task pauses after this many images for your review. Smaller batches save generation quota and correct direction earlier; larger batches are more automated.",
    "开 始 渲 染": "START RENDERING",
    "开始前请确认右上角状态灯为绿色（已登录并就绪）——未启动时点「启动 Chrome 去登录」。": "Before starting, confirm that the status indicator at the top right is green. If Chrome is not running, click “Launch Chrome to sign in.”",
    "用 Gemini 生图时需同时登录 Gemini（出图）与 ChatGPT（负责理解想法和查篡改的文字推理）。": "When using Gemini for images, sign in to both Gemini (image generation) and ChatGPT (brief interpretation and fidelity checks).",
    "开始前请确认右上角状态灯为绿色（已登录并就绪）——未启动时点「启动 Chrome 去登录」。 用 Gemini 生图时需同时登录 Gemini（出图）与 ChatGPT（负责理解想法和查篡改的文字推理）。": "Before starting, confirm that the status indicator at the top right is green. If Chrome is not running, click “Launch Chrome to sign in.” When using Gemini for images, sign in to both Gemini (image generation) and ChatGPT (brief interpretation and fidelity checks).",

    /* History, help and state */
    "Ⅰ·5 · 历史成图": "Ⅰ·5 · RENDER HISTORY",
    "— 挑一张满意的当新底图，接着迭代": "— Choose a successful render as the next base image",
    "加载历史中…": "Loading history…",
    "↻ 刷新": "↻ Refresh",
    "🗑 回收站": "🗑 Recycle bin",
    "🖌 局部修改在哪？": "🖌 Where are local edits?",
    "任务跑起来后，右侧每张过程图下方都有「圈选局部修改这张图」按钮——": "Once a task is running, each process image on the right has a “Mark a region for local edits” button.",
    "任务跑起来后，右侧每张过程图下方都有「圈选局部修改这张图」按钮—— 在": "Once a task is running, each process image on the right has a “Mark a region for local edits” button. Open it",
    "每 5 轮点评暂停": "review pause",
    "时点开，用画笔或框选标红要改的部位，": "Open it during a review pause and mark the area to change with the brush or selection tools.",
    "AI 只改圈内、不动周边。": "AI changes only the marked area and preserves everything around it.",
    "时点开，用画笔或框选标红要改的部位， AI 只改圈内、不动周边。": "Open it during a review pause and mark the area to change with the brush or selection tools. AI changes only the marked area and preserves everything around it.",
    "🔑 账号登录在哪？": "🔑 Where do I sign in?",
    "在专用 Chrome 窗口里（右上角可一键启动），登录一次 chatgpt.com 即可，之后一直记住。": "Sign in once at chatgpt.com in the dedicated Chrome window, which you can launch from the top right. The session is remembered.",
    "Ⅱ · 状态": "Ⅱ · STATUS",
    "未开始": "Not started",
    "刷新 ChatGPT / 重查结果": "Refresh ChatGPT / check again",
    "提前结束": "Finish early",
    "等待任务…": "Waiting for a task…",
    "❓ AI 有疑问，答清再生图": "❓ AI needs clarification before generating",
    "— 不消耗生图额度": "— Does not use image-generation quota",
    "逐条回答上面的问题，一句话答清即可。": "Answer the questions above clearly; one sentence per question is enough.",
    "回答，继续": "Answer and continue",
    "🧭 先确认我的理解对不对": "🧭 Confirm my understanding first",
    "— 确认后才开始生图，不消耗额度": "— Generation starts only after confirmation and uses no quota yet",
    "我理解你的意思是：": "My understanding:",
    "中文提示词（可直接改，改完点右边按钮让 AI 同步）": "Working prompt (editable; use the button to ask AI to sync your changes)",
    "可选：有理解偏差就写一句，例如「其实我要正午硬光不是黄昏」「别加行人」。": "Optional: describe any correction, for example “Use hard midday light, not dusk” or “Do not add pedestrians.”",
    "就用这份，开始生图": "Use this and start generating",
    "让 AI 按我的修改再调整": "Ask AI to apply my changes",
    "⏸ 请点评这一批过程图": "⏸ Review this batch",
    "也可以点过程图下方的「🖌 圈选局部修改」——只改圈出的部分，不动周边": "You can also choose “🖌 Mark a region for local edits” below a process image. Only the marked area will change.",
    "例如：第 4 张最好，但天空太假；入口格栅被改掉了必须恢复；行人再少一点。": "Example: Image 4 is best, but the sky looks artificial. Restore the entrance screen and reduce the number of pedestrians.",
    "按点评继续": "Continue with feedback",
    "满意，输出到桌面": "Approve and export",
    "✓ 已完成": "✓ Complete",
    "最终图已保存到：": "Final image saved to:",
    "点开看增强大图": "Open the enhanced full-size image",
    "Ⅲ · 过程图": "Ⅲ · PROCESS IMAGES",
    "— 每轮附 AI 篡改检查结论，点击图片放大": "— Each round includes an AI fidelity check; click an image to enlarge",
    "— 过程图会实时出现在这里 —": "— Process images will appear here in real time —",
    "该图的详细提示词": "Detailed prompt for this image",
    "关闭": "Close",

    /* Local edit studio */
    "🖌 局部修改": "🖌 Local edit",
    "选择": "Select",
    "手画": "Freehand",
    "画笔": "Brush",
    "直线": "Line",
    "箭头": "Arrow",
    "框选": "Rectangle select",
    "矩形": "Rectangle",
    "椭圆": "Ellipse",
    "多边形套索": "Polygon lasso",
    "钢笔选取": "Pen selection",
    "涂抹": "Paint",
    "文字": "Text",
    "橡皮擦": "Eraser",
    "线宽": "Line width",
    "颜色": "Color",
    "粗细": "Width",
    "撤销": "Undo",
    "清空": "Clear",
    "用红色标出": "Mark in red",
    "唯一允许修改": "the only area that may change",
    "的区域——AI 将被严格要求不动区域外的任何内容。": ". AI will be strictly instructed to preserve everything outside it.",
    "手画/涂抹：按住拖动 · 直线/箭头：拖出 · 框选：拖出矩形 · 多边形套索：连续点、": "Freehand/Paint: drag · Line/Arrow: drag · Rectangle: drag · Polygon lasso: click points and",
    "双击闭合": "double-click to close",
    "· 文字：点一下再输入 ·": "· Text: click, then type ·",
    "：点已画标注→拖动移位、拖右下角缩放、双击文字改内容 · 橡皮擦：拖过要删掉的标记 ·": ": click an annotation to move it, drag the lower-right handle to resize, or double-click text to edit · Eraser: drag over marks to remove ·",
    "滑块调粗细": "slider adjusts the width",
    "编辑记录会自动保存": "Edits are saved automatically",
    "——万一出图中途停了，重开这张图或刷新页面，你圈的标注和指令都还在，改改提示词直接重新提交即可": ". If generation stops, reopen the image or refresh the page: your marks and instructions will still be there and can be resubmitted.",
    "已选材质，提交后将把圈出区域换成它": "A material is selected. Submitting will apply it to the marked area.",
    "取消材质": "Clear material",
    "这个区域要怎么改？例如：把入口雨棚改成木格栅材质 / 去掉这个人 / 这块墙面换成清水混凝土": "How should this area change? Example: use timber slats on the entrance canopy / remove this person / change this wall to fair-faced concrete.",
    "提交局部修改（只改圈出的部分）": "Submit local edit (marked area only)",

    /* Status names and history controls */
    "连接 Chrome 中…": "Connecting to Chrome…",
    "迭代运行中": "Iterating",
    "等你确认提示词": "Waiting for prompt confirmation",
    "AI 有疑问，等你回答": "Waiting for your clarification",
    "等待你的点评": "Waiting for your review",
    "局部修改中": "Applying local edit",
    "已暂停 · 待重试": "Paused · Retry required",
    "已完成": "Complete",
    "出错": "Error",
    "还没有历史成图。完成一次渲染后，可复用的成图会出现在这里。": "No render history yet. Reusable images will appear here after your first completed render.",
    "历史加载失败：": "History failed to load: ",
    "标为重点底图": "Mark as a favorite base image",
    "删除这张（进回收站）": "Delete this image (move to recycle bin)",
    "用作底图": "Use as base image",
    "→ 发给助手": "→ Send to Assistant",
    "📄 提示词": "📄 Prompt",
    "🔍 提升画质": "🔍 Enhance quality",
    "初始命令：": "Initial brief:",
    "（无初始命令记录）": "(No initial brief recorded)",
    "最后一版提示词": "Latest prompt",
    "删除整个会话（进回收站）": "Delete the entire session (move to recycle bin)",
    "🗑 删除": "🗑 Delete",
    "重点底图": "Favorite base images",
    "这张图": "this image",
    "整个会话（含所有过程图）": "the entire session (including all process images)",
    "删除失败": "Delete failed",
    "彻底清空回收站？此操作不可恢复。": "Permanently empty the recycle bin? This cannot be undone.",
    "回收站是空的。": "The recycle bin is empty.",
    "回收站加载失败：": "Recycle bin failed to load: ",
    "单张": "Single image",
    "整会话": "Entire session",
    "恢复": "Restore",
    "彻底清空回收站": "Permanently empty recycle bin",
    "恢复失败": "Restore failed",
    "发送失败": "Send failed",
    "已接收提示词助手发来的底图（可点击重选）": "Base image received from Prompt Assistant (click to replace)",
    "已选历史成图当底图（点击可改上传新图）": "A previous render is selected as the base image (click to upload a new one)",

    /* Prompt library categories and names */
    "图纸": "Drawings",
    "渲染": "Rendering",
    "材料": "Materials",
    "光影": "Lighting",
    "修复": "Fixes",
    "约束": "Constraints",
    "总平竞赛图": "Competition site plan",
    "平面图": "Floor plan",
    "立面图": "Elevation",
    "剖面图": "Section",
    "轴测爆炸": "Exploded axonometric",
    "写实日景": "Photoreal daylight",
    "黄金时刻": "Golden hour",
    "蓝调夜景": "Blue-hour night",
    "雨后街景": "Post-rain streetscape",
    "鸟瞰城市": "Aerial city view",
    "玻璃幕墙": "Glass curtain wall",
    "石材立面": "Stone façade",
    "清水混凝土": "Fair-faced concrete",
    "金属铝板": "Metal / aluminum panels",
    "木格栅": "Timber slats",
    "杂志摄影": "Editorial photography",
    "人视街景": "Eye-level streetscape",
    "柔和阴天": "Soft overcast",
    "室内外通透": "Interior–exterior transparency",
    "只修清晰度": "Clarity only",
    "局部材质替换": "Local material replacement",
    "恢复楼梯硬景": "Restore stairs and hardscape",
    "文字保护": "Text and signage protection",
    "形体锁定": "Geometry lock",
    "负向质量": "Negative quality constraints",
    "意向图边界": "Reference-image boundaries",
    "素材": "asset",
    "定义每张": "assigning each image",
    "标注": "annotate",
    "（无）": "(None)",
    "张": "images",
    "通用参考": "General reference",
    "氛围/意向": "Mood / intent",
    "换入内容/物件": "Content / object to insert",

    /* Prompt library descriptions */
    "总平面图表达：白底竞赛图风格，清晰表达用地边界、建筑轮廓、道路系统、人行流线、景观分区、入口节点、北向与比例感；线宽层级明确，淡彩功能分区，标签清晰可读。": "Competition-style site plan on a white background. Clearly show site boundaries, building footprints, roads, pedestrian circulation, landscape zones, entrances, north direction and scale. Use a clear line-weight hierarchy, light functional color coding and legible labels.",
    "建筑平面图表达：墙体线宽层级清楚，门窗洞口、核心筒、楼梯、电梯、家具尺度、流线箭头和功能分区准确；房间标签可读，图面干净，出版级矢量制图质感。": "Architectural floor plan with a clear wall line-weight hierarchy, accurate openings, cores, stairs, lifts, furniture scale, circulation arrows and functional zoning. Keep room labels legible and use clean publication-quality vector drafting.",
    "建筑立面图表达：正投影视角，无透视变形；轴网、楼层线、开窗节奏、材料分缝、门头标识和阴影厚度清楚，线面层级克制，适合方案汇报。": "Orthographic architectural elevation with no perspective distortion. Clearly show grids, floor lines, opening rhythm, material joints, entrance signage and shadow depth with a restrained graphic hierarchy suitable for design presentations.",
    "建筑剖面图表达：楼板厚度、层高、楼梯/坡道、核心筒、结构与空间关系、采光路径、人物尺度、室内外高差清楚；剖切线黑白分明，背景淡化。": "Architectural section clearly showing slab thicknesses, floor heights, stairs and ramps, cores, structural–spatial relationships, daylight paths, human scale and interior–exterior level changes. Use strong cut lines and a subdued background.",
    "建筑轴测/爆炸图表达：几何准确，构件分层清楚，结构、表皮、交通、景观关系有秩序；使用克制阴影和高可读标签，避免装饰性过度。": "Accurate architectural axonometric or exploded diagram with clearly layered components and an ordered relationship between structure, envelope, circulation and landscape. Use restrained shadows and highly legible labels without excessive decoration.",
    "照片级建筑写实日景：自然白天漫射光，柔和阴影，真实玻璃反射，石材/金属/混凝土细节清晰，人物车辆比例准确、密度适中，专业建筑摄影后期，避免CG塑料感。": "Photoreal architectural daylight scene with natural diffuse light, soft shadows, realistic glass reflections and clear stone, metal and concrete detail. Keep people and vehicles correctly scaled and moderately dense, with professional architectural-photography grading and no plastic CGI look.",
    "黄金时刻建筑摄影：低角度暖光，长阴影，玻璃暖冷反差，天空轻微渐变，材质边缘有克制高光，氛围温暖但不过度电影化。": "Golden-hour architectural photography with low-angle warm light, long shadows, warm–cool contrast in the glass, a subtle sky gradient and restrained edge highlights. Keep the mood warm without becoming overly cinematic.",
    "蓝调夜景建筑渲染：天空保留深蓝层次，室内暖光透出，立面灯光有节制，路灯和车灯产生真实反射，玻璃深色透明，避免霓虹过度和曝光炸裂。": "Blue-hour architectural rendering with layered deep-blue sky, warm interior light, restrained façade lighting, realistic streetlight and headlight reflections, and dark transparent glass. Avoid excessive neon and blown highlights.",
    "雨后建筑街景：湿地面轻微反射，水迹自然不夸张，天空漫射光，材质饱和度略高，建筑轮廓和窗框保持干净锐利，行人车辆不喧宾夺主。": "Post-rain architectural streetscape with subtle wet-ground reflections, natural water traces, diffuse sky light and slightly richer material color. Keep building edges and window frames clean and sharp, with people and vehicles secondary.",
    "鸟瞰城市建筑表现：屋顶关系、道路网、绿化、水体、周边体量和城市尺度清晰；保持真实高度感和空气透视，避免玩具模型感。": "Aerial urban architectural view clearly showing roof relationships, road network, planting, water, surrounding massing and city scale. Maintain convincing height and atmospheric perspective; avoid a toy-model appearance.",
    "玻璃幕墙细节：低反射 Low-E 玻璃，室内暗部层次可见，竖梃和横梁清晰，反射遵循天空与周边环境，不做假蓝玻璃，不扭曲窗框。": "Glass curtain-wall detail with low-reflectance Low-E glazing, visible interior depth, crisp mullions and transoms, and reflections consistent with the sky and surroundings. Avoid artificial blue glass and distorted frames.",
    "石材立面细节：浅米白或灰白石材，细微颗粒、分缝对齐、边缘倒角、柱脚接触阴影自然；避免塑料白墙、过度洁白、分缝波浪。": "Light beige or off-white stone façade with subtle grain, aligned joints, chamfered edges and natural contact shadows at column bases. Avoid plastic-white walls, excessive whiteness and wavy joints.",
    "清水混凝土质感：模板缝、拉片孔、微小色差、真实粗糙度和克制边角磨损；整体干净但不死白，避免脏污过度和涂抹感。": "Fair-faced concrete with formwork joints, tie holes, subtle color variation, realistic roughness and restrained edge wear. Keep it clean without looking flat white; avoid excessive staining or smeared textures.",
    "金属/铝板立面：拉丝或阳极氧化质感，板缝准确，边缘高光克制，反射柔和，避免镜面化、波浪变形和廉价塑料感。": "Metal or aluminum-panel façade with brushed or anodized finish, accurate joints, restrained edge highlights and soft reflections. Avoid mirror finishes, warped panels and a cheap plastic appearance.",
    "木格栅细节：木纹方向明确，格栅间距一致，阴影节奏真实，暖色不过饱和；保持结构厚度和连接逻辑，不把格栅画成贴图。": "Timber-slat detail with clear grain direction, consistent spacing, realistic shadow rhythm and restrained warm color. Preserve structural thickness and connection logic; do not render the slats as a flat texture.",
    "建筑杂志摄影质感：等效35-50mm镜头，竖线垂直，两点透视自然，曝光均衡，自然HDR，轻微景深，边缘锐利但不过度锐化，画面干净。": "Architectural editorial photography with a 35–50 mm equivalent lens, vertical lines kept vertical, natural two-point perspective, balanced exposure, restrained HDR, slight depth of field and crisp but not oversharpened edges.",
    "人视街景构图：镜头高度接近人眼，前景保留人行尺度，道路和铺装引导视线，建筑竖线保持垂直，人物车辆比例准确。": "Eye-level streetscape composition with a human-height camera, pedestrian scale in the foreground, roads and paving guiding the view, vertical building lines and accurately scaled people and vehicles.",
    "柔和阴天光线：大面积漫射光，阴影轻但有层次，材质颜色真实，玻璃反射低调，适合强调立面细节和体量关系。": "Soft overcast lighting with broad diffuse illumination, light but layered shadows, true material colors and restrained glass reflections, emphasizing façade detail and massing relationships.",
    "室内外通透表达：玻璃后方可见适度室内深度、吊顶和暖光层次，室外反射与室内透视平衡，不让玻璃变成黑洞或纯镜面。": "Balanced interior–exterior transparency, revealing moderate interior depth, ceilings and warm light behind the glass while balancing exterior reflections and interior views. Avoid black-hole glazing or perfect mirrors.",
    "只做清晰度和材质细节修复：提升边缘、窗框、石材分缝、玻璃层次和阴影接触关系；不改变构图、体量、道路、场地、天空、人物和车辆。": "Improve only clarity and material detail: refine edges, window frames, stone joints, glass depth and contact shadows without changing composition, massing, roads, site, sky, people or vehicles.",
    "局部材质替换：只在指定区域内替换材料，保持区域外逐像素不动；新材质必须服从原图光线、透视、阴影和边界，不新增构件。": "Replace material only inside the specified region and preserve all pixels outside it. The new material must match the original lighting, perspective, shadows and boundaries without adding components.",
    "恢复楼梯和场地硬景：踏步、踢面、平台、坡道、栏杆、铺装缝、路缘石和高差阴影必须按原图保留；禁止填平广场或重画道路。": "Restore stairs and site hardscape exactly from the base image, including treads, risers, landings, ramps, railings, paving joints, curbs and level-change shadows. Do not flatten plazas or redraw roads.",
    "文字和标识保护：门头、logo、道路标线、指示牌、车身文字必须保持原内容、原位置、原字形和清晰度；无法写清楚时宁可保持原样不动。": "Protect text and signage. Entrances, logos, road markings, signs and vehicle text must keep their original content, position, letterforms and clarity. If text cannot be reproduced accurately, leave it unchanged.",
    "硬性约束：建筑形体、层数、开窗、柱网、屋顶线、楼板线、入口、道路、楼梯、坡道、栏杆、场地高差和周边建筑必须与原图一致，不得增删移动。": "Hard constraint: building geometry, floor count, openings, structural grid, roofline, slab lines, entrances, roads, stairs, ramps, railings, site levels and surrounding buildings must match the base image exactly. Do not add, remove or move them.",
    "负向质量约束：禁止过度锐化、强HDR、CG塑料感、假蓝玻璃、乱码文字、弯曲窗框、漂浮建筑、错误阴影、随意加楼层、随意加构件。": "Negative quality constraints: no oversharpening, aggressive HDR, plastic CGI look, fake blue glass, garbled text, bent window frames, floating buildings, incorrect shadows, added floors or invented components.",
    "意向图使用边界：只借鉴氛围、材质、光线、色调和摄影质感；不借鉴意向图的建筑形体、体量、开窗、场地、树木布置或新增构件。": "Reference-image boundary: borrow only mood, materials, lighting, color and photographic treatment. Do not copy building geometry, massing, openings, site layout, tree placement or added components from the reference.",

    /* Shorter Prompt Assistant preset variants */
    "照片级建筑写实日景：自然白天漫射光，柔和阴影，真实玻璃反射，材质细节清晰，专业建筑摄影后期，避免CG塑料感。": "Photoreal architectural daylight with natural diffuse light, soft shadows, realistic glass reflections, crisp material detail and professional architectural-photography grading. Avoid a plastic CGI look.",
    "黄金时刻建筑摄影：低角度暖光，长阴影，玻璃暖冷反差，天空轻微渐变，氛围温暖但不过度电影化。": "Golden-hour architectural photography with low-angle warm light, long shadows, warm–cool glass contrast and a subtle sky gradient. Keep the mood warm without becoming overly cinematic.",
    "玻璃幕墙细节：低反射 Low-E 玻璃，室内暗部层次可见，竖梃横梁清晰，不做假蓝玻璃。": "Glass curtain-wall detail with low-reflectance Low-E glazing, visible interior depth and crisp mullions and transoms. Avoid artificial blue glass.",
    "石材立面细节：浅米白或灰白石材，细微颗粒、分缝对齐、边缘倒角，避免塑料白墙。": "Light beige or off-white stone façade with subtle grain, aligned joints and chamfered edges. Avoid plastic-white walls.",
    "清水混凝土质感：模板缝、拉片孔、微小色差、真实粗糙度，避免脏污过度。": "Fair-faced concrete with formwork joints, tie holes, subtle color variation and realistic roughness. Avoid excessive staining.",
    "建筑杂志摄影质感：等效35-50mm，竖线垂直，自然HDR，轻微景深，边缘锐利但不过度锐化。": "Architectural editorial photography with a 35–50 mm equivalent lens, vertical lines, restrained HDR, slight depth of field and crisp but not oversharpened edges.",
    "硬性约束：建筑形体、层数、开窗、柱网、屋顶线、场地必须与原图一致，不得增删移动。": "Hard constraint: building geometry, floor count, openings, grid, roofline and site must match the base image exactly. Do not add, remove or move them.",
    "负向约束：禁止过度锐化、强HDR、CG塑料感、假蓝玻璃、乱码文字、弯曲窗框、漂浮建筑。": "Negative constraints: no oversharpening, aggressive HDR, plastic CGI look, fake blue glass, garbled text, bent window frames or floating buildings.",

    /* Dynamic main-page controls */
    "无法连接本地服务：": "Cannot connect to the local service: ",
    "服务返回异常": "Unexpected service response",
    "点击放大查看是否正确": "Click to enlarge and verify",
    "标注这张意向图": "Annotate this reference image",
    "这张图给生图 AI 的用途": "How the image-generation AI should use this image",
    "移除这张": "Remove this image",
    "标注模块未加载，刷新页面再试": "The annotation module did not load. Refresh the page and try again.",
    "需求描述和原图都是必填的（可上传新图，或从「历史成图」里挑一张当底图）": "A brief and a base image are required. Upload a new image or choose one from Render History.",
    "启动失败": "Failed to start",
    "请写点评，或直接点“满意”": "Enter feedback or choose Approve.",
    "请先回答 AI 的问题": "Answer the AI's questions first.",
    "确定提前结束吗？将放弃正在生成的这张，把已完成的最新一张图输出到桌面。": "Finish early? The image currently being generated will be discarded and the latest completed image will be exported.",
    "正在结束…": "Finishing…",
    "已发送，等待重查…": "Sent; waiting for another check…",
    "刷新失败": "Refresh failed",
    "（原图已够大，做了高质量缩放）": " (the original was already large enough; high-quality resizing applied)",
    "当前是 1K 原生档，无需增强。\n把顶栏「画质」切到 2K/4K/8K，再点这个按钮。": "The current setting is native 1K and needs no enhancement.\nChoose 2K, 4K or 8K in the top bar, then click this button again.",
    "当前是 1K 原生档，无需增强。": "The current setting is native 1K and needs no enhancement.",
    "把顶栏「画质」切到 2K/4K/8K，再点这个按钮。": "Choose 2K, 4K or 8K in the top bar, then click this button again.",
    "增强失败": "Enhancement failed",
    "未知错误（可能超分模型未下载）": "Unknown error (the upscaling model may not be downloaded)",
    "局部修改指令": "Local-edit instruction",
    "本轮提示词": "Prompt for this round",
    "结论": "Conclusion",
    "篡改检查明细": "Fidelity-check details",
    "建筑师初始命令": "Architect's initial brief",
    "最后一版提示词（中文）": "Latest prompt (Chinese)",
    "最后一版提示词（EN）": "Latest prompt (English)",
    "这张图没有留存任何提示词（更新此功能前生成的旧图，且会话级提示词也未保存）。": "No prompt was saved for this image. It predates per-image prompt history, and no session-level prompt is available.",
    "请先选择或上传一张原图，再标注": "Choose or upload a base image before annotating.",
    "已用标注后的底图（点击可重选）": "Using the annotated base image (click to replace)",
    "标注底图.png": "annotated-base.png",
    "_标注.png": "_annotated.png",
    "helper底图.jpg": "helper-base.jpg",
    "底图.jpg": "base-image.jpg",
    "点击放大": "Click to enlarge",
    "用作意向图": "Use as reference",
    "贴到标注": "Place in annotation",
    "换此材质": "Apply this material",
    "删除素材": "Delete asset",
    "素材加载失败": "Failed to load assets",
    "还没有": "No ",
    "素材，点「+ 导入」添加": " assets yet. Click “+ Import” to add some.",
    "导入失败": "Import failed",
    "删除这个素材？": "Delete this asset?",
    "加入意向图失败": "Failed to add reference image",
    "已选中该配景。先选/传一张原图，再点「✏️ 标注底图」，它会作为图章贴入，可拖动缩放。": "This entourage asset is selected. Choose or upload a base image, then click “✏️ Annotate base image.” It will be inserted as a movable, resizable stamp.",
    "检查更新失败": "Failed to check for updates",
    "更新内容：": "What's new:",
    "现在更新并重启服务吗？": "Update and restart the service now?",
    "更新失败": "Update failed",
    "已更新": "Updated",
    "已是最新": "Already up to date",
    "正在启动专用 Chrome…": "Launching dedicated Chrome…",
    "启动 Chrome 失败": "Failed to launch Chrome",
    "检测中…": "Checking…",
    "检测失败": "Check failed",
    "↻ 重试本轮": "↻ Retry this round",
    "局部修改": "Local edit",
    "的修改指令": " edit instruction",
    "后的提示词": " prompt",
    "自动迭代": "Automatic iteration",
    "把这条评价填入点评框": "Use this assessment as feedback",
    "🖌 圈选局部修改这张图": "🖌 Mark a region for local edits",
    "🔍 按当前画质提升并查看": "🔍 Enhance at current quality and view",
    "切换失败": "Switch failed",
    "已切到 Gemini 生图。 请确认专用 Chrome 里已登录 gemini.google.com。": "Gemini is now selected for image generation. Confirm that you are signed in to gemini.google.com in dedicated Chrome.",
    "已切到 Gemini 生图。": "Gemini is now selected for image generation.",
    "请确认专用 Chrome 里已登录 gemini.google.com。": "Confirm that you are signed in to gemini.google.com in dedicated Chrome.",
    "在下面「Gemini 模型」下拉里选生图模型即可，开始渲染后会自动切到它。下次「开始渲染」生效。": "Choose an image model from the Gemini model list below. The app will switch to it automatically when rendering starts; it applies to the next render.",
    "高档位每张需数分钟）。只增强最终交付图。": "Higher settings may take several minutes per image. Only the final delivery is enhanced.",
    "将在出图后本地 AI 超分（首次用会自动加载模型；高档位每张需数分钟）。只增强最终交付图。": "The image will be upscaled locally with AI after generation; the model loads automatically on first use, and higher settings may take several minutes per image. Only the final delivery is enhanced.",
    "超分中…": "Upscaling…",
    "切换模型失败": "Failed to switch model",
    "切换画质失败": "Failed to change output quality",
    "局部修改只能在“等待点评”暂停时进行（每 5 轮暂停一次）": "Local edits are available only during a review pause.",
    "输入文字：": "Enter text:",
    "修改文字：": "Edit text:",
    "请先用上面的工具在图上标红要修改的区域（多边形套索需双击闭合）": "Use the tools above to mark the area to change. Double-click to close a polygon lasso.",
    "请写清楚圈出的区域要怎么改": "Describe clearly how the marked area should change.",

    /* Base-image annotation modal */
    "✏️ 标注底图": "✏️ Annotate base image",
    "缩放": "Zoom",
    "缩小": "Zoom out",
    "放大（也可按住 Ctrl 滚轮）": "Zoom in (or hold Ctrl and use the mouse wheel)",
    "适应窗口": "Fit to window",
    "适应": "Fit",
    "取消": "Cancel",
    "完成标注": "Finish annotation",
    "：点任意标注→拖动移位、拖右下角缩放、": ": click any annotation to move it, drag the lower-right handle to resize, or",
    "双击文字改内容": "double-click text to edit",
    "· 画笔按住拖 · 直线/箭头/矩形/椭圆 拖出 · 钢笔逐点点击、": "· Brush: drag · Line/Arrow/Rectangle/Ellipse: drag · Pen: click points and",
    "· 文字点一下再输入 · 橡皮擦点掉标记": "· Text: click, then type · Eraser: click a mark to remove it",

    /* Prompt Assistant */
    "提示词助手": "Prompt Assistant",
    "— 拖图进来，帮你写出专业提示词": "— Drop in an image and build a professional prompt",
    "ChatGPT（专业级 · 需账号+VPN）": "ChatGPT (professional · account and VPN required)",
    "本地大模型（离线识图 · 免账号/VPN）": "Local model (offline vision · no account or VPN)",
    "点击或拖拽一张图片进来": "Click or drag an image here",
    "→ 把这张图发给渲染器当底图": "→ Send this image to the renderer as the base",
    "你的想法（一句话即可）": "Your idea (one sentence is enough)",
    "例如：黄昏暖光，玻璃幕墙要有真实反射，前景加行人。": "Example: warm dusk light, realistic curtain-wall reflections and pedestrians in the foreground.",
    "专业储备库（点选增强）": "Professional modules (select to enhance)",
    "看图理解 → 认可后再生成": "Interpret image → Confirm → Generate",
    "AI 看懂了这张图什么（可直接修改；改这里 = 告诉它正确的画面，再认可）": "What AI understands from the image (editable; correct the description here before confirming)",
    "点上面「看图理解」，这里会显示 AI 对你这张底图的理解…": "Choose “Interpret image” above to see the AI's understanding of your base image…",
    "✓ 认可，据此生成提示词": "✓ Confirm and generate prompt",
    "中文提示词": "Chinese prompt",
    "英文提示词（复制这段拿去生图）": "English prompt (copy this for image generation)",
    "📋 复制英文提示词": "📋 Copy English prompt",
    "不满意？说一句让我改（会在上面这版基础上修订，不推倒重来）": "Want a revision? Describe one change; the current prompt will be refined rather than rebuilt.",
    "例如：太商业了，我要更安静的住宅感；光线改成清晨；去掉行人。": "Example: It feels too commercial. Make it a quieter residential scene, use morning light and remove pedestrians.",
    "↻ 按我的意见改一版": "↻ Revise using my feedback",
    "将用 ChatGPT 看图并扩写（需已启动专用 Chrome 并登录）。": "ChatGPT will interpret the image and expand the prompt. Dedicated Chrome must be running and signed in.",
    "将用本机 Ollama 视觉模型离线识图，免账号免 VPN。未装可在下方一键准备。": "A local Ollama vision model will interpret the image offline, with no account or VPN. If needed, set it up below.",
    "已选择图片（可点击重选，点图放大）": "Image selected (click to replace; click the preview to enlarge)",
    "先选一张图": "Choose an image first.",
    "AI 正在看图理解中（首次可能较慢）…": "AI is interpreting the image (the first run may be slower)…",
    "完成，请在下方确认或修改。": "complete. Confirm or edit the description below.",
    "本地识图暂不可用，可直接在这里手写画面描述后认可。": "Local vision is unavailable. You can write the image description here and confirm it.",
    "看图理解失败": "Image interpretation failed",
    "AI 想跟你确认：": "AI would like to clarify:",
    "请先让 AI 看图理解，或在上面写一句这张图是什么，再认可": "Ask AI to interpret the image first, or write a short description above before confirming.",
    "生成中…": "Generating…",
    "生成失败": "Generation failed",
    "已复制英文提示词": "English prompt copied",
    "先写一句你想怎么改": "Describe the change you want first.",
    "请先生成一版提示词": "Generate a prompt first.",
    "改稿中…": "Revising…",
    "改稿失败": "Revision failed",
    "（修改意见）": "(Revision request) ",
    "⚠ 后台还是旧版本——网页更新了，但 Python 服务没重启": "⚠ The backend is still an older version—the page updated, but the Python service was not restarted",
    "本地模型「切换」要重启服务才生效：": "Switching local models requires a service restart:",
    "① 双击「停止服务.bat」（或关掉那个后台窗口）→ ② 双击「双击启动.bat」→ ③ 回来刷新本页。": "1. Double-click Stop Service.bat (or close the service window) → 2. Double-click Start.bat → 3. Return and refresh this page.",
    "只刷新浏览器不够": "Refreshing the browser alone is not enough",
    "——网页文件是即时的，但后台程序要重启才换成新的。": ". Page files update immediately, but the backend must restart to load the new version.",
    "检测到 Ollama，但还没有识图模型。": "Ollama is installed, but no vision model is available.",
    "还没装本地识图。可一键下载并安装 Ollama + 识图模型（需你同意）。": "Local vision is not installed. You can download and install Ollama plus a vision model with one click after approval.",
    "一键准备本地识图": "Set up local vision",
    "本地识图（": "Local vision (",
    "要重启服务": "service restart required",
    "上次失败：": "Last failure: ",
    "用哪个：": "Model:",
    "想再装一个随时切换：": "Install another model for quick switching:",
    "下载": "Download",
    "✓ 本地识图就绪": "✓ Local vision ready",
    "已切换本地识图模型：": "Local vision model switched to: ",
    "（下次识图生效）": " (applies to the next image)",
    "准备中": "Preparing",
    "下载并安装 Ollama 中": "Downloading and installing Ollama",
    "下载识图模型中": "Downloading vision model",
    "完成": "Complete",
    "⏳": "⏳",
    "…（可最小化，装好会自动就绪）": "… (you may minimize this page; it will become ready automatically)",
    "将下载并安装 Ollama（约几百 MB）+ 识图模型": "This will download and install Ollama (several hundred MB) plus vision model ",
    "，全部在本机、离线可复用。": ". Everything stays on this computer and can be reused offline.",
    "下载较大、请保持联网；期间可继续用 ChatGPT 引擎。": "The download is large, so keep the network connected. You may continue using the ChatGPT engine during setup.",
    "现在开始吗？": "Start now?",

    /* Backend/API messages and logs */
    "已有任务在运行": "A task is already running.",
    "需求描述和原图都是必填的": "A brief and a base image are required.",
    "图片无法读取：": "Could not read the image: ",
    "任务进行中不能切换生图引擎，请等本次结束或先结束任务": "The image engine cannot be changed while a task is running. Wait for it to finish or finish it early.",
    "任务进行中不能切换分工，请等本次结束或先结束任务": "Roles cannot be changed while a task is running. Wait for it to finish or finish it early.",
    "任务进行中不能切换模型，请等本次结束或先结束任务": "The model cannot be changed while a task is running. Wait for it to finish or finish it early.",
    "未知画质档位：": "Unknown output-quality setting: ",
    "找不到这张图": "Image not found.",
    "当前是 1K 原生档，无需增强；把画质切到 2K/4K/8K 再试": "The current setting is native 1K and requires no enhancement. Switch to 2K, 4K or 8K and try again.",
    "已有一张图在增强中，请等它完成再点": "Another image is being enhanced. Wait for it to finish before starting another.",
    "当前不在点评阶段": "The task is not at a review stage.",
    "当前不在确认阶段": "The task is not at the confirmation stage.",
    "只能在点评暂停时做局部修改": "Local edits are available only during a review pause.",
    "标记图和修改指令都是必需的": "A marked image and edit instructions are required.",
    "找不到要修改的图": "The image to edit could not be found.",
    "当前 AI 没有待回答的疑问": "AI has no pending clarification questions.",
    "回答不能为空": "The answer cannot be empty.",
    "渲染任务运行中，连接正常": "Rendering is in progress; the connection is healthy.",
    "专用 Chrome 未启动": "Dedicated Chrome is not running.",
    "已登录，就绪": "signed in and ready",
    "已登录": "signed in",
    "Chrome 已启动，但": "Chrome is running, but",
    "未登录（去那个窗口登录一次）": "is not signed in. Sign in once in that window.",
    "连接失败：": "Connection failed: ",
    "没找到 Chrome，请确认已安装 Google Chrome": "Google Chrome was not found. Confirm that it is installed.",
    "现在没有正在等待的浏览器操作": "No browser operation is currently waiting.",
    "当前正在渲染，稍后再用 ChatGPT 精修": "A render is in progress. Use ChatGPT refinement after it finishes.",
    "没检测到可用的 ChatGPT（需已启动专用 Chrome 并登录），可切到「本地」模式": "No available ChatGPT session was detected. Launch dedicated Chrome and sign in, or switch to Local mode.",
    "还没有已确认的画面理解，请先做第一步「看图理解」": "There is no confirmed image understanding yet. Complete “Interpret image” first.",
    "安装已在进行中，请看进度。": "Setup is already in progress. Follow the status below.",
    "已开始准备本地识图，界面会显示进度。": "Local vision setup has started. Progress will appear on the page.",
    "未检测到 Ollama，开始下载并安装（首次约几百 MB）…": "Ollama was not detected. Downloading and installing it (several hundred MB on first use)…",
    "Ollama 安装后仍未就绪，请手动确认安装。": "Ollama is still unavailable after installation. Confirm the installation manually.",
    "Ollama 安装完成。": "Ollama installation complete.",
    "启动 Ollama 服务…": "Starting the Ollama service…",
    "安装包下载不完整": "The installer download is incomplete.",
    "运行安装程序（静默、无需管理员）…": "Running the installer silently without administrator rights…",
    "Ollama 服务启动超时，请手动运行 `ollama serve` 后重试。": "Ollama service startup timed out. Run `ollama serve` manually and try again.",
    "没有收到图片": "No image was received.",
    "本地模型没返回描述，可重试或改用 ChatGPT 引擎": "The local model returned no description. Retry or use the ChatGPT engine.",
    "本地识图失败：": "Local image interpretation failed: ",
    "本机没装 git，无法在线更新。": "Git is not installed, so online update is unavailable.",
    "git 操作超时（可能网络不通）。": "The Git operation timed out, possibly because the network is unavailable.",
    "有渲染任务在进行，请先结束/完成再更新": "A render is running. Finish or stop it before updating.",
    "已经是最新版本。": "You already have the latest version.",
    "依赖有变化，正在自动安装新依赖（pip install -r requirements.txt）…": "Dependencies changed. Installing the new dependencies automatically…",
    "⚠ 新依赖安装失败，已暂不重启。请手动运行 pip install -r requirements.txt 后重启。": "⚠ New dependency installation failed, so the service was not restarted. Install the requirements manually and restart.",
    "新依赖安装完成。": "New dependencies installed.",
    "缺少 session/image": "Missing session or image.",
    "要收藏的图不存在": "The image to favorite does not exist.",
    "无效的会话": "Invalid session.",
    "无效的图片名": "Invalid image name.",
    "找不到该会话": "Session not found.",
    "找不到该图": "Image not found.",
    "回收站里没有这一项": "This item is not in the recycle bin.",
    "原会话已存在同名，无法恢复": "A session with the same name already exists and cannot be restored.",
    "to 必须是 helper 或 render": "Destination must be helper or render.",
    "没有可传的图": "No image is available to send.",
    "分类必须是 意向/配景/材质": "Category must be References, Entourage or Materials.",
    "没有可导入的图片": "No importable images were provided.",
    "导入失败：图片都无法读取": "Import failed: none of the images could be read.",
    "无效的素材 id": "Invalid asset ID.",
    "素材不存在": "Asset not found.",

    /* Generation workflow logs */
    "AI 对需求有疑问，先反问建筑师（不消耗生图额度）…": "AI needs clarification and is asking the architect before generating (no image quota used)…",
    "生图引擎：Gemini（nano-banana）网页驱动；ChatGPT 只做文本推理（理解/提示词/查篡改）。": "Image engine: Gemini (nano-banana) via the web interface. ChatGPT handles text reasoning only: understanding, prompts and fidelity checks.",
    "导演对话：理解想法、扩写第一版全面提示词…": "Director chat: interpreting the brief and expanding the first complete prompt…",
    "在回答 AI 反问前结束了任务，尚未生成任何图片。": "The task ended before the clarification was answered; no image was generated.",
    "收到回答，导演对话继续组织提示词…": "Answer received. The director chat is continuing to organize the prompt…",
    "第一版提示词已生成。": "The first prompt is ready.",
    "建筑师调整了提示词，导演据此重新组织…": "The architect edited the prompt. The director is reorganizing it…",
    "在确认提示词前结束了任务，尚未生成任何图片。": "The task ended before prompt confirmation; no image was generated.",
    "等待建筑师确认理解与中文提示词（还没消耗生图额度）…": "Waiting for the architect to confirm the understanding and working prompt (no image quota used yet)…",
    "提示词已确认，开始生图。": "Prompt confirmed. Starting image generation.",
    "局部修改：先让导演复述对修改的理解，等你确认…": "Local edit: the director is restating the requested change for your confirmation…",
    "局部修改出图完成，检查标记区域外是否被动…": "Local-edit image complete. Checking whether anything outside the marked area changed…",
    "已提前结束：放弃正在生成的这一张，输出已完成的最后一张成品。": "Finished early: the current generation was discarded and the latest completed image will be exported.",
    "⚠ 自动重试用尽仍未出图，暂停等待手动重试或结束：": "⚠ Automatic retries were exhausted without an image. Paused for manual retry or finish: ",
    "收到重试指令，重开 ChatGPT 对话再生成一次…": "Retry received. Reopening the ChatGPT conversation and generating again…",
    "收到点评，导演对话据此修订提示词…": "Feedback received. The director is revising the prompt…",
    "提示词已按点评修订。": "The prompt was revised using your feedback.",
    "警告：点评后未解析出新提示词，沿用上一版。": "Warning: no new prompt could be parsed after feedback; continuing with the previous version.",
    "已提前结束（放弃了正在生成的那张，已交付此前完成的最后一张）。": "Finished early. The in-progress image was discarded and the last completed image was delivered.",
    "已提前结束（还没有生成任何图片）。": "Finished early before any image was generated.",
    "出错：": "Error: ",
    "未预期的错误：": "Unexpected error: ",
    "收到重试指令：将重开 ChatGPT 对话再生成一次。": "Retry received: the ChatGPT conversation will reopen and generate again.",
    "收到人工干预：将刷新 ChatGPT 页面并重新检查结果。": "Manual intervention received: refreshing ChatGPT and checking the result again.",
    "完成！最终图已放到桌面：": "Complete! The final image was saved to the desktop: ",
    "任务结束时还没有任何生成图，无图可输出。": "The task ended without a generated image, so there is nothing to export.",
    "画质增强完成 →": "Quality enhancement complete →",
    "画质增强不可用": "Quality enhancement unavailable",
    "画质增强出错，已保留原图": "Quality enhancement failed; the original image was preserved",
    "去水印": "watermark removal"
    ,"（空）": "(empty)"
    ,"无结论": "No conclusion"
    ,"删除": "Delete"
    ,"失败": "failed"
    ,"检查": "check"
    ,"下载": "download"
    ,"安装": "install"
    ,"已装": "installed"
    ,"全部源": "all sources"
    ,"换下一个": "trying the next one"
    ,"新版": "new version"
    ,"新依赖": "new dependencies"
    ,"本地视觉模型": "local vision model"
    ,"视觉模型": "vision model"
    ,"画质增强跳过": "Quality enhancement skipped"
    ,"缺依赖": "missing dependency"
    ,"已跳过，出图不受影响": "Skipped; image generation is unaffected"
    ,"高档位需数分钟，请稍候": "Higher settings may take several minutes; please wait"
    ,"调试端口": "debug port"
    ,"正在连接": "Connecting to"
    ,"只修改标记区域": "changing only the marked area"
    ,"检查完成": "check complete"
    ,"出图完成": "image complete"
    ,"页面可能假死": "the page may be unresponsive"
    ,"生图卡住": "image generation is stuck"
    ,"自动刷新重试一轮": "automatically refreshing and retrying once"
    ,"收尾时": "while finishing"
    ,"官方源": "official source"
    ,"运行官方安装脚本": "Running the official installer script"
    ,"安装脚本": "installer script"
    ,"可手动到": "You can install it manually from"
    ,"没检测到": "Not detected: "
    ,"检测到": "Detected: "
    ,"但没有": "but no"
    ,"已拉取新版": "New version downloaded"
    ,"含新依赖，已自动安装": "new dependencies included and installed automatically"
    ,"代码已更新，但新依赖自动安装失败。请手动运行": "The code was updated, but automatic dependency installation failed. Run this manually: "
  };

  const DYNAMIC = [
    [/^未知生图引擎：(.+)（可选 (.+)）$/, m => `Unknown image engine: ${m[1]} (available: ${m[2]})`],
    [/^未知 Gemini 模型：(.+)（可选 (.+)）$/, m => `Unknown Gemini model: ${m[1]} (available: ${m[2]})`],
    [/^未知画质：(.+)（可选 (.+)）$/, m => `Unknown output quality: ${m[1]} (available: ${m[2]})`],
    [/^⚠ 画质增强不可用（缺依赖：(.+)），已跳过，出图不受影响。$/, m => `⚠ Quality enhancement unavailable (missing dependency: ${m[1]}). Skipped; image generation is unaffected.`],
    [/^本地画质增强中（(.+)）…高档位需数分钟，请稍候。$/, m => `Enhancing locally (${translateCore(m[1])})… Higher settings may take several minutes; please wait.`],
    [/^（画质增强跳过：(.+)）$/, m => `(Quality enhancement skipped: ${translateCore(m[1])})`],
    [/^正在连接 Chrome（调试端口 (.+)）…$/, m => `Connecting to Chrome (debug port ${m[1]})…`],
    [/^⚠ 出图成功但篡改检查时 ChatGPT 未响应（(.+)）——已保留此图，下一轮从原图重画。$/, m => `⚠ The image was generated, but ChatGPT did not respond during the fidelity check (${m[1]}). The image was kept; the next round will redraw from the base image.`],
    [/^局部修改检查完成：(.+)$/, m => `Local-edit check complete: ${translateCore(m[1])}`],
    [/^⚠ 生图卡住：(.+) —— 自动刷新重试一轮(.*)$/, m => `⚠ Image generation is stuck: ${translateCore(m[1])} — refreshing automatically and retrying once${translateCore(m[2])}`],
    [/^提前结束收尾时出错：(.+)$/, m => `Error while finishing early: ${translateCore(m[1])}`],
    [/^该源失败（(.+)），换下一个…$/, m => `This source failed (${translateCore(m[1])}); trying the next one…`],
    [/^Ollama 安装包全部源都下载失败：(.+)。可手动到 ollama.com 装。$/, m => `All Ollama installer download sources failed: ${translateCore(m[1])}. You can install it manually from ollama.com.`],
    [/^从「(.+)」下载 (.+) …$/, m => `Downloading ${m[2]} from “${m[1]}”…`],
    [/^「(.+)」失败：(.+)，换下一个源…$/, m => `“${m[1]}” failed: ${translateCore(m[2])}; trying the next source…`],
    [/^模型下载失败（ModelScope 与官方源都没成功）：(.+)$/, m => `Model download failed from both ModelScope and the official source: ${translateCore(m[1])}`],
    [/^检测到 Ollama 但没有视觉模型（已装：(.+)）。$/, m => `Ollama was detected, but no supported vision model is available (installed: ${m[1]}).`],
    [/^确定删除(.+)？可在「回收站」里恢复。$/, m => `Delete ${translateCore(m[1])}? You can restore it from the recycle bin.`],
    [/^已选中该材质「(.+)」。到点评阶段点某张图的「🖌 圈选局部修改」，用钢笔\/套索圈出区域后提交，即按此材质替换（区域外不动）。$/, m => `Material “${m[1]}” selected. During a review pause, choose “🖌 Mark a region for local edits,” mark the area with the pen or lasso, then submit. The material will be replaced only inside that region.`],
    [/^发现新版本（当前 v(.+)，落后\s*(\d+)\s*次提交）。$/, m => `A new version is available (current v${m[1]}, ${m[2]} commits behind).`],
    [/^·\s*第\s*(\d+)\s*轮$/, m => `· Round ${m[1]}`],
    [/^第\s*(\d+)\s*轮：在上一张基础上做增量精修（省额度，不推倒重画）…$/, m => `Round ${m[1]}: applying an incremental refinement to the previous image (quota-efficient; no full redraw)…`],
    [/^第\s*(\d+)\s*轮：从原图底图重画（约 1-3 分钟）…$/, m => `Round ${m[1]}: redrawing from the base image (about 1–3 minutes)…`],
    [/^第\s*(\d+)\s*轮出图完成，对比原图检查篡改与画质…$/, m => `Round ${m[1]} image complete. Comparing it with the base image for fidelity and quality…`],
    [/^第\s*(\d+)\s*轮检查完成（下一轮将(.+?)）：(.+)$/, m => `Round ${m[1]} check complete (next round: ${translateCore(m[2])}): ${translateCore(m[3])}`],
    [/^第\s*(\d+)\s*轮（局部修改）：只修改标记区域——(.+)$/, m => `Round ${m[1]} (local edit): changing only the marked area — ${translateCore(m[2])}`],
    [/^第\s*(\d+)\s*轮似乎出图了但没抓到图片（页面可能假死）。$/, m => `Round ${m[1]} appears to have generated an image, but it could not be captured (the page may be unresponsive).`],
    [/^局部修改第\s*(\d+)\s*轮似乎出图了但没抓到图片（页面可能假死）。$/, m => `Local-edit round ${m[1]} appears to have generated an image, but it could not be captured (the page may be unresponsive).`],
    [/^已完成\s*(\d+)\s*轮，等待建筑师点评（可圈选图片做局部修改）…$/, m => `${m[1]} rounds complete. Waiting for the architect's review; you can mark an image for local edits…`],
    [/^第\s*(\d+)\s*轮$/, m => `Round ${m[1]}`],
    [/^第\s*(\d+)\s*轮\s*·\s*(.+)$/, m => `Round ${m[1]} · ${translateCore(m[2])}`],
    [/^已选\s*(\d+)\s*张（点图放大\s*·\s*×移除(?:\s*·\s*✏标注)?）$/, m => `${m[1]} selected (click to enlarge · × remove${m[0].includes("标注") ? " · ✏ annotate" : ""})`],
    [/^(.+?)\s*·\s*(\d+)\s*张$/, m => `${m[1]} · ${m[2]} images`],
    [/^仍然连不上（(.+)）——请确认已配置并连上可访问它们的网络后再试。$/, m => `Still can't reach ${m[1]} — set up and connect to a network that can reach them, then try again.`],
    [/^检测失败：(.+)$/, m => `Check failed: ${translateCore(m[1])}`],
    [/^已提升到\s*(\w+)(.*)$/, m => `Enhanced to ${m[1]}${translateCore(m[2])}`],
    [/^正在按\s*(\w+)\s*本地 AI 超分…(.+)$/, m => `Upscaling locally to ${m[1]} with AI… ${translateCore(m[2])}`],
    [/^最终图按\s*(\w+)\s*画质本地增强中（高档位需数分钟）…$/, m => `Enhancing the final image locally at ${m[1]} quality (higher settings may take several minutes)…`],
    [/^已按\s*(\w+)\s*画质增强(.*)$/, m => `Enhanced at ${m[1]} quality${translateCore(m[2])}`],
    [/^已经是最新版本（v(.+)）。$/, m => `You already have the latest version (v${m[1]}).`],
    [/^发现新版本（当前 v(.+)，落后\s*(\d+)\s*次提交）。([\s\S]*)$/, m => `A new version is available (current v${m[1]}, ${m[2]} commits behind).${translateCore(m[3])}`],
    [/^已设为\s*(\w+)\s*画质。([\s\S]*)$/, m => `Output quality set to ${m[1]}. ${translateCore(m[2])}`],
    [/^已切换本地识图模型：(.+)（下次识图生效）$/, m => `Local vision model switched to ${m[1]} (applies to the next image).`],
    [/^开始下载识图模型\s*(.+)（较大、只需一次，之后离线复用）…$/, m => `Downloading vision model ${m[1]} (large one-time download; reusable offline)…`],
    [/^识图模型\s*(.+)\s*就绪，本地识图已可用。$/, m => `Vision model ${m[1]} is ready; local image interpretation is available.`],
    [/^(.+)\s*端口被另一个调试浏览器占用——关掉那个程序后再点「检测」$/, m => `Port ${m[1]} is being used by another debug browser. Close that program and click Check again.`],
    [/^英文提示词偏短\/缺失，原始回复：(.+)。追问一次…$/, m => `The English prompt is too short or missing. Original reply: ${translateCore(m[1])}. Asking once more…`],
    [/^随底图一并发送\s*(\d+)\s*张参考图给生图 AI（(.+)）。$/, m => `Sending ${m[1]} reference images with the base image to the image AI (${translateCore(m[2])}).`],
    [/^(.+)加载失败：(.+)$/, m => `${translateCore(m[1])} failed to load: ${translateCore(m[2])}`],
    [/^(.+)失败：(.+)$/, m => `${translateCore(m[1])} failed: ${translateCore(m[2])}`]
  ];
  const PHRASES = Object.keys(EXACT).filter(key => HAN.test(key)).sort((a, b) => b.length - a.length);

  const SKIP_SELECTOR = [
    "[data-i18n-skip]", "#requirement", "#clarifyText", "#promptZh", "#confirmNote",
    "#fbText", "#editInstruction", "#understanding", "#questions", "#promptModalBody pre",
    ".gallery pre", ".hist-req pre", "#intent", "#understandEdit", "#zh", "#en",
    "#refineText", "input[type=file]"
  ].join(",");
  const ATTRS = ["title", "placeholder", "aria-label", "alt"];
  const textSources = new WeakMap();
  const attrSources = new WeakMap();
  let observer = null;
  let applying = false;

  function translateCore(value) {
    if (!value || !HAN.test(value)) return value;
    const normalized = value.replace(/\s+/g, " ").trim();
    if (EXACT[normalized]) return EXACT[normalized];
    for (const [pattern, render] of DYNAMIC) {
      const match = normalized.match(pattern);
      if (match) return render(match);
    }
    /* Fallback for composed runtime strings not covered by EXACT/DYNAMIC. Splice known
       phrases (longest first) into English. Then: if any Chinese still remains, we could
       not translate the sentence cleanly — return the ORIGINAL untouched rather than a
       half-English mix or a placeholder marker, both of which read as bugs. CJK
       punctuation is normalized only once the splice fully succeeds, so a finished English
       sentence never keeps Chinese punctuation. */
    let out = normalized;
    for (const source of PHRASES) {
      if (out.includes(source)) out = out.split(source).join(EXACT[source]);
    }
    if (HAN.test(out)) return value;
    return out.replace(/，/g, ", ").replace(/。/g, ".").replace(/：/g, ": ")
      .replace(/；/g, "; ").replace(/（/g, "(").replace(/）/g, ")")
      .replace(/？/g, "?").replace(/[「」]/g, '"').replace(/、/g, ", ");
  }

  function t(value) {
    if (language !== "en" || typeof value !== "string" || !value) return value;
    return value.split("\n").map(line => {
      const leading = line.match(/^\s*/)[0];
      const trailing = line.match(/\s*$/)[0];
      const core = line.slice(leading.length, line.length - trailing.length || undefined);
      return leading + translateCore(core) + trailing;
    }).join("\n");
  }

  function skipped(node) {
    const el = node.nodeType === 1 ? node : node.parentElement;
    return !!(el && el.closest && (el.closest("script,style,noscript,template") || el.closest(SKIP_SELECTOR)));
  }

  function translateTextNode(node) {
    if (!node || node.nodeType !== 3 || skipped(node)) return;
    const current = node.nodeValue || "";
    let source = textSources.get(node);
    if (source === undefined) {
      source = current;
      textSources.set(node, source);
    } else if (language === "en" && current !== t(source) && HAN.test(current)) {
      source = current;
      textSources.set(node, source);
    }
    const next = language === "en" ? t(source) : source;
    if (current !== next) node.nodeValue = next;
  }

  function translateAttrs(el) {
    if (!el || el.nodeType !== 1 || skipped(el)) return;
    const sources = attrSources.get(el) || {};
    for (const attr of ATTRS) {
      if (!el.hasAttribute(attr)) continue;
      const current = el.getAttribute(attr) || "";
      if (!(attr in sources)) sources[attr] = current;
      else if (language === "en" && current !== t(sources[attr]) && HAN.test(current)) sources[attr] = current;
      const next = language === "en" ? t(sources[attr]) : sources[attr];
      if (current !== next) el.setAttribute(attr, next);
    }
    attrSources.set(el, sources);
  }

  function translateTree(root) {
    if (!root) return;
    applying = true;
    try {
      if (root.nodeType === 3) translateTextNode(root);
      if (root.nodeType === 1 || root.nodeType === 9) {
        if (root.nodeType === 1) translateAttrs(root);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (node.nodeType === 3) translateTextNode(node);
          else translateAttrs(node);
        }
      }
    } finally {
      applying = false;
    }
  }

  function syncToggle() {
    document.documentElement.lang = language === "en" ? "en" : "zh-CN";
    document.querySelectorAll("[data-lang-choice]").forEach(btn => {
      const active = btn.dataset.langChoice === language;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
  }

  function setLanguage(next) {
    language = next === "en" ? "en" : "zh";
    localStorage.setItem(STORAGE_KEY, language);
    syncToggle();
    translateTree(document);
    window.dispatchEvent(new CustomEvent("archrender:languagechange", { detail: { language } }));
  }

  function installToggle() {
    if (document.getElementById("languageSwitch")) return;
    const style = document.createElement("style");
    style.textContent = `
      .language-switch{position:fixed;top:12px;right:16px;z-index:10000;display:flex;align-items:center;
        gap:2px;padding:3px;background:rgba(30,27,21,.96);border:1px solid #514a3a;border-radius:999px;
        box-shadow:0 6px 22px rgba(0,0,0,.35);backdrop-filter:blur(8px)}
      .language-switch button{appearance:none;border:0;background:transparent;color:#9b9483;border-radius:999px;
        padding:6px 11px;font:700 11px/1 "Segoe UI",system-ui,sans-serif;letter-spacing:.08em;cursor:pointer}
      .language-switch button.active{background:#d9a441;color:#14130f}
      .language-switch button:focus-visible{outline:2px solid #f6f2e8;outline-offset:2px}
      @media(max-width:700px){.language-switch{top:8px;right:8px}.language-switch button{padding:6px 9px}}
    `;
    document.head.appendChild(style);
    const switcher = document.createElement("nav");
    switcher.id = "languageSwitch";
    switcher.className = "language-switch";
    switcher.setAttribute("aria-label", "Language");
    switcher.innerHTML = '<button type="button" data-lang-choice="zh" aria-label="Chinese">ZH</button><button type="button" data-lang-choice="en" aria-label="English">EN</button>';
    switcher.addEventListener("click", event => {
      const button = event.target.closest("[data-lang-choice]");
      if (button) setLanguage(button.dataset.langChoice);
    });
    document.body.appendChild(switcher);
    syncToggle();
  }

  const nativeAlert = window.alert ? window.alert.bind(window) : null;
  const nativeConfirm = window.confirm ? window.confirm.bind(window) : null;
  const nativePrompt = window.prompt ? window.prompt.bind(window) : null;
  if (nativeAlert) window.alert = message => nativeAlert(t(String(message ?? "")));
  if (nativeConfirm) window.confirm = message => nativeConfirm(t(String(message ?? "")));
  if (nativePrompt) window.prompt = (message, initial) => nativePrompt(t(String(message ?? "")), initial);

  window.I18N = {
    t,
    setLanguage,
    getLanguage: () => language,
    translate: translateTree,
    hasChinese: value => HAN.test(String(value || ""))
  };

  function init() {
    installToggle();
    translateTree(document);
    observer = new MutationObserver(records => {
      if (applying) return;
      for (const record of records) {
        if (record.type === "characterData") translateTextNode(record.target);
        else if (record.type === "attributes") translateAttrs(record.target);
        else record.addedNodes.forEach(translateTree);
      }
    });
    observer.observe(document.documentElement, {
      subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ATTRS
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
