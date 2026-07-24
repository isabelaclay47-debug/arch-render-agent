# 细部·必须保留（多参照单输出的强忠实）设计

日期：2026-07-24
状态：已确认（待写实现计划）
范围：单个实现计划可覆盖

## 背景与问题

当前流程假设**只有一张底图**：第 1 张图是「必须严格忠实的原图底图」，其余上传图都是
「意向图」，角色限 `generic/material/mood/content/drawing`，语义**一律"只借氛围/材质、
绝不照抄形体"**。用户的真实需求是「一张主图 + 若干必须忠实保留的细部图，合成到同一张
出图里」——现有角色体系没有"这张细部必须被忠实还原"这一强忠实类别。

用户已明确选择：**最严 QC——每张细部都逐张进篡改检查**（认可由此多发 N 张图、更耗
额度与时间）。

## 方案

采用**方案 A：在现有意向图体系里新增一个 `detail` 角色**，复用已跑通的多图上传 +
逐张角色下拉基建，新语义只落在 `prompt_engine` 与 QC 两处。不改 `base_image` 的单张模型，
不改历史「用作底图」、圈选局部修改、增量精修。

### ① 角色模型（`prompt_engine.py` + 前端）

- 新增角色键 `detail`，中文标签「细部·必须保留」。
- `REF_ROLE_EN["detail"]`（强忠实，与其它角色相反）：
  > a DETAIL that MUST be faithfully reproduced — its exact content, geometry,
  > proportions, materials and any text must appear in the output wherever that
  > part is visible; treat it as binding as the base image.
- `REF_ROLE_LABELS["detail"] = "细部·必须保留"`。
- 前端 `REF_ROLES` 追加 `["detail","细部·必须保留"]`。
- `i18n.js` 补「细部·必须保留」及更新后的意向图区提示文案的英文条目。

### ② 生图（`generation_message_multi`）

现 footer 一刀切「Never copy a reference image's geometry, composition, camera or
layout.」——与细部图冲突。改为**按角色分流**：

- 非细部参照（材质/氛围/内容/图纸）：保持"绝不照抄其形体/构图/相机/布局"。
- 细部图（role=detail）：单列硬约束段——"忠实还原它所示的细部到底图对应部位（内容、
  几何、比例、材质、文字都要对上），其约束力等同底图"。

细部图属于 `ref_images`，已随每轮"从原图重画"一并发送（`app.py:796-802`），无需新穿线。

### ③ QC 忠实检查（`app.py` QC 处 + `qc_and_revise_prompt`）

- 现在发 `[fidelity_base, img_path]`。改为 `[fidelity_base, *detail_imgs, img_path]`，
  其中 `detail_imgs` = 本次 `ref_images` 中 role==detail 的图（保持上传顺序）。
- `qc_and_revise_prompt` 增参数 `detail_count`（默认 0，向后兼容）。提示词说明图片顺序
  「第一张=原图底图，中间 detail_count 张=必须忠实还原的细部图，最后一张=本轮生成图」，
  并新增一步「逐张核对每张细部是否在出图对应部位被忠实还原」。不一致 → 计入
  `<精修指令>`（精修）或 `<新提示词>`（重画）。`<忠实度>/<下一步>/<结论>` 输出格式不变。
- QC 每轮都查细部（重画轮与增量精修轮一致）；细部图全会话可用。

### ④ UI（`index.html` + `i18n.js`）

- 前端 `REF_ROLES` 加入 `detail` 项。
- 意向图区 label 提示（`index.html:435` 附近）更新，加入「细部·必须保留」说明其为强忠实。
- 更新/新增的中文可见串补 `i18n.js` 英文条目（`test_i18n` 护栏强制）。

## 边界与不做的事（YAGNI）

- 不把 `base_image` 改成多张列表（方案 C 已否决，风险最高）。
- 圈选局部修改、增量精修、历史「用作底图」不动。
- 增量精修轮不重发细部图（它只在上一张出图上打补丁）；但 QC 仍查细部。

## 测试

- `generation_message_multi`：roles 含 `detail` → 断言出现细部硬约束措辞，且"绝不照抄形体"
  只作用于非 detail 参照。
- `qc_and_revise_prompt(iteration, detail_count>0)`：断言措辞含"中间 N 张细部"与逐张核对步骤；
  `detail_count=0` 时与旧文案等价（向后兼容）。
- QC 图集组装抽成可测小函数，断言顺序 = `[fidelity_base, *detail_imgs, output]`。
- i18n：新增/改动的中文串均有英文条目（现有 `test_i18n` 覆盖）。

## 影响文件

- `prompt_engine.py`：REF_ROLE_EN/REF_ROLE_LABELS 加 detail；generation_message_multi 分流；
  qc_and_revise_prompt 加 detail_count。
- `app.py`：QC 图集组装（抽小函数）+ 传 detail_count。
- `templates/index.html`：前端 REF_ROLES + 意向图区文案。
- `static/i18n.js`：新中文串英文条目。
- `tests/`：新增 prompt_engine 与 QC 组装的单测。
