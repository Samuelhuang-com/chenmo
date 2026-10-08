"""問事者端頁面（Jinja2）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.repositories import get_repo
from app.services.strokes import visible_strokes
from app.templating import templates

router = APIRouter()


@router.get("/")
async def index(request: Request, source: str = ""):
    # 老師從手機主畫面打開 App：直接進案前
    if source == "pwa" and request.session.get("master"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/master", status_code=303)
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/ask")
async def ask(request: Request):
    from app.auth import current_student
    from app.models import roc_year_now
    student = current_student(request)
    need_login = get_settings().student_login_effective and not student
    return templates.TemplateResponse(request, "ask.html",
                                      {"max_chars": get_settings().question_max_chars,
                                       "roc_now": roc_year_now(),
                                       "student": student, "need_login": need_login})


@router.get("/me")
async def my_cases(request: Request):
    """我的問字：學生登入後查看自己問過的字與老師的解讀。"""
    from app.auth import current_student
    student = current_student(request)
    cases = []
    if student:
        cases = [c for c in await get_repo().list_by_owner(student["email"]) if c.status.value != "drafting"]
    return templates.TemplateResponse(request, "me.html", {"student": student, "cases": cases})


@router.get("/c/{token}")
async def case_page(request: Request, token: str):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        raise HTTPException(404, "查無此案件")
    strokes = visible_strokes(await repo.list_events(case.id))
    from app.auth import current_student
    student = current_student(request)
    return templates.TemplateResponse(request, "case.html",
                                      {"case": case, "strokes": strokes, "student": student,
                                       "is_owner": bool(student and student["email"] == case.owner_email)})


@router.get("/privacy")
async def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms")
async def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})


@router.get("/healthz")
async def healthz():
    return {"ok": True}
