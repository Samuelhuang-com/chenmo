"""送出前確認（第一階段）：字不符要明確確認；以及個資不得外露給問事者端。"""
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import CaseStatus
from app.repositories import get_repo

client = TestClient(app)


def _master():
    m = TestClient(app)
    m.post("/master/login", data={"password": "test-pw"}, follow_redirects=False)
    return m


def _case(**fields):
    token = client.post("/api/cases").json()["token"]
    repo = get_repo()
    c = asyncio.run(repo.get_by_token(token))
    c = asyncio.run(repo.update(c.id, status=CaseStatus.submitted, question="問工作", **fields))
    return c


def test_char_mismatch_needs_explicit_ack():
    m = _master()
    c = _case(char="考")
    body = "【此字】\n行　注音 ㄒㄧㄥˊ\n\n【解讀】\n往前走。"
    r = m.post(f"/api/master/cases/{c.id}/answer", json={"body": body})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "char_mismatch" and d["asked"] == "考" and d["section"] == "行"
    assert asyncio.run(get_repo().get(c.id)).status == CaseStatus.submitted      # 沒有送出
    r = m.post(f"/api/master/cases/{c.id}/answer", json={"body": body, "ack_char_mismatch": True})
    assert r.status_code == 200                                                    # 老師確認後可送


def test_matching_or_unknown_char_is_not_blocked():
    m = _master()
    ok = _case(char="考")
    assert m.post(f"/api/master/cases/{ok.id}/answer",
                  json={"body": "【此字】\n考　注音\n\n【解讀】\n穩。"}).status_code == 200
    nochar = _case()     # 問事者沒填字：沒有比對基準，不擋
    assert m.post(f"/api/master/cases/{nochar.id}/answer",
                  json={"body": "【此字】\n行\n\n【解讀】\n好。"}).status_code == 200
    nosec = _case(char="考")   # 解字稿沒有【此字】段落：不擋
    assert m.post(f"/api/master/cases/{nosec.id}/answer",
                  json={"body": "【解讀】\n好。"}).status_code == 200


def test_yao_case_not_affected():
    m = _master()
    c = _case(kind="yao", char="考")
    assert m.post(f"/api/master/cases/{c.id}/answer",
                  json={"body": "【此字】\n行\n\n【解讀】\n好。"}).status_code == 200


def test_confirm_dialog_never_uses_innerhtml():
    js = Path("app/static/js/confirm-send.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js     # 暱稱、問題是學生輸入的字串
    assert client.get("/static/js/confirm-send.js").status_code == 200


def test_student_side_never_exposes_private_fields():
    m = _master()
    c = _case(char="考", owner_email="secret.student@example.com", owner_name="祕密本名",
              nickname="小王", draft="系統草稿SECRETDRAFT")
    m.post(f"/api/master/cases/{c.id}/answer",
           json={"body": "【此字】\n考\n\n【五行】\n老師筆記NOTE123\n\n【解讀】\n穩穩來。"})
    api = client.get(f"/api/cases/{c.token}")
    page = client.get(f"/c/{c.token}")
    for blob in (api.text, page.text):
        for secret in ("secret.student@example.com", "祕密本名", "NOTE123", "SECRETDRAFT", c.id):
            assert secret not in blob, secret
    assert "穩穩來" in page.text
    # 沒登入不能讀老師端資料
    assert client.get(f"/api/master/cases/{c.id}").status_code == 401
    assert client.get("/api/master/cases").status_code == 401
