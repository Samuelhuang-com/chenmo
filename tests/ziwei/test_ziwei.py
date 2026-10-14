import json
import random
from pathlib import Path

import pytest

from app.services.ziwei import build_chart
from app.services.ziwei.chart import (BRANCHES, JU_OF_ELEMENT, NAYIN, ZIWEI_SERIES, TIANFU_SERIES,
                                      ziwei_branch, ganzhi_index)

MAJOR_NAMES = {n for n, _ in ZIWEI_SERIES} | {n for n, _ in TIANFU_SERIES}
AUX_COUNT = 18


@pytest.mark.parametrize("ju", [2, 3, 4, 5, 6])
def test_ziwei_at_yin_when_day_equals_ju(ju):
    # 日數恰為局數（整除）時，紫微在寅
    assert ziwei_branch(ju, ju) == 2


def test_ziwei_known_starbooks_case_木三局_初一_在辰():
    # 1964/09/06（農曆甲辰年八月初一）木三局，starbooks 盤面紫微在辰
    assert ziwei_branch(1, 3) == 4


def test_ziwei_zigzag_stays_in_range():
    for ju in (2, 3, 4, 5, 6):
        for d in range(1, 31):
            assert 0 <= ziwei_branch(d, ju) < 12


def test_nayin_lookup_known_values():
    # 納音每兩個干支一組：甲子乙丑＝海中金、丙寅丁卯＝爐中火、戊辰己巳＝大林木、庚午辛未＝路旁土
    def nayin(stem, branch):
        return NAYIN[ganzhi_index(stem, branch) // 2]
    assert len(NAYIN) == 30
    assert nayin(0, 0) == "金"    # 甲子
    assert nayin(1, 1) == "金"    # 乙丑
    assert nayin(2, 2) == "火"    # 丙寅
    assert nayin(4, 4) == "木"    # 戊辰
    assert nayin(6, 6) == "土"    # 庚午


def test_year_ganzhi_and_no_leap_for_known_date():
    c = build_chart(1990, 1, 1, 12, 0, gender="男")
    assert c.year_gz == "己巳"                 # 農曆己巳年（1989）
    assert c.lunar == "1989年十二月初五"
    assert c.leap is False


@pytest.mark.parametrize("seed", range(40))
def test_random_charts_structure(seed):
    rnd = random.Random(seed)
    y = rnd.randint(1930, 2060)
    m, d = rnd.randint(1, 12), rnd.randint(1, 28)
    h, mi = rnd.randint(0, 23), rnd.randint(0, 59)
    g = rnd.choice(["男", "女"])
    c = build_chart(y, m, d, h, mi, gender=g)

    assert c.ju in {"水二局", "木三局", "金四局", "土五局", "火六局"}
    assert len(c.palaces) == 12
    assert [p.branch for p in c.palaces] == list(BRANCHES)

    names = [s.name for p in c.palaces for s in p.majors]
    assert sorted(names) == sorted(MAJOR_NAMES) and len(names) == 14

    aux = [s.name for p in c.palaces for s in p.aux]
    assert len(aux) == AUX_COUNT and len(set(aux)) == AUX_COUNT

    hua = [s.hua for p in c.palaces for s in p.majors + p.aux if s.hua]
    assert sorted(hua) == sorted(["祿", "權", "科", "忌"])

    assert sum(p.is_ming for p in c.palaces) == 1
    assert sum(p.is_shen for p in c.palaces) == 1
    ming = next(p for p in c.palaces if p.is_ming)
    assert ming.name == "命宮"
    assert c.ming_lord and c.shen_lord

    # 大限：12 段、連續 10 年、從命宮起算的第一段為局數
    decades = sorted((p.decade for p in c.palaces if p.decade), key=lambda t: t[0])
    assert len(decades) == 12
    assert decades[0][0] == {"水二局": 2, "木三局": 3, "金四局": 4, "土五局": 5, "火六局": 6}[c.ju]
    assert all(b[0] - a[0] == 10 for a, b in zip(decades, decades[1:]))
    assert ming.decade is not None and ming.decade[0] in {d[0] for d in decades}

    # 天府與紫微的關係：天府 = 4 − 紫微（對寅申軸）
    zw = next(p.index for p in c.palaces if any(s.name == "紫微" for s in p.majors))
    tf = next(p.index for p in c.palaces if any(s.name == "天府" for s in p.majors))
    assert tf == (4 - zw) % 12
    assert (zw == tf) == (zw in (2, 8))
    assert c.ziwei_branch == BRANCHES[zw]


def test_late_zi_option_changes_lunar_day_only_at_23():
    a = build_chart(1990, 1, 1, 23, 0)
    b = build_chart(1990, 1, 1, 23, 0, late_zi_next_day=True)
    assert a.lunar != b.lunar
    assert a.hour_name == b.hour_name == "子時"
    c = build_chart(1990, 1, 1, 22, 0, late_zi_next_day=True)
    assert c.lunar == a.lunar


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        build_chart(1990, 2, 30, 12)
    with pytest.raises(ValueError):
        build_chart(1990, 1, 1, 24)
    with pytest.raises(ValueError):
        build_chart(1990, 1, 1, 12, gender="其他")


GOLDEN = json.loads((Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.skipif(not GOLDEN, reason="尚未放入 starbooks 標準答案（golden_cases.json）")
@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c.get("name", "case"))
def test_golden(case):
    i = case["input"]
    c = build_chart(i["year"], i["month"], i["day"], i["hour"], i.get("minute", 0),
                    gender=i.get("gender", "男"), late_zi_next_day=i.get("late_zi_next_day", False))
    e = case["expect"]
    for key in ("lunar", "year_gz", "ju", "ming_gz", "ming_branch", "shen_branch", "ziwei_branch",
                "ming_lord", "shen_lord"):
        if key in e:
            assert getattr(c, key) == e[key], key
    if "bazi" in e:
        assert c.bazi == e["bazi"]
    for b, extra in e.get("palace_extra", {}).items():
        p = c.palaces[BRANCHES.index(b)]
        assert p.changsheng == extra["changsheng"], b
        assert p.boshi == extra["boshi"], b
    for b, stars in e.get("palace_stars", {}).items():
        p = c.palaces[BRANCHES.index(b)]
        assert sorted(s.name for s in p.majors) == sorted(stars), b


def test_xiaoxian_ages_cover_each_palace_in_cycle():
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    ages = sorted(a for p in c.palaces for a in p.xiaoxian)
    assert ages == list(range(1, 121))
    ming_bazi_palace = next(p for p in c.palaces if p.branch == "巳")
    assert ming_bazi_palace.xiaoxian[:2] == [8, 20]    # 截圖：命宮小限 8、20、32…


def test_liunian_ages_match_second_screenshot():
    # 丙午（寅午戌）流年一歲在午、順行：辰宮 11、23；巳宮 12、24
    c = build_chart(1966, 10, 10, 12, 0, gender="女")
    by = {p.branch: p for p in c.palaces}
    assert by["辰"].liunian[:2] == [11, 23]
    assert by["巳"].liunian[:2] == [12, 24]


def test_liunian_rows_helper():
    from app.services.ziwei.chart import liunian_rows
    rows = liunian_rows(1966, 2027, 2)
    assert rows[0] == {"year": 2027, "gz": "丁未", "age": 62}


def test_liunian_overlay_for_1964_chart_in_2026():
    from app.services.ziwei.chart import liunian_overlay
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    ov = liunian_overlay(c, 2026)            # 丙午
    assert ov["branch"] == "午" and ov["gz"] == "丙午"
    assert ov["names"][6] == "命宮"           # 流年命宮在午
    by = {p.index: p for p in c.palaces}
    # 丙干四化：天同祿、天機權、文昌科、廉貞忌
    assert "流祿" in ov["marks"][by[[b for b in range(12) if any(s.name == "天同" for s in by[b].majors)][0]].index]
    assert "流忌" in ov["marks"][[b for b in range(12) if any(s.name == "廉貞" for s in by[b].majors)][0]]


def test_liunian_hua_follows_year_stem():
    from app.services.ziwei.chart import liunian_overlay
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    ov = liunian_overlay(c, 2026)            # 丙干：天同祿、天機權、文昌科、廉貞忌
    got = {label: star for label, star, _ in ov["hua"]}
    assert got == {"祿": "天同", "權": "天機", "科": "文昌", "忌": "廉貞"}
    # 換成甲年（1964 年為甲辰，但流年 2024 為甲辰）應與本命相同，2025 乙巳則不同
    ov2 = liunian_overlay(c, 2025)           # 乙干：天機祿、天梁權、紫微科、太陰忌
    assert {label: star for label, star, _ in ov2["hua"]} == {"祿": "天機", "權": "天梁", "科": "紫微", "忌": "太陰"}


def test_liunian_overlay_age_and_current_decade():
    from app.services.ziwei.chart import liunian_overlay
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    ov = liunian_overlay(c, 2026)
    assert ov["age"] == 63                       # 2026 - 1964 + 1
    cur = [p for p in c.palaces if p.decade and p.decade[0] <= ov["age"] <= p.decade[1]]
    assert len(cur) == 1 and cur[0].decade == (63, 72)


def test_liunian_aux_stars_for_bingwu_year():
    from app.services.ziwei.chart import liunian_overlay
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    ov = liunian_overlay(c, 2026)            # 丙午：流魁亥、流鉞酉、流昌申、流羊午、流陀辰、流馬申
    got = {name: br for name, br in ov["aux_list"]}
    assert got == {"流魁": "亥", "流鉞": "酉", "流昌": "申", "流羊": "午", "流陀": "辰", "流馬": "申"}


def test_facts_text_contains_flow_structure_without_inference():
    from app.services.ziwei.ai import facts_text
    c = build_chart(1964, 9, 6, 8, 0, gender="男")
    txt = facts_text(c, 2026)
    assert "流年：2026年 丙午（虛歲 63）" in txt
    assert "流年命宮：流年地支午，即本命" in txt
    assert txt.count("\n流") >= 12                      # 十二宮逐列
    assert "流命宮" in txt and "※" not in txt            # 事實文字不含 AI 結語


def test_interpret_without_key_returns_message():
    import asyncio
    from app.services.ziwei.ai import interpret
    text, msg = asyncio.run(interpret("x"))
    assert text is None and "ANTHROPIC_API_KEY" in msg
