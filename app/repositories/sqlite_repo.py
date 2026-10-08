"""SQLite 版儲存（本機使用，資料存在檔案中，重啟不會消失）。

預設檔案：~/.chenmo/chenmo.db（Windows 為 C:\\Users\\<你>\\.chenmo\\chenmo.db）
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import Case, CaseStatus, now_ms

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  answered_at INTEGER,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cases_status ON cases(status, answered_at);
CREATE TABLE IF NOT EXISTS events (
  n INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_case ON events(case_id, n);
"""


class SqliteCaseRepository:
    def __init__(self, path: str) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(p)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = asyncio.Lock()

    # 內部工具 -------------------------------------------------
    def _save(self, c: Case) -> None:
        self.db.execute(
            "INSERT INTO cases(id, token, status, created_at, answered_at, data) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, answered_at=excluded.answered_at, "
            "data=excluded.data",
            (c.id, c.token, c.status.value, c.created_at, c.answered_at, c.model_dump_json()))
        self.db.commit()

    @staticmethod
    def _row(row) -> Case | None:
        return Case.model_validate_json(row[0]) if row else None

    # 介面 -----------------------------------------------------
    async def create_case(self) -> Case:
        c = Case()
        async with self.lock:
            self._save(c)
        return c

    async def get(self, case_id: str) -> Case | None:
        return self._row(self.db.execute("SELECT data FROM cases WHERE id=?", (case_id,)).fetchone())

    async def get_by_token(self, token: str) -> Case | None:
        return self._row(self.db.execute("SELECT data FROM cases WHERE token=?", (token,)).fetchone())

    async def update(self, case_id: str, **fields: Any) -> Case | None:
        async with self.lock:
            c = await self.get(case_id)
            if not c:
                return None
            c = c.model_copy(update={**fields, "updated_at": now_ms()})
            c = Case.model_validate(c.model_dump())  # 確保 status 等欄位型別正確
            self._save(c)
            return c

    async def list_cases(self, limit: int = 100, status: CaseStatus | None = None,
                         offset: int = 0) -> list[Case]:
        if status == CaseStatus.answered:
            rows = self.db.execute(
                "SELECT data FROM cases WHERE status=? ORDER BY answered_at DESC LIMIT ? OFFSET ?",
                (status.value, limit, offset)).fetchall()
        elif status:
            rows = self.db.execute(
                "SELECT data FROM cases WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status.value, limit, offset)).fetchall()
        else:
            rows = self.db.execute("SELECT data FROM cases ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                   (limit, offset)).fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    async def list_by_owner(self, email: str, limit: int = 200) -> list[Case]:
        rows = self.db.execute(
            "SELECT data FROM cases WHERE json_extract(data, '$.owner_email') = ? "
            "ORDER BY created_at DESC LIMIT ?", (email, limit)).fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    async def append_event(self, case_id: str, event: dict) -> None:
        async with self.lock:
            self.db.execute("INSERT INTO events(case_id, data) VALUES (?, ?)",
                            (case_id, json.dumps(event, ensure_ascii=False)))
            self.db.commit()

    async def list_events(self, case_id: str) -> list[dict]:
        rows = self.db.execute("SELECT n, data FROM events WHERE case_id=? ORDER BY n", (case_id,))
        return [{**json.loads(d), "n": n} for n, d in rows.fetchall()]
