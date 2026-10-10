"""自選字：學生不知道要寫什麼字時，從字池隨機抽字讓他選。

兩種來源（互相獨立，主題字庫壞掉不影響原本的隨機抽字）：
- random_set()：原本的字池 pick_pool.txt 隨機抽 20 字（預設）。
- themed_set()：依「方向」從主題字庫抽一組彼此有關聯的 20 字（見 pick_bank.py），學生選填。
"""
from __future__ import annotations

import logging
import random
from functools import lru_cache
from pathlib import Path

from app.services import pick_bank

log = logging.getLogger("chenmo.pick")

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


# ---------------------------------------------------------------- 主題字庫（選填）
@lru_cache
def bank() -> pick_bank.CharacterBank | None:
    """載入主題字庫；失敗時記錄錯誤並回傳 None（自選字退回原本的隨機抽字）。"""
    try:
        return pick_bank.CharacterBank.load()
    except pick_bank.BankError as e:
        log.error("主題字庫載入失敗，自選字改用隨機字池：%s", e)
        return None


def themes() -> list[dict]:
    b = bank()
    return b.list_themes() if b else []


def themed_set(theme_id: str, group_id: str | None = None, exclude: str = "") -> dict | None:
    """依方向抽一組字。字庫不可用時回傳 None；方向不存在時丟 KeyError。"""
    b = bank()
    if b is None:
        return None
    ex = "".join(c for c in exclude if pick_bank.is_single_han(c))[:40]
    return b.pick(theme_id, group_id or None, ex)


def theme_label(theme_id: str, group_id: str | None = None) -> str:
    """方向名稱（給老師看）。代號不正確或字庫不可用時回傳空字串。"""
    b = bank()
    return b.label(theme_id, group_id) if b else ""


@lru_cache
def _bank_chars() -> frozenset[str]:
    b = bank()
    return b.all_chars() if b else frozenset()


def valid_offer(offered: list[str], n: int = 20) -> bool:
    """候選字必須全部來自系統提供的字（隨機字池或主題字庫），防止前端竄改。"""
    p = set(pool()) | _bank_chars()
    return 0 < len(offered) <= n and len(set(offered)) == len(offered) and all(c in p for c in offered)
