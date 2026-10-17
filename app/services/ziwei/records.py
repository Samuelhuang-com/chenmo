"""紫微命盤紀錄：把生辰、流年、排盤事實、AI 解讀與備註存成一筆，可隨時讀取、修改、刪除。

- 正式站（REPO_BACKEND=firestore）：Firestore 集合 ziwei_records
- 本機（其他情況）：同一個 sqlite 檔案，另開 ziwei_records 表
紀錄以生辰為準；要改生辰請另存新紀錄，避免同一筆資料對不上。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings

COLLECTION = "ziwei_records"


def _now_ms() -> int:
    return int(time.time() * 1000)


def make_record(birth: dict, ly: int, label: str, note: str, reading: str, facts: str,
                kind: str = "本命", question: str = "", owner: str = "") -> dict:
    now = _now_ms()
    return {
        "id": uuid.uuid4().hex, "created_at": now, "updated_at": now,
        "birth": birth, "ly": ly, "label": label, "note": note,
        "reading": reading, "facts": facts,
        "kind": kind, "question": question, "owner": owner,
        "asked_at": now if kind == "占問" else None,
    }


class SqliteZiweiStore:
    def __init__(self, path: str) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(p), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS ziwei_records ("
                        "id TEXT PRIMARY KEY, updated_at INTEGER NOT NULL, data TEXT NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_ziwei_updated ON ziwei_records(updated_at)")
        self.db.commit()
        self.lock = asyncio.Lock()

    def _write(self, rec: dict) -> None:
        self.db.execute(
            "INSERT INTO ziwei_records(id, updated_at, data) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, data=excluded.data",
            (rec["id"], rec["updated_at"], json.dumps(rec, ensure_ascii=False)))
        self.db.commit()

    async def create(self, rec: dict) -> dict:
        async with self.lock:
            self._write(rec)
        return rec

    async def get(self, rid: str) -> dict | None:
        row = self.db.execute("SELECT data FROM ziwei_records WHERE id=?", (rid,)).fetchone()
        return json.loads(row[0]) if row else None

    async def list(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute(
            "SELECT data FROM ziwei_records ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    async def update(self, rid: str, patch: dict[str, Any]) -> dict | None:
        async with self.lock:
            rec = await self.get(rid)
            if rec is None:
                return None
            rec.update(patch)
            rec["updated_at"] = _now_ms()
            self._write(rec)
            return rec

    async def delete(self, rid: str) -> bool:
        async with self.lock:
            cur = self.db.execute("DELETE FROM ziwei_records WHERE id=?", (rid,))
            self.db.commit()
            return cur.rowcount > 0


class FirestoreZiweiStore:
    def __init__(self, project: str | None = None, database: str = "(default)") -> None:
        from google.cloud import firestore
        self._fs = firestore
        self.db = firestore.AsyncClient(project=project, database=database)
        self.col = self.db.collection(COLLECTION)

    async def create(self, rec: dict) -> dict:
        await self.col.document(rec["id"]).set(rec)
        return rec

    async def get(self, rid: str) -> dict | None:
        snap = await self.col.document(rid).get()
        return snap.to_dict() if snap.exists else None

    async def list(self, limit: int = 200) -> list[dict]:
        q = self.col.order_by("updated_at", direction=self._fs.Query.DESCENDING).limit(limit)
        return [d.to_dict() async for d in q.stream()]

    async def update(self, rid: str, patch: dict[str, Any]) -> dict | None:
        ref = self.col.document(rid)
        snap = await ref.get()
        if not snap.exists:
            return None
        patch = {**patch, "updated_at": _now_ms()}
        await ref.update(patch)
        return {**snap.to_dict(), **patch}

    async def delete(self, rid: str) -> bool:
        ref = self.col.document(rid)
        if not (await ref.get()).exists:
            return False
        await ref.delete()
        return True


@lru_cache
def get_ziwei_store():
    s = get_settings()
    if s.repo_backend == "firestore":
        return FirestoreZiweiStore(project=s.gcp_project, database=s.firestore_database)
    return SqliteZiweiStore(s.sqlite_path)
