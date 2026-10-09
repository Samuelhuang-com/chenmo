"""問爻 Y3（AI 草稿、用神、經文、規則庫）與 Y4（以字起卦、不再占提醒、卦例回饋）。"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.liuyao import build_chart
from app.services.liuyao.meihua import values_from_strokes
from app.services.liuyao.texts import for_chart, lookup
from app.services.liuyao.yongshen import choose, suggest_target
from tests.test_features import master_client
from tests.test_yao_flow import start, whitelisted

WHEN = datetime(2026, 10, 9, 19, 30)


def submitted_case(c, m, backs=(1, 2, 1, 3, 1, 2), **extra):
    token = start(c, **extra)
    for b in backs:
        c.post(f"/api/yao/cases/{token}/toss", json={"backs": b})
    c.post(f"/api/yao/cases/{token}/submit")
    cid = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    return token, cid


# ---------- 經文 ----------
def test_zhouyi_text_complete():
    from app.services.liuyao import hexagram as hx
    for h in hx.BY_BITS.values():
        t = lookup(h.short)
        assert t["guaci"] and len(t["yao"]) == 6 and t["tuan"], h.name
    assert lookup("乾")["yao"][1] == "九二：見龍在田，利見大人。"
    assert lookup("坤")["yao"][5] == "上六：龍戰于野，其血玄黃。"
    assert "以其彙" in lookup("泰")["yao"][0] and "繫於苞桑" in lookup("否")["yao"][4]


def test_texts_for_chart_moving_lines():
    c = build_chart([9, 7, 7, 7, 7, 7], WHEN)               # 乾初九動
    t = for_chart(c)
    assert t["moving_lines"] == ["初九：潛龍，勿用。"] and t["bian_name"] == "天風姤"
    t = for_chart(build_chart([9] * 6, WHEN))                # 六爻全動加用九
    assert t["moving_lines"][-1].startswith("用九")


# ---------- 用神 ----------
@pytest.mark.parametrize("asked,cat,g,expect", [
    ("自己", "財運", "男", "妻財"), ("自己", "事業", "女", "官鬼"), ("自己", "考試", "男", "父母"),
    ("自己", "感情", "男", "妻財"), ("自己", "感情", "女", "官鬼"), ("自己", "健康", "男", "世"),
    ("伴侶", "健康", "女", "官鬼"), ("朋友", "財運", "男", "兄弟"), ("其他", "", "男", "應"),
])
def test_yongshen_rules(asked, cat, g, expect):
    q, sp, _ = suggest_target(asked, cat, g)
    assert (q or sp) == expect


def test_yongshen_hidden_uses_fushen():
    c = build_chart([8, 7, 8, 9, 8, 7], WHEN)                # 火水未濟，缺官鬼，亥水伏三爻
    y = choose(c, "自己", "感情", "女")
    assert y.liuqin == "官鬼" and y.hidden and y.lines == [3]


# ---------- 梅花：以字起卦 ----------
def test_meihua_formula():
    v, info = values_from_strokes(11, WHEN)                 # 戌時 = 11
    assert info["upper"] == "離" and info["lower"] == "坎" and info["moving"] == 4
    c = build_chart(v, WHEN)
    assert c.ben.name == "火水未濟" and c.moving_positions == [4]


def test_derive_from_char_case():
    m = master_client()
    token = TestClient(app).post("/api/cases").json()["token"]
    cid = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    assert m.post(f"/api/master/yao/derive/{cid}", json={}).status_code == 422   # 還不知道是什麼字
    r = m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["char"] == "王" and d["strokes"] > 0 and d["url"].startswith("/master/yao/paipan?v=")
    assert m.get(d["url"]).status_code == 200
    assert "已起參考卦" in m.get(f"/master/case/{cid}").text


# ---------- 規則庫 ----------
def test_rules_crud():
    m = master_client()
    page = m.get("/master/yao/rules")
    assert page.status_code == 200 and "用神旺衰" in page.text          # 預設規則
    m.post("/master/yao/rules", data={"title": "問考試", "text": "父母為文書，官鬼為功名。", "active": "1"})
    assert "父母為文書" in m.get("/master/yao/rules").text
    from app.services import yao_rules
    import asyncio
    rid = next(r["id"] for r in asyncio.run(yao_rules.list_rules()) if r["title"] == "問考試")
    m.post(f"/master/yao/rules/{rid}/delete")
    assert "父母為文書" not in m.get("/master/yao/rules").text
    assert TestClient(app).get("/master/yao/rules", follow_redirects=False).status_code in (303, 404)


# ---------- 工作台：用神、AI、追問、卦例 ----------
def test_workbench_yongshen_ai_followups_verify(monkeypatch):
    c, m = whitelisted(), master_client()
    token, cid = submitted_case(c, m)
    page = m.get(f"/master/yao/case/{cid}").text
    assert "用神" in page and "經文" in page and "系統建議：" in page

    assert m.put(f"/api/master/yao/cases/{cid}/yongshen", json={"liuqin": "官鬼"}).status_code == 200
    assert m.put(f"/api/master/yao/cases/{cid}/yongshen", json={"liuqin": "亂寫"}).status_code == 422

    # AI：沒有金鑰時清楚告知；有金鑰時用假的 generate
    assert m.post(f"/api/master/yao/cases/{cid}/ai").status_code == 409
    from app.config import get_settings
    from app.services import yao_ai
    seen = {}

    async def fake(context):
        seen["ctx"] = context
        return {"reading": "Amy，這一卦…", "basis": ["用神官鬼"], "followups": ["何時有消息？", "要準備什麼？", "還有機會嗎？"]}, ""
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test")
    monkeypatch.setattr(yao_ai, "generate", fake)
    r = m.post(f"/api/master/yao/cases/{cid}/ai")
    assert r.status_code == 200 and r.json()["reading"].startswith("Amy")
    ctx = seen["ctx"]
    assert "【卦盤】" in ctx and "用神：官鬼（老師指定）" in ctx and "【周易經文】" in ctx and "【老師的斷卦規則】" in ctx

    m.put(f"/api/master/yao/cases/{cid}/followups", json={"items": ["何時有消息？", "要準備什麼？"]})
    m.post(f"/api/master/cases/{cid}/answer", json={"body": "x", "reading_html": "<p>好</p>"})
    view = c.get(f"/c/{token}").text
    assert "何時有消息？" in view and "/ask?follow=" in view          # 自訂追問 + 可改用問字

    assert m.put(f"/api/master/yao/cases/{cid}/verify", json={"status": "應驗", "note": "兩週後錄取"}).status_code == 200
    assert "兩週後錄取" in m.get("/master/yao/rules?v=應驗").text


# ---------- 不再占提醒 ----------
def test_repeat_reminder():
    c, m = whitelisted(), master_client()
    token, _ = submitted_case(c, m)
    r = c.post("/api/yao/recent", json={"question": "這次面試結果如何呢", "tokens": [token]}).json()
    assert r["match"] and r["match"]["url"] == f"/c/{token}"
    r = c.post("/api/yao/recent", json={"question": "下個月搬家好嗎", "tokens": [token]}).json()
    assert r["match"] is None
