"""普通玩家主动退出：大厅释放名额、对局中出局与令牌失效。"""
from __future__ import annotations

import asyncio

import pytest

from ...rooms import RoomManager
from ...store.db import Database
from ..errors import EngineError
from ..models import Phase, RoomStatus


def _setup_duo(game):
    game.act(None, "JOIN", player_id="A", nickname="房主", is_host=True)
    game.act(None, "JOIN", player_id="B", nickname="玩家")
    game.act("A", "SELECT_PROFESSION", professionId="prof-006")
    game.act("B", "SELECT_PROFESSION", professionId="prof-010")
    game.act("A", "SELECT_DREAM", dreamId="ft-d-safari")
    game.act("B", "SELECT_DREAM", dreamId="ft-d-jet")


def test_leave_lobby_releases_player_name_profession_and_dream(game):
    _setup_duo(game)
    game.act("B", "LEAVE_GAME")

    assert "B" not in game.state.players
    game.act(None, "JOIN", player_id="C", nickname="玩家")
    game.act("C", "SELECT_PROFESSION", professionId="prof-010")
    game.act("C", "SELECT_DREAM", dreamId="ft-d-jet")


def test_leave_setup_keeps_remaining_order_and_new_join_requires_reorder(game):
    _setup_duo(game)
    game.act("A", "SET_TURN_ORDER", order=["A", "B"])
    assert game.state.status == RoomStatus.SETUP

    game.act("B", "LEAVE_GAME")
    assert game.state.turn_order == ["A"]
    assert game.state.status == RoomStatus.SETUP

    game.act(None, "JOIN", player_id="C", nickname="新玩家")
    assert game.state.status == RoomStatus.LOBBY
    assert game.state.turn_order == []


