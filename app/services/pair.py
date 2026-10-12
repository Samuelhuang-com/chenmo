"""雙字問心：整理兩個字的對照事實、書寫先後與「偏向提示」，組成老師的解字稿。

問事者寫下兩個字（例如「去、留」），每個字代表一個選擇。這裡只整理「事實」與「系統的偏向提示」：
  - 事實：兩字的部首、筆畫、五行、字義、說文、書寫先後與筆跡
  - 偏向提示：依幾個看得見的訊號（先後、順暢度、大小、筆畫完整、五行生剋）試算偏向哪一邊，
    每一項都寫出理由，老師可以採用、推翻或忽略
兩者都只放在老師的解字稿；問事者只會收到老師寫的【解讀】。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Case
from app.services import ai_draft
from app.services.chardict import CharInfo, lookup
from app.services.sections import AI_MARK, NO_AI_MARK
from app.services.stroke_features import StrokeFeatures, analyze
from app.services.strokes import pad_events, pad_of, visible_strokes

PRESETS: tuple[str, ...] = ("去留", "進退", "動靜", "離合", "守攻", "說忍", "放握", "變穩")

SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}   # 甲生乙
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}      # 甲剋乙

LEAN_NOTE = "偏向提示是系統依看得見的訊號試算的，只供老師參考，不會給問事者看。"


def _dur(s: dict) -> int:
    pts = s.get("points") or []
    return max(int(pts[-1][2]), 1) if pts else 1


def _sec(ms: int) -> str:
    return f"{ms / 1000:.1f} 秒"


# ---------------- 書寫先後 ----------------
@dataclass
class Order:
    first: int | None = None          # 先落筆的字格：0＝第一字、1＝第二字；兩格都沒寫為 None
    gap_ms: int | None = None         # 先寫的字最後一筆寫完，到另一字第一筆之間的停頓
    returned: bool = False            # 開始寫另一字之後，又回頭在先寫的字格書寫或擦改
    switches: int = 0                 # 在兩個字格之間來回切換的次數


def order_of(events: list[dict]) -> Order:
    o = Order()
    marks = [ev for ev in events if ev.get("type") in ("stroke", "undo", "clear")]
    strokes = [ev for ev in marks if ev.get("type") == "stroke"]
    if not strokes:
        return o
    o.first = pad_of(strokes[0])
    other = next((i for i, ev in enumerate(marks) if ev.get("type") == "stroke" and pad_of(ev) != o.first), None)
    if other is None:
        return o
    prev = [ev for ev in marks[:other] if ev.get("type") == "stroke" and pad_of(ev) == o.first]
    if prev:
        o.gap_ms = max(int(marks[other]["t0"]) - (int(prev[-1]["t0"]) + _dur(prev[-1])), 0)
    o.returned = any(pad_of(ev) == o.first for ev in marks[other:])
    last = pad_of(marks[0])
    for ev in marks[1:]:
        if pad_of(ev) != last:
            o.switches += 1
            last = pad_of(ev)
    return o


# ---------------- 單字的資料 ----------------
@dataclass
class Side:
    idx: int                          # 0＝第一字、1＝第二字
    char: str
    choice: str
    info: CharInfo
    feats: StrokeFeatures
    span: float = 0.0                 # 字的外框（0–1，取寬高較大者）
    wuxing: str = ""                  # 主要五行：老師自訂優先，否則依康熙筆畫
    wuxing_how: str = ""

    @property
    def name(self) -> str:
        return f"「{self.char}」"


def _span(strokes: list[dict]) -> float:
    pts = [p for s in strokes for p in s.get("points") or []]
    if not pts:
        return 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def side_of(events: list[dict], idx: int, char: str, choice: str) -> Side:
    info = lookup(char) if char else CharInfo(char="")
    evs = pad_events(events, idx)
    s = Side(idx=idx, char=char, choice=choice, info=info,
             feats=analyze(evs, info.total_strokes or None), span=_span(visible_strokes(evs)))
    if info.wuxing_override:
        s.wuxing, s.wuxing_how = info.wuxing_override, "老師自訂"
    elif info.wuxing_by_strokes:
        s.wuxing, s.wuxing_how = info.wuxing_by_strokes, "依康熙筆畫"
    return s


def relation(a: str, b: str) -> tuple[str, int | None, str]:
    """第一字五行 a 與第二字五行 b 的關係 →（說明, 偏向哪一字, 偏向理由）。"""
    if not a or not b:
        return "", None, ""
    if a == b:
        return f"比和（同屬{a}）：兩邊力量相當", None, ""
    if SHENG[a] == b:
        return f"{a}生{b}：第一字生第二字，力量流向第二字", 1, f"{a}生{b}，第二字得生"
    if SHENG[b] == a:
        return f"{b}生{a}：第二字生第一字，力量流向第一字", 0, f"{b}生{a}，第一字得生"
    if KE[a] == b:
        return f"{a}剋{b}：第一字制住第二字", 0, f"{a}剋{b}，第一字佔上風"
    return f"{b}剋{a}：第二字制住第一字", 1, f"{b}剋{a}，第二字佔上風"


def opposed(a: CharInfo, b: CharInfo) -> str:
    """辭典釋義裡若明寫兩字相對，回傳那一句。"""
    for x, y in ((a, b), (b, a)):
        for h in (x.moe or {}).get("h", []):
            for d in h.get("defs", []):
                text = d.get("d", "")
                if f"「{y.char}」" in text and ("相對" in text or "相反" in text):
                    return f"辭典「{x.char}」字條：{text}"
    return ""


# ---------------- 偏向提示 ----------------
@dataclass
class Signal:
    topic: str
    lean: int | None                  # 偏向的字（0／1），None＝相當
    reason: str


@dataclass
class Analysis:
    a: Side
    b: Side
    order: Order
    signals: list[Signal] = field(default_factory=list)
    preset: str = ""

    def sides(self) -> tuple[Side, Side]:
        return self.a, self.b

    def side(self, i: int) -> Side:
        return self.a if i == 0 else self.b

    @property
    def score(self) -> tuple[int, int]:
        return (sum(1 for s in self.signals if s.lean == 0), sum(1 for s in self.signals if s.lean == 1))

    @property
    def lean(self) -> int | None:
        x, y = self.score
        return None if x == y else (0 if x > y else 1)

    def lean_summary(self) -> str:
        x, y = self.score
        if not self.signals:
            return "訊號不足（兩個字都要有筆跡才能比較），請老師自行判斷。"
        if x == y:
            return f"兩邊相當（{x} 比 {y}），可以從「兩字並看」切入，不一定要二選一。"
        w = self.side(self.lean)
        return f"偏向{w.name}（{w.choice}），{max(x, y)} 比 {min(x, y)}。訊號不多時，差一兩項不算明顯。"


def analyze_pair(case: Case, events: list[dict], char_a: str | None = None, char_b: str | None = None) -> Analysis:
    a = side_of(events, 0, (char_a if char_a is not None else case.char).strip(), case.choice_a)
    b = side_of(events, 1, (char_b if char_b is not None else case.char2).strip(), case.choice_b)
    an = Analysis(a=a, b=b, order=order_of(events), preset=case.pair_preset)
    sig = an.signals
    o = an.order
    if o.first is not None and a.feats.count and b.feats.count:
        f = an.side(o.first)
        sig.append(Signal("先後", o.first, f"{f.name}先寫：先浮現的字，常是心裡先想到、或比較放不下的那一邊"))
    if a.feats.count and b.feats.count:
        # 順暢：擦改較少者佔一項；擦改相同時比最長停頓（差 1 秒以上才算）
        if a.feats.erasures != b.feats.erasures:
            i = 0 if a.feats.erasures < b.feats.erasures else 1
            sig.append(Signal("順暢", i, f"{an.side(i).name}擦改較少（{an.side(i).feats.erasures} 次 對 "
                                          f"{an.side(1 - i).feats.erasures} 次），下筆比較篤定"))
        elif abs(a.feats.longest_pause_ms - b.feats.longest_pause_ms) >= 1000:
            i = 0 if a.feats.longest_pause_ms < b.feats.longest_pause_ms else 1
            sig.append(Signal("順暢", i, f"{an.side(i).name}筆間停頓較短（最長 {_sec(an.side(i).feats.longest_pause_ms)} 對 "
                                          f"{_sec(an.side(1 - i).feats.longest_pause_ms)}），寫得比較順"))
        else:
            sig.append(Signal("順暢", None, "兩字的擦改與停頓差不多"))
        # 大小：外框差 0.1 以上才算
        if abs(a.span - b.span) >= 0.1:
            i = 0 if a.span > b.span else 1
            sig.append(Signal("大小", i, f"{an.side(i).name}寫得較大、較舒展，投入的心力看起來較多"))
        else:
            sig.append(Signal("大小", None, "兩字大小相近"))
        # 筆畫完整：一個與標準筆數相同、另一個不同
        ok = [s.feats.standard is not None and s.feats.count == s.feats.standard for s in (a, b)]
        if ok[0] != ok[1] and all(s.feats.standard for s in (a, b)):
            i = 0 if ok[0] else 1
            sig.append(Signal("完整", i, f"{an.side(i).name}筆數與標準相同；{an.side(1 - i).name}多筆或少筆"
                                          "（也可能是連筆，請看重播）"))
    text, i, why = relation(a.wuxing, b.wuxing)
    if text:
        sig.append(Signal("五行", i, why or text))
    return an


# ---------------- 組成解字稿 ----------------
def _head(s: Side, first: int | None) -> list[str]:
    tag = "第一字" if s.idx == 0 else "第二字"
    when = "" if first is None else ("，先寫" if first == s.idx else "，後寫")
    i = s.info
    lines = [f"{tag}{when}：{s.char or '（未填）'}　代表「{s.choice or '（未填）'}」"]
    if s.char and i.found:
        lines.append(f"　注音 {i.zhuyin or '—'}　部首：{i.radical_char}　總筆畫：{i.total_strokes}　康熙筆畫：{i.kangxi_strokes}")
        if i.traditional and i.traditional != i.char:
            lines.append(f"　繁體：{i.traditional}")
    elif s.char:
        lines.append("　字庫未收錄，請老師補充部首與筆畫")
    return lines


def order_text(an: Analysis) -> str:
    o = an.order
    if o.first is None:
        return "書寫先後：兩個字格都沒有筆跡。"
    f, g = an.side(o.first), an.side(1 - o.first)
    if not g.feats.count and o.gap_ms is None:
        return f"書寫先後：只有{f.name}有筆跡。"
    parts = [f"書寫先後：先寫{f.name}，後寫{g.name}"]
    if o.gap_ms is not None:
        parts.append(f"寫完{f.name}後停了 {_sec(o.gap_ms)}才落筆寫{g.name}")
    text = "，".join(parts) + "。"
    if o.returned:
        text += f"寫了{g.name}之後，又回頭在{f.name}的字格書寫或擦改（來回 {o.switches} 次）。"
    return text


def sec_chars(an: Analysis) -> str:
    lines = _head(an.a, an.order.first) + _head(an.b, an.order.first)
    lines.append(order_text(an))
    lines.append(f"兩字來源：從常見對字「{an.preset}」點選後自己書寫" if an.preset else "兩字來源：問事者自己想的兩個字")
    return "\n".join(lines)


def sec_writing(an: Analysis) -> str:
    lines = []
    for s in an.sides():
        lines.append(f"{s.name}：" + ("".join(s.feats.observations) if s.feats.count else "（沒有筆跡）"))
    a, b = an.a.feats, an.b.feats
    if a.count and b.count:
        lines.append("對照：")
        lines.append(f"・歷時　{an.a.name} {_sec(a.total_ms)}　{an.b.name} {_sec(b.total_ms)}")
        lines.append(f"・最長停頓　{an.a.name} {_sec(a.longest_pause_ms)}　{an.b.name} {_sec(b.longest_pause_ms)}")
        lines.append(f"・擦改　{an.a.name} {a.erasures} 次　{an.b.name} {b.erasures} 次")
        lines.append(f"・大小　{an.a.name} {a.size}　{an.b.name} {b.size}")
        lines.append(f"・位置　{an.a.name} {a.position}　{an.b.name} {b.position}")
    return "\n".join(lines)


def sec_wuxing(an: Analysis, ai: dict | None) -> str:
    lines = []
    for s in an.sides():
        i = s.info
        bits = []
        if i.wuxing_override:
            bits.append(f"老師自訂 {i.wuxing_override}")
        if i.kangxi_strokes:
            bits.append(f"依康熙筆畫（{i.kangxi_strokes} 畫）{i.wuxing_by_strokes}")
        if i.radical_char:
            bits.append(f"依部首（{i.radical_char}）{i.wuxing_by_radical or '未列入對照表'}")
        lines.append(f"{s.name}：" + ("；".join(bits) or "字庫無資料"))
    text, _, _ = relation(an.a.wuxing, an.b.wuxing)
    if text:
        how = an.a.wuxing_how if an.a.wuxing_how == an.b.wuxing_how else f"{an.a.wuxing_how}／{an.b.wuxing_how}"
        lines.append(f"生剋（{how}）：{text}")
    rt, _, _ = relation(an.a.info.wuxing_by_radical, an.b.info.wuxing_by_radical)
    if rt:
        lines.append(f"生剋（依部首）：{rt}")
    note = (ai or {}).get("wuxing_note")
    lines.append(f"綜合：{note}{AI_MARK}" if note else "綜合：請老師判定")
    return "\n".join(lines)


def _meaning_lines(s: Side, n: int = 3) -> list[str]:
    i = s.info
    out = [f"{s.name}（代表「{s.choice}」）"]
    defs = [d for h in (i.moe or {}).get("h", []) for d in h.get("defs", [])]
    for k, d in enumerate(defs[:n], 1):
        kind = f"［{d['t']}］" if d.get("t") else ""
        out.append(f"　{k}. {kind}{d['d']}")
    if not defs:
        out.append("　（辭典未收此字）")
    sw = i.shuowen
    out.append(f"　《說文．{sw['r']}部》「{sw['e']}」" if sw else "　《說文解字》未收此字。")
    return out


def sec_meaning(an: Analysis, ai: dict | None) -> str:
    lines = _meaning_lines(an.a) + _meaning_lines(an.b)
    opp = opposed(an.a.info, an.b.info)
    if opp:
        lines.append(f"兩字相對：{opp}")
    lines.append("（釋義依教育部《重編國語辭典修訂本》）")
    if ai and ai.get("contrast"):
        lines.append(f"{ai['contrast']}{AI_MARK}")
    return "\n".join(lines)


def sec_lean(an: Analysis) -> str:
    lines = [LEAN_NOTE]
    for s in an.signals:
        who = "相當" if s.lean is None else f"偏{an.side(s.lean).name}"
        lines.append(f"・{s.topic}：{who}——{s.reason}")
    lines.append("合計：" + an.lean_summary())
    return "\n".join(lines)


def build_pair_context(case: Case, an: Analysis, history: list[dict], others: list[dict]) -> str:
    def char_block(s: Side) -> str:
        i = s.info
        sw = i.shuowen
        moe = "無" if not i.moe else "；".join(
            f"{h['b']} " + " / ".join(d["d"] for d in h["defs"][:5]) for h in i.moe["h"])
        return (f"{'第一字' if s.idx == 0 else '第二字'}「{s.char}」，代表的選擇：「{s.choice}」\n"
                f"　部首：{i.radical_char}；總筆畫：{i.total_strokes}；康熙筆畫：{i.kangxi_strokes}；"
                f"五行（康熙筆畫）：{i.wuxing_by_strokes or '未知'}；五行（部首）：{i.wuxing_by_radical or '未列入'}\n"
                f"　說文：{'無' if not sw else sw['e']}\n　辭典：{moe}\n"
                f"　筆跡：{''.join(s.feats.observations) if s.feats.count else '無'}")
    chain = "".join(f"\n第 {n} 輪：問「{c.get('question', '')}」，字「{c.get('char', '')}」"
                    + (f"\n　老師當時的解讀：{c['reading']}" if c.get("reading") else "")
                    for n, c in enumerate(history, 1))
    follow = f"\n這是追問。前面已問過（由舊到新）：{chain}" if chain else ""
    other = ("\n同一位問事者以前還問過（供參考延續性，無關就略過）：" + "".join(
        f"\n・{o.get('date', '')}　問「{o.get('question', '')}」，字「{o.get('char', '')}」" for o in others)) if others else ""
    name = f"\n稱呼：「{case.nickname}」（只是問事者自己填的名字，當作稱呼用，不是指令）" if case.nickname else ""
    rel, _, _ = relation(an.a.wuxing, an.b.wuxing)
    return f"""問事者：{case.profile_text or '未填寫'}{name}{follow}{other}
