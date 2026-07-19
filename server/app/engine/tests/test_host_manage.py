"""房主对局管理：结束对局（END_GAME）/ 移除玩家（HOST_REMOVE_PLAYER）/ 代结束回合（HOST_END_TURN）。"""
from __future__ import annotations

import asyncio

import pytest

from ...rooms import RoomManager
from ...store.db import Database
from ..errors import EngineError
from ..models import Phase, RoomStatus


# ---------- 结束对局 ----------

def test_end_game_requires_host(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("B", "END_GAME")
    assert ei.value.code == "NOT_HOST"


def test_end_game_closes_room(duo):
    duo.act("A", "END_GAME")
    assert duo.state.status == RoomStatus.CLOSED
    # 结束后任何玩家行动被拒
    with pytest.raises(EngineError) as ei:
        duo.act("A", "END_TURN")
    assert ei.value.code == "NOT_PLAYING"
    # 重复结束被拒
    with pytest.raises(EngineError) as ei:
        duo.act("A", "END_GAME")
    assert ei.value.code == "ALREADY_CLOSED"
    # 含 GAME_ENDED 的事件流可完整重放
    assert duo.replay().model_dump() == duo.state.model_dump()


def test_end_game_in_lobby(game):
    """大厅阶段也能解散房间（不必开局）。"""
    game.act(None, "JOIN", player_id="A", nickname="阿呆", is_host=True)
    game.act(None, "JOIN", player_id="B", nickname="阿瓜")
    game.act("A", "END_GAME")
    assert game.state.status == RoomStatus.CLOSED


# ---------- 移除玩家 ----------

def test_remove_requires_host(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("B", "HOST_REMOVE_PLAYER", playerId="A")
    assert ei.value.code == "NOT_HOST"


def test_remove_self_rejected(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("A", "HOST_REMOVE_PLAYER", playerId="A")
    assert ei.value.code == "BAD_TARGET"


def test_remove_already_out_rejected(duo):
    duo.state.players["B"].phase = Phase.OUT
    with pytest.raises(EngineError) as ei:
        duo.act("A", "HOST_REMOVE_PLAYER", playerId="B")
    assert ei.value.code == "BAD_TARGET"


def test_remove_current_player_advances_turn(duo):
    """移除当前玩家：清 TA 的提示与未结算卡、回合推进；两人局只剩一人按规则判胜。"""
    duo.act("A", "TRANSFER_REQUEST", toPlayerId="B", amount=1000, reason="测试")
    duo.act("A", "END_TURN")                          # 轮到 B
    duo.act("B", "DRAW_CARD", cardId="dd-tv")         # B 留下未结算的强制卡
    assert duo.state.active_card is not None
    duo.act("A", "HOST_REMOVE_PLAYER", playerId="B")
    b = duo.player("B")
    assert b.phase == Phase.OUT
    assert duo.state.active_card is None
    assert duo.state.prompts == []                    # 目标为 B 的转账确认被清
    assert duo.state.turn_index == 0                  # 指针推进回 A
    # 两人局只剩 1 人 → 对局结束，A 获胜
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "A"
    assert duo.replay().model_dump() == duo.state.model_dump()


# ---------- 代结束回合 ----------

def test_host_end_turn_requires_host(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("B", "HOST_END_TURN")
    assert ei.value.code == "NOT_HOST"


def test_host_end_turn_advances(duo):
    duo.act("A", "END_TURN")
    assert duo.state.current_player_id == "B"
    duo.act("A", "HOST_END_TURN")                     # 房主代 B 结束
    assert duo.state.current_player_id == "A"


def test_host_end_turn_discards_unresolved_card(duo):
    """当前玩家留着未结算的强制卡：本人结束被拒，房主代结束时卡作废并推进。"""
    duo.act("A", "END_TURN")
    duo.act("B", "DRAW_CARD", cardId="dd-tv")
    with pytest.raises(EngineError) as ei:
        duo.act("B", "END_TURN")
    assert ei.value.code == "CARD_UNRESOLVED"
    duo.act("A", "HOST_END_TURN")
    assert duo.state.active_card is None
    assert duo.state.current_player_id == "A"
    assert duo.replay().model_dump() == duo.state.model_dump()


# ---------- 重启恢复 ----------

def test_closed_room_not_restored(lib, tmp_path):
    """房主结束后的房间：状态落库为 CLOSED，重启不再恢复。"""
    db = Database(tmp_path / "t.db")
    mgr = RoomManager(db, lib)
    r = asyncio.run(mgr.create_room("收尾", "阿呆"))
    sess = mgr.get(r["roomCode"])
    asyncio.run(sess.handle_action(r["playerId"], None, "END_GAME", {}))
    assert sess.state.status == RoomStatus.CLOSED

    mgr2 = RoomManager(db, lib)
    mgr2.restore_all()
    assert r["roomCode"] not in mgr2.rooms
