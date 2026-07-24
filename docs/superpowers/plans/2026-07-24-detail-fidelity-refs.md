# 细部·必须保留（多参照单输出强忠实）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「细部·必须保留」角色，让主底图之外的细部图作为强忠实约束一起生图、并逐张进篡改检查。

**Architecture:** 方案 A——复用现有多图上传+逐张角色基建，新语义只落在 `prompt_engine`（角色表、生图分流、QC 提示词、QC 图序 helper）与 `app.py`（QC 调用点接线）；前端加一个下拉项 + i18n。不改底图单张模型与既有编辑流程。

**Tech Stack:** Python 3 / Flask、pytest、原生 JS 前端、`static/i18n.js` 词典。测试用 `.venv/bin/python -m pytest`。

---

### Task 1: prompt_engine 角色表加 `detail`

**Files:**
- Modify: `prompt_engine.py:323-333`（`REF_ROLE_EN` / `REF_ROLE_LABELS`）
- Test: `tests/test_detail_role.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_detail_role.py
# -*- coding: utf-8 -*-
import prompt_engine as pe


def test_detail_role_registered():
    assert pe.REF_ROLE_LABELS["detail"] == "细部·必须保留"
    en = pe.REF_ROLE_EN["detail"].lower()
    assert "faithfully reproduced" in en
    assert "must" in en
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: FAIL（KeyError: 'detail'）

- [ ] **Step 3: 加角色**

在 `prompt_engine.py` 的 `REF_ROLE_EN` 字典末尾（`"drawing"` 行后）加：

```python
    "detail":   "a DETAIL that MUST be faithfully reproduced — its exact content, geometry, proportions, materials and any text must appear in the output wherever that part is visible; treat it as binding as the base image",
```

在 `REF_ROLE_LABELS` 字典里 `"drawing": "图纸",` 后加：

```python
    "detail": "细部·必须保留",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add prompt_engine.py tests/test_detail_role.py
git commit -m "feat: prompt_engine 新增 detail 角色（细部·必须保留）"
```

---

### Task 2: `generation_message_multi` 按角色分流忠实约束

**Files:**
- Modify: `prompt_engine.py:336-355`（`generation_message_multi`）
- Test: `tests/test_detail_role.py`

- [ ] **Step 1: 写失败测试**

```python
def test_generation_message_detail_is_faithful_others_not():
    msg = pe.generation_message_multi("PROMPT", ["material", "detail"])
    # 细部图有强忠实措辞
    assert "faithfully reproduce" in msg.lower()
    # 非细部参照仍被禁止照抄形体
    assert "never copy" in msg.lower()


def test_generation_message_no_detail_keeps_blanket_rule():
    msg = pe.generation_message_multi("PROMPT", ["material", "mood"])
    assert "never copy a reference image" in msg.lower()
    assert "faithfully reproduce" not in msg.lower()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: FAIL（`test_generation_message_detail_is_faithful_others_not` 找不到 faithfully reproduce）

- [ ] **Step 3: 分流实现**

把 `generation_message_multi` 的函数体替换为（仅在 `role_lines` 之后、`return` 处改动，加 `copy_rule` 分流）：

```python
def generation_message_multi(prompt_en: str, roles, quality: str = "标准",
                             ratio: str = "跟随原图") -> str:
    """底图 + 多张参考图（意向/材质/图纸/细部）一起发给「生成对话」。
    roles：每张**参考图**（不含底图）一个角色键（见 REF_ROLE_EN），顺序与图片一致。
    细部图(role=detail)=强忠实、必须还原；其余参照绝不照抄形体。逐张枚举角色 +
    强制"直接出图、不要描述/分析"——多图时模型很容易转去分析描述而非生成。"""
    roles = list(roles or [])
    extras = " ".join(x for x in (QUALITY_HINTS.get(quality, ""),
                                  RATIO_HINTS.get(ratio, "")) if x)
    role_lines = "\n".join(
        f"- Image {idx + 2} is {REF_ROLE_EN.get(r, REF_ROLE_EN['generic'])}."
        for idx, r in enumerate(roles))
    # 细部图必须忠实还原；其余参照绝不照抄形体。分流表述，避免"绝不照抄"误伤细部图。
    if any(r == "detail" for r in roles):
        copy_rule = ("For reference images that are materials, mood, content or drawing "
                     "references, never copy their geometry, composition, camera or layout. "
                     "For DETAIL images, faithfully reproduce the detail they show in the "
                     "corresponding part of the BASE — its content, geometry, proportions, "
                     "materials and any text must match.")
    else:
        copy_rule = "Never copy a reference image's geometry, composition, camera or layout."
    return f"""I uploaded {len(roles) + 1} images. The FIRST image is the architectural BASE — keep its exact geometry, composition, camera, proportions and site content. The other images are references, each with a specific role:
{role_lines}
{copy_rule} Generate ONE photorealistic architectural render of the BASE image, applying the prompt below. Output the image directly — no questions, no explanation, do NOT describe or analyze the uploaded images. {extras}

{prompt_en}

{GENERATION_BASICS}"""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add prompt_engine.py tests/test_detail_role.py
git commit -m "feat: 生图提示词按角色分流——细部图强忠实、其余不照抄形体"
```

