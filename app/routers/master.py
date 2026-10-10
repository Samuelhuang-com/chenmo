"""解題老師端：登入、看板、解字工作台、回覆。"""
from __future__ import annotations

import hmac
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import SESSION_KEY, STUDENT_KEY, get_oauth, require_master_api, require_master_page
from app.config import get_settings
from app.models import AnswerIn, CaseStatus, JieziIn, NotesIn, RewriteIn, SponsorIn, now_ms
from app.services.richtext import html_to_text, sanitize_html, text_to_html
from app.services.sections import public_reading, split_sections
from app.services.jiezi import compose
from app.repositories import get_repo
from app.services.realtime import hub
from app.templating import fmt_ms, templates

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
    request.session["login_for"] = "master"
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/me/login")
async def student_login(request: Request, next: str = "/me"):
    """學生（問事者）用 Google 登入。與老師共用同一個回呼網址，不需另外設定 OAuth。"""
    oauth = get_oauth()
    if not oauth:
        return RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    request.session["login_for"] = "student"
    request.session["login_next"] = next if next.startswith("/") and not next.startswith("//") else "/me"
    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/me/logout")
async def student_logout(request: Request):
    request.session.pop(STUDENT_KEY, None)
    return RedirectResponse("/", status_code=303)


@router.get("/master/auth/callback", name="google_callback")
async def google_callback(request: Request):
    oauth = get_oauth()
    if not oauth:
        raise HTTPException(404)
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:  # noqa: BLE001
        if request.session.pop("login_for", "master") == "student":
            return RedirectResponse("/?login_error=1", status_code=303)
        return _login_error("Google 登入失敗，請再試一次")
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if request.session.pop("login_for", "master") == "student":
        if not info.get("email_verified") or not email:
            return RedirectResponse("/?login_error=1", status_code=303)
        request.session[STUDENT_KEY] = {"email": email, "name": info.get("name") or email}
        nxt = request.session.pop("login_next", "/me")
        if email in get_settings().master_email_set:
            # 老師從前台登入：同時開啟老師身分，直接進案前（除非是要去問字頁或看某一案）
            request.session[SESSION_KEY] = {"email": email, "name": info.get("name") or email}
            if not (nxt.startswith("/ask") or nxt.startswith("/c/")):
                nxt = "/master"
        return RedirectResponse(nxt, status_code=303)
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


@router.get("/master/pick-stats")
async def pick_stats_page(request: Request, days: int = 0, master: dict = Depends(require_master_page)):
    """自選字統計：多少人用自選字、有沒有選方向、各方向被選次數（只算數量）。"""
    from app.services.pick_stats import load_cases, summarize
    days = days if days in (7, 30) else 0
    stats = summarize(await load_cases(get_repo()), days=days or None)
    return templates.TemplateResponse(request, "master/pick_stats.html", {"master": master, "s": stats})


@router.get("/master/case/{case_id}")
async def workbench(request: Request, case_id: str, master: dict = Depends(require_master_page)):
    case = await get_repo().get(case_id)
    if not case:
        raise HTTPException(404, "查無此案件")
    from app.services.sections import split_sections
    reading_init = case.reading_draft or case.answer_html
    if not reading_init:   # 舊資料：從純文字的【解讀】段落（或已送出的內容）轉成段落
        reading_init = text_to_html(case.answer or split_sections(case.notes or case.draft or "").get("解讀", ""))
    from app.services.sections import AI_MARK as _AI, NO_AI_MARK
    reading_init = reading_init.replace(NO_AI_MARK, "")
    return templates.TemplateResponse(request, "master/case.html",
                                      {"master": master, "case": case, "reading_init": reading_init,
                                       "site_url": (get_settings().site_url or "").rstrip("/")})


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


def _reading_of(body: AnswerIn) -> tuple[str, str]:
    """回傳（純文字解讀，安全的 HTML）。有編輯器內容就用編輯器的，否則沿用舊的【解讀】段落。"""
    if body.reading_html is not None:
        from app.services.sections import AI_MARK, NO_AI_MARK
        html_ = sanitize_html(body.reading_html).replace(AI_MARK, "").replace(NO_AI_MARK, "")
        return html_to_text(html_), html_
    return public_reading(body.body), ""


