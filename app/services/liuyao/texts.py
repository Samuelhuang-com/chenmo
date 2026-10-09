"""《周易》經文查詢（卦辭、爻辭、彖傳）。資料在 app/data/zhouyi.json。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "zhouyi.json"


@lru_cache
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def source_note() -> str:
    return _data()["_source"]


def lookup(short: str) -> dict:
    return _data()["hexagrams"][short]


def for_chart(chart) -> dict:
    """依卦盤取出要看的經文：本卦卦辭、動爻爻辭（六爻全動的乾坤加用九／用六）、變卦卦辭。"""
    ben = lookup(chart.ben.short)
    moving = chart.moving_positions
    lines = [ben["yao"][p - 1] for p in moving]
    if len(moving) == 6 and ben.get("yong"):
        lines.append(ben["yong"])
    out = {"ben_name": chart.ben.name, "guaci": ben["guaci"], "tuan": ben["tuan"], "moving_lines": lines}
    if chart.bian:
        bian = lookup(chart.bian.short)
        out.update(bian_name=chart.bian.name, bian_guaci=bian["guaci"])
    return out
