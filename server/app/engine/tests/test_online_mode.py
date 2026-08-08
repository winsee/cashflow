"""对局模式回归（change add-online-board-mode §2，capability online-mode）。

覆盖：模式默认值/不可改/撤销后重放不丢、纯线上模式各闸门、职业随机发、
回合顺序服务端掷骰。线下辅助模式的行为一个字都不改——那条约束由既有全量测试守。
"""
from __future__ import annotations

import asyncio

import pytest

from ...rooms import RoomManager
from ...store.db import Database
from .. import engine as E
from ..errors import EngineError
from ..models import GameMode, RoomState


@pytest.fixture
def mgr(lib, tmp_path):
    return RoomManager(Database(tmp_path / "t.db"), lib)


def _online_room(mgr, players=("阿呆", "阿瓜")):
    """建一个纯线上房间并把人凑齐，返回 (session, [player_ids], act)。"""
    host, *rest = players
    r = asyncio.run(mgr.create_room("纯线上局", host, mode=GameMode.ONLINE.value))
    ids = [r["playerId"]]
    sess = mgr.get(r["roomCode"])
    for nick in rest:
        ids.append(asyncio.run(mgr.join_room(sess.code, nick))["playerId"])

    def act(actor, atype, **payload):
        return asyncio.run(sess.handle_action(actor, None, atype, payload))

    return sess, ids, act


def _ready(sess, ids, act):
    """全员抽职业 + 选梦想（梦想两种模式都是手动挑）。"""
    dreams = ["ft-d-safari", "ft-d-jet", "ft-d-forest", "ft-d-yacht",
              "ft-d-golf", "ft-d-library"]
    for pid, dream in zip(ids, dreams):
        act(pid, "SELECT_PROFESSION")
        act(pid, "SELECT_DREAM", dreamId=dream)


# ---------- 2.9 模式本身 ----------

def test_mode_defaults_to_offline(mgr):
    r = asyncio.run(mgr.create_room("线下局", "阿呆"))
    sess = mgr.get(r["roomCode"])
    assert sess.state.mode is GameMode.OFFLINE_ASSIST
    assert sess.serialize()["mode"] == "OFFLINE_ASSIST"


def test_mode_is_first_event_and_visible(mgr):
    sess, ids, act = _online_room(mgr)
    rows = sess.db.events_for_room(sess.room_id)
    assert rows[0]["type"] == "ROOM_MODE_SET"
    assert sess.serialize()["mode"] == "ONLINE"
    assert mgr.list_rooms()[0]["mode"] == "ONLINE"
    assert mgr.seats(sess.code)["mode"] == "ONLINE"


def test_mode_cannot_be_changed(mgr):
    sess, ids, act = _online_room(mgr)
    with pytest.raises(EngineError) as ei:
        act(ids[0], "SET_ROOM_MODE", mode="OFFLINE_ASSIST")
    assert ei.value.code == "MODE_LOCKED"
    assert sess.state.mode is GameMode.ONLINE


def test_bad_mode_rejected(lib):
    with pytest.raises(EngineError) as ei:
        E.decide(RoomState(), None, "SET_ROOM_MODE", {"mode": "HYBRID"}, lib)
    assert ei.value.code == "BAD_MODE"


def test_mode_survives_revert(mgr):
    """D1 的核心回归：_revert 从空 RoomState 重放，模式只存 DB 会被撤没。"""
    sess, ids, act = _online_room(mgr)
    a = ids[0]
    _ready(sess, ids, act)
    act(a, "START_GAME")
    act(a, "TAKE_LOAN", amount=1000)
    seq = next(r["seq"] for r in sess.db.events_for_room(sess.room_id)
               if r["type"] == "LOAN_TAKEN")
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.mode is GameMode.ONLINE
    sess.restore()
    assert sess.state.mode is GameMode.ONLINE


def test_legacy_room_replays_as_offline(lib):
    """升级前的事件流里没有 ROOM_MODE_SET，重放得到默认值。"""
    state = E.replay([{"type": "PLAYER_JOINED",
                       "payload": {"player_id": "A", "nickname": "阿呆",
                                   "is_host": True, "seat": 0}}])
    assert state.mode is GameMode.OFFLINE_ASSIST


# ---------- 2.9 纯线上模式的闸门（D10 那张表） ----------

