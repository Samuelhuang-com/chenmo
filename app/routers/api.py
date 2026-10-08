"""問事者端 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.models import CaseStatus, SubmitIn, now_ms
from app.repositories import get_repo
from app.services.ratelimit import RateLimiter, client_ip
from app.services.realtime import hub
from app.services.strokes import visible_strokes

router = APIRouter(prefix="/api")

_limiter = RateLimiter(limit=get_settings().cases_per_ip_per_hour, window_sec=3600)


@router.post("/cases", status_code=201)
async def create_case(request: Request):
    from app.auth import current_student
    student = current_student(request)
    if get_settings().student_login_effective and not student:
        raise HTTPException(401, "請先用 Google 帳號登入再問字")
    if not _limiter.allow(client_ip(request)):
        raise HTTPException(429, "提問太頻繁，請稍後再試")
    repo = get_repo()
    try:
        data = await request.json()
        redo_of = str(data.get("redo_of", ""))[:64]
        follow_of = str(data.get("follow_of", ""))[:64]
    except Exception:  # noqa: BLE001  沒有 body 就是一般新問字
        redo_of = follow_of = ""
    case = await repo.create_case()
    if redo_of:
        old = await repo.get_by_token(redo_of)
        if old and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            case = await repo.update(case.id, redo_of=redo_of)
    if follow_of and not redo_of:
        prev = await repo.get_by_token(follow_of)
        if prev and prev.status == CaseStatus.answered:
            # 追問：帶入前面每一輪的「問題」與「字」（只要字，不帶筆跡），方便老師綜合判讀
            chain = [*prev.follow_chain, {"question": prev.question, "char": prev.char}][-5:]
            case = await repo.update(case.id, follow_of=follow_of, follow_chain=chain)
    if student:
        case = await repo.update(case.id, owner_email=student["email"], owner_name=student.get("name", ""))
    await hub.to_masters({"type": "case_new", "case": case.model_dump(mode="json")})
    return {"token": case.token}


@router.get("/cases/{token}")
async def get_case(token: str):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        raise HTTPException(404, "查無此案件")
    events = await repo.list_events(case.id)
    return {"case": case.public_dict(), "strokes": visible_strokes(events)}


@router.get("/pick")
async def pick_set():
    """自選字：隨機提供 20 個字。"""
    from app.services.pick import random_set
    return {"chars": random_set(20)}


@router.post("/cases/{token}/submit")
async def submit_case(token: str, body: SubmitIn, request: Request):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        raise HTTPException(404, "查無此案件")
    if case.status != CaseStatus.drafting:
        raise HTTPException(409, "此案件已送出")
    events = await repo.list_events(case.id)
    if body.picked:
        from app.services.pick import valid_offer
        if not body.char or not valid_offer(body.offered) or body.char not in body.offered:
            raise HTTPException(422, "自選字資料不正確，請重新選字")
        extra = {"char_source": "picked", "offered": body.offered, "pick_rounds": body.rounds}
    else:
        if not visible_strokes(events):
            raise HTTPException(422, "請先在字格中寫下一個字，或按「自選字」選一個字")
        extra = {"char_source": "written", "offered": [], "pick_rounds": 0}
    case = await repo.update(case.id, **extra, question=body.question, char=body.char,
                             birth_year=body.birth_year, gender=body.gender,
                             status=CaseStatus.submitted, submitted_at=now_ms())
    if case.redo_of:   # 重寫完成：老師要求重寫的舊案件由新的取代
        old = await repo.get_by_token(case.redo_of)
        if old and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            await repo.delete(old.id)
            await hub.to_masters({"type": "case_deleted", "case_id": old.id})
            await hub.to_user(old.token, {"type": "case_replaced", "url": f"/c/{case.token}"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    from app.services.notify import notify_new_case
    await notify_new_case(case, str(request.base_url))   # 失敗不影響送出
    return {"ok": True, "url": f"/c/{case.token}"}
