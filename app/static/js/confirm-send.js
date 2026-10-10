// 送出前確認框：讓老師在送出前，再核對一次「這份解讀是寫給誰」。
// 所有內容都用 textContent 填入（暱稱、問題是問事者輸入的字串，不可當成 HTML）。

const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  kids.forEach(k => n.append(k));
  return n;
};

/**
 * @param {{rows: [string,string][], warning?: string, warningLabel?: string, okLabel?: string}} opt
 * @returns {Promise<{ok: boolean, ackWarning: boolean}>}
 */
export function confirmSend({ rows, warning = "", warningLabel = "我確定沒有貼錯，仍要送出", okLabel = "確定送出" }) {
  return new Promise(resolve => {
    const dlg = el("dialog", { className: "confirm-dialog" });
    dlg.setAttribute("aria-labelledby", "cs-title");
    const dl = el("dl", { className: "cs-list" });
    rows.forEach(([k, v]) => dl.append(el("dt", { textContent: k }), el("dd", { textContent: v || "（空白）" })));

    const ok1 = el("input", { type: "checkbox" });
    const ok2 = el("input", { type: "checkbox" });
    const goBtn = el("button", { type: "submit", className: "btn btn-zhu", value: "ok", textContent: okLabel, disabled: true });
    const cancelBtn = el("button", { type: "submit", className: "btn", value: "cancel", textContent: "再檢查一下" });
    cancelBtn.formNoValidate = true;

    const sync = () => { goBtn.disabled = !(ok1.checked && (!warning || ok2.checked)); };
    ok1.onchange = ok2.onchange = sync;

    const form = el("form", { method: "dialog" },
      el("h3", { id: "cs-title", textContent: "送出前請再核對一次" }),
      dl,
      ...(warning ? [el("p", { className: "cs-warn", role: "alert", textContent: warning })] : []),
      el("label", { className: "cs-check" }, ok1, " 我已核對，這份解讀是寫給上面這位問事者的"),
      ...(warning ? [el("label", { className: "cs-check" }, ok2, " " + warningLabel)] : []),
      el("div", { className: "cs-actions" }, cancelBtn, goBtn));
    dlg.append(form);
    document.body.append(dlg);

    dlg.addEventListener("close", () => {
      const ok = dlg.returnValue === "ok" && !goBtn.disabled;
      dlg.remove();
      resolve({ ok, ackWarning: ok && !!warning && ok2.checked });
    });
    dlg.showModal();
    ok1.focus();
  });
}

const trunc = (s, n) => { const a = [...(s || "").trim().replace(/\s+/g, " ")]; return a.length > n ? a.slice(0, n).join("") + "…" : a.join(""); };
export { trunc };
