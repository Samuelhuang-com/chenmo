"""干支曆：年（以立春換年）、月（以「節」換月）、日、時、旬空。

不依賴外部套件。太陽視黃經用 Meeus《Astronomical Algorithms》第 25 章的低精度公式，
誤差約 0.01°（約 15 分鐘）。起卦時間若落在交節前後 1 小時內，會標記 near_jie 提醒老師核對。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .tables import BRANCHES, STEMS

TPE = timezone(timedelta(hours=8))

# 十二「節」的太陽黃經與名稱；月支依序為寅卯辰…丑
JIE = [(315, "立春"), (345, "驚蟄"), (15, "清明"), (45, "立夏"), (75, "芒種"), (105, "小暑"),
       (135, "立秋"), (165, "白露"), (195, "寒露"), (225, "立冬"), (255, "大雪"), (285, "小寒")]
MONTH_BRANCHES = "寅卯辰巳午未申酉戌亥子丑"

# 五虎遁（年干→寅月月干）、五鼠遁（日干→子時時干）
_TIGER = {"甲": "丙", "己": "丙", "乙": "戊", "庚": "戊", "丙": "庚", "辛": "庚", "丁": "壬", "壬": "壬", "戊": "甲", "癸": "甲"}
_RAT = {"甲": "甲", "己": "甲", "乙": "丙", "庚": "丙", "丙": "戊", "辛": "戊", "丁": "庚", "壬": "庚", "戊": "壬", "癸": "壬"}

NEAR_JIE_DEGREES = 0.042   # 約 1 小時的太陽移動量


def ganzhi(index: int) -> str:
    return STEMS[index % 10] + BRANCHES[index % 12]


def ganzhi_index(gz: str) -> int:
    s, b = STEMS.index(gz[0]), BRANCHES.index(gz[1])
    return next(i for i in range(60) if i % 10 == s and i % 12 == b)


def _julian_day(dt_utc: datetime) -> float:
    y, m = dt_utc.year, dt_utc.month
    d = dt_utc.day + (dt_utc.hour + (dt_utc.minute + dt_utc.second / 60) / 60) / 24
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def sun_longitude(dt: datetime) -> float:
    """太陽視黃經（度，0–360）。dt 需帶時區。"""
    jde = _julian_day(dt.astimezone(timezone.utc)) + 69.0 / 86400   # TT ≈ UT + 69 秒
    t = (jde - 2451545.0) / 36525
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m) + 0.000289 * math.sin(3 * m))
    omega = math.radians(125.04 - 1934.136 * t)
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360


def _day_index(d: date) -> int:
    """日干支序（0 = 甲子）。2000-01-01 為戊午日。"""
    return (d.toordinal() - date(2000, 1, 1).toordinal() + 54) % 60


@dataclass(frozen=True)
class GanzhiTime:
    when: datetime         # 起卦時間（台北時間）
    year: str
    month: str
    day: str
    hour: str
    jie: str               # 目前所在的「節」（月令起點）
    xunkong: tuple[str, str]   # 日旬空的兩個地支
    near_jie: bool         # 是否在交節前後約 1 小時內

    @property
    def month_branch(self) -> str:
        return self.month[1]

    @property
    def day_stem(self) -> str:
        return self.day[0]

    @property
    def day_branch(self) -> str:
        return self.day[1]

    def as_dict(self) -> dict:
        return {"when": self.when.strftime("%Y-%m-%d %H:%M"), "year": self.year, "month": self.month,
                "day": self.day, "hour": self.hour, "jie": self.jie, "xunkong": "".join(self.xunkong),
                "near_jie": self.near_jie}


def xunkong(day_gz: str) -> tuple[str, str]:
    i = ganzhi_index(day_gz)
    start = i - i % 10                       # 旬首（甲日）
    return BRANCHES[(start + 10) % 12], BRANCHES[(start + 11) % 12]


def to_ganzhi(when: datetime, zi_new_day: bool = True) -> GanzhiTime:
    """zi_new_day=True：23:00 起算隔日（子初換日）；False：00:00 換日。"""
    if when.tzinfo is None:
        when = when.replace(tzinfo=TPE)
    local = when.astimezone(TPE)
    lam = sun_longitude(local)

    # 月：從立春（315°）起每 30° 一個月
    k = int(((lam - 315) % 360) // 30)
    month_branch = MONTH_BRANCHES[k]
    jie = JIE[k][1]
    edge = (lam - 315) % 30
    near = edge < NEAR_JIE_DEGREES or edge > 30 - NEAR_JIE_DEGREES

    # 年：立春前算前一年（k=10 子月、k=11 丑月且在 1、2 月，屬前一年）
    y = local.year
    if local.month <= 2 and k >= 10:
        y -= 1
    year_gz = ganzhi(y - 4)

    month_stem_start = STEMS.index(_TIGER[year_gz[0]])
    month_gz = STEMS[(month_stem_start + k) % 10] + month_branch

    d = local.date()
    if zi_new_day and local.hour == 23:
        d = d + timedelta(days=1)
    day_gz = ganzhi(_day_index(d))

    hb = ((local.hour + 1) // 2) % 12
    hour_gz = STEMS[(STEMS.index(_RAT[day_gz[0]]) + hb) % 10] + BRANCHES[hb]

    return GanzhiTime(local, year_gz, month_gz, day_gz, hour_gz, jie, xunkong(day_gz), near)
