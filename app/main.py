"""辰墨軒 — FastAPI 進入點。

本機啟動：uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired
from app.config import get_settings
from app.routers import api, flags, master, pages, pwa, ws, yao
from app.services.features import enabled_set
from app.templating import templates

logging.basicConfig(level=logging.INFO)

settings = get_settings()
app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)


# 功能開關：算出這個人看得到哪些封測功能，模板用 'yao' in request.state.features 判斷。
# 必須在 SessionMiddleware 之前註冊（後註冊的在外層），才能讀到 request.session。
@app.middleware("http")
async def feature_flags(request: Request, call_next):
    try:
        request.state.features = await enabled_set(request.session)
    except Exception:  # noqa: BLE001  開關壞了也不能讓整站壞掉
        request.state.features = set()
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="chenmo_session",
    max_age=60 * 60 * 24 * 14,   # 14 天，PWA 不必常常重新登入
    same_site="lax",
    https_only=settings.secure_cookies,
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

app.include_router(pages.router)
app.include_router(api.router)
app.include_router(master.router)
app.include_router(ws.router)
app.include_router(pwa.router)
app.include_router(yao.router)
app.include_router(flags.router)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/master/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html",
                                      {"code": exc.status_code, "message": exc.detail},
                                      status_code=exc.status_code)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp
