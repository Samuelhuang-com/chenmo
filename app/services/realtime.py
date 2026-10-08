"""即時連線中樞。

初期 Cloud Run 設 max-instances=1，用記憶體版即可。
日後流量變大要開多台時，改寫一個同介面的 RedisHub（Memorystore Pub/Sub）替換即可。
"""
from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self.masters: set[WebSocket] = set()
        self.users: dict[str, set[WebSocket]] = defaultdict(set)

    # ---- 老師端 ----
    def add_master(self, ws: WebSocket) -> None:
        self.masters.add(ws)

    def remove_master(self, ws: WebSocket) -> None:
        self.masters.discard(ws)

    async def to_masters(self, msg: dict) -> None:
        for ws in list(self.masters):
            try:
                await ws.send_json(msg)
            except Exception:
                log.info("drop dead master socket")
                self.masters.discard(ws)

    # ---- 問事者端（同一案件可能同時開著書寫頁與結果頁）----
    def add_user(self, token: str, ws: WebSocket) -> None:
        self.users[token].add(ws)

    def remove_user(self, token: str, ws: WebSocket) -> None:
        self.users[token].discard(ws)
        if not self.users[token]:
            self.users.pop(token, None)

    async def to_user(self, token: str, msg: dict) -> None:
        for ws in list(self.users.get(token, ())):
            try:
                await ws.send_json(msg)
            except Exception:
                self.users[token].discard(ws)


hub = Hub()
