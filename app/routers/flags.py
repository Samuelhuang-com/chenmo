"""老師後台：功能開關（封測名單）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import require_master_page
from app.services.features import FEATURES, env_all, env_emails, get_flag, save_flag
from app.templating import templates

router = APIRouter()


def _check(name: str) -> None:
    if name not in FEATURES:
        raise HTTPException(404, "沒有這個功能")


@router.get("/master/flags")
async def flags_page(request: Request, msg: str = "", master: dict = Depends(require_master_page)):
    items = []
    for name, label in FEATURES.items():
        flag = await get_flag(name, fresh=True)
        items.append({"name": name, "label": label, "flag": flag,
                      "env_emails": env_emails(name), "env_all": env_all(name)})
    return templates.TemplateResponse(request, "master/flags.html",
                                      {"master": master, "items": items, "msg": msg})


@router.post("/master/flags/{name}/emails")
async def add_emails(name: str, emails: str = Form(""), master: dict = Depends(require_master_page)):
    _check(name)
    flag = await get_flag(name, fresh=True)
    new = [e for e in emails.replace("，", ",").replace("\n", ",").replace(" ", ",").split(",") if e.strip()]
    bad = [e for e in new if "@" not in e]
    flag.allow_emails = flag.allow_emails + new
    await save_flag(flag, master.get("email", ""))
    msg = "已加入" if not bad else f"已加入；略過格式不對的：{'、'.join(bad)}"
    return RedirectResponse(f"/master/flags?msg={msg}", status_code=303)


@router.post("/master/flags/{name}/remove")
async def remove_email(name: str, email: str = Form(...), master: dict = Depends(require_master_page)):
    _check(name)
    flag = await get_flag(name, fresh=True)
    flag.allow_emails = [e for e in flag.allow_emails if e != email.strip().lower()]
    await save_flag(flag, master.get("email", ""))
    return RedirectResponse("/master/flags?msg=已移除", status_code=303)


@router.post("/master/flags/{name}/all")
async def set_all(name: str, on: str = Form("0"), master: dict = Depends(require_master_page)):
    _check(name)
    flag = await get_flag(name, fresh=True)
    flag.enabled_for_all = on == "1"
    await save_flag(flag, master.get("email", ""))
    return RedirectResponse(f"/master/flags?msg={'已正式開放' if flag.enabled_for_all else '已改回封測'}",
                            status_code=303)
