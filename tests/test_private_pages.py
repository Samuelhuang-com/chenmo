"""個人頁面不可被快取／收錄；日誌不寫完整信箱。"""
import asyncio
import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, is_private_path
from app.models import CaseStatus
from app.repositories import get_repo
from app.services import notify

client = TestClient(app)


def _token():
    token = client.post("/api/cases").json()["token"]
    c = asyncio.run(get_repo().get_by_token(token))
    asyncio.run(get_repo().update(c.id, status=CaseStatus.submitted, question="問"))
    return token


def test_private_pages_are_no_store_and_noindex():
    t = _token()
    for url in (f"/c/{t}", "/me", f"/api/cases/{t}", "/master/login", f"/ask?follow={t}&n=0", "/ask?redo=abc"):
        r = client.get(url, follow_redirects=False)
        assert r.headers.get("cache-control") == "no-store", url
        assert "noindex" in r.headers.get("x-robots-tag", ""), url


def test_public_pages_stay_cacheable_and_indexable():
    for url in ("/", "/ask", "/privacy", "/terms", "/static/css/main.css"):
        r = client.get(url)
        assert "no-store" not in r.headers.get("cache-control", ""), url
        assert "x-robots-tag" not in r.headers, url


def test_is_private_path_rules():
    assert is_private_path("/c/abc") and is_private_path("/me") and is_private_path("/me/login")
    assert is_private_path("/master") and is_private_path("/master/case/1") and is_private_path("/api/x")
    assert is_private_path("/ask", "follow=t&n=1") and is_private_path("/yao", "redo=t")
    assert not is_private_path("/ask") and not is_private_path("/ask", "x=1")
    assert not is_private_path("/metrics") and not is_private_path("/privacy") and not is_private_path("/")


def test_service_worker_never_caches_private_pages():
    sw = Path("app/static/sw.js").read_text(encoding="utf-8")
    assert "isPrivate" in sw and "caches.match(\"/offline\")" in sw
    # 個人頁面分支必須在「放進快取」之前
    assert sw.index("if (isPrivate(url))") < sw.index("c.put(req, copy)")
    # 前後端規則的關鍵字一致
    for kw in ("follow", "redo", "master", "me"):
        assert kw in sw


def test_mask_email_and_student_mail_log(monkeypatch, caplog):
    assert notify.mask_email("student@example.com") == "s***@example.com"
    assert notify.mask_email("") == "***"

    class S:
        smtp_user, smtp_password, site_url = "u", "p", "https://x.test"
    monkeypatch.setattr(notify, "get_settings", lambda: S())
    monkeypatch.setattr(notify, "build_student_message", lambda case, link: object())
    monkeypatch.setattr(notify, "_send", lambda msg: None)
    case = type("C", (), {"owner_email": "student@example.com", "token": "tok"})()
    with caplog.at_level(logging.INFO, logger=notify.log.name):
        ok, _ = asyncio.run(notify.notify_student_answered(case, "http://b"))
        assert ok
        def boom(msg): raise RuntimeError("550 student@example.com rejected")
        monkeypatch.setattr(notify, "_send", boom)
        ok, _ = asyncio.run(notify.notify_student_answered(case, "http://b"))
        assert not ok
    assert "student@example.com" not in caplog.text and "s***@example.com" in caplog.text
