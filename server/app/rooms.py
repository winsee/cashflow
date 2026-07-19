"""房间会话管理：内存态 + 事件持久化 + WS 广播（design/03 §4、§6）。

服务器权威：客户端只发意图（action），一切状态变更 = decide → append(event) → apply。
崩溃恢复：启动时对每个房间重放未撤销事件重建状态。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from typing import Any

from fastapi import WebSocket

from .data_loader import CardLibrary
from .engine import engine as E
from .engine import formulas as F
from .engine.errors import EngineError
from .engine.models import Phase, RoomState, RoomStatus
from .store.db import Database


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RoomSession:
    def __init__(self, room_id: str, code: str, db: Database, lib: CardLibrary,
                 password_hash: str | None = None, created_at: str = ""):
        self.room_id = room_id
        self.code = code
        self.db = db
        self.lib = lib
        self.password_hash = password_hash   # 只存服务端，绝不进 RoomState/广播
        self.created_at = created_at
        self.state = RoomState()
        self.seq = 0
        self.lock = asyncio.Lock()
        self.sockets: dict[str, set[WebSocket]] = {}   # player_id -> conns
        self.manager: RoomManager | None = None   # 房主独自退出时需要从管理器里摘除自己
        self.last_activity = time.time()          # 24h 无活动自动归档（design/03 §7.2）

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
        self.last_activity = time.time()
        async with self.lock:
            if action_id:
                cached = self.db.dedupe_get(self.room_id, action_id)
                if cached:
                    return json.loads(cached["result"])
            if action_type in ("HOST_REVERT", "PLAYER_CORRECT"):
                events = self._revert(actor_id, payload,
                                      as_host=action_type == "HOST_REVERT")
            else:
                events = E.decide(self.state, actor_id, action_type, payload, self.lib)
                for ev in events:
                    self.seq += 1
                    self.db.append_event(self.room_id, self.seq, actor_id,
                                         ev["type"], ev["payload"])
                    self.state = E.apply(self.state, ev)
                    if ev["type"] == "PLAYER_LEFT":
                        # 主动退出后废弃原令牌；即使旧 WebSocket 尚未关闭，也无法重连。
                        self.db.update_player_token(
                            ev["payload"]["player_id"],
                            _hash_token(secrets.token_urlsafe(24)))
                        new_host_id = ev["payload"].get("new_host_id")
                        if new_host_id:
                            self.db.set_player_host(new_host_id, True)
            self._after_change()
            if action_id:
                self.db.dedupe_put(self.room_id, action_id, json.dumps(events, ensure_ascii=False))
            if self.state.status in (RoomStatus.LOBBY, RoomStatus.SETUP) and not self.state.players:
                # 大厅/准备阶段的最后一人（此时必为房主）离开：视为解散房间，与 RoomManager.delete_room 一致。
                # 排除发起者自己的连接：main.py 还要在这条连接上回发 ack，
                # 若在此处一并关闭，客户端收不到 ack，只能靠前端 5s 兜底超时才跳转大厅。
                # 客户端收到 ack 后会自行 clearSession() 关闭连接，服务端无需代劳。
                await self.close_sockets(exclude_player_id=actor_id)
                if self.manager is not None:
                    self.manager.rooms.pop(self.code, None)
                self.db.delete_room(self.room_id)
                return events
            await self.broadcast_state(last_events=events)
            return events

    # FR-29：本人可自我更正的事件类型 = 卡牌入账类（选错卡的后果都落在这些事件上）
    CORRECTABLE_TYPES = frozenset({
        "CARD_DRAWN", "CARD_RESOLVED", "CARD_PASSED",
        "ASSET_BOUGHT", "DOODAD_PAID", "INSTALLMENT_ADDED",
        "LOSS_PAID", "EXPENSE_EVENT_PAID",
        "STOCK_BOUGHT", "STOCK_SOLD", "SHARES_ADJUSTED",
        "MARKET_SOLD", "MARKET_DECLINED",
    })

    def _revert(self, actor_id: str, payload: dict, as_host: bool) -> list[dict]:
        actor = self.state.players.get(actor_id)
        if actor is None:
            raise EngineError("NOT_IN_ROOM", "你不在本房间")
        if as_host and not actor.is_host:
            raise EngineError("NOT_HOST", "只有房主能撤销事件")
        target_seq = int(payload["eventSeq"])
        # 先试重放：撤销后事件流必须仍然可应用，否则拒绝
        rows = self.db.events_for_room(self.room_id)
        target = next((r for r in rows if r["seq"] == target_seq), None)
        if target is None:
            raise EngineError("NO_EVENT", "目标事件不存在或已被撤销")
        if not as_host:
            # 本人更正（FR-29）：只能撤自己的卡牌入账事件
            if target["actor_player_id"] != actor_id:
                raise EngineError("NOT_YOURS", "只能更正自己的操作，或请房主撤销")
            if target["type"] not in self.CORRECTABLE_TYPES:
                raise EngineError("NOT_CORRECTABLE", "该类事件不支持本人更正，请房主撤销")
        remaining = [r for r in rows if r["seq"] != target_seq]
        try:
            state = RoomState()
            for r in remaining:
                state = E.apply(state, {"type": r["type"], "payload": json.loads(r["payload"])})
        except Exception:
            raise EngineError("REVERT_CONFLICT",
                              "撤销该事件会使后续事件无法成立，请先撤销依赖它的事件") from None
        ev = {"type": "HOST_REVERTED" if as_host else "PLAYER_CORRECTED",
              "payload": {"event_seq": target_seq, "reason": str(payload.get("reason", ""))}}
        self.seq += 1
        rid = self.db.append_event(self.room_id, self.seq, actor_id, ev["type"], ev["payload"])
        self.db.revoke_event(self.room_id, target_seq, rid)
        self.state = state           # HOST_REVERTED 本身不改状态，仅留审计痕迹
        # 撤销可能撤掉了一次房主转让：把 DB 侧的 is_host 重新对齐到重放后的状态，
        # 否则被撤销转让的旧房主令牌仍会被 delete_room 当作房主凭证。
        for pid, pl in self.state.players.items():
            self.db.set_player_host(pid, pl.is_host)
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
            "turnSquareUsed": s.turn_square_used,
            "turnPaydayUsed": s.turn_payday_used,
            "currentPlayerId": s.current_player_id,
            "activeCard": ({**s.active_card.model_dump(),
                            "settlePreview": E.settlement_preview(s, self.lib)}
                           if s.active_card else None),
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
        self.last_activity = time.time()
        self.sockets.setdefault(player_id, set()).add(ws)
        snap = {"type": "snapshot", "seq": self.seq, "you": player_id,
                "state": self.serialize()}
        await ws.send_text(json.dumps(snap, ensure_ascii=False))

    def detach(self, player_id: str, ws: WebSocket) -> None:
        self.sockets.get(player_id, set()).discard(ws)

    def check_password(self, password: str | None) -> bool:
        """无密码房间恒通过；有密码房间要求明文匹配。"""
        if self.password_hash is None:
            return True
        return password is not None and _hash_token(password) == self.password_hash

    async def close_sockets(self, player_id: str | None = None, code: int = 4000,
                            exclude_player_id: str | None = None) -> None:
        """断开指定玩家（或全部）的连接：座位接管/房间删除时用。

        exclude_player_id：保留该玩家自己的连接不主动关闭（例如它还等着收 ack）。
        """
        if player_id:
            targets = [self.sockets.get(player_id, set())]
        else:
            targets = [conns for pid, conns in self.sockets.items() if pid != exclude_player_id]
        for conns in targets:
            for ws in list(conns):
                try:
                    await ws.close(code=code)
                except Exception:
                    pass
            conns.clear()

    def log_rows(self) -> list[dict]:
        rows = self.db.events_for_room(self.room_id, include_revoked=True)
        nick = {pid: p.nickname for pid, p in self.state.players.items()}
        out = []
        for r in rows:
            payload = json.loads(r["payload"])
            out.append({
                "seq": r["seq"],
                "actorId": r["actor_player_id"],
                "actor": nick.get(r["actor_player_id"],
                                  payload.get("nickname", r["actor_player_id"])),
                "type": r["type"],
                "payload": payload,
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
            if row["status"] in ("CLOSED", "ARCHIVED"):
                continue     # 已结束/已归档的对局不再恢复（事件流保留在库中可查）
            sess = RoomSession(row["id"], row["code"], self.db, self.lib,
                               password_hash=row["password_hash"],
                               created_at=row["created_at"] or "")
            sess.manager = self
            sess.restore()
            self.rooms[row["code"]] = sess

    ARCHIVE_TTL_S = 24 * 3600

    async def archive_idle(self, ttl_s: float | None = None,
                           now: float | None = None) -> list[str]:
        """24h 无活动的房间自动归档（design/03 §7.2）：断连、出内存、DB 标记；
        事件流保留可查，但不再可加入/恢复。返回被归档的房间码。"""
        ttl_s = self.ARCHIVE_TTL_S if ttl_s is None else ttl_s
        now = time.time() if now is None else now
        archived = []
        for code, sess in list(self.rooms.items()):
            if now - sess.last_activity < ttl_s:
                continue
            await sess.close_sockets(code=4002)
            self.db.set_room_status(sess.room_id, "ARCHIVED")
            self.rooms.pop(code, None)
            archived.append(code)
        return archived

    async def create_room(self, name: str, host_nickname: str,
                          max_players: int = 6,
                          password: str | None = None) -> dict:
        code = self._gen_code()
        room_id = uuid.uuid4().hex
        pw_hash = _hash_token(password) if password else None
        self.db.create_room(room_id, code, name, {"max_players": max_players}, pw_hash)
        row = self.db.find_room_by_code(code)
        sess = RoomSession(room_id, code, self.db, self.lib,
                           password_hash=pw_hash,
                           created_at=row["created_at"] or "")
        sess.manager = self
        sess.state.settings.max_players = max_players
        sess.state.settings.name = name
        self.rooms[code] = sess
        host_id, token = await self._join(sess, host_nickname, is_host=True)
        return {"roomCode": code, "playerId": host_id, "playerToken": token}

    async def join_room(self, code: str, nickname: str,
                        password: str | None = None) -> dict:
        sess = self.get(code)
        if not sess.check_password(password):
            raise EngineError("BAD_PASSWORD", "房间密码错误")
        player_id, token = await self._join(sess, nickname, is_host=False)
        return {"roomCode": code, "playerId": player_id, "playerToken": token}

    def list_rooms(self) -> list[dict]:
        """大厅列表：按创建时间倒序。"""
        out = []
        for sess in self.rooms.values():
            s = sess.state
            out.append({
                "code": sess.code,
                "name": s.settings.name,
                "status": s.status.value,
                "playerCount": len(s.players),
                "maxPlayers": s.settings.max_players,
                "hasPassword": sess.password_hash is not None,
                "createdAt": sess.created_at,
            })
        out.sort(key=lambda r: r["createdAt"], reverse=True)
        return out

    def seats(self, code: str) -> dict:
        """加入页/接管选座用的房间概要（不泄露令牌等敏感信息）。"""
        sess = self.get(code)
        s = sess.state
        return {
            "code": sess.code,
            "name": s.settings.name,
            "status": s.status.value,
            "hasPassword": sess.password_hash is not None,
            "maxPlayers": s.settings.max_players,
            "players": [{"id": p.id, "nickname": p.nickname, "isHost": p.is_host,
                         "professionTitle": p.profession_title}
                        for p in s.players.values()],
        }

    async def takeover(self, code: str, player_id: str,
                       password: str | None = None) -> dict:
        """凭房间密码接管已有座位（换设备恢复身份）：重发令牌，旧令牌作废。

        不产生引擎事件——身份是传输层概念，游戏状态不变。
        """
        sess = self.get(code)
        if not sess.check_password(password):
            raise EngineError("BAD_PASSWORD", "房间密码错误")
        player = sess.state.players.get(player_id)
        if player is None:
            raise EngineError("NO_PLAYER", "该座位不存在")
        if player.phase == Phase.OUT:
            raise EngineError("PLAYER_OUT", "该玩家已退出，不能接管座位")
        token = secrets.token_urlsafe(24)
        self.db.update_player_token(player_id, _hash_token(token))
        await sess.close_sockets(player_id)   # 原设备立即断线，冒领当场暴露
        return {"roomCode": code, "playerId": player_id, "playerToken": token}

    async def delete_room(self, code: str, token: str | None = None,
                          password: str | None = None) -> None:
        """删除房间：FINISHED/CLOSED 任何人可删；否则需房主令牌或房间密码。"""
        sess = self.get(code)
        if sess.state.status not in (RoomStatus.FINISHED, RoomStatus.CLOSED):
            allowed = False
            if token:
                row = self.db.find_player_by_token(_hash_token(token))
                if row and row["room_id"] == sess.room_id and row["is_host"]:
                    allowed = True
            if not allowed and sess.password_hash is not None \
                    and sess.check_password(password):
                allowed = True
            if not allowed:
                raise EngineError("FORBIDDEN", "只有房主或输入房间密码才能删除进行中的房间")
        await sess.close_sockets()
        self.rooms.pop(code, None)
        self.db.delete_room(sess.room_id)

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
