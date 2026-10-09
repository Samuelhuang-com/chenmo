// 六龍問爻：填問題 → 擲三枚銅錢六次 → 呈送。
// 擲出的結果由後端決定（/api/yao/cases/{token}/toss），這裡只負責動畫與顯示。

const $ = (id) => document.getElementById(id);
const form = $("yao-form");

const NAMES = { 6: "老陰", 7: "少陽", 8: "少陰", 9: "老陽" };
const POS = ["初", "二", "三", "四", "五", "上"];
const STORE = "yao-token";

function init() {
  const q = $("question"), counter = $("counter"), max = +q.dataset.max;
  const count = () => { counter.textContent = `${[...q.value].length} / ${max}`; counter.classList.toggle("over", [...q.value].length > max); };
  q.addEventListener("input", count); count();

  let token = null, values = [], busy = false, manual = false, repeatOk = false;
  const TOKENS = "yao-tokens";
  const myTokens = () => { try { return JSON.parse(localStorage.getItem(TOKENS) || "[]"); } catch { return []; } };
  const rememberToken = (t) => { try { localStorage.setItem(TOKENS, JSON.stringify([t, ...myTokens().filter(x => x !== t)].slice(0, 20))); } catch {} };
  $("repeat-go").addEventListener("click", () => { repeatOk = true; $("repeat").hidden = true; form.requestSubmit(); });

  const err = (msg) => { const e = $("form-error"); e.textContent = msg || ""; e.hidden = !msg; if (msg) e.scrollIntoView({ block: "center", behavior: "smooth" }); };

  const lockForm = () => {
    form.querySelectorAll("input, select, textarea, button").forEach(el => el.disabled = true);
    $("start-row").hidden = true;
    $("stage").hidden = false;
    $("stage").scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ---- 1. 開始起卦：建立案件 ----
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err("");
    const body = {
      question: q.value.trim(),
      birth_year: parseInt($("birth_year").value, 10) || 0,
      gender: form.querySelector("input[name=gender]:checked")?.value || "",
      nickname: $("nickname").value.trim(),
      asked_for: form.querySelector("input[name=asked_for]:checked")?.value || "自己",
      category: $("category").value,
      redo_of: form.dataset.redo, follow_of: form.dataset.follow,
    };
    if (!body.question) return err("請寫下想問的事。");
    if (!body.birth_year) return err("請填年次（民國）。");
    if (!body.gender) return err("請選擇性別。");
    if (!repeatOk) {
      const rr = await fetch("/api/yao/recent", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: body.question, category: body.category, tokens: myTokens() }) }).catch(() => null);
      const m = rr && rr.ok ? (await rr.json()).match : null;
      if (m) {
        const d = new Date(m.when);
        $("repeat-text").textContent = `${d.getMonth() + 1}/${d.getDate()} 你問過「${m.question}」${m.gua ? "，得" + m.gua : ""}。`;
        $("repeat-view").href = m.url;
        $("repeat").hidden = false;
        $("repeat").scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
    }
    $("start").disabled = true;
    const r = await fetch("/api/yao/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) {
      $("start").disabled = false;
      const d = await r.json().catch(() => ({}));
      const detail = Array.isArray(d.detail) ? d.detail.map(x => (x.msg || "").replace(/^Value error, /, "")).join("；") : d.detail;
      return err(detail || "送出失敗，請再試一次。");
    }
    token = (await r.json()).token;
    try { sessionStorage.setItem(STORE, token); } catch {}
    lockForm();
  });

  // ---- 2. 擲錢 ----
  const coinsBtn = $("coins");
  const coinEls = [...document.querySelectorAll(".coin-inner")];
  const spin = [0, 0, 0];   // 每枚目前的旋轉角度
  let pressAt = 0;

  const shakeStart = () => { if (busy || values.length >= 6 || manual) return; pressAt = performance.now(); coinsBtn.classList.add("shaking"); };
  const shakeEnd = () => { if (!pressAt) return; const ms = Math.round(performance.now() - pressAt); pressAt = 0; coinsBtn.classList.remove("shaking"); throwCoins(null, ms); };
  coinsBtn.addEventListener("pointerdown", shakeStart);
  coinsBtn.addEventListener("pointerup", shakeEnd);
  coinsBtn.addEventListener("pointerleave", () => { if (pressAt) shakeEnd(); });
  coinsBtn.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && !e.repeat) { e.preventDefault(); throwCoins(null, 0); } });

  document.querySelectorAll(".manual-btns button").forEach(b => b.addEventListener("click", () => throwCoins(+b.dataset.backs, 0)));
  $("manual-toggle").addEventListener("click", () => {
    manual = !manual;
    $("manual").hidden = !manual;
    coinsBtn.classList.toggle("is-manual", manual);
    $("manual-toggle").textContent = manual ? "改回線上擲錢" : "我想用自己的銅錢";
    updateRemind();
    $("calm").textContent = manual ? "用自己的三枚銅錢擲，每擲一次，在下面選出現了幾個「背」。" : "靜心片刻，心中默念所問。準備好了，按下銅錢。";
  });

  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function animateCoins(faces) {
    // faces：每枚 "背" 或 "字"；字面朝上 = 0°，背面朝上 = 180°
    return Promise.all(coinEls.map((el, i) => {
      const turns = 3 + Math.floor(Math.random() * 3);
      const end = Math.ceil(spin[i] / 360) * 360 + turns * 360 + (faces[i] === "背" ? 180 : 0);
      const from = spin[i];
      spin[i] = end;
      if (reduce) { el.style.transform = `rotateY(${end}deg)`; return Promise.resolve(); }
      const lift = 70 + Math.random() * 40;
      return el.animate([
        { transform: `translateY(0) rotateY(${from}deg)` },
        { transform: `translateY(-${lift}px) rotateY(${from + (end - from) * 0.55}deg)`, offset: 0.45 },
        { transform: `translateY(0) rotateY(${end - 20}deg)`, offset: 0.85 },
        { transform: `translateY(-6px) rotateY(${end - 6}deg)`, offset: 0.93 },
        { transform: `translateY(0) rotateY(${end}deg)` },
      ], { duration: 950 + i * 120, easing: "cubic-bezier(.3,.6,.4,1)", fill: "forwards" }).finished;
    }));
  }

  function drawLine(n, value, coins) {
    const slot = document.querySelector(`.slot[data-pos="${n}"]`);
    const yang = value === 7 || value === 9, moving = value === 6 || value === 9;
    slot.classList.add("filled", yang ? "yang" : "yin");
    slot.classList.toggle("moving", moving);
    slot.querySelector(".slot-mark").textContent = moving ? (yang ? "○" : "×") : "";
    slot.querySelector(".slot-text").textContent = `${NAMES[value]}${coins ? "　" + coins.join("") : ""}`;
  }

  function clearLines() {
    document.querySelectorAll(".slot").forEach(s => {
      s.className = "slot";
      s.querySelector(".slot-mark").textContent = "";
      s.querySelector(".slot-text").textContent = "";
    });
  }

  function updateCount() {
    $("toss-count").textContent = values.length < 6 ? `第 ${values.length + 1} 次・共 6 次（${POS[values.length]}爻）` : "六爻已成";
    coinsBtn.disabled = values.length >= 6;
    document.querySelectorAll(".manual-btns button").forEach(b => b.disabled = values.length >= 6);
  }

  async function throwCoins(backs, shakeMs) {
    if (busy || !token || values.length >= 6) return;
    busy = true;
    coinsBtn.classList.add("busy");
    const req = fetch(`/api/yao/cases/${token}/toss`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backs, shake_ms: shakeMs }),
    }).then(r => r.ok ? r.json() : Promise.reject(r));
    try {
      const res = await req;
      if (backs === null) await animateCoins(res.coins);
      else coinEls.forEach((el, i) => { spin[i] = res.coins[i] === "背" ? 180 : 0; el.style.transform = `rotateY(${spin[i]}deg)`; });
      try { navigator.vibrate?.(25); } catch {}
      if (backs === null) clink();
      values = res.values;
      drawLine(res.n, res.value, res.coins);
      updateCount();
      if (values.length === 6) finish(res.gua);
    } catch (e) {
      err("連線不穩，這一擲沒有記錄，請再擲一次。");
    } finally {
      busy = false;
      coinsBtn.classList.remove("busy");
    }
  }

  function finish(gua) {
    $("gua-title").textContent = gua || "";
    $("done").hidden = false;
    $("done").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  $("reset").addEventListener("click", async () => {
    if (!confirm("全部重擲？剛才的六爻會清除（老師看得到曾經重擲）。")) return;
    const r = await fetch(`/api/yao/cases/${token}/clear`, { method: "POST" });
    if (!r.ok) return err("清除失敗，請再試一次。");
    values = [];
    clearLines();
    $("done").hidden = true;
    updateCount();
  });

  $("submit").addEventListener("click", async () => {
    $("submit").disabled = true;
    const r = await fetch(`/api/yao/cases/${token}/submit`, { method: "POST" });
    if (!r.ok) {
      $("submit").disabled = false;
      const d = await r.json().catch(() => ({}));
      return err(d.detail || "呈送失敗，請再試一次。");
    }
    try { sessionStorage.removeItem(STORE); } catch {}
    rememberToken(token);
    location.href = (await r.json()).url;
  });

  // ---- 音效（預設關；用 Web Audio 合成銅錢聲，不需要音檔） ----
  let soundOn = false, ctx = null;
  try { soundOn = localStorage.getItem("yao-sound") === "1"; } catch {}
  const soundBtn = $("sound-toggle");
  const paintSound = () => { const l = `音效：${soundOn ? "開" : "關"}`; soundBtn.setAttribute("aria-label", l); soundBtn.title = l; soundBtn.setAttribute("aria-pressed", String(soundOn)); };
  soundBtn.addEventListener("click", () => {
    soundOn = !soundOn; paintSound();
    try { localStorage.setItem("yao-sound", soundOn ? "1" : "0"); } catch {}
    if (soundOn) { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); ctx.resume?.(); clink(); }
  });
  paintSound();
  function clink() {
    if (!soundOn) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.09, 0.16].forEach((delay, i) => {
        const t = ctx.currentTime + delay;
        [2300 + i * 260, 3700 + i * 180, 5200].forEach((f, k) => {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.type = "sine"; o.frequency.value = f;
          g.gain.setValueAtTime(0.0001, t);
          g.gain.exponentialRampToValueAtTime(0.12 / (k + 1), t + 0.004);
          g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35 - k * 0.08);
          o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + 0.4);
        });
      });
    } catch {}
  }

  // ---- 搖手機擲錢（DeviceMotion）：手機預設開啟；iPhone 要使用者先動作一次才能授權 ----
  const shakeBtn = $("shake-toggle");
  const canShake = "DeviceMotionEvent" in window && matchMedia("(pointer: coarse)").matches;
  const needPerm = canShake && typeof DeviceMotionEvent.requestPermission === "function";
  let shakeOn = false, shakeOff = false, shakeSince = 0, lastStrong = 0, shakeTimer = null;
  function updateRemind() {
    const el = $("toss-remind");
    el.hidden = manual;
    el.textContent = !canShake ? "按住銅錢搖一搖，放開就擲出。"
      : shakeOn ? "可以直接搖手機，或按下銅錢擲出。"
      : "可以按下銅錢擲出；點上方的手機圖示，就能改用搖手機。";
  }
  function paintShake() {
    shakeBtn.setAttribute("aria-pressed", String(shakeOn));
    const l = shakeOn ? "搖手機擲錢：開" : "搖手機擲錢：關";
    shakeBtn.setAttribute("aria-label", l); shakeBtn.title = l;
    updateRemind();
  }
  function onMotion(e) {
    if (busy || manual || values.length >= 6 || !token) return;
    const a = e.acceleration;
    let mag;
    if (a && a.x !== null) mag = Math.hypot(a.x, a.y, a.z);
    else { const g = e.accelerationIncludingGravity || {}; mag = Math.abs(Math.hypot(g.x || 0, g.y || 0, g.z || 0) - 9.8); }
    const now = performance.now();
    if (mag > 12) {
      if (!shakeSince) { shakeSince = now; coinsBtn.classList.add("shaking"); }
      lastStrong = now;
      clearTimeout(shakeTimer);
      shakeTimer = setTimeout(() => {   // 停下來 0.35 秒就擲出
        const held = lastStrong - shakeSince;
        coinsBtn.classList.remove("shaking");
        shakeSince = 0;
        if (held >= 300) throwCoins(null, Math.round(held));
      }, 350);
    }
  }
  async function setShake(on) {
    if (on && !shakeOn) {
      try {
        if (needPerm) {
          const res = await DeviceMotionEvent.requestPermission();
          if (res !== "granted") { err("手機沒有允許讀取動作感應，請直接按銅錢擲錢。"); return; }
        }
      } catch { err("這支手機不支援搖動擲錢，請直接按銅錢。"); return; }
      window.addEventListener("devicemotion", onMotion);
      shakeOn = true;
    } else if (!on && shakeOn) {
      window.removeEventListener("devicemotion", onMotion);
      shakeOn = false;
    }
    paintShake();
  }
  if (canShake) {
    shakeBtn.hidden = false;
    shakeBtn.addEventListener("click", () => { shakeOff = shakeOn; setShake(!shakeOn); });
    if (needPerm) coinsBtn.addEventListener("click", () => { if (!shakeOn && !shakeOff) setShake(true); });  // iPhone：第一次按銅錢時一併詢問授權
    else setShake(true);                                                                                   // Android：直接開啟
  }
  paintShake();

  // ---- 重新整理時接續未完成的卦 ----
  (async () => {
    let saved = null;
    try { saved = sessionStorage.getItem(STORE); } catch {}
    if (!saved || form.dataset.redo || form.dataset.follow) return;
    const r = await fetch(`/api/cases/${saved}`);
    if (!r.ok) return;
    const c = (await r.json()).case;
    if (c.kind !== "yao" || c.status !== "drafting") { try { sessionStorage.removeItem(STORE); } catch {} return; }
    token = saved;
    q.value = c.question; count();
    $("nickname").value = c.nickname || "";
    $("birth_year").value = c.birth_year || "";
    form.querySelectorAll("input[name=gender]").forEach(i => i.checked = i.value === c.gender);
    form.querySelectorAll("input[name=asked_for]").forEach(i => i.checked = i.value === c.asked_for);
    $("category").value = c.category || "";
    lockForm();
    values = c.yao_values || [];
    values.forEach((v, i) => drawLine(i + 1, v, null));
    updateCount();
    if (values.length === 6) finish(c.gua);
  })();

  updateCount();
}

if (form) init();
