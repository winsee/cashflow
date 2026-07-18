"""房间会话管理：内存态 + 事件持久化 + WS 广播（design/03 §4、§6）。

服务器权威：客户端只发意图（action），一切状态变更 = decide → append(event) → apply。
崩溃恢复：启动时对每个房间重放未撤销事件重建状态。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from typing import Any

from fastapi import WebSocket

from .data_loader import CardLibrary
from .engine import engine as E
from .engine import formulas as F
from .engine.errors import EngineError
from .engine.models import RoomState
from .store.db import Database


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RoomSession:
    def __init__(self, room_id: str, code: str, db: Database, lib: CardLibrary):
        self.room_id = room_id
        self.code = code
        self.db = db
        self.lib = lib
        self.state = RoomState()
        self.seq = 0
        self.lock = asyncio.Lock()
        self.sockets: dict[str, set[WebSocket]] = {}   # player_id -> conns

    # ---------- 恢复 ----------

    def restore(self) -> None:
        rows = self.db.events_for_room(self.room_id)
        state = RoomState()
        for r in rows:
            state = E.apply(state, {"type": r["type"], "payload": json.loads(r["payload"])})
        self.state = state
        self.seq = self.db.max_seq(self.room_id)

    # ---------- 行动入口 ----------

    async def handle_action(self, actor_id: str | None, action_id: str | None,
                            action_type: str, payload: dict) -> list[dict]:
        async with self.lock:
            if action_id:
                cached = self.db.dedupe_get(self.room_id, action_id)
                if cached:
                    return json.loads(cached["result"])
            if action_type == "HOST_REVERT":
                events = self._host_revert(actor_id, payload)
            else:
                events = E.decide(self.state, actor_id, action_type, payload, self.lib)
                for ev in events:
                    self.seq += 1
                    self.db.append_event(self.room_id, self.seq, actor_id,
                                         ev["type"], ev["payload"])
                    self.state = E.apply(self.state, ev)
            self._after_change()
            if action_id:
                self.db.dedupe_put(self.room_id, action_id, json.dumps(events, ensure_ascii=False))
            await self.broadcast_state(last_events=events)
            return events

    def _host_revert(self, actor_id: str, payload: dict) -> list[dict]:
        host = self.state.players.get(actor_id)
        if host is None or not host.is_host:
            raise EngineError("NOT_HOST", "只有房主能撤销事件")
        target_seq = int(payload["eventSeq"])
        # 先试重放：撤销后事件流必须仍然可应用，否则拒绝
        rows = self.db.events_for_room(self.room_id)
        remaining = [r for r in rows if r["seq"] != target_seq]
        if len(remaining) == len(rows):
            raise EngineError("NO_EVENT", "目标事件不存在或已被撤销")
        try:
            state = RoomState()
            for r in remaining:
                state = E.apply(state, {"type": r["type"], "payload": json.loads(r["payload"])})
        except Exception:
            raise EngineError("REVERT_CONFLICT",
                              "撤销该事件会使后续事件无法成立，请先撤销依赖它的事件") from None
        ev = {"type": "HOST_REVERTED",
              "payload": {"event_seq": target_seq, "reason": str(payload.get("reason", ""))}}
        self.seq += 1
        rid = self.db.append_event(self.room_id, self.seq, actor_id, ev["type"], ev["payload"])
        self.db.revoke_event(self.room_id, target_seq, rid)
        self.state = state           # HOST_REVERTED 本身不改状态，仅留审计痕迹
        return [ev]

    def _after_change(self) -> None:
        self.db.save_snapshot(self.room_id, self.seq,
                              self.state.model_dump_json())
        self.db.set_room_status(self.room_id, self.state.status.value)

    # ---------- 广播 ----------

    def serialize(self, viewer_id: str | None = None) -> dict:
        s = self.state
        players = []
        for pid in (s.turn_order or list(s.players)):
            p = s.players[pid]
            players.append({
                "id": p.id, "nickname": p.nickname, "seat": p.seat,
                "isHost": p.is_host, "phase": p.phase.value,
                "professionId": p.profession_id, "professionTitle": p.profession_title,
                "cash": p.cash, "childCount": p.child_count,
                "charityTurns": p.charity_turns, "skipTurns": p.skip_turns,
                "dreamId": p.dream_id, "inBankruptcy": p.in_bankruptcy,
                "salary": p.salary, "taxes": p.taxes,
                "mortgagePayment": p.mortgage_payment,
                "schoolLoanPayment": p.school_loan_payment,
                "carLoanPayment": p.car_loan_payment,
                "creditCardPayment": p.credit_card_payment,
                "extraExpenses": p.extra_expenses, "otherExpenses": p.other_expenses,
                "perChildExpense": p.per_child_expense,
                "interestIncome": p.interest_income,
                "stocks": [h.model_dump() for h in p.stocks],
                "realEstates": [a.model_dump() for a in p.real_estates],
                "businesses": [a.model_dump() for a in p.businesses],
                "extraLiabilities": [l.model_dump() for l in p.extra_liabilities],
                "liabilities": p.liabilities.model_dump(),
                "fasttrack": p.fasttrack.model_dump(),
                "derived": F.derived(p),
            })
        return {
            "roomCode": self.code,
            "status": s.status.value,
            "settings": s.settings.model_dump(),
            "players": players,
            "turnOrder": s.turn_order,
            "turnIndex": s.turn_index,
            "turnCount": s.turn_count,
            "currentPlayerId": s.current_player_id,
            "activeCard": s.active_card.model_dump() if s.active_card else None,
            "prompts": [p.model_dump() for p in s.prompts],
            "ftSoldSquares": s.ft_sold_squares,
            "dreamPriceBumps": s.dream_price_bumps,
            "winnerId": s.winner_id,
        }

    async def broadcast_state(self, last_events: list[dict] | None = None) -> None:
        msg = {"type": "state", "seq": self.seq, "state": self.serialize(),
               "lastEvents": last_events or []}
        data = json.dumps(msg, ensure_ascii=False)
        for conns in list(self.sockets.values()):
            for ws in list(conns):
                try:
                    await ws.send_text(data)
                except Exception:
                    conns.discard(ws)

    async def attach(self, player_id: str, ws: WebSocket) -> None:
        self.sockets.setdefault(player_id, set()).add(ws)
        snap = {"type": "snapshot", "seq": self.seq, "you": player_id,
                "state": self.serialize()}
        await ws.send_text(json.dumps(snap, ensure_ascii=False))

    def detach(self, player_id: str, ws: WebSocket) -> None:
        self.sockets.get(player_id, set()).discard(ws)

    def log_rows(self) -> list[dict]:
        rows = self.db.events_for_room(self.room_id, include_revoked=True)
        nick = {pid: p.nickname for pid, p in self.state.players.items()}
        out = []
        for r in rows:
            out.append({
                "seq": r["seq"],
                "actor": nick.get(r["actor_player_id"], r["actor_player_id"]),
                "type": r["type"],
                "payload": json.loads(r["payload"]),
                "at": r["created_at"],
                "revoked": r["revoked_by"] is not None,
            })
        return out


class RoomManager:
    def __init__(self, db: Database, lib: CardLibrary):
        self.db = db
        self.lib = lib
        self.rooms: dict[str, RoomSession] = {}       # code -> session

    def restore_all(self) -> None:
        for row in self.db.all_rooms():
            sess = RoomSession(row["id"], row["code"], self.db, self.lib)
            sess.restore()
            self.rooms[row["code"]] = sess

    async def create_room(self, name: str, host_nickname: str,
                          max_players: int = 6) -> dict:
        code = self._gen_code()
        room_id = uuid.uuid4().hex
        self.db.create_room(room_id, code, name, {"max_players": max_players})
        sess = RoomSession(room_id, code, self.db, self.lib)
        sess.state.settings.max_players = max_players
        sess.state.settings.name = name
        self.rooms[code] = sess
        host_id, token = await self._join(sess, host_nickname, is_host=True)
        return {"roomCode": code, "playerId": host_id, "playerToken": token}

    async def join_room(self, code: str, nickname: str) -> dict:
        sess = self.get(code)
        player_id, token = await self._join(sess, nickname, is_host=False)
        return {"roomCode": code, "playerId": player_id, "playerToken": token}

    async def _join(self, sess: RoomSession, nickname: str, is_host: bool):
        player_id = uuid.uuid4().hex[:12]
        token = secrets.token_urlsafe(24)
        await sess.handle_action(None, None, "JOIN", {
            "player_id": player_id, "nickname": nickname, "is_host": is_host})
        self.db.add_player(player_id, sess.room_id, nickname, _hash_token(token), is_host)
        return player_id, token

    def get(self, code: str) -> RoomSession:
        sess = self.rooms.get(code)
        if sess is None:
            raise EngineError("NO_ROOM", "房间不存在")
        return sess

    def auth(self, token: str) -> tuple[RoomSession, str]:
        row = self.db.find_player_by_token(_hash_token(token))
        if row is None:
            raise EngineError("BAD_TOKEN", "身份令牌无效")
        for sess in self.rooms.values():
            if sess.room_id == row["room_id"]:
                return sess, row["id"]
        raise EngineError("NO_ROOM", "房间不存在")

    def _gen_code(self) -> str:
        alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(4))
            if code not in self.rooms:
                return code
