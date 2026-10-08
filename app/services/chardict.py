"""內建字庫：Unihan（部首、筆畫、讀音、繁簡）＋《說文解字》＋五行規則。

資料檔在 app/data/：
  unihan.tsv        Unicode Unihan Database 子集（Unicode License）
  radicals.json     康熙 214 部首與部首本字筆畫
  shuowen.json      說文解字（含段玉裁注節錄），來源 shuowen.org（Apache License 2.0）
  moedict.json      教育部《重編國語辭典修訂本》單字釋義（CC BY-ND 3.0 TW，須標示出處、不得改作）
  wuxing_rules.json 五行判定規則（老師可自行修改）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass
class UnihanRow:
    char: str
    radical: int
    residual: int
    total: int
    mandarin: str
    traditional: str
    simplified: str


@lru_cache
def _unihan() -> dict[str, UnihanRow]:
    out: dict[str, UnihanRow] = {}
    with open(DATA / "unihan.tsv", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 7:
                continue
            try:
                out[p[0]] = UnihanRow(p[0], int(p[1]), int(p[2]), int(p[3]), p[4], p[5], p[6])
            except ValueError:
                continue
    return out


@lru_cache
def _radicals() -> dict[int, dict]:
    raw = json.loads((DATA / "radicals.json").read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


@lru_cache
def _shuowen() -> dict:
    return json.loads((DATA / "shuowen.json").read_text(encoding="utf-8"))


@lru_cache
def _moedict() -> dict:
    return json.loads((DATA / "moedict.json").read_text(encoding="utf-8"))["chars"]


@lru_cache
def wuxing_rules() -> dict:
    return json.loads((DATA / "wuxing_rules.json").read_text(encoding="utf-8"))


@dataclass
class CharInfo:
    char: str
    found: bool = False
    radical_char: str = ""
    radical_no: int = 0
    total_strokes: int = 0
    kangxi_strokes: int = 0
    pinyin: str = ""
    zhuyin: str = ""
    traditional: str = ""
    simplified: str = ""
    wuxing_by_strokes: str = ""
    wuxing_by_radical: str = ""
    wuxing_override: str = ""
    shuowen: dict | None = None
    moe: dict | None = None              # 教育部辭典：{"h": [{"b": 注音, "p": 拼音, "defs": [...]}], "w": 常用詞}
    notes: list[str] = field(default_factory=list)


def kangxi_strokes(row: UnihanRow) -> int:
    """康熙筆畫：部首以本字計（氵算水 4 畫、艹算艸 6 畫、阝左算阜 8 畫…）。"""
    nums = wuxing_rules().get("numeral_strokes", {})
    if row.char in nums:
        return int(nums[row.char])
    if row.residual < 0:          # 例如「王」在玉部，餘筆 -1，直接用總筆畫
        return row.total
    rad = _radicals().get(row.radical)
    if not rad or not rad["strokes"]:
        return row.total
    return rad["strokes"] + row.residual


def lookup_shuowen(char: str, row: UnihanRow | None) -> dict | None:
    sw = _shuowen()
    candidates = [char]
    if row and row.traditional:
        candidates += list(row.traditional)
    for c in candidates:
        eid = sw["index"].get(c)
        if eid is not None:
            return sw["entries"][str(eid)]
    return None


def lookup(char: str) -> CharInfo:
    info = CharInfo(char=char)
    row = _unihan().get(char)
    rules = wuxing_rules()
    if row:
        info.found = True
        rad = _radicals().get(row.radical, {})
        info.radical_no = row.radical
        info.radical_char = rad.get("char", "")
        info.total_strokes = row.total
        # 簡化字以繁體計算康熙筆畫
        trad_row = _unihan().get(row.traditional) if len(row.traditional) == 1 else None
        info.kangxi_strokes = kangxi_strokes(trad_row or row)
        info.pinyin = row.mandarin
        info.zhuyin = ""
        info.traditional = row.traditional
        info.simplified = row.simplified
        if row.traditional and row.traditional != char:
            info.notes.append(f"此為簡化字，繁體作「{row.traditional}」，五行與康熙筆畫建議以繁體為準。")
        info.wuxing_by_strokes = rules["strokes_last_digit"].get(str(info.kangxi_strokes % 10), "")
        for element, rads in rules["radical"].items():
            if info.radical_char in rads:
                info.wuxing_by_radical = element
                break
    info.moe = _moedict().get(char) or (_moedict().get(row.traditional) if row and len(row.traditional) == 1 else None)
    if info.moe:
        info.zhuyin = "／".join(h["b"] for h in info.moe["h"] if h.get("b"))
    info.wuxing_override = rules.get("override", {}).get(char, "")
    info.shuowen = lookup_shuowen(char, row)
    return info
