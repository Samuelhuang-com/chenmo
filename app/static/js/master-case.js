import { Player, strokeDuration } from "./replay.js";
import { visibleStrokes } from "./ink.js";
import { Socket } from "./ws-client.js";

const $ = id => document.getElementById(id);
let nickNow = "";
function profileLine(c) {
  nickNow = c.nickname || "";
  const p = c.profile_text || "（尚未填寫年次與性別）";
  return nickNow ? `${nickNow}　${p}` : p;
}
const caseId = $("bench").dataset.caseId;
const STATUS = { drafting: "書寫中", submitted: "待解", answered: "已解" };
let events = [];
let lastLive = 0;

const player = new Player($("pad"), {
  onTick: (frac, playing) => {
    $("progress").value = Math.round(frac * 1000);
    $("play").textContent = playing ? "暫停" : "播放";
  },
});

function sec(ms) { return (ms / 1000).toFixed(1) + " 秒"; }

function renderFacts() {
  const strokes = visibleStrokes(events);
  const erased = events.filter(e => e.type === "undo" || e.type === "clear").length;
  const rows = [];
  let total = 0, longest = 0;
  strokes.forEach((s, i) => {
    const dur = strokeDuration(s);
    const gap = i ? s.t0 - (strokes[i - 1].t0 + strokeDuration(strokes[i - 1])) : null;
    if (gap !== null) longest = Math.max(longest, gap);
    rows.push(`<tr><td>${i + 1}</td><td>${sec(dur)}</td><td class="${gap > 2000 ? "long" : ""}">${gap === null ? "—" : sec(Math.max(gap, 0))}</td></tr>`);
  });
  if (strokes.length) {
    const last = strokes[strokes.length - 1];
    total = last.t0 + strokeDuration(last) - strokes[0].t0;
  }
  $("facts").innerHTML = `
    <dt>筆數</dt><dd>${strokes.length} 筆</dd>
    <dt>書寫歷時</dt><dd>${strokes.length ? sec(total) : "—"}</dd>
    <dt>最長停頓</dt><dd>${strokes.length > 1 ? sec(longest) : "—"}</dd>
    <dt>擦除</dt><dd>${erased ? `復原或清除 ${erased} 次` : "無"}</dd>`;
  $("stroke-rows").innerHTML = rows.join("");
}

function refresh() {
  const following = player.time >= player.tl.total - 1 && !player.playing;
  player.load(events, { keepTime: !following });
  renderFacts();
}

let caseStatus = "";
let revision = 0;
function setStatus(s, c = null) {
  const was = caseStatus;
  caseStatus = s;
  if (c) revision = c.revision || 0;
  $("status").textContent = STATUS[s] || s;
  $("send").disabled = s !== "submitted";
  $("send").hidden = s === "answered";
  $("send").textContent = revision ? "重送解讀" : "送出解讀";
  $("retract").hidden = s !== "answered";
  $("update-reading").hidden = s !== "answered";
  $("jiezi-run").disabled = s === "answered";
  if (s === "answered") {
    $("save-state").textContent = "";
    if (c && c.answered_at) $("sent-info").textContent =
      `第 ${c.revision} 次送出，${new Date(c.answered_at).toLocaleString("zh-TW", { hour12: false })}`;
    dirtySent = false; $("update-reading").disabled = true;
  } else if (was === "answered") {
    dirtySent = false;
    $("save-state").textContent = "已收回，問事者頁面回到等待狀態。修改後可重送。";
    $("sent-info").textContent = "";
  }
  // 問事者剛送出、而且有自填的字：自動帶出解字資料
  if (was === "drafting" && s === "submitted") maybeAutoJiezi();
}

