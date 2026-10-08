"""問事者端頁面（Jinja2）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.repositories import get_repo
from app.services.strokes import visible_strokes
from app.templating import templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/ask")
async def ask(request: Request):
    from app.models import roc_year_now
    return templates.TemplateResponse(request, "ask.html",
                                      {"max_chars": get_settings().question_max_chars,
                                       "roc_now": roc_year_now()})


@router.get("/c/{token}")
async def case_page(request: Request, token: str):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        raise HTTPException(404, "查無此案件")
    strokes = visible_strokes(await repo.list_events(case.id))
    return templates.TemplateResponse(request, "case.html",
                                      {"case": case, "strokes": strokes})


@router.get("/healthz")
async def healthz():
    return {"ok": True}
