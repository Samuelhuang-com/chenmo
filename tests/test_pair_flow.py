"""雙字問心：封測開關、兩個字格分開記錄、必填欄位、先後順序、老師端對照與偏向提示。"""
import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.services import features
from app.services.pair import order_of, relation
from tests.test_features import master_client, student_client

PROFILE = {"birth_year": 75, "gender": "男", "nickname": "小明"}
BODY = {"question": "要不要接新工作？", "char_a": "去", "char_b": "留",
        "choice_a": "接新工作", "choice_b": "留在現職", **PROFILE}


def reset(emails=None, all_=False):
    asyncio.run(features.save_flag(features.Flag("pair", enabled_for_all=all_, allow_emails=emails or []), "test"))
    features.reset_cache()


def whitelisted() -> TestClient:
    reset(["pair@gmail.com"])
    return student_client("pair@gmail.com")


def stroke(ws, seq, pts, pad=0, t0=1_000_000):
    msg = {"seq": seq, **({"pad": 1} if pad else {})}
    ws.send_json({"type": "stroke_start", "t0": t0, **msg})
    ws.send_json({"type": "stroke_points", "points": pts, **msg})
    ws.send_json({"type": "stroke_end", **msg})


def write_both(c, token, erase_b=False):
    with c.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 300]], t0=1_000_000)
        stroke(ws, 2, [[0.5, 0.1, 0], [0.5, 0.9, 300]], t0=1_001_000)
        if erase_b:
            stroke(ws, 10001, [[0.1, 0.1, 0], [0.2, 0.2, 100]], pad=1, t0=1_005_000)
            ws.send_json({"type": "undo", "pad": 1})
        stroke(ws, 10002, [[0.4, 0.4, 0], [0.6, 0.6, 200]], pad=1, t0=1_006_000)
        ws.send_json({"type": "sync", "id": 1})
        assert ws.receive_json() == {"type": "synced", "id": 1}


def case_id_of(m, token):
    return next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]


def test_hidden_without_flag():
    reset()
    c = TestClient(app)
    assert c.get("/pair").status_code == 404
    assert c.post("/api/pair/cases", json={}).status_code == 404
    assert "/pair" not in c.get("/").text and "/pair" not in c.get("/ask").text


def test_entry_visible_for_whitelist():
    c = whitelisted()
    assert c.get("/pair").status_code == 200
    assert "/pair" in c.get("/ask").text          # 問字頁出現雙字問心的入口
    assert "/pair" in c.get("/").text


def test_full_flow_and_order():
    c, m = whitelisted(), master_client()
    token = c.post("/api/pair/cases", json={}).json()["token"]

    # 沒寫字不能呈送
    r = c.post(f"/api/pair/cases/{token}/submit", json=BODY)
    assert r.status_code == 422 and "第一個字格" in r.text

    write_both(c, token, erase_b=True)
    cid = case_id_of(m, token)
    d = m.get(f"/api/master/cases/{cid}").json()
    assert d["case"]["kind"] == "pair" and d["case"]["stroke_count"] == 3   # 第二字的 undo 不會吃掉第一字
    assert d["pair"]["first"] == 0 and "先寫" in d["pair"]["order"]

    # 必填：代表的選擇、兩個字不同
    for bad, msg in [({"choice_b": " "}, "代表的選擇"), ({"char_b": "去"}, "不同的字"), ({"char_a": ""}, "各只填一個字")]:
        r = c.post(f"/api/pair/cases/{token}/submit", json={**BODY, **bad})
        assert r.status_code == 422 and msg in r.text, r.text
    # 一般問字的呈送端點不能拿來送雙字問心
    assert c.post(f"/api/cases/{token}/submit", json={"question": "x", "char": "去", **PROFILE}).status_code == 404

    r = c.post(f"/api/pair/cases/{token}/submit", json={**BODY, "preset": "去留"})
    assert r.status_code == 200, r.text
    case = m.get(f"/api/master/cases/{cid}").json()["case"]
    assert (case["char"], case["char2"], case["choice_a"], case["choice_b"], case["pair_preset"]) == \
        ("去", "留", "接新工作", "留在現職", "去留")

    # 問事者頁面：兩個字、各自代表的選擇
    view = c.get(f"/c/{token}").text
    assert "接新工作" in view and "留在現職" in view and 'id="pad2"' in view
    api = c.get(f"/api/cases/{token}").json()
    assert len(api["strokes"]) == 2 and len(api["strokes2"]) == 1

    # 老師端：工作台、帶出對照（沒有 AI 時也有事實與偏向提示）
    page = m.get(f"/master/case/{cid}").text
    assert "第二字" in page and "偏向提示" in page
    j = m.post(f"/api/master/cases/{cid}/jiezi", json={"char": "去", "char2": "留"}).json()
    for head in ("【此二字】", "【書寫對照】", "【五行生剋】", "【字義對照】", "【偏向提示】", "【解讀】"):
        assert head in j["text"]
    assert "先寫「去」" in j["text"] and "土剋水" in j["text"]
    assert "代表「接新工作」" in j["text"] and "合計" in j["text"]
    assert m.post(f"/api/master/cases/{cid}/jiezi", json={"char": "去", "char2": "留"}).json()["cached"]

    # 送出：問事者只看到【解讀】，看不到偏向提示
    r = m.post(f"/api/master/cases/{cid}/answer",
               json={"body": j["text"], "reading_html": "<p>小明，去與留各有道理。</p>"})
    assert r.status_code == 200, r.text
    view = c.get(f"/c/{token}").text
    assert "去與留各有道理" in view and "偏向" not in view and "/pair?follow=" in view


def test_redo_replaces_old_case():
    c, m = whitelisted(), master_client()
    token = c.post("/api/pair/cases", json={}).json()["token"]
    write_both(c, token)
    assert c.post(f"/api/pair/cases/{token}/submit", json=BODY).status_code == 200
    cid = case_id_of(m, token)
    assert m.post(f"/api/master/cases/{cid}/request_rewrite", json={"reason": "第二字太小"}).status_code == 200
    assert f"/pair?redo={token}" in c.get(f"/c/{token}").text
    page = c.get(f"/pair?redo={token}").text
    assert "第二字太小" in page and "接新工作" in page
    new = c.post("/api/pair/cases", json={"redo_of": token}).json()["token"]
    write_both(c, new)
    assert c.post(f"/api/pair/cases/{new}/submit", json=BODY).status_code == 200
    assert c.get(f"/api/cases/{token}").status_code == 404


def test_order_helpers():
    ev = [{"type": "stroke", "t0": 0, "points": [[0, 0, 0], [1, 1, 500]]},
          {"type": "stroke", "pad": 1, "t0": 2500, "points": [[0, 0, 0], [1, 1, 100]]},
          {"type": "undo"}]
    o = order_of(ev)
    assert o.first == 0 and o.gap_ms == 2000 and o.returned and o.switches == 2
    # 第二字先寫也記得出來
    assert order_of([ev[1], ev[0]]).first == 1
    assert relation("土", "金")[1] == 1 and relation("金", "木")[1] == 0 and relation("水", "水")[1] is None
