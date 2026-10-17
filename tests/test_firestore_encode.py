"""Firestore 不允許陣列裡再放陣列（nested arrays）。筆畫的 points 必須在寫入前編碼，讀取時還原。"""
import asyncio

from app.repositories.firestore_repo import FirestoreCaseRepository, _decode_event, _encode_event

STROKE = {"type": "stroke", "seq": 1, "t0": 1000, "ts": 2000,
          "points": [[0.1, 0.1, 0, 0.5], [0.9, 0.2, 40, 0.5]]}


def _has_nested_array(d: dict) -> bool:
    return any(isinstance(v, list) and any(isinstance(x, list) for x in v) for v in d.values())


def test_encoded_stroke_has_no_nested_arrays_and_roundtrips():
    enc = _encode_event(STROKE)
    assert not _has_nested_array(enc)
    assert isinstance(enc["points"], str)
    assert _decode_event(enc) == STROKE


def test_non_stroke_events_unchanged():
    undo = {"type": "undo", "ts": 5}
    assert _encode_event(undo) == undo
    assert _decode_event(undo) == undo


def test_legacy_unencoded_points_still_readable():
    assert _decode_event(STROKE) == STROKE


class _Ref:
    """假的 Firestore 文件／集合參考，只實作 append_event 與 list_events 用到的部分。"""

    def __init__(self, store, key):
        self.store, self.key = store, key

    def document(self, k):
        return _Ref(self.store, self.key + (k,))

    def collection(self, name):
        return _Ref(self.store, self.key + (name,))

    def order_by(self, _field):
        return self

    async def set(self, data):
        assert not _has_nested_array(data), "寫入 Firestore 的資料含有巢狀陣列"
        self.store[self.key] = data

    async def stream(self):
        for key in sorted(self.store, key=lambda k: self.store[k]["n"]):
            if key[:-1] == self.key:
                yield _Snap(self.store[key])


class _Snap:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)


def test_events_appended_in_same_clock_tick_are_not_overwritten(monkeypatch):
    """Windows 的時鐘解析度較粗，模擬連續兩次取得相同時間，兩筆事件都必須保留。"""
    import app.repositories.firestore_repo as mod
    monkeypatch.setattr(mod.time, "time_ns", lambda: 1_700_000_000_000_000_000)
    repo = FirestoreCaseRepository.__new__(FirestoreCaseRepository)
    store: dict = {}
    repo.col = _Ref(store, ("cases",))

    async def run():
        await repo.append_event("c1", STROKE)
        await repo.append_event("c1", {"type": "undo", "ts": 9})
        await repo.append_event("c1", {"type": "clear", "ts": 10})
        return await repo.list_events("c1")

    assert [e["type"] for e in asyncio.run(run())] == ["stroke", "undo", "clear"]


def test_append_and_list_events_through_repo():
    repo = FirestoreCaseRepository.__new__(FirestoreCaseRepository)   # 不建立真的 Firestore 連線
    store: dict = {}
    repo.col = _Ref(store, ("cases",))

    async def run():
        await repo.append_event("c1", STROKE)
        await repo.append_event("c1", {"type": "clear", "ts": 9})
        return await repo.list_events("c1")

    events = asyncio.run(run())
    assert [e["type"] for e in events] == ["stroke", "clear"]
    assert events[0]["points"] == STROKE["points"]
    assert all(e["n"] > 0 for e in events)
