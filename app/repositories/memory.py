"""記憶體版儲存（本機開發與測試用；重啟即消失）。"""
from __future__ import annotations

import asyncio
from typing import Any

from app.models import Case, CaseStatus, now_ms


class MemoryCaseRepository:
    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._by_token: dict[str, str] = {}
        self._events: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()

    async def create_case(self) -> Case:
        case = Case()
        async with self._lock:
            self._cases[case.id] = case
            self._by_token[case.token] = case.id
            self._events[case.id] = []
        return case.model_copy()

    async def get(self, case_id: str) -> Case | None:
        c = self._cases.get(case_id)
        return c.model_copy() if c else None

    async def get_by_token(self, token: str) -> Case | None:
        cid = self._by_token.get(token)
        return await self.get(cid) if cid else None

    async def update(self, case_id: str, **fields: Any) -> Case | None:
        async with self._lock:
            c = self._cases.get(case_id)
            if not c:
                return None
            updated = c.model_copy(update={**fields, "updated_at": now_ms()})
            self._cases[case_id] = updated
            return updated.model_copy()

    async def list_cases(self, limit: int = 100, status: CaseStatus | None = None,
                         offset: int = 0) -> list[Case]:
        cases = [c for c in self._cases.values() if status is None or c.status == status]
        key = (lambda c: c.answered_at or 0) if status == CaseStatus.answered else (lambda c: c.created_at)
        cases.sort(key=key, reverse=True)
        return [c.model_copy() for c in cases[offset:offset + limit]]

    async def list_by_owner(self, email: str, limit: int = 200) -> list[Case]:
        cases = [c for c in self._cases.values() if email and c.owner_email == email]
        cases.sort(key=lambda c: c.created_at, reverse=True)
        return [c.model_copy() for c in cases[:limit]]

    async def append_event(self, case_id: str, event: dict) -> None:
        async with self._lock:
            evs = self._events.setdefault(case_id, [])
            evs.append({**event, "n": len(evs)})

    async def list_events(self, case_id: str) -> list[dict]:
        return list(self._events.get(case_id, []))
