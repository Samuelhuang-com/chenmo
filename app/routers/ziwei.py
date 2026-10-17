"""老師端：紫微斗數排盤工具（封測）。"""
import json
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import current_student, require_master_api, require_master_page
from app.services.features import require_feature
from app.services.ziwei import build_chart
from app.services.ziwei.ai import facts_text
from app.services.ziwei.chart import liunian_overlay, liunian_rows
from app.services.ziwei.records import get_ziwei_store, make_record
from app.services.ziwei.chart import BRANCHES
from app.templating import templates

router = APIRouter()
TPE = timezone(timedelta(hours=8))


def _render(request: Request, y, m, d, h, mi, g, late, ly, mode, master, rec=None, zizhan=False, question=None):
    now = datetime.now(TPE)
    if y is None:
        y, m, d, h, mi = now.year, now.month, now.day, now.hour, now.minute
    chart, error = None, ""
    try:
        chart = build_chart(y, m, d, h, mi, gender=g, late_zi_next_day=bool(late))
    except ValueError as e:
        error = str(e) or "日期或時間不正確"
    hours = [(i, f"{i:02d}:00 {BRANCHES[((i + 1) // 2) % 12]}時") for i in range(24)]
    liu = liunian_rows(chart.birth_lunar_year, now.year) if chart else []
    ly = ly or now.year
    mode = "y" if mode == "y" else "n"
    overlay = liunian_overlay(chart, ly) if chart and mode == "y" else None
    rec_js = json.dumps(rec, ensure_ascii=False).replace("</", "<\\/") if rec else "null"
    years = list(range(now.year - 20, now.year + 31))
    return templates.TemplateResponse(request, "master/ziwei_paipan.html", {
        "master": master, "chart": chart, "error": error, "hours": hours, "liu": liu,
        "overlay": overlay, "years": years, "rec": rec, "rec_js": rec_js,
        "zizhan": zizhan, "question": question,
        "f": {"y": y, "m": m, "d": d, "h": h, "mi": mi, "g": g, "late": late, "ly": ly, "mode": mode}})


@router.get("/master/ziwei/paipan")
async def ziwei_paipan(request: Request, y: int | None = None, m: int = 1, d: int = 1,
                       h: int = 12, mi: int = 0, g: str = "男", late: int = 0,
                       ly: int | None = None, mode: str = "n",
                       rid: str | None = None,
                       master: dict = Depends(require_master_page)):
    """老師端排盤。帶 rid 時開啟已儲存的紀錄（生辰以紀錄為準）。"""
    rec = None
    if rid:
        rec = await get_ziwei_store().get(rid)
        if rec is None:
            raise HTTPException(404, "找不到此紀錄")
        b = rec["birth"]
        y, m, d, h, mi, g, late = b["y"], b["m"], b["d"], b["h"], b["mi"], b["g"], b["late"]
        ly = ly or rec["ly"]
    return _render(request, y, m, d, h, mi, g, late, ly, mode, master, rec=rec)


@router.get("/ziwei", dependencies=[Depends(require_feature("ziwei"))])
async def ziwei_student(request: Request, y: int | None = None, m: int = 1, d: int = 1,
                        h: int = 12, mi: int = 0, g: str = "男", late: int = 0,
                        ly: int | None = None, mode: str = "n"):
    """學生端（封測）：只有開關允許的 Email 看得到，不在名單內回 404。"""
    return _render(request, y, m, d, h, mi, g, late, ly, mode, None)


