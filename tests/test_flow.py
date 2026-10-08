from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
PROFILE = {"birth_year": 75, "gender": "男"}


def stroke(ws, seq, pts):
    ws.send_json({"type": "stroke_start", "seq": seq, "t0": 1_000_000 + seq * 1000})
    ws.send_json({"type": "stroke_points", "seq": seq, "points": pts})
    ws.send_json({"type": "stroke_end", "seq": seq})


def login(c):
    r = c.post("/master/login", data={"password": "test-pw"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/master"


def test_pages_render():
    for path in ["/", "/ask", "/master/login"]:
        assert client.get(path).status_code == 200
    assert client.get("/c/nope").status_code == 404
    r = client.get("/master", follow_redirects=False)
    assert r.headers["location"] == "/master/login"


def test_full_flow():
    master = TestClient(app)
    login(master)
    token = client.post("/api/cases").json()["token"]

    # 沒寫字不能送出
    r = client.post(f"/api/cases/{token}/submit", json={"question": "問工作", **PROFILE})
    assert r.status_code == 422

    with master.websocket_connect("/ws/master") as mws, \
         client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.1, 0.1, 0], [0.5, 0.1, 30], [9, -3, 60]])
        stroke(ws, 2, [[0.3, 0.0, 0], [0.3, 0.9, 40]])
        ws.send_json({"type": "undo"})
        stroke(ws, 3, [[0.2, 0.5, 0], [0.8, 0.5, 50]])
        ws.send_json({"type": "sync", "id": 7})
        assert ws.receive_json() == {"type": "synced", "id": 7}

        got = [mws.receive_json()["type"] for _ in range(10)]
        assert got[:4] == ["stroke_start", "stroke_points", "stroke_end", "stroke_start"]
        assert "undo" in got

        too_long = "字" * 101
        r = client.post(f"/api/cases/{token}/submit", json={"question": too_long, **PROFILE})
        assert r.status_code == 422
        r = client.post(f"/api/cases/{token}/submit", json={"question": "今年換工作好嗎？", "char": "行", **PROFILE})
        assert r.status_code == 200

        data = client.get(f"/api/cases/{token}").json()
        assert data["case"]["status"] == "submitted"
        assert len(data["strokes"]) == 2               # 第 2 筆被復原
        assert data["strokes"][0]["points"][2][:2] == [1.0, 0.0]  # 座標被夾在 0–1

        cases = master.get("/api/master/cases").json()["cases"]
        case_id = next(c["id"] for c in cases if c["token"] == token)
        detail = master.get(f"/api/master/cases/{case_id}").json()
        assert [e["type"] for e in detail["events"]] == ["stroke", "stroke", "undo", "stroke"]

        # 沒有【解讀】不能送出
        r = master.post(f"/api/master/cases/{case_id}/answer", json={"body": "【五行】火"})
        assert r.status_code == 422
        full = "【此字】\n行\n\n【五行】\n火（老師筆記）\n\n【解讀】\n行者，往前也。（AI 草稿，請審閱）\n"
        r = master.post(f"/api/master/cases/{case_id}/answer", json={"body": full})
        assert r.status_code == 200 and r.json()["reading"] == "行者，往前也。"
        # 問事者端收到通知
        while True:
            m = ws.receive_json()
            if m["type"] == "answer_ready":
                break

    page = client.get(f"/c/{token}")
    assert "行者，往前也。" in page.text
    assert "老師筆記" not in page.text and "AI 草稿" not in page.text   # 學生只看到解讀
    assert "老師筆記" not in str(client.get(f"/api/cases/{token}").json())

    # 已送出不能直接重送，要先收回
    assert master.post(f"/api/master/cases/{case_id}/answer", json={"body": full}).status_code == 409
    assert master.post(f"/api/master/cases/{case_id}/retract").status_code == 200
    assert client.get(f"/api/cases/{token}").json()["case"]["status"] == "submitted"
    assert "行者" not in client.get(f"/c/{token}").text            # 收回後學生看不到
    full2 = full.replace("行者，往前也。", "行者，宜緩步前行。")
    r = master.post(f"/api/master/cases/{case_id}/answer", json={"body": full2})
    assert r.json()["revision"] == 2
    assert "宜緩步前行" in client.get(f"/c/{token}").text

    # 已解紀錄
    h = master.get("/master/history")
    assert h.status_code == 200 and "宜緩步前行" in h.text and "共送出 2 次" in h.text
    assert "宜緩步前行" in master.get("/master/history", params={"q": "行"}).text
    assert "找不到" in master.get("/master/history", params={"q": "無此字詞"}).text
    # 老師工作台保留完整解字稿
    assert "老師筆記" in master.get(f"/master/case/{case_id}").text


