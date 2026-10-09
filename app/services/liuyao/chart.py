"""六爻排盤：輸入六個爻值（初爻→上爻，6/7/8/9）與起卦時間，輸出完整卦盤。

只標「事實」（旺衰、空破、回頭生剋），不下吉凶結論，判斷交給老師。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import hexagram as hx
from .calendar import GanzhiTime, to_ganzhi
from .tables import (BRANCH_ELEMENT, CLASH, GENERATES, LIUSHEN_ORDER, LIUSHEN_START, NAJIA,
                     OVERCOMES)

LIUQIN = ["父母", "兄弟", "子孫", "妻財", "官鬼"]

# 爻值：6 老陰（動）、7 少陽、8 少陰、9 老陽（動）
YAO_VALUES = {6: (0, True), 7: (1, False), 8: (0, False), 9: (1, True)}
YAO_NAMES = {6: "老陰", 7: "少陽", 8: "少陰", 9: "老陽"}
POSITION_NAMES = ["初", "二", "三", "四", "五", "上"]


def liuqin(palace_element: str, element: str) -> str:
    """以卦宮五行為「我」：同我兄弟、我生子孫、我剋妻財、剋我官鬼、生我父母。"""
    if element == palace_element:
        return "兄弟"
    if GENERATES[palace_element] == element:
        return "子孫"
    if OVERCOMES[palace_element] == element:
        return "妻財"
    if OVERCOMES[element] == palace_element:
        return "官鬼"
    return "父母"


def najia(bits) -> list[str]:
    """六爻納甲干支（初→上）。內卦取下卦的內三爻，外卦取上卦的外三爻。"""
    lower, upper = hx.trigrams_of(bits)
    return NAJIA[lower][0].split() + NAJIA[upper][1].split()


def wangshuai(element: str, month_element: str) -> str:
    """月令旺相休囚死。"""
    if element == month_element:
        return "旺"
    if GENERATES[month_element] == element:
        return "相"
    if GENERATES[element] == month_element:
        return "休"
    if OVERCOMES[element] == month_element:
        return "囚"
    return "死"


def relation(src: str, dst: str) -> str:
    """src 對 dst 的作用：生、剋、比和、洩（dst 生 src）、耗（dst 剋 src）。"""
    if src == dst:
        return "比和"
    if GENERATES[src] == dst:
        return "生"
    if OVERCOMES[src] == dst:
        return "剋"
    if GENERATES[dst] == src:
        return "洩"
    return "耗"


# 化進神／化退神（同五行地支前進或後退）
JIN = {"亥": "子", "寅": "卯", "巳": "午", "申": "酉", "丑": "辰", "辰": "未", "未": "戌", "戌": "丑"}
TUI = {v: k for k, v in JIN.items()}
# 地支六合
HE = {a: b for x, y in ["子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"] for a, b in ((x, y), (y, x))}


def change_relation(branch: str, change_branch: str) -> str:
    """動爻變出的爻對本爻的作用。"""
    if JIN.get(branch) == change_branch:
        return "化進神"
    if TUI.get(branch) == change_branch:
        return "化退神"
    if branch == change_branch:
        return "伏吟"
    if CLASH[branch] == change_branch:
        return "反吟（化沖）"
    r = relation(BRANCH_ELEMENT[change_branch], BRANCH_ELEMENT[branch])
    text = {"生": "回頭生", "剋": "回頭剋", "比和": "比和", "洩": "化洩", "耗": "剋變爻"}[r]
    if HE.get(branch) == change_branch:
        text += "・化合"
    return text


@dataclass
class Line:
    position: int            # 1–6
    value: int               # 6/7/8/9
    yang: bool
    moving: bool
    ganzhi: str              # 納甲干支，例「甲子」
    branch: str
    element: str
    liuqin: str
    liushen: str
    shi: bool = False
    ying: bool = False
    # 變爻（只有動爻才有）
    change_ganzhi: str = ""
    change_element: str = ""
    change_liuqin: str = ""
    change_relation: str = ""     # 回頭生、回頭剋、比和…（變爻對本爻）
    # 伏神（本卦缺的六親，伏在此爻下）
    fu_ganzhi: str = ""
    fu_liuqin: str = ""
    fu_element: str = ""
    # 旺衰標記
    month_state: str = ""         # 旺相休囚死
    marks: list[str] = field(default_factory=list)   # 月破、日沖、旬空、月建、日辰…

    @property
    def label(self) -> str:
        """爻題：初九、六二…上六。"""
        n, p = ("九" if self.yang else "六"), POSITION_NAMES[self.position - 1]
        return p + n if self.position in (1, 6) else n + p


@dataclass
class Chart:
    values: list[int]
    time: GanzhiTime
    ben: hx.Hexagram
    bian: hx.Hexagram | None
    hu: hx.Hexagram
    cuo: hx.Hexagram
    zong: hx.Hexagram
    palace: hx.PalaceInfo
    bian_palace: hx.PalaceInfo | None
    gua_shen: str                 # 卦身地支
    gua_shen_present: bool        # 卦身是否出現在卦中
    lines: list[Line]
    missing_liuqin: list[str]     # 本卦缺的六親（已帶出伏神）

    @property
    def moving_positions(self) -> list[int]:
        return [ln.position for ln in self.lines if ln.moving]

    def as_dict(self) -> dict:
        def hexd(h):
            return None if h is None else {"number": h.number, "name": h.name, "short": h.short,
                                            "upper": h.upper, "lower": h.lower}
        return {
            "values": self.values,
            "time": self.time.as_dict(),
            "ben": hexd(self.ben), "bian": hexd(self.bian), "hu": hexd(self.hu),
            "cuo": hexd(self.cuo), "zong": hexd(self.zong),
            "palace": asdict(self.palace),
            "bian_palace": asdict(self.bian_palace) if self.bian_palace else None,
            "gua_shen": self.gua_shen, "gua_shen_present": self.gua_shen_present,
            "missing_liuqin": self.missing_liuqin,
            "moving": self.moving_positions,
            "lines": [{**asdict(ln), "label": ln.label} for ln in self.lines],
        }


def gua_shen(shi: int, shi_yang: bool) -> str:
    """卦身：陽世從子起、陰世從午起，數到世爻的位置。"""
    start = 0 if shi_yang else 6
    return "子丑寅卯辰巳午未申酉戌亥"[(start + shi - 1) % 12]


def build_chart(values: list[int], when: datetime, zi_new_day: bool = True) -> Chart:
    if len(values) != 6 or any(v not in YAO_VALUES for v in values):
        raise ValueError("需要 6 個爻值（初爻到上爻），每個是 6、7、8、9 其中之一")
    t = to_ganzhi(when, zi_new_day)

    bits = [YAO_VALUES[v][0] for v in values]
    moving = [YAO_VALUES[v][1] for v in values]
    changed = [b ^ 1 if m else b for b, m in zip(bits, moving)]

    ben = hx.from_bits(bits)
    bian = hx.from_bits(changed) if any(moving) else None
    pal = hx.palace_of(bits)
    pel = pal.element

    gz = najia(bits)
    gz_bian = najia(changed)
    start = LIUSHEN_START[t.day_stem]
    month_el = BRANCH_ELEMENT[t.month_branch]
    day_el = BRANCH_ELEMENT[t.day_branch]

    lines: list[Line] = []
    for i in range(6):
        br = gz[i][1]
        el = BRANCH_ELEMENT[br]
        ln = Line(position=i + 1, value=values[i], yang=bool(bits[i]), moving=moving[i],
                  ganzhi=gz[i], branch=br, element=el, liuqin=liuqin(pel, el),
                  liushen=LIUSHEN_ORDER[(start + i) % 6],
                  shi=pal.shi == i + 1, ying=pal.ying == i + 1)
        if moving[i]:
            cb = gz_bian[i][1]
            ln.change_ganzhi = gz_bian[i]
            ln.change_element = BRANCH_ELEMENT[cb]
            ln.change_liuqin = liuqin(pel, ln.change_element)   # 變爻六親仍以本卦宮五行論
            ln.change_relation = change_relation(br, cb)
        # 旺衰標記（只標事實）
        ln.month_state = wangshuai(el, month_el)
        if br == t.month_branch:
            ln.marks.append("臨月建")
        elif CLASH[br] == t.month_branch:
            ln.marks.append("月破")
        if br == t.day_branch:
            ln.marks.append("臨日辰")
        elif CLASH[br] == t.day_branch:
            ln.marks.append("日沖")
        else:
            r = relation(day_el, el)
            if r in ("生", "剋"):
                ln.marks.append("日" + r)
        if br in t.xunkong:
            ln.marks.append("旬空")
        lines.append(ln)

    # 伏神：本卦缺的六親，從本宮首卦同位置帶出
    present = {ln.liuqin for ln in lines}
    missing = [q for q in LIUQIN if q not in present]
    if missing:
        head_gz = najia(hx.palace_head(pal.palace))
        for i, g in enumerate(head_gz):
            q = liuqin(pel, BRANCH_ELEMENT[g[1]])
            if q in missing and not lines[i].fu_liuqin:
                lines[i].fu_ganzhi, lines[i].fu_liuqin = g, q
                lines[i].fu_element = BRANCH_ELEMENT[g[1]]

    shen = gua_shen(pal.shi, bool(bits[pal.shi - 1]))
    return Chart(values=list(values), time=t, ben=ben, bian=bian,
                 hu=hx.from_bits(hx.hu(bits)), cuo=hx.from_bits(hx.cuo(bits)), zong=hx.from_bits(hx.zong(bits)),
                 palace=pal, bian_palace=hx.palace_of(changed) if bian else None,
                 gua_shen=shen, gua_shen_present=any(ln.branch == shen for ln in lines),
                 lines=lines, missing_liuqin=missing)