@router.get("/master/system")
async def system_page(request: Request, master: dict = Depends(require_master_page)):
    """系統狀態：確認部署版本、AI、寄信、贊助等設定是否生效。"""
    import os
    s = get_settings()
    ver, commit, deployed = (os.environ.get(k, "") for k in ("APP_VERSION", "APP_COMMIT", "APP_DEPLOYED_AT"))
    if not ver:   # 本機執行：直接讀目前的 git commit
        try:
            import subprocess
            run = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3,
                                            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))).stdout.strip()
            ver, commit = run("log", "-1", "--pretty=%s"), run("rev-parse", "--short", "HEAD")
        except Exception:
            ver = commit = ""
    checks = [
        ("版次", (ver + (f"（{commit}）" if commit else "")) if ver else "未知（部署時沒有帶入版次）"),
        ("部署時間", deployed or "—"),
        ("部署版本（Cloud Run revision）", os.environ.get("K_REVISION") or "本機執行（沒有版本號）"),
        ("網站網址 SITE_URL", s.site_url or "未設定（信中連結會用目前網址）"),
        ("AI 金鑰", "已設定" if s.anthropic_api_key else "未設定"),
        ("寄信（新問字通知、送出解讀寄信）", "已設定" if s.email_enabled else "未設定（需要 SMTP_USER、SMTP_PASSWORD、NOTIFY_EMAILS）"),
        ("Google 登入", "已啟用" if s.google_login_enabled else "未啟用"),
        ("問事者必須登入才能問字", "是" if s.student_login_effective else "否（可不登入）"),
        ("銀行轉帳資訊", "已設定" if (s.sponsor_bank_code and s.sponsor_bank_account) else "未設定"),
        ("LINE 加好友按鈕", s.sponsor_line_url or "不顯示"),
    ]
    return templates.TemplateResponse(request, "master/system.html", {"master": master, "checks": checks})


@router.post("/api/master/ai_check")
async def api_ai_check(master: dict = Depends(require_master_api)):
    from app.services.ai_draft import ping
    ok, msg = await ping()
    return {"ok": ok, "message": msg}


def _char_mismatch(case, text: str) -> tuple[str, str] | None:
    """解字稿【此字】的第一個字，與問事者所寫的字不同時，回傳（所寫的字, 解字稿的字）。問爻案件不檢查。"""
    if case.kind != "char":
        return None
    asked = next(iter((case.char or "").strip()), "")
    head = split_sections(text).get("此字", "").strip()
    section = next(iter(head), "")
    if asked and section and asked != section:
        return asked, section
    return None


def _already_sent_msg(case) -> str:
    when = fmt_ms(case.answered_at)
    return (f"此字已於 {when} 送出（第 {case.revision} 次），不會重複送出。"
            "要修改請按「更新解讀」，或先「收回」再重送。")


@router.post("/api/master/cases/{case_id}/answer")
async def api_answer(case_id: str, body: AnswerIn, request: Request, master: dict = Depends(require_master_api)):
    """送出（或重送）解字。問事者只會收到【解讀】段落，其餘段落留在老師的解字稿。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.status == CaseStatus.drafting:
        raise HTTPException(409, "問事者尚未送出")
    if case.status == CaseStatus.answered:
        raise HTTPException(409, _already_sent_msg(case))
    reading, html_ = _reading_of(body)
    if not reading:
        raise HTTPException(422, "【解讀】段落是空的。問事者只會收到【解讀】，請先寫好這一段。")
    mm = None if body.ack_char_mismatch else _char_mismatch(case, body.body)
    if mm:
        raise HTTPException(409, {
            "code": "char_mismatch", "asked": mm[0], "section": mm[1],
            "message": f"解字稿【此字】是「{mm[1]}」，但問事者所寫的是「{mm[0]}」，請確認沒有貼錯。"
                       "若確定無誤，請在送出確認框勾選後再送出。"})
    # 原子比對：只有「狀態仍是待解」才寫入。同時兩個請求（連點、兩個分頁、逾時重試）只會有一個成功，
    # 失敗的那個不會寫入、不會通知問事者、也不會寄信。
    updated = await repo.transition(case_id, CaseStatus.submitted,
                                    notes=body.body.strip(), answer=reading, answer_html=html_,
                                    reading_draft=html_,
                                    status=CaseStatus.answered, answered_at=now_ms(),
                                    answered_by=master.get("email", ""), revision=case.revision + 1)
    if updated is None:
        latest = await repo.get(case_id)
        if latest and latest.status == CaseStatus.answered:
            raise HTTPException(409, _already_sent_msg(latest))
        raise HTTPException(409, "此字的狀態剛剛變動了，請重新整理頁面確認後再送出")
    case = updated
    await hub.to_user(case.token, {"type": "answer_ready"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    emailed, email_note = None, ""
    if body.email_student:
        from app.services.notify import notify_student_answered
        emailed, email_note = await notify_student_answered(case, str(request.base_url))   # 失敗不影響送出
    return {"ok": True, "reading": reading, "revision": case.revision,
            "emailed": emailed, "email_note": email_note, "email_to": case.owner_email}


@router.put("/api/master/cases/{case_id}/sponsor")
async def api_set_sponsor(case_id: str, body: SponsorIn, master: dict = Depends(require_master_api)):
    """老師決定：是否在這位問事者的頁面顯示「請老師喝杯咖啡」贊助區塊（預設不顯示）。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    case = await repo.update(case_id, show_sponsor=body.show)
    if case.status == CaseStatus.answered:
        await hub.to_user(case.token, {"type": "answer_ready"})   # 問事者頁面即時更新
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    return {"ok": True, "show": case.show_sponsor}