def test_master_api_requires_login():
    assert TestClient(app).get("/api/master/cases").status_code == 401


def test_question_counts_code_points():
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.1, 0.1, 0]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    q = "𠀀" * 100  # 罕用字（UTF-16 佔 2 單位）仍算 100 字
    assert client.post(f"/api/cases/{token}/submit", json={"question": q, **PROFILE}).status_code == 200


def test_chardict_kangxi_and_wuxing():
    from app.services.chardict import lookup
    he = lookup("河")
    assert (he.radical_char, he.total_strokes, he.kangxi_strokes) == ("水", 8, 9)
    assert he.wuxing_by_strokes == "水" and he.wuxing_by_radical == "水"
    assert lookup("王").kangxi_strokes == 4          # 餘筆為負時用總筆畫
    assert lookup("四").kangxi_strokes == 4          # 數字依字義
    assert lookup("蓮").kangxi_strokes == 17         # 艹 以艸 6 畫計
    assert lookup("龙").kangxi_strokes == 16         # 簡體以繁體計
    assert "訊也" in lookup("問").shuowen["e"]


def test_jiezi_without_ai():
    master = TestClient(app)
    login(master)
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        for i, y in enumerate((0.25, 0.5, 0.75)):
            stroke(ws, i + 1, [[0.25, y, 0], [0.75, y, 40]])
        stroke(ws, 4, [[0.5, 0.25, 0], [0.5, 0.75, 60]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    client.post(f"/api/cases/{token}/submit", json={"question": "問考試", "char": "王", **PROFILE})
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)

    r = master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": "王"})
    assert r.status_code == 200
    text = r.json()["text"]
    for head in ["【此字】", "【五行】", "【古字說法】", "【字義】", "【解讀】"]:
        assert head in text
    assert "康熙筆畫：4" in text and "與標準筆數相同" in text
    assert "天下所歸往也" in text
    assert r.json()["cached"] is False
    assert master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": "王"}).json()["cached"] is True
    assert master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": "王王"}).status_code == 422


def test_jiezi_with_ai_mock(monkeypatch):
    import pytest
    pytest.importorskip("anthropic")
    from app.services import ai_draft

    class FakeMsg:
        content = [type("B", (), {"type": "text", "text": '說明如下 {"ancient": "王為會意字。", "meaning": "本義為君主。", "reading": "三橫一豎，貫通天地人。", "wuxing_note": "宜以土論。"}'})()]

    class FakeClient:
        def __init__(self, **k):
            self.messages = self

        async def create(self, **k):
            assert k["model"] and k["system"] and "問事者的問題" in k["messages"][0]["content"]
            return FakeMsg()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setattr(ai_draft.get_settings(), "anthropic_api_key", "sk-test")
    master = TestClient(app)
    login(master)
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    client.post(f"/api/cases/{token}/submit", json={"question": "問工作", "char": "王", **PROFILE})
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    d = master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": "王"}).json()
    assert d["ai_used"] is True
    assert "三橫一豎" in d["sections"]["解讀"] and "AI 草稿" in d["sections"]["解讀"]
    assert "宜以土論" in d["sections"]["五行"]


def test_sqlite_repo_persists(tmp_path):
    import asyncio
    from app.models import CaseStatus
    from app.repositories.sqlite_repo import SqliteCaseRepository

    async def run():
        path = str(tmp_path / "t.db")
        r = SqliteCaseRepository(path)
        c = await r.create_case()
        await r.append_event(c.id, {"type": "stroke", "points": [[0, 0, 0]]})
        await r.update(c.id, status=CaseStatus.answered, answered_at=5, answer="解讀")
        r2 = SqliteCaseRepository(path)              # 模擬重新啟動
        got = await r2.get_by_token(c.token)
        assert got.answer == "解讀" and got.status == CaseStatus.answered
        assert [e["type"] for e in await r2.list_events(c.id)] == ["stroke"]
        assert len(await r2.list_cases(status=CaseStatus.answered)) == 1
        assert await r2.list_cases(status=CaseStatus.submitted) == []
    asyncio.run(run())


def test_public_reading():
    from app.services.sections import public_reading
    t = "【此字】\n王\n\n【解讀】\n第一段（AI 草稿，請審閱）\n第二段\n"
    assert public_reading(t) == "第一段\n第二段"
    assert public_reading("【此字】\n王") == ""


def test_profile_validation_and_display():
    master = TestClient(app)
    login(master)
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "profile", "birth_year": 77, "gender": "女"})
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    url = f"/api/cases/{token}/submit"
    assert client.post(url, json={"question": "問", "birth_year": 75}).status_code == 422          # 沒選性別
    assert client.post(url, json={"question": "問", "birth_year": 0, "gender": "男"}).status_code == 422
    assert client.post(url, json={"question": "問", "birth_year": 999, "gender": "男"}).status_code == 422
    assert client.post(url, json={"question": "問", "birth_year": 75, "gender": "其他"}).status_code == 422
    assert client.post(url, json={"question": "問", "birth_year": 77, "gender": "女"}).status_code == 200
    data = client.get(f"/api/cases/{token}").json()["case"]
    assert data["birth_year"] == 77 and data["gender"] == "女"
    assert data["profile_text"] == "民國 77 年次（西元 1988，屬龍）、女"
    assert "民國 77 年次" in client.get(f"/c/{token}").text
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    assert "屬龍" in master.get(f"/master/case/{case_id}").text


