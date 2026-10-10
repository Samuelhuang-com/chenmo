"""自選字的主題字庫：資料驗證、抽字規則、API、呈送與老師端顯示。
原本的隨機自選字（/api/pick 不帶參數）由 test_flow.py::test_pick_char_flow 負責。"""
import copy
import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pick, pick_bank
from app.services.pick_bank import BankError, CharacterBank, validate_data

DATA = Path(pick_bank.DATA_DIR)
client = TestClient(app)
PROFILE = {"birth_year": 77, "gender": "女", "nickname": "小明"}


def _raw():
    return tuple(json.loads((DATA / f).read_text(encoding="utf-8"))
                 for f in ("themes.json", "groups.json", "character_meanings.json"))


@pytest.fixture(scope="module")
def bank():
    return CharacterBank.load()


def _flat(r):
    return [c for s in r["stages"] for c in s["characters"]]


# ---------------------------------------------------------------- 資料
def test_shipped_bank_has_no_errors():
    errors, _ = validate_data(*_raw())
    assert errors == []


def test_twelve_themes_and_three_groups(bank):
    assert len(bank.list_themes()) == 12 and len(bank.group_by_id) == 3


# ---------------------------------------------------------------- 抽字規則
@pytest.mark.parametrize("gid", ["life_breakthrough", "love_cherish", "mind_calm"])
def test_group_pick_is_20_unique_stage_ordered(bank, gid):
    tid = bank.group_by_id[gid]["theme_id"]
    spec = bank.group_by_id[gid]["stages"]
    for seed in range(200):
        r = bank.pick(tid, gid, rng=random.Random(seed))
        chars = _flat(r)
        assert len(chars) == 20 == len(set(chars))
        assert [len(s["characters"]) for s in r["stages"]] == [4] * 5
        for st, sp in zip(r["stages"], spec):
            assert set(st["characters"]) <= set(sp["characters"])
        assert set(r["meanings"]) == set(chars)


def test_again_with_exclude_is_completely_different(bank):
    first = bank.pick("mind", "mind_calm", rng=random.Random(3))
    prev = "".join(_flat(first))
    for seed in range(100):
        again = bank.pick("mind", "mind_calm", exclude=prev, rng=random.Random(seed))
        assert set(_flat(again)).isdisjoint(prev) and again["group_id"] == "mind_calm"


def test_theme_without_groups_is_flat_pool_and_not_redrawable(bank):
    r = bank.pick("career")
    assert r["source"] == "pool" and len(_flat(r)) == 20 == len(set(_flat(r))) and r["can_redraw"] is False


def test_label_only_accepts_known_ids(bank):
    assert bank.label("life", "life_breakthrough") == "突破困境"
    assert bank.label("career") == "事業工作"
    assert bank.label("life", "love_cherish") == "人生方向"      # 子題不屬於該主題 → 退回主題名
    assert bank.label("<script>") == "" and bank.label("") == ""


# ---------------------------------------------------------------- 驗證能抓到錯
def test_validator_catches_overlap_quota_and_meaning_problems():
    t, g, m = _raw()
    g2 = copy.deepcopy(g)
    g2["groups"][0]["stages"][1]["characters"] += "難"
    assert any("不得重疊" in e for e in validate_data(t, g2, m)[0])
    g3 = copy.deepcopy(g)
    g3["groups"][0]["stages"][0]["quota"] = 5
    g3["groups"][0]["stages"][1]["characters"] = "思省"
    errs = validate_data(t, g3, m)[0]
    assert any("配額加總" in e for e in errs) and any("少於配額" in e for e in errs)
    m2 = copy.deepcopy(m)
    del m2["characters"]["毅"]
    m2["characters"]["勇"]["meaning"] = "註定成功"
    errs = validate_data(t, g, m2)[0]
    assert any("缺少字義：毅" in e for e in errs) and any("預言式" in e for e in errs)


def test_broken_bank_fails_strict_load(tmp_path):
    for f in ("themes.json", "groups.json", "character_meanings.json"):
        (tmp_path / f).write_text("{ broken", encoding="utf-8")
    with pytest.raises(BankError):
        CharacterBank.load(tmp_path)


# ---------------------------------------------------------------- API
def test_api_default_is_unchanged_random():
    d = client.get("/api/pick").json()
    assert set(d) == {"chars"} and len(d["chars"]) == 20


