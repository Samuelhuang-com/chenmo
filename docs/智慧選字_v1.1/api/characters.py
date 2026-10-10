"""辰墨軒｜選字 API（FastAPI router）。

接入方式（在現有 main.py）：
    from api.characters import router as characters_router
    app.include_router(characters_router)

字庫載入失敗時不會讓整站掛掉：自動改用舊字池 character_pool.txt（回應 source = "legacy"）。
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

from services.character_picker import (
    CharacterBank,
    BankError,
    DEFAULT_DATA_DIR,
    is_single_han,
    load_legacy_pool,
    pick_legacy,
)

log = logging.getLogger("chenmo.characters")
router = APIRouter(prefix="/api/characters", tags=["characters"])

_bank: CharacterBank | None = None
_legacy: list[str] = []
_loaded = False


def _ensure_loaded() -> None:
    global _bank, _legacy, _loaded
    if _loaded:
        return
    _loaded = True
    _legacy = load_legacy_pool(Path(DEFAULT_DATA_DIR) / "character_pool.txt")
    try:
        _bank = CharacterBank.load(DEFAULT_DATA_DIR)
        log.info("字庫載入成功：%s", _bank.version)
    except BankError as e:
        _bank = None
        log.error("字庫載入失敗，改用舊字池：%s", e)


def _no_store(resp: Response) -> None:
    # 抽字結果每次不同，不可被瀏覽器或 CDN 快取
    resp.headers["Cache-Control"] = "no-store"


@router.get("/themes")
def themes(response: Response):
    _ensure_loaded()
    if _bank is None:
        return {"source": "legacy", "themes": []}
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"source": "bank", "version": _bank.version, "themes": _bank.list_themes()}


@router.get("/groups")
def groups(response: Response, theme_id: str = Query(..., max_length=32)):
    _ensure_loaded()
    if _bank is None:
        raise HTTPException(503, "字庫暫時無法使用")
    try:
        data = _bank.list_groups(theme_id)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"theme_id": theme_id, "groups": data}


@router.get("/pick")
def pick(
    response: Response,
    theme_id: str = Query(..., max_length=32),
    group_id: str | None = Query(None, max_length=48),
    exclude: str = Query("", max_length=40, description="上一組的字，用於重抽時避開"),
):
    _ensure_loaded()
    _no_store(response)
    if _bank is None:
        if len(_legacy) >= 20:
            return pick_legacy(_legacy)
        raise HTTPException(503, "字庫暫時無法使用")
    ex = "".join(c for c in exclude if is_single_han(c))
    try:
        return _bank.pick(theme_id, group_id=group_id, exclude=ex)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))


@router.get("/random")
def random_pick(response: Response):
    _ensure_loaded()
    _no_store(response)
    if _bank is None:
        if len(_legacy) >= 20:
            return pick_legacy(_legacy)
        raise HTTPException(503, "字庫暫時無法使用")
    return _bank.random()


@router.get("/meaning/{ch}")
def meaning(ch: str, response: Response):
    _ensure_loaded()
    if _bank is None or not is_single_han(ch):
        raise HTTPException(404, "找不到這個字的說明")
    info = _bank.meaning(ch)
    if info is None:
        raise HTTPException(404, "找不到這個字的說明")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"char": ch, **info}