def test_online_rejects_manual_card(mgr):
    sess, ids, act = _online_room(mgr)
    _ready(sess, ids, act)
    act(ids[0], "START_GAME")
    with pytest.raises(EngineError) as ei:
        act(sess.state.current_player_id, "DRAW_CARD", cardId="sd-006")
    assert ei.value.code == "ONLINE_DECK_ONLY"


def test_online_rejects_manual_payday(mgr):
    sess, ids, act = _online_room(mgr)
    _ready(sess, ids, act)
    act(ids[0], "START_GAME")
    cur = sess.state.current_player_id
    with pytest.raises(EngineError) as ei:
        act(cur, "PAYDAY", times=1)
    assert ei.value.code == "ONLINE_AUTO_PAYDAY"
    with pytest.raises(EngineError) as ei:
        act(cur, "FT_PAYDAY", times=1)
    assert ei.value.code == "ONLINE_AUTO_PAYDAY"


def test_online_rejects_manual_turn_order(mgr):
    sess, ids, act = _online_room(mgr)
    with pytest.raises(EngineError) as ei:
        act(ids[0], "SET_TURN_ORDER", order=list(ids))
    assert ei.value.code == "ONLINE_AUTO_ORDER"
    assert sess.state.turn_order == []


def test_online_rejects_self_correct(mgr):
    """纯线上不可能认错卡，退回堆顶再抽必然同一张——这条路径整个关掉。"""
    sess, ids, act = _online_room(mgr)
    a = ids[0]
    _ready(sess, ids, act)
    act(a, "START_GAME")
    cur = sess.state.current_player_id
    act(cur, "TAKE_LOAN", amount=1000)
    seq = next(r["seq"] for r in sess.db.events_for_room(sess.room_id)
               if r["type"] == "LOAN_TAKEN")
    with pytest.raises(EngineError) as ei:
        act(cur, "PLAYER_CORRECT", eventSeq=seq)
    assert ei.value.code == "ONLINE_NO_CORRECT"
    # 房主撤销在两种模式下都照常可用
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.players[cur].liabilities.bank_loan == 0


def test_offline_self_correct_still_works(mgr):
    """线下模式的本人更正一个字不改。"""
    r = asyncio.run(mgr.create_room("线下局", "阿呆"))
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
    act(a, "DRAW_CARD", cardId="sd-006")
    seq = next(r["seq"] for r in sess.db.events_for_room(sess.room_id)
               if r["type"] == "CARD_DRAWN")
    act(a, "PLAYER_CORRECT", eventSeq=seq)
    assert sess.state.active_card is None


# ---------- 2.10 职业随机发 ----------

def test_online_profession_is_random_and_distinct(mgr):
    sess, ids, act = _online_room(mgr, ("阿呆", "阿瓜", "阿丙"))
    for pid in ids:
        act(pid, "SELECT_PROFESSION")
    got = [sess.state.players[pid].profession_id for pid in ids]
    assert all(got) and len(set(got)) == len(got)


def test_online_profession_ignores_client_id(mgr):
    """客户端指定要哪一张：服务端忽略该字段。抽到 prof-006 的概率是 1/12，
    连抽 8 局都恰好命中它的可能性可以忽略。"""
    picked = set()
    for _ in range(8):
        sess, ids, act = _online_room(mgr)
        act(ids[0], "SELECT_PROFESSION", professionId="prof-006")
        picked.add(sess.state.players[ids[0]].profession_id)
    assert picked != {"prof-006"}


def test_online_profession_cannot_redraw(mgr):
    sess, ids, act = _online_room(mgr)
    act(ids[0], "SELECT_PROFESSION")
    first = sess.state.players[ids[0]].profession_id
    with pytest.raises(EngineError) as ei:
        act(ids[0], "SELECT_PROFESSION")
    assert ei.value.code == "PROFESSION_DRAWN"
    assert sess.state.players[ids[0]].profession_id == first


def test_online_profession_replays(mgr):
    sess, ids, act = _online_room(mgr)
    _ready(sess, ids, act)
    before = {pid: sess.state.players[pid].profession_id for pid in ids}
    sess.restore()
    assert {pid: sess.state.players[pid].profession_id for pid in ids} == before


