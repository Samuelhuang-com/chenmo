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
async def ask(request: Request, redo: str = "", follow: str = "", n: int = 0):
    from app.auth import current_student
    from app.models import roc_year_now
    student = current_student(request)
    need_login = get_settings().student_login_effective and not student
    redo_case = None
    if redo:
        old = await get_repo().get_by_token(redo)
        if old and old.rewrite_requested_at and old.status.value == "submitted":
            redo_case = {"token": old.token, "question": old.question, "birth_year": old.birth_year,
                         "gender": old.gender, "nickname": old.nickname, "reason": old.rewrite_reason}
    follow_case = None
    if follow and not redo_case:
        from app.services.followups import suggest
        old = await get_repo().get_by_token(follow)
        if old and old.status.value == "answered":
            items = suggest(old.question)
            follow_case = {"token": old.token, "prev": old.question, "birth_year": old.birth_year,
                           "gender": old.gender, "nickname": old.nickname, "question": items[n] if 0 <= n < len(items) else ""}
    return templates.TemplateResponse(request, "ask.html",
                                      {"follow": follow_case, "max_chars": get_settings().question_max_chars,
                                       "roc_now": roc_year_now(),
                                       "student": student, "need_login": need_login,
                                       "redo": redo_case})


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
async def case_page(request: Request, token: str, claim: str = ""):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        raise HTTPException(404, "查無此案件")
    strokes = visible_strokes(await repo.list_events(case.id))
    from app.auth import current_student
    student = current_student(request)
    claimed = False
    # 沒登入時問的字，事後登入可以收進「我的問字」（只限還沒有主人的案件）
    if claim and student and not case.owner_email and case.status.value != "drafting":
        case = await repo.update(case.id, owner_email=student["email"], owner_name=student.get("name", ""))
        claimed = True
    from app.services.followups import suggest
    return templates.TemplateResponse(request, "case.html",
                                      {"followups": suggest(case.question) if case.status.value == "answered" else [],
                                       "case": case, "strokes": strokes, "student": student,
                                       "is_owner": bool(student and student["email"] == case.owner_email),
                                       "claimed": claimed,
                                       "can_claim": bool(not case.owner_email and case.status.value != "drafting")})


@router.get("/privacy")
async def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms")
async def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})


@router.get("/healthz")
async def healthz():
    return {"ok": True}