@router.post("/master/ziwei/ai")
async def ziwei_ai(y: int | None = None, m: int | None = None, d: int | None = None, h: int = 12,
                   mi: int = 0, g: str = "男", late: int = 0, ly: int | None = None,
                   rid: str | None = None,
                   master: dict = Depends(require_master_api)):
    """老師端：AI 草稿解讀流年注意事項（結果只給老師審閱）。"""
    from app.services.ziwei.ai import facts_text, interpret
    if y is None or m is None or d is None:
        return {"text": None, "msg": "請先輸入出生日期並排盤，再按 AI 解讀"}
    try:
        chart = build_chart(y, m, d, h, mi, gender=g, late_zi_next_day=bool(late))
    except ValueError as e:
        return {"text": None, "msg": str(e)}
    ly = ly or datetime.now(TPE).year
    question = None
    if rid:
        rec = await get_ziwei_store().get(rid)
        question = (rec or {}).get("question") or None
    try:
        month = datetime.now(TPE).month
        text, msg = await interpret(facts_text(chart, ly, month, question=question))
    except Exception as e:  # noqa: BLE001  錯誤以文字回傳，方便老師看見原因
        return {"text": None, "msg": f"解命盤失敗：{type(e).__name__}：{e}"}
    return {"text": text, "msg": msg}


# ---- 命盤紀錄（老師端）：存命盤、解讀與備註，可讀取、修改、刪除 ----

def _birth_from(body: dict) -> dict:
    def num(k, default=None):
        try:
            return int(body.get(k, default))
        except (TypeError, ValueError):
            raise HTTPException(400, f"欄位 {k} 格式不正確")
    return {
        "y": num("y"), "m": num("m"), "d": num("d"),
        "h": num("h", 12), "mi": num("mi", 0),
        "g": "女" if str(body.get("g", "男")) == "女" else "男",
        "late": 1 if str(body.get("late", "0")) in ("1", "true", "on") else 0,
        "ly": num("ly", datetime.now(TPE).year),
    }


@router.post("/master/ziwei/records")
async def ziwei_record_create(request: Request, master: dict = Depends(require_master_api)):
    body = await request.json()
    b = _birth_from(body)
    try:
        chart = build_chart(b["y"], b["m"], b["d"], b["h"], b["mi"], gender=b["g"],
                            late_zi_next_day=bool(b["late"]))
    except ValueError as e:
        raise HTTPException(400, str(e) or "日期或時間不正確")
    rec = make_record(birth=b, ly=b["ly"], label=str(body.get("label") or "").strip(),
                      note=str(body.get("note") or ""), reading=str(body.get("reading") or ""),
                      facts=facts_text(chart, b["ly"]))
    await get_ziwei_store().create(rec)
    return {"id": rec["id"]}


@router.get("/master/ziwei/records")
async def ziwei_records_page(request: Request, master: dict = Depends(require_master_page)):
    recs = await get_ziwei_store().list()
    return templates.TemplateResponse(request, "master/ziwei_records.html", {"master": master, "recs": recs})


@router.get("/master/ziwei/api/records/{rid}")
async def ziwei_record_get(rid: str, master: dict = Depends(require_master_api)):
    rec = await get_ziwei_store().get(rid)
    if rec is None:
        raise HTTPException(404, "找不到此紀錄")
    return rec


@router.patch("/master/ziwei/records/{rid}")
async def ziwei_record_update(rid: str, request: Request, master: dict = Depends(require_master_api)):
    body = await request.json()
    patch = {k: str(body[k]) for k in ("label", "note", "reading") if body.get(k) is not None}
    rec = await get_ziwei_store().update(rid, patch)
    if rec is None:
        raise HTTPException(404, "找不到此紀錄")
    return {"ok": True, "updated_at": rec["updated_at"]}


@router.delete("/master/ziwei/records/{rid}")
async def ziwei_record_delete(rid: str, master: dict = Depends(require_master_api)):
    if not await get_ziwei_store().delete(rid):
        raise HTTPException(404, "找不到此紀錄")
    return {"ok": True}


@router.get("/master/ziwei/ask")
async def ziwei_ask_get(master: dict = Depends(require_master_page)):
    """直接打開網址時，導回命盤紀錄頁（起盤請用頁面上的表單）。"""
    return RedirectResponse("/master/ziwei/records", status_code=303)


