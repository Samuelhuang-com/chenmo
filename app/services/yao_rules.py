"""斷卦規則庫：老師自己的斷卦心法。AI 解卦草稿只能引用這裡的規則與《周易》經文。

存放位置與案件相同的後端：Firestore yao_rules/all、SQLite kv 表、或記憶體。
第一次使用時帶入幾條六爻通行原則當起點，老師可以改、停用或刪除。
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path

from app.config import get_settings
from app.models import now_ms

DEFAULT_RULES = [
    ("用神旺衰", "用神臨月建、得月日生扶為旺，有力；休囚死又無生扶為衰，力弱。"),
    ("空破", "用神旬空或月破，事情一時難成；出旬、逢值或填實之日再看。"),
    ("動與靜", "動爻代表事情有變化；靜卦以用神旺衰與世應關係為主。"),
    ("回頭生剋", "用神發動化回頭生，得助力；化回頭剋，先好後阻，或中途生變。"),
    ("進神退神", "化進神主事情往前、漸漸增加；化退神主事情退縮、漸漸減弱。"),
    ("世應", "世爻是問事者自己，應爻是對方或所問之事；世應相生和順，相剋有阻礙。"),
    ("原神忌神", "生用神的原神發動有助力；剋用神的忌神發動，要防阻礙。"),
]


class _Store:
    def get(self) -> list[dict] | None: ...
    def put(self, rules: list[dict]) -> None: ...


class _Memory(_Store):
    def __init__(self):
        self.rules = None

    async def get(self):
        return self.rules

    async def put(self, rules):
        self.rules = rules


class _Sqlite(_Store):
    def __init__(self, path: str):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(p), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        self.db.commit()

    async def get(self):
        row = self.db.execute("SELECT v FROM kv WHERE k='yao_rules'").fetchone()
        return json.loads(row[0]) if row else None

    async def put(self, rules):
        self.db.execute("INSERT INTO kv(k, v) VALUES ('yao_rules', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                        (json.dumps(rules, ensure_ascii=False),))
        self.db.commit()


class _Firestore(_Store):
    def __init__(self, project, database):
        from google.cloud import firestore
        self.doc = firestore.AsyncClient(project=project, database=database).collection("yao_rules").document("all")

    async def get(self):
        snap = await self.doc.get()
        return (snap.to_dict() or {}).get("rules") if snap.exists else None

    async def put(self, rules):
        await self.doc.set({"rules": rules, "updated_at": now_ms()})


_store = None


def _get_store():
    global _store
    if _store is None:
        s = get_settings()
        if s.repo_backend == "firestore":
            _store = _Firestore(s.gcp_project, s.firestore_database)
        elif s.repo_backend == "sqlite":
            _store = _Sqlite(s.sqlite_path)
        else:
            _store = _Memory()
    return _store


async def list_rules() -> list[dict]:
    rules = await _get_store().get()
    if rules is None:
        rules = [{"id": secrets.token_hex(4), "title": t, "text": x, "active": True, "updated_at": now_ms()}
                 for t, x in DEFAULT_RULES]
        await _get_store().put(rules)
    return rules


async def save_rule(rule_id: str | None, title: str, text: str, active: bool) -> list[dict]:
    rules = await list_rules()
    title, text = title.strip()[:40], text.strip()[:1000]
    if not text:
        raise ValueError("規則內容是空的")
    for r in rules:
        if rule_id and r["id"] == rule_id:
            r.update(title=title, text=text, active=active, updated_at=now_ms())
            break
    else:
        rules.append({"id": secrets.token_hex(4), "title": title, "text": text, "active": active,
                      "updated_at": now_ms()})
    await _get_store().put(rules)
    return rules


async def delete_rule(rule_id: str) -> list[dict]:
    rules = [r for r in await list_rules() if r["id"] != rule_id]
    await _get_store().put(rules)
    return rules


async def active_rules() -> list[dict]:
    return [r for r in await list_rules() if r.get("active", True)]


def reset_for_tests() -> None:
    global _store
    _store = None
