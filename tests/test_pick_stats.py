"""自選字統計：只算數量。"""
from fastapi.testclient import TestClient

from app.main import app
from app.models import Case, CaseStatus, now_ms
from app.services.pick_stats import DAY_MS, summarize

client = TestClient(app)


def _case(source="", theme="", rounds=0, char="", status=CaseStatus.submitted, kind="char", ago_days=0):
    t = now_ms() - ago_days * DAY_MS
    return Case(char_source=source, pick_theme=theme, pick_rounds=rounds, char=char, status=status,
                kind=kind, submitted_at=t, created_at=t)


CASES = [
    _case("written"), _case(""),                                              # 手寫（含舊資料）
    _case("picked", "", 1, "山"), _case("picked", "", 3, "水"),               # 隨機字
    _case("picked", "突破困境", 2, "毅"), _case("picked", "突破困境", 1, "毅"),
    _case("picked", "珍惜關係", 5, "誠", status=CaseStatus.answered),
    _case("picked", "事業工作", 1, "勤", ago_days=20),                       # 20 天前
    _case("picked", "事業工作", 1, "勤", status=CaseStatus.drafting),          # 還沒呈送：不算
    _case("picked", "", 1, "命", kind="yao"),                                  # 問爻：不算
]


def test_summarize_all():
    s = summarize(CASES)
    assert s["total"] == 8 and s["written"] == 2 and s["picked"] == 6
    assert s["random"] == 2 and s["themed"] == 4 and s["themed_pct"] == 67          # 4/6
    assert s["themes"][0] == {"name": "突破困境", "n": 2, "pct": 50}
    assert {t["name"] for t in s["themes"]} == {"突破困境", "珍惜關係", "事業工作"}
    assert s["avg_rounds"] == 2.2 and s["first_set_pct"] == 50                       # (1+3+2+1+5+1)/6、3/6
    assert {"char": "毅", "n": 2} in s["top_chars"] and {"char": "勤", "n": 1} in s["top_chars"]   # 草稿與問爻不計


def test_summarize_recent_days_only():
    s = summarize(CASES, days=7)
    assert s["total"] == 7 and s["themed"] == 3 and "事業工作" not in {t["name"] for t in s["themes"]}


def test_summarize_empty_is_safe():
    s = summarize([])
    assert s["total"] == 0 and s["themed_pct"] == 0 and s["avg_rounds"] == 0 and s["themes"] == [] and s["top_chars"] == []


def test_stats_page_requires_master_and_renders():
    anon = TestClient(app)
    r = anon.get("/master/pick-stats", follow_redirects=False)
    assert r.status_code in (302, 303, 401) and "自選字統計" not in r.text      # 沒登入看不到
    m = TestClient(app)
    assert m.post("/master/login", data={"password": "test-pw"}, follow_redirects=False).status_code == 303
    for url in ("/master/pick-stats", "/master/pick-stats?days=7", "/master/pick-stats?days=30", "/master/pick-stats?days=999"):
        r = m.get(url)
        assert r.status_code == 200 and "自選字統計" in r.text and "有選方向的比例" in r.text, url
        assert r.headers.get("cache-control") == "no-store"
    assert "自選字統計" in m.get("/master").text                                      # 案前有入口
