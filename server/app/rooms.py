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

    # 市场卡的效果分好几条事件落地（design/06 §6.3）：抽出的一瞬间就伴随生成求购/强制效果，
    # 玩家的答复又是各自独立的后续行动。只撤单独一行会留下幽灵 MARKET_PROMPTED——
    # 重放时它照样把同一条求购 prompt 塞回去，弹层原样弹回，抽卡人回不到「重新选卡」。
    _MARKET_BATCH_TYPES = frozenset({
        "MARKET_PROMPTED", "CASHFLOW_MODIFIED", "ASSETS_SURRENDERED", "CARD_RESOLVED",
    })
    _MARKET_RESPONSE_TYPES = frozenset({
        "MARKET_SOLD", "MARKET_DECLINED", "INSTALLMENT_SCHEDULED",
    })

    def _market_cascade(self, rows: list[dict], target: dict, target_seq: int
                        ) -> tuple[set[int], set[int]]:
        """给定一条市场卡的 CARD_DRAWN，圈出同批伴随事件 + 后续答复事件的 seq 集合。

        返回 (撤销集合, 「别人做出的答复」所属 seq 集合)——后者用于本人更正时的权限判断。
        非市场卡直接返回只含自身的集合。
        """
        tp = json.loads(target["payload"])
        if target["type"] != "CARD_DRAWN" or tp.get("deck") != "MARKET":
            return {target_seq}, set()
        card_id = tp["card_id"]
        cascade = {target_seq}
        prompt_ids: set[str] = set()
        # 同一次 decide() 产出、seq 紧邻的伴随事件：房间级锁保证批内不会被其它行动插入。
        for r in rows:
            if r["seq"] <= target_seq or r["revoked_by"] is not None:
                continue
            rp = json.loads(r["payload"])
            if r["type"] in self._MARKET_BATCH_TYPES and rp.get("card_id") == card_id:
                cascade.add(r["seq"])
                if r["type"] == "MARKET_PROMPTED":
                    prompt_ids.add(rp["prompt_id"])
                continue
            break   # 遇到跟这张卡无关的行动，说明这一批已经结束
        # 答复可能是几秒后才提交的独立行动，不限于紧邻范围，要扫全量。
        other_response_seqs: set[int] = set()
        for r in rows:
            if r["revoked_by"] is not None or r["seq"] in cascade:
                continue
            if r["type"] not in self._MARKET_RESPONSE_TYPES:
                continue
            rp = json.loads(r["payload"])
            if rp.get("prompt_id") in prompt_ids:
                cascade.add(r["seq"])
                if r["actor_player_id"] != target["actor_player_id"]:
                    other_response_seqs.add(r["seq"])
        return cascade, other_response_seqs

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
            # 语义是「抽错卡当场撤销重选」（设计稿 §04），过了这个回合就只能请房主撤销：
            # 否则谁都能回头翻旧账，账本失去时序上的可信度。
            if self.state.current_player_id != actor_id:
                raise EngineError("NOT_YOUR_TURN", "只能在自己回合内更正，请房主在日志中撤销")
            # 回合边界只认 TURN_ENDED：靠 turn_count 反推会被停赛/出局玩家带偏。
            last_end = max((r["seq"] for r in rows
                            if r["type"] == "TURN_ENDED" and r["revoked_by"] is None),
                           default=0)
            if target_seq < last_end:
                raise EngineError("TURN_CLOSED", "该回合已结束，请房主在日志中撤销")
        target_seqs, other_response_seqs = self._market_cascade(rows, target, target_seq)
        if not as_host and other_response_seqs:
            # 别人对这张卡的求购要约已经做出了实质决定（卖/不卖/接受分期），
            # 不能靠抽卡人一句「选错卡」就悄悄把别人的选择也撤掉。
            raise EngineError("MARKET_RESPONDED", "已有其他玩家对这张卡做出回应，只能请房主在日志中撤销")
        remaining = [r for r in rows if r["seq"] not in target_seqs]
        try:
            state = RoomState()
            for r in remaining:
                state = E.apply(state, {"type": r["type"], "payload": json.loads(r["payload"])})
        except Exception:
            raise EngineError("REVERT_CONFLICT",
                              "撤销该事件会使后续事件无法成立，请先撤销依赖它的事件") from None
        # 被撤销事件的身份随审计事件一起下发：回执要能说出「撤销了哪一条、这条是谁的」，
        # 否则只能推给全员一句含糊的「有人更正了一条记录」（设计稿 §10 的六类触发之一）。
        tp = json.loads(target["payload"])
        ev = {"type": "HOST_REVERTED" if as_host else "PLAYER_CORRECTED",
              "payload": {"event_seq": target_seq, "reason": str(payload.get("reason", "")),
                          "target_type": target["type"],
                          "target_player_id": tp.get("player_id") or target["actor_player_id"],
                          "target_title": tp.get("title") or tp.get("name") or tp.get("symbol") or ""}}
        self.seq += 1
        rid = self.db.append_event(self.room_id, self.seq, actor_id, ev["type"], ev["payload"])
        # 同一批全部挂到这一条审计事件上：日志里这几行会一起被划线标记为「已撤销」。
        for seq in target_seqs:
            self.db.revoke_event(self.room_id, seq, rid)
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
                "installmentReceivables": [r.model_dump() for r in p.installment_receivables],
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
                            "settlePreview": E.settlement_preview(s, self.lib),
                            "stockOffer": E.stock_offer_preview(s, self.lib)}
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

    @property
    def online_ids(self) -> set[str]:
        """当前真正握着连接的玩家（断开的 socket 由 detach 摘掉，只留空集合）。"""
        return {pid for pid, conns in self.sockets.items() if conns}

    @property
    def online_count(self) -> int:
        return len(self.online_ids)

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
        """事件流 + 每行所属轮次（日志页按轮分组用）。

        轮次由引擎自身重放给出，零漂移：靠 TURN_ENDED 反推会被停赛/出局玩家带偏
        （_advance_turn 可能连跳好几个座位）。撤销行不参与重放——与 _revert 同一手法，
        否则重放出的状态和真实状态对不上。开局前的事件记 turn=0，前端显示「开局前」。
        """
        rows = self.db.events_for_room(self.room_id, include_revoked=True)
        nick = {pid: p.nickname for pid, p in self.state.players.items()}
        # revoked_by 存的是撤销事件的 rowid：反查一次，好让日志把撤销**画在被撤销那一行上**
        # （设计稿 §11：划线痕迹 +「已被房主撤销」），而不是另起一行。
        by_id = {r["id"]: r for r in rows}
        out = []
        state = RoomState()
        for r in rows:
            payload = json.loads(r["payload"])
            turn = state.turn_count if state.status is RoomStatus.PLAYING else 0
            if r["revoked_by"] is None:
                try:
                    state = E.apply(state, {"type": r["type"], "payload": payload})
                except Exception:
                    pass          # 日志是只读视图，重放不成也不能让整页拿不到
            revoker = by_id.get(r["revoked_by"]) if r["revoked_by"] is not None else None
            out.append({
                "seq": r["seq"],
                "turn": turn,
                "actorId": r["actor_player_id"],
                "actor": nick.get(r["actor_player_id"],
                                  payload.get("nickname", r["actor_player_id"])),
                "type": r["type"],
                "payload": payload,
                "at": r["created_at"],
                "revoked": r["revoked_by"] is not None,
                "revokedBy": (None if revoker is None else
                              ("host" if revoker["type"] == "HOST_REVERTED" else "self")),
                "revokedByActor": (None if revoker is None else
                                   nick.get(revoker["actor_player_id"])),
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
    EMPTY_TTL_S = 3600           # 从未开局又没人在线的空房：1h 直接删，别在大厅里越堆越多

    async def archive_idle(self, ttl_s: float | None = None,
                           now: float | None = None,
                           empty_ttl_s: float | None = None) -> dict[str, list[str]]:
        """定时清理（design/03 §7.2）。返回 {"archived": [...], "deleted": [...]}。

        - 24h 无活动的对局：断连、出内存、DB 标记 ARCHIVED，事件流保留可查，不再可加入。
        - 1h 无活动且无人在线的 LOBBY/SETUP 房：直接删。这类房间多半是建了没连上的
          空壳（没有值得留存的事件流），归档只会让它们在库里堆着。
        """
        ttl_s = self.ARCHIVE_TTL_S if ttl_s is None else ttl_s
        empty_ttl_s = self.EMPTY_TTL_S if empty_ttl_s is None else empty_ttl_s
        now = time.time() if now is None else now
        archived: list[str] = []
        deleted: list[str] = []
        for code, sess in list(self.rooms.items()):
            idle = now - sess.last_activity
            if sess.state.status in (RoomStatus.LOBBY, RoomStatus.SETUP) \
                    and sess.online_count == 0 and idle >= empty_ttl_s:
                await sess.close_sockets(code=4002)
                self.rooms.pop(code, None)
                self.db.delete_room(sess.room_id)
                deleted.append(code)
                continue
            if idle < ttl_s:
                continue
            await sess.close_sockets(code=4002)
            self.db.set_room_status(sess.room_id, "ARCHIVED")
            self.rooms.pop(code, None)
            archived.append(code)
        return {"archived": archived, "deleted": deleted}

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
            cur = s.players.get(s.current_player_id or "")
            out.append({
                "code": sess.code,
                "name": s.settings.name,
                "status": s.status.value,
                "playerCount": len(s.players),
                "maxPlayers": s.settings.max_players,
                "hasPassword": sess.password_hash is not None,
                "onlineCount": sess.online_count,
                # 大厅要写清「第几轮 · 轮到谁」，未开局的房间这两项没有意义
                "turnCount": s.turn_count if s.status is RoomStatus.PLAYING else 0,
                "currentPlayer": cur.nickname if s.status is RoomStatus.PLAYING and cur else None,
                "createdAt": sess.created_at,
            })
        out.sort(key=lambda r: r["createdAt"], reverse=True)
        return out

    def seats(self, code: str) -> dict:
        """加入页/接管选座用的房间概要（不泄露令牌等敏感信息）。"""
        sess = self.get(code)
        s = sess.state
        online = sess.online_ids
        return {
            "code": sess.code,
            "name": s.settings.name,
            "status": s.status.value,
            "hasPassword": sess.password_hash is not None,
            "maxPlayers": s.settings.max_players,
            "onlineCount": len(online),
            # online：这个座位现在有没有设备连着——换设备恢复时用来提醒「原设备将下线」
            "players": [{"id": p.id, "nickname": p.nickname, "isHost": p.is_host,
                         "professionTitle": p.profession_title,
                         "online": p.id in online}
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
        """删除房间：FINISHED/CLOSED 任何人可删；否则需房主令牌、房间密码，
        或「无密码 + 尚未开局 + 当前无人在线」——房主清了浏览器缓存的无密码房，
        否则谁都删不掉（令牌没了，又没有密码这条路），只能在大厅里挂满一天。"""
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
            if not allowed and sess.password_hash is None \
                    and sess.state.status in (RoomStatus.LOBBY, RoomStatus.SETUP) \
                    and sess.online_count == 0:
                # 空壳房间：没设密码、没开局、没人连着，删掉不会打断任何人。
                # 设了密码的房间不走这条——密码就是为了拦住「不相干的人动我的房间」。
                allowed = True
            if not allowed:
                raise EngineError(
                    "FORBIDDEN", "只有房主、房间密码，或房间无人在线时才能删除该房间")
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
