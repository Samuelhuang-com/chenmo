// 雙字問心：依序寫兩個字（第一字、第二字），每個字標明代表的選擇。
// 筆跡沿用問字的 WebSocket；第二字的訊息帶 pad: 1，筆序號加 10000 以免和第一字重複。
import { BrushPad } from "./brush-pad.js";
import { Socket } from "./ws-client.js";

const $ = id => document.getElementById(id);
const form = $("pair-form");
const q = $("question"), counter = $("counter"), err = $("error"), conn = $("conn");
const MAX = parseInt(q.dataset.max, 10) || 100;
const SEQ_B = 10000;

let sock = null, creating = null, token = null;
const STATE_TEXT = { connecting: "連線中…", open: "已與老師連線", closed: "連線中斷，重新連線中" };
function onState(s) { conn.dataset.state = s; conn.textContent = STATE_TEXT[s] || ""; }
function showErr(m) { err.textContent = m || ""; }

function ensureCase() {
  if (!creating) {
    creating = fetch("/api/pair/cases", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ redo_of: form.dataset.redo || "", follow_of: form.dataset.follow || "" }),
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (r.status === 401) { location.href = "/me/login?next=/pair"; throw new Error("請先登入"); }
      if (!r.ok) throw new Error(d.detail || "暫時無法建立問事，請稍後再試");
      token = d.token;
      sock = new Socket(`/ws/user/${token}`, msg => { if (msg.type === "error") showErr(msg.message); }, onState);
    }).catch(e => { creating = null; showErr(e.message); throw e; });
  }
  return creating;
}
function send(msg) { ensureCase().then(() => sock.send(msg)).catch(() => {}); }

// ---- 問題 ----
let qTimer = 0;
function onQuestion() {
  let chars = [...q.value];
  if (chars.length > MAX) { chars = chars.slice(0, MAX); q.value = chars.join(""); }
  counter.textContent = `${chars.length} / ${MAX}`;
  counter.classList.toggle("full", chars.length >= MAX);
}
q.addEventListener("input", () => {
  onQuestion();
  clearTimeout(qTimer);
  qTimer = setTimeout(() => send({ type: "question", text: q.value }), 500);
});
onQuestion();

// ---- 年次、性別、稱呼 ----
const byInput = $("birth_year"), nickInput = $("nickname");
const ROC_NOW = parseInt(byInput.max, 10);
const ZODIAC = "鼠牛虎兔龍蛇馬羊猴雞狗豬";
function birthYear() { const v = parseInt(byInput.value, 10); return Number.isInteger(v) && v >= 1 && v <= ROC_NOW ? v : null; }
function nickname() { return nickInput.value.replace(/\s+/g, " ").trim().slice(0, 30); }
function gender() { return document.querySelector("input[name=gender]:checked")?.value || ""; }
let pTimer = 0;
function onProfile(push = true) {
  const by = birthYear();
  $("by-detail").textContent = by ? `西元 ${by + 1911} 年，屬${ZODIAC[(by + 1911 - 4) % 12]}`
    : byInput.value ? `請填民國 1 到 ${ROC_NOW} 年` : "";
  if (!push) return;
  clearTimeout(pTimer);
  pTimer = setTimeout(() => {
    if (by || gender() || nickname()) send({ type: "profile", birth_year: by, gender: gender(), nickname: nickname() });
  }, 500);
}
byInput.addEventListener("input", () => onProfile());
nickInput.addEventListener("input", () => onProfile());
document.querySelectorAll("input[name=gender]").forEach(r => r.addEventListener("change", () => onProfile()));
onProfile(false);

// ---- 常見對字：只幫忙填入「這是哪個字」，字還是要自己寫 ----
let preset = "";
const charA = $("char-a"), charB = $("char-b");
document.querySelectorAll("[data-preset]").forEach(b => b.onclick = () => {
  const p = b.dataset.preset;
  const on = preset !== p;
  preset = on ? p : "";
  document.querySelectorAll("[data-preset]").forEach(x => x.setAttribute("aria-pressed", String(on && x === b)));
  if (on) { charA.value = [...p][0]; charB.value = [...p][1]; showErr(""); }
});
[charA, charB].forEach(inp => inp.addEventListener("input", () => {
  if (preset && charA.value.trim() + charB.value.trim() !== preset) {
    preset = "";
    document.querySelectorAll("[data-preset]").forEach(x => x.setAttribute("aria-pressed", "false"));
  }
}));