---

### Task 3: `qc_and_revise_prompt` 加 `detail_count`

**Files:**
- Modify: `prompt_engine.py:176-209`（`qc_and_revise_prompt`）
- Test: `tests/test_detail_role.py`

- [ ] **Step 1: 写失败测试**

```python
def test_qc_prompt_mentions_details_when_present():
    p = pe.qc_and_revise_prompt(3, detail_count=2)
    assert "中间 2 张" in p
    assert "细部" in p
    assert "逐张核对" in p


def test_qc_prompt_backward_compatible_without_details():
    p = pe.qc_and_revise_prompt(3)  # detail_count 默认 0
    assert "第二张为本轮生成图" in p
    assert "细部" not in p
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: FAIL（`qc_and_revise_prompt()` 不接受 detail_count 或缺"中间 2 张"）

- [ ] **Step 3: 实现（加参数 + 分支 intro/detail_line，其余正文不变）**

把 `qc_and_revise_prompt` 的签名与开头改为：

```python
def qc_and_revise_prompt(iteration: int, detail_count: int = 0) -> str:
    """把生成结果发回导演：查篡改 + 判断"精修/重画" + 给出对应修改依据（分析中文、指令英文）。
    detail_count>0 时图序为：第一张原图底图、中间 detail_count 张必须忠实还原的细部图、
    最后一张本轮生成图；并要求逐张核对细部忠实度。"""
    if detail_count > 0:
        intro = (f"这是第 {iteration} 轮的结果（第一张为忠实性参照的原图底图，"
                 f"中间 {detail_count} 张为必须忠实还原的细部图，最后一张为本轮生成图）。请执行三步：")
        detail_line = ("\n- 逐张核对每张细部图：它所示的部位是否在生成图对应位置被忠实还原"
                       "（内容、几何、比例、材质、文字都要对上）？有无遗漏、变形或替换？")
    else:
        intro = (f"这是第 {iteration} 轮的结果（第一张为忠实性参照的原图底图，"
                 f"第二张为本轮生成图）。请执行三步：")
        detail_line = ""
    return f"""{intro}

第一步【篡改检查】逐项对比生成图与原图底图：
- 建筑形体/轮廓/层数、开窗位置与比例是否一致？有没有凭空增删体块、构件、楼层？
- 直线是否仍笔直、竖线是否仍垂直？有没有弯曲、鼓胀、透视扭曲？
- 视角与透视是否偏移？特殊构件（格栅/连廊/坡道等）是否保留？
- 图中文字是否清晰端正、有没有扭曲变形或乱码？
- 画质评价：光影是否自然、材质是否真实、配景是否得当、有无过曝/塑料感。{detail_line}

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add prompt_engine.py tests/test_detail_role.py
git commit -m "feat: QC 提示词支持细部图逐张核对（detail_count，向后兼容）"
```

---

### Task 4: `qc_image_paths` helper（QC 图序组装）

**Files:**
- Modify: `prompt_engine.py`（在 `qc_and_revise_prompt` 后新增函数）
- Test: `tests/test_detail_role.py`

- [ ] **Step 1: 写失败测试**

```python
def test_qc_image_paths_orders_base_details_output():
    got = pe.qc_image_paths(
        "base.png", "out.png",
        ref_images=["m.png", "d1.png", "d2.png", "mood.png"],
        ref_roles=["material", "detail", "detail", "mood"])
    assert got == ["base.png", "d1.png", "d2.png", "out.png"]


def test_qc_image_paths_no_details():
    got = pe.qc_image_paths("base.png", "out.png", ref_images=["m.png"], ref_roles=["material"])
    assert got == ["base.png", "out.png"]


def test_qc_image_paths_tolerates_missing_roles():
    got = pe.qc_image_paths("base.png", "out.png", ref_images=None, ref_roles=None)
    assert got == ["base.png", "out.png"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: FAIL（`qc_image_paths` 未定义）

- [ ] **Step 3: 实现**

在 `prompt_engine.py` 的 `qc_and_revise_prompt` 函数之后加：

```python
def qc_image_paths(fidelity_base, output_img, ref_images=None, ref_roles=None):
    """QC 发给导演的图序：主底图 → 各细部图(role=detail，按上传序) → 本轮生成图。
    细部张数 = len(结果) - 2，喂给 qc_and_revise_prompt 的 detail_count。"""
    ref_images = list(ref_images or [])
    ref_roles = list(ref_roles or [])
    details = [img for img, role in zip(ref_images, ref_roles) if role == "detail"]
    return [fidelity_base, *details, output_img]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_detail_role.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add prompt_engine.py tests/test_detail_role.py
git commit -m "feat: qc_image_paths——QC 图序 主底图+细部+出图（可测）"
```

---

### Task 5: app.py QC 调用点接线

**Files:**
- Modify: `app.py:818-819`

- [ ] **Step 1: 改调用点**

把 `app.py:818-819`：

```python
                qc_reply = client.send(client.director_page, pe.qc_and_revise_prompt(i),
                                       image_paths=[fidelity_base, img_path])
```

替换为：

```python
                qc_imgs = pe.qc_image_paths(fidelity_base, img_path, ref_images, ref_roles)
                qc_reply = client.send(
                    client.director_page,
                    pe.qc_and_revise_prompt(i, detail_count=len(qc_imgs) - 2),
                    image_paths=qc_imgs)
```

- [ ] **Step 2: 语法检查**

Run: `.venv/bin/python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 全套件回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS（全绿）

- [ ] **Step 4: 提交**

```bash
git add app.py
git commit -m "feat: 主生图 QC 把细部图逐张纳入忠实检查"
```

---

### Task 6: 前端下拉项 + 意向图区文案 + i18n

**Files:**
- Modify: `templates/index.html`（`REF_ROLES` 常量；意向图 label）
- Modify: `static/i18n.js`（新增/更新中文串英文条目）
- Test: `tests/test_i18n.py`

- [ ] **Step 1: 前端 REF_ROLES 加 detail**

在 `templates/index.html` 找到 `const REF_ROLES = [...]`（约 927 行），把它替换为：

```javascript
const REF_ROLES = [["generic","通用参考"],["material","材质"],["mood","氛围/意向"],
                   ["content","换入内容/物件"],["drawing","图纸"],
                   ["detail","细部·必须保留"]];
```

- [ ] **Step 2: 更新意向图 label 文案**

在 `templates/index.html` 找到意向图 `<label>` 里那段 `<small>` 提示（约 435 行，以「可选多张；每张可选角色」开头），把该 `<small>` 文本整体替换为：

```
— 可选多张；每张可选角色（通用/材质/氛围/换入内容/图纸/细部·必须保留），标「细部·必须保留」的会当强忠实约束、逐张进篡改检查；不选=通用参考，都会连同底图发给生图 AI
```

- [ ] **Step 3: 跑 i18n 测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_i18n.py -q`
Expected: FAIL（`missing` 含「细部·必须保留」及新的 `<small>` 文案）

- [ ] **Step 4: 补 i18n 词典**

先定位旧意向图文案的英文键（会被替换掉）：
Run: `grep -n "可选多张" static/i18n.js`

在 `static/i18n.js` 顶层词典对象里：
1. 若存在旧「可选多张…」条目，删掉该行（文案已改）。
2. 加入以下两条（放在 `"Gemini 模型"` 之类的 UI 短语附近即可）：

```javascript
    "细部·必须保留": "Detail · must keep",
    "— 可选多张；每张可选角色（通用/材质/氛围/换入内容/图纸/细部·必须保留），标「细部·必须保留」的会当强忠实约束、逐张进篡改检查；不选=通用参考，都会连同底图发给生图 AI": "— optional, multiple allowed; pick a role per image (generic / material / mood / content / drawing / detail-must-keep). Images marked \"Detail · must keep\" are treated as strict fidelity constraints and checked one by one; unset = generic reference. All are sent to the image AI together with the base image.",
```

- [ ] **Step 5: 跑 i18n 测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_i18n.py -q`
Expected: PASS

- [ ] **Step 6: 全套件回归 + 提交**

```bash
.venv/bin/python -m pytest tests/ -q
git add templates/index.html static/i18n.js
git commit -m "feat: 前端加「细部·必须保留」角色项 + 意向图区文案 + 英文词典"
```

---

## Self-Review 记录

- **Spec 覆盖**：①角色→Task1；②生图分流→Task2；③QC 提示词→Task3、QC 图序→Task4、接线→Task5；④UI+i18n→Task6；测试贯穿各 Task。全覆盖。
- **占位符**：无 TBD/TODO；每个改动都给了完整代码或精确替换文本。
- **类型/命名一致**：`qc_image_paths(fidelity_base, output_img, ref_images, ref_roles)`、`qc_and_revise_prompt(iteration, detail_count=0)`、角色键 `detail` 在前后端与测试中一致。
- **边界**：QC 只纳入 role=detail 的参照图（不含 material/mood 等）；`detail_count=0` 向后兼容旧文案；增量精修/圈选/历史「用作底图」不动。
