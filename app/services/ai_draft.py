"""AI 解字草稿（Claude API）。

只負責產生「草稿」，一定由老師審閱後才送出。
古字說法要求模型只根據提供的《說文解字》原文說明，避免捏造典故。
未設定 ANTHROPIC_API_KEY 時回傳 None，系統仍會帶出字庫資料。
"""
from __future__ import annotations

import json
import logging

from app.config import get_settings

log = logging.getLogger(__name__)

SYSTEM = """你是協助測字老師的助理，熟悉文字學、《說文解字》與傳統測字（拆字、增損筆畫、會意聯想）。
請用台灣慣用的繁體中文書寫，不做恐嚇性斷言，不涉及醫療、法律、投資的具體建議。
「古字說法」可以保持文字學的準確用語；但「解讀」是要念給現代年輕人聽的，必須口語。
你寫的是給老師參考的草稿，老師會再修改。

規則：
1. 「古字說法」只能根據使用者提供的《說文解字》原文與段注來解說（例如六書歸類、字形構成、本義）。
   若資料中沒有說文條目，請明說「說文未收此字」，再依一般文字學常識簡述，並標註「需老師查證」。
   不要捏造甲骨文、金文字形的具體描述。
2. 「字義」：辭典釋義系統已另外列出，你只需用兩三句話說明從本義到引申義的脈絡。
3. 「解讀」結合問事者的問題、此字的拆解（部件、增減筆畫可成何字）、筆跡觀察，寫 150 到 300 字的測字解讀草稿。
   「解讀」的語氣要像一位溫和的長輩或朋友坐在對面，用日常說話的方式聊天，直接對「你」說話：
   - 用白話、短句，一句話講一件事。不要文言文、不要「宜」「蓋」「乃」「爻」「恐」「勿」這類書面詞，
     例如不說「宜穩中求進」，改說「這陣子比較適合穩穩來，不要急著衝」。
   - 不要故作玄虛、不堆砌成語，也不要說教。拆字要說得白話：「這個字上面是 X，下面是 Y，意思是……」。
   - 先講這個字讓你想到什麼，再回到問事者問的事，最後給一個具體、可以做的小建議。
   - 不下絕對的結論，用「看起來」「比較像是」「可以考慮」這種留有餘地的說法。
   若此字是問事者從系統隨機提供的候選字中自選的，可以從「在這些字中偏偏選了它」切入；沒有筆跡時不要談筆跡。
   若資料中有「稱呼」，請在解讀開頭自然地叫一次對方（例如「小明，…」），之後用「你」就好，不要每句都叫名字。
   若資料中有「這是追問」，代表問事者在上一輪解讀後接著追問：請先簡短呼應前面問過的問題與字，
   並評估前後的延續與變化（例如「上次你問…，那時看到…；這次這個字又說明…」），
   再結合這一次的字與新問題，給出前後連貫、不互相矛盾的綜合判斷，不要把這一次當成全新的一題。
   若資料中有「同一位問事者以前還問過」，那是這個人其他時間問過的事：只在確實相關時簡短帶到
   （例如「你之前也問過工作，這次的字和上次的方向一致」），不相關就不要提，也不要硬湊。
4. 「五行補充」用一兩句話說明此字在各種五行判法下的取捨建議。
5. 若資料中有「參考卦」，另外輸出兩段：
   gua_note：給老師看的卦象簡析，可以用六爻術語（世應、用神、旺衰、動變），150 字內；
   gua_plain：給問事者看的白話卦象說明，100 到 180 字，不用爻、六親、世應、用神等術語，口氣和「解讀」一樣。
   兩者都只能依提供的盤面事實，不要自己重新排盤，也不要捏造沒有的爻或六親。沒有「參考卦」就不要輸出這兩個欄位。
只輸出一個 JSON 物件，欄位為 ancient、meaning、reading、wuxing_note（有參考卦時再加 gua_note、gua_plain），不要輸出其他文字。"""


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def generate_ex(context: str) -> tuple[dict | None, str]:
    """回傳（草稿, 失敗原因）。未設定 API Key 時原因為空字串；失敗會自動重試一次。"""
    s = get_settings()
    if not s.anthropic_api_key:
        return None, ""
    try:
        from anthropic import AsyncAnthropic
    except Exception:  # noqa: BLE001
        return None, "伺服器沒有安裝 anthropic 套件"
    client = AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=2, timeout=90)
    reason = ""
    for attempt in (1, 2):
        try:
            msg = await client.messages.create(
                model=s.anthropic_model,
                max_tokens=4000,          # 中文 JSON 容易超過 2000 token 而被截斷
                system=SYSTEM,
                messages=[{"role": "user", "content": context}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            data = _extract_json(text)
            if data and str(data.get("reading", "")).strip():
                return data, ""
            reason = ("AI 回覆被截斷" if getattr(msg, "stop_reason", "") == "max_tokens"
                      else "AI 回覆的格式不是預期的 JSON，或沒有寫出解讀")
            log.warning("AI draft attempt %s: %s (stop=%s)", attempt, reason, getattr(msg, "stop_reason", ""))
        except Exception as e:  # noqa: BLE001
            reason = f"{type(e).__name__}：{str(e)[:160]}"
            log.exception("AI draft attempt %s failed", attempt)
    return None, reason


async def ping() -> tuple[bool, str]:
    """測試 AI 連線：送一個極小的請求，回報成功或失敗原因（給老師的「系統狀態」頁用）。"""
    s = get_settings()
    if not s.anthropic_api_key:
        return False, "尚未設定 ANTHROPIC_API_KEY（雲端要設在 Secret Manager，並重新部署）"
    try:
        from anthropic import AsyncAnthropic
    except Exception:  # noqa: BLE001
        return False, "伺服器沒有安裝 anthropic 套件"
    try:
        client = AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=0, timeout=30)
        msg = await client.messages.create(model=s.anthropic_model, max_tokens=16,
                                           messages=[{"role": "user", "content": "只回答：好"}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return True, f"連線正常（模型 {s.anthropic_model}，回覆：{text[:20]}）"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}：{str(e)[:200]}"


async def generate(context: str) -> dict | None:
    data, _ = await generate_ex(context)
    return data
