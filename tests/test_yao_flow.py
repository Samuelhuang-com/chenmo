"""六龍問爻完整流程：開始起卦 → 擲六次 → 呈送 → 老師解卦 → 問事者看到。"""
import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.services import features
from tests.test_features import master_client, reset, student_client

START = {"question": "這次面試結果如何？", "birth_year": 75, "gender": "女", "nickname": "Amy",
         "asked_for": "自己", "category": "事業"}


def whitelisted() -> TestClient:
    reset(["tester@gmail.com"])
    return student_client("tester@gmail.com")


def start(c, **extra) -> str:
    r = c.post("/api/yao/cases", json={**START, **extra})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_needs_feature():
    reset()
    assert TestClient(app).post("/api/yao/cases", json=START).status_code == 404


def test_full_flow():
    c, m = whitelisted(), master_client()
    token = start(c)
    case_id = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]

    # 擲錢前不能呈送
    assert c.post(f"/api/yao/cases/{token}/submit").status_code == 422
    vals = []
    for i in range(6):
        r = c.post(f"/api/yao/cases/{token}/toss", json={"shake_ms": 800}).json()
        assert r["n"] == i + 1 and r["value"] in (6, 7, 8, 9) and len(r["coins"]) == 3
        assert r["value"] == sum(3 if x == "背" else 2 for x in r["coins"])
        vals.append(r["value"])
    assert r["values"] == vals and ("→" in r["gua"] or "靜卦" in r["gua"])
    assert c.post(f"/api/yao/cases/{token}/toss", json={}).status_code == 409   # 第七次

    # 老師端即時看得到卦盤
    page = m.get(f"/master/yao/case/{case_id}")
    assert page.status_code == 200 and "擲錢紀錄" in page.text and "卦盤" in page.text

    assert c.post(f"/api/yao/cases/{token}/submit").json()["url"] == f"/c/{token}"
    view = c.get(f"/c/{token}").text
    assert "卦已呈老師案前" in view and "本卦" in view
    assert "六神" not in view and "伏神" not in view          # 問事者看不到完整卦盤

    # 老師送出解卦（沿用問字的 API）
    r = m.post(f"/api/master/cases/{case_id}/answer",
               json={"body": "白話解讀", "reading_html": "<p>Amy 好，這一卦不錯。</p>"})
    assert r.status_code == 200, r.text
    view = c.get(f"/c/{token}").text
    assert "老師解卦" in view and "這一卦不錯" in view and "/yao?follow=" in view


def test_manual_coins():
    c = whitelisted()
    token = start(c)
    got = [c.post(f"/api/yao/cases/{token}/toss", json={"backs": b}).json()["value"] for b in (0, 1, 2, 3, 1, 1)]
    assert got == [6, 7, 8, 9, 7, 7]


def test_clear_is_recorded():
    c, m = whitelisted(), master_client()
    token = start(c)
    for _ in range(3):
        c.post(f"/api/yao/cases/{token}/toss", json={"backs": 1})
    c.post(f"/api/yao/cases/{token}/clear")
    data = c.get(f"/api/cases/{token}").json()["case"]
    assert data["yao_values"] == []
    case_id = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    assert "清除重擲 1 次" in m.get(f"/master/yao/case/{case_id}").text


def test_redo_replaces_old_case():
    c, m = whitelisted(), master_client()
    token = start(c)
    for _ in range(6):
        c.post(f"/api/yao/cases/{token}/toss", json={"backs": 1})
    c.post(f"/api/yao/cases/{token}/submit")
    old_id = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    m.post(f"/api/master/cases/{old_id}/request_rewrite", json={"reason": "請只問一件事"})
    assert "老師請你重新起卦" in c.get(f"/c/{token}").text
    assert "請只問一件事" in c.get(f"/yao?redo={token}").text

    new = start(c, redo_of=token)
    for _ in range(6):
        c.post(f"/api/yao/cases/{new}/toss", json={"backs": 2})
    c.post(f"/api/yao/cases/{new}/submit")
    assert c.get(f"/c/{token}").status_code == 404     # 舊的被新的取代


def test_char_cases_unchanged():
    """問字的案件照舊走 /master/case，不受問爻影響。"""
    m = master_client()
    token = TestClient(app).post("/api/cases").json()["token"]
    cid = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    assert m.get(f"/master/case/{cid}").status_code == 200
    assert m.get(f"/master/yao/case/{cid}").status_code == 404


def test_toss_log_order():
    c, m = whitelisted(), master_client()
    token = start(c)
    for b in (3, 0, 1, 2, 1, 1):
        c.post(f"/api/yao/cases/{token}/toss", json={"backs": b})
    cid = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    html = m.get(f"/master/yao/case/{cid}").text
    assert html.index("<td>1</td><td>初爻</td>") < html.index("<td>6</td><td>上爻</td>")
