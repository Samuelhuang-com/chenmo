"""六龍問爻（封測中）：只有功能開關白名單看得到。

流程：填問題 → 擲三枚銅錢六次（結果由後端產生）→ 呈送 → 老師在案前看卦盤、寫解讀 → 問事者頁面更新。
送出解讀、收回、請重擲、刪除、隨喜，沿用問字的老師端 API（/api/master/cases/{id}/…）。
"""
from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import current_student, require_master_api, require_master_page
from app.config import get_settings
from app.models import (ASKED_FOR, YAO_CATEGORIES, Case, CaseStatus, TossIn, YaoStartIn, now_ms,
                        roc_year_now)
from app.repositories import get_repo
from app.services.features import require_feature
from app.services.liuyao import build_chart
from app.services.liuyao.calendar import TPE
from app.services.liuyao.chart import YAO_NAMES
from app.services.realtime import hub
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_feature("yao"))])

# 金錢卦：背 = 3、字 = 2，三枚相加
BACK, FACE = 3, 2


def coins_to_value(coins: list[bool]) -> int:
    """coins：True 代表「背」。"""
    return sum(BACK if c else FACE for c in coins)


def chart_of(case: Case):
    """依案件的六爻與起卦時間排盤；未滿六爻回傳 None。"""
    if len(case.yao_values) != 6:
        return None
    when = datetime.fromtimestamp((case.cast_at or case.submitted_at or now_ms()) / 1000, TPE)
    return build_chart(case.yao_values, when)


def gua_summary(case: Case) -> str:
    c = chart_of(case)
    if not c:
        return ""
    return f"{c.ben.name} → {c.bian.name}" if c.bian else f"{c.ben.name}（靜卦）"


async def _get_yao(token: str) -> Case:
    case = await get_repo().get_by_token(token)
    if not case or case.kind != "yao":
        raise HTTPException(404, "查無此案件")
    return case


async def _push(case: Case) -> None:
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})


# ---------------- 問事者 ----------------
@router.get("/yao")
async def yao_home(request: Request, redo: str = "", follow: str = "", n: int = 0):
    """問爻頁：填問題、擲錢。"""
    repo = get_repo()
    student = current_student(request)
    need_login = get_settings().student_login_effective and not student
    prefill: dict = {}
    note = None
    if redo:
        old = await repo.get_by_token(redo)
        if old and old.kind == "yao" and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            prefill = {"question": old.question, "birth_year": old.birth_year, "gender": old.gender,
                       "nickname": old.nickname, "asked_for": old.asked_for, "category": old.category,
                       "redo_of": old.token}
            note = {"kind": "redo", "reason": old.rewrite_reason}
    elif follow:
        from app.services.followups import suggest
        old = await repo.get_by_token(follow)
        if old and old.status == CaseStatus.answered:
            items = suggest(old.question)
            prefill = {"question": items[n] if 0 <= n < len(items) else "", "birth_year": old.birth_year,
                       "gender": old.gender, "nickname": old.nickname, "asked_for": old.asked_for or "自己",
                       "category": old.category, "follow_of": old.token}
            note = {"kind": "follow", "prev": old.question}
    return templates.TemplateResponse(request, "yao.html", {
        "student": student, "need_login": need_login, "prefill": prefill, "note": note,
        "max_chars": get_settings().question_max_chars, "roc_now": roc_year_now(),
        "asked_for": ASKED_FOR, "categories": YAO_CATEGORIES, "yao_names": YAO_NAMES})


@router.get("/api/yao/ping")
async def yao_ping():
    """封測用：確認此帳號有問爻權限。"""
    return {"ok": True, "feature": "yao"}


