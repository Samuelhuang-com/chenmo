// 墨跡繪製：依筆速改變粗細，模擬毛筆「慢則粗、快則細」。
const INK = "#1f1b17";
const ZHU = "#b23a2e";

export function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

// pts: [[x, y, dt, pressure], ...]，x/y 為 0–1
export function drawStroke(ctx, pts, w, h, upto = Infinity, color = INK) {
  if (!pts || !pts.length) return;
  const base = Math.min(w, h) * 0.027;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  let px = pts[0][0] * w, py = pts[0][1] * h;
  let width = base * 1.1;
  if (pts.length === 1 || (pts[1] && pts[1][2] > upto)) {
    ctx.beginPath(); ctx.arc(px, py, width / 2, 0, Math.PI * 2); ctx.fill();
    return;
  }
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i];
    if (p[2] > upto) break;
    const x = p[0] * w, y = p[1] * h;
    const dist = Math.hypot(x - px, y - py);
    const dt = Math.max(p[2] - pts[i - 1][2], 1);
    const v = dist / dt; // px/ms
    let target = base * Math.min(Math.max(1.55 - v * 0.9, 0.45), 1.6);
    const pr = p[3];
    if (pr != null && pr !== 0.5 && pr > 0) target *= 0.55 + pr; // 觸控筆壓力
    width = width * 0.72 + target * 0.28;
    ctx.lineWidth = width;
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
    px = x; py = y;
  }
}

export function drawNumber(ctx, n, pt, w, h) {
  if (!pt) return;
  const x = Math.min(Math.max(pt[0] * w - 14, 4), w - 18);
  const y = Math.min(Math.max(pt[1] * h - 14, 4), h - 18);
  ctx.fillStyle = ZHU;
  ctx.beginPath(); ctx.arc(x + 7, y + 7, 9, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#ede5d3";
  ctx.font = "600 11px 'Noto Serif TC', serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(String(n), x + 7, y + 7.5);
}

export function drawAll(canvas, strokes, { numbers = false, highlightLast = false } = {}) {
  const { ctx, w, h } = fitCanvas(canvas);
  strokes.forEach((s, i) => {
    const last = highlightLast && i === strokes.length - 1;
    drawStroke(ctx, s.points, w, h, s.upto ?? Infinity, last ? ZHU : INK);
  });
  if (numbers) strokes.forEach((s, i) => drawNumber(ctx, i + 1, s.points[0], w, h));
}

export function visibleStrokes(events) {
  let out = [];
  for (const ev of events) {
    if (ev.type === "stroke") out.push(ev);
    else if (ev.type === "undo") out.pop();
    else if (ev.type === "clear") out = [];
  }
  return out;
}
