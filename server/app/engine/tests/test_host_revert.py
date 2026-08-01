"""房主撤销（HOST_REVERT）回归：连续撤销、重启恢复、真依赖冲突（FR-22）。

走真实 RoomSession + SQLite，覆盖 rooms.py 的试重放校验路径。
"""
from __future__ import annotations

import asyncio

import pytest

from ...rooms import RoomManager, RoomSession
from ...store.db import Database
from ..errors import EngineError


@pytest.fixture
def mgr(lib, tmp_path):
    return RoomManager(Database(tmp_path / "t.db"), lib)


def _setup(mgr):
    """两人局开局完成，返回 (session, A_id, B_id)。"""
    r = asyncio.run(mgr.create_room("撤销回归", "阿呆"))
    r2 = asyncio.run(mgr.join_room(r["roomCode"], "阿瓜"))
    sess = mgr.get(r["roomCode"])
    a, b = r["playerId"], r2["playerId"]

    def act(actor, atype, **payload):
        return asyncio.run(sess.handle_action(actor, None, atype, payload))

    act(a, "SELECT_PROFESSION", professionId="prof-006")
    act(b, "SELECT_PROFESSION", professionId="prof-010")
    act(a, "SELECT_DREAM", dreamId="ft-d-safari")
    act(b, "SELECT_DREAM", dreamId="ft-d-jet")
    act(a, "SET_TURN_ORDER", order=[a, b])
    act(a, "START_GAME")
    return sess, a, b, act


def _seq_of(sess, etype: str, **payload_match) -> int:
    rows = sess.db.events_for_room(sess.room_id)
    import json
    for r in rows:
        if r["type"] == etype:
            p = json.loads(r["payload"])
            if all(p.get(k) == v for k, v in payload_match.items()):
                return r["seq"]
    raise AssertionError(f"未找到事件 {etype} {payload_match}")


def test_consecutive_reverts(mgr):
    """撤销一次后再撤销另一笔独立事件必须成功（曾因 HOST_REVERTED 无 applier 全部误报冲突）。"""
    sess, a, b, act = _setup(mgr)
    cash0 = sess.state.players[a].cash
    act(a, "TAKE_LOAN", amount=1000)
    act(a, "TAKE_LOAN", amount=2000)
    s1 = _seq_of(sess, "LOAN_TAKEN", amount=1000)
    s2 = _seq_of(sess, "LOAN_TAKEN", amount=2000)

    act(a, "HOST_REVERT", eventSeq=s1)
    assert sess.state.players[a].cash == cash0 + 2000
    assert sess.state.players[a].liabilities.bank_loan == 2000

    act(a, "HOST_REVERT", eventSeq=s2)          # 第二次撤销：修复前在这里报 REVERT_CONFLICT
    assert sess.state.players[a].cash == cash0
    assert sess.state.players[a].liabilities.bank_loan == 0


def test_restore_after_revert(mgr):
    """撤销过事件的房间重启恢复（restore 重放全流）不崩且状态一致。"""
    sess, a, b, act = _setup(mgr)
    act(a, "TAKE_LOAN", amount=3000)
    act(a, "HOST_REVERT", eventSeq=_seq_of(sess, "LOAN_TAKEN", amount=3000))

    fresh = RoomSession(sess.room_id, sess.code, sess.db, sess.lib)
    fresh.restore()                              # 修复前：UNKNOWN_EVENT 崩溃
    assert fresh.state.model_dump() == sess.state.model_dump()
    assert fresh.seq == sess.seq


def test_true_conflict_still_rejected(mgr):
    """真依赖冲突仍要被拒：撤销 B 的加入会使其后续选职业等事件无法成立。"""
    sess, a, b, act = _setup(mgr)
    act(a, "TAKE_LOAN", amount=1000)
    act(a, "HOST_REVERT", eventSeq=_seq_of(sess, "LOAN_TAKEN", amount=1000))
    with pytest.raises(EngineError) as ei:
        act(a, "HOST_REVERT", eventSeq=_seq_of(sess, "PLAYER_JOINED", player_id=b))
    assert ei.value.code == "REVERT_CONFLICT"


def test_revert_requires_host(mgr):
    sess, a, b, act = _setup(mgr)
    act(a, "TAKE_LOAN", amount=1000)
    with pytest.raises(EngineError) as ei:
        act(b, "HOST_REVERT", eventSeq=_seq_of(sess, "LOAN_TAKEN", amount=1000))
    assert ei.value.code == "NOT_HOST"


# ---------- FR-29 本人更正：语义是「抽错卡当场重选」，出了这个回合就该找房主 ----------

def test_player_correct_within_own_turn(mgr):
    """自己回合内撤销自己的抽卡：这是本人更正存在的理由，必须放行。"""
    sess, a, b, act = _setup(mgr)
    act(a, "DRAW_CARD", cardId="bd-001")
    act(a, "PLAYER_CORRECT", eventSeq=_seq_of(sess, "CARD_DRAWN", card_id="bd-001"))
    assert sess.state.active_card is None          # 撤掉了就能重新选卡


def test_player_correct_rejected_when_not_my_turn(mgr):
    """回合已交出去：不能再自己改账，否则谁都能回头翻旧账。"""
    sess, a, b, act = _setup(mgr)
    act(a, "DRAW_CARD", cardId="bd-001")
    seq = _seq_of(sess, "CARD_DRAWN", card_id="bd-001")
    act(a, "END_TURN")
    with pytest.raises(EngineError) as ei:
        act(a, "PLAYER_CORRECT", eventSeq=seq)
    assert ei.value.code == "NOT_YOUR_TURN"


def test_player_correct_rejected_for_earlier_turn(mgr):
    """轮回到自己了，但那笔账是上一回合的：只能请房主撤销。"""
    sess, a, b, act = _setup(mgr)
    act(a, "DRAW_CARD", cardId="bd-001")
    seq = _seq_of(sess, "CARD_DRAWN", card_id="bd-001")
    act(a, "END_TURN")
    act(b, "END_TURN")
    assert sess.state.current_player_id == a       # 又轮到 A，但已是下一回合
    with pytest.raises(EngineError) as ei:
        act(a, "PLAYER_CORRECT", eventSeq=seq)
    assert ei.value.code == "TURN_CLOSED"

    act(a, "HOST_REVERT", eventSeq=seq)            # 房主这条路始终通
    assert sess.state.players[a].cash > 0


def test_revert_event_carries_target_identity(mgr):
    """审计事件要带上被撤销那条的身份，否则回执只能推给全员一句含糊话。"""
    sess, a, b, act = _setup(mgr)
    act(a, "DRAW_CARD", cardId="bd-001")
    evs = act(a, "HOST_REVERT", eventSeq=_seq_of(sess, "CARD_DRAWN", card_id="bd-001"))
    p = evs[0]["payload"]
    assert p["target_type"] == "CARD_DRAWN"
    assert p["target_player_id"] == a
    assert p["target_title"]
