"""功能開關：問爻封測期間，只有老師與白名單 Email 看得到。"""
import asyncio
import json
from base64 import b64encode

import itsdangerous
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import features


def student_client(email: str) -> TestClient:
    """模擬已用 Google 登入的學生（直接簽一個 Starlette session cookie）。"""
    data = b64encode(json.dumps({"student": {"email": email, "name": email}}).encode())
    cookie = itsdangerous.TimestampSigner(get_settings().secret_key).sign(data).decode()
    c = TestClient(app)
    c.cookies.set("chenmo_session", cookie)
    return c


def master_client() -> TestClient:
    c = TestClient(app)
    c.post("/master/login", data={"password": "test-pw"}, follow_redirects=False)
    return c


def reset(emails=None, all_=False):
    asyncio.run(features.save_flag(features.Flag("yao", enabled_for_all=all_, allow_emails=emails or []), "test"))
    features.reset_cache()


def test_hidden_from_public():
    reset()
    c = TestClient(app)
    assert c.get("/yao").status_code == 404
    assert c.get("/api/yao/ping").status_code == 404
    home = c.get("/").text
    assert "/yao" not in home and "問爻" not in home


def test_hidden_from_student_not_on_list():
    reset(["friend@gmail.com"])
    c = student_client("stranger@gmail.com")
    assert c.get("/yao").status_code == 404
    assert "/yao" not in c.get("/").text


def test_visible_to_whitelisted_student_case_insensitive():
    reset(["Friend@Gmail.com"])
    c = student_client("friend@gmail.com")
    assert c.get("/yao").status_code == 200
    assert c.get("/api/yao/ping").json() == {"ok": True, "feature": "yao"}
    assert 'href="/yao"' in c.get("/").text


def test_master_always_sees_it():
    reset()
    m = master_client()
    assert m.get("/yao").status_code == 200


def test_env_whitelist(monkeypatch):
    reset()
    monkeypatch.setenv("FEATURE_YAO_EMAILS", "env@gmail.com")
    assert student_client("env@gmail.com").get("/yao").status_code == 200
    assert student_client("other@gmail.com").get("/yao").status_code == 404


def test_open_to_all():
    reset(all_=True)
    assert TestClient(app).get("/yao").status_code == 200
    reset()
    assert TestClient(app).get("/yao").status_code == 404


def test_master_manages_list():
    reset()
    anon = TestClient(app)
    assert anon.get("/master/flags", follow_redirects=False).status_code == 303   # 要先登入
    assert anon.post("/master/flags/yao/emails", data={"emails": "x@y.com"},
                     follow_redirects=False).status_code == 303
    assert asyncio.run(features.get_flag("yao", fresh=True)).allow_emails == []

    m = master_client()
    assert m.get("/master/flags").status_code == 200
    m.post("/master/flags/yao/emails", data={"emails": "A@b.com，c@d.com bad"})
    flag = asyncio.run(features.get_flag("yao", fresh=True))
    assert flag.allow_emails == ["a@b.com", "c@d.com"]
    assert student_client("a@b.com").get("/yao").status_code == 200

    m.post("/master/flags/yao/remove", data={"email": "a@b.com"})
    assert student_client("a@b.com").get("/yao").status_code == 404

    m.post("/master/flags/yao/all", data={"on": "1"})
    assert TestClient(app).get("/yao").status_code == 200
    m.post("/master/flags/yao/all", data={"on": "0"})
    assert TestClient(app).get("/yao").status_code == 404
    assert m.post("/master/flags/nope/all", data={"on": "1"}).status_code == 404


def test_existing_pages_unchanged_for_public():
    reset()
    c = TestClient(app)
    for path in ["/", "/ask", "/me", "/privacy", "/terms"]:
        assert c.get(path).status_code == 200