@router.put("/api/master/cases/{case_id}/reading")
async def api_edit_reading(case_id: str, body: AnswerIn, master: dict = Depends(require_master_api)):
    """已送出後直接修改【解讀】：不必收回，問事者頁面會即時更新。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.status != CaseStatus.answered:
        raise HTTPException(409, "此字尚未送出，請用「送出解讀」")
    reading, html_ = _reading_of(body)
    if not reading:
        raise HTTPException(422, "【解讀】是空的。問事者只會看到【解讀】，請先寫好內容。")
    case = await repo.update(case_id, notes=body.body.strip(), answer=reading, answer_html=html_,
                             reading_draft=html_, reading_edited_at=now_ms())
    await hub.to_user(case.token, {"type": "answer_ready"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    return {"ok": True, "reading": reading}


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


@router.post("/api/master/cases/{case_id}/request_rewrite")
async def api_request_rewrite(case_id: str, body: RewriteIn, master: dict = Depends(require_master_api)):
    """請問事者重寫：問事者的結果頁會出現「請重寫」與重新書寫按鈕。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    if case.status == CaseStatus.drafting:
        raise HTTPException(409, "問事者還在書寫中，尚未送出")
    if case.status == CaseStatus.answered:
        raise HTTPException(409, "此字已解讀送出。要請對方重寫，請先按「收回」")
    case = await repo.update(case_id, rewrite_requested_at=now_ms(), rewrite_reason=body.reason.strip())
    await hub.to_user(case.token, {"type": "rewrite_requested"})
    await hub.to_masters({"type": "case_update", "case": case.model_dump(mode="json")})
    return {"ok": True}


@router.delete("/api/master/cases/{case_id}")
async def api_delete(case_id: str, master: dict = Depends(require_master_api)):
    """刪除這一筆（含筆跡紀錄），無法復原。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    await repo.delete(case_id)
    await hub.to_user(case.token, {"type": "case_deleted"})
    await hub.to_masters({"type": "case_deleted", "case_id": case_id})
    return {"ok": True}


@router.post("/api/master/cases/{case_id}/notes")
async def api_notes(case_id: str, body: NotesIn, master: dict = Depends(require_master_api)):
    """自動暫存老師的解字稿（不會送給問事者）。"""
    repo = get_repo()
    if not await repo.get(case_id):
        raise HTTPException(404)
    fields = {"notes": body.body}
    if body.reading_html is not None:
        fields["reading_draft"] = sanitize_html(body.reading_html)
    await repo.update(case_id, **fields)
    return {"ok": True}


@router.post("/api/master/cases/{case_id}/jiezi")
async def api_jiezi(case_id: str, body: JieziIn, master: dict = Depends(require_master_api)):
    """帶出解字五段：此字、五行、古字說法、字義、解讀。"""
    repo = get_repo()
    case = await repo.get(case_id)
    if not case:
        raise HTTPException(404)
    stale = bool(case.derived_yao) and "【參考卦】" not in (case.draft or "")   # 起卦後要重新帶出才會有參考卦
    if case.draft and case.draft_char == body.char and not body.refresh and not stale:
        return {"char": body.char, "text": case.draft, "cached": True}
    result = await compose(case, await repo.list_events(case_id), body.char)
    # AI 設定了卻失敗時不要快取，下次按「帶出字資料」才會重試
    if result["ai_used"] or not result["ai_error"]:
        await repo.update(case_id, draft=result["text"], draft_char=body.char)
    return {**result, "cached": False}