def test_pick_char_flow():
    from app.services.pick import pool
    master = TestClient(app)
    login(master)
    s1 = client.get("/api/pick").json()["chars"]
    assert len(s1) == 20 and len(set(s1)) == 20 and all(c in pool() for c in s1)
    assert any(client.get("/api/pick").json()["chars"] != s1 for _ in range(5))   # 隨機

    token = client.post("/api/cases").json()["token"]
    url = f"/api/cases/{token}/submit"
    base = {"question": "問感情", **PROFILE}
    # 沒寫字也沒自選 → 不能送
    assert client.post(url, json=base).status_code == 422
    # 選的字不在候選中 → 不能送
    bad = {**base, "picked": True, "char": "鬱", "offered": s1}
    assert client.post(url, json=bad).status_code == 422
    # 候選字被竄改（不在字池）→ 不能送
    assert client.post(url, json={**base, "picked": True, "char": "鬱", "offered": ["鬱"] + s1[1:]}).status_code == 422
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        ws.send_json({"type": "pick", "char": s1[3], "offered": s1, "rounds": 2})
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    ok = {**base, "picked": True, "char": s1[3], "offered": s1, "rounds": 2}
    assert client.post(url, json=ok).status_code == 200      # 自選字可以不手寫
    data = client.get(f"/api/cases/{token}").json()["case"]
    assert data["char"] == s1[3] and data["char_source"] == "picked"

    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    c = master.get(f"/api/master/cases/{case_id}").json()["case"]
    assert c["offered"] == s1 and c["pick_rounds"] == 2
    assert "換到第 2 組才選定" in master.get(f"/master/case/{case_id}").text
    j = master.post(f"/api/master/cases/{case_id}/jiezi", json={"char": s1[3]}).json()
    assert "此字為學生自選" in j["sections"]["此字"] and "沒有筆跡" not in j["sections"]["此字"]
    assert "自選字" in client.get(f"/c/{token}").text


def test_email_on_submit(monkeypatch):
    import smtplib
    from app.config import get_settings
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): sent.append(("tls",))
        def login(self, u, p): sent.append(("login", u))
        def send_message(self, m): sent.append(("msg", m))

    s = get_settings()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(s, "smtp_user", "teacher@gmail.com")
    monkeypatch.setattr(s, "smtp_password", "app-pass")
    monkeypatch.setattr(s, "notify_emails", "a@x.com,b@x.com")
    monkeypatch.setattr(s, "site_url", "https://chenmo.example")

    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    r = client.post(f"/api/cases/{token}/submit",
                    json={"question": "明年換工作好嗎？", "char": "行", **PROFILE})
    assert r.status_code == 200
    msg = next(x[1] for x in sent if x[0] == "msg")
    assert ("connect", "smtp.gmail.com", 587) in sent and ("tls",) in sent
    assert "新問字「行」" in msg["Subject"] and "民國 75 年次" in msg["Subject"]
    assert msg["To"] == "a@x.com, b@x.com"
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "明年換工作好嗎？" in text and "https://chenmo.example/master/case/" in text