@router.post("/master/ziwei/ask")
async def ziwei_ask(question: str = Form(""), g: str = Form("男"),
                    master: dict = Depends(require_master_page)):
    """占問排盤：以按下起盤的當下時間（鐘錶時、不換日）起盤，問題與盤面一起存成紀錄。"""
    q = question.strip()
    if not q:
        raise HTTPException(400, "請先輸入問題")
    if len(q) > 200:
        raise HTTPException(400, "問題請控制在 200 字以內")
    now = datetime.now(TPE)
    b = {"y": now.year, "m": now.month, "d": now.day, "h": now.hour, "mi": now.minute,
         "g": "女" if g == "女" else "男", "late": 0, "ly": now.year}
    try:
        chart = build_chart(b["y"], b["m"], b["d"], b["h"], b["mi"], gender=b["g"])
    except ValueError as e:
        raise HTTPException(400, str(e) or "日期或時間不正確")
    rec = make_record(birth=b, ly=now.year, label=q[:20], note="", reading="",
                      facts=facts_text(chart, now.year, question=q), kind="占問", question=q)
    await get_ziwei_store().create(rec)
    return RedirectResponse(f"/master/ziwei/paipan?rid={rec['id']}", status_code=303)


# ---- 紫占排盤（學生端，封測）：以問事當下的時間起盤，存成紀錄；學生只看得到自己的 ----

def _my_email(request: Request) -> str:
    me = current_student(request) or {}
    return (me.get("email") or "").strip().lower()


@router.get("/zizhan", dependencies=[Depends(require_feature("zizhan"))])
async def zizhan_page(request: Request, rid: str | None = None, mode: str = "n"):
    email = _my_email(request)
    if not rid:
        # 起盤頁：列出這位學生自己的占問紀錄（不含解讀與備註）
        mine = []
        if email:
            recs = await get_ziwei_store().list()
            mine = [r for r in recs if r.get("kind") == "占問" and r.get("owner") == email][:20]
        now = datetime.now(TPE)
        f = {"y": now.year, "m": now.month, "d": now.day, "h": now.hour, "mi": now.minute,
             "g": "男", "late": 0, "ly": now.year, "mode": "n"}
        return templates.TemplateResponse(request, "master/ziwei_paipan.html", {
            "master": None, "chart": None, "error": "", "hours": [], "liu": [], "overlay": None,
            "years": [], "f": f, "zizhan": True, "question": "", "rec": None, "rec_js": "null",
            "mine": mine})
    rec = await get_ziwei_store().get(rid)
    if rec is None or rec.get("kind") != "占問" or not email or rec.get("owner") != email:
        raise HTTPException(404, "找不到這個頁面")
    b = rec["birth"]
    # 不傳 rec：學生頁面不帶出解讀與備註
    return _render(request, b["y"], b["m"], b["d"], b["h"], b["mi"], b["g"], 0, rec["ly"], mode, None,
                   zizhan=True, question=rec["question"])


@router.post("/zizhan", dependencies=[Depends(require_feature("zizhan"))])
async def zizhan_start(request: Request, question: str = Form(""), g: str = Form("男")):
    email = _my_email(request)
    if not email:
        raise HTTPException(404, "找不到這個頁面")
    q = question.strip()
    if not q:
        raise HTTPException(400, "請先輸入問題")
    if len(q) > 200:
        raise HTTPException(400, "問題請控制在 200 字以內")
    now = datetime.now(TPE)
    b = {"y": now.year, "m": now.month, "d": now.day, "h": now.hour, "mi": now.minute,
         "g": "女" if g == "女" else "男", "late": 0, "ly": now.year}
    try:
        chart = build_chart(b["y"], b["m"], b["d"], b["h"], b["mi"], gender=b["g"])
    except ValueError as e:
        raise HTTPException(400, str(e) or "日期或時間不正確")
    rec = make_record(birth=b, ly=now.year, label=q[:20], note="", reading="",
                      facts=facts_text(chart, now.year, question=q), kind="占問", question=q, owner=email)
    await get_ziwei_store().create(rec)
    return RedirectResponse(f"/zizhan?rid={rec['id']}", status_code=303)
