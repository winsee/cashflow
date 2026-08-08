"""纯线上棋盘回归（change add-online-board-mode §3/§4）。

覆盖 capability card-decks（建堆/发牌/弃牌/洗回/撤销退牌/牌序不泄露）与
board-movement（位置、掷骰、过站结算、落点派发、结束回合闸门、撤销掷骰整批）。

随机性一律钉死：`ScriptedRng` 让骰子按脚本给点数、洗牌保持卡库顺序、抽职业取池首张，
所以「第 N 格」「牌堆顶是哪张」在测试里都是确定的。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from ...rooms import RoomManager, _sanitize_payload
from ...store.db import Database
from .. import engine as E
from .. import formulas as F
from ..errors import EngineError
from ..models import GameMode, OwnedBusiness, Phase, RealEstate, RoomStatus
from .conftest import Game


class ScriptedRng:
    """把随机性钉死：骰子按脚本给点数，洗牌不动顺序，抽职业取池首张。"""

    def __init__(self):
        self.script: list[int] = []

    def randint(self, a: int, b: int) -> int:
        return self.script.pop(0) if self.script else 1

    def shuffle(self, seq) -> None:
        pass

    def choice(self, seq):
        return seq[0]


DREAMS = ["ft-d-safari", "ft-d-jet", "ft-d-forest"]


@pytest.fixture
def rng(monkeypatch):
    r = ScriptedRng()
    monkeypatch.setattr(E, "_dice_rng", r)
    return r


@pytest.fixture
def online(lib, rng):
    """两人纯线上局，A 先手，全员站在起点标记（位置 0）。"""
    g = Game(lib)
    g.act(None, "SET_ROOM_MODE", mode=GameMode.ONLINE.value)
    g.act(None, "JOIN", player_id="A", nickname="阿呆", is_host=True)
    g.act(None, "JOIN", player_id="B", nickname="阿瓜")
    for pid, dream in zip(("A", "B"), DREAMS):
        g.act(pid, "SELECT_PROFESSION")
        g.act(pid, "SELECT_DREAM", dreamId=dream)
    rng.script = [6, 1]                     # 开局定先后：A 掷 6、B 掷 1
    g.act("A", "START_GAME")
    g.rng = rng
    return g


def _roll(g, pid, *dice):
    g.rng.script = list(dice)
    return g.act(pid, "ROLL_DICE", diceCount=len(dice))


def _types(evs):
    return [e["type"] for e in evs]


# ============================================================ §3 牌堆

def test_decks_built_from_real_deck_composition(online, lib):
    """建堆张数 = 卡库该牌堆总数；重复卡按实际份数入堆（张数决定抽牌概率）。"""
    decks = online.state.decks
    assert set(decks) == set(E.DECK_NAMES)
    for deck in E.DECK_NAMES:
        assert len(decks[deck]) == len(lib.by_deck(deck))
    # 重复卡各占一张：按 key 归组后，组内有几张牌堆里就有几张
    dup_ids = [c.id for c in lib.by_deck("SMALL_DEAL") if c.duplicate_of]
    assert dup_ids and all(cid in decks["SMALL_DEAL"] for cid in dup_ids)


def test_draw_takes_from_top_and_discards_after_resolve(online):
    a = online.state
    top = a.decks["SMALL_DEAL"][0]
    _roll(online, "A", 1)                      # 第 1 格 = 机会
    online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
    assert online.state.active_card.card_id == top
    assert top not in online.state.decks["SMALL_DEAL"]
    assert online.state.discards["SMALL_DEAL"] == []
    online.act("A", "CARD_DECISION", decision="pass")
    assert online.state.discards["SMALL_DEAL"] == [top]


def test_deck_reshuffles_when_empty(online, lib):
    """牌堆取空 → 先洗回弃牌堆再发牌；两者同空则明确报错。"""
    st = online.state
    st.decks["DOODAD"] = []
    st.discards["DOODAD"] = ["dd-002", "dd-004"]
    _roll(online, "A", 2)                      # 第 2 格 = 额外支出
    evs = online.events[-3:]
    assert "DECK_RESHUFFLED" in _types(evs)
    assert online.state.active_card.card_id == "dd-002"
    assert online.state.decks["DOODAD"] == ["dd-004"]
    assert online.state.discards["DOODAD"] == []


def test_deck_and_discard_both_empty_errors(online):
    st = online.state
    st.decks["DOODAD"] = []
    st.discards["DOODAD"] = []
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 2)
    assert ei.value.code == "DECK_EMPTY"


def test_serialize_only_exposes_deck_counts(lib, tmp_path, rng):
    """出口一：房间状态只下发张数。"""
    mgr = RoomManager(Database(tmp_path / "t.db"), lib)
    sess, ids, act = _online_session(mgr)
    _ready(sess, ids, act, rng)
    act(ids[0], "START_GAME")
    decks = sess.serialize()["decks"]
    assert decks["SMALL_DEAL"]["remaining"] == len(lib.by_deck("SMALL_DEAL"))
    blob = json.dumps(sess.serialize(), ensure_ascii=False)
    assert "sd-001" not in blob and "orders" not in blob


def test_card_order_never_leaves_the_room(lib, tmp_path, rng):
    """出口二/三：WS 广播的 lastEvents 与 /log 接口都不含牌序；事件表里仍然完整。"""
    mgr = RoomManager(Database(tmp_path / "t.db"), lib)
    sess, ids, act = _online_session(mgr)
    _ready(sess, ids, act, rng)
    ws = _FakeWS()
    sess.sockets.setdefault(ids[0], set()).add(ws)
    act(ids[0], "START_GAME")

    broadcast = json.loads(ws.sent[-1])
    shuffled = next(e for e in broadcast["lastEvents"] if e["type"] == "DECKS_SHUFFLED")
    assert "orders" not in shuffled["payload"]
    assert shuffled["payload"]["counts"]["SMALL_DEAL"] == len(lib.by_deck("SMALL_DEAL"))
    assert "sd-001" not in json.dumps(broadcast, ensure_ascii=False)

    log = sess.log_rows()
    row = next(r for r in log if r["type"] == "DECKS_SHUFFLED")
    assert "orders" not in row["payload"]
    assert "sd-001" not in json.dumps(log, ensure_ascii=False)

    # 脱敏只发生在出口：事件表里牌序仍在，否则重放就废了
    stored = next(r for r in sess.db.events_for_room(sess.room_id)
                  if r["type"] == "DECKS_SHUFFLED")
    assert len(json.loads(stored["payload"])["orders"]["SMALL_DEAL"]) \
        == len(lib.by_deck("SMALL_DEAL"))


def test_sanitize_keeps_other_payloads_intact():
    assert _sanitize_payload("CARD_DRAWN", {"card_id": "sd-002"}) == {"card_id": "sd-002"}
    assert _sanitize_payload("DECK_RESHUFFLED", {"deck": "DOODAD", "order": ["a", "b"]}) \
        == {"deck": "DOODAD", "count": 2}


def test_replay_gives_the_same_deal_sequence(online):
    drawn = []
    for _ in range(3):
        _roll(online, "A", 1)
        online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
        drawn.append(online.state.active_card.card_id)
        online.act("A", "CARD_DECISION", decision="pass")
        online.act("A", "END_TURN")
        online.act("B", "END_TURN")
        online.state.players["A"].rr_position = 0
    assert len(set(drawn)) == 3
    replayed = online.replay()
    assert replayed.decks == online.state.decks
    assert replayed.discards == online.state.discards


# ============================================================ §4 掷骰与移动

def test_start_at_marker_then_first_roll_lands_on_that_square(online):
    """开局位置 0（起点箭头，不是格子），掷 N 点落到第 N 格。"""
    assert online.player("A").rr_position == 0
    evs = _roll(online, "A", 3)
    moved = next(e for e in evs if e["type"] == "PLAYER_MOVED")
    assert moved["payload"]["from"] == 0
    assert moved["payload"]["path"] == [1, 2, 3]
    assert moved["payload"]["to"] == 3
    assert online.player("A").rr_position == 3
    assert online.state.landing.type == "OPPORTUNITY"      # 第 3 格
    assert online.state.landing.index == 3


def test_client_supplied_roll_is_ignored(online):
    evs = online.act("A", "ROLL_DICE", diceCount=1, rolls=[6], total=6)
    assert evs[0]["payload"]["rolls"] == [1]               # 脚本默认值，不是客户端的 6


def test_one_roll_per_turn(online):
    _roll(online, "A", 1)
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 1)
    assert ei.value.code == "DICE_USED"


def test_not_your_turn_cannot_roll(online):
    with pytest.raises(EngineError) as ei:
        _roll(online, "B", 1)
    assert ei.value.code == "NOT_YOUR_TURN"


def test_bankrupt_player_cannot_roll(online):
    online.state.players["A"].in_bankruptcy = True
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 1)
    assert ei.value.code == "IN_BANKRUPTCY"


def test_skipping_player_cannot_roll(online):
    online.state.players["A"].skip_turns = 2
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 1)
    assert ei.value.code == "SKIPPING"


def test_offline_room_has_no_roll_dice(duo):
    with pytest.raises(EngineError) as ei:
        duo.act("A", "ROLL_DICE", diceCount=1)
    assert ei.value.code == "OFFLINE_DICE"


# ---------- 4.7 骰子粒数按赛道分开 ----------

def test_rat_race_default_one_die(online):
    evs = _roll(online, "A", 4)
    assert evs[0]["payload"]["dice_count"] == 1
    assert online.state.landing.type == "CHARITY"          # 第 4 格


def test_rat_race_two_dice_only_with_charity(online):
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 3, 3)
    assert ei.value.code == "BAD_DICE_COUNT"
    online.state.players["A"].charity_turns = 3
    evs = _roll(online, "A", 3, 3)
    assert evs[0]["payload"]["total"] == 6


def test_rat_race_charity_never_allows_three_dice(online):
    """3 粒是快车道慈善才有的权利（P.6），老鼠赛跑的慈善只给到 2 粒。"""
    online.state.players["A"].charity_turns = 3
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 1, 1, 1)
    assert ei.value.code == "BAD_DICE_COUNT"


def test_fast_track_dice_counts(online):
    a = online.state.players["A"]
    a.phase = Phase.FAST_TRACK
    a.fasttrack.current_income = 0
    with pytest.raises(EngineError) as ei:
        _roll(online, "A", 1, 1, 1)
    assert ei.value.code == "BAD_DICE_COUNT"
    a.fasttrack.charity_forever = True                     # 快车道慈善是永久的
    evs = _roll(online, "A", 1, 1, 1)
    assert evs[0]["payload"]["dice_count"] == 3


def test_zero_or_four_dice_rejected(online):
    for n in (0, 4):
        with pytest.raises(EngineError) as ei:
            online.act("A", "ROLL_DICE", diceCount=n)
        assert ei.value.code == "BAD_DICE_COUNT"


# ---------- 4.17 / 4.18 过站结算 ----------

def test_pass_one_payday_then_land_elsewhere(online):
    a = online.player("A")
    a.rr_position = 5
    cash0, cf = a.cash, F.monthly_cashflow(a)
    evs = _roll(online, "A", 2)                            # 经过第 6 格结算日，停在第 7 格
    assert _types(evs)[:3] == ["DICE_ROLLED", "PAYDAY", "PLAYER_MOVED"]
    assert online.player("A").cash == cash0 + cf
    assert online.state.landing.index == 7


def test_land_exactly_on_payday(online):
    a = online.player("A")
    cash0, cf = a.cash, F.monthly_cashflow(a)
    evs = _roll(online, "A", 6)
    assert _types(evs) == ["DICE_ROLLED", "PAYDAY", "PLAYER_MOVED", "LANDING_RESOLVED"]
    assert online.player("A").cash == cash0 + cf
    assert online.state.landing.type == "PAYDAY" and online.state.landing.resolved


def test_pass_two_paydays_settles_twice(online):
    """一次移动跨两个结算格：逐次结算，不合并成一次。"""
    a = online.player("A")
    a.rr_position = 5
    a.charity_turns = 3                                    # 才能掷 2 粒骰走 9 格
    cash0, cf = a.cash, F.monthly_cashflow(a)
    evs = _roll(online, "A", 5, 4)                         # 5 → 14，经过第 6、14 两格
    assert _types(evs).count("PAYDAY") == 2
    assert online.player("A").cash == cash0 + cf * 2
    assert online.state.landing.index == 14


def test_bankruptcy_during_move_stops_in_place(online):
    """跨结算日时付不出钱 → 就地终止 + 进清算，棋子停在那个结算格。"""
    a = online.state.players["A"]
    a.rr_position = 4
    a.liabilities.bank_loan = 40000                        # 利息 4,000/月
    a.cash = 100
    assert F.monthly_cashflow(a) < 0
    evs = _roll(online, "A", 2)                            # 本该走到第 6 格之后
    assert _types(evs) == ["DICE_ROLLED", "PAYDAY_UNPAYABLE", "BANKRUPTCY_STARTED",
                           "PLAYER_MOVED", "LANDING_RESOLVED"]
    moved = next(e for e in evs if e["type"] == "PLAYER_MOVED")
    assert moved["payload"]["path"] == [5, 6] and moved["payload"]["to"] == 6
    assert online.player("A").rr_position == 6
    assert online.player("A").in_bankruptcy


# ---------- 4.19 落点派发 ----------

def test_landing_dispatch_by_square_type(online):
    a = online.state.players["A"]
    a.cash = 200_000                                       # 失业格要一次性付掉总支出

    def land_on(index):
        pl = online.state.players["A"]
        pl.rr_position = index - 1
        pl.skip_turns = 0                                  # 失业格会把人停赛，别挡住下一次落点
        online.state.turn_dice_used = False
        online.state.turn_square_used = False
        online.state.landing = None
        online.state.active_card = None
        return _roll(online, "A", 1)

    assert "CARD_DRAWN" in _types(land_on(2))              # 额外支出：直接发牌
    assert online.state.active_card.deck == "DOODAD"
    assert "CARD_DRAWN" in _types(land_on(8))              # 市场风云：直接发牌
    assert online.state.active_card.deck == "MARKET"
    assert "CHILD_ADDED" in _types(land_on(12))            # 孩子
    assert "UNEMPLOYMENT_HIT" in _types(land_on(20))       # 失业
    # 机会格与慈善格是选择格：落点未决，等玩家动作
    land_on(1)
    assert online.state.landing.type == "OPPORTUNITY" and not online.state.landing.resolved
    land_on(4)
    assert online.state.landing.type == "CHARITY" and not online.state.landing.resolved


def test_opportunity_deal_size_then_draw(online):
    _roll(online, "A", 1)
    with pytest.raises(EngineError) as ei:
        online.act("A", "CHOOSE_DEAL_SIZE", size="HUGE")
    assert ei.value.code == "BAD_DEAL_SIZE"
    online.act("A", "CHOOSE_DEAL_SIZE", size="BIG")
    assert online.state.active_card.deck == "BIG_DEAL"
    assert online.state.landing.resolved


def test_choose_deal_size_needs_that_square(online):
    _roll(online, "A", 2)                                   # 额外支出格
    with pytest.raises(EngineError) as ei:
        online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
    assert ei.value.code == "WRONG_SQUARE"


def test_charity_requires_standing_on_charity_square(online):
    _roll(online, "A", 1)
    with pytest.raises(EngineError) as ei:
        online.act("A", "CHARITY")
    assert ei.value.code == "WRONG_SQUARE"
    online.state.players["A"].rr_position = 3
    online.state.turn_dice_used = False
    _roll(online, "A", 1)                                   # 第 4 格 = 慈善事业
    online.act("A", "CHARITY")
    assert online.player("A").charity_turns == 3


def test_unemployment_short_of_cash_keeps_landing_open(online):
    """失业格付不出：掷骰已成事实，落点保持未决，玩家先贷款再自己付。"""
    a = online.state.players["A"]
    a.rr_position = 19
    a.cash = 0
    _roll(online, "A", 1)
    assert online.state.landing.type == "UNEMPLOYMENT"
    assert not online.state.landing.resolved
    with pytest.raises(EngineError) as ei:
        online.act("A", "END_TURN")
    assert ei.value.code == "LANDING_UNRESOLVED"
    online.act("A", "TAKE_LOAN", amount=10000)   # 贷款本身会抬高利息支出，借宽裕些
    online.act("A", "UNEMPLOYMENT")
    assert online.state.landing.resolved
    online.act("A", "END_TURN")


# ---------- 4.19b 结束回合闸门 ----------

def test_opportunity_blocks_end_turn(online):
    _roll(online, "A", 1)
    with pytest.raises(EngineError) as ei:
        online.act("A", "END_TURN")
    assert ei.value.code == "LANDING_UNRESOLVED"
    online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
    online.act("A", "CARD_DECISION", decision="pass")
    online.act("A", "END_TURN")
    assert online.state.current_player_id == "B"


def test_charity_square_can_be_skipped(online):
    _roll(online, "A", 4)
    assert not online.state.landing.resolved
    online.act("A", "END_TURN")                             # 不捐 = 什么都不做，放行
    assert online.state.current_player_id == "B"


def test_fasttrack_green_square_can_be_skipped(online):
    a = online.state.players["A"]
    a.phase = Phase.FAST_TRACK
    a.ft_position = 1                                       # 下一格是 ft-b-inn（绿格）
    _roll(online, "A", 1)
    assert online.state.landing.type == "FT_BUSINESS"
    assert not online.state.landing.resolved
    online.act("A", "END_TURN")


def test_sold_out_green_square_is_a_no_op(online):
    a = online.state.players["A"]
    a.phase = Phase.FAST_TRACK
    a.ft_position = 1
    online.state.ft_sold_squares.append("ft-b-inn")
    evs = _roll(online, "A", 1)
    assert "LANDING_RESOLVED" in _types(evs)
    assert online.state.landing.resolved
    assert "无事发生" in online.state.landing.note


# ---------- 4.12 进快车道 ----------

def test_enter_fasttrack_puts_pawn_on_entry_marker(online):
    a = online.state.players["A"]
    a.real_estates.append(RealEstate(
        id="r1", card_id="x", asset_type="4室公寓", name="大公寓",
        cost=1, down_payment=1, mortgage=0,
        cashflow=F.total_expenses(a) + 1))
    online.act("A", "ENTER_FASTTRACK")
    assert online.player("A").phase is Phase.FAST_TRACK
    assert online.player("A").ft_position == 0              # 「在此进入」箭头，不是第 1 格
    assert online.state.landing is None


def test_first_fasttrack_roll_counts_from_the_marker(online):
    a = online.state.players["A"]
    a.phase = Phase.FAST_TRACK
    a.ft_position = 0
    evs = _roll(online, "A", 2, 1)
    moved = next(e for e in evs if e["type"] == "PLAYER_MOVED")
    assert moved["payload"]["track"] == "FAST_TRACK"
    assert moved["payload"]["path"] == [1, 2, 3]
    assert online.state.landing.ref_id == "ft-d-fans-restaurant"


def test_fasttrack_cashflow_day_settles_on_pass(online):
    a = online.state.players["A"]
    a.phase = Phase.FAST_TRACK
    a.ft_position = 11                                      # 第 12 格 = 现金流量日
    a.fasttrack.current_income = 25_000
    cash0 = a.cash
    evs = _roll(online, "A", 1, 1)                          # 经过 12，停在 13
    assert _types(evs)[:3] == ["DICE_ROLLED", "FT_PAYDAY", "PLAYER_MOVED"]
    assert online.player("A").cash == cash0 + 25_000
    assert online.state.landing.ref_id == "ft-d-cannes"


# ---------- 重放 ----------

def test_positions_and_landing_replay(online):
    _roll(online, "A", 3)
    online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
    online.act("A", "CARD_DECISION", decision="pass")
    online.act("A", "END_TURN")
    _roll(online, "B", 2)
    replayed = online.replay()
    assert replayed.players["A"].rr_position == 3
    assert replayed.players["B"].rr_position == 2
    assert replayed.landing == online.state.landing
    assert replayed.turn_dice_used == online.state.turn_dice_used


# ---------- 4.21 完整一局 / 说明书示例回归 ----------

def test_full_online_game_rat_race_to_victory(online):
    """纯线上跑通一局：老鼠赛跑走格抽卡 → 进快车道 → 停在自己的梦想上获胜。"""
    # ① 老鼠赛跑：走一格、抽一张机会卡
    _roll(online, "A", 1)
    online.act("A", "CHOOSE_DEAL_SIZE", size="SMALL")
    online.act("A", "CARD_DECISION", decision="pass")
    online.act("A", "END_TURN")
    online.act("B", "END_TURN")

    # ② 非工资收入过线 → 进快车道，棋子落在「在此进入」箭头（位置 0）
    a = online.state.players["A"]
    a.businesses.append(OwnedBusiness(
        id="biz", card_id="x", name="测试企业", cost=0, down_payment=0,
        cashflow=F.total_expenses(a) + 100))
    online.act("A", "ENTER_FASTTRACK")
    assert online.player("A").phase is Phase.FAST_TRACK
    assert online.player("A").ft_position == 0

    # ③ 快车道默认掷 2 粒骰，绿格可以不买
    _roll(online, "A", 1, 1)
    assert online.state.landing.ref_id == "ft-b-inn"
    online.act("A", "END_TURN")
    online.act("B", "END_TURN")

    # ④ 停在自己选定的梦想上 → 获胜（ft-d-safari 在第 47 格）
    online.state.players["A"].ft_position = 45
    _roll(online, "A", 1, 1)
    assert online.state.landing.ref_id == "ft-d-safari"
    online.act("A", "FT_BUY_DREAM", squareId="ft-d-safari")
    assert online.state.status is RoomStatus.FINISHED
    assert online.state.winner_id == "A"


def test_online_passing_settlement_uses_the_manual_example_math(duo):
    """说明书示例（医生月现金流 3,550）在纯线上的过站结算里逐字相同。

    两种模式的算钱只有一份实现（`payday_events`），所以 design/02 §13 的示例回归
    自动覆盖纯线上模式——不存在第二份会算错钱的账。
    """
    doctor = duo.player("A")
    assert F.monthly_cashflow(doctor) == 3550
    duo.state.mode = GameMode.ONLINE
    ev = E._settlement_events(duo.state, "A", "RAT_RACE")[0]
    assert ev == {"type": "PAYDAY",
                  "payload": {"player_id": "A", "cashflow": 3550, "times": 1}}


# ============================================================ 会话级：撤销

class _FakeWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


def _online_session(mgr, players=("阿呆", "阿瓜")):
    host, *rest = players
    r = asyncio.run(mgr.create_room("纯线上局", host, mode=GameMode.ONLINE.value))
    sess = mgr.get(r["roomCode"])
    ids = [r["playerId"]]
    for nick in rest:
        ids.append(asyncio.run(mgr.join_room(sess.code, nick))["playerId"])

    def act(actor, atype, **payload):
        return asyncio.run(sess.handle_action(actor, None, atype, payload))

    return sess, ids, act


def _ready(sess, ids, act, rng):
    for pid, dream in zip(ids, DREAMS):
        act(pid, "SELECT_PROFESSION")
        act(pid, "SELECT_DREAM", dreamId=dream)
    rng.script = [6, 1]


@pytest.fixture
def session(lib, tmp_path, rng):
    mgr = RoomManager(Database(tmp_path / "t.db"), lib)
    sess, ids, act = _online_session(mgr)
    _ready(sess, ids, act, rng)
    act(ids[0], "START_GAME")
    return sess, ids, act, rng


def _seq_of(sess, etype, **match):
    for r in sess.db.events_for_room(sess.room_id):
        if r["type"] == etype and all(json.loads(r["payload"]).get(k) == v
                                      for k, v in match.items()):
            return r["seq"]
    raise AssertionError(f"未找到事件 {etype} {match}")


def test_revert_draw_returns_card_to_the_top(session):
    """撤销一次发牌 → 牌退回堆顶，下一张发出的仍是同一张（不需要任何「退牌」代码）。"""
    sess, ids, act, rng = session
    a = sess.state.current_player_id
    rng.script = [1]
    act(a, "ROLL_DICE", diceCount=1)
    act(a, "CHOOSE_DEAL_SIZE", size="SMALL")
    first = sess.state.active_card.card_id
    seq = _seq_of(sess, "CARD_DRAWN", card_id=first)
    act(ids[0], "HOST_REVERT", eventSeq=seq)
    assert sess.state.active_card is None
    assert sess.state.decks["SMALL_DEAL"][0] == first
    assert not sess.state.landing.resolved            # 落点回到「尚未处理」
    act(a, "CHOOSE_DEAL_SIZE", size="SMALL")
    assert sess.state.active_card.card_id == first


def test_revert_draw_does_not_move_the_pawn(session):
    """撤抽卡不动棋子（change D13）——位置只由掷骰事件决定。"""
    sess, ids, act, rng = session
    a = sess.state.current_player_id
    rng.script = [1]
    act(a, "ROLL_DICE", diceCount=1)
    act(a, "CHOOSE_DEAL_SIZE", size="SMALL")
    seq = _seq_of(sess, "CARD_DRAWN", card_id=sess.state.active_card.card_id)
    act(ids[0], "HOST_REVERT", eventSeq=seq)
    assert sess.state.players[a].rr_position == 1
    assert sess.state.landing.index == 1


def test_revert_dice_rolls_back_the_whole_batch(session):
    """撤销掷骰 = 位置、经过的结算、发出的牌整批回退，且重放一致。

    全程走真实事件（不直接改 state）——撤销就是整流重放，手动改出来的状态重放不出来。
    """
    sess, ids, act, rng = session
    a, b = ids[0], ids[1]

    def roll(pid, n):
        rng.script = [n]
        return act(pid, "ROLL_DICE", diceCount=1)

    roll(a, 4)                                     # 第 4 格慈善，可直接结束回合
    act(a, "END_TURN")
    act(b, "END_TURN")
    cash0 = sess.state.players[a].cash
    deck0 = list(sess.state.decks["DOODAD"])
    roll(a, 6)                                     # 经过第 6 格结算日，停在第 10 格额外支出
    assert sess.state.players[a].rr_position == 10
    assert sess.state.players[a].cash != cash0
    assert sess.state.decks["DOODAD"] != deck0

    seq = max(r["seq"] for r in sess.db.events_for_room(sess.room_id)
              if r["type"] == "DICE_ROLLED")
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.players[a].rr_position == 4
    assert sess.state.players[a].cash == cash0
    assert sess.state.decks["DOODAD"] == deck0
    assert sess.state.landing is None
    assert not sess.state.turn_dice_used
    before = sess.state.model_dump()
    sess.restore()
    assert sess.state.model_dump() == before


def test_revert_dice_after_market_response(session):
    """两层 cascade 嵌套：掷骰落在市场风云格、别人已答复，房主撤掷骰一并回退。"""
    sess, ids, act, rng = session
    a, b = ids[0], ids[1]
    act(a, "HOST_ADJUST", playerId=b, delta=10000, reason="测试备用金")

    def roll(pid, n):
        rng.script = [n]
        return act(pid, "ROLL_DICE", diceCount=1)

    # B 先买下一套 2室1厅（小生意牌堆第 2 张），好让后面的求购卡有对象
    roll(a, 4); act(a, "END_TURN")                          # A → 第 4 格慈善
    roll(b, 1); act(b, "CHOOSE_DEAL_SIZE", size="SMALL")    # sd-001 股票
    act(b, "CARD_DECISION", decision="pass"); act(b, "END_TURN")
    roll(a, 4); act(a, "END_TURN")                          # A → 第 8 格市场风云 mk-001
    roll(b, 2); act(b, "CHOOSE_DEAL_SIZE", size="SMALL")    # sd-002 = 2室1厅
    act(b, "CARD_DECISION", decision="buy"); act(b, "END_TURN")
    assert sess.state.players[b].real_estates
    roll(a, 4); act(a, "END_TURN"); act(b, "END_TURN")      # A → 第 12 格孩子
    roll(a, 4); act(a, "END_TURN"); act(b, "END_TURN")      # A → 第 16 格市场风云 mk-002
    roll(a, 6); act(a, "END_TURN"); act(b, "END_TURN")      # A → 第 22 格结算日
    roll(a, 2)                                              # A → 第 24 格市场风云 mk-003

    prompt = sess.state.prompts[0]
    assert prompt.target_player_id == b
    act(b, "MARKET_SELL", promptId=prompt.id, accept=True)
    assert not sess.state.players[b].real_estates

    seq = max(r["seq"] for r in sess.db.events_for_room(sess.room_id)
              if r["type"] == "DICE_ROLLED")
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.players[b].real_estates      # B 的房子回来了
    assert sess.state.prompts == []                # 没留下幽灵求购弹层
    assert sess.state.players[a].rr_position == 22
    before = sess.state.model_dump()
    sess.restore()
    assert sess.state.model_dump() == before


def test_revert_crossing_a_reshuffle_replays_consistently(lib, tmp_path, rng,
                                                          monkeypatch):
    """撤销跨越一次洗回：牌堆状态由事件重放得出，等价于那次发牌从未发生。

    把额外支出堆缩到 2 张再开局——短牌堆同样写进 DECKS_SHUFFLED，整条链仍然可重放。
    """
    real_build = E._build_decks
    monkeypatch.setattr(E, "_build_decks",
                        lambda l: {**real_build(l), "DOODAD": ["dd-004", "dd-008"]})
    mgr = RoomManager(Database(tmp_path / "t.db"), lib)
    sess, ids, act = _online_session(mgr)
    _ready(sess, ids, act, rng)
    act(ids[0], "START_GAME")
    a, b = ids[0], ids[1]

    def doodad_turn(n_from_start):
        rng.script = [n_from_start]
        act(a, "ROLL_DICE", diceCount=1)
        act(a, "CARD_DECISION")                    # 额外支出是强制卡，付掉才能结束回合
        act(a, "END_TURN")
        act(b, "END_TURN")

    doodad_turn(2)                                 # 第 2 格：取走 dd-004
    doodad_turn(8)                                 # 第 10 格：取走 dd-008，牌堆见底
    assert sess.state.decks["DOODAD"] == []
    rng.script = [8]
    act(a, "ROLL_DICE", diceCount=1)               # 第 18 格：牌堆空了，先洗回再发
    assert _seq_of(sess, "DECK_RESHUFFLED")
    seq = max(r["seq"] for r in sess.db.events_for_room(sess.room_id)
              if r["type"] == "DICE_ROLLED")
    act(a, "HOST_REVERT", eventSeq=seq)
    assert sess.state.decks["DOODAD"] == []        # 回到「那次发牌从未发生」
    assert len(sess.state.discards["DOODAD"]) == 2
    before = sess.state.model_dump()
    sess.restore()
    assert sess.state.model_dump() == before
