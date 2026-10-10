import { BrushPad } from "./brush-pad.js";
import { Socket } from "./ws-client.js";

const $ = id => document.getElementById(id);
const q = $("question"), counter = $("counter"), err = $("error"), conn = $("conn");
const MAX = parseInt(q.dataset.max, 10) || 100;

let sock = null, creating = null, token = null;
const redoNote = document.getElementById("redo-note");

const STATE_TEXT = { connecting: "連線中…", open: "已與老師連線", closed: "連線中斷，重新連線中" };
function onState(s) { conn.dataset.state = s; conn.textContent = STATE_TEXT[s] || ""; }
function onMsg(msg) { if (msg.type === "error") showErr(msg.message); }
function showErr(m) { err.textContent = m || ""; }

function ensureCase() {
  if (!creating) {
    creating = fetch("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ redo_of: redoNote?.dataset.token || "", follow_of: document.getElementById("follow-note")?.dataset.token || "" }) }).then(async r => {
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
const nickInput = $("nickname");
function nickname() { return nickInput.value.replace(/\s+/g, " ").trim().slice(0, 30); }
function gender() { return document.querySelector("input[name=gender]:checked")?.value || ""; }
let pTimer = 0;
function onProfile() {
  const by = birthYear();
  $("by-detail").textContent = by ? `西元 ${by + 1911} 年，屬${ZODIAC[(by + 1911 - 4) % 12]}`
    : byInput.value ? `請填民國 1 到 ${ROC_NOW} 年` : "";
  clearTimeout(pTimer);
  pTimer = setTimeout(() => {
    if (by || gender() || nickname()) send({ type: "profile", birth_year: by, gender: gender(), nickname: nickname() });
  }, 500);
}
byInput.addEventListener("input", onProfile);
nickInput.addEventListener("input", onProfile);
document.querySelectorAll("input[name=gender]").forEach(r => r.addEventListener("change", onProfile));

// ---- 手寫板 ----
const pad = new BrushPad($("pad"), {
  onFirstTouch: () => showErr(""),
  onBlocked: () => { if (typing()) document.activeElement.blur(); },
  onStrokeStart: (seq, t0) => send({ type: "stroke_start", seq, t0 }),
  onPoints: (seq, points) => send({ type: "stroke_points", seq, points }),
  onStrokeEnd: seq => send({ type: "stroke_end", seq }),
  onUndo: () => send({ type: "undo" }),
  onClear: () => send({ type: "clear" }),
});
// ---- 自選字 ----
let pick = null;            // { char, offered, rounds, theme, group }
let offered = [], rounds = 0;
let themeId = "", groupId = "";   // themeId 空＝隨機字（原本的做法）；選了方向才有主題字庫
const panel = $("pick-panel"), grid = $("pick-grid"), charInput = $("char");
const PAD_HINT = $("pad-hint").textContent;
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// 換一組（again）：同一方向、同一子題，並避開目前這組字；換方向或第一次載入則重新抽
async function loadSet(again = false) {
  $("pick-shuffle").disabled = true;
  try {
    const qs = new URLSearchParams();
    if (themeId) {
      qs.set("theme", themeId);
      if (again && groupId) qs.set("group", groupId);
      if (again) qs.set("exclude", offered.join(""));
    }
    const r = await fetch("/api/pick" + (qs.toString() ? `?${qs}` : ""));
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    offered = d.chars;
    groupId = d.group_id || "";
    rounds += 1;
    renderCaption(d);
    grid.classList.toggle("by-stage", d.source === "group");   // 子題：每列一個階段，由上而下是思考路徑
    grid.innerHTML = "";
    offered.forEach(ch => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = ch; b.setAttribute("aria-pressed", "false");
      b.onclick = () => choose(ch, b);
      grid.appendChild(b);
    });
    $("pick-shuffle").hidden = !!themeId && d.can_redraw === false;   // 沒有不同組合就不假裝能換
  } catch { showErr("暫時無法取得候選字，請稍後再試。"); }
  finally { $("pick-shuffle").disabled = false; }
}
function renderCaption(d) {
  const cap = $("pick-caption");
  if (!themeId || !d.group_name) { cap.hidden = true; cap.textContent = ""; return; }
  const path = d.source === "group" ? `　由上而下：${d.stages.map(s => s.name).join(" → ")}` : "";
  cap.innerHTML = `<b>${esc(d.group_name)}</b>　${esc(d.tagline || "")}${path ? `<span class="pick-path">${esc(path.trim())}</span>` : ""}`;
  cap.hidden = false;
}
// 挑字方向：選填。預設「隨機」，和原本一樣；第一次打開面板才載入清單，載入失敗就只剩隨機
let themesLoaded = false;
async function loadThemes() {
  if (themesLoaded) return;
  themesLoaded = true;
  try {
    const r = await fetch("/api/pick/themes");
    const list = r.ok ? (await r.json()).themes : [];
    if (!list.length) return;
    const row = $("pick-themes");
    [{ id: "", short: "隨機" }, ...list].forEach(t => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = t.short; b.dataset.id = t.id;
      b.setAttribute("aria-pressed", String(t.id === themeId));
      b.onclick = () => {
        if (t.id === themeId) return;
        themeId = t.id; groupId = "";
        row.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
        loadSet(false);
      };
      row.appendChild(b);
    });
    row.hidden = false;
  } catch { /* 沒有方向清單就維持隨機，不影響問字 */ }
}
function choose(ch, btn) {
  grid.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b === btn)));
  pick = { char: ch, offered: [...offered], rounds, theme: themeId, group: groupId };
  $("pad-guide").textContent = ch;
  charInput.value = ch; charInput.readOnly = true;
  $("pad-hint").innerHTML = `已選「<b>${esc(ch)}</b>」。可以照著淡字描寫一次（選填），也可以直接呈送。`;
  $("pad-hint").classList.add("picked-note");
  $("pick-open").textContent = "改選其他字";
  showErr("");
  send({ type: "pick", char: ch, offered: pick.offered, rounds, theme: themeId, group: groupId });
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
  loadThemes();
  if (!offered.length) loadSet();
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
};
$("pick-shuffle").onclick = () => loadSet(true);
$("pick-close").onclick = () => {
  unpick();
  panel.hidden = true;
  $("pick-open").setAttribute("aria-expanded", "false");
};

