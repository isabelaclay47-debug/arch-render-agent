/* 底图标注工作室（PS-lite）阶段 1：箭头/文字/椭圆/画笔/直线/框选/橡皮擦 + 颜色/粗细。
   自成一体，不依赖也不改动"生成图局部修改"画板。
   用法：openAnnotate(imgSrcUrl, (flatDataUrl)=>{...})  完成时回传压平后的 PNG dataURL。 */
(function () {
  const A = {
    ops: [], tool: "brush", color: "#e12020", size: 6,
    img: null, natW: 0, natH: 0, scale: 1, drawing: null, onDone: null,
  };
  let canvas, ctx;

  const TOOLS = [
    ["brush", "画笔"], ["line", "直线"], ["arrow", "箭头"],
    ["rect", "矩形"], ["ellipse", "椭圆"], ["text", "文字"], ["eraser", "橡皮擦"],
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
        <div class="ann-hint">画笔按住拖 · 直线/箭头/矩形/椭圆 拖出 · 文字点一下再输入 · 橡皮擦点掉标记</div>
      </div>`;
    document.body.appendChild(wrap);
    canvas = document.getElementById("annCanvas");
    ctx = canvas.getContext("2d");

    wrap.querySelectorAll(".ann-t[data-tool]").forEach(b =>
      b.addEventListener("click", () => setTool(b.dataset.tool)));
    document.getElementById("annColor").addEventListener("input", e => A.color = e.target.value);
    document.getElementById("annSize").addEventListener("input", e => A.size = +e.target.value);
    document.getElementById("annUndo").addEventListener("click", () => { A.ops.pop(); render(); });
    document.getElementById("annClear").addEventListener("click", () => { A.ops = []; render(); });
    document.getElementById("annCancel").addEventListener("click", close);
    document.getElementById("annDone").addEventListener("click", done);

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
  }

  function setTool(t) {
    A.tool = t;
    document.querySelectorAll("#annStudio .ann-t[data-tool]").forEach(b =>
      b.classList.toggle("on", b.dataset.tool === t));
  }

  function pos(e) {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * canvas.width / r.width,
            (e.clientY - r.top) * canvas.height / r.height];
  }

  function onDown(e) {
    e.preventDefault(); canvas.setPointerCapture(e.pointerId);
    const [x, y] = pos(e);
    if (A.tool === "text") {
      const txt = prompt("输入文字：");
      if (txt) { A.ops.push({ tool: "text", color: A.color, size: A.size * 3, x, y, text: txt }); render(); }
      return;
    }
    if (A.tool === "eraser") { eraseAt(x, y); A.drawing = { tool: "eraser" }; return; }
    if (A.tool === "brush") A.drawing = { tool: "brush", color: A.color, size: A.size, pts: [[x, y]] };
    else A.drawing = { tool: A.tool, color: A.color, size: A.size, x0: x, y0: y, x1: x, y1: y };
    render();
  }
  function onMove(e) {
    if (!A.drawing) return;
    const [x, y] = pos(e);
    if (A.drawing.tool === "eraser") { eraseAt(x, y); return; }
    if (A.drawing.tool === "brush") A.drawing.pts.push([x, y]);
    else { A.drawing.x1 = x; A.drawing.y1 = y; }
    render();
  }
  function onUp() {
    if (!A.drawing) return;
    if (A.drawing.tool !== "eraser") A.ops.push(A.drawing);
    A.drawing = null; render();
  }

  function eraseAt(x, y) {
    const R = Math.max(14, canvas.width / 40);
    for (let i = A.ops.length - 1; i >= 0; i--) {
      if (hit(A.ops[i], x, y, R)) { A.ops.splice(i, 1); render(); return; }
    }
  }
  function hit(op, x, y, R) {
    if (op.tool === "text") return Math.abs(x - op.x) < op.size * op.text.length && Math.abs(y - op.y) < op.size;
    if (op.pts) return op.pts.some(p => Math.hypot(x - p[0], y - p[1]) <= R);
    const xs = [op.x0, op.x1], ys = [op.y0, op.y1];
    return x >= Math.min(...xs) - R && x <= Math.max(...xs) + R &&
           y >= Math.min(...ys) - R && y <= Math.max(...ys) + R;
  }

  function drawOp(c, op, k) {
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
    ctx.drawImage(A.img, 0, 0, canvas.width, canvas.height);
    [...A.ops, A.drawing].filter(Boolean).forEach(op => drawOp(ctx, op, 1));
  }

  function openAnnotate(src, onDone) {
    ensureDom();
    A.ops = []; A.drawing = null; A.onDone = onDone;
    setTool("brush");
    const img = new Image();
    img.onload = () => {
      A.img = img; A.natW = img.naturalWidth; A.natH = img.naturalHeight;
      const cap = 1400, sc = Math.min(1, cap / Math.max(img.width, img.height));
      A.scale = sc;
      canvas.width = Math.round(img.width * sc);
      canvas.height = Math.round(img.height * sc);
      render();
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
