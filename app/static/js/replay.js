// 筆畫重播：依真實書寫時間重現每一筆。筆與筆之間的長停頓會壓縮（最長 1.2 秒），
// 真實停頓秒數另外列在筆跡紀錄表中。
import { drawAll, visibleStrokes } from "./ink.js";

const MAX_GAP = 1200, MIN_GAP = 150, ERASE_PAUSE = 400;

export function strokeDuration(s) {
  const p = s.points; return p.length ? Math.max(p[p.length - 1][2], 1) : 1;
}

export function buildTimeline(events, includeErased) {
  const src = includeErased ? events.filter(e => ["stroke", "undo", "clear"].includes(e.type))
                            : visibleStrokes(events);
  const ops = [];
  let t = 0, prevEnd = null;
  for (const ev of src) {
    if (ev.type === "stroke") {
      if (prevEnd !== null) {
        const real = ev.t0 - prevEnd;
        t += Math.min(Math.max(real, MIN_GAP), MAX_GAP);
      }
      const dur = strokeDuration(ev);
      ops.push({ kind: "stroke", ev, start: t, end: t + dur });
      t += dur;
      prevEnd = ev.t0 + dur;
    } else {
      t += ERASE_PAUSE;
      ops.push({ kind: ev.type, start: t, end: t });
      t += ERASE_PAUSE;
    }
  }
  return { ops, total: t };
}

export function stateAt(ops, time) {
  let strokes = [];
  for (const op of ops) {
    if (op.start > time) break;
    if (op.kind === "stroke") strokes.push({ points: op.ev.points, upto: time - op.start });
    else if (op.kind === "undo") strokes.pop();
    else if (op.kind === "clear") strokes = [];
  }
  return strokes;
}

export class Player {
  constructor(canvas, { onTick = () => {}, numbers = true } = {}) {
    this.canvas = canvas; this.onTick = onTick; this.numbers = numbers;
    this.events = []; this.includeErased = false;
    this.speed = 1; this.time = 0; this.playing = false;
    this.tl = { ops: [], total: 0 };
    new ResizeObserver(() => this.render()).observe(canvas);
  }
  load(events, { keepTime = false } = {}) {
    this.events = events;
    this.tl = buildTimeline(events, this.includeErased);
    if (!keepTime) this.time = this.tl.total;
    else this.time = Math.min(this.time, this.tl.total);
    this.render();
  }
  setErased(v) { this.includeErased = v; this.load(this.events); }
  render() {
    const strokes = stateAt(this.tl.ops, this.time);
    const drawing = this.playing || this.time < this.tl.total;
    drawAll(this.canvas, strokes, { numbers: this.numbers, highlightLast: drawing && strokes.length > 0 });
    this.onTick(this.tl.total ? this.time / this.tl.total : 1, this.playing);
  }
  play() {
    if (this.time >= this.tl.total) this.time = 0;
    this.playing = true;
    let last = performance.now();
    const step = now => {
      if (!this.playing) return;
      this.time = Math.min(this.time + (now - last) * this.speed, this.tl.total);
      last = now;
      if (this.time >= this.tl.total) this.playing = false;
      this.render();
      if (this.playing) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  pause() { this.playing = false; this.render(); }
  seek(frac) { this.pause(); this.time = frac * this.tl.total; this.render(); }
  stepStroke(dir) {
    this.pause();
    const ends = this.tl.ops.map(o => o.end);
    if (dir > 0) this.time = ends.find(e => e > this.time + 1) ?? this.tl.total;
    else this.time = [...ends].reverse().find(e => e < this.time - 1) ?? 0;
    this.render();
  }
}

export function drawStatic(canvas, strokes) {
  const redraw = () => drawAll(canvas, strokes);
  new ResizeObserver(redraw).observe(canvas);
  redraw();
}

export function replayInto(canvas, events) {
  const p = new Player(canvas, { numbers: false });
  p.load(events); p.play();
  return p;
}
