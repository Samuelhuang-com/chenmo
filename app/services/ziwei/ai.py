"""紫微 AI 解命盤草稿：把盤面整理成事實文字，交給 Claude 寫成口語解說。

結果只給老師審閱，不直接呈現給問事者。未設定 ANTHROPIC_API_KEY 時回傳說明文字，不會壞掉。
"""
from __future__ import annotations

from app.config import get_settings

from .chart import PALACE_NAMES, Chart, liunian_overlay

SYSTEM = """你是紫微斗數的輔助撰寫者。使用者會給你一張盤的事實資料，請用口語、白話的方式，寫成給問事者聽的解說草稿，供老師審閱修改。

若資料中有「問事內容」，先用 2 到 3 句直接回應這個問題（仍遵守下列規則），再依序寫三段。

【輸出結構】依序三段，每段用小標題：
一、這十年的大運：現行大限落在哪一宮、這段時間的重心在哪裡。
二、今年的重點：依序談下面五個預設主題，每個主題 2 到 4 句：
  1. 事業：看官祿宮
  2. 財富：看財帛宮
  3. 貴人：看交友宮，並留意天魁、天鉞、左輔、右弼
  4. 工作：看官祿宮的日常面，並參考遷移、疾厄的負荷
  5. 婚姻感情：看夫妻宮
  若盤面另外出現下列主題，再加一段「另外要留意」，最多列 2 項：
  - 健康：疾厄宮
  - 出外與變動：遷移宮
  - 居住與家庭：田宅宮
  - 學業、考試與文書：父母宮（文昌、文曲）
  - 官非與是非：煞星出現在官祿、遷移、夫妻或疾厄宮
  - 桃花：貪狼、紅鸞、天喜
  - 破財：破軍，或財帛宮有煞星
  - 心態與休息：福德宮
三、本月注意事項：依資料中「本月」的流月宮位，給 2 到 3 條具體可做的小提醒。

【語氣與用字】
1. 口語、親切，像在跟對方聊天；避免艱深術語，不要堆砌星名。星名只在必要時提一次，並用白話解釋它的意思。
2. 不把「化忌」「煞星」等術語直接丟給問事者，改說「這裡容易卡關」「需要多留意」。
3. 全文約 800 字以內，用小標題與短段落。

【固定規則（一定要遵守）】
1. 不下絕對吉凶，不說「一定會」「必然」「註定」。
2. 不恐嚇，不用「破財」「血光」「凶」等字眼做結論；提到風險時，只說「可以多留意」與怎麼做。
3. 健康：只說「注意作息、定期檢查」，不下病名、不提時間點或期限、不推斷病情嚴重程度。
4. 壽元、死亡、重大疾病：一律不解讀，也不提及；若資料中出現，不列入內容。
5. 感情：不判斷「會分手」「會出軌」「不會結婚」等結論，只談相處與溝通上可以注意的地方。
6. 官非與意外：只提醒「凡事多留心、保留證據、避免衝突」，不寫具體事件。
7. 金錢：不推薦投資標的，不給具體買賣時機，只談理財與消費習慣上的提醒。
8. 只根據資料推論，不要編造資料中沒有的星曜或宮位；資料沒有的主題就不寫。
9. 若問事者的困擾超出命盤能回答的範圍（如醫療、法律），建議向專業人士諮詢。
10. 最後一行固定寫「※ AI 草稿，須經老師審閱後才可使用。」
輸出為繁體中文，分段即可。"""


def facts_text(chart: Chart, year: int, month: int | None = None, question: str | None = None) -> str:
    """把盤面整理成純文字事實（不含任何推論）。month 為當月（農曆以外的西曆月），有則加上流月。"""
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
    if month:
        lm = (ov["ming"] + month - 1) % 12        # 流月：從流年命宮起正月，順行
        k = (ov["ming"] - lm) % 12
        pal = chart.palaces[lm]
        lines.append(f"本月（{month}月）：流月落在本命{pal.name}（{pal.branch}），即流{PALACE_NAMES[k]}")
    if question:
        lines.insert(0, f"問事內容：{question}")
    return "\n".join(lines)


async def interpret(text: str) -> tuple[str | None, str]:
    """回傳 (草稿文字, 訊息)。草稿為 None 時，訊息說明原因。"""
    s = get_settings()
    if not s.anthropic_api_key:
        return None, "尚未設定 ANTHROPIC_API_KEY，無法使用解命盤"
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
