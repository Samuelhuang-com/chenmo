"""AI 解卦草稿（Claude API）。只產生草稿，一定由老師審閱後才送出。

AI 拿到的資料：問事者的問題與稱呼、完整卦盤、老師選定的用神、《周易》經文、老師的斷卦規則庫、
同一位問事者以前問過的事。要求它只能引用給它的經文與規則，不可捏造古籍說法。
"""
from __future__ import annotations

import logging

from app.config import get_settings

log = logging.getLogger(__name__)

SYSTEM = """你是協助六爻卜卦老師的助理，熟悉六爻納甲筮法（用神、世應、旺衰、動變、空破、伏神）。
請用台灣慣用的繁體中文。你寫的是給老師參考的草稿，老師會再修改後才給問事者看。

規則：
1. 判斷只能根據資料中的「卦盤」「用神」「老師的斷卦規則」與「周易經文」。
   引用經文要照抄資料中的原句；引用規則要寫出規則標題。資料裡沒有的古籍、典故、斷語，一律不要寫。
2. 「解讀」是要給現代人看的：像一位溫和的長輩坐在對面聊天，直接對「你」說話。
   - 白話、短句，不要文言文、不要堆砌術語。若提到卦象，用一句白話說明意思。
   - 先講這一卦整體在說什麼，再回到他問的事，最後給一個具體、可以做的小建議。
   - 不下絕對的結論，用「看起來」「比較像是」「可以考慮」。不恐嚇，不做醫療、法律、投資的具體建議。
   - 若資料中有「稱呼」，開頭自然地叫一次對方，之後用「你」。
   - 若有「同一位問事者以前問過」，只在確實相關時簡短帶到，不相關就不要提。
   - 長度 150 到 300 字。
3. 「依據」：列出你的判斷用到的卦盤事實、規則、經文（每項一句），給老師核對，不會給問事者看。
4. 「追問」：三個問事者接下來可能想問的白話問題，每個 20 字以內。
只輸出一個 JSON 物件，欄位為 reading（字串）、basis（字串陣列）、followups（三個字串的陣列），不要輸出其他文字。"""


def chart_text(chart, yongshen) -> str:
    t = chart.time
    rows = [f"起卦時間：{t.when:%Y-%m-%d %H:%M}（{t.year}年 {t.month}月 {t.day}日 {t.hour}時），旬空：{''.join(t.xunkong)}",
            f"本卦：{chart.ben.name}（{chart.palace.palace}宮・{chart.palace.stage}）"
            + (f"　變卦：{chart.bian.name}" if chart.bian else "　靜卦，無動爻"),
            f"互卦：{chart.hu.name}　卦身：{chart.gua_shen}",
            "六爻（由上爻到初爻）："]
    for ln in reversed(chart.lines):
        parts = [f"{ln.label}", ln.liushen, f"{ln.liuqin}{ln.ganzhi}{ln.element}"]
        if ln.shi:
            parts.append("世")
        if ln.ying:
            parts.append("應")
        if ln.moving:
            parts.append(f"動，化{ln.change_liuqin}{ln.change_ganzhi}{ln.change_element}（{ln.change_relation}）")
        if ln.fu_liuqin:
            parts.append(f"伏{ln.fu_liuqin}{ln.fu_ganzhi}{ln.fu_element}")
        parts.append(f"月令{ln.month_state}")
        if ln.marks:
            parts.append("、".join(ln.marks))
        rows.append("　".join(parts))
    rows.append(f"用神：{yongshen.label}（{yongshen.reason}）"
                + (f"，在第 {'、'.join(map(str, yongshen.lines))} 爻" if yongshen.lines else "")
                + ("，不上卦，取伏神" if yongshen.hidden else ""))
    return "\n".join(rows)


def build_context(case, chart, yongshen, texts: dict, rules: list[dict], history: list) -> str:
    who = []
    if case.nickname:
        who.append(f"稱呼：{case.nickname}")
    if case.profile_text:
        who.append(f"問事者：{case.profile_text}")
    who.append(f"為誰而問：{case.asked_for or '自己'}")
    if case.category:
        who.append(f"類別：{case.category}")
    parts = ["\n".join(who), f"問題：{case.question}", "", "【卦盤】", chart_text(chart, yongshen), "",
             "【周易經文】", f"{texts['ben_name']} 卦辭：{texts['guaci']}", f"彖傳：{texts['tuan']}"]
    if texts["moving_lines"]:
        parts.append("動爻爻辭：" + "／".join(texts["moving_lines"]))
    if texts.get("bian_name"):
        parts.append(f"變卦 {texts['bian_name']} 卦辭：{texts['bian_guaci']}")
    parts += ["", "【老師的斷卦規則】"] + [f"・{r['title']}：{r['text']}" for r in rules]
    if case.follow_chain:
        parts += ["", "【這是追問，前面問過】"] + [f"・{c['question']}（{c.get('char', '')}）" for c in case.follow_chain]
    if history:
        parts += ["", "【同一位問事者以前問過】"]
        for h in history[:5]:
            what = h.gua or (f"字「{h.char}」" if h.char else "")
            parts.append(f"・{h.question}（{what}）：{(h.answer or '')[:80]}")
    return "\n".join(parts)


async def generate(context: str) -> tuple[dict | None, str]:
    """回傳（草稿, 失敗原因）。未設定 API Key 時原因為空字串。"""
    s = get_settings()
    if not s.anthropic_api_key:
        return None, ""
    try:
        from anthropic import AsyncAnthropic
    except Exception:  # noqa: BLE001
        return None, "伺服器沒有安裝 anthropic 套件"
    from app.services.ai_draft import _extract_json
    client = AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=2, timeout=90)
    reason = ""
    for attempt in (1, 2):
        try:
            msg = await client.messages.create(model=s.anthropic_model, max_tokens=3000, system=SYSTEM,
                                               messages=[{"role": "user", "content": context}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            data = _extract_json(text)
            if data and str(data.get("reading", "")).strip():
                data["followups"] = [str(x)[:40] for x in (data.get("followups") or [])][:3]
                data["basis"] = [str(x) for x in (data.get("basis") or [])][:12]
                return data, ""
            reason = "AI 回覆被截斷" if getattr(msg, "stop_reason", "") == "max_tokens" else "AI 回覆格式不對"
        except Exception as e:  # noqa: BLE001
            reason = f"{type(e).__name__}：{str(e)[:160]}"
            log.exception("yao AI draft attempt %s failed", attempt)
    return None, reason
