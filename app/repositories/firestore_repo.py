"""Firestore 版儲存（Google Cloud 正式環境）。

結構：
  cases/{case_id}                 案件主檔
  cases/{case_id}/events/{n}      書寫事件（stroke / undo / clear），n 為奈秒時間戳
在 Cloud Run 上會自動使用服務帳號憑證，不需要金鑰檔。
"""
from __future__ import annotations

import time
from typing import Any

from google.cloud import firestore

from app.models import Case, CaseStatus, now_ms


class FirestoreCaseRepository:
    def __init__(self, project: str | None = None, database: str = "(default)") -> None:
        self.db = firestore.AsyncClient(project=project, database=database)
        self.col = self.db.collection("cases")

    async def create_case(self) -> Case:
        case = Case()
        await self.col.document(case.id).set(case.model_dump(mode="json"))
        return case

    async def get(self, case_id: str) -> Case | None:
        snap = await self.col.document(case_id).get()
        return Case(**snap.to_dict()) if snap.exists else None

    async def get_by_token(self, token: str) -> Case | None:
        q = self.col.where(filter=firestore.FieldFilter("token", "==", token)).limit(1)
        async for snap in q.stream():
            return Case(**snap.to_dict())
        return None

    async def update(self, case_id: str, **fields: Any) -> Case | None:
        ref = self.col.document(case_id)
        data = {k: (v.value if hasattr(v, "value") else v) for k, v in fields.items()}
        data["updated_at"] = now_ms()
        try:
            await ref.update(data)
        except Exception:  # 文件不存在
            return None
        return await self.get(case_id)

    async def transition(self, case_id: str, expect: CaseStatus, **fields: Any) -> Case | None:
        """Firestore transaction：讀到的狀態仍是 expect 才寫入，多個 Cloud Run 實例同時送也只會成功一次。"""
        ref = self.col.document(case_id)
        data = {k: (v.value if hasattr(v, "value") else v) for k, v in fields.items()}
        data["updated_at"] = now_ms()

        @firestore.async_transactional
        async def _run(tx) -> bool:
            snap = await ref.get(transaction=tx)
            if not snap.exists or snap.to_dict().get("status") != expect.value:
                return False
            tx.update(ref, data)
            return True

        ok = await _run(self.db.transaction())
        return await self.get(case_id) if ok else None

    async def list_cases(self, limit: int = 100, status: CaseStatus | None = None,
                         offset: int = 0) -> list[Case]:
        # status + 排序需要複合索引，deploy/gcp_setup.sh 會建立
        q = self.col
        if status is not None:
            q = q.where(filter=firestore.FieldFilter("status", "==", status.value))
        order = "answered_at" if status == CaseStatus.answered else "created_at"
        q = q.order_by(order, direction=firestore.Query.DESCENDING).offset(offset).limit(limit)
        return [Case(**s.to_dict()) async for s in q.stream()]

    async def list_by_owner(self, email: str, limit: int = 200) -> list[Case]:
        # 只用單一欄位等於條件（不需複合索引），排序在程式內做
        q = self.col.where(filter=firestore.FieldFilter("owner_email", "==", email)).limit(limit)
        cases = [Case(**s.to_dict()) async for s in q.stream()]
        return sorted(cases, key=lambda c: c.created_at, reverse=True)

    async def delete(self, case_id: str) -> bool:
        ref = self.col.document(case_id)
        if not (await ref.get()).exists:
            return False
        async for ev in ref.collection("events").stream():
            await ev.reference.delete()
        await ref.delete()
        return True

    async def append_event(self, case_id: str, event: dict) -> None:
        # 同一案件的事件由同一條 WebSocket 依序處理，用奈秒時間戳當流水號即可保證順序，
        # 不需要 transaction（避免與 stroke_count 更新互相競爭）。
        n = time.time_ns()
        ev_col = self.col.document(case_id).collection("events")
        await ev_col.document(str(n)).set({**event, "n": n})

    async def list_events(self, case_id: str) -> list[dict]:
        ev_col = self.col.document(case_id).collection("events")
        return [s.to_dict() async for s in ev_col.order_by("n").stream()]
