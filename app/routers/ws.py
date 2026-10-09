"""WebSocket：問事者即時上傳筆畫、老師端即時觀看。

設計原則：筆畫點座標即時轉送給老師（不落地，省 Firestore 寫入次數），
每一筆寫完（stroke_end）才整筆存入資料庫；undo / clear 也存成事件，
因為「寫了又擦掉」對測字也是線索。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import ws_master
from app.config import get_settings
from app.models import CaseStatus, code_point_len, now_ms
from app.repositories import get_repo
from app.services.realtime import hub
from app.services.strokes import clean_points, visible_strokes

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/ws/user/{token}")
async def user_ws(ws: WebSocket, token: str):
    s = get_settings()
    repo = get_repo()
    case = await repo.get_by_token(token)
    if not case:
        await ws.close(code=4404)
        return
    await ws.accept()
    hub.add_user(token, ws)

    pending: dict[int, dict] = {}       # 書寫中、尚未存檔的筆
    stroke_total = len(visible_strokes(await repo.list_events(case.id)))

    async def persist(seq: int) -> None:
        nonlocal stroke_total
        st = pending.pop(seq, None)
        if not st or not st["points"]:
            return
        await repo.append_event(case.id, {"type": "stroke", "seq": seq, "t0": st["t0"],
                                          "points": st["points"], "ts": now_ms()})
        stroke_total += 1
        await repo.update(case.id, stroke_count=stroke_total)

    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            if t == "ping":
                await ws.send_json({"type": "pong"})
                continue
            if t == "sync":
                # 訊息依序處理，回覆 synced 代表先前的筆畫都已存檔
                await ws.send_json({"type": "synced", "id": msg.get("id")})
                continue

            # 送出後就不再接受書寫（但連線保留，用來接收老師回覆通知）。
            # 只在低頻訊息時查狀態，避免每批點座標都讀資料庫。
            if t in ("question", "profile", "pick", "unpick", "stroke_start", "undo", "clear"):
                fresh = await repo.get(case.id)
                if not fresh or fresh.status != CaseStatus.drafting:
                    pending.clear()
                    continue

            out: dict | None = None
            if t == "question":
                text = str(msg.get("text", ""))[: s.question_max_chars]
                if code_point_len(text) <= s.question_max_chars:
                    await repo.update(case.id, question=text)
                    out = {"type": "question", "text": text}

            elif t == "profile":
                from app.models import GENDERS, roc_year_now
                fields: dict = {}
                try:
                    by = int(msg.get("birth_year") or 0)
                    if 1 <= by <= roc_year_now():
                        fields["birth_year"] = by
                except (TypeError, ValueError):
                    pass
                nn = " ".join(str(msg.get("nickname", "")).split())[:30]
                if "nickname" in msg:
                    fields["nickname"] = nn
                if msg.get("gender") in GENDERS:
                    fields["gender"] = msg["gender"]
                if fields:
                    updated = await repo.update(case.id, **fields)
                    out = {"type": "profile", "text": updated.profile_text, "nickname": updated.nickname}

            elif t == "pick":
                from app.services.pick import valid_offer
                ch, offered = str(msg.get("char", "")), msg.get("offered") or []
                if isinstance(offered, list) and valid_offer(offered) and ch in offered:
                    rounds = max(int(msg.get("rounds") or 1), 1)
                    await repo.update(case.id, char=ch, char_source="picked", offered=offered,
                                      pick_rounds=rounds)
                    out = {"type": "pick", "char": ch, "offered": offered, "rounds": rounds}

            elif t == "unpick":
                await repo.update(case.id, char="", char_source="", offered=[], pick_rounds=0)
                out = {"type": "unpick"}

            elif t == "stroke_start":
                seq = int(msg.get("seq", 0))
                if stroke_total + len(pending) >= s.max_strokes:
                    await ws.send_json({"type": "error", "message": "筆畫過多，請清除重寫"})
                    continue
                pending[seq] = {"t0": int(msg.get("t0") or now_ms()), "points": []}
                out = {"type": "stroke_start", "seq": seq, "t0": pending[seq]["t0"]}

            elif t == "stroke_points":
                seq = int(msg.get("seq", 0))
                st = pending.get(seq)
                if st is None:
                    continue
                room = s.max_points_per_stroke - len(st["points"])
                pts = clean_points(msg.get("points"), max(room, 0))
                st["points"].extend(pts)
                out = {"type": "stroke_points", "seq": seq, "points": pts}

            elif t == "stroke_end":
                seq = int(msg.get("seq", 0))
                await persist(seq)
                out = {"type": "stroke_end", "seq": seq}

            elif t in ("undo", "clear"):
                await repo.append_event(case.id, {"type": t, "ts": now_ms()})
                stroke_total = len(visible_strokes(await repo.list_events(case.id)))
                await repo.update(case.id, stroke_count=stroke_total)
                out = {"type": t}

            if out:
                await hub.to_masters({**out, "case_id": case.id})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("user ws error")
    finally:
        # 斷線時，書寫到一半的筆也存下來
        for seq in list(pending):
            try:
                await persist(seq)
            except Exception:  # noqa: BLE001
                log.exception("persist on disconnect failed")
        hub.remove_user(token, ws)


@router.websocket("/ws/master")
async def master_ws(ws: WebSocket):
    if not ws_master(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.add_master(ws)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_master(ws)