@router.post("/api/yao/cases", status_code=201)
async def start_case(body: YaoStartIn, request: Request):
    """開始起卦：建立問爻案件（老師案前會即時出現在「擲錢中」）。"""
    from app.routers.api import _limiter
    from app.services.ratelimit import client_ip
    student = current_student(request)
    if get_settings().student_login_effective and not student:
        raise HTTPException(401, "請先用 Google 帳號登入再問事")
    if not _limiter.allow(client_ip(request)):
        raise HTTPException(429, "提問太頻繁，請稍後再試")
    repo = get_repo()
    case = await repo.create_case()
    fields = dict(kind="yao", question=body.question, birth_year=body.birth_year, gender=body.gender,
                  nickname=body.nickname, asked_for=body.asked_for, category=body.category)
    if body.redo_of:
        old = await repo.get_by_token(body.redo_of)
        if old and old.kind == "yao" and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            fields["redo_of"] = body.redo_of
    if body.follow_of and not body.redo_of:
        prev = await repo.get_by_token(body.follow_of)
        if prev and prev.status == CaseStatus.answered:
            fields["follow_of"] = body.follow_of
            fields["follow_chain"] = [*prev.follow_chain,
                                      {"question": prev.question, "char": prev.char or prev.gua}][-5:]
    if student:
        fields.update(owner_email=student["email"], owner_name=student.get("name", ""))
    case = await repo.update(case.id, **fields)
    await hub.to_masters({"type": "case_new", "case": case.model_dump(mode="json")})
    return {"token": case.token}


@router.post("/api/yao/cases/{token}/toss")
async def toss(token: str, body: TossIn):
    """擲一次。線上擲的結果在這裡（後端）用 secrets 產生，前端只負責動畫。"""
    repo = get_repo()
    case = await _get_yao(token)
    if case.status != CaseStatus.drafting:
        raise HTTPException(409, "此卦已呈送")
    if len(case.yao_values) >= 6:
        raise HTTPException(409, "六爻已滿，請呈送")
    if body.backs is None:
        coins = [secrets.randbelow(2) == 1 for _ in range(3)]
        src = "online"
    else:
        coins = [True] * body.backs + [False] * (3 - body.backs)
        src = "manual"
    value = coins_to_value(coins)
    values = [*case.yao_values, value]
    n = len(values)
    source = src if case.yao_source in ("", src) else "mixed"
    ts = now_ms()
    await repo.append_event(case.id, {"type": "toss", "yao_n": n, "coins": ["背" if c else "字" for c in coins],
                                      "value": value, "source": src, "shake_ms": body.shake_ms, "ts": ts})
    fields = {"yao_values": values, "yao_source": source}
    if n == 6:
        fields["cast_at"] = ts
    case = await repo.update(case.id, **fields)
    if n == 6:
        case = await repo.update(case.id, gua=gua_summary(case))
    await _push(case)
    return {"n": n, "coins": ["背" if c else "字" for c in coins], "value": value,
            "name": YAO_NAMES[value], "values": values, "gua": case.gua}


@router.post("/api/yao/cases/{token}/clear")
async def clear(token: str):
    """整卦清除重擲（不能只重擲某一爻）。清除會記錄，老師看得到。"""
    repo = get_repo()
    case = await _get_yao(token)
    if case.status != CaseStatus.drafting:
        raise HTTPException(409, "此卦已呈送")
    if case.yao_values:
        await repo.append_event(case.id, {"type": "clear", "had": case.yao_values, "ts": now_ms()})
        case = await repo.update(case.id, yao_values=[], yao_source="", cast_at=None, gua="",
                                 yao_clears=case.yao_clears + 1)
        await _push(case)
    return {"ok": True}


@router.post("/api/yao/cases/{token}/submit")
async def submit(token: str, request: Request):
    repo = get_repo()
    case = await _get_yao(token)
    if case.status != CaseStatus.drafting:
        raise HTTPException(409, "此卦已呈送")
    if len(case.yao_values) != 6:
        raise HTTPException(422, "請擲滿六次再呈送")
    case = await repo.update(case.id, status=CaseStatus.submitted, submitted_at=now_ms(),
                             gua=gua_summary(case))
    if case.redo_of:   # 重擲完成：舊案件由新的取代
        old = await repo.get_by_token(case.redo_of)
        if old and old.rewrite_requested_at and old.status == CaseStatus.submitted:
            await repo.delete(old.id)
            await hub.to_masters({"type": "case_deleted", "case_id": old.id})
            await hub.to_user(old.token, {"type": "case_replaced", "url": f"/c/{case.token}"})
    await _push(case)
    from app.services.notify import notify_new_case
    await notify_new_case(case, str(request.base_url))   # 失敗不影響送出
    return {"ok": True, "url": f"/c/{case.token}"}


