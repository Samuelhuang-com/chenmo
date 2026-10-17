"""命盤紀錄儲存：建立、讀取、修改、刪除（sqlite 版）。"""
import asyncio

from app.services.ziwei.records import SqliteZiweiStore, make_record


def test_record_roundtrip(tmp_path):
    store = SqliteZiweiStore(str(tmp_path / "t.db"))
    birth = {"y": 1964, "m": 9, "d": 6, "h": 8, "mi": 15, "g": "男", "late": 0}
    rec = make_record(birth=birth, ly=2026, label="測試", note="", reading="", facts="x")

    async def run():
        await store.create(rec)
        assert (await store.get(rec["id"]))["label"] == "測試"
        upd = await store.update(rec["id"], {"note": "備註一", "reading": "解讀"})
        assert upd["note"] == "備註一"
        assert (await store.get(rec["id"]))["reading"] == "解讀"
        assert len(await store.list()) == 1
        assert await store.delete(rec["id"]) is True
        assert await store.get(rec["id"]) is None
        assert await store.update("missing", {"note": "x"}) is None

    asyncio.run(run())


def test_ask_record_keeps_question(tmp_path):
    store = SqliteZiweiStore(str(tmp_path / "t2.db"))
    rec = make_record(birth={"y": 2026, "m": 10, "d": 14, "h": 10, "mi": 58, "g": "男", "late": 0},
                      ly=2026, label="占問", note="", reading="", facts="x",
                      kind="占問", question="這次面試會順利嗎？")

    async def run():
        await store.create(rec)
        got = await store.get(rec["id"])
        assert got["kind"] == "占問"
        assert got["question"] == "這次面試會順利嗎？"
        assert got["asked_at"]

    asyncio.run(run())
