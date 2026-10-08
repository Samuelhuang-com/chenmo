// 手寫板：記錄每一筆的座標、時間與壓力，並透過回呼即時送出。
import { drawAll } from "./ink.js";

export class BrushPad {
  constructor(canvas, cb = {}) {
    this.c = canvas;
    this.cb = cb;
    this.strokes = [];
    this.cur = null;
    this.buffer = [];
    this.seq = 0;
    this.raf = 0;
    this.enabled = true;          // false 時不接受書寫（手指滑動交給頁面捲動）
    canvas.addEventListener("pointerdown", e => this._down(e));
    canvas.addEventListener("pointermove", e => this._move(e));
    canvas.addEventListener("pointerup", e => this._up(e));
    canvas.addEventListener("pointercancel", e => this._up(e));
    canvas.addEventListener("contextmenu", e => e.preventDefault());
    new ResizeObserver(() => this.redraw()).observe(canvas);
    this.flusher = setInterval(() => this._flush(), 50);
    this.redraw();
  }
  get count() { return this.strokes.length; }
  _pt(e) {
    const r = this.c.getBoundingClientRect();
    return [
      +((e.clientX - r.left) / r.width).toFixed(4),
      +((e.clientY - r.top) / r.height).toFixed(4),
      Math.round(performance.now() - this.cur.tStart),
      e.pointerType === "pen" ? +(e.pressure || 0.5).toFixed(3) : 0.5,
    ];
  }
  _down(e) {
    if (this.cur || !this.enabled) return;
    e.preventDefault();
    this.c.setPointerCapture(e.pointerId);
    this.cb.onFirstTouch?.();
    this.seq += 1;
    this.cur = { seq: this.seq, t0: Date.now(), tStart: performance.now(), points: [], pid: e.pointerId };
    this.cb.onStrokeStart?.(this.cur.seq, this.cur.t0);
    this._add(e);
  }
  _move(e) {
    if (!this.cur || e.pointerId !== this.cur.pid) return;
    const list = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    (list.length ? list : [e]).forEach(ev => this._add(ev));
  }
  _add(e) {
    const p = this._pt(e);
    const last = this.cur.points[this.cur.points.length - 1];
    if (last && Math.abs(last[0] - p[0]) < 0.002 && Math.abs(last[1] - p[1]) < 0.002) return;
    this.cur.points.push(p);
    this.buffer.push(p);
    this._schedule();
  }
  _up(e) {
    if (!this.cur || e.pointerId !== this.cur.pid) return;
    this._flush();
    this.strokes.push({ seq: this.cur.seq, t0: this.cur.t0, points: this.cur.points });
    this.cb.onStrokeEnd?.(this.cur.seq);
    this.cur = null;
    this._schedule();
  }
  _flush() {
    if (this.cur && this.buffer.length) this.cb.onPoints?.(this.cur.seq, this.buffer.splice(0));
  }
  _schedule() {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.redraw(); });
  }
  redraw() {
    const all = this.cur ? [...this.strokes, this.cur] : this.strokes;
    drawAll(this.c, all);
  }
  undo() {
    if (this.cur || !this.strokes.length) return false;
    this.strokes.pop(); this.redraw(); this.cb.onUndo?.(); return true;
  }
  clear() {
    if (this.cur || !this.strokes.length) return false;
    this.strokes = []; this.redraw(); this.cb.onClear?.(); return true;
  }
}
