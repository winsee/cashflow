"""全库扫描（design/07 §6 验收）：194 张卡逐张在真实对局中抽出并结算。

这是升级到 v3 卡库最有价值的一条网——它不检查具体数值，只保证**每一张卡都走得通**：
没有「未知 subtype」、没有 BAD_CONDITION、没有缺字段的 KeyError。
新增或改动卡牌后这里会第一个亮红灯。
"""
import pytest

from ...data_loader import load_library
from .. import engine as E
from .. import formulas as F
from ..models import OwnedBusiness, Phase, RealEstate, RoomState, RoomStatus

LIB = load_library()

ASSET_SUBTYPES = ("REALESTATE", "BUSINESS", "COLLECTIBLE")
# 抽卡人自己就要做主决策的卡；市场卡的效果在抽卡时随伴随事件完成
DECISION = {
    **{s: "buy" for s in ASSET_SUBTYPES},
    "DICE_GAMBLE": "buy",
    "STOCK_EVENT": "apply",
    "EXPENSE_EVENT": "pay",
    "CASH": "pay",
    "INSTALLMENT": "pay",
    "CREDIT_OPTION": "credit",
}

PLAYABLE = [c.id for c in LIB.cards.values() if c.deck != "PROFESSION"]


def _seed_portfolio(state: RoomState, pid: str) -> None:
    """把全库每一张可购入资产各配一份给玩家，好让市场卡一定能找到匹配标的。"""
    pl = state.players[pid]
    for card in LIB.cards.values():
        if card.subtype not in ASSET_SUBTYPES:
            continue
        d = card.data
        common = dict(
            id=f"sweep-{card.id}", card_id=card.id, name=card.title,
            asset_type=d.get("assetType", "企业"), cost=d["cost"],
            down_payment=d["downPayment"], mortgage=d.get("mortgage", 0),
            cashflow=d["cashflow"], rooms=d.get("rooms"), units=d.get("units"),
            quantity=d.get("quantity"), business_kind=d.get("businessKind"),
            income_category=d.get("incomeCategory"))
        if card.subtype == "REALESTATE":
            pl.real_estates.append(RealEstate(**common))
        else:
            pl.businesses.append(OwnedBusiness(**common))


@pytest.mark.parametrize("card_id", PLAYABLE)
def test_every_card_resolves_in_a_real_game(duo, card_id):
    card = LIB.cards[card_id]
    # 备足现金与全套资产：本用例要验的是「卡走得通」，不是「买得起」
    duo.player("A").cash += 5_000_000
    duo.player("B").cash += 5_000_000
    _seed_portfolio(duo.state, "A")
    _seed_portfolio(duo.state, "B")

    duo.act("A", "DRAW_CARD", cardId=card_id)

    if card.subtype == "STOCK_OFFER":
        duo.act("A", "STOCK_BUY", qty=1)
    elif card.subtype in DECISION:
        duo.act("A", "CARD_DECISION", decision=DECISION[card.subtype])

    # 市场卡推出的每一份要约都必须能被接受并结清
    for prompt in [p for p in duo.state.prompts if p.kind == "MARKET_SELL"]:
        duo.act(prompt.target_player_id, "MARKET_SELL",
                promptId=prompt.id, accept=True)

    assert not [p for p in duo.state.prompts if p.kind == "MARKET_SELL"]
    # 强制卡必须已结算，否则回合结束会被拦下
    duo.act("A", "END_TURN")


@pytest.mark.parametrize("card_id", [c.id for c in LIB.cards.values()
                                     if c.subtype in ASSET_SUBTYPES])
def test_every_asset_card_can_be_passed(duo, card_id):
    """机会卡一律可以放弃，放弃后不留未结算状态。"""
    duo.act("A", "DRAW_CARD", cardId=card_id)
    duo.act("A", "CARD_DECISION", decision="pass")
    duo.act("A", "END_TURN")            # 未结算的强制卡会在这里拦下