def test_online_profession_redrawable_after_revert(mgr):
    """撤销一次抽职业后可以重抽——撤销的本意就是重来。"""
    sess, ids, act = _online_room(mgr)
    a = ids[0]
    act(a, "SELECT_PROFESSION")
    seq = next(r["seq"] for r in sess.db.events_for_room(sess.room_id)
               if r["type"] == "PROFESSION_SELECTED")
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.players[a].profession_id is None
    act(a, "SELECT_PROFESSION")
    assert sess.state.players[a].profession_id


def test_online_profession_matches_offline_entry(mgr, lib):
    """纯线上抽到某职业后的报表，与线下录入同一职业逐字相同。"""
    sess, ids, act = _online_room(mgr)
    a = ids[0]
    act(a, "SELECT_PROFESSION")
    online_player = sess.state.players[a].model_dump()

    g = RoomState()
    g = E.apply(g, {"type": "PLAYER_JOINED",
                    "payload": {"player_id": a, "nickname": "阿呆",
                                "is_host": True, "seat": 0}})
    for ev in E.decide(g, a, "SELECT_PROFESSION",
                       {"professionId": online_player["profession_id"]}, lib):
        g = E.apply(g, ev)
    assert g.players[a].model_dump() == online_player


# ---------- 2.10b 回合顺序服务端掷骰 ----------

def test_online_turn_order_rolled_at_start(mgr):
    sess, ids, act = _online_room(mgr, ("阿呆", "阿瓜", "阿丙"))
    _ready(sess, ids, act)
    assert sess.state.turn_order == []
    act(ids[0], "START_GAME")
    order = sess.state.turn_order
    assert sorted(order) == sorted(ids)
    ev = next(r for r in sess.db.events_for_room(sess.room_id)
              if r["type"] == "TURN_ORDER_SET")
    import json
    rolls = json.loads(ev["payload"])["rolls"]
    assert rolls and all(1 <= v <= 6 for rnd in rolls for v in rnd.values())
    # 第一轮所有人都摇了；点数降序即为座次（同点者由后续重摇分先后）
    first = rolls[0]
    assert set(first) == set(ids)
    assert [first[pid] for pid in order] == sorted(
        (first[pid] for pid in order), reverse=True)


def test_online_turn_order_reroll_on_tie(mgr, monkeypatch):
    """三人全平 → 重摇；重摇过程同样记入事件流。"""
    seq = iter([4, 4, 4,        # 第一轮全平
                6, 2, 5])       # 重摇分出先后
    monkeypatch.setattr(E._dice_rng, "randint", lambda a, b: next(seq))
    sess, ids, act = _online_room(mgr, ("阿呆", "阿瓜", "阿丙"))
    _ready(sess, ids, act)
    act(ids[0], "START_GAME")
    import json
    ev = next(r for r in sess.db.events_for_room(sess.room_id)
              if r["type"] == "TURN_ORDER_SET")
    rolls = json.loads(ev["payload"])["rolls"]
    assert len(rolls) == 2
    assert sess.state.turn_order == [ids[0], ids[2], ids[1]]


def test_online_turn_order_replays(mgr):
    sess, ids, act = _online_room(mgr, ("阿呆", "阿瓜", "阿丙"))
    _ready(sess, ids, act)
    act(ids[0], "START_GAME")
    before = list(sess.state.turn_order)
    sess.restore()
    assert sess.state.turn_order == before


def test_online_host_cannot_reorder_after_start(mgr):
    sess, ids, act = _online_room(mgr)
    _ready(sess, ids, act)
    act(ids[0], "START_GAME")
    with pytest.raises(EngineError) as ei:
        act(ids[0], "SET_TURN_ORDER", order=list(reversed(sess.state.turn_order)))
    assert ei.value.code == "ONLINE_AUTO_ORDER"


# ---------- 2.8 梦想两种模式都手动挑 ----------

def test_online_dream_still_manual(mgr):
    sess, ids, act = _online_room(mgr)
    act(ids[0], "SELECT_DREAM", dreamId="ft-d-safari")
    assert sess.state.players[ids[0]].dream_id == "ft-d-safari"
    with pytest.raises(EngineError) as ei:
        act(ids[1], "SELECT_DREAM", dreamId="ft-d-safari")
    assert ei.value.code == "DREAM_TAKEN"
