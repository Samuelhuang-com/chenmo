"""老師端登入：Google 帳號（OAuth，由 Google Cloud Console 建立用戶端）或開發用密碼。"""
from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket

from app.config import get_settings

SESSION_KEY = "master"
STUDENT_KEY = "student"


def current_student(request) -> dict | None:
    return request.session.get(STUDENT_KEY)

_oauth = None


def get_oauth():
    """延遲建立 Authlib OAuth 用戶端（只有設定了 Google 用戶端 ID 才會用到）。"""
    global _oauth
    s = get_settings()
    if not s.google_login_enabled:
        return None
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth

        _oauth = OAuth()
        _oauth.register(
            name="google",
            client_id=s.google_client_id,
            client_secret=s.google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return _oauth


def current_master(request: Request) -> dict | None:
    return request.session.get(SESSION_KEY)


def require_master_api(request: Request) -> dict:
    m = current_master(request)
    if not m:
        raise HTTPException(status_code=401, detail="請先登入老師端")
    return m


class LoginRequired(Exception):
    """頁面用：未登入時導向登入頁。"""


def require_master_page(request: Request) -> dict:
    m = current_master(request)
    if not m:
        raise LoginRequired()
    return m


def ws_master(ws: WebSocket) -> dict | None:
    return ws.session.get(SESSION_KEY) if "session" in ws.scope else None