def test_every_market_card_finds_its_target():
    """每张求购卡都必须在全库里找得到匹配标的，否则就是受控词表打错字。

    design/06 §7 踩过的坑：公寓被拆成「2室公寓/4室公寓/8室公寓」，
    而求购卡写的是「公寓」，字符串对不上 → 15 张公寓卡全部卖不掉。
    """
    state = RoomState()
    state.players["A"] = _blank_player("A")
    _seed_portfolio(state, "A")
    holdings = [*state.players["A"].real_estates, *state.players["A"].businesses]

    orphans = []
    for card in LIB.cards.values():
        if card.subtype not in ("BUYER_OFFER", "MULTIPLE_OFFER",
                                "PREMIUM_OFFER", "INSTALLMENT_SALE"):
            continue
        if not any(E._asset_matches(a, card.data) for a in holdings):
            orphans.append(f"{card.id} {card.title}")
    assert orphans == []


def _blank_player(pid: str):
    from ..models import PlayerState
    return PlayerState(id=pid, nickname=pid)


def test_full_game_rat_race_to_fasttrack_win(duo):
    """§6 末条验收：用 194 张全量卡库跑通一局完整老鼠赛跑 + 进快车道 + 获胜。

    全程走真实的卡与真实的行动，只用房主调账代替若干轮攒钱的过程。
    """
    # B = 经理（总支出 $2,930），非工资收入越过它即可离开老鼠赛跑
    b = duo.player("B")
    assert F.total_expenses(b) == 2930

    duo.act("A", "HOST_ADJUST", playerId="B", delta=200_000, reason="e2e：代替攒钱过程")
    duo.act("A", "END_TURN")

    # 真刀真枪买三张卡：住宅（月租）+ 优先股（股利）+ 银行存单（利息）
    duo.act("B", "DRAW_CARD", cardId="sd-006")          # 3室2厅 +$100/月
    duo.act("B", "CARD_DECISION", decision="buy")
    duo.act("B", "END_TURN")
    duo.act("A", "END_TURN")

    duo.act("B", "DRAW_CARD", cardId="sd-001")          # 优先股 2BIG，$10/股/月
    duo.act("B", "STOCK_BUY", qty=20)                   # +$200 股利
    duo.act("B", "END_TURN")
    duo.act("A", "END_TURN")

    duo.act("B", "DRAW_CARD", cardId="bd-031")          # 比萨饼特许专卖店 +$5,000/月
    duo.act("B", "CARD_DECISION", decision="buy")

    b = duo.player("B")
    assert F.real_estate_income(b) == 100
    assert F.dividend_income(b) == 200
    assert F.business_income(b) == 5000
    passive = F.passive_income(b)
    assert passive == 5300 and passive > F.total_expenses(b)

    # 结算日：月现金流照常入账
    cash_before = b.cash
    duo.act("B", "PAYDAY")
    assert duo.player("B").cash == cash_before + F.monthly_cashflow(b)

    # 进快车道：现金交回银行，初始现金流量日收入 = 非工资收入千元四舍五入 ×100
    duo.act("B", "ENTER_FASTTRACK")
    b = duo.player("B")
    assert b.phase == Phase.FAST_TRACK
    assert b.cash == 0
    assert b.fasttrack.initial_income == F.fasttrack_initial_income(passive) == 500_000

    # 快车道：领钱 → 买企业 → 收入增量达 $50,000 即获胜
    duo.act("B", "END_TURN")
    duo.act("A", "END_TURN")
    duo.act("B", "FT_PAYDAY")
    assert duo.player("B").cash == 500_000
    duo.act("B", "FT_BUY_BUSINESS", squareId="ft-b-beauty")   # $250,000 → +$10,000/月
    b = duo.player("B")
    assert b.cash == 250_000
    assert b.fasttrack.current_income == 510_000

    duo.act("B", "END_TURN")
    duo.act("A", "END_TURN")
    duo.act("B", "FT_PAYDAY")
    duo.act("B", "FT_BUY_DREAM", squareId="ft-d-jet")         # B 选的梦想
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "B"

    # 全程事件流可完整重放（金额随事件下发，回放不依赖卡库）
    assert duo.replay().players["B"].cash == duo.player("B").cash
