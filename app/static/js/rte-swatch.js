/* 解讀編輯器的「文字顏色」與「螢光筆」：只給幾個固定顏色的小選單。
   在內文選好文字後，按工具列的 A 或螢光筆，再點一個顏色。 */
(() => {
  const reading = document.getElementById("reading");
  const bar = document.getElementById("rte-bar");
  if (!reading || !bar) return;
  let saved = null;
  document.addEventListener("selectionchange", () => {
    const s = getSelection();
    if (s.rangeCount && reading.contains(s.anchorNode)) saved = s.getRangeAt(0).cloneRange();
  });
  const closeAll = () => bar.querySelectorAll(".sw-pop").forEach(p => { p.hidden = true; });
  // 按工具列不要讓內文失去選取
  bar.addEventListener("mousedown", e => { if (e.target.closest(".sw-trigger, .sw")) e.preventDefault(); });
  bar.addEventListener("click", e => {
    const t = e.target.closest(".sw-trigger");
    if (t) {
      const pop = document.getElementById(t.dataset.pop), open = pop.hidden;
      closeAll(); pop.hidden = !open; return;
    }
    const sw = e.target.closest(".sw");
    if (!sw) return;
    reading.focus();
    if (saved) { const s = getSelection(); s.removeAllRanges(); s.addRange(saved); }
    document.execCommand("styleWithCSS", false, true);
    if (sw.dataset.fore) document.execCommand("foreColor", false, sw.dataset.fore);
    if (sw.dataset.hilite) document.execCommand("hiliteColor", false, sw.dataset.hilite);
    reading.dispatchEvent(new Event("input"));
    closeAll();
  });
  document.addEventListener("click", e => { if (!e.target.closest(".swatch-wrap")) closeAll(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeAll(); });
})();
