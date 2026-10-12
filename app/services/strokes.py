"""筆畫資料的檢查與整理。"""
from __future__ import annotations


def clean_points(raw, max_points: int) -> list[list[float]]:
    """點座標格式 [x, y, dt, pressure?]，x/y 正規化 0–1，dt 為距本筆開始的毫秒。"""
    out: list[list[float]] = []
    if not isinstance(raw, list):
        return out
    for p in raw[:max_points]:
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            continue
        try:
            x = min(max(float(p[0]), 0.0), 1.0)
            y = min(max(float(p[1]), 0.0), 1.0)
            dt = max(int(p[2]), 0)
            pr = min(max(float(p[3]), 0.0), 1.0) if len(p) > 3 else 0.5
        except (TypeError, ValueError):
            continue
        out.append([round(x, 4), round(y, 4), dt, round(pr, 3)])
    return out


def visible_strokes(events: list[dict]) -> list[dict]:
    """依事件重建「目前畫面上看得到的筆畫」（套用 undo / clear）。"""
    strokes: list[dict] = []
    for ev in events:
        t = ev.get("type")
        if t == "stroke":
            strokes.append(ev)
        elif t == "undo" and strokes:
            strokes.pop()
        elif t == "clear":
            strokes = []
    return strokes


# ---------------- 雙字問心：兩個字格的事件存在同一個案件，用 pad 區分 ----------------
# 第一字的事件不帶 pad 欄位（與問字完全相同），第二字的事件帶 "pad": 1。
def pad_of(ev: dict) -> int:
    return 1 if ev.get("pad") == 1 else 0


def pad_events(events: list[dict], pad: int) -> list[dict]:
    """只取某一個字格的事件（undo / clear 也只作用在自己的字格）。"""
    return [ev for ev in events if pad_of(ev) == pad]


def visible_count(events: list[dict]) -> int:
    """畫面上看得到的總筆數；雙字問心的兩個字格分開計算 undo / clear 再相加。"""
    if not any(pad_of(ev) for ev in events):
        return len(visible_strokes(events))
    return len(visible_strokes(pad_events(events, 0))) + len(visible_strokes(pad_events(events, 1)))
