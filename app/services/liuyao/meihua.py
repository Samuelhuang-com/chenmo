"""梅花易數「物數起卦」：用字的康熙筆畫數加時辰起卦（以字起卦用）。

上卦 = 筆畫數 ÷ 8 的餘數；下卦 = (筆畫數 + 時辰數) ÷ 8 的餘數；動爻 = (筆畫數 + 時辰數) ÷ 6 的餘數；
餘數 0 取 8（或 6）。先天八卦數：乾1 兌2 離3 震4 巽5 坎6 艮7 坤8；時辰數：子1…亥12。
"""
from __future__ import annotations

from datetime import datetime

from .calendar import TPE
from .tables import BRANCHES, TRIGRAMS

XIANTIAN = ["乾", "兌", "離", "震", "巽", "坎", "艮", "坤"]


def hour_number(when: datetime) -> int:
    local = when.astimezone(TPE) if when.tzinfo else when
    return ((local.hour + 1) // 2) % 12 + 1


def values_from_strokes(strokes: int, when: datetime) -> tuple[list[int], dict]:
    """回傳（六爻值 初→上, 計算說明）。"""
    if strokes <= 0:
        raise ValueError("筆畫數必須大於 0")
    h = hour_number(when)
    upper = XIANTIAN[(strokes % 8 or 8) - 1]
    lower = XIANTIAN[((strokes + h) % 8 or 8) - 1]
    moving = (strokes + h) % 6 or 6
    bits = list(TRIGRAMS[lower] + TRIGRAMS[upper])
    values = [(9 if b else 6) if i + 1 == moving else (7 if b else 8) for i, b in enumerate(bits)]
    info = {"strokes": strokes, "hour": f"{BRANCHES[h - 1]}時（{h}）", "upper": upper, "lower": lower,
            "moving": moving,
            "formula": f"上卦 {strokes}÷8 餘 {strokes % 8 or 8} 為{upper}；"
                       f"下卦 ({strokes}+{h})÷8 餘 {(strokes + h) % 8 or 8} 為{lower}；"
                       f"動爻 ({strokes}+{h})÷6 餘 {moving}"}
    return values, info