// ---- 兩個字格 ----
function typing() {
  const el = document.activeElement;
  return !!el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && ["text", "number", "tel", "search", ""].includes(el.type)));
}
const MSG = { lock: "請把字格完整滑進畫面再開始書寫", typing: "請先點一下字格收起鍵盤，再開始書寫", order: "先寫好第一字，再寫第二字" };
const pads = [0, 1].map(i => {
  const k = "ab"[i];
  const box = $(`pad-box-${k}`), canvas = $(`pad-${k}`);
  const extra = i ? { pad: 1 } : {};
  const seq = n => (i ? n + SEQ_B : n);
  const p = new BrushPad(canvas, {
    onFirstTouch: () => showErr(""),
    onBlocked: () => { if (typing()) document.activeElement.blur(); },
    onStrokeStart: (n, t0) => send({ type: "stroke_start", seq: seq(n), t0, ...extra }),
    onPoints: (n, points) => send({ type: "stroke_points", seq: seq(n), points, ...extra }),
    onStrokeEnd: n => { send({ type: "stroke_end", seq: seq(n), ...extra }); setTimeout(applyLocks, 0); },
    onUndo: () => { send({ type: "undo", ...extra }); applyLocks(); },
    onClear: () => { send({ type: "clear", ...extra }); applyLocks(); },
  });
  return { i, box, canvas, pad: p, visible: !("IntersectionObserver" in window), text: box.querySelector(".pad-lock span") };
});
function applyLocks() {
  const isTyping = typing();
  for (const s of pads) {
    const order = s.i === 1 && !pads[0].pad.count && !s.pad.count;   // 第二字要等第一字落筆
    const ok = (s.visible && !isTyping && !order) || !!s.pad.cur;     // 已經下筆的這一筆要寫完
    s.pad.enabled = ok;
    s.box.classList.toggle("locked", !ok);
    s.text.textContent = order ? MSG.order : isTyping ? MSG.typing : MSG.lock;
  }
}
if ("IntersectionObserver" in window) {
  const steps = Array.from({ length: 51 }, (_, i) => i / 50);
  for (const s of pads) {
    new IntersectionObserver(([en]) => {
      const need = Math.min(0.98, (innerHeight * 0.98) / Math.max(en.boundingClientRect.height, 1));
      s.visible = s.visible ? en.intersectionRatio >= Math.min(need, 0.6) : en.intersectionRatio >= need;
      applyLocks();
    }, { threshold: steps }).observe(s.box);
    ["pointerup", "pointercancel"].forEach(t => s.canvas.addEventListener(t, () => setTimeout(applyLocks, 0)));
  }
}
applyLocks();
document.addEventListener("focusin", applyLocks);
document.addEventListener("focusout", () => setTimeout(applyLocks, 150));
document.documentElement.style.overscrollBehaviorY = "none";
document.querySelectorAll("[data-undo]").forEach(b => b.onclick = () => pads[+b.dataset.undo].pad.undo());
document.querySelectorAll("[data-clear]").forEach(b => b.onclick = () => pads[+b.dataset.clear].pad.clear());

// ---- 呈送 ----
function oneChar(v) { return [...v.trim()].length === 1; }
$("submit").onclick = async () => {
  showErr("");
  const question = q.value.trim();
  const by = birthYear(), g = gender(), nn = nickname();
  const a = charA.value.trim(), b = charB.value.trim();
  const ca = $("choice-a").value.replace(/\s+/g, " ").trim(), cb = $("choice-b").value.replace(/\s+/g, " ").trim();
  if (!nn) { nickInput.focus(); return showErr("請填寫姓氏、暱稱或英文名，讓老師知道怎麼稱呼你。"); }
  if (!by) { byInput.focus(); return showErr(`請填寫年次（民國 1 到 ${ROC_NOW} 年）。`); }
  if (!g) return showErr("請選擇性別。");
  if (!question) { q.focus(); return showErr("請先說說你在猶豫什麼。"); }
  if (!pads[0].pad.count) return showErr("請在第一個字格寫下第一個字。");
  if (!pads[1].pad.count) return showErr("請在第二個字格寫下第二個字。");
  if (!oneChar(a)) { charA.focus(); return showErr("請填入第一字是哪個字（一個字）。"); }
  if (!oneChar(b)) { charB.focus(); return showErr("請填入第二字是哪個字（一個字）。"); }
  if (a === b) { charB.focus(); return showErr("兩個字請寫不同的字。"); }
  if (!ca) { $("choice-a").focus(); return showErr(`請寫下「${a}」代表的選擇。`); }
  if (!cb) { $("choice-b").focus(); return showErr(`請寫下「${b}」代表的選擇。`); }
  const btn = $("submit");
  btn.disabled = true; btn.textContent = "呈送中";
  try {
    await ensureCase();
    sock.send({ type: "question", text: question });
    await sock.sync(8000);
    const r = await fetch(`/api/pair/cases/${token}/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, char_a: a, char_b: b, choice_a: ca, choice_b: cb,
                             birth_year: by, gender: g, nickname: nn, preset }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = Array.isArray(d.detail) ? d.detail.map(x => x.msg.replace(/^Value error, /, "")).join("；") : d.detail;
      throw new Error(detail || "呈送失敗，請再試一次");
    }
    sock.close();
    location.href = d.url;
  } catch (e) {
    showErr(e.message === "timeout" ? "連線不穩，筆跡尚未全部傳到，請稍候再按一次呈送。" : e.message);
    btn.disabled = false; btn.textContent = "呈送";
  }
};
