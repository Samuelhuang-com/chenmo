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
