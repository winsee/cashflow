"""再来一局 REMATCH（就地重开）：结束后同一房间重置为准备阶段，保留玩家身份，全员重选职业。

设计见 design/07 交接 / 计划文件。红线：REMATCH 事件必须可回放（事件溯源自洽）。
"""
import pytest

from .conftest import Game
from ..errors import EngineError
from ..models import Phase, RealEstate, RoomStatus


def _finish(duo, winner="A"):
    """把两人局强制推到 FINISHED（两名玩家仍在老鼠赛跑），用于验证重置逻辑。"""
    duo.state.status = RoomStatus.FINISHED
    duo.state.winner_id = winner


def test_rematch_full_cycle(duo):
    """结束 → 再来一局 → 房间回到准备阶段、账目清空、可重新完整开一局。"""
    # 造点会被清空的痕迹：现金、孩子、资产、当前卡
    duo.state.players["A"].cash = 99999
    duo.state.players["A"].child_count = 2
    duo.player("A").real_estates.append(RealEstate(
        id="r1", card_id="x", asset_type="房", name="旧房", cost=100, down_payment=10, cashflow=50))
    _finish(duo, winner="A")

    duo.act("A", "REMATCH")

    s = duo.state
    assert s.status == RoomStatus.LOBBY
    assert set(s.players) == {"A", "B"}                 # 两名未出局玩家保留
    a, b = duo.player("A"), duo.player("B")
    assert a.is_host and a.nickname == "阿呆"            # 身份/昵称保留
    assert not b.is_host and b.nickname == "阿瓜"
    # 游戏态彻底清空
    assert a.profession_id is None and a.dream_id is None
    assert a.cash == 0 and a.child_count == 0 and a.real_estates == []
    assert a.phase == Phase.RAT_RACE
    assert s.turn_order == [] and s.turn_index == 0 and s.turn_count == 1
    assert s.winner_id is None and s.active_card is None and s.prompts == []
    assert sorted(p.seat for p in s.players.values()) == [0, 1]   # 座位重排 0..n

    # 能重新完整开一局，并重新发钱
    duo.act("A", "SELECT_PROFESSION", professionId="prof-006")
    duo.act("B", "SELECT_PROFESSION", professionId="prof-010")
    duo.act("A", "SELECT_DREAM", dreamId="ft-d-safari")
    duo.act("B", "SELECT_DREAM", dreamId="ft-d-jet")
    duo.act("A", "SET_TURN_ORDER", order=["A", "B"])
    duo.act("A", "START_GAME")
    assert duo.state.status == RoomStatus.PLAYING
    assert duo.player("A").cash == 3550 + 400           # 月现金流 + 储蓄，重新发钱

    # 事件溯源自洽：整段日志（含 REMATCH）重放 == 当前状态
    assert duo.replay().model_dump() == duo.state.model_dump()


def test_rematch_requires_finished(duo):
    """对局进行中（PLAYING）不能再来一局。"""
    with pytest.raises(EngineError) as ei:
        duo.act("A", "REMATCH")
    assert ei.value.code == "NOT_FINISHED"


def test_rematch_host_only(duo):
    """只有房主能发起再来一局。"""
    _finish(duo, winner="A")
    with pytest.raises(EngineError) as ei:
        duo.act("B", "REMATCH")
    assert ei.value.code == "NOT_HOST"


def test_rematch_drops_eliminated_players(lib):
    """被踢/出局的非房主玩家不带入下一局；房主与未出局玩家保留。"""
    g = Game(lib)
    for pid, nick, host in [("A", "阿呆", True), ("B", "阿瓜", False), ("C", "阿丙", False)]:
        g.act(None, "JOIN", player_id=pid, nickname=nick, is_host=host)
    g.act("A", "SELECT_PROFESSION", professionId="prof-006")
    g.act("B", "SELECT_PROFESSION", professionId="prof-010")
    g.act("C", "SELECT_PROFESSION", professionId="prof-003")
    g.act("A", "SELECT_DREAM", dreamId="ft-d-safari")
    g.act("B", "SELECT_DREAM", dreamId="ft-d-jet")
    g.act("C", "SELECT_DREAM", dreamId="ft-d-golf")
    g.act("A", "SET_TURN_ORDER", order=["A", "B", "C"])
    g.act("A", "START_GAME")
    g.act("A", "HOST_REMOVE_PLAYER", playerId="C")       # C → OUT（仍 A、B 存活，PLAYING）
    assert g.state.status == RoomStatus.PLAYING
    g.state.status = RoomStatus.FINISHED                 # 强制结束（A、B 仍在）
    g.state.winner_id = "A"

    g.act("A", "REMATCH")

    assert set(g.state.players) == {"A", "B"}            # C 被剔除
    assert g.player("A").is_host
    assert sorted(p.seat for p in g.state.players.values()) == [0, 1]
    assert g.replay().model_dump() == g.state.model_dump()
