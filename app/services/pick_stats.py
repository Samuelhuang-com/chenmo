"""自選字統計（老師端用）：只算數量，不碰問題內容、姓名或年次。

用來回答：多少人用自選字、有多少人會去選「方向」、哪些方向最常被選、選定前平均看了幾組，
以便決定下一批要替哪些方向補子題。
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from app.models import Case, CaseStatus, now_ms

DAY_MS = 86_400_000
PAGE = 500
CAP = 5000          # 每種狀態最多讀最近 5000 筆，避免資料很多時拖慢頁面


async def load_cases(repo) -> list[Case]:
    """讀出已呈送與已解的案件（書寫中的不算，還沒送出）。"""
    out: list[Case] = []
    for status in (CaseStatus.submitted, CaseStatus.answered):
        offset = 0
        while offset < CAP:
            rows = await repo.list_cases(limit=PAGE, status=status, offset=offset)
            out += rows
            if len(rows) < PAGE:
                break
            offset += PAGE
    return out


def _pct(n: int, d: int) -> int:
    return round(n * 100 / d) if d else 0


def summarize(cases: Iterable[Case], days: int | None = None, now: int | None = None) -> dict:
    """days：只算最近幾天（依呈送時間）；None＝全部。問爻案件不算。"""
    cs = [c for c in cases if c.kind != "yao" and c.status in (CaseStatus.submitted, CaseStatus.answered)]
    if days:
        cutoff = (now if now is not None else now_ms()) - days * DAY_MS
        cs = [c for c in cs if (c.submitted_at or c.created_at) >= cutoff]

    total = len(cs)
    picked = [c for c in cs if c.char_source == "picked"]
    themed = [c for c in picked if c.pick_theme]
    n_picked, n_themed = len(picked), len(themed)

    themes = Counter(c.pick_theme for c in themed)
    theme_rows = [{"name": k, "n": v, "pct": _pct(v, n_themed)} for k, v in themes.most_common()]

    rounds = [max(c.pick_rounds, 1) for c in picked]
    first_set = sum(1 for r in rounds if r == 1)
    top_chars = Counter(c.char for c in picked if c.char).most_common(10)

    return {
        "days": days,
        "total": total,
        "written": total - n_picked,
        "picked": n_picked,
        "picked_pct": _pct(n_picked, total),
        "random": n_picked - n_themed,
        "themed": n_themed,
        "themed_pct": _pct(n_themed, n_picked),      # 自選字裡，有去選方向的比例（決定要不要擴充字庫的關鍵數字）
        "themes": theme_rows,
        "avg_rounds": round(sum(rounds) / len(rounds), 1) if rounds else 0,
        "first_set_pct": _pct(first_set, n_picked),
        "top_chars": [{"char": c, "n": n} for c, n in top_chars],
    }
