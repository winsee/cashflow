"""§13.3 属性测试：任意事件序列重放一致；现金永不为负（破产中间态除外）。"""
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from .. import engine as E
from .. import formulas as F
from ..errors import EngineError
from ..models import Phase, RoomState
from .conftest import Game


def _setup_duo(lib) -> Game:
    g = Game(lib)
    g.act(None, "JOIN", player_id="A", nickname="阿呆", is_host=True)
    g.act(None, "JOIN", player_id="B", nickname="阿瓜")
    g.act("A", "SELECT_PROFESSION", professionId="prof-doctor")
    g.act("B", "SELECT_PROFESSION", professionId="prof-manager")
    g.act("A", "SELECT_DREAM", dreamId="ft-d-safari")
    g.act("B", "SELECT_DREAM", dreamId="ft-d-jet")
    g.act("A", "SET_TURN_ORDER", order=["A", "B"])
    g.act("A", "START_GAME")
    return g


# 随机行动池：无效行动会被引擎拒绝（EngineError），属性只关心不变量
_ACTIONS = [
    ("PAYDAY", {}),
    ("END_TURN", {}),
    ("TAKE_LOAN", {"amount": 1000}),
    ("TAKE_LOAN", {"amount": 3000}),
    ("REPAY_LOAN", {"amount": 1000}),
    ("ADD_CHILD", {}),
    ("CHARITY", {}),
    ("DRAW_CARD", {"cardId": "dd-boat"}),
    ("DRAW_CARD", {"cardId": "dd-tv"}),
    ("DRAW_CARD", {"cardId": "dd-wedding"}),
    ("DRAW_CARD", {"cardId": "sd-house-3b2b-01"}),
    ("DRAW_CARD", {"cardId": "sd-stock-on2u-30"}),
    ("DRAW_CARD", {"cardId": "mk-evt-inflation"}),
    ("CARD_DECISION", {"decision": "pay"}),
    ("CARD_DECISION", {"decision": "buy"}),
    ("CARD_DECISION", {"decision": "credit"}),
    ("CARD_DECISION", {"decision": "pass"}),
    ("STOCK_BUY", {"qty": 5}),
    ("STOCK_SELL", {"qty": 5}),
    ("PAY_OFF_DEBT", {"liabilityId": "car_loan"}),
    ("UNEMPLOYMENT", {}),
]


@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.tuples(st.sampled_from(["A", "B"]),
                          st.integers(0, len(_ACTIONS) - 1)), max_size=60))
def test_random_walk_invariants(lib, seq):
    g = _setup_duo(lib)
    for actor, idx in seq:
        atype, payload = _ACTIONS[idx]
        try:
            g.act(actor, atype, **payload)
        except EngineError:
            continue
        # 不变量1：现金永不为负（破产流程中间态除外，本行动池不含破产）
        for pl in g.state.players.values():
            assert pl.cash >= 0, f"{pl.nickname} 现金为负: {pl.cash}"
            assert 0 <= pl.child_count <= 3
            assert 0 <= pl.charity_turns <= 3
            assert pl.liabilities.bank_loan % 1000 == 0
    # 不变量2：重放事件流所得状态与逐步计算一致
    replayed = E.replay(g.events)
    assert replayed.model_dump() == g.state.model_dump()


def test_replay_equals_final_state_long_flow(lib):
    """确定性长流程：全事件重放 == 最终状态。"""
    g = _setup_duo(lib)
    g.act("A", "TAKE_LOAN", amount=2000)
    g.act("A", "DRAW_CARD", cardId="sd-house-3b2b-01")
    g.act("A", "CARD_DECISION", decision="buy")
    g.act("A", "PAYDAY")
    g.act("A", "END_TURN")
    g.act("B", "DRAW_CARD", cardId="dd-tv")
    g.act("B", "CARD_DECISION", decision="credit")
    g.act("B", "CHARITY")
    g.act("B", "END_TURN")
    g.act("A", "DRAW_CARD", cardId="mk-evt-inflation")
    g.act("A", "REPAY_LOAN", amount=1000)
    g.act("A", "END_TURN")
    replayed = E.replay(g.events)
    assert replayed.model_dump() == g.state.model_dump()
    # 派生值与状态自洽：重放态计算出的现金流与直接态一致
    for pid in ("A", "B"):
        assert F.monthly_cashflow(replayed.players[pid]) == F.monthly_cashflow(g.state.players[pid])


def test_revoked_event_replay(lib):
    """撤销事件（跳过重放）后状态等于未发生过该事件。"""
    g = _setup_duo(lib)
    g.act("A", "TAKE_LOAN", amount=5000)
    marker = len(g.events)
    g.act("A", "TAKE_LOAN", amount=3000)     # 假设这笔被房主撤销
    events_without = g.events[:marker] + g.events[marker + 1:]
    replayed = E.replay(events_without)
    assert replayed.players["A"].liabilities.bank_loan == 5000
    assert replayed.players["A"].cash == 3950 + 5000