// ---- 字格完整出現在畫面內，才開始接受書寫（避免捲動時誤觸畫到邊框） ----
const padBox = $("pad-box");
const lockText = padBox.querySelector(".pad-lock span");
const LOCK_MSG = "請把字格完整滑進畫面再開始書寫";
const TYPING_MSG = "請先點一下字格收起鍵盤，再開始書寫";
let fullyVisible = true;
function typing() {
  const el = document.activeElement;
  return !!el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && ["text", "number", "tel", "search", ""].includes(el.type)));
}
function applyPadLock() {
  const isTyping = typing();
  pad.enabled = (fullyVisible && !isTyping) || !!pad.cur;     // 已經下筆的這一筆要寫完
  padBox.classList.toggle("locked", !pad.enabled);
  lockText.textContent = isTyping ? TYPING_MSG : LOCK_MSG;
}
if ("IntersectionObserver" in window) {
  fullyVisible = false;
  applyPadLock();
  const steps = Array.from({ length: 51 }, (_, i) => i / 50);
  new IntersectionObserver(([en]) => {
    // 字格比螢幕還高時，放寬為「螢幕能容納的部分都在畫面內」
    const need = Math.min(0.98, (innerHeight * 0.98) / Math.max(en.boundingClientRect.height, 1));
    // 解鎖後只要大部分還在畫面內就維持可寫，避免畫面微幅晃動時一直鎖／解鎖
    fullyVisible = fullyVisible ? en.intersectionRatio >= Math.min(need, 0.6) : en.intersectionRatio >= need;
    applyPadLock();
  }, { threshold: steps }).observe(padBox);
  ["pointerup", "pointercancel"].forEach(t => $("pad").addEventListener(t, () => setTimeout(applyPadLock, 0)));
}
// 輸入問題、年次時鍵盤會改變畫面大小，期間先不接受書寫
document.addEventListener("focusin", applyPadLock);
document.addEventListener("focusout", () => setTimeout(applyPadLock, 150));
// 手機不要因為手指下拉而重新整理或整頁彈跳
document.documentElement.style.overscrollBehaviorY = "none";

$("undo").onclick = () => pad.undo();
$("clear").onclick = () => pad.clear();

// ---- 呈送 ----
$("submit").onclick = async () => {
  showErr("");
  const question = q.value.trim();
  const ch = $("char").value.trim();
  const by = birthYear(), g = gender(), nn = nickname();
  if (!nn) { nickInput.focus(); return showErr("請填寫姓氏、暱稱或英文名，讓老師知道怎麼稱呼你。"); }
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
        ? { question, char: pick.char, birth_year: by, gender: g, nickname: nn, picked: true, offered: pick.offered, rounds: pick.rounds, theme: pick.theme, group: pick.group }
        : { question, char: ch, birth_year: by, gender: g, nickname: nn }),
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

// ---- 老師請重寫：帶入原本的問題、年次、性別 ----
const followNote = document.getElementById("follow-note");
const prefillNote = redoNote || followNote;
if (prefillNote) {
  const d = prefillNote.dataset;
  q.value = d.question || "";
  q.dispatchEvent(new Event("input"));
  if (d.nickname) { nickInput.value = d.nickname; }
  if (d.birth) { byInput.value = d.birth; byInput.dispatchEvent(new Event("input")); }
  if (d.gender) {
    const r = document.querySelector(`input[name=gender][value="${d.gender}"]`);
    if (r) { r.checked = true; r.dispatchEvent(new Event("change")); }
  }
}
