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
請用台灣慣用的繁體中文書寫，語氣沉穩、溫和，不做恐嚇性斷言，不涉及醫療、法律、投資的具體建議。
你寫的是給老師參考的草稿，老師會再修改。

規則：
1. 「古字說法」只能根據使用者提供的《說文解字》原文與段注來解說（例如六書歸類、字形構成、本義）。
   若資料中沒有說文條目，請明說「說文未收此字」，再依一般文字學常識簡述，並標註「需老師查證」。
   不要捏造甲骨文、金文字形的具體描述。
2. 「字義」：辭典釋義系統已另外列出，你只需用兩三句話說明從本義到引申義的脈絡。
3. 「解讀」結合問事者的問題、此字的拆解（部件、增減筆畫可成何字）、筆跡觀察，寫 150 到 300 字的測字解讀草稿。
   若此字是問事者從系統隨機提供的候選字中自選的，可以從「在這些字中偏偏選了它」切入；沒有筆跡時不要談筆跡。
4. 「五行補充」用一兩句話說明此字在各種五行判法下的取捨建議。
只輸出一個 JSON 物件，欄位為 ancient、meaning、reading、wuxing_note，不要輸出其他文字。"""


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def generate(context: str) -> dict | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=s.anthropic_api_key)
        msg = await client.messages.create(
            model=s.anthropic_model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": context}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = _extract_json(text)
        if not data:
            log.warning("AI draft: response was not JSON")
        return data
    except Exception:  # noqa: BLE001
        log.exception("AI draft failed")
        return None