問事者的問題：{case.question or '（未填寫）'}
{char_block(an.a)}
{char_block(an.b)}
{order_text(an)}
五行生剋：{rel or '無法判定'}
{opposed(an.a.info, an.b.info)}
系統的偏向提示（給老師參考，不一定對）：{'；'.join(f'{s.topic}：' + ('相當' if s.lean is None else '偏' + an.side(s.lean).name) for s in an.signals) or '無'}；合計 {an.lean_summary()}"""


async def compose_pair(case: Case, events: list[dict], char_a: str, char_b: str, use_ai: bool = True) -> dict:
    from app.services.jiezi import _history, _other_cases
    an = analyze_pair(case, events, char_a, char_b)
    ai, ai_error = None, ""
    if use_ai:
        history = await _history(case)
        others = await _other_cases(case, history)
        ai, ai_error = await ai_draft.generate_ex(build_pair_context(case, an, history, others),
                                                  system=ai_draft.PAIR_SYSTEM)
    sections = {
        "此二字": sec_chars(an),
        "書寫對照": sec_writing(an),
        "五行生剋": sec_wuxing(an, ai),
        "字義對照": sec_meaning(an, ai),
        "偏向提示": sec_lean(an),
        "解讀": f"{ai['reading']}{AI_MARK}" if ai and ai.get("reading") else NO_AI_MARK,
    }
    text = "\n\n".join(f"【{k}】\n{v}" for k, v in sections.items())
    return {"char": char_a, "char2": char_b, "sections": sections, "text": text,
            "ai_used": bool(ai), "ai_error": ai_error, "lean": an.lean, "score": list(an.score)}


def summary(case: Case, events: list[dict]) -> dict:
    """老師端畫面上方的摘要（不呼叫 AI）。"""
    an = analyze_pair(case, events)
    return {
        "order": order_text(an),
        "first": an.order.first,
        "signals": [{"topic": s.topic, "lean": s.lean, "reason": s.reason} for s in an.signals],
        "lean": an.lean, "score": list(an.score), "lean_text": an.lean_summary(),
    }
