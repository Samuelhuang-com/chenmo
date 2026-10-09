import { Socket } from "./ws-client.js";

const STALE_MS = 30 * 60 * 1000; // 30 分鐘沒寫任何一筆的草稿不顯示
let cases = [];
const live = new Map(); // case_id -> 最後一次收到筆畫的時間

function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }
function fmt(ms) {
  if (!ms) return "";
  const d = new Date(ms);
  return d.toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

function ticket(c) {
  const isLive = c.status === "drafting" && Date.now() - (live.get(c.id) || 0) < 15000;
  const time = c.status === "answered" ? c.answered_at : c.status === "submitted" ? c.submitted_at : c.updated_at;
  return `<a class="ticket${isLive ? " live" : ""}" href="/master/case/${c.id}">
    <div class="t-char grid-paper">${esc(c.char) || ""}</div>
    <div><p class="t-q">${esc(c.question) || "（尚未填寫問題）"}${c.char_source === "picked" ? '<span class="tag-pick">自選</span>' : ""}</p>
    <div class="t-meta">${c.nickname ? "<b>" + esc(c.nickname) + "</b>　" : ""}${c.profile_text ? esc(c.profile_text.replace(/（.*?）/, "")) + "，" : ""}${c.stroke_count} 筆，${fmt(time)}</div></div></a>`;
}

function render() {
  const now = Date.now();
  const groups = { drafting: [], submitted: [], answered: [] };
  for (const c of cases) {
    if (c.status === "drafting" && now - c.updated_at > STALE_MS && !live.has(c.id)) continue;
    groups[c.status]?.push(c);
  }
  groups.submitted.sort((a, b) => a.submitted_at - b.submitted_at); // 先到先解
  groups.answered = groups.answered.slice(0, 10);
  for (const [k, list] of Object.entries(groups)) {
    document.getElementById(`col-${k}`).innerHTML =
      list.map(ticket).join("") || `<p class="empty">${{ drafting: "目前沒有人在書寫。", submitted: "沒有待解的字。", answered: "還沒有解過的字。" }[k]}</p>`;
    document.getElementById(`n-${k}`).textContent = !list.length ? "" : k === "answered" ? `最近 ${list.length} 件` : `${list.length} 件`;
  }
}

async function reload() {
  const r = await fetch("/api/master/cases");
  if (r.status === 401) { location.href = "/master/login"; return; }
  cases = (await r.json()).cases;
  render();
}

function upsert(c) {
  const i = cases.findIndex(x => x.id === c.id);
  if (i >= 0) cases[i] = c; else cases.unshift(c);
  if (c.status === "answered") cases.sort((a, b) => (b.answered_at || 0) - (a.answered_at || 0));
  render();
}

new Socket("/ws/master", msg => {
  if (msg.type === "case_new" || msg.type === "case_update") return upsert(msg.case);
  if (msg.type === "case_deleted") { cases = cases.filter(x => x.id !== msg.case_id); return render(); }
  const c = cases.find(x => x.id === msg.case_id);
  if (!c) return reload();
  live.set(c.id, Date.now());
  if (msg.type === "stroke_end") c.stroke_count += 1;
  if (msg.type === "undo") c.stroke_count = Math.max(c.stroke_count - 1, 0);
  if (msg.type === "clear") c.stroke_count = 0;
  if (msg.type === "question") c.question = msg.text;
  if (msg.type === "profile") { c.profile_text = msg.text; if (msg.nickname !== undefined) c.nickname = msg.nickname; }
  if (msg.type === "pick") { c.char = msg.char; c.char_source = "picked"; }
  if (msg.type === "unpick") { c.char = ""; c.char_source = ""; }
  c.updated_at = Date.now();
  render();
}, s => { if (s === "open") reload(); });

setInterval(render, 5000);
reload();
