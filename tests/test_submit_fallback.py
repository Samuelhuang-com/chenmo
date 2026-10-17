"""送出時的筆跡備援：建立案件時網路不穩、筆畫沒送到伺服器，送出仍應以畫面上的字為準。"""
from fastapi.testclient import TestClient

from app.main import app
from app.services.strokes import clean_strokes

client = TestClient(app)
PROFILE = {"birth_year": 75, "gender": "男", "nickname": "測試"}
STROKES = [{"t0": 1000, "points": [[0.1, 0.1, 0, 0.5], [0.9, 0.1, 40, 0.5]]}]


def _new_case():
    return client.post("/api/cases").json()["token"]


def test_submit_falls_back_to_client_strokes_when_server_has_none():
    token = _new_case()   # 伺服器完全沒收到任何筆畫
    r = client.post(f"/api/cases/{token}/submit",
                    json={"question": "問工作", "char": "行", **PROFILE, "strokes": STROKES})
    assert r.status_code == 200
    data = client.get(f"/api/cases/{token}").json()
    assert len(data["strokes"]) == 1
    assert data["case"]["stroke_count"] == 1
    assert data["strokes"][0]["points"][1][:2] == [0.9, 0.1]


def test_submit_without_any_strokes_still_rejected():
    token = _new_case()
    r = client.post(f"/api/cases/{token}/submit", json={"question": "問工作", "char": "行", **PROFILE, "strokes": []})
    assert r.status_code == 422
    assert "請先在字格中寫下一個字" in r.json()["detail"]


def test_server_strokes_take_precedence_over_client_copy():
    token = _new_case()
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        ws.send_json({"type": "stroke_start", "seq": 1, "t0": 1000})
        ws.send_json({"type": "stroke_points", "seq": 1, "points": [[0.2, 0.2, 0]]})
        ws.send_json({"type": "stroke_end", "seq": 1})
        ws.send_json({"type": "sync", "id": 1})
        assert ws.receive_json() == {"type": "synced", "id": 1}
    r = client.post(f"/api/cases/{token}/submit",
                    json={"question": "問工作", "char": "行", **PROFILE, "strokes": STROKES + STROKES})
    assert r.status_code == 200
    data = client.get(f"/api/cases/{token}").json()
    assert len(data["strokes"]) == 1                      # 以伺服器收到的為準，備份不重複加入
    assert data["strokes"][0]["points"] == [[0.2, 0.2, 0, 0.5]]


def test_clean_strokes_drops_malformed_and_clamps():
    raw = [
        {"t0": 5, "points": [[0.5, 0.5, 0, 0.5]]},
        {"t0": 6, "points": []},                          # 沒有點
        "not-a-stroke",                                    # 型別錯誤
        {"t0": "x", "points": [[2, -1, 0, 9]]},            # t0 不是數字；座標夾在 0–1
        {"t0": 7, "points": [["a", "b", 0]]},              # 點的內容不合法
    ]
    out = clean_strokes(raw, max_strokes=10, max_points=100)
    assert [s["t0"] for s in out] == [5, 0]
    assert out[1]["points"] == [[1.0, 0.0, 0, 1.0]]
    assert clean_strokes(None, 10, 100) == []
    assert len(clean_strokes([{"t0": 1, "points": [[0, 0, 0]]}] * 5, max_strokes=2, max_points=100)) == 2