# ---------------- 老師：問爻工作台 ----------------
@router.get("/master/yao/case/{case_id}")
async def workbench(request: Request, case_id: str, master: dict = Depends(require_master_page)):
    repo = get_repo()
    case = await repo.get(case_id)
    if not case or case.kind != "yao":
        raise HTTPException(404, "查無此案件")
    events = await repo.list_events(case.id)
    tosses = [e for e in events if e.get("type") in ("toss", "clear")]
    # 每一擲距離上一擲的秒數（猶豫程度）
    prev = case.created_at
    for e in tosses:
        e["pause_s"] = round(max(e.get("ts", prev) - prev, 0) / 1000, 1)
        prev = e.get("ts", prev)
    from app.services.richtext import html_to_text, text_to_html
    from app.services.followups import suggest
    from app.services.liuyao import texts as zy
    from app.services.liuyao.yongshen import choose
    chart = chart_of(case)
    ys = choose(chart, case.asked_for, case.category, case.gender, case.yongshen) if chart else None
    return templates.TemplateResponse(request, "master/yao_case.html", {
        "master": master, "case": case, "chart": chart, "tosses": tosses, "ys": ys,
        "texts": zy.for_chart(chart) if chart else None, "texts_note": zy.source_note(),
        "followups": case.followups or suggest(case.question),
        "ai_enabled": bool(get_settings().anthropic_api_key),
        "reading_init": (case.reading_draft or case.answer_html or text_to_html(case.answer or "")),
        "reading_text": html_to_text(case.reading_draft or case.answer_html) if (case.reading_draft or case.answer_html) else case.answer,
        "site_url": (get_settings().site_url or "").rstrip("/")})


class YongshenIn(BaseModel):
    liuqin: str = ""
    special: str = ""
    line: int | None = None


@router.put("/api/master/yao/cases/{case_id}/yongshen")
async def set_yongshen(case_id: str, body: YongshenIn, master: dict = Depends(require_master_api)):
    from app.services.liuyao.chart import LIUQIN
    if body.liuqin and body.liuqin not in LIUQIN or body.special not in ("", "世", "應"):
        raise HTTPException(422, "用神不正確")
    repo = get_repo()
    case = await _get_case_id(case_id)
    data = {} if not (body.liuqin or body.special) else {**body.model_dump(), "set_by": "master"}
    await repo.update(case.id, yongshen=data)
    return {"ok": True}


@router.post("/api/master/yao/cases/{case_id}/ai")
async def ai_draft(case_id: str, master: dict = Depends(require_master_api)):
    """AI 解卦草稿：依卦盤、用神、經文、規則庫與此人以前問過的事。"""
    from app.services import yao_ai, yao_rules
    from app.services.liuyao import texts as zy
    from app.services.liuyao.yongshen import choose
    repo = get_repo()
    case = await _get_case_id(case_id)
    chart = chart_of(case)
    if not chart:
        raise HTTPException(409, "六爻還沒擲滿")
    if not get_settings().anthropic_api_key:
        raise HTTPException(409, "尚未設定 ANTHROPIC_API_KEY，無法產生 AI 草稿")
    ys = choose(chart, case.asked_for, case.category, case.gender, case.yongshen)
    history = []
    if case.owner_email:
        history = [c for c in await repo.list_by_owner(case.owner_email)
                   if c.id != case.id and c.status == CaseStatus.answered]
    context = yao_ai.build_context(case, chart, ys, zy.for_chart(chart), await yao_rules.active_rules(), history)
    data, reason = await yao_ai.generate(context)
    if not data:
        raise HTTPException(502, f"AI 草稿產生失敗：{reason}")
    await repo.update(case.id, draft=data["reading"])
    return data


class FollowupsIn(BaseModel):
    items: list[str] = Field(max_length=3)


