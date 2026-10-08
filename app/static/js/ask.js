import { BrushPad } from "./brush-pad.js";
import { Socket } from "./ws-client.js";

const $ = id => document.getElementById(id);
const q = $("question"), counter = $("counter"), err = $("error"), conn = $("conn");
const MAX = parseInt(q.dataset.max, 10) || 100;

let sock = null, creating = null, token = null;

const STATE_TEXT = { connecting: "連線中…", open: "已與老師連線", closed: "連線中斷，重新連線中" };
function onState(s) { conn.dataset.state = s; conn.textContent = STATE_TEXT[s] || ""; }
function onMsg(msg) { if (msg.type === "error") showErr(msg.message); }
function showErr(m) { err.textContent = m || ""; }

function ensureCase() {
  if (!creating) {
    creating = fetch("/api/cases", { method: "POST" }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (r.status === 401) { location.href = "/me/login?next=/ask"; throw new Error("請先登入"); }
      if (!r.ok) throw new Error(d.detail || "暫時無法建立問事，請稍後再試");
      token = d.token;
      sock = new Socket(`/ws/user/${token}`, onMsg, onState);
    }).catch(e => { creating = null; showErr(e.message); throw e; });
  }
  return creating;
}
function send(msg) { ensureCase().then(() => sock.send(msg)).catch(() => {}); }

// ---- 問題描述：以 code point 計數，超過 100 字截斷 ----
let qTimer = 0;
q.addEventListener("input", () => {
  let chars = [...q.value];
  if (chars.length > MAX) { chars = chars.slice(0, MAX); q.value = chars.join(""); }
  counter.textContent = `${chars.length} / ${MAX}`;
  counter.classList.toggle("full", chars.length >= MAX);
  clearTimeout(qTimer);
  qTimer = setTimeout(() => send({ type: "question", text: q.value }), 500);
});

// ---- 年次（民國）與性別 ----
const byInput = $("birth_year");
const ROC_NOW = parseInt(byInput.max, 10);
const ZODIAC = "鼠牛虎兔龍蛇馬羊猴雞狗豬";
function birthYear() {
  const v = parseInt(byInput.value, 10);
  return Number.isInteger(v) && v >= 1 && v <= ROC_NOW ? v : null;
}
function gender() { return document.querySelector("input[name=gender]:checked")?.value || ""; }
let pTimer = 0;
function onProfile() {
  const by = birthYear();
  $("by-detail").textContent = by ? `西元 ${by + 1911} 年，屬${ZODIAC[(by + 1911 - 4) % 12]}`
    : byInput.value ? `請填民國 1 到 ${ROC_NOW} 年` : "";
  clearTimeout(pTimer);
  pTimer = setTimeout(() => {
    if (by || gender()) send({ type: "profile", birth_year: by, gender: gender() });
  }, 500);
}
byInput.addEventListener("input", onProfile);
document.querySelectorAll("input[name=gender]").forEach(r => r.addEventListener("change", onProfile));

// ---- 手寫板 ----
const pad = new BrushPad($("pad"), {
  onFirstTouch: () => { q.blur(); showErr(""); },
  onStrokeStart: (seq, t0) => send({ type: "stroke_start", seq, t0 }),
  onPoints: (seq, points) => send({ type: "stroke_points", seq, points }),
  onStrokeEnd: seq => send({ type: "stroke_end", seq }),
  onUndo: () => send({ type: "undo" }),
  onClear: () => send({ type: "clear" }),
});
// ---- 自選字 ----
let pick = null;            // { char, offered, rounds }
let offered = [], rounds = 0;
const panel = $("pick-panel"), grid = $("pick-grid"), charInput = $("char");
const PAD_HINT = $("pad-hint").textContent;

async function loadSet() {
  $("pick-shuffle").disabled = true;
  try {
    const r = await fetch("/api/pick");
    offered = (await r.json()).chars;
    rounds += 1;
    grid.innerHTML = "";
    offered.forEach(ch => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = ch; b.setAttribute("aria-pressed", "false");
      b.onclick = () => choose(ch, b);
      grid.appendChild(b);
    });
  } catch { showErr("暫時無法取得候選字，請稍後再試。"); }
  finally { $("pick-shuffle").disabled = false; }
}
function choose(ch, btn) {
  grid.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
  pick = { char: ch, offered: [...offered], rounds };
  $("pad-guide").textContent = ch;
  charInput.value = ch; charInput.readOnly = true;
  $("pad-hint").innerHTML = `已選「<b>${ch}</b>」。可以照著淡字描寫一次（選填），也可以直接呈送。`;
  $("pad-hint").classList.add("picked-note");
  $("pick-open").textContent = "改選其他字";
  showErr("");
  send({ type: "pick", char: ch, offered: pick.offered, rounds });
}
function unpick() {
  if (pick) send({ type: "unpick" });
  pick = null;
  $("pad-guide").textContent = "";
  charInput.value = ""; charInput.readOnly = false;
  $("pad-hint").textContent = PAD_HINT; $("pad-hint").classList.remove("picked-note");
  $("pick-open").textContent = "自選字";
  grid.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", "false"));
}
$("pick-open").onclick = () => {
  panel.hidden = false;
  $("pick-open").setAttribute("aria-expanded", "true");
  if (!offered.length) loadSet();
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
};
$("pick-shuffle").onclick = loadSet;
$("pick-close").onclick = () => {
  unpick();
  panel.hidden = true;
  $("pick-open").setAttribute("aria-expanded", "false");
};

$("undo").onclick = () => pad.undo();
$("clear").onclick = () => pad.clear();

// ---- 呈送 ----
$("submit").onclick = async () => {
  showErr("");
  const question = q.value.trim();
  const ch = $("char").value.trim();
  const by = birthYear(), g = gender();
  if (!by) { byInput.focus(); return showErr(`請填寫年次（民國 1 到 ${ROC_NOW} 年）。`); }
  if (!g) return showErr("請選擇性別。");
  if (!question) return showErr("請先簡述您想問的事。");
  if (!pad.count && !pick) return showErr("請先在字格中寫下一個字，或按「自選字」選一個字。");
  if ([...ch].length > 1) return showErr("「寫的是哪個字」請只填一個字。");
  const btn = $("submit");
  btn.disabled = true; btn.textContent = "呈送中";
  try {
    await ensureCase();
    sock.send({ type: "question", text: question });
    await sock.sync(8000);
    const r = await fetch(`/api/cases/${token}/submit`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pick
        ? { question, char: pick.char, birth_year: by, gender: g, picked: true, offered: pick.offered, rounds: pick.rounds }
        : { question, char: ch, birth_year: by, gender: g }),
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
