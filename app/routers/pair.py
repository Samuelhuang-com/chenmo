"""雙字問心（封測中）：只有功能開關白名單看得到。

流程：填問題 → 依序寫下兩個字（各自標明代表的選擇）→ 呈送 → 老師在案前看兩字對照、寫解讀。
筆跡沿用問字的 WebSocket（/ws/user/{token}），第二字的訊息帶 "pad": 1。
送出解讀、收回、請重寫、刪除、隨喜，沿用問字的老師端 API 與解字工作台（/master/case/{id}）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import current_student
from app.config import get_settings
from app.models import PAIR_CHOICE_MAX, CaseStatus, PairSubmitIn, now_ms, roc_year_now
from app.repositories import get_repo
from app.services.features import require_feature
from app.services.pair import PRESETS
from app.services.realtime import hub
from app.services.strokes import pad_events, visible_strokes
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_feature("pair"))])


def pair_label(case) -> str:
    """給追問脈絡、通知信用：「去／留」。"""
    return f"{case.char}／{case.char2}" if case.char2 else case.char


class PairStartIn(BaseModel):
    redo_of: str = Field(default="", max_length=64)
    follow_of: str = Field(default="", max_length=64)


@router.get("/pair")
async def pair_home(request: Request, redo: str = "", follow: str = "", n: int = 0):
    repo = get_repo()
    student = current_student(request)
    need_login = get_settings().student_login_effective and not student
    prefill: dict = {}
    note = None
    if redo:
        old = await repo.get_by_token(redo)
        if old and old.kind == "pair" and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            prefill = {"question": old.question, "birth_year": old.birth_year, "gender": old.gender,
                       "nickname": old.nickname, "char_a": old.char, "char_b": old.char2,
                       "choice_a": old.choice_a, "choice_b": old.choice_b, "redo_of": old.token}
            note = {"kind": "redo", "reason": old.rewrite_reason}
    elif follow:
        from app.services.followups import suggest
        old = await repo.get_by_token(follow)
        if old and old.status == CaseStatus.answered:
            items = suggest(old.question)
            prefill = {"question": items[n] if 0 <= n < len(items) else "", "birth_year": old.birth_year,
                       "gender": old.gender, "nickname": old.nickname, "follow_of": old.token}
            note = {"kind": "follow", "prev": old.question}
    return templates.TemplateResponse(request, "pair.html", {
        "student": student, "need_login": need_login, "prefill": prefill, "note": note,
        "max_chars": get_settings().question_max_chars, "roc_now": roc_year_now(),
        "choice_max": PAIR_CHOICE_MAX, "presets": PRESETS})


@router.post("/api/pair/cases", status_code=201)
async def start_case(body: PairStartIn, request: Request):
    """第一筆落下（或按呈送）時建立案件；之後筆跡走 WebSocket。"""
    from app.routers.api import _limiter
    from app.services.ratelimit import client_ip
    student = current_student(request)
    if get_settings().student_login_effective and not student:
        raise HTTPException(401, "請先用 Google 帳號登入再問事")
    if not _limiter.allow(client_ip(request)):
        raise HTTPException(429, "提問太頻繁，請稍後再試")
    repo = get_repo()
    case = await repo.create_case()
    fields: dict = {"kind": "pair"}
    if body.redo_of:
        old = await repo.get_by_token(body.redo_of)
        if old and old.kind == "pair" and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            fields["redo_of"] = body.redo_of
    if body.follow_of and not body.redo_of:
        prev = await repo.get_by_token(body.follow_of)
        if prev and prev.status == CaseStatus.answered:
            prev_char = pair_label(prev) if prev.kind == "pair" else (prev.char or prev.gua)
            fields["follow_of"] = body.follow_of
            fields["follow_chain"] = [*prev.follow_chain, {"question": prev.question, "char": prev_char}][-5:]
    if student:
        fields.update(owner_email=student["email"], owner_name=student.get("name", ""))
    case = await repo.update(case.id, **fields)
    await hub.to_masters({"type": "case_new", "case": case.model_dump(mode="json")})
    return {"token": case.token}


@router.post("/api/pair/cases/{token}/submit")
async def submit_case(token: str, body: PairSubmitIn, request: Request):
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case or case.kind != "pair":
        raise HTTPException(404, "查無此案件")
    if case.status != CaseStatus.drafting:
        raise HTTPException(409, "此案件已送出")
    events = await repo.list_events(case.id)
    if not visible_strokes(pad_events(events, 0)):
        raise HTTPException(422, "請先在第一個字格寫下第一個字")
    if not visible_strokes(pad_events(events, 1)):
        raise HTTPException(422, "請在第二個字格寫下第二個字")
    preset = body.preset if body.preset in PRESETS and body.preset == body.char_a + body.char_b else ""
    case = await repo.update(case.id, question=body.question, char=body.char_a, char2=body.char_b,
                             choice_a=body.choice_a, choice_b=body.choice_b, pair_preset=preset,
                             char_source="written", birth_year=body.birth_year, gender=body.gender,
                             nickname=body.nickname, status=CaseStatus.submitted, submitted_at=now_ms())
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