@router.put("/api/master/yao/cases/{case_id}/followups")
async def set_followups(case_id: str, body: FollowupsIn, master: dict = Depends(require_master_api)):
    case = await _get_case_id(case_id)
    items = [i.strip()[:40] for i in body.items if i.strip()]
    case = await get_repo().update(case.id, followups=items)
    if case.status == CaseStatus.answered:
        await hub.to_user(case.token, {"type": "answer_ready"})
    return {"ok": True, "items": items}


VERIFY = ("", "應驗", "部分應驗", "未應驗")


class VerifyIn(BaseModel):
    status: str = ""
    note: str = Field(default="", max_length=1000)


@router.put("/api/master/yao/cases/{case_id}/verify")
async def set_verify(case_id: str, body: VerifyIn, master: dict = Depends(require_master_api)):
    """卦例回饋：事後記錄有沒有應驗，累積起來回頭修正規則庫。"""
    if body.status not in VERIFY:
        raise HTTPException(422, "狀態不正確")
    case = await _get_case_id(case_id)
    await get_repo().update(case.id, verify_status=body.status, verify_note=body.note.strip(),
                            verified_at=now_ms() if body.status else None)
    return {"ok": True}


async def _get_case_id(case_id: str) -> Case:
    case = await get_repo().get(case_id)
    if not case or case.kind != "yao":
        raise HTTPException(404, "查無此案件")
    return case


# ---------------- 老師：斷卦規則庫與卦例 ----------------
@router.get("/master/yao/rules")
async def rules_page(request: Request, v: str = "", msg: str = "", master: dict = Depends(require_master_page)):
    from app.services import yao_rules
    repo = get_repo()
    answered = [c for c in await repo.list_cases(limit=500, status=CaseStatus.answered) if c.kind == "yao"]
    if v == "none":
        answered = [c for c in answered if not c.verify_status]
    elif v:
        answered = [c for c in answered if c.verify_status == v]
    counts = {k: 0 for k in VERIFY[1:]}
    for c in answered:
        if c.verify_status in counts:
            counts[c.verify_status] += 1
    return templates.TemplateResponse(request, "master/yao_rules.html", {
        "master": master, "rules": await yao_rules.list_rules(), "cases": answered[:100],
        "counts": counts, "v": v, "msg": msg, "verify": VERIFY[1:]})


@router.post("/master/yao/rules")
async def rules_save(request: Request, master: dict = Depends(require_master_page)):
    from fastapi.responses import RedirectResponse
    from app.services import yao_rules
    form = await request.form()
    try:
        await yao_rules.save_rule(str(form.get("id") or "") or None, str(form.get("title") or ""),
                                  str(form.get("text") or ""), form.get("active") == "1")
    except ValueError as e:
        return RedirectResponse(f"/master/yao/rules?msg={e}", status_code=303)
    return RedirectResponse("/master/yao/rules?msg=已儲存", status_code=303)


@router.post("/master/yao/rules/{rule_id}/delete")
async def rules_delete(rule_id: str, master: dict = Depends(require_master_page)):
    from fastapi.responses import RedirectResponse
    from app.services import yao_rules
    await yao_rules.delete_rule(rule_id)
    return RedirectResponse("/master/yao/rules?msg=已刪除", status_code=303)


# ---------------- 老師：以字起卦（梅花易數） ----------------
class DeriveIn(BaseModel):
    char: str = Field(default="", max_length=2)


