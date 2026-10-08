"""自選字：學生不知道要寫什麼字時，從字池隨機抽字讓他選。"""
from __future__ import annotations

import random
from functools import lru_cache
from pathlib import Path

POOL_FILE = Path(__file__).resolve().parent.parent / "data" / "pick_pool.txt"
_rng = random.SystemRandom()


@lru_cache
def pool() -> tuple[str, ...]:
    out: list[str] = []
    for line in POOL_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for ch in line:
            if not ch.isspace() and ch not in out:
                out.append(ch)
    return tuple(out)


def random_set(n: int = 20) -> list[str]:
    p = pool()
    return _rng.sample(p, min(n, len(p)))


def valid_offer(offered: list[str], n: int = 20) -> bool:
    p = set(pool())
    return 0 < len(offered) <= n and len(set(offered)) == len(offered) and all(c in p for c in offered)
