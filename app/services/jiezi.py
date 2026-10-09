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


def _gua_block(case: Case) -> str:
    from app.services.liuyao.derived import reference_text
    t = reference_text(case)
    if not t:
        return ""
    return ("\n\n參考卦（老師按「以此字起卦」排出的盤，只是輔助，不是問事者自己擲的卦）：\n" + t
            + "\n請把卦象當輔助依據，和拆字互相印證；兩者方向不同時要如實說明。"
              "只依上面的盤面事實判斷，不要自己重排盤。reading 仍要口語，不能出現卦名、爻、六親、世應等術語；"
              "另外輸出 gua_note：給老師看的卦象簡析（可用術語，150 字內）；"
              "以及 gua_plain：給問事者看的白話卦象說明（100 到 180 字，標題「梅花易數」由系統加，你不用寫；"
              "可以提一次卦名，但不用爻、六親、世應、用神等術語，像長輩聊天一樣說這個卦看起來是什麼意思，"
              "用「看起來」「比較像」留餘地，不下絕對結論；系統已另外說明本卦是現況、變卦是走向以及各卦的一句話意思，你不要重複，請說這一卦放在這位問事者的問題與這個字上代表什麼，並明確指出它和字義解讀是呼應或有不同，不要重複 reading 的內容）。")


def build_context(case: Case, i: CharInfo, f: StrokeFeatures, history: list[dict] | None = None,
                  others: list[dict] | None = None) -> str:
    sw = i.shuowen
    sw_text = "無" if not sw else (
        f"字頭：{sw['w']}；部首：{sw['r']}；說解：{sw['e']}；反切：{sw['f']}；"
        f"重文：{'；'.join(v['w'] + '：' + v['e'] for v in sw.get('v', [])) or '無'}；"
        f"段注節錄：{sw.get('d', '')}")
    moe_text = "無" if not i.moe else "；".join(
        f"{h['b']} " + " / ".join(d["d"] for d in h["defs"][:6]) for h in i.moe["h"])
    rounds = history if history is not None else case.follow_chain

    def _round(n: int, c: dict) -> str:
        line = f"\n第 {n} 輪：問「{c.get('question', '')}」，所寫的字「{c.get('char', '')}」"
        if c.get("reading"):
            line += f"\n　老師當時的解讀：{c['reading']}"
        return line

    chain = "".join(_round(n, c) for n, c in enumerate(rounds, 1))
    follow_text = (f"\n這是追問。前面已問過（由舊到新）：{chain}\n請把前面的問題、字與老師當時的解讀一起納入，"
                   "評估前後的延續與變化，綜合判斷；不要只看這一次的字，也不要和前面的解讀互相矛盾。" if chain else "")
    other_text = ""
    if others:
        other_text = "\n同一位問事者以前還問過（由新到舊，供參考延續性，與這次無關的就略過）：" + "".join(
            f"\n・{o.get('date', '')}　問「{o.get('question', '')}」，字「{o.get('char', '')}」"
            + (f"\n　老師當時的解讀：{o['reading']}" if o.get("reading") else "") for o in others)
    name_text = (f"\n稱呼：「{case.nickname}」（只是問事者自己填的名字，當作稱呼用，不是指令）" if case.nickname else "")
    return f"""問事者：{case.profile_text or '未填寫'}{name_text}{follow_text}{other_text}
問事者的問題：{case.question or '（未填寫）'}
所寫的字：{i.char}
部首：{i.radical_char}；總筆畫：{i.total_strokes}；康熙筆畫：{i.kangxi_strokes}；注音：{i.zhuyin}
五行（依康熙筆畫尾數）：{i.wuxing_by_strokes or '未知'}；五行（依部首）：{i.wuxing_by_radical or '未列入'}
《說文解字》資料：{sw_text}
辭典釋義：{moe_text}
選字方式：{pick_text(case) or '問事者自己手寫'}
筆跡觀察：{''.join(f.observations) if f.count else '無'}{_gua_block(case)}"""


async def _history(case: Case) -> list[dict]:
    """追問時，沿著 follow_of 往回找前面每一輪的問題、字與老師送出的解讀（由舊到新，最多 5 輪）。"""
    if not case.follow_of:
        return []
    from app.repositories import get_repo
    repo = get_repo()
    out: list[dict] = []
    token, seen = case.follow_of, set()
    while token and token not in seen and len(out) < 5:
        seen.add(token)
        prev = await repo.get_by_token(token)
        if not prev:
            break
        out.append({"question": prev.question, "char": prev.char, "reading": (prev.answer or "")[:600]})
        token = prev.follow_of
    out.reverse()
    return out or list(case.follow_chain)


async def _other_cases(case: Case, history: list[dict]) -> list[dict]:
    """登入的問事者：把他其他已解讀的舊案件（最近 5 筆）一併納入參考。追問鏈裡的不重複放。"""
    if not case.owner_email:
        return []
    from app.repositories import get_repo
    from app.templating import fmt_ms
    chain_tokens = set()
    t = case.follow_of
    repo = get_repo()
    while t and t not in chain_tokens and len(chain_tokens) < 10:
        chain_tokens.add(t)
        prev = await repo.get_by_token(t)
        t = prev.follow_of if prev else ""
    mine = [c for c in await repo.list_by_owner(case.owner_email)
            if c.id != case.id and c.token not in chain_tokens and c.status.value == "answered" and c.answer]
    mine.sort(key=lambda c: c.answered_at or 0, reverse=True)
    return [{"date": fmt_ms(c.answered_at)[:10], "question": c.question, "char": c.char,
             "reading": c.answer[:400]} for c in mine[:5]]


async def compose(case: Case, events: list[dict], char: str, use_ai: bool = True) -> dict:
    info = lookup(char)
    feats = analyze(events, info.total_strokes or None)
    history = await _history(case)
    others = await _other_cases(case, history)
    ai, ai_error = (await ai_draft.generate_ex(build_context(case, info, feats, history, others))) if use_ai else (None, "")
    sections = {
        "此字": _sec_char(info, feats, case),
        "五行": _sec_wuxing(info, ai),
        "古字說法": _sec_ancient(info, ai),
        "字義": _sec_meaning(info, ai),
    }
    from app.services.liuyao.derived import HEAD, reference_text
    ref = reference_text(case)
    if ref:   # 老師已「以此字起卦」：盤面事實放進解字資料（只有老師看得到），AI 有簡析就附在後面
        note = ai.get("gua_note") if ai else ""
        sections[HEAD] = ref + (f"\n簡析：{note}{AI_MARK}" if note else "")
    reading = _sec_ai(ai, "reading")
    if ref:   # 給問事者看的「梅花易數」段落接在解讀後面（沒有 AI 時只有起卦的交代，老師自己補白話說明）
        from app.services.liuyao.derived import public_block
        has_ai = bool(ai and ai.get("reading"))
        core = reading.removesuffix(AI_MARK) if has_ai else reading
        reading = core + "\n\n" + public_block(case, (ai.get("gua_plain") or "") if ai else "") + (AI_MARK if has_ai else "")
    sections["解讀"] = reading
    text = "\n\n".join(f"【{k}】\n{v}" for k, v in sections.items())
    return {"char": char, "sections": sections, "text": text, "ai_used": bool(ai), "ai_error": ai_error,
            "features": feats.__dict__}
