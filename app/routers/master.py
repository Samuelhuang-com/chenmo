"""解題老師端：登入、看板、解字工作台、回覆。"""
from __future__ import annotations

import hmac
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import SESSION_KEY, get_oauth, require_master_api, require_master_page
from app.config import get_settings
from app.models import AnswerIn, CaseStatus, JieziIn, NotesIn, now_ms
from app.services.sections import public_reading
from app.services.jiezi import compose
from app.repositories import get_repo
from app.services.realtime import hub
from app.templating import templates

router = APIRouter()


def _login_error(msg: str) -> RedirectResponse:
    return RedirectResponse(f"/master/login?error={quote(msg)}", status_code=303)


# ---------------- 登入 ----------------
@router.get("/master/login")
async def login_page(request: Request, error: str = ""):
    s = get_settings()
    return templates.TemplateResponse(request, "master/login.html", {
        "google": s.google_login_enabled,
        "password": bool(s.master_password),
        "error": error,
    })


@router.post("/master/login")
async def login_password(request: Request, password: str = Form(...)):
    s = get_settings()
    if not s.master_password or not hmac.compare_digest(password, s.master_password):
        return _login_error("密碼錯誤")
    request.session[SESSION_KEY] = {"email": "local", "name": "老師"}
    return RedirectResponse("/master", status_code=303)


@router.get("/master/auth/google")
async def login_google(request: Request):
    oauth = get_oauth()
    if not oauth:
        raise HTTPException(404, "尚未設定 Google 登入")
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/master/auth/callback", name="google_callback")
async def google_callback(request: Request):
    oauth = get_oauth()
    if not oauth:
        raise HTTPException(404)
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:  # noqa: BLE001
        return _login_error("Google 登入失敗，請再試一次")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or email not in get_settings().master_email_set:
        return _login_error("此帳號沒有老師權限")
    request.session[SESSION_KEY] = {"email": email, "name": info.get("name") or email}
    return RedirectResponse("/master", status_code=303)


@router.get("/master/logout")
async def logout(request: Request):
    request.session.pop(SESSION_KEY, None)
    return RedirectResponse("/master/login", status_code=303)


# ---------------- 頁面 ----------------
async def _board_cases() -> list:
    repo = get_repo()
    return (await repo.list_cases(limit=50, status=CaseStatus.drafting)
            + await repo.list_cases(limit=200, status=CaseStatus.submitted)
            + await repo.list_cases(limit=10, status=CaseStatus.answered))


@router.get("/master")
async def board(request: Request, master: dict = Depends(require_master_page)):
    return templates.TemplateResponse(request, "master/board.html", {"master": master})


HISTORY_PAGE = 30


@router.get("/master/history")
async def history(request: Request, q: str = "", page: int = 1,
                  master: dict = Depends(require_master_page)):
    """已解紀錄：依解字時間由新到舊，可用字或問題關鍵字搜尋。"""
    repo = get_repo()
    page = max(page, 1)
    q = q.strip()
    if q:
        # 關鍵字搜尋：掃描最近 2000 筆已解案件
        pool = await repo.list_cases(limit=2000, status=CaseStatus.answered)
        hits = [c for c in pool if q in c.char or q in c.question or q in c.answer or q in c.draft_char]
        cases = hits[(page - 1) * HISTORY_PAGE: page * HISTORY_PAGE + 1]
    else:
        cases = await repo.list_cases(limit=HISTORY_PAGE + 1, status=CaseStatus.answered,
                                      offset=(page - 1) * HISTORY_PAGE)
    has_next = len(cases) > HISTORY_PAGE
    return templates.TemplateResponse(request, "master/history.html", {
        "master": master, "cases": cases[:HISTORY_PAGE], "q": q, "page": page, "has_next": has_next})


@router.get("/master/case/{case_id}")
async def workbench(request: Request, case_id: str, master: dict = Depends(require_master_page)):
    case = await get_repo().get(case_id)
    if not case:
        raise HTTPException(404, "查無此案件")
    return templates.TemplateResponse(request, "master/case.html",
                                      {"master": master, "case": case})


# ---------------- API ----------------
@router.get("/api/master/cases")
async def api_cases(master: dict = Depends(require_master_api)):
    return {"cases": [c.model_dump(mode="json") for c in await _board_cases()]}


@router.get("/api/master/cases/{case_id}")
async def api_case(case_id: str, master: dict = Depends(require_master_api)):
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    return {"case": case.model_dump(mode="json"), "events": await repo.list_events(case_id)}


@router.post("/api/master/cases/{case_id}/answer")
async def api_answer(case_id: str, body: AnswerIn, master: dict = Depends(require_master_api)):
    """送出（或重送）解字。問事者只會收到【解讀】段落，其餘段落留在老師的解字稿。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.status == CaseStatus.drafting:
        raise HTTPException(409, "問事者尚未送出")
    if case.status == CaseStatus.answered:
        raise HTTPException(409, "此字已送出，請先收回再重送")
    reading = public_reading(body.body)
    if not reading:
        raise HTTPException(422, "【解讀】段落是空的。問事者只會收到【解讀】，請先寫好這一段。")
    case = await repo.update(case_id, notes=body.body.strip(), answer=reading,
                             status=CaseStatus.answered, answered_at=now_ms(),
                             answered_by=master.get("email", ""), revision=case.revision + 1)
    await hub.to_user(case.token, {"type": "answer_ready"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    return {"ok": True, "reading": reading, "revision": case.revision}


@router.post("/api/master/cases/{case_id}/retract")
async def api_retract(case_id: str, master: dict = Depends(require_master_api)):
    """收回已送出的解讀：問事者頁面回到「等待老師解讀」，老師可修改後重送。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.status != CaseStatus.answered:
        raise HTTPException(409, "此字尚未送出，不需收回")
    case = await repo.update(case_id, status=CaseStatus.submitted, retracted_at=now_ms())
    await hub.to_user(case.token, {"type": "answer_retracted"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    return {"ok": True}


@router.post("/api/master/cases/{case_id}/notes")
async def api_notes(case_id: str, body: NotesIn, master: dict = Depends(require_master_api)):
    """自動暫存老師的解字稿（不會送給問事者）。"""
    repo = get_repo()
    if not await repo.get(case_id):
        raise HTTPException(404)
    await repo.update(case_id, notes=body.body)
    return {"ok": True}


@router.post("/api/master/cases/{case_id}/jiezi")
async def api_jiezi(case_id: str, body: JieziIn, master: dict = Depends(require_master_api)):
    """帶出解字五段：此字、五行、古字說法、字義、解讀。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.draft and case.draft_char == body.char and not body.refresh:
        return {"char": body.char, "text": case.draft, "cached": True}
    result = await compose(case, await repo.list_events(case_id), body.char)
    await repo.update(case_id, draft=result["text"], draft_char=body.char)
    return {**result, "cached": False}