def test_api_themes_list():
    ts = client.get("/api/pick/themes").json()["themes"]
    assert len(ts) == 12 and ts[0]["short"] == "人生方向"


def test_api_theme_pick_and_again():
    d = client.get("/api/pick", params={"theme": "life"}).json()
    assert d["group_id"] == "life_breakthrough" and len(d["chars"]) == 20 == len(set(d["chars"]))
    assert d["chars"] == _flat(d) and d["can_redraw"] is True
    assert "meanings" not in d                      # 字義不給問事者
    d2 = client.get("/api/pick", params={"theme": "life", "group": d["group_id"], "exclude": "".join(d["chars"])}).json()
    assert set(d2["chars"]).isdisjoint(d["chars"])
    assert client.get("/api/pick", params={"theme": "career"}).json()["can_redraw"] is False
    assert client.get("/api/pick", params={"theme": "zzz"}).status_code == 404


def test_api_falls_back_to_random_when_bank_unavailable(monkeypatch):
    monkeypatch.setattr(pick, "bank", lambda: None)
    assert client.get("/api/pick/themes").json() == {"themes": []}
    d = client.get("/api/pick", params={"theme": "life"}).json()
    assert len(d["chars"]) == 20 and all(c in pick.pool() for c in d["chars"])


# ---------------------------------------------------------------- 呈送、老師端、解字稿
def _login():
    m = TestClient(app)
    r = m.post("/master/login", data={"password": "test-pw"}, follow_redirects=False)
    assert r.status_code == 303
    return m


def test_themed_pick_end_to_end():
    d = client.get("/api/pick", params={"theme": "mind"}).json()
    chars, ch = d["chars"], d["chars"][7]
    token = client.post("/api/cases").json()["token"]
    base = {"question": "問心情", **PROFILE, "picked": True, "char": ch, "offered": chars, "rounds": 2,
            "theme": "mind", "group": d["group_id"]}
    assert client.post(f"/api/cases/{token}/submit", json=base).status_code == 200

    master = _login()
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    c = master.get(f"/api/master/cases/{case_id}").json()["case"]
    assert c["pick_theme"] == "找回平靜" and c["offered"] == chars
    html = master.get(f"/master/case/{case_id}").text
    assert "方向「找回平靜」" in html and "換到第 2 組才選定" in html
    j = master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": ch}).json()
    assert "此字為學生自選：從「找回平靜」方向提供的 20 字中選出" in j["sections"]["此字"]


def test_unknown_theme_is_ignored_but_pick_still_valid():
    chars = client.get("/api/pick").json()["chars"]
    token = client.post("/api/cases").json()["token"]
    body = {"question": "問事", **PROFILE, "picked": True, "char": chars[0], "offered": chars, "rounds": 1,
            "theme": "<b>x</b>", "group": "nope"}
    assert client.post(f"/api/cases/{token}/submit", json=body).status_code == 200
    master = _login()
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    assert master.get(f"/api/master/cases/{case_id}").json()["case"]["pick_theme"] == ""
    j = master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": chars[0]}).json()
    assert "從系統隨機提供的 20 字" in j["sections"]["此字"]        # 隨機字的原本說法不變


def test_tampered_offer_still_rejected_with_theme():
    d = client.get("/api/pick", params={"theme": "life"}).json()
    token = client.post("/api/cases").json()["token"]
    bad = {"question": "問事", **PROFILE, "picked": True, "char": "鬱", "offered": ["鬱"] + d["chars"][1:],
           "rounds": 1, "theme": "life"}
    assert client.post(f"/api/cases/{token}/submit", json=bad).status_code == 422


def test_ws_pick_records_and_unpick_clears_theme():
    d = client.get("/api/pick", params={"theme": "love"}).json()
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        ws.send_json({"type": "pick", "char": d["chars"][2], "offered": d["chars"], "rounds": 1,
                      "theme": "love", "group": d["group_id"]})
        ws.send_json({"type": "sync", "id": 1})
        ws.receive_json()
        master = _login()
        case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
        assert master.get(f"/api/master/cases/{case_id}").json()["case"]["pick_theme"] == "珍惜關係"
        ws.send_json({"type": "unpick"})
        ws.send_json({"type": "sync", "id": 2})
        ws.receive_json()
        assert master.get(f"/api/master/cases/{case_id}").json()["case"]["pick_theme"] == ""
