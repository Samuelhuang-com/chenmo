"""老師端：紫微斗數排盤工具（封測）。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from app.auth import require_master_api, require_master_page
from app.services.features import require_feature
from app.services.ziwei import build_chart
from app.services.ziwei.chart import liunian_overlay, liunian_rows
from app.services.ziwei.chart import BRANCHES
from app.templating import templates

router = APIRouter()
TPE = timezone(timedelta(hours=8))


def _render(request: Request, y, m, d, h, mi, g, late, ly, mode, master):
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
    years = list(range(now.year - 20, now.year + 31))
    return templates.TemplateResponse(request, "master/ziwei_paipan.html", {
        "master": master, "chart": chart, "error": error, "hours": hours, "liu": liu,
        "overlay": overlay, "years": years,
        "f": {"y": y, "m": m, "d": d, "h": h, "mi": mi, "g": g, "late": late, "ly": ly, "mode": mode}})


@router.get("/master/ziwei/paipan")
async def ziwei_paipan(request: Request, y: int | None = None, m: int = 1, d: int = 1,
                       h: int = 12, mi: int = 0, g: str = "男", late: int = 0,
                       ly: int | None = None, mode: str = "n",
                       master: dict = Depends(require_master_page)):
    """老師端排盤。"""
    return _render(request, y, m, d, h, mi, g, late, ly, mode, master)


@router.get("/ziwei", dependencies=[Depends(require_feature("ziwei"))])
async def ziwei_student(request: Request, y: int | None = None, m: int = 1, d: int = 1,
                        h: int = 12, mi: int = 0, g: str = "男", late: int = 0,
                        ly: int | None = None, mode: str = "n"):
    """學生端（封測）：只有開關允許的 Email 看得到，不在名單內回 404。"""
    return _render(request, y, m, d, h, mi, g, late, ly, mode, None)


@router.post("/master/ziwei/ai")
async def ziwei_ai(y: int | None = None, m: int | None = None, d: int | None = None, h: int = 12,
                   mi: int = 0, g: str = "男", late: int = 0, ly: int | None = None,
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
    text, msg = await interpret(facts_text(chart, ly))
    return {"text": text, "msg": msg}

