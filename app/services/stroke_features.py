"""從書寫事件整理出「筆跡觀察」：筆數、停頓、擦除、字在格中的位置與大小。"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.strokes import visible_strokes


@dataclass
class StrokeFeatures:
    count: int = 0
    standard: int | None = None
    erasures: int = 0
    total_ms: int = 0
    longest_pause_ms: int = 0
    longest_pause_before: int = 0      # 第幾筆之前
    position: str = ""                 # 偏上、偏左下…
    size: str = ""                     # 偏小、適中、偏大、出格
    observations: list[str] = field(default_factory=list)


def _dur(s: dict) -> int:
    pts = s.get("points") or []
    return max(int(pts[-1][2]), 1) if pts else 1


def analyze(events: list[dict], standard_strokes: int | None = None) -> StrokeFeatures:
    f = StrokeFeatures(standard=standard_strokes)
    strokes = visible_strokes(events)
    f.count = len(strokes)
    f.erasures = sum(1 for e in events if e.get("type") in ("undo", "clear"))
    if not strokes:
        return f

    f.total_ms = strokes[-1]["t0"] + _dur(strokes[-1]) - strokes[0]["t0"]
    for i in range(1, len(strokes)):
        gap = strokes[i]["t0"] - (strokes[i - 1]["t0"] + _dur(strokes[i - 1]))
        if gap > f.longest_pause_ms:
            f.longest_pause_ms, f.longest_pause_before = gap, i + 1

    xs = [p[0] for s in strokes for p in s["points"]]
    ys = [p[1] for s in strokes for p in s["points"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    v = "偏上" if cy < 0.42 else "偏下" if cy > 0.58 else ""
    h = "偏左" if cx < 0.42 else "偏右" if cx > 0.58 else ""
    f.position = (v + h).replace("偏上偏", "偏上、偏").replace("偏下偏", "偏下、偏") or "居中"
    span = max(x1 - x0, y1 - y0)
    if x0 <= 0.01 or y0 <= 0.01 or x1 >= 0.99 or y1 >= 0.99:
        f.size = "觸及格線邊緣（出格）"
    elif span < 0.4:
        f.size = "偏小"
    elif span > 0.85:
        f.size = "偏大"
    else:
        f.size = "適中"

    obs = f.observations
    if standard_strokes:
        diff = f.count - standard_strokes
        if diff > 0:
            obs.append(f"共寫 {f.count} 筆，比標準 {standard_strokes} 筆多 {diff} 筆（也可能是連筆或斷筆）。")
        elif diff < 0:
            obs.append(f"共寫 {f.count} 筆，比標準 {standard_strokes} 筆少 {-diff} 筆（可能有連筆）。")
        else:
            obs.append(f"共寫 {f.count} 筆，與標準筆數相同。")
    else:
        obs.append(f"共寫 {f.count} 筆。")
    obs.append(f"書寫歷時約 {f.total_ms / 1000:.1f} 秒。")
    if f.longest_pause_ms >= 1500:
        obs.append(f"第 {f.longest_pause_before} 筆之前停頓最久，約 {f.longest_pause_ms / 1000:.1f} 秒。")
    if f.erasures:
        obs.append(f"書寫中復原或清除 {f.erasures} 次。")
    obs.append(f"字在格中{f.position}，大小{f.size}。")
    return f
