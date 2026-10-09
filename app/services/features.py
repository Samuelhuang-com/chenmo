"""功能開關（Feature Flag）：新功能封測期間，只有白名單 Email 看得到。

規則（依序判斷，任一成立就開放）：
  1. 老師（已登入老師端）一律可見
  2. 該功能已「正式開放」（enabled_for_all = true）
  3. 學生已用 Google 登入，且 Email 在白名單內

白名單有兩個來源，取聯集：
  - 環境變數 FEATURE_<NAME>_EMAILS（逗號分隔，部署時預先放入，例如自己的信箱）
  - 老師後台 /master/flags 新增的名單（存在資料庫，不必重新部署）

不在名單內的人：頁面與 API 一律回 404，入口也不會出現，看不出有這個功能。
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.config import get_settings
from app.models import now_ms

# 目前有開關的功能。key 用在網址、資料庫、模板（'yao' in request.state.features）
FEATURES: dict[str, str] = {
    "yao": "六龍問爻",
}

CACHE_SECONDS = 60


@dataclass
class Flag:
    name: str
    enabled_for_all: bool = False
    allow_emails: list[str] = field(default_factory=list)
    updated_at: int = 0
    updated_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"enabled_for_all": self.enabled_for_all, "allow_emails": self.allow_emails,
                "updated_at": self.updated_at, "updated_by": self.updated_by}

    @classmethod
    def from_dict(cls, name: str, d: dict | None) -> "Flag":
        d = d or {}
        return cls(name=name, enabled_for_all=bool(d.get("enabled_for_all", False)),
                   allow_emails=_clean_emails(d.get("allow_emails") or []),
                   updated_at=int(d.get("updated_at") or 0), updated_by=str(d.get("updated_by") or ""))


def _clean_emails(items) -> list[str]:
    out: list[str] = []
    for e in items:
        e = str(e).strip().lower()
        if e and "@" in e and e not in out:
            out.append(e)
    return out


def env_emails(name: str) -> list[str]:
    return _clean_emails(os.environ.get(f"FEATURE_{name.upper()}_EMAILS", "").split(","))


def env_all(name: str) -> bool:
    return os.environ.get(f"FEATURE_{name.upper()}_ALL", "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------- 儲存（與案件同一個後端） ----------------
class _MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    async def get(self, name: str) -> dict | None:
        return self.data.get(name)

    async def put(self, name: str, data: dict) -> None:
        self.data[name] = dict(data)


class _SqliteStore:
    def __init__(self, path: str) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(p), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS feature_flags (name TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()

    async def get(self, name: str) -> dict | None:
        row = self.db.execute("SELECT data FROM feature_flags WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    async def put(self, name: str, data: dict) -> None:
        self.db.execute("INSERT INTO feature_flags(name, data) VALUES (?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET data=excluded.data",
                        (name, json.dumps(data, ensure_ascii=False)))
        self.db.commit()


class _FirestoreStore:
    """Firestore：feature_flags/{name}"""

    def __init__(self, project: str | None, database: str) -> None:
        from google.cloud import firestore
        self.col = firestore.AsyncClient(project=project, database=database).collection("feature_flags")

    async def get(self, name: str) -> dict | None:
        snap = await self.col.document(name).get()
        return snap.to_dict() if snap.exists else None

    async def put(self, name: str, data: dict) -> None:
        await self.col.document(name).set(data)


_store = None


def _get_store():
    global _store
    if _store is None:
        s = get_settings()
        if s.repo_backend == "firestore":
            _store = _FirestoreStore(s.gcp_project, s.firestore_database)
        elif s.repo_backend == "sqlite":
            _store = _SqliteStore(s.sqlite_path)
        else:
            _store = _MemoryStore()
    return _store


# ---------------- 讀取（快取 60 秒） ----------------
_cache: dict[str, tuple[float, Flag]] = {}
_lock = asyncio.Lock()


async def get_flag(name: str, fresh: bool = False) -> Flag:
    """資料庫裡的設定（不含環境變數）。讀取失敗時視為「未開放」，不會讓整站壞掉。"""
    hit = _cache.get(name)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        flag = Flag.from_dict(name, await _get_store().get(name))
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("讀取功能開關失敗：%s", name)
        flag = hit[1] if hit else Flag(name=name)
    _cache[name] = (time.monotonic(), flag)
    return flag


async def save_flag(flag: Flag, by: str) -> Flag:
    async with _lock:
        flag.allow_emails = _clean_emails(flag.allow_emails)
        flag.updated_at = now_ms()
        flag.updated_by = by
        await _get_store().put(flag.name, flag.to_dict())
        _cache[flag.name] = (time.monotonic(), flag)
    return flag


def reset_cache() -> None:
    _cache.clear()


# ---------------- 判斷 ----------------
def _identity(session) -> tuple[bool, str]:
    """（是否老師, 學生 Email）。學生 Email 只來自已驗證的 Google 登入。"""
    is_master = bool(session.get("master"))
    student = session.get("student") or {}
    return is_master, (student.get("email") or "").strip().lower()


async def enabled_for(name: str, session) -> bool:
    if name not in FEATURES:
        return False
    is_master, email = _identity(session)
    if is_master or env_all(name):
        return True
    flag = await get_flag(name)
    if flag.enabled_for_all:
        return True
    return bool(email) and (email in flag.allow_emails or email in env_emails(name))


async def enabled_set(session) -> set[str]:
    return {n for n in FEATURES if await enabled_for(n, session)}


def require_feature(name: str):
    """路由用：不在名單內回 404（不是 403），不透露功能存在。"""
    async def _dep(request: Request) -> None:
        if not await enabled_for(name, request.session):
            raise HTTPException(404, "找不到這個頁面")
    return _dep


async def ws_feature_allowed(ws, name: str) -> bool:
    """WebSocket 用（HTTP middleware 不會經過 WebSocket）。"""
    session = ws.session if "session" in ws.scope else {}
    return await enabled_for(name, session)