// ---- 帶出字資料 ----
let beforeJiezi = null;
async function runJiezi(refresh = false) {
  if ($("jiezi-run").disabled) return;
  const ch = $("jiezi-char").value.trim();
  if ([...ch].length !== 1) { $("jiezi-state").textContent = "請先在「此字」欄填入一個字。"; $("jiezi-char").focus(); return; }
  const btn = $("jiezi-run");
  btn.disabled = true;
  $("jiezi-state").textContent = "正在查字庫並產生草稿，約需十餘秒…";
  try {
    const r = await fetch(`/api/master/cases/${caseId}/jiezi`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ char: ch, refresh }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(Array.isArray(d.detail) ? d.detail.map(x => x.msg.replace(/^Value error, /, "")).join("；") : (d.detail || "帶出失敗"));
    beforeJiezi = { data: $("answer").value, html: $("reading").innerHTML };
    setFromCombined(d.text, true);
    $("answer").dataset.auto = "";
    onAnswerChanged();
    $("jiezi-undo").hidden = false;
    btn.textContent = "重新產生";
    $("jiezi-state").textContent = d.cached ? "已帶出先前產生的內容。要重新產生請再按一次「重新產生」。"
      : d.ai_used ? "已帶出。標示「AI 草稿」的段落請審閱修改後再送出。"
      : d.ai_error ? `字庫資料已帶出，但 AI 草稿失敗（${d.ai_error}）。【解讀】沒有內容，請再按一次「重新產生」，或自己填寫。`
      : "已帶出字庫資料。尚未設定 AI，字義與解讀請老師補充。";
    if (!d.cached && !d.ai_used) $("jiezi-state").classList.add("warn"); else $("jiezi-state").classList.remove("warn");
    btn.dataset.refresh = "1";
  } catch (e) {
    $("jiezi-state").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}
function maybeAutoJiezi() {
  if ($("answer").dataset.auto === "1" && $("jiezi-char").value.trim() && caseStatus !== "drafting") runJiezi();
}
$("jiezi-run").onclick = () => runJiezi($("jiezi-run").dataset.refresh === "1");
$("jiezi-undo").onclick = () => {
  if (beforeJiezi === null) return;
  $("answer").value = beforeJiezi.data; $("reading").innerHTML = beforeJiezi.html;
  beforeJiezi = null; $("jiezi-undo").hidden = true;
  onAnswerChanged();
};

async function load() {
  const r = await fetch(`/api/master/cases/${caseId}`);
  if (r.status === 401) { location.href = "/master/login"; return; }
  const d = await r.json();
  events = d.events;
  $("question").textContent = d.case.question || "（尚未填寫）";
  $("profile").textContent = profileLine(d.case);
  showPick(d.case);
  setStatus(d.case.status, d.case);
  player.load(events);
  renderFacts();
  if (!$("jiezi-char").value && d.case.char) $("jiezi-char").value = d.case.char;
  maybeAutoJiezi();
}

// ---- 自選字資訊 ----
function showPick(c) {
  const picked = c && c.char_source === "picked";
  $("pad-guide").textContent = picked ? c.char : "";
  $("pick-info").hidden = !picked;
  if (picked) {
    const r = (c.pick_rounds || c.rounds) > 1 ? `，換到第 ${c.pick_rounds || c.rounds} 組才選定` : "";
    $("pick-info").textContent = `自選字「${c.char}」${r}。候選：${(c.offered || []).join("、")}`;
    if (!$("jiezi-char").value || $("jiezi-char").dataset.fromPick) {
      $("jiezi-char").value = c.char; $("jiezi-char").dataset.fromPick = "1";
    }
  }
}

// ---- 即時觀看 ----
const liveStrokes = new Map();
new Socket("/ws/master", msg => {
  if (msg.type === "case_update" && msg.case.id === caseId) {
    if (msg.case.rewrite_requested_at) $("rewrite-state").textContent = "已請問事者重寫，等待新的字。";
    if (!$("jiezi-char").value && msg.case.char) $("jiezi-char").value = msg.case.char;
    if (msg.case.profile_text) $("profile").textContent = profileLine(msg.case);
    showPick(msg.case);
    return setStatus(msg.case.status, msg.case);
  }
  if (msg.type === "case_deleted" && msg.case_id === caseId) { location.href = "/master"; return; }
  if (msg.case_id !== caseId) return;
  lastLive = Date.now();
  $("live-tag").textContent = "問事者正在書寫";
  switch (msg.type) {
    case "stroke_start": {
      const ev = { type: "stroke", seq: msg.seq, t0: msg.t0, points: [] };
      liveStrokes.set(msg.seq, ev); events.push(ev); break;
    }
    case "stroke_points": liveStrokes.get(msg.seq)?.points.push(...msg.points); break;
    case "stroke_end": liveStrokes.delete(msg.seq); break;
    case "undo": case "clear": events.push({ type: msg.type }); break;
    case "question": $("question").textContent = msg.text || "（尚未填寫）"; return;
    case "profile": $("profile").textContent = profileLine({ nickname: msg.nickname ?? nickNow, profile_text: msg.text }); return;
    case "pick": showPick({ char_source: "picked", char: msg.char, offered: msg.offered, pick_rounds: msg.rounds }); return;
    case "unpick": showPick(null); return;
  }
  refresh();
}, s => { if (s === "open") load(); });

setInterval(() => { if (Date.now() - lastLive > 4000) $("live-tag").textContent = ""; }, 1000);

// ---- 重播控制 ----
$("play").onclick = () => (player.playing ? player.pause() : player.play());
$("prev").onclick = () => player.stepStroke(-1);
$("next").onclick = () => player.stepStroke(1);
$("progress").oninput = e => player.seek(e.target.value / 1000);
document.querySelectorAll("[data-speed]").forEach(b => b.onclick = () => {
  player.speed = parseFloat(b.dataset.speed);
  document.querySelectorAll("[data-speed]").forEach(x => x.setAttribute("aria-pressed", x === b));
});
$("opt-numbers").onchange = e => { player.numbers = e.target.checked; player.render(); };
$("opt-erased").onchange = e => player.setErased(e.target.checked);

// ---- 解字資料（老師用）與【解讀】（問事者看到）分開編輯，存檔時合成同一份解字稿 ----
const AI_MARK = "（AI 草稿，請審閱）";
let dirtySent = false;
function splitCombined(text) {
  const heads = [...text.matchAll(/^【([^】\n]+)】[ \t]*$/gm)];
  let reading = "", data = text;
  for (let i = 0; i < heads.length; i++) {
    if (heads[i][1].trim() !== "解讀") continue;
    const start = heads[i].index + heads[i][0].length;
    const end = i + 1 < heads.length ? heads[i + 1].index : text.length;
    reading = text.slice(start, end).trim();
    data = (text.slice(0, heads[i].index) + text.slice(end)).trim();
    break;
  }
  return { data, reading };
}
const esc = t => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function textToHtml(text) {
  return text.trim().split(/\n\s*\n/).filter(x => x.trim())
    .map(x => `<p>${esc(x.trim()).replace(/\n/g, "<br>")}</p>`).join("");
}
const readingEl = $("reading");
function readingPlain() { return readingEl.innerText.replace(/\u00a0/g, " ").trim(); }
function combined() { return `${$("answer").value.trim()}\n\n【解讀】\n${publicReading()}`; }
// force=true：一律用文字覆蓋編輯器（AI 帶出時）；否則編輯器已有內容就保留
function setFromCombined(text, force = false) {
  const { data, reading } = splitCombined(text);
  $("answer").value = data;
  if (force || !readingPlain()) readingEl.innerHTML = textToHtml(reading.replaceAll("（尚未設定 AI，請老師補充）", ""));
}
function stripMarks(t) { return t.replaceAll(AI_MARK, "").replaceAll("（尚未設定 AI，請老師補充）", ""); }
function publicReading() { return stripMarks(readingPlain()).trim(); }
function readingHtml() { return stripMarks(readingEl.innerHTML); }

// 預覽用的前端清理（伺服器端另有一次白名單清理，這裡只是讓預覽不會跑版）
const OK_TAGS = new Set(["P", "DIV", "BR", "B", "STRONG", "I", "EM", "U", "S", "STRIKE", "DEL", "UL", "OL", "LI", "SPAN", "FONT", "H3", "H4"]);
function cleanNode(src, dst) {
  src.childNodes.forEach(n => {
    if (n.nodeType === 3) dst.appendChild(document.createTextNode(n.textContent));
    else if (n.nodeType === 1 && OK_TAGS.has(n.tagName)) {
      const c = document.createElement(n.tagName.toLowerCase());
      if (n.getAttribute("style")) {
        const ok = n.getAttribute("style").split(";").filter(d => /^\s*(color|background-color|text-align|font-weight|font-style|text-decoration|font-size)\s*:\s*[^;]*$/i.test(d) && !/url|expression/i.test(d));
        if (ok.length) c.setAttribute("style", ok.join(";"));
      }
      if (n.tagName === "FONT" && /^[1-7]$/.test(n.getAttribute("size") || "")) c.setAttribute("size", n.getAttribute("size"));
      cleanNode(n, c); dst.appendChild(c);
    } else if (n.nodeType === 1 && !["SCRIPT", "STYLE", "IFRAME", "OBJECT"].includes(n.tagName)) cleanNode(n, dst);
  });
}
function renderReading() {
  readingEl.dataset.empty = readingPlain() ? "" : "1";
  const box = document.createElement("div");
  cleanNode(new DOMParser().parseFromString(readingHtml(), "text/html").body, box);
  $("preview").className = "answer rich";
  $("preview").innerHTML = box.innerHTML;
  const n = [...publicReading().replace(/\s/g, "")].length;
  $("reading-count").textContent = n ? `${n} 字` : "";
  $("reading-clear-mark").hidden = !readingEl.innerHTML.includes(AI_MARK);
}

let saveTimer = 0;
function onAnswerChanged() {
  renderReading();
  if (caseStatus === "answered") {
    dirtySent = true; $("update-reading").disabled = false;
    $("save-state").textContent = "已修改，按「更新解讀」後問事者才會看到新內容。";
    return;
  }
  clearTimeout(saveTimer);
  $("save-state").textContent = "編輯中…";
  saveTimer = setTimeout(async () => {
    const r = await fetch(`/api/master/cases/${caseId}/notes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: combined(), reading_html: readingHtml() }),
    }).catch(() => null);
    $("save-state").textContent = r && r.ok ? "已自動暫存" : "暫存失敗，請檢查連線";
  }, 1200);
}
$("answer").addEventListener("input", onAnswerChanged);
readingEl.addEventListener("input", onAnswerChanged);
$("reading-clear-mark").onclick = () => {
  readingEl.innerHTML = readingEl.innerHTML.replaceAll(AI_MARK, ""); onAnswerChanged();
};
// 初始：把伺服器帶來的完整解字稿拆成兩個編輯區
setFromCombined($("answer").value);
renderReading();
window.addEventListener("beforeunload", e => { if (dirtySent) { e.preventDefault(); e.returnValue = ""; } });

function errText(d, fallback) {
  return Array.isArray(d.detail) ? d.detail.map(x => x.msg).join("；") : (d.detail || fallback);
}

// ---- 送出／重送 ----
$("send").onclick = async () => {
  $("error").textContent = "";
  if (!publicReading()) {
    $("error").textContent = "【解讀】是空的。問事者只會收到【解讀】，請先寫好這一段。";
    return;
  }
  const body = combined();
  $("send").disabled = true;
  clearTimeout(saveTimer);
  try {
    const r = await fetch(`/api/master/cases/${caseId}/answer`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body, reading_html: readingHtml(), email_student: !!$("email-student")?.checked }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "送出失敗"));
    revision = d.revision;
    setStatus("answered", { revision: d.revision, answered_at: Date.now() });
    let note = "已送出，問事者頁面已更新。之後還可以直接修改並按「更新解讀」。";
    if (d.emailed === true) note += ` 已寄信給 ${d.email_to}。`;
    else if (d.emailed === false) note += ` 但信沒有寄出：${d.email_note}。可以用上方的連結自己傳給他。`;
    $("save-state").textContent = note;
  } catch (e) {
    $("error").textContent = e.message;
    $("send").disabled = caseStatus !== "submitted";
  }
};

// ---- 送出後直接修改：更新解讀 ----
$("update-reading").onclick = async () => {
  $("error").textContent = "";
  if (!publicReading()) { $("error").textContent = "【解讀】是空的，無法更新。"; return; }
  $("update-reading").disabled = true;
  try {
    const r = await fetch(`/api/master/cases/${caseId}/reading`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: combined(), reading_html: readingHtml() }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "更新失敗"));
    dirtySent = false;
    $("save-state").textContent = "已更新，問事者頁面已同步。";
  } catch (e) {
    $("error").textContent = e.message;
    $("update-reading").disabled = false;
  }
};

// ---- 收回 ----
$("retract").onclick = async () => {
  $("error").textContent = "";
  $("retract").disabled = true;
  try {
    const r = await fetch(`/api/master/cases/${caseId}/retract`, { method: "POST" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "收回失敗"));
    setStatus("submitted");
  } catch (e) {
    $("error").textContent = e.message;
  } finally {
    $("retract").disabled = false;
  }
};

// ---- 請問事者重寫／刪除 ----
$("rewrite").onclick = async () => {
  $("error2").textContent = "";
  $("rewrite").disabled = true;
  try {
    const r = await fetch(`/api/master/cases/${caseId}/request_rewrite`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: $("rewrite-reason").value }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "送出失敗"));
    $("rewrite-state").textContent = "已請問事者重寫，等待新的字。新字送出後，這一筆會自動被取代。";
  } catch (e) {
    $("error2").textContent = e.message;
  } finally {
    $("rewrite").disabled = false;
  }
};

$("delete-case").onclick = async () => {
  if (!confirm("確定要刪除這一筆嗎？筆跡與解讀都會一併刪除，無法復原。")) return;
  $("error2").textContent = "";
  try {
    const r = await fetch(`/api/master/cases/${caseId}`, { method: "DELETE" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "刪除失敗"));
    location.href = "/master";
  } catch (e) {
    $("error2").textContent = e.message;
  }
};

// ---- 解讀編輯器工具列 ----
document.execCommand("styleWithCSS", false, true);
let savedRange = null;
document.addEventListener("selectionchange", () => {
  const sel = getSelection();
  if (sel.rangeCount && readingEl.contains(sel.anchorNode)) savedRange = sel.getRangeAt(0).cloneRange();
});
function restoreSel() {
  readingEl.focus();
  if (savedRange) { const sel = getSelection(); sel.removeAllRanges(); sel.addRange(savedRange); }
}
function exec(cmd, val = null) { restoreSel(); document.execCommand(cmd, false, val); onAnswerChanged(); }
$("rte-bar").addEventListener("mousedown", e => { if (!e.target.closest("select, input")) e.preventDefault(); });
$("rte-bar").addEventListener("click", e => {
  const b = e.target.closest("button[data-cmd]");
  if (b) exec(b.dataset.cmd);
});
$("rte-color").addEventListener("input", e => exec("foreColor", e.target.value));
$("rte-hilite").addEventListener("input", e => exec("hiliteColor", e.target.value));
$("rte-size").addEventListener("change", e => {
  const px = e.target.value; e.target.value = "";
  if (!px) return;
  restoreSel();
  document.execCommand("fontSize", false, "7");
  // 瀏覽器會產生 <font size=7> 或 font-size: xxx-large 的暫時標記，換成指定的像素大小
  readingEl.querySelectorAll('font[size="7"]').forEach(f => {
    const sp = document.createElement("span"); sp.style.fontSize = px + "px";
    sp.innerHTML = f.innerHTML; f.replaceWith(sp);
  });
  readingEl.querySelectorAll("[style*='xxx-large']").forEach(el => { el.style.fontSize = px + "px"; });
  onAnswerChanged();
});
// 貼上一律當純文字，避免帶進網頁的雜亂格式
readingEl.addEventListener("paste", e => {
  e.preventDefault();
  document.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text/plain"));
});

// ---- 給問事者的連結 ----
const shareBox = $("share-box");
const shareUrl = (shareBox.dataset.site || location.origin) + "/c/" + shareBox.dataset.token;
$("share-url").value = shareUrl;
async function copyText(text, okMsg) {
  try { await navigator.clipboard.writeText(text); $("share-state").textContent = okMsg; }
  catch { $("share-url").select(); document.execCommand("copy"); $("share-state").textContent = okMsg; }
}
$("share-url").addEventListener("focus", e => e.target.select());
$("share-copy").onclick = () => copyText(shareUrl, "已複製連結。");
$("share-copy-msg").onclick = () => copyText(
  `您好，您在辰墨軒問的字，老師已經解讀完成了。\n請點下面的連結查看您寫的字和老師的解讀：\n${shareUrl}`,
  "已複製通知訊息，可以直接貼到 LINE 或簡訊。");

// ---- 是否在問事者頁面顯示贊助區塊 ----
$("sponsor-toggle")?.addEventListener("change", async (e) => {
  const box = e.target, st = $("sponsor-state");
  st.textContent = "";
  try {
    const r = await fetch(`/api/master/cases/${caseId}/sponsor`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ show: box.checked }),
    });
    if (!r.ok) throw new Error();
    st.textContent = box.checked ? " 已設為顯示" : " 已設為不顯示";
  } catch {
    box.checked = !box.checked;
    st.textContent = " 設定失敗，請再試一次";
  }
});
