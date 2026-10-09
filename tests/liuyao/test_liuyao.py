"""六爻排盤引擎：標準答案（golden）與規則測試。"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.liuyao import build_chart
from app.services.liuyao import hexagram as hx
from app.services.liuyao.calendar import to_ganzhi, xunkong

CASES = json.loads((Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["title"] for c in CASES])
def test_golden(case):
    c = build_chart(case["values"], datetime.fromisoformat(case["when"]))
    e = case["expect"]
    checks = {
        "ben": lambda: c.ben.name,
        "bian": lambda: c.bian.name if c.bian else None,
        "hu": lambda: c.hu.name,
        "palace": lambda: c.palace.palace,
        "stage": lambda: c.palace.stage,
        "shi": lambda: c.palace.shi,
        "ying": lambda: c.palace.ying,
        "najia": lambda: [ln.ganzhi for ln in c.lines],
        "liuqin": lambda: [ln.liuqin for ln in c.lines],
        "liushen": lambda: [ln.liushen for ln in c.lines],
        "gua_shen": lambda: c.gua_shen,
        "moving": lambda: c.moving_positions,
    }
    for key, get in checks.items():
        if key in e:
            assert get() == e[key], f"{case['title']}：{key}"
    if "time" in e:
        t = c.time.as_dict()
        for k, v in e["time"].items():
            assert t[k] == v, f"{case['title']}：time.{k}"
    for pos, (gz, q) in e.get("fu", {}).items():
        ln = c.lines[int(pos) - 1]
        assert (ln.fu_ganzhi, ln.fu_liuqin) == (gz, q), f"{case['title']}：伏神 {pos} 爻"
    for pos, (gz, q, rel) in e.get("change", {}).items():
        ln = c.lines[int(pos) - 1]
        assert (ln.change_ganzhi, ln.change_liuqin, ln.change_relation) == (gz, q, rel)


# 京房八宮（各宮依序：本宮、一世…五世、遊魂、歸魂）
EIGHT_PALACES = {
    "乾": "乾為天 天風姤 天山遯 天地否 風地觀 山地剝 火地晉 火天大有",
    "坎": "坎為水 水澤節 水雷屯 水火既濟 澤火革 雷火豐 地火明夷 地水師",
    "艮": "艮為山 山火賁 山天大畜 山澤損 火澤睽 天澤履 風澤中孚 風山漸",
    "震": "震為雷 雷地豫 雷水解 雷風恆 地風升 水風井 澤風大過 澤雷隨",
    "巽": "巽為風 風天小畜 風火家人 風雷益 天雷无妄 火雷噬嗑 山雷頤 山風蠱",
    "離": "離為火 火山旅 火風鼎 火水未濟 山水蒙 風水渙 天水訟 天火同人",
    "坤": "坤為地 地雷復 地澤臨 地天泰 雷天大壯 澤天夬 水天需 水地比",
    "兌": "兌為澤 澤水困 澤地萃 澤山咸 水山蹇 地山謙 雷山小過 雷澤歸妹",
}
STAGES = ["本宮", "一世", "二世", "三世", "四世", "五世", "遊魂", "歸魂"]
SHI = [6, 1, 2, 3, 4, 5, 4, 3]


@pytest.mark.parametrize("palace", list(EIGHT_PALACES))
def test_eight_palaces(palace):
    for k, name in enumerate(EIGHT_PALACES[palace].split()):
        info = hx.palace_of(hx.BY_NAME[name].bits)
        assert (info.palace, info.stage, info.shi) == (palace, STAGES[k], SHI[k]), name


def test_64_unique_names():
    names = {h.name for h in hx.BY_BITS.values()}
    assert len(names) == 64
    assert sum(len(v.split()) for v in EIGHT_PALACES.values()) == 64


def test_liushen_by_day_stem():
    # 甲乙青龍、丙丁朱雀、戊勾陳、己螣蛇、庚辛白虎、壬癸玄武，皆從初爻起
    from app.services.liuyao.chart import LIUSHEN_ORDER, LIUSHEN_START
    assert LIUSHEN_ORDER[LIUSHEN_START["甲"]] == "青龍"
    assert LIUSHEN_ORDER[LIUSHEN_START["戊"]] == "勾陳"
    assert LIUSHEN_ORDER[LIUSHEN_START["己"]] == "螣蛇"
    assert LIUSHEN_ORDER[LIUSHEN_START["庚"]] == "白虎"
    assert LIUSHEN_ORDER[LIUSHEN_START["壬"]] == "玄武"


def test_xunkong():
    assert xunkong("甲子") == ("戌", "亥")
    assert xunkong("癸酉") == ("戌", "亥")
    assert xunkong("甲戌") == ("申", "酉")
    assert xunkong("丙辰") == ("子", "丑")
    assert xunkong("癸亥") == ("子", "丑")


# 節氣日期：香港天文台 2026 年曆
JIE_2026 = [("01-05", "小寒"), ("02-04", "立春"), ("03-05", "驚蟄"), ("04-05", "清明"), ("05-05", "立夏"),
            ("06-05", "芒種"), ("07-07", "小暑"), ("08-07", "立秋"), ("09-07", "白露"), ("10-08", "寒露"),
            ("11-07", "立冬"), ("12-07", "大雪")]


@pytest.mark.parametrize("md,name", JIE_2026)
def test_jie_dates_2026(md, name):
    from datetime import timedelta
    before = to_ganzhi(datetime.fromisoformat(f"2026-{md}T00:00:00+08:00") - timedelta(days=1))
    after = to_ganzhi(datetime.fromisoformat(f"2026-{md}T23:59:00+08:00"))
    assert after.jie == name and before.jie != name


def test_ganzhi_dates():
    # 萬年曆核對：2026-10-08 乙卯日、2026-10-09 丙辰日、2000-01-01 戊午日
    assert to_ganzhi(datetime(2026, 10, 8, 12)).day == "乙卯"
    assert to_ganzhi(datetime(2026, 10, 9, 12)).day == "丙辰"
    assert to_ganzhi(datetime(2000, 1, 1, 12)).day == "戊午"
    g = to_ganzhi(datetime(2026, 10, 9, 19, 30))
    assert (g.year, g.month, g.hour) == ("丙午", "戊戌", "戊戌")


def test_year_changes_at_lichun_not_jan_1():
    assert to_ganzhi(datetime(2026, 2, 3, 12)).year == "乙巳"
    assert to_ganzhi(datetime(2026, 2, 3, 12)).month == "己丑"
    assert to_ganzhi(datetime(2026, 2, 4, 12)).year == "丙午"
    assert to_ganzhi(datetime(2026, 2, 4, 12)).month == "庚寅"


def test_zi_hour_day_change():
    late = datetime(2026, 10, 9, 23, 30)
    assert to_ganzhi(late, zi_new_day=True).day == "丁巳"
    assert to_ganzhi(late, zi_new_day=False).day == "丙辰"
    assert to_ganzhi(late).hour[1] == "子"


def test_rejects_bad_values():
    with pytest.raises(ValueError):
        build_chart([7, 7, 7, 7, 7], datetime(2026, 10, 9))
    with pytest.raises(ValueError):
        build_chart([7, 7, 7, 7, 7, 5], datetime(2026, 10, 9))


def test_every_hexagram_builds():
    for bits in hx.BY_BITS:
        c = build_chart([7 if b else 8 for b in bits], datetime(2026, 10, 9, 12))
        assert len(c.lines) == 6 and sum(ln.shi for ln in c.lines) == 1 and sum(ln.ying for ln in c.lines) == 1
        present = {ln.liuqin for ln in c.lines} | {ln.fu_liuqin for ln in c.lines if ln.fu_liuqin}
        assert present == {"父母", "兄弟", "子孫", "妻財", "官鬼"}


def test_change_relation_terms():
    from app.services.liuyao.chart import change_relation as c
    assert c("子", "丑") == "回頭剋・化合"
    assert c("寅", "卯") == "化進神" and c("卯", "寅") == "化退神"
    assert c("子", "午") == "反吟（化沖）" and c("午", "午") == "伏吟"
    assert c("子", "申") == "回頭生" and c("午", "丑") == "化洩" and c("卯", "辰") == "剋變爻"
