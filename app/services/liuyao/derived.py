"""問字案件「以字起卦」的參考卦：把卦盤整理成文字，給老師看，也給 AI 草稿當依據。"""
from __future__ import annotations

from datetime import datetime

from app.services.liuyao import build_chart
from app.services.liuyao.calendar import TPE

HEAD = "參考卦"
MARK = "梅花易數｜"   # 解讀文字裡的標記：編輯器與預覽會把這一段換成「梅花易數」標題


def derived_chart(case):
    """依案件記錄的參考卦（六爻與起卦時間）排盤；沒有或資料壞掉時回傳 None。"""
    d = getattr(case, "derived_yao", None) or {}
    try:
        values, when = d["values"], datetime.fromisoformat(d["when"]).replace(tzinfo=TPE)
        return build_chart(values, when) if len(values) == 6 else None
    except Exception:
        return None


def reference_text(case) -> str:
    """參考卦的盤面事實（可用術語，只給老師看）。沒有參考卦時回傳空字串。"""
    chart = derived_chart(case)
    if not chart:
        return ""
    d = case.derived_yao
    t = chart.time
    rows = [f"梅花易數：以「{d.get('char', '')}」{d.get('strokes', '')} 畫加時辰起卦（參考卦，不是問事者自己擲的）",
            f"起卦時間：{t.when:%Y-%m-%d %H:%M}（{t.year}年 {t.month}月 {t.day}日 {t.hour}時），旬空：{''.join(t.xunkong)}",
            f"本卦：{chart.ben.name}（{chart.palace.palace}宮・{chart.palace.stage}）"
            + (f"　變卦：{chart.bian.name}" if chart.bian else "　靜卦，無動爻"),
            f"互卦：{chart.hu.name}　卦身：{chart.gua_shen}",
            "六爻（由上爻到初爻）："]
    for ln in reversed(chart.lines):
        parts = [ln.label, ln.liushen, f"{ln.liuqin}{ln.ganzhi}{ln.element}"]
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
    return "\n".join(rows)


def public_block(case, plain: str = "") -> str:
    """給問事者看的「梅花易數」段落（白話）：說明哪一卦代表現況、哪一卦代表走向，再接 AI 或老師寫的白話說明。"""
    from app.services.liuyao.gloss import gloss
    d = getattr(case, "derived_yao", None) or {}
    if not d.get("gua"):
        return ""
    ben, _, bian = d["gua"].partition(" → ")
    ch, strokes = d.get("char", ""), d.get("strokes", "")

    def one(name: str) -> str:
        g = gloss(name)
        return f"「{name}」" + (f"，白話說就是{g}" if g else "")

    intro = f"這是用你問的「{ch}」字（{strokes} 畫）加上起卦的時辰排出的一卦。本卦代表現在的狀況：{one(ben)}。"
    if bian:
        intro += f"變卦代表事情接下來的走向：{one(bian)}。"
    else:
        intro += "沒有明顯的變動，表示目前的狀態會持續一陣子。"
    intro += "這是用另一個角度看同一件事，可以和上面「字」的解讀互相對照。"
    return MARK + intro + (("\n\n" + plain.strip()) if plain.strip() else "")
