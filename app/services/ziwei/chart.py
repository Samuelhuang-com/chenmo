"""紫微斗數排盤引擎：純規則、不連網。農曆換算使用 lunar-python，其餘為安星規則。

安星內容：命宮／身宮、五行局、紫微與天府定位、十四正曜、常用輔星、生年四化、大限。

慣例（通行排法；若與 starbooks 結果不同，請記下出生資料對照，見 tests/ziwei/golden_cases.json）：
- 年干支以農曆年（正月初一換年）計；命宮、五行局、紫微定位皆以農曆月日時計。
- 閏月以所閏之月數安星（閏二月即按二月）。
- 23:00 預設仍屬當日子時；late_zi_next_day=True 時 23:00 改以隔日計日。
- 大限：陽男陰女順行（地支順序），陰男陽女逆行；第一個大限在命宮，起始歲數為五行局數。
- 星曜不含廟旺、亮度與斷語；斷語由老師判斷。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from lunar_python import Solar

BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
STEMS = "甲乙丙丁戊己庚辛壬癸"
MONTH_CN = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
DAY_CN = ["", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
          "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
          "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
PALACE_NAMES = ["命宮", "兄弟", "夫妻", "子女", "財帛", "疾厄", "遷移", "交友", "官祿", "田宅", "福德", "父母"]

# 紫微星系：以紫微為基準的位移（逆行）；天府星系：以天府為基準的位移（順行）
ZIWEI_SERIES = [("紫微", 0), ("天機", -1), ("太陽", -3), ("武曲", -4), ("天同", -5), ("廉貞", -8)]
TIANFU_SERIES = [("天府", 0), ("太陰", 1), ("貪狼", 2), ("巨門", 3), ("天相", 4),
                 ("天梁", 5), ("七殺", 6), ("破軍", 10)]

# 六十甲子納音：每兩個干支一組（甲子、乙丑同為海中金）
NAYIN = "金火木土金火水土金木水土火木水" * 2
JU_OF_ELEMENT = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}
JU_NAME = {2: "水二局", 3: "木三局", 4: "金四局", 5: "土五局", 6: "火六局"}

# 生年四化（祿、權、科、忌），依年干
SIHUA = {
    0: ("廉貞", "破軍", "武曲", "太陽"),
    1: ("天機", "天梁", "紫微", "太陰"),
    2: ("天同", "天機", "文昌", "廉貞"),
    3: ("太陰", "天同", "天機", "巨門"),
    4: ("貪狼", "太陰", "右弼", "天機"),
    5: ("武曲", "貪狼", "天梁", "文曲"),
    6: ("太陽", "武曲", "太陰", "天同"),
    7: ("巨門", "太陽", "文曲", "文昌"),
    8: ("天梁", "紫微", "左輔", "武曲"),
    9: ("破軍", "巨門", "太陰", "貪狼"),
}
HUA_LABELS = ("祿", "權", "科", "忌")

# 以下輔星表：key 為干或支所在的組
KUI_YUE = {(0, 4, 6): (1, 7), (1, 5): (0, 8), (2, 3): (11, 9), (8, 9): (3, 5), (7,): (6, 2)}  # 天魁、天鉞（依年干）
LU_CUN = {(0,): 2, (1,): 3, (2, 4): 5, (3, 5): 6, (6,): 8, (7,): 9, (8,): 11, (9,): 0}                       # 祿存（依年干）
TIAN_MA = {(2, 6, 10): 8, (8, 0, 4): 2, (11, 3, 7): 5, (5, 9, 1): 11}                         # 天馬（依年支）
HUO_XING = {(2, 6, 10): 1, (8, 0, 4): 2, (11, 3, 7): 3, (5, 9, 1): 9}                         # 火星起點（依年支，子時起算）
LING_XING = {(2, 6, 10): 3, (8, 0, 4): 10, (11, 3, 7): 10, (5, 9, 1): 10}                     # 鈴星起點（依年支）

MING_LORD = ["貪狼", "巨門", "祿存", "文曲", "廉貞", "武曲", "破軍", "武曲", "廉貞", "文曲", "祿存", "巨門"]
SHEN_LORD_BY_YEAR = ["火星", "天相", "天梁", "天同", "文昌", "天機", "火星", "天相", "天梁", "天同", "文昌", "天機"]   # 身主依生年地支

# 4×4 盤面位置（子=0 … 亥=11），中間四格為資訊區
CHANGSHENG_NAMES = ["長生", "沐浴", "冠帶", "臨官", "帝旺", "衰", "病", "死", "墓", "絕", "胎", "養"]
CHANGSHENG_START = {2: 8, 3: 11, 4: 5, 5: 8, 6: 2}            # 依五行局：水二申、木三亥、金四巳、土五申、火六寅
BOSHI_NAMES = ["博士", "力士", "青龍", "小耗", "將軍", "奏書", "飛廉", "喜神", "病符", "大耗", "伏兵", "官府"]
BOSHI_START = {(8, 0, 4): 2, (5, 9, 1): 8, (2, 6, 10): 4, (11, 3, 7): 11}   # 依生年地支
LIUNIAN_START = {(2, 6, 10): 6, (8, 0, 4): 0, (11, 3, 7): 3, (5, 9, 1): 9}   # 流年一歲所在宮，依生年地支
XIAOXIAN_START = {(2, 6, 10): 4, (8, 0, 4): 10, (11, 3, 7): 7, (5, 9, 1): 1}  # 小限第一歲所在宮，依生年地支

GRID = {5: (1, 1), 6: (1, 2), 7: (1, 3), 8: (1, 4), 9: (2, 4), 10: (3, 4), 11: (4, 4),
        0: (4, 3), 1: (4, 2), 2: (4, 1), 3: (3, 1), 4: (2, 1)}


@dataclass
class Star:
    name: str
    hua: str = ""          # 祿／權／科／忌

    @property
    def label(self) -> str:
        return f"{self.name}化{self.hua}" if self.hua else self.name


@dataclass
class Palace:
    index: int             # 地支序，子=0
    branch: str
    stem: str
    name: str              # 十二宮名稱（以命宮為起點逆排）
    grid: tuple[int, int]
    majors: list[Star] = field(default_factory=list)
    aux: list[Star] = field(default_factory=list)
    decade: tuple[int, int] | None = None   # 大限歲數範圍（虛歲）
    is_ming: bool = False
    is_shen: bool = False
    changsheng: str = ""                                  # 長生十二神
    boshi: str = ""                                       # 博士十二神
    xiaoxian: list[int] = field(default_factory=list)     # 小限歲數（虛歲）
    liunian: list[int] = field(default_factory=list)      # 流年歲數（虛歲，順行）


@dataclass
class Chart:
    solar: str
    lunar: str
    year_gz: str
    hour_name: str
    gender: str
    leap: bool
    ming_gz: str
    element: str
    ju: str
    ming_branch: str
    shen_branch: str
    ziwei_branch: str
    direction: str
    ming_lord: str
    shen_lord: str
    bazi: str
    bazi_jieqi: str
    birth_lunar_year: int
    yinyang: str               # 陽男／陰女…（依生年干）
    palaces: list[Palace]


def ganzhi_index(stem: int, branch: int) -> int:
    """干支序（甲子=0）。"""
    return next(i for i in range(60) if i % 10 == stem and i % 12 == branch)


def ziwei_branch(day: int, ju: int) -> int:
    """紫微所在地支（子=0）。寅為第一位：以局數除農曆日，商數（1 起算）自寅順數；
    除不盡時，再依補數（局數減餘數）順數（補數為偶）或逆數（補數為奇）。"""
    k = -(-day // ju)                 # 向上取整的商（1 起算）
    base = 2 + (k - 1)
    r = day % ju
    if r:
        c = ju - r
        base += c if c % 2 == 0 else -c
    return base % 12


def _lookup(table: dict, key: int) -> int | tuple:
    for group, value in table.items():
        if key in group:
            return value
    raise KeyError(key)


def build_chart(year: int, month: int, day: int, hour: int, minute: int = 0,
                gender: str = "男", late_zi_next_day: bool = False) -> Chart:
    if gender not in ("男", "女"):
        raise ValueError("性別請選男或女")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("時間不正確")
    base = datetime(year, month, day, hour, minute)   # 日期不合法會丟 ValueError
    if late_zi_next_day and hour == 23:
        base += timedelta(days=1)

    lun = Solar.fromYmdHms(base.year, base.month, base.day, hour, minute, 0).getLunar()
    ly, ld = lun.getYear(), lun.getDay()
    raw_month = lun.getMonth()
    leap, lm = raw_month < 0, abs(raw_month)

    ys, yb = (ly - 4) % 10, (ly - 4) % 12        # 農曆年干支
    hb = ((hour + 1) // 2) % 12                  # 時辰：子=0（23:00–00:59 為子）
    start = (2 * (ys % 5) + 2) % 10              # 五虎遁：寅月天干

    def stem_at(b: int) -> int:
        return (start + (b - 2) % 12) % 10

    ming = (2 + (lm - 1) - hb) % 12              # 命宮：寅起正月，順數月、逆數時
    shen = (2 + (lm - 1) + hb) % 12              # 身宮：寅起正月，順數月、順數時
    element = NAYIN[ganzhi_index(stem_at(ming), ming) // 2]
    ju = JU_OF_ELEMENT[element]
    zw = ziwei_branch(ld, ju)
    tf = (4 - zw) % 12                           # 天府與紫微對寅申軸相對

    palaces = [Palace(index=b, branch=BRANCHES[b], stem=STEMS[stem_at(b)],
                      name=PALACE_NAMES[(ming - b) % 12], grid=GRID[b],
                      is_ming=(b == ming), is_shen=(b == shen)) for b in range(12)]

    def put(b: int, name: str, major: bool = False) -> None:
        (palaces[b % 12].majors if major else palaces[b % 12].aux).append(Star(name))

    for name, off in ZIWEI_SERIES:
        put(zw + off, name, major=True)
    for name, off in TIANFU_SERIES:
        put(tf + off, name, major=True)

    lu = _lookup(LU_CUN, ys)
    kui, yue = _lookup(KUI_YUE, ys)
    aux = {
        "左輔": 4 + (lm - 1), "右弼": 10 - (lm - 1),
        "文昌": 10 - hb, "文曲": 4 + hb,
        "天魁": kui, "天鉞": yue,
        "祿存": lu, "擎羊": lu + 1, "陀羅": lu - 1,
        "天馬": _lookup(TIAN_MA, yb),
        "火星": _lookup(HUO_XING, yb) + hb, "鈴星": _lookup(LING_XING, yb) + hb,
        "地空": 11 - hb, "地劫": 11 + hb,
        "紅鸞": 3 - yb, "天喜": 3 - yb + 6,
        "龍池": 4 + yb, "鳳閣": 10 - yb,
    }
    for name, b in aux.items():
        put(b, name)

    for label, name in zip(HUA_LABELS, SIHUA[ys]):
        hits = [s for p in palaces for s in p.majors + p.aux if s.name == name]
        if len(hits) != 1:
            raise RuntimeError(f"四化星定位異常：{name}")
        hits[0].hua = label

    male = gender == "男"
    forward = (ys % 2 == 0) == male              # 陽男陰女順行，陰男陽女逆行
    for k in range(12):
        b = (ming + k) % 12 if forward else (ming - k) % 12
        palaces[b].decade = (ju + 10 * k, ju + 10 * k + 9)

    step = 1 if forward else -1
    for i in range(12):
        palaces[(CHANGSHENG_START[ju] + step * i) % 12].changsheng = CHANGSHENG_NAMES[i]
        palaces[(_lookup(BOSHI_START, yb) + step * i) % 12].boshi = BOSHI_NAMES[i]
    xx_start = _lookup(XIAOXIAN_START, yb)
    for age in range(1, 121):
        palaces[(xx_start + step * (age - 1)) % 12].xiaoxian.append(age)

    ls = _lookup(LIUNIAN_START, yb)
    for age in range(1, 121):
        palaces[(ls + (age - 1)) % 12].liunian.append(age)

    # 八字（以原始輸入的年月日時計，不受晚子選項影響）
    # 八字：年柱依農曆年；月柱依農曆月（正月為寅，與參考 App 一致，非節氣換月）；
    # 日柱取原始日期；時柱依日干五鼠遁。
    raw = Solar.fromYmdHms(year, month, day, hour, minute, 0).getLunar()
    day_gz = raw.getDayInGanZhi()
    day_stem = STEMS.index(day_gz[0])
    hour_gz = STEMS[(2 * (day_stem % 5) + hb) % 10] + BRANCHES[hb]
    month_gz = STEMS[(start + (lm - 1)) % 10] + BRANCHES[(2 + (lm - 1)) % 12]
    bazi = f"{STEMS[ys]}{BRANCHES[yb]} {month_gz} {day_gz} {hour_gz}"
    jq = raw.getEightChar()
    bazi_jieqi = f"{jq.getYear()} {jq.getMonth()} {jq.getDay()} {jq.getTime()}"

    return Chart(
        solar=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
        lunar=f"{ly}年{'閏' if leap else ''}{MONTH_CN[lm - 1]}月{DAY_CN[ld]}",
        year_gz=STEMS[ys] + BRANCHES[yb],
        hour_name=BRANCHES[hb] + "時",
        gender=gender,
        leap=leap,
        ming_gz=STEMS[stem_at(ming)] + BRANCHES[ming],
        element=element,
        ju=JU_NAME[ju],
        ming_branch=BRANCHES[ming],
        shen_branch=BRANCHES[shen],
        ziwei_branch=BRANCHES[zw],
        direction="順行" if forward else "逆行",
        ming_lord=MING_LORD[ming],
        shen_lord=SHEN_LORD_BY_YEAR[yb],
        bazi=bazi,
        bazi_jieqi=bazi_jieqi,
        birth_lunar_year=ly,
        yinyang=('陽' if ys % 2 == 0 else '陰') + gender,
        palaces=palaces,
    )


def liunian_rows(birth_lunar_year: int, start_year: int, n: int = 10) -> list[dict]:
    """下方流年列：年份、干支、虛歲（農曆生年起算）。"""
    return [{"year": y, "gz": STEMS[(y - 4) % 10] + BRANCHES[(y - 4) % 12],
             "age": y - birth_lunar_year + 1} for y in range(start_year, start_year + n)]


# 流昌：依流年天干（甲巳 乙午 丙申 丁酉 戊申 己酉 庚亥 辛子 壬寅 癸卯）
LIU_CHANG = {0: 5, 1: 6, 2: 8, 3: 9, 4: 8, 5: 9, 6: 11, 7: 0, 8: 2, 9: 3}


def liunian_overlay(chart: "Chart", year: int) -> dict:
    """流年疊加層（不改動本命盤）。

    流年命宮：該年地支所在宮位；流年宮名以流年命宮起逆排；
    流年四化：依該年天干套用生年四化表，標在本命盤上對應的星曜所在宮。
    """
    ys, yb = (year - 4) % 10, (year - 4) % 12
    names = [PALACE_NAMES[(yb - b) % 12] for b in range(12)]
    marks: dict[int, list[str]] = {b: [] for b in range(12)}
    hua: list[tuple[str, str, str]] = []           # (化名, 星名, 所在宮地支)
    for label, star in zip(HUA_LABELS, SIHUA[ys]):
        for pal in chart.palaces:
            if any(st.name == star for st in pal.majors + pal.aux):
                marks[pal.index].append(f"流{label}")
                hua.append((label, star, pal.branch))
    # 流年雜曜：流魁、流鉞（依流年天干）、流羊、流陀（依流年天干之祿存）、流馬（依流年地支）、流昌（依流年天干）
    kui, yue = _lookup(KUI_YUE, ys)
    lu = _lookup(LU_CUN, ys)
    aux = [("流魁", kui), ("流鉞", yue), ("流昌", LIU_CHANG[ys]),
           ("流羊", (lu + 1) % 12), ("流陀", (lu - 1) % 12), ("流馬", _lookup(TIAN_MA, yb))]
    aux_marks: dict[int, list[str]] = {b: [] for b in range(12)}
    aux_list: list[tuple[str, str]] = []
    for name, b in aux:
        aux_marks[b].append(name)
        aux_list.append((name, BRANCHES[b]))

    return {
        "year": year,
        "gz": STEMS[ys] + BRANCHES[yb],
        "branch": BRANCHES[yb],
        "ming": yb,
        "names": names,
        "marks": marks,
        "hua": hua,
        "stem": STEMS[ys],
        "age": year - chart.birth_lunar_year + 1,     # 虛歲
        "aux_marks": aux_marks,
        "aux_list": aux_list,
    }