def test_email_failure_does_not_block_submit(monkeypatch):
    import smtplib
    from app.config import get_settings

    class BrokenSMTP:
        def __init__(self, *a, **k): raise OSError("network down")

    s = get_settings()
    monkeypatch.setattr(smtplib, "SMTP", BrokenSMTP)
    monkeypatch.setattr(s, "smtp_user", "teacher@gmail.com")
    monkeypatch.setattr(s, "smtp_password", "app-pass")
    monkeypatch.setattr(s, "notify_emails", "a@x.com")
    assert s.email_enabled
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    r = client.post(f"/api/cases/{token}/submit", json={"question": "問", **PROFILE})
    assert r.status_code == 200


def _fake_google(monkeypatch, email, name="學生甲"):
    """模擬 Google OAuth：authorize_redirect 直接跳回 callback，callback 回傳指定帳號。"""
    from fastapi.responses import RedirectResponse
    import app.routers.master as master_mod
    from app.config import get_settings

    class FakeGoogle:
        async def authorize_redirect(self, request, redirect_uri):
            return RedirectResponse(redirect_uri, status_code=302)

        async def authorize_access_token(self, request):
            return {"userinfo": {"email": email, "email_verified": True, "name": name}}

    class FakeOAuth:
        google = FakeGoogle()

    s = get_settings()
    monkeypatch.setattr(master_mod, "get_oauth", lambda: FakeOAuth())
    monkeypatch.setattr(s, "google_client_id", "cid")
    monkeypatch.setattr(s, "google_client_secret", "csecret")


def test_student_login_and_my_cases(monkeypatch):
    _fake_google(monkeypatch, "student@gmail.com")
    st = TestClient(app)
    # 需要登入：未登入不能問字
    assert "先登入，再問字" in st.get("/ask").text
    assert st.post("/api/cases").status_code == 401
    assert st.get("/me", follow_redirects=False).headers["location"].startswith("/me/login")
    # 登入
    r = st.get("/me/login?next=/ask", follow_redirects=True)
    assert r.url.path == "/ask" and "以 學生甲 的身分問字" in r.text
    # 問字
    token = st.post("/api/cases").json()["token"]
    with st.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    assert st.post(f"/api/cases/{token}/submit", json={"question": "問考運", "char": "考", **PROFILE}).status_code == 200
    me = st.get("/me").text
    assert "問考運" in me and "待老師解讀" in me
    # 老師解讀後，學生在「我的問字」看得到解讀
    master = TestClient(app)
    login(master)
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    assert master.get(f"/api/master/cases/{case_id}").json()["case"]["owner_email"] == "student@gmail.com"
    master.post(f"/api/master/cases/{case_id}/answer", json={"body": "【解讀】\n考字下有巧，宜穩中求進。"})
    me = st.get("/me").text
    assert "宜穩中求進" in me and "已解" in me
    # 別人看不到這筆
    _fake_google(monkeypatch, "other@gmail.com", "學生乙")
    other = TestClient(app)
    other.get("/me/login?next=/me")
    assert "問考運" not in other.get("/me").text
    # 登出
    st.get("/me/logout")
    assert st.post("/api/cases").status_code == 401


def test_teacher_login_still_works_with_shared_callback(monkeypatch):
    _fake_google(monkeypatch, "boss@gmail.com", "老師")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "master_emails", "boss@gmail.com")
    t = TestClient(app)
    r = t.get("/master/auth/google", follow_redirects=True)
    assert r.url.path == "/master" and t.get("/api/master/cases").status_code == 200
    # 學生帳號走老師登入會被拒
    _fake_google(monkeypatch, "student@gmail.com")
    s2 = TestClient(app)
    r = s2.get("/master/auth/google", follow_redirects=True)
    assert "沒有老師權限" in r.text


