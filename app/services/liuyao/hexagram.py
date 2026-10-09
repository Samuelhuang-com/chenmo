"""64 卦、八宮、世應、互錯綜。"""
from __future__ import annotations

from dataclasses import dataclass

from .tables import (HEXAGRAMS, PALACE_ORDER, PALACE_SHI, PALACE_STAGE, TRIGRAM_BY_BITS,
                     TRIGRAM_ELEMENT, TRIGRAM_IMAGE, TRIGRAMS)

Bits = tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class Hexagram:
    number: int          # 文王序
    upper: str           # 上卦（外卦）
    lower: str           # 下卦（內卦）
    short: str           # 卦名，例「同人」
    bits: Bits           # 由下而上

    @property
    def name(self) -> str:
        """全名，例「天火同人」「乾為天」。"""
        if self.upper == self.lower:
            return f"{self.short}為{TRIGRAM_IMAGE[self.upper]}"
        return f"{TRIGRAM_IMAGE[self.upper]}{TRIGRAM_IMAGE[self.lower]}{self.short}"


def _bits(upper: str, lower: str) -> Bits:
    return TRIGRAMS[lower] + TRIGRAMS[upper]  # type: ignore[return-value]


BY_BITS: dict[Bits, Hexagram] = {}
BY_NAME: dict[str, Hexagram] = {}
for _n, _u, _l, _s in HEXAGRAMS:
    _h = Hexagram(_n, _u, _l, _s, _bits(_u, _l))
    BY_BITS[_h.bits] = _h
    BY_NAME[_h.name] = _h
    BY_NAME[_h.short] = _h
assert len(BY_BITS) == 64


def from_bits(bits) -> Hexagram:
    return BY_BITS[tuple(int(b) for b in bits)]  # type: ignore[index]


def trigrams_of(bits) -> tuple[str, str]:
    """（下卦, 上卦）"""
    return TRIGRAM_BY_BITS[tuple(bits[:3])], TRIGRAM_BY_BITS[tuple(bits[3:])]


# ---------------- 八宮（京房） ----------------
@dataclass(frozen=True)
class PalaceInfo:
    palace: str        # 宮名（八卦）
    element: str       # 宮五行
    stage: str         # 本宮、一世…遊魂、歸魂
    shi: int           # 世爻位置 1–6
    ying: int          # 應爻位置 1–6


def _build_palaces() -> dict[Bits, PalaceInfo]:
    out: dict[Bits, PalaceInfo] = {}
    for p in PALACE_ORDER:
        base = list(TRIGRAMS[p] * 2)
        seq = [tuple(base)]
        cur = base[:]
        for i in range(5):              # 一世到五世：由初爻起逐爻變
            cur[i] ^= 1
            seq.append(tuple(cur))
        you = cur[:]                    # 遊魂：五世卦的四爻再變回來
        you[3] ^= 1
        seq.append(tuple(you))
        gui = list(TRIGRAMS[p]) + you[3:]   # 歸魂：遊魂卦的內卦還原為本宮卦
        seq.append(tuple(gui))
        for k, b in enumerate(seq):
            shi = PALACE_SHI[k]
            out[b] = PalaceInfo(p, TRIGRAM_ELEMENT[p], PALACE_STAGE[k], shi, (shi + 2) % 6 + 1)  # type: ignore[index]
    assert len(out) == 64
    return out


PALACES = _build_palaces()


def palace_of(bits) -> PalaceInfo:
    return PALACES[tuple(bits)]  # type: ignore[index]


def palace_head(palace: str) -> Bits:
    """本宮首卦（八純卦）。"""
    return _bits(palace, palace)


# ---------------- 互、錯、綜 ----------------
def hu(bits) -> Bits:
    """互卦：二三四爻為下卦，三四五爻為上卦。"""
    return tuple(bits[1:4]) + tuple(bits[2:5])  # type: ignore[return-value]


def cuo(bits) -> Bits:
    """錯卦：六爻陰陽全反。"""
    return tuple(1 - b for b in bits)  # type: ignore[return-value]


def zong(bits) -> Bits:
    """綜卦：上下顛倒。"""
    return tuple(reversed(bits))  # type: ignore[return-value]