@router.post("/api/master/yao/derive/{case_id}")
async def derive_from_char(case_id: str, body: DeriveIn | None = None, master: dict = Depends(require_master_api)):
    """問字案件：用字的康熙筆畫數加時辰起一個參考卦，掛在原問字案件下。"""
    from app.services.chardict import lookup
    from app.services.liuyao.meihua import values_from_strokes
    repo = get_repo()
    case = await repo.get(case_id)
    if not case or case.kind == "yao":
        raise HTTPException(404, "查無此問字案件")
    char = ((body.char if body else "") or case.char or case.draft_char).strip()[:1]
    if not char:
        raise HTTPException(422, "這一筆還不知道寫的是哪個字，請先在「此字」欄填上")
    strokes = lookup(char).kangxi_strokes or lookup(char).total_strokes
    if not strokes:
        raise HTTPException(422, f"字庫查不到「{char}」的筆畫數")
    ts = case.submitted_at or now_ms()
    when = datetime.fromtimestamp(ts / 1000, TPE)
    values, info = values_from_strokes(strokes, when)
    chart = build_chart(values, when)
    derived = {"char": char, "values": values, "cast_at": ts, "when": f"{when:%Y-%m-%dT%H:%M}", **info,
               "gua": f"{chart.ben.name} → {chart.bian.name}" if chart.bian else chart.ben.name}
    await repo.update(case.id, derived_yao=derived)
    url = f"/master/yao/paipan?v={''.join(map(str, values))}&t={when:%Y-%m-%dT%H:%M}&zi=1"
    return {**derived, "url": url}


# ---------------- 問事者：不再占提醒 ----------------
class RecentIn(BaseModel):
    question: str = Field(default="", max_length=400)
    category: str = ""
    tokens: list[str] = Field(default_factory=list, max_length=30)


def _similar(a: str, b: str) -> bool:
    grams = lambda t: {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}  # noqa: E731
    ga, gb = grams("".join(a.split())), grams("".join(b.split()))
    return bool(ga and gb) and len(ga & gb) / len(ga | gb) >= 0.4


@router.post("/api/yao/recent")
async def recent_similar(body: RecentIn, request: Request):
    """近期是否問過類似的事（古人說「初筮告，再三瀆」）。只提醒，不擋。"""
    import os
    days = int(os.environ.get("YAO_REPEAT_DAYS", "7"))
    since = now_ms() - days * 86400_000
    repo = get_repo()
    student = current_student(request)
    pool = list(await repo.list_by_owner(student["email"])) if student else []
    for t in body.tokens[:30]:
        c = await repo.get_by_token(t)
        if c and all(c.id != x.id for x in pool):
            pool.append(c)
    for c in sorted(pool, key=lambda c: c.created_at, reverse=True):
        if c.kind != "yao" or c.status == CaseStatus.drafting or (c.submitted_at or 0) < since:
            continue
        if _similar(body.question, c.question) or (body.category and body.category == c.category):
            return {"match": {"question": c.question, "gua": c.gua, "url": f"/c/{c.token}",
                              "when": c.submitted_at, "days": days}}
    return {"match": None}


# ---------------- 老師：排盤工具 ----------------
def _parse(values: str, when: str) -> tuple[list[int], datetime]:
    v = [int(c) for c in values if c.isdigit()]
    try:
        t = datetime.fromisoformat(when) if when else datetime.now(TPE)
    except ValueError:
        raise HTTPException(422, "時間格式不對")
    return v, t


@router.get("/master/yao/paipan")
async def paipan_page(request: Request, v: str = "", t: str = "", zi: int = 1,
                      master: dict = Depends(require_master_page)):
    """排盤工具：輸入六爻與時間，看系統排出的卦盤，和自己的排法對照。"""
    chart, error = None, ""
    values, when = _parse(v, t)
    if v:
        try:
            chart = build_chart(values, when, zi_new_day=bool(zi))
        except ValueError as e:
            error = str(e)
    return templates.TemplateResponse(request, "master/yao_paipan.html", {
        "master": master, "chart": chart, "error": error,
        "values": values if len(values) == 6 else [7, 7, 7, 7, 7, 7],
        "when": when.astimezone(TPE).strftime("%Y-%m-%dT%H:%M") if when.tzinfo else when.strftime("%Y-%m-%dT%H:%M"),
        "zi": zi})


class ChartIn(BaseModel):
    values: list[int] = Field(min_length=6, max_length=6, description="初爻→上爻，6/7/8/9")
    when: datetime | None = None
    zi_new_day: bool = True


@router.post("/api/master/yao/chart")
async def api_chart(body: ChartIn, master: dict = Depends(require_master_api)):
    try:
        chart = build_chart(body.values, body.when or datetime.now(TPE), body.zi_new_day)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return chart.as_dict()