def test_only_regular_player_can_leave_and_repeat_is_rejected(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("A", "LEAVE_GAME")
    assert ei.value.code == "HOST_CANNOT_LEAVE"

    duo.act("B", "LEAVE_GAME")
    assert duo.player("B").phase == Phase.OUT
    with pytest.raises(EngineError) as ei:
        duo.act("B", "LEAVE_GAME")
    assert ei.value.code == "ALREADY_LEFT"


def test_host_leave_lobby_promotes_remaining_player(game):
    _setup_duo(game)
    game.act("A", "LEAVE_GAME")

    assert "A" not in game.state.players
    assert game.state.players["B"].is_host is True


def test_host_leave_lobby_promotes_earliest_seat_not_arbitrary(game):
    game.act(None, "JOIN", player_id="A", nickname="房主", is_host=True)
    game.act(None, "JOIN", player_id="B", nickname="老二")
    game.act(None, "JOIN", player_id="C", nickname="老三")

    game.act("A", "LEAVE_GAME")

    assert game.state.players["B"].is_host is True
    assert game.state.players["C"].is_host is False


def test_host_leave_lobby_alone_empties_room_without_error(game):
    game.act(None, "JOIN", player_id="A", nickname="房主", is_host=True)
    game.act("A", "LEAVE_GAME")
    assert game.state.players == {}


def test_current_player_leave_clears_pending_work_advances_and_replays(duo):
    duo.act("A", "TRANSFER_REQUEST", toPlayerId="B", amount=1000, reason="测试")
    duo.act("A", "END_TURN")
    duo.act("B", "DRAW_CARD", cardId="dd-003")

    duo.act("B", "LEAVE_GAME")

    assert duo.state.active_card is None
    assert duo.state.prompts == []
    assert duo.state.turn_index == 0
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "A"
    assert duo.replay().model_dump() == duo.state.model_dump()


def test_leaving_closed_room_is_rejected(duo):
    duo.act("A", "END_GAME")
    with pytest.raises(EngineError) as ei:
        duo.act("B", "LEAVE_GAME")
    assert ei.value.code == "NOT_LEAVABLE"


def test_leave_revokes_token_blocks_takeover_and_host_revert_restores_seat(lib, tmp_path):
    manager = RoomManager(Database(tmp_path / "leave.db"), lib)
    host = asyncio.run(manager.create_room("测试局", "房主"))
    guest = asyncio.run(manager.join_room(host["roomCode"], "玩家"))
    sess = manager.get(host["roomCode"])

    asyncio.run(sess.handle_action(guest["playerId"], None, "LEAVE_GAME", {}))
    with pytest.raises(EngineError) as ei:
        manager.auth(guest["playerToken"])
    assert ei.value.code == "BAD_TOKEN"
    with pytest.raises(EngineError) as ei:
        asyncio.run(manager.takeover(host["roomCode"], guest["playerId"]))
    assert ei.value.code == "NO_PLAYER"

    leave_seq = sess.seq
    asyncio.run(sess.handle_action(host["playerId"], None, "HOST_REVERT",
                                    {"eventSeq": leave_seq, "reason": "误退"}))
    restored = asyncio.run(manager.takeover(host["roomCode"], guest["playerId"]))
    assert restored["playerId"] == guest["playerId"]


def test_host_leave_lobby_new_host_can_delete_room_with_own_token(lib, tmp_path):
    """房主转让后，delete_room 的令牌校验（依赖 DB 侧 is_host）必须认得新房主。

    房间要设密码：无密码的空房间任何人都能删（delete_room 的空壳分支），
    那条路会把令牌校验整个绕过去，这个用例就测不到东西了。
    """
    manager = RoomManager(Database(tmp_path / "leave_host_delete.db"), lib)
    host = asyncio.run(manager.create_room("测试局", "房主", 6, "8888"))
    guest = asyncio.run(manager.join_room(host["roomCode"], "玩家", "8888"))
    sess = manager.get(host["roomCode"])

    asyncio.run(sess.handle_action(host["playerId"], None, "LEAVE_GAME", {}))
    assert sess.state.players[guest["playerId"]].is_host is True

    asyncio.run(manager.delete_room(host["roomCode"], token=guest["playerToken"]))
    assert host["roomCode"] not in manager.rooms


def test_host_revert_after_host_leave_restores_original_host(lib, tmp_path):
    # 同上：带密码才能验到「令牌不再是房主」，否则会被空房间可删的分支放行
    manager = RoomManager(Database(tmp_path / "leave_host_revert.db"), lib)
    host = asyncio.run(manager.create_room("测试局", "房主", 6, "8888"))
    guest = asyncio.run(manager.join_room(host["roomCode"], "玩家", "8888"))
    sess = manager.get(host["roomCode"])

    asyncio.run(sess.handle_action(host["playerId"], None, "LEAVE_GAME", {}))
    assert sess.state.players[guest["playerId"]].is_host is True

    leave_seq = sess.seq
    asyncio.run(sess.handle_action(guest["playerId"], None, "HOST_REVERT",
                                    {"eventSeq": leave_seq, "reason": "误退"}))
    assert sess.state.players[host["playerId"]].is_host is True
    assert sess.state.players[guest["playerId"]].is_host is False

    # 被撤销转让的旧房主令牌已在离开时作废，须通过接管拿回身份；
    # 而被撤销晋升的原访客不应再凭自己的令牌拥有 delete_room 的房主权限。
    restored = asyncio.run(manager.takeover(host["roomCode"], host["playerId"], "8888"))
    assert restored["playerId"] == host["playerId"]
    with pytest.raises(EngineError) as ei:
        asyncio.run(manager.delete_room(host["roomCode"], token=guest["playerToken"]))
    assert ei.value.code == "FORBIDDEN"


def test_host_leave_lobby_alone_deletes_room(lib, tmp_path):
    manager = RoomManager(Database(tmp_path / "leave_solo.db"), lib)
    host = asyncio.run(manager.create_room("测试局", "房主"))
    sess = manager.get(host["roomCode"])

    asyncio.run(sess.handle_action(host["playerId"], None, "LEAVE_GAME", {}))

    assert host["roomCode"] not in manager.rooms
    assert not any(r["code"] == host["roomCode"] for r in manager.list_rooms())
    assert manager.db.find_room_by_code(host["roomCode"]) is None
