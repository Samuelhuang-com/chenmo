import { Player, strokeDuration } from "./replay.js";
import { visibleStrokes } from "./ink.js";
import { Socket } from "./ws-client.js";

const $ = id => document.getElementById(id);
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
  $("send").textContent = revision ? "重送解讀" : "送出解讀";
  $("retract").hidden = s !== "answered";
  $("rewrite").hidden = s !== "submitted";
  $("answer").readOnly = s === "answered";
  $("jiezi-run").disabled = s === "answered";
  if (s === "answered") {
    $("save-state").textContent = "已送出給問事者。要修改請先按「收回」。";
    if (c && c.answered_at) $("sent-info").textContent =
      `第 ${c.revision} 次送出，${new Date(c.answered_at).toLocaleString("zh-TW", { hour12: false })}`;
  } else if (was === "answered") {
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
    beforeJiezi = $("answer").value;
    $("answer").value = d.text;
    $("answer").dataset.auto = "";
    onAnswerChanged();
    $("jiezi-undo").hidden = false;
    btn.textContent = "重新產生";
    $("jiezi-state").textContent = d.cached ? "已帶出先前產生的內容。要重新產生請再按一次「重新產生」。"
      : d.ai_used ? "已帶出。標示「AI 草稿」的段落請審閱修改後再送出。"
      : "已帶出字庫資料。尚未設定 AI，字義與解讀請老師補充。";
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
  $("answer").value = beforeJiezi; beforeJiezi = null; $("jiezi-undo").hidden = true;
  onAnswerChanged();
};

async function load() {
  const r = await fetch(`/api/master/cases/${caseId}`);
  if (r.status === 401) { location.href = "/master/login"; return; }
  const d = await r.json();
  events = d.events;
  $("question").textContent = d.case.question || "（尚未填寫）";
  $("profile").textContent = d.case.profile_text || "（尚未填寫年次與性別）";
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
    if (msg.case.profile_text) $("profile").textContent = msg.case.profile_text;
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
    case "profile": $("profile").textContent = msg.text || "（尚未填寫年次與性別）"; return;
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

// ---- 預覽「問事者會看到的內容」：只取【解讀】 ----
const AI_MARK = "（AI 草稿，請審閱）";
function publicReading(text) {
  const heads = [...text.matchAll(/^【([^】\n]+)】[ \t]*$/gm)];
  for (let i = 0; i < heads.length; i++) {
    if (heads[i][1].trim() !== "解讀") continue;
    const start = heads[i].index + heads[i][0].length;
    const end = i + 1 < heads.length ? heads[i + 1].index : text.length;
    return text.slice(start, end).replaceAll(AI_MARK, "").trim();
  }
  return "";
}

// ---- 自動暫存老師的解字稿 ----
let saveTimer = 0;
function onAnswerChanged() {
  $("preview").textContent = publicReading($("answer").value);
  if (caseStatus === "answered") return;
  clearTimeout(saveTimer);
  $("save-state").textContent = "編輯中…";
  saveTimer = setTimeout(async () => {
    const r = await fetch(`/api/master/cases/${caseId}/notes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: $("answer").value }),
    }).catch(() => null);
    $("save-state").textContent = r && r.ok ? "解字稿已自動暫存" : "暫存失敗，請檢查連線";
  }, 1200);
}
$("answer").addEventListener("input", onAnswerChanged);
$("preview").textContent = publicReading($("answer").value);

function errText(d, fallback) {
  return Array.isArray(d.detail) ? d.detail.map(x => x.msg).join("；") : (d.detail || fallback);
}

// ---- 送出／重送 ----
$("send").onclick = async () => {
  $("error").textContent = "";
  const body = $("answer").value.trim();
  if (!publicReading(body)) {
    $("error").textContent = "【解讀】段落是空的。問事者只會收到【解讀】，請先寫好這一段。";
    return;
  }
  $("send").disabled = true;
  clearTimeout(saveTimer);
  try {
    const r = await fetch(`/api/master/cases/${caseId}/answer`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errText(d, "送出失敗"));
    revision = d.revision;
    setStatus("answered", { revision: d.revision, answered_at: Date.now() });
    $("save-state").textContent = "已送出，問事者頁面已更新。要修改請先按「收回」。";
  } catch (e) {
    $("error").textContent = e.message;
    $("send").disabled = caseStatus !== "submitted";
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
