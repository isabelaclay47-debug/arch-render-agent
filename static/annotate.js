/* 底图标注工作室（PS-lite）阶段 1：箭头/文字/椭圆/画笔/直线/框选/橡皮擦 + 颜色/粗细。
   自成一体，不依赖也不改动"生成图局部修改"画板。
   用法：openAnnotate(imgSrcUrl, (flatDataUrl)=>{...})  完成时回传压平后的 PNG dataURL。 */
(function () {
  const A = {
    ops: [], tool: "brush", color: "#e12020", size: 6,
    img: null, natW: 0, natH: 0, scale: 1, drawing: null, onDone: null,
    sel: null, act: null,          // sel=选中的 op 下标；act=当前移动/缩放动作
  };
  let canvas, ctx;

  const TOOLS = [
    ["select", "选择"], ["brush", "画笔"], ["line", "直线"], ["arrow", "箭头"],
    ["rect", "矩形"], ["ellipse", "椭圆"], ["pen", "钢笔选取"],
    ["text", "文字"], ["eraser", "橡皮擦"],
  ];

  function ensureDom() {
    if (document.getElementById("annStudio")) return;
    const wrap = document.createElement("div");
    wrap.id = "annStudio";
    wrap.innerHTML = `
      <div class="ann-box">
        <div class="ann-tools">
          <b>✏️ 标注底图</b>
          <span class="ann-toolset">
            ${TOOLS.map(([t, n]) => `<button class="ann-t" data-tool="${t}">${n}</button>`).join("")}
          </span>
          <label class="ann-ctl">颜色 <input type="color" id="annColor" value="#e12020"></label>
          <label class="ann-ctl">粗细 <input type="range" id="annSize" min="2" max="40" value="6"></label>
          <button class="ann-t" id="annUndo">撤销</button>
          <button class="ann-t" id="annClear">清空</button>
          <span style="flex:1"></span>
          <button class="ann-t ann-cancel" id="annCancel">取消</button>
          <button class="ann-t ann-done" id="annDone">完成标注</button>
        </div>
        <canvas id="annCanvas"></canvas>
        <div class="ann-hint"><b>选择</b>：点任意标注→拖动移位、拖右下角缩放、<b>双击文字改内容</b> · 画笔按住拖 · 直线/箭头/矩形/椭圆 拖出 · 钢笔逐点点击、<b>双击闭合</b> · 文字点一下再输入 · 橡皮擦点掉标记</div>
      </div>`;
    document.body.appendChild(wrap);
    canvas = document.getElementById("annCanvas");
    ctx = canvas.getContext("2d");

    wrap.querySelectorAll(".ann-t[data-tool]").forEach(b =>
      b.addEventListener("click", () => setTool(b.dataset.tool)));
    document.getElementById("annColor").addEventListener("input", e => A.color = e.target.value);
    document.getElementById("annSize").addEventListener("input", e => A.size = +e.target.value);
    document.getElementById("annUndo").addEventListener("click", undo);
    document.getElementById("annClear").addEventListener("click", () => { A.ops = []; A.drawing = null; A.sel = null; A.act = null; render(); });
    document.getElementById("annCancel").addEventListener("click", close);
    document.getElementById("annDone").addEventListener("click", done);

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("dblclick", onDblClick);
  }

  function undo() {
    if (A.drawing && A.drawing.tool === "pen") {   // 正在点钢笔选区：退一个锚点
      A.drawing.pts.pop();
      if (!A.drawing.pts.length) A.drawing = null;
    } else A.ops.pop();
    A.sel = null; A.act = null;                    // 标注列表变了，选中框失效
    render();
  }

  function setTool(t) {
    // 切走时若有没闭合的钢笔选区，丢弃挂起的路径
    if (t !== "pen" && A.drawing && A.drawing.tool === "pen") A.drawing = null;
    if (t !== "select") { A.sel = null; A.act = null; }   // 离开选择工具即清掉选中框
    A.tool = t;
    document.querySelectorAll("#annStudio .ann-t[data-tool]").forEach(b =>
      b.classList.toggle("on", b.dataset.tool === t));
    canvas.style.cursor = t === "select" ? "move" : (t === "eraser" ? "cell" : "crosshair");
    render();
  }

  // ---- 通用几何：任意标注的包围盒/平移/缩放，供「选择」工具二次编辑（移动·缩放·改字）----
  function _bx(x0, y0, x1, y1) {
    return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
  }
  function bboxOf(op) {
    if (op.tool === "stamp") return { x: op.x, y: op.y, w: op.w, h: op.h };
    if (op.tool === "text") {
      ctx.font = `bold ${op.size}px "Microsoft YaHei", sans-serif`;
      return { x: op.x, y: op.y, w: Math.max(14, ctx.measureText(op.text).width), h: op.size };
    }
    if (op.pts) {
      const xs = op.pts.map(p => p[0]), ys = op.pts.map(p => p[1]);
      return _bx(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys));
    }
    return _bx(op.x0, op.y0, op.x1, op.y1);
  }
  function moveOp(op, dx, dy) {
    if (op.tool === "stamp" || op.tool === "text") { op.x += dx; op.y += dy; return; }
    if (op.pts) { op.pts = op.pts.map(p => [p[0] + dx, p[1] + dy]); return; }
    op.x0 += dx; op.x1 += dx; op.y0 += dy; op.y1 += dy;
  }
  // 把 op 的包围盒左上角固定，右下角缩放到 (bb.x+nw, bb.y+nh)
  function scaleOp(op, bb, nw, nh) {
    const sx = bb.w ? nw / bb.w : 1, sy = bb.h ? nh / bb.h : 1;
    if (op.tool === "stamp") { op.w = Math.max(20, nw); op.h = Math.max(20, nh); return; }
    if (op.tool === "text") { op.size = Math.max(8, op.size * ((sx + sy) / 2)); return; }
    const fx = x => bb.x + (x - bb.x) * sx, fy = y => bb.y + (y - bb.y) * sy;
    if (op.pts) { op.pts = op.pts.map(p => [fx(p[0]), fy(p[1])]); return; }
    op.x0 = fx(op.x0); op.x1 = fx(op.x1); op.y0 = fy(op.y0); op.y1 = fy(op.y1);
  }
  function pickTop(x, y) {                    // 命中最上面（最后画的）那个标注，返回下标
    for (let i = A.ops.length - 1; i >= 0; i--) {
      const bb = bboxOf(A.ops[i]), R = 8;
      if (x >= bb.x - R && x <= bb.x + bb.w + R && y >= bb.y - R && y <= bb.y + bb.h + R) return i;
    }
    return null;
  }
  function onResizeHandle(bb, x, y) {         // 是否点在右下角缩放手柄上
    const HS = Math.max(10, canvas.width / 90);
    return Math.abs(x - (bb.x + bb.w)) <= HS && Math.abs(y - (bb.y + bb.h)) <= HS;
  }

  function pos(e) {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * canvas.width / r.width,
            (e.clientY - r.top) * canvas.height / r.height];
  }

  function onDown(e) {
    e.preventDefault(); canvas.setPointerCapture(e.pointerId);
    const [x, y] = pos(e);
    if (A.tool === "select") {              // 选择/移动：点已有标注→选中，拖动=移动，拖右下角=缩放
      if (A.sel != null && A.ops[A.sel]) {
        const bb = bboxOf(A.ops[A.sel]);
        if (onResizeHandle(bb, x, y)) { A.act = { mode: "resize", bb }; return; }
      }
      const idx = pickTop(x, y);
      A.sel = idx;
      if (idx != null) A.act = { mode: "move", lx: x, ly: y };
      render(); return;
    }
    const sh = _hitStamp(x, y);            // 图章优先：命中已贴配景就拖动/缩放（跨工具，橡皮擦除外）
    if (sh && A.tool !== "eraser") { A.stampAct = sh; return; }
    if (A.tool === "text") {
      const txt = prompt("输入文字：");
      if (txt) { A.ops.push({ tool: "text", color: A.color, size: A.size * 3, x, y, text: txt }); render(); }
      return;
    }
    if (A.tool === "eraser") { eraseAt(x, y); A.drawing = { tool: "eraser" }; return; }
    if (A.tool === "pen") {                       // 钢笔选取：逐点点击、双击/点回起点闭合成选区
      if (A.drawing && A.drawing.tool === "pen") {
        const first = A.drawing.pts[0], R = Math.max(8, canvas.width / 130);
        if (A.drawing.pts.length >= 3 && Math.hypot(x - first[0], y - first[1]) <= R) closePen();
        else { A.drawing.pts.push([x, y]); render(); }
      } else {
        A.drawing = { tool: "pen", color: A.color, size: A.size, pts: [[x, y]], closed: false };
        render();
      }
      return;
    }
    if (A.tool === "brush") A.drawing = { tool: "brush", color: A.color, size: A.size, pts: [[x, y]] };
    else A.drawing = { tool: A.tool, color: A.color, size: A.size, x0: x, y0: y, x1: x, y1: y };
    render();
  }
  function onMove(e) {
    const [x, y] = pos(e);
    if (A.act) {                            // 选择工具：移动或缩放选中的标注
      const op = A.ops[A.sel];
      if (!op) { A.act = null; return; }
      if (A.act.mode === "move") { moveOp(op, x - A.act.lx, y - A.act.ly); A.act.lx = x; A.act.ly = y; }
      else { scaleOp(op, A.act.bb, x - A.act.bb.x, y - A.act.bb.y); A.act.bb = bboxOf(op); }
      render(); return;
    }
    if (A.stampAct) {                       // 拖动/缩放图章
      const s = A.stampAct;
      if (s.mode === "move") { s.op.x = x - s.dx; s.op.y = y - s.dy; }
      else { s.op.w = Math.max(20, x - s.op.x); s.op.h = Math.max(20, y - s.op.y); }
      render(); return;
    }
    if (!A.drawing) return;
    if (A.drawing.tool === "eraser") { eraseAt(x, y); return; }
    if (A.drawing.tool === "pen") { A.drawing.hover = [x, y]; render(); return; }
    if (A.drawing.tool === "brush") A.drawing.pts.push([x, y]);
    else { A.drawing.x1 = x; A.drawing.y1 = y; }
    render();
  }
  function onDblClick(e) {
    if (A.tool === "select") {              // 双击选中的文字→改内容（其余类型忽略）
      const [x, y] = pos(e);
      const idx = A.sel != null ? A.sel : pickTop(x, y);
      const op = idx != null ? A.ops[idx] : null;
      if (op && op.tool === "text") {
        const t = prompt("修改文字：", op.text);
        if (t != null && t.trim()) { op.text = t.trim(); A.sel = idx; render(); }
      }
      return;
    }
    if (A.drawing && A.drawing.tool === "pen" && A.drawing.pts.length >= 3) closePen();
  }
  function closePen() {
    A.drawing.closed = true; delete A.drawing.hover;
    A.ops.push(A.drawing); A.drawing = null; render();
  }
  function onUp() {
    if (A.act) { A.act = null; return; }              // 结束选择工具的移动/缩放
    if (A.stampAct) { A.stampAct = null; return; }   // 结束图章拖动/缩放
    if (!A.drawing) return;
    if (A.drawing.tool === "pen") return;   // 钢笔选区由点击/双击控制，pointerup 不结束
    if (A.drawing.tool !== "eraser") A.ops.push(A.drawing);
    A.drawing = null; render();
  }

  function eraseAt(x, y) {
    const R = Math.max(14, canvas.width / 40);
    for (let i = A.ops.length - 1; i >= 0; i--) {
      if (hit(A.ops[i], x, y, R)) { A.ops.splice(i, 1); A.sel = null; A.act = null; render(); return; }
    }
  }
  function hit(op, x, y, R) {
    if (op.tool === "stamp") return x >= op.x - R && x <= op.x + op.w + R && y >= op.y - R && y <= op.y + op.h + R;
    if (op.tool === "text") return Math.abs(x - op.x) < op.size * op.text.length && Math.abs(y - op.y) < op.size;
    if (op.pts) return op.pts.some(p => Math.hypot(x - p[0], y - p[1]) <= R);
    const xs = [op.x0, op.x1], ys = [op.y0, op.y1];
    return x >= Math.min(...xs) - R && x <= Math.max(...xs) + R &&
           y >= Math.min(...ys) - R && y <= Math.max(...ys) + R;
  }

  function drawOp(c, op, k, decorate) {
    if (op.tool === "stamp") {                 // 配景图章：直接把素材图画上去
      if (op.img && op.img.complete) c.drawImage(op.img, op.x * k, op.y * k, op.w * k, op.h * k);
      if (decorate) {                          // 编辑时才画选框+缩放手柄；压平输出(done)不画
        c.save();
        c.strokeStyle = "#3a7bd5"; c.setLineDash([5, 4]); c.lineWidth = 1.5;
        c.strokeRect(op.x * k, op.y * k, op.w * k, op.h * k);
        c.setLineDash([]);
        const hs = 9; c.fillStyle = "#3a7bd5";
        c.fillRect((op.x + op.w) * k - hs / 2, (op.y + op.h) * k - hs / 2, hs, hs);
        c.restore();
      }
      return;
    }
    c.strokeStyle = op.color; c.fillStyle = op.color;
    c.lineWidth = op.size * k; c.lineCap = c.lineJoin = "round";
    if (op.tool === "brush") {
      c.beginPath(); op.pts.forEach((p, i) => i ? c.lineTo(p[0] * k, p[1] * k) : c.moveTo(p[0] * k, p[1] * k)); c.stroke();
    } else if (op.tool === "line" || op.tool === "arrow") {
      c.beginPath(); c.moveTo(op.x0 * k, op.y0 * k); c.lineTo(op.x1 * k, op.y1 * k); c.stroke();
      if (op.tool === "arrow") arrowHead(c, op, k);
    } else if (op.tool === "rect") {
      c.strokeRect(op.x0 * k, op.y0 * k, (op.x1 - op.x0) * k, (op.y1 - op.y0) * k);
    } else if (op.tool === "ellipse") {
      c.beginPath();
      c.ellipse((op.x0 + op.x1) / 2 * k, (op.y0 + op.y1) / 2 * k,
        Math.abs(op.x1 - op.x0) / 2 * k, Math.abs(op.y1 - op.y0) / 2 * k, 0, 0, 7); c.stroke();
    } else if (op.tool === "pen") {
      c.lineWidth = Math.max(2, op.size * k / 2);
      c.beginPath();
      op.pts.forEach((p, i) => i ? c.lineTo(p[0] * k, p[1] * k) : c.moveTo(p[0] * k, p[1] * k));
      if (op.closed) {                       // 闭合选区：半透明填充 + 描边
        c.closePath();
        c.save(); c.globalAlpha = 0.28; c.fill(); c.restore();
        c.stroke();
      } else {                               // 未闭合：连到光标的橡皮筋 + 各锚点小圆
        if (op.hover) c.lineTo(op.hover[0] * k, op.hover[1] * k);
        c.stroke();
        const R = Math.max(3, canvas.width / 260);
        op.pts.forEach(p => { c.beginPath(); c.arc(p[0] * k, p[1] * k, R, 0, 7); c.fill(); });
      }
    } else if (op.tool === "text") {
      c.font = `bold ${op.size * k}px "Microsoft YaHei", sans-serif`;
      c.textBaseline = "top"; c.fillText(op.text, op.x * k, op.y * k);
    }
  }
  function arrowHead(c, op, k) {
    const a = Math.atan2((op.y1 - op.y0), (op.x1 - op.x0)), L = Math.max(12, op.size * k * 2.2);
    const x1 = op.x1 * k, y1 = op.y1 * k;
    c.beginPath(); c.moveTo(x1, y1);
    c.lineTo(x1 - L * Math.cos(a - 0.4), y1 - L * Math.sin(a - 0.4));
    c.moveTo(x1, y1);
    c.lineTo(x1 - L * Math.cos(a + 0.4), y1 - L * Math.sin(a + 0.4)); c.stroke();
  }

  function render() {
    if (!A.img) return;   // 图未加载完（如初始 setTool）时不画，避免 drawImage(null) 报错
    ctx.drawImage(A.img, 0, 0, canvas.width, canvas.height);
    [...A.ops, A.drawing].filter(Boolean).forEach(op => drawOp(ctx, op, 1, true));
    if (A.tool === "select" && A.sel != null && A.ops[A.sel]) {   // 选中标注：蓝色虚线框 + 右下角缩放手柄
      const bb = bboxOf(A.ops[A.sel]);
      ctx.save();
      ctx.strokeStyle = "#3a7bd5"; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
      ctx.strokeRect(bb.x, bb.y, bb.w, bb.h);
      ctx.setLineDash([]); ctx.fillStyle = "#3a7bd5";
      const hs = 9; ctx.fillRect(bb.x + bb.w - hs / 2, bb.y + bb.h - hs / 2, hs, hs);
      ctx.restore();
    }
  }

  // 配景图章命中检测：右下角手柄→缩放，图章内部→移动。跨工具生效（贴完仍可随时拖）
  function _hitStamp(x, y) {
    const HS = Math.max(10, canvas.width / 90);
    for (let i = A.ops.length - 1; i >= 0; i--) {
      const op = A.ops[i];
      if (op.tool !== "stamp") continue;
      if (Math.abs(x - (op.x + op.w)) <= HS && Math.abs(y - (op.y + op.h)) <= HS)
        return { op, mode: "resize" };
      if (x >= op.x && x <= op.x + op.w && y >= op.y && y <= op.y + op.h)
        return { op, mode: "move", dx: x - op.x, dy: y - op.y };
    }
    return null;
  }

  // 从素材库点「贴到标注」后，把该配景图作为可拖拽/缩放的图章贴到画布
  function _consumePendingStamp() {
    const p = window._pendingStamp;
    if (!p || !p.url) return;
    window._pendingStamp = null;
    const st = new Image();
    st.onload = () => {
      const ar = (st.naturalWidth / st.naturalHeight) || 1;
      let w = canvas.width * 0.35, h = w / ar;
      if (h > canvas.height * 0.6) { h = canvas.height * 0.6; w = h * ar; }
      A.ops.push({ tool: "stamp", img: st,
                   x: (canvas.width - w) / 2, y: (canvas.height - h) / 2, w, h });
      setTool("brush");   // 贴好后切回普通工具避免误画；图章仍可直接拖动/缩放
      render();
    };
    st.src = p.url;       // 同源 /asset_images/，画布不会被污染，done() 仍可导出
  }

  function openAnnotate(src, onDone) {
    ensureDom();
    A.ops = []; A.drawing = null; A.sel = null; A.act = null; A.onDone = onDone;
    setTool("brush");
    const img = new Image();
    img.onload = () => {
      A.img = img; A.natW = img.naturalWidth; A.natH = img.naturalHeight;
      const cap = 1400, sc = Math.min(1, cap / Math.max(img.width, img.height));
      A.scale = sc;
      canvas.width = Math.round(img.width * sc);
      canvas.height = Math.round(img.height * sc);
      render();
      _consumePendingStamp();   // 若从素材库点了"贴到标注"，把配景作为图章贴上
      document.getElementById("annStudio").style.display = "flex";
    };
    img.src = src;
  }

  function done() {
    // 压平到原图分辨率，标注按比例放大，保画质
    const out = document.createElement("canvas");
    out.width = A.natW; out.height = A.natH;
    const oc = out.getContext("2d");
    oc.drawImage(A.img, 0, 0, A.natW, A.natH);
    const k = A.natW / canvas.width;
    A.ops.forEach(op => drawOp(oc, op, k));
    const dataUrl = out.toDataURL("image/png");
    close();
    if (A.onDone) A.onDone(dataUrl);
  }
  function close() { const el = document.getElementById("annStudio"); if (el) el.style.display = "none"; }

  window.openAnnotate = openAnnotate;
})();
