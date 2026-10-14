"""紫微流年 AI 草稿：把流年盤整理成事實文字，交給 Claude 寫「流年注意事項」。

結果只給老師審閱，不直接呈現給問事者。未設定 ANTHROPIC_API_KEY 時回傳說明文字，不會壞掉。
"""
from __future__ import annotations

from app.config import get_settings

from .chart import PALACE_NAMES, Chart, liunian_overlay

SYSTEM = """你是紫微斗數的輔助撰寫者。使用者會給你一張流年盤的事實資料，請寫出「流年注意事項」草稿，供老師審閱修改。
要求：
1. 先說明流年命宮落在本命的哪一宮，以及該宮位的主要方向。
2. 說明流年四化落在哪些宮位，各自代表的影響方向。
3. 提醒流年雜曜（紫字）與值得留意的宮位組合。
4. 簡述此時所在的大限背景。
5. 語氣務實，不下絕對吉凶，不用恐嚇用語；只根據給的資料推論，不要編造資料中沒有的星曜或宮位。
6. 最後一行固定寫「※ AI 草稿，須經老師審閱後才可使用。」
輸出為繁體中文，分段條列即可。"""


def facts_text(chart: Chart, year: int) -> str:
    """把流年盤整理成純文字事實（不含任何推論）。"""
    ov = liunian_overlay(chart, year)
    lines = [
        f"流年：{ov['year']}年 {ov['gz']}（虛歲 {ov['age']}）",
        f"命盤：{chart.yinyang}　{chart.ju}　命宮{chart.ming_gz}（{chart.ming_branch}）"
        f"　身宮在{chart.shen_branch}　命主{chart.ming_lord}　身主{chart.shen_lord}",
    ]
    cur = next((p for p in chart.palaces if p.decade and p.decade[0] <= ov["age"] <= p.decade[1]), None)
    if cur:
        lines.append(f"現行大限：{cur.decade[0]}~{cur.decade[1]}歲，大限在本命{cur.name}（{cur.stem}{cur.branch}）")
    lines.append(f"流年命宮：流年地支{ov['branch']}，即本命{chart.palaces[ov['ming']].name}")
    lines.append("流年各宮（流宮名｜所在本命宮｜本命星｜流年四化｜流年雜曜）：")
    for k in range(12):
        b = (ov["ming"] - k) % 12                  # 流年宮名依序逆排
        pal = chart.palaces[b]
        stars = "、".join(
            [s.name + (f"化{s.hua}" if s.hua else "") for s in pal.majors]
            + [s.name for s in pal.aux]) or "無"
        marks = "、".join(ov["marks"][b]) or "無"
        aux = "、".join(ov["aux_marks"][b]) or "無"
        lines.append(f"流{PALACE_NAMES[k]}｜本命{pal.name}（{pal.branch}）｜{stars}｜{marks}｜{aux}")
    return "\n".join(lines)


async def interpret(text: str) -> tuple[str | None, str]:
    """回傳 (草稿文字, 訊息)。草稿為 None 時，訊息說明原因。"""
    s = get_settings()
    if not s.anthropic_api_key:
        return None, "尚未設定 ANTHROPIC_API_KEY，無法使用 AI 解讀"
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return None, "伺服器沒有安裝 anthropic 套件"
    client = AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=2, timeout=90)
    try:
        msg = await client.messages.create(
            model=s.anthropic_model, max_tokens=2000, system=SYSTEM,
            messages=[{"role": "user", "content": text}])
    except Exception as e:  # noqa: BLE001
        return None, f"AI 呼叫失敗：{e}"
    out = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return (out or None), ("" if out else "AI 沒有回傳內容")
