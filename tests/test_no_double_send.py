"""送出解讀／解卦不得重複：Master 只有一人，所以每一筆「是否已送出」都必須由伺服器確定。"""
import asyncio

import httpx
import pytest

from app.main import app
from app.models import CaseStatus
from app.repositories.memory import MemoryCaseRepository
from app.repositories.sqlite_repo import SqliteCaseRepository

READING = "【解讀】\n好好走。"


@pytest.mark.parametrize("make", ["memory", "sqlite"])
def test_transition_only_one_wins(make, tmp_path):
    async def run():
        r = MemoryCaseRepository() if make == "memory" else SqliteCaseRepository(str(tmp_path / "t.db"))
        c = await r.create_case()
        await r.update(c.id, status=CaseStatus.submitted)
        results = await asyncio.gather(*[
            r.transition(c.id, CaseStatus.submitted, status=CaseStatus.answered, revision=n + 1)
            for n in range(10)])
        assert sum(x is not None for x in results) == 1          # 十個同時送，只有一個成功
        assert (await r.get(c.id)).status == CaseStatus.answered
        assert await r.transition(c.id, CaseStatus.submitted, status=CaseStatus.answered) is None
        assert await r.transition("不存在", CaseStatus.submitted, status=CaseStatus.answered) is None
    asyncio.run(run())


def test_concurrent_api_send_writes_and_notifies_once(monkeypatch):
    """兩個請求同時按送出：只有一個 200，另一個 409；revision 只加 1，只通知／寄信一次。"""
    from fastapi.testclient import TestClient
    from app.repositories import get_repo
    from app.services import notify

    sent = []

    async def fake_notify(case, base):
        sent.append(case.id)
        return True, ""
    monkeypatch.setattr(notify, "notify_student_answered", fake_notify)

    sync = TestClient(app)
    sync.post("/master/login", data={"password": "test-pw"}, follow_redirects=False)

    async def run():
        repo = get_repo()
        c = await repo.create_case()
        await repo.update(c.id, status=CaseStatus.submitted, owner_email="s@example.com")
        cookies = dict(sync.cookies.items())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t", cookies=cookies) as ac:
            rs = await asyncio.gather(*[
                ac.post(f"/api/master/cases/{c.id}/answer",
                        json={"body": READING, "email_student": True}) for _ in range(5)])
        codes = sorted(r.status_code for r in rs)
        assert codes == [200, 409, 409, 409, 409], codes
        loser = next(r for r in rs if r.status_code == 409)
        assert "不會重複送出" in loser.json()["detail"]
        got = await repo.get(c.id)
        assert got.status == CaseStatus.answered and got.revision == 1
        assert sent == [c.id]                                    # 信只寄一次
    asyncio.run(run())