def test_sponsor_box(monkeypatch):
    from app.config import get_settings
    master = TestClient(app)
    login(master)
    token = client.post("/api/cases").json()["token"]
    with client.websocket_connect(f"/ws/user/{token}") as ws:
        stroke(ws, 1, [[0.2, 0.2, 0], [0.8, 0.2, 40]])
        ws.send_json({"type": "sync", "id": 1}); ws.receive_json()
    client.post(f"/api/cases/{token}/submit", json={"question": "問", **PROFILE})
    case_id = next(c["id"] for c in master.get("/api/master/cases").json()["cases"] if c["token"] == token)
    assert "請老師喝杯咖啡" not in client.get(f"/c/{token}").text           # 未設定不顯示
    monkeypatch.setattr(get_settings(), "sponsor_line_url", "https://line.me/R/xxx")
    assert "請老師喝杯咖啡" not in client.get(f"/c/{token}").text           # 尚未解讀不顯示
    master.post(f"/api/master/cases/{case_id}/answer", json={"body": "【解讀】\n好"})
    page = client.get(f"/c/{token}").text
    assert "請老師喝杯咖啡" in page and "https://line.me/R/xxx" in page


def test_sqlite_list_by_owner(tmp_path):
    import asyncio
    from app.repositories.sqlite_repo import SqliteCaseRepository

    async def run():
        r = SqliteCaseRepository(str(tmp_path / "o.db"))
        a = await r.create_case(); await r.update(a.id, owner_email="s@x.com", question="一")
        b = await r.create_case(); await r.update(b.id, owner_email="s@x.com", question="二")
        c = await r.create_case(); await r.update(c.id, owner_email="t@x.com")
        got = await r.list_by_owner("s@x.com")
        assert [x.id for x in got] == [b.id, a.id] or {x.id for x in got} == {a.id, b.id}
        assert len(got) == 2
    asyncio.run(run())


def test_legal_pages():
    assert "個人資料保護法" in client.get("/privacy").text
    assert "不構成醫療" in client.get("/terms").text


def test_pwa():
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and "manifest+json" in m.headers["content-type"]
    d = m.json()
    assert d["display"] == "standalone" and d["short_name"] == "辰墨軒"
    for icon in d["icons"]:
        assert client.get(icon["src"]).status_code == 200            # 每個圖示都存在
    assert {i["purpose"] for i in d["icons"]} == {"any", "maskable"}
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert "__VERSION__" not in sw.text and "chenmo-" in sw.text
    assert "目前沒有網路" in client.get("/offline").text
    home = client.get("/").text
    assert 'rel="manifest"' in home and "apple-touch-icon" in home and "/static/brand/" in home


def test_brand_switch(monkeypatch):
    from app.config import get_settings
    for k in "ABCDE":
        monkeypatch.setattr(get_settings(), "brand_logo", k)
        assert f"/static/brand/{k}/logo.svg" in client.get("/").text
    monkeypatch.setattr(get_settings(), "brand_logo", "Z")              # 不存在的款式退回 C
    assert "/static/brand/C/logo.svg" in client.get("/").text


def test_teacher_logs_in_from_front_door(monkeypatch):
    from app.config import get_settings
    _fake_google(monkeypatch, "boss@gmail.com", "老師")
    monkeypatch.setattr(get_settings(), "master_emails", "boss@gmail.com")
    t = TestClient(app)
    r = t.get("/me/login?next=/me", follow_redirects=True)          # 從前台「登入」
    assert r.url.path == "/master"                                   # 直接進案前
    assert t.get("/api/master/cases").status_code == 200
    assert 'class="nav-master"' in t.get("/").text                   # 前台頁首有「案前」
    # 從 PWA 打開 → 直接進案前
    assert t.get("/?source=pwa", follow_redirects=False).headers["location"] == "/master"
    # 要問字時仍可留在問字頁
    assert t.get("/me/login?next=/ask", follow_redirects=True).url.path == "/ask"
    # 一般學生從 PWA 打開仍看到首頁
    _fake_google(monkeypatch, "student@gmail.com")
    s2 = TestClient(app)
    s2.get("/me/login?next=/me")
    assert s2.get("/?source=pwa", follow_redirects=False).status_code == 200
    assert 'class="nav-master"' not in s2.get("/").text
