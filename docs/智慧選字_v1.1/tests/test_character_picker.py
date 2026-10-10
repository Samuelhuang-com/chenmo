import copy
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.character_picker import (  # noqa: E402
    BankError,
    CharacterBank,
    is_single_han,
    load_legacy_pool,
    pick_legacy,
    validate_data,
)

DATA = ROOT / "data"


@pytest.fixture(scope="module")
def bank():
    return CharacterBank.load(DATA)


def _raw():
    return (
        json.loads((DATA / "themes.json").read_text(encoding="utf-8")),
        json.loads((DATA / "groups.json").read_text(encoding="utf-8")),
        json.loads((DATA / "character_meanings.json").read_text(encoding="utf-8")),
    )


# ---------------------------------------------------------------- 字庫資料
def test_shipped_data_has_no_errors():
    errors, _ = validate_data(*_raw())
    assert errors == []


def test_twelve_themes(bank):
    assert len(bank.list_themes()) == 12


# ---------------------------------------------------------------- 抽字
@pytest.mark.parametrize("gid", ["life_breakthrough", "love_cherish", "mind_calm"])
def test_group_pick_is_20_unique_and_ordered_by_stage(bank, gid):
    theme_id = bank.group_by_id[gid]["theme_id"]
    for seed in range(200):
        r = bank.pick(theme_id, group_id=gid, rng=random.Random(seed))
        chars = [c for s in r["stages"] for c in s["characters"]]
        assert len(chars) == 20 and len(set(chars)) == 20
        assert [len(s["characters"]) for s in r["stages"]] == [4] * 5
        assert r["group_id"] == gid and r["source"] == "group"
        assert set(r["meanings"]) == set(chars)  # 字卡所需字義隨回應帶回


def test_each_char_comes_from_its_own_stage(bank):
    g = bank.group_by_id["life_breakthrough"]
    r = bank.pick("life", group_id="life_breakthrough", rng=random.Random(1))
    for st, spec in zip(r["stages"], g["stages"]):
        assert set(st["characters"]) <= set(spec["characters"])


def test_redraw_with_exclude_gives_fully_different_set(bank):
    first = bank.pick("mind", group_id="mind_calm", rng=random.Random(3))
    prev = "".join(c for s in first["stages"] for c in s["characters"])
    for seed in range(100):
        again = bank.pick("mind", group_id="mind_calm", exclude=prev, rng=random.Random(seed))
        now = {c for s in again["stages"] for c in s["characters"]}
        assert now.isdisjoint(prev)  # 每階段 8 選 4：候選足夠時，重抽完全不同


def test_redraw_stays_in_same_group(bank):
    r = bank.pick("love", group_id="love_cherish", exclude="遇緣逢識")
    assert r["group_id"] == "love_cherish"


def test_theme_without_groups_uses_flat_pool_and_is_honest_about_redraw(bank):
    r = bank.pick("career", rng=random.Random(0))
    assert r["source"] == "pool" and r["count"] == 20
    assert r["can_redraw"] is False  # 20 字池沒有替代組合，不假裝重抽
    chars = r["stages"][0]["characters"]
    assert len(set(chars)) == 20


def test_unknown_theme_or_group_raises(bank):
    with pytest.raises(KeyError):
        bank.pick("nope")
    with pytest.raises(KeyError):
        bank.pick("life", group_id="love_cherish")


def test_random_works_for_all_themes(bank):
    for seed in range(100):
        r = bank.random(rng=random.Random(seed))
        assert r["count"] == 20


# ---------------------------------------------------------------- 驗證能抓到錯
def test_validator_catches_cross_stage_overlap():
    t, g, m = _raw()
    g = copy.deepcopy(g)
    g["groups"][0]["stages"][1]["characters"] += "難"  # 與第一階段重疊
    errors, _ = validate_data(t, g, m)
    assert any("不得重疊" in e for e in errors)


