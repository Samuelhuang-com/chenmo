"""組合「解字」五段內容：此字、五行、古字說法、字義、解讀。

字庫可查到的（部首、筆畫、注音、五行、說文）直接帶出；
字義與解讀需要 AI，沒有設定 AI 時保留空位讓老師填寫。
"""
from __future__ import annotations

from app.models import Case
from app.services import ai_draft
from app.services.chardict import CharInfo, lookup
from app.services.stroke_features import StrokeFeatures, analyze

from app.services.sections import AI_MARK  # noqa: E402
NO_AI = "（尚未設定 AI，請老師補充）"


def pick_text(case: Case) -> str:
    if case.char_source != "picked":
        return ""
    rounds = f"換到第 {case.pick_rounds} 組才選定，" if case.pick_rounds > 1 else ""
    return f"此字為學生自選：從系統隨機提供的 {len(case.offered)} 字中選出（{rounds}候選：{'、'.join(case.offered)}）。"


def _sec_char(i: CharInfo, f: StrokeFeatures, case: Case | None = None) -> str:
    if not i.found:
        return f"{i.char}（字庫未收錄，請老師補充部首與筆畫）"
    lines = [f"{i.char}　注音 {i.zhuyin or '—'}　拼音 {i.pinyin or '—'}",
             f"部首：{i.radical_char}　總筆畫：{i.total_strokes}　康熙筆畫：{i.kangxi_strokes}"]
    if i.traditional and i.traditional != i.char:
        lines.append(f"繁體：{i.traditional}")
    lines += i.notes
    picked = pick_text(case) if case else ""
    if picked:
        lines.append(picked)
    if f.count:
        lines.append(("描寫觀察：" if picked else "筆跡觀察：") + "".join(f.observations))
    elif not picked:
        lines.append("筆跡觀察：（沒有筆跡）")
    return "\n".join(lines)


def _sec_wuxing(i: CharInfo, ai: dict | None) -> str:
    lines = []
    if i.wuxing_override:
        lines.append(f"老師自訂：{i.wuxing_override}")
    if i.kangxi_strokes:
        lines.append(f"依康熙筆畫（{i.kangxi_strokes} 畫，尾數 {i.kangxi_strokes % 10}）：{i.wuxing_by_strokes}")
    if i.radical_char:
        lines.append(f"依部首（{i.radical_char}）：{i.wuxing_by_radical or '此部首未列入對照表'}")
    note = (ai or {}).get("wuxing_note")
    lines.append(f"綜合：{note}{AI_MARK}" if note else "綜合：請老師判定")
    return "\n".join(lines)


def _sec_ancient(i: CharInfo, ai: dict | None) -> str:
    sw = i.shuowen
    lines = []
    if sw:
        head = sw["w"] if sw["w"] == i.char else f"{sw['w']}（{i.char}）"
        lines.append(f"《說文解字．{sw['r']}部》{head}：「{sw['e']}」")
        if sw.get("f"):
            lines.append(f"反切：{sw['f']}")
        for v in sw.get("v", []):
            if v.get("e"):
                lines.append(f"重文「{v['w']}」：{v['e']}")
        if sw.get("d"):
            d = sw["d"]
            lines.append(f"段玉裁注（節錄）：{d[:160]}{'……' if len(d) > 160 else ''}")
    else:
        lines.append("《說文解字》未收此字。")
    if ai and ai.get("ancient"):
        lines.append(f"{ai['ancient']}{AI_MARK}")
    return "\n".join(lines)


def _sec_meaning(i: CharInfo, ai: dict | None) -> str:
    lines = []
    moe = i.moe
    if moe:
        lines.append("依教育部《重編國語辭典修訂本》：")
        for h in moe["h"]:
            if not h["defs"]:
                continue
            if len(moe["h"]) > 1:
                lines.append(f"〔{h['b']}〕")
            for n, d in enumerate(h["defs"][:6], 1):
                kind = f"［{d['t']}］" if d.get("t") else ""
                lines.append(f"{n}. {kind}{d['d']}{d['x']}")
            if len(h["defs"]) > 6:
                lines.append(f"（另有 {len(h['defs']) - 6} 義，見辭典）")
        if moe.get("w"):
            lines.append("常用詞：" + "、".join(moe["w"]))
    else:
        lines.append("（辭典未收此字）")
    if ai and ai.get("meaning"):
        lines.append(f"{ai['meaning']}{AI_MARK}")
    return "\n".join(lines)


def _sec_ai(ai: dict | None, key: str) -> str:
    if ai and ai.get(key):
        return f"{ai[key]}{AI_MARK}"
    return NO_AI


def build_context(case: Case, i: CharInfo, f: StrokeFeatures) -> str:
    sw = i.shuowen
    sw_text = "無" if not sw else (
        f"字頭：{sw['w']}；部首：{sw['r']}；說解：{sw['e']}；反切：{sw['f']}；"
        f"重文：{'；'.join(v['w'] + '：' + v['e'] for v in sw.get('v', [])) or '無'}；"
        f"段注節錄：{sw.get('d', '')}")
    moe_text = "無" if not i.moe else "；".join(
        f"{h['b']} " + " / ".join(d["d"] for d in h["defs"][:6]) for h in i.moe["h"])
    chain = "".join(f"\n第 {n} 輪：問「{c.get('question', '')}」，所寫的字「{c.get('char', '')}」"
                    for n, c in enumerate(case.follow_chain, 1))
    follow_text = (f"\n這是追問。前面已問過（由舊到新）：{chain}\n請把前面的問題與字一起納入，綜合判斷，"
                   "不要只看這一次的字。" if chain else "")
    return f"""問事者：{case.profile_text or '未填寫'}{follow_text}
問事者的問題：{case.question or '（未填寫）'}
所寫的字：{i.char}
部首：{i.radical_char}；總筆畫：{i.total_strokes}；康熙筆畫：{i.kangxi_strokes}；注音：{i.zhuyin}
五行（依康熙筆畫尾數）：{i.wuxing_by_strokes or '未知'}；五行（依部首）：{i.wuxing_by_radical or '未列入'}
《說文解字》資料：{sw_text}
辭典釋義：{moe_text}
選字方式：{pick_text(case) or '問事者自己手寫'}
筆跡觀察：{''.join(f.observations) if f.count else '無'}"""


async def compose(case: Case, events: list[dict], char: str, use_ai: bool = True) -> dict:
    info = lookup(char)
    feats = analyze(events, info.total_strokes or None)
    ai, ai_error = (await ai_draft.generate_ex(build_context(case, info, feats))) if use_ai else (None, "")
    sections = {
        "此字": _sec_char(info, feats, case),
        "五行": _sec_wuxing(info, ai),
        "古字說法": _sec_ancient(info, ai),
        "字義": _sec_meaning(info, ai),
        "解讀": _sec_ai(ai, "reading"),
    }
    text = "\n\n".join(f"【{k}】\n{v}" for k, v in sections.items())
    return {"char": char, "sections": sections, "text": text, "ai_used": bool(ai), "ai_error": ai_error,
            "features": feats.__dict__}
