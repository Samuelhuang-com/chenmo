"""以字起卦的參考卦：寫進解字資料、AI 草稿的依據、快取失效。"""
import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.models import CaseStatus
from app.services import jiezi
from app.services.liuyao.derived import derived_chart, reference_text
from app.repositories import get_repo
from tests.test_features import master_client


def char_case(m):
    token = TestClient(app).post("/api/cases").json()["token"]
    return next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]


def test_derive_returns_reference_text_and_is_saved():
    m = master_client()
    cid = char_case(m)
    d = m.post(f"/api/master/yao/derive/{cid}", json={"char": "億"}).json()
    assert "梅花易數" in d["text"] and "本卦：" in d["text"] and "六爻（由上爻到初爻）" in d["text"]
    case = asyncio.run(get_repo().get(cid))
    assert derived_chart(case) is not None
    assert reference_text(case) == d["text"]


def test_no_derived_means_no_reference():
    m = master_client()
    cid = char_case(m)
    case = asyncio.run(get_repo().get(cid))
    assert derived_chart(case) is None and reference_text(case) == ""


def test_compose_adds_reference_section_for_teacher_only():
    m = master_client()
    cid = char_case(m)
    m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"})
    case = asyncio.run(get_repo().get(cid))
    r = asyncio.run(jiezi.compose(case, [], "王", use_ai=False))
    keys = list(r["sections"])
    assert "參考卦" in keys and keys.index("參考卦") < keys.index("解讀")      # 在【解讀】之前，所以不會送給問事者
    assert "【參考卦】" in r["text"]


def test_context_for_ai_includes_chart_only_when_derived(monkeypatch):
    m = master_client()
    cid = char_case(m)
    seen = []

    async def fake(context):
        seen.append(context)
        return {"reading": "好。", "gua_note": "世爻旺。"}, ""
    monkeypatch.setattr(jiezi.ai_draft, "generate_ex", fake)
    case = asyncio.run(get_repo().get(cid))
    asyncio.run(jiezi.compose(case, [], "王"))
    assert "參考卦" not in seen[-1]
    m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"})
    case = asyncio.run(get_repo().get(cid))
    r = asyncio.run(jiezi.compose(case, [], "王"))
    assert "參考卦" in seen[-1] and "不能出現卦名" in seen[-1]
    assert "簡析：世爻旺。" in r["sections"]["參考卦"]


def test_jiezi_cache_is_bypassed_after_derive():
    m = master_client()
    cid = char_case(m)
    first = m.post(f"/api/master/cases/{cid}/jiezi", json={"char": "王"}).json()
    assert "【參考卦】" not in first["text"]
    m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"})
    second = m.post(f"/api/master/cases/{cid}/jiezi", json={"char": "王"}).json()
    assert second.get("cached") is False and "【參考卦】" in second["text"]
    third = m.post(f"/api/master/cases/{cid}/jiezi", json={"char": "王"}).json()
    assert third.get("cached") is True and "【參考卦】" in third["text"]


# ---------- 給問事者看的「梅花易數」白話段落 ----------
def test_public_block_in_reading_with_ai_plain(monkeypatch):
    m = master_client()
    cid = char_case(m)

    async def fake(context):
        assert "gua_plain" in context
        return {"reading": "這個字像一扇門。", "gua_note": "世爻旺。", "gua_plain": "這個卦看起來是先退後進。"}, ""
    monkeypatch.setattr(jiezi.ai_draft, "generate_ex", fake)
    d = m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"}).json()
    assert d["block"].startswith("梅花易數｜") and "本卦代表現在的狀況" in d["block"] and "變卦代表事情接下來的走向" in d["block"]
    case = asyncio.run(get_repo().get(cid))
    r = asyncio.run(jiezi.compose(case, [], "王"))
    reading = r["sections"]["解讀"]
    assert reading.startswith("這個字像一扇門。") and "梅花易數｜" in reading and "先退後進" in reading
    assert "世爻旺" not in reading                      # 術語簡析只在【參考卦】，不進問事者看的解讀
    assert "世爻旺" in r["sections"]["參考卦"]


def test_public_block_without_ai_has_intro_only():
    m = master_client()
    cid = char_case(m)
    m.post(f"/api/master/yao/derive/{cid}", json={"char": "王"})
    case = asyncio.run(get_repo().get(cid))
    r = asyncio.run(jiezi.compose(case, [], "王", use_ai=False))
    assert "梅花易數｜這是用你問的「王」字" in r["sections"]["解讀"]


def test_marker_becomes_heading_and_survives_sanitize():
    from app.services.richtext import sanitize_html, text_to_html
    h = text_to_html("前面一段。\n\n梅花易數｜用「王」字起卦。\n\n白話說明。")
    assert h == "<p>前面一段。</p><h4>梅花易數</h4><p>用「王」字起卦。</p><p>白話說明。</p>"
    assert "<h4>梅花易數</h4>" in sanitize_html(h)


def test_student_sees_meihua_heading():
    m = master_client()
    token = TestClient(app).post("/api/cases").json()["token"]
    cid = next(x for x in m.get("/api/master/cases").json()["cases"] if x["token"] == token)["id"]
    asyncio.run(get_repo().update(cid, answer_html="<p>你好。</p><h4>梅花易數</h4><p>這個卦看起來是轉機。</p>",
                                  answer="你好。", status=CaseStatus.answered))
    page = TestClient(app).get(f"/c/{token}")
    assert page.status_code == 200 and "<h4>梅花易數</h4>" in page.text