def test_validator_catches_quota_mismatch_and_too_few_candidates():
    t, g, m = _raw()
    g = copy.deepcopy(g)
    g["groups"][0]["stages"][0]["quota"] = 5
    g["groups"][0]["stages"][1]["characters"] = "思省"
    errors, _ = validate_data(t, g, m)
    assert any("配額加總" in e for e in errors)
    assert any("少於配額" in e for e in errors)


def test_validator_catches_missing_meaning_and_fortune_telling_words():
    t, g, m = _raw()
    m = copy.deepcopy(m)
    del m["characters"]["毅"]
    m["characters"]["勇"]["meaning"] = "註定成功"
    errors, _ = validate_data(t, g, m)
    assert any("缺少字義：毅" in e for e in errors)
    assert any("預言式" in e for e in errors)


def test_validator_catches_non_han_and_bad_references():
    t, g, m = _raw()
    t, g = copy.deepcopy(t), copy.deepcopy(g)
    g["groups"][0]["stages"][0]["characters"] += "A"
    t["themes"][0]["group_ids"] = ["ghost"]
    errors, _ = validate_data(t, g, m)
    assert any("非漢字" in e for e in errors)
    assert any("不存在的子題" in e for e in errors)


def test_strict_load_refuses_broken_bank(tmp_path):
    (tmp_path / "themes.json").write_text("{ broken", encoding="utf-8")
    (tmp_path / "groups.json").write_text("{}", encoding="utf-8")
    (tmp_path / "character_meanings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BankError):
        CharacterBank.load(tmp_path)


# ---------------------------------------------------------------- 舊字池備援
def test_legacy_pool_parsing_and_pick(tmp_path):
    p = tmp_path / "character_pool.txt"
    p.write_text("# 註解\n\n日月星雲山水火木金土\n日 月 abc 風雨雷電花鳥蟲魚\n春夏秋冬東西南北\n", encoding="utf-8")
    pool = load_legacy_pool(p)
    assert len(pool) == len(set(pool)) and all(is_single_han(c) for c in pool)
    r = pick_legacy(pool, 20, random.Random(1))
    assert r["source"] == "legacy" and len(set(r["stages"][0]["characters"])) == 20


def test_legacy_pool_too_small(tmp_path):
    with pytest.raises(BankError):
        pick_legacy(list("日月星"), 20)


# ---------------------------------------------------------------- API
def test_api_end_to_end():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import characters as api_mod

    app = fastapi.FastAPI()
    app.include_router(api_mod.router)
    c = TestClient(app)

    assert len(c.get("/api/characters/themes").json()["themes"]) == 12

    r = c.get("/api/characters/pick", params={"theme_id": "life", "group_id": "life_breakthrough"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    prev = "".join(ch for s in body["stages"] for ch in s["characters"])

    r2 = c.get("/api/characters/pick", params={"theme_id": "life", "group_id": "life_breakthrough", "exclude": prev})
    now = {ch for s in r2.json()["stages"] for ch in s["characters"]}
    assert now.isdisjoint(prev)

    assert c.get("/api/characters/pick", params={"theme_id": "zzz"}).status_code == 404
    assert c.get("/api/characters/meaning/毅").json()["meaning"]
    assert c.get("/api/characters/meaning/A").status_code == 404
    assert c.get("/api/characters/random").json()["count"] == 20


def test_api_falls_back_to_legacy_when_bank_broken(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import characters as api_mod

    (tmp_path / "themes.json").write_text("{ broken", encoding="utf-8")
    (tmp_path / "character_pool.txt").write_text("日月星雲山水火木金土風雨雷電花鳥蟲魚春夏秋冬", encoding="utf-8")
    monkeypatch.setattr(api_mod, "DEFAULT_DATA_DIR", tmp_path)
    monkeypatch.setattr(api_mod, "_loaded", False)
    monkeypatch.setattr(api_mod, "_bank", None)

    app = fastapi.FastAPI()
    app.include_router(api_mod.router)
    r = TestClient(app).get("/api/characters/pick", params={"theme_id": "life"})
    assert r.status_code == 200 and r.json()["source"] == "legacy"
