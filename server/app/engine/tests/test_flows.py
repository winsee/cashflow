"""§13.2 流程用例（design/02）。医生=A（房主），经理=B，见 conftest.duo。"""
import pytest

from .. import formulas as F
from ..errors import EngineError
from ..models import Phase, RealEstate, RoomStatus, StockHolding, OwnedBusiness


# ---------- 开局发钱（§4） ----------

def test_setup_grants(duo):
    assert duo.player("A").cash == 3550 + 400    # 月现金流 + 储蓄
    assert duo.player("B").cash == 1670 + 400
    assert duo.player("A").savings == 0          # 储蓄发钱后注销
    assert duo.state.status == RoomStatus.PLAYING
    assert duo.state.current_player_id == "A"


# ---------- 买房 → 市场卡（§6.1、§6.3） ----------

def test_buy_house_then_inflation_surrender(duo):
    duo.act("A", "DRAW_CARD", cardId="sd-house-3b2b-01")
    duo.act("A", "CARD_DECISION", decision="buy")
    a = duo.player("A")
    assert a.cash == 3950 - 3000
    assert len(a.real_estates) == 1
    assert F.passive_income(a) == 100
    duo.act("A", "END_TURN")

    # B 抽到通胀：A 的 3室2厅 全部交回银行，无补偿
    duo.act("B", "DRAW_CARD", cardId="mk-evt-inflation")
    a = duo.player("A")
    assert a.real_estates == []
    assert a.cash == 950
    assert F.passive_income(a) == 0


def test_market_buyer_offer_sell(duo):
    # 预置 B 持有一套 2室1厅（抵押 40,000）
    duo.state.players["B"].real_estates.append(RealEstate(
        id="r-test", card_id="x", asset_type="2室1厅", name="2室1厅出租房",
        cost=45000, down_payment=5000, mortgage=40000, cashflow=150))
    duo.act("A", "DRAW_CARD", cardId="mk-offer-2b1b-55k")
    prompts = [p for p in duo.state.prompts if p.kind == "MARKET_SELL"]
    assert len(prompts) == 1 and prompts[0].target_player_id == "B"
    cash_before = duo.player("B").cash
    duo.act("B", "MARKET_SELL", promptId=prompts[0].id, accept=True)
    b = duo.player("B")
    assert b.cash == cash_before + (55000 - 40000)   # 收益 = 卖价 − 抵押
    assert b.real_estates == []
    assert duo.state.prompts == []


def test_market_multiple_offer(duo):
    duo.state.players["B"].businesses.append(OwnedBusiness(
        id="b-lp", card_id="x", asset_type="有限合伙", name="有限合伙",
        cost=5000, down_payment=5000, mortgage=0, cashflow=200))
    duo.act("A", "DRAW_CARD", cardId="mk-multi-lp-3x")
    pr = duo.state.prompts[0]
    assert pr.payload["price"] == 15000              # 原价 3 倍
    duo.act("B", "MARKET_SELL", promptId=pr.id, accept=True)
    assert duo.player("B").businesses == []


# ---------- 股票：买入/广播卖出/并股（§6.2） ----------

def test_stock_buy_sell_window_and_merge(duo):
    duo.state.players["B"].stocks.append(
        StockHolding(symbol="ON2U", shares=20, cost_per_share=10))
    duo.act("A", "DRAW_CARD", cardId="sd-stock-on2u-30")
    duo.act("A", "STOCK_BUY", qty=10)
    assert duo.player("A").cash == 3950 - 300
    # 广播卖出窗口：B 按今日价格卖出
    duo.act("B", "STOCK_SELL", qty=20)
    assert duo.player("B").cash == 2070 + 600
    assert duo.player("B").stocks == []
    # 只有抽卡人能买
    with pytest.raises(EngineError, match="抽卡人"):
        duo.act("B", "STOCK_BUY", qty=1)
    duo.act("A", "END_TURN")
    # 机会失效：结束回合后窗口关闭
    with pytest.raises(EngineError):
        duo.act("A", "STOCK_SELL", qty=1)


def test_stock_merge_2_to_1(duo):
    duo.state.players["A"].stocks.append(StockHolding(symbol="MYT4U", shares=11, cost_per_share=10))
    duo.state.players["B"].stocks.append(StockHolding(symbol="MYT4U", shares=4, cost_per_share=20))
    duo.act("A", "DRAW_CARD", cardId="sd-stockevt-myt4u")
    duo.act("A", "CARD_DECISION", decision="apply")
    assert duo.player("A").stocks[0].shares == 5     # 11 → 5（每两股并一股，零头舍去）
    assert duo.player("B").stocks[0].shares == 2


# ---------- 额外支出卡（§6.4） ----------

def test_doodad_installment_boat(duo):
    duo.act("A", "DRAW_CARD", cardId="dd-boat")
    exp_before = F.total_expenses(duo.player("A"))
    duo.act("A", "CARD_DECISION", decision="pay")
    a = duo.player("A")
    assert a.cash == 3950 - 1000
    assert a.extra_liabilities[0].amount == 17000
    assert a.extra_liabilities[0].monthly == 340
    assert F.total_expenses(a) == exp_before + 340


def test_doodad_credit_option(duo):
    duo.act("A", "DRAW_CARD", cardId="dd-tv")
    duo.act("A", "CARD_DECISION", decision="credit")
    a = duo.player("A")
    assert a.cash == 3950                            # 现金不动
    assert a.liabilities.credit_card == 9000 + 4000
    assert a.credit_card_payment == 270 + 120


def test_doodad_conditional_cash_no_children(duo):
    duo.act("A", "DRAW_CARD", cardId="dd-wedding")
    duo.act("A", "CARD_DECISION", decision="pay")
    assert duo.player("A").cash == 3950              # 无孩子不付


def test_forced_card_blocks_end_turn(duo):
    duo.act("A", "DRAW_CARD", cardId="dd-boat")
    with pytest.raises(EngineError, match="强制卡牌"):
        duo.act("A", "END_TURN")


# ---------- 慈善 3 轮倒计时（§5） ----------

def test_charity_countdown(duo):
    duo.act("A", "CHARITY")
    a = duo.player("A")
    assert a.cash == 3950 - 1320                     # 总收入 13,200 × 10%
    assert a.charity_turns == 3
    duo.act("A", "END_TURN")                         # 捐款当轮不消耗
    assert duo.player("A").charity_turns == 3
    for expect in (2, 1, 0):
        duo.act("B", "END_TURN")
        duo.act("A", "END_TURN")
        assert duo.player("A").charity_turns == expect


# ---------- 失业：停 2 轮 + 清除慈善（§5） ----------

def test_unemployment(duo):
    duo.act("A", "CHARITY")
    duo.act("A", "TAKE_LOAN", amount=9000)           # 补足支付总支出的现金
    a = duo.player("A")
    total_exp = F.total_expenses(a)                  # 9,650 + 900 利息
    assert total_exp == 10550
    cash_before = a.cash
    duo.act("A", "UNEMPLOYMENT")
    a = duo.player("A")
    assert a.cash == cash_before - total_exp
    assert a.skip_turns == 2
    assert a.charity_turns == 0                      # 失业清除慈善
    duo.act("A", "END_TURN")
    # A 停赛 2 轮：接下来两次都轮到 B
    assert duo.state.current_player_id == "B"
    duo.act("B", "END_TURN")
    assert duo.state.current_player_id == "B"        # A 被跳过（2→1）
    duo.act("B", "END_TURN")
    assert duo.state.current_player_id == "B"        # A 被跳过（1→0）
    duo.act("B", "END_TURN")
    assert duo.state.current_player_id == "A"        # 复赛


# ---------- 银行：贷款/还款利息递减/清偿（§7） ----------

def test_loan_and_partial_repay(duo):
    duo.act("A", "TAKE_LOAN", amount=5000)
    a = duo.player("A")
    assert a.cash == 3950 + 5000
    assert F.bank_loan_expense(a) == 500
    duo.act("A", "REPAY_LOAN", amount=2000)
    a = duo.player("A")
    assert a.liabilities.bank_loan == 3000
    assert F.bank_loan_expense(a) == 300             # 利息按千元递减
    assert F.monthly_cashflow(a) == 3550 - 300
    with pytest.raises(EngineError, match="1,000"):
        duo.act("A", "TAKE_LOAN", amount=1500)


def test_pay_off_car_loan(duo):
    duo.act("A", "HOST_ADJUST", playerId="A", delta=20000, reason="测试注资")
    duo.act("A", "PAY_OFF_DEBT", liabilityId="car_loan")
    a = duo.player("A")
    assert a.liabilities.car_loan == 0
    assert a.car_loan_payment == 0
    assert F.total_expenses(a) == 9650 - 380
    assert a.cash == 3950 + 20000 - 19000
    # 税金/其他支出/孩子支出为长期支出不可清偿
    with pytest.raises(EngineError):
        duo.act("A", "PAY_OFF_DEBT", liabilityId="taxes")


# ---------- 机会卡转卖（§6.5 / FR-15） ----------

def test_resell_opportunity(duo):
    duo.act("A", "DRAW_CARD", cardId="sd-house-3b2b-01")
    duo.act("A", "CARD_DECISION", decision="resell", toPlayerId="B", price=500)
    pr = duo.state.prompts[0]
    assert pr.kind == "RESELL_CONFIRM" and pr.target_player_id == "B"
    duo.act("B", "TAKE_LOAN", amount=2000)           # 买家贷款补差
    duo.act("B", "RESELL_CONFIRM", promptId=pr.id, accept=True)
    a, b = duo.player("A"), duo.player("B")
    assert a.cash == 3950 + 500                      # 转让费
    assert b.cash == 2070 + 2000 - 500 - 3000        # 贷款 − 费用 − 按卡面首付购入
    assert len(b.real_estates) == 1
    assert b.real_estates[0].cashflow == 100


def test_transfer_between_players(duo):
    duo.act("A", "TRANSFER_REQUEST", toPlayerId="B", amount=1000, reason="线下议定")
    pr = duo.state.prompts[0]
    duo.act("B", "TRANSFER_CONFIRM", promptId=pr.id, accept=True)
    assert duo.player("A").cash == 3950 - 1000
    assert duo.player("B").cash == 2070 + 1000


# ---------- 破产三种出口（§8） ----------

def _push_to_brink(duo):
    """医生 A：借 4 万 → 利息 4,000/月，月现金流 −450，现金压到 100。"""
    duo.act("A", "TAKE_LOAN", amount=40000)
    duo.state.players["A"].cash = 100
    a = duo.player("A")
    assert F.monthly_cashflow(a) == -450
    with pytest.raises(EngineError, match="NEED_LOAN_OR_BANKRUPTCY".replace("_", ".*")) :
        duo.act("A", "PAYDAY")


def test_bankruptcy_recover_by_selling(duo):
    # A 持有月现金流 500 的房产：卖掉后现金流转正
    duo.state.players["A"].real_estates.append(RealEstate(
        id="r-big", card_id="x", asset_type="4室公寓", name="4室公寓",
        cost=125000, down_payment=30000, mortgage=95000, cashflow=500))
    duo.act("A", "TAKE_LOAN", amount=40000)
    duo.state.players["A"].cash = 100
    assert F.monthly_cashflow(duo.player("A")) == 50   # 3550+500-4000
    duo.state.players["A"].liabilities.bank_loan = 45000  # 利息 4,500 → 现金流 −450
    assert F.monthly_cashflow(duo.player("A")) == -450
    duo.act("A", "BANKRUPTCY_START")
    duo.act("A", "BANKRUPTCY_SELL_ASSET", assetId="r-big")
    a = duo.player("A")
    assert a.cash == 100 + 30000 // 2                # 首期付款的 50%
    assert a.real_estates == []
    assert F.monthly_cashflow(a) == -950             # 失去 500 现金流
    # 还贷 10,000 → 利息 3,500 → 现金流 +50 转正
    duo.act("A", "REPAY_LOAN", amount=10000)
    duo.act("A", "BANKRUPTCY_RESOLVE")
    a = duo.player("A")
    assert not a.in_bankruptcy
    assert a.skip_turns == 3                         # 复活：停赛 3 轮
    assert a.phase == Phase.RAT_RACE


def test_bankruptcy_recover_by_debt_writeoff(duo):
    """无资产可卖 → 注销购车/信用卡/额外负债各 50% 后转正。"""
    duo.act("A", "TAKE_LOAN", amount=36000)          # 利息 3,600 → 现金流 −50
    duo.state.players["A"].cash = 10
    a = duo.player("A")
    assert F.monthly_cashflow(a) == -50
    duo.act("A", "BANKRUPTCY_START")
    duo.act("A", "BANKRUPTCY_RESOLVE")
    a = duo.player("A")
    assert a.liabilities.car_loan == 9500            # 19,000 → 50%
    assert a.liabilities.credit_card == 4500
    assert a.liabilities.extra == 500
    assert a.car_loan_payment == 190
    assert a.credit_card_payment == 135
    assert a.extra_expenses == 25
    assert F.monthly_cashflow(a) == -50 + 190 + 135 + 25
    assert a.skip_turns == 3 and a.phase == Phase.RAT_RACE


def test_bankruptcy_out(duo):
    duo.act("A", "TAKE_LOAN", amount=40000)          # 利息 4,000 → −450；减债后仍 −100
    duo.state.players["A"].cash = 10
    duo.act("A", "BANKRUPTCY_START")
    duo.act("A", "BANKRUPTCY_RESOLVE")
    a = duo.player("A")
    assert a.phase == Phase.OUT
    # 两人局只剩 1 人 → 对局结束
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "B"


# ---------- 进入快车道（§9） ----------

def _give_passive(duo, pid, cashflow):
    duo.state.players[pid].businesses.append(OwnedBusiness(
        id=f"biz-{pid}", card_id="x", name="测试企业", cost=0,
        down_payment=0, cashflow=cashflow))


def test_enter_fasttrack_conversion(duo):
    _give_passive(duo, "A", 9700)                    # 非工资 9,700 > 总支出 9,650
    duo.act("A", "ENTER_FASTTRACK")
    a = duo.player("A")
    assert a.phase == Phase.FAST_TRACK
    assert a.cash == 0                               # 现金交回银行
    assert a.fasttrack.initial_income == 1_000_000   # 9,700→10,000×100
    duo.act("A", "FT_PAYDAY")
    assert duo.player("A").cash == 1_000_000


def test_enter_fasttrack_rejected_when_not_eligible(duo):
    with pytest.raises(EngineError, match="尚未达成"):
        duo.act("A", "ENTER_FASTTRACK")


def test_no_bank_loan_in_fasttrack(duo):
    _give_passive(duo, "A", 9700)
    duo.act("A", "ENTER_FASTTRACK")
    with pytest.raises(EngineError, match="快车道无银行贷款"):
        duo.act("A", "TAKE_LOAN", amount=1000)


# ---------- 快车道：绿格/梦想/胜利（§10、§11） ----------

def _enter_ft(duo, pid, passive=9700):
    _give_passive(duo, pid, passive)
    if duo.state.current_player_id != pid:
        duo.act(duo.state.current_player_id, "END_TURN")
    duo.act(pid, "ENTER_FASTTRACK")
    duo.act(pid, "FT_PAYDAY")                        # 领第一笔现金


def test_ft_business_and_income_victory(duo):
    _enter_ft(duo, "A")
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-inn")       # +14,000
    a = duo.player("A")
    assert a.fasttrack.current_income == 1_000_000 + 14000
    assert duo.state.status == RoomStatus.PLAYING
    # 掷骰格：俄罗斯石油 ≥4 成功 +75,000 → 累计 ≥ +50,000 胜利
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-russia-oil", diceRoll=5)
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "A"


def test_ft_dice_business_failure_keeps_square_open(duo):
    _enter_ft(duo, "A")
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-goldmine", diceRoll=2)
    a = duo.player("A")
    assert a.cash == 1_000_000 - 150000              # 钱已付
    assert a.fasttrack.businesses == []              # 未获得现金流
    assert "ft-b-goldmine" not in duo.state.ft_sold_squares    # 成功前保持开放
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-goldmine", diceRoll=3)
    assert duo.player("A").fasttrack.current_income == 1_050_000
    assert "ft-b-goldmine" in duo.state.ft_sold_squares


def test_ft_lumpsum_stock_not_counted_for_victory(duo):
    _enter_ft(duo, "A")
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-biotech", diceRoll=6)
    a = duo.player("A")
    assert a.cash == 1_000_000 - 50000 + 500000      # 一次性现金收益
    assert a.fasttrack.current_income == 1_000_000   # 不计入现金流量日收入
    assert duo.state.status == RoomStatus.PLAYING    # 不触发 +50,000 胜利


def test_ft_business_exclusive(duo):
    _enter_ft(duo, "A")
    duo.act("A", "FT_BUY_BUSINESS", squareId="ft-b-drycleaner")
    duo.act("A", "END_TURN")
    _enter_ft(duo, "B")
    with pytest.raises(EngineError, match="买断"):
        duo.act("B", "FT_BUY_BUSINESS", squareId="ft-b-drycleaner")


def test_ft_dream_double_bump_twice_then_buy(duo):
    _enter_ft(duo, "A")                              # A 的梦想 safari，B 的梦想 jet(250,000)
    duo.act("A", "FT_PAYDAY")                        # 再领一笔，现金 2,000,000
    duo.act("A", "FT_DOUBLE_DREAM", squareId="ft-d-jet")
    assert duo.player("A").cash == 2_000_000 - 250000
    duo.act("A", "FT_DOUBLE_DREAM", squareId="ft-d-jet")
    assert duo.player("A").cash == 2_000_000 - 250000 - 500000  # 第二次按加价后价格
    assert duo.state.dream_price_bumps["ft-d-jet"] == 2
    duo.act("A", "END_TURN")
    _enter_ft(duo, "B")
    duo.act("B", "FT_PAYDAY")
    # B 购买自己梦想须按累加价 750,000
    duo.act("B", "FT_BUY_DREAM", squareId="ft-d-jet")
    assert duo.player("B").cash == 2_000_000 - 750000
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "B"


def test_ft_buy_own_dream_victory(duo):
    _enter_ft(duo, "A")
    duo.act("A", "FT_BUY_DREAM", squareId="ft-d-safari")       # 100,000
    assert duo.state.status == RoomStatus.FINISHED
    assert duo.state.winner_id == "A"
    assert duo.player("A").cash == 1_000_000 - 100000


def test_ft_cash_hits_and_charity(duo, lib):
    _enter_ft(duo, "A")
    duo.act("A", "FT_TAX_AUDIT")
    assert duo.player("A").cash == 500_000           # 半额
    duo.act("A", "FT_CHARITY")
    a = duo.player("A")
    assert a.cash == 400_000 and a.fasttrack.charity_forever
    duo.act("A", "FT_LAWSUIT")
    assert duo.player("A").cash == 200_000
    duo.act("A", "FT_DIVORCE")
    assert duo.player("A").cash == 0


# ---------- 孩子（§5） ----------

def test_children_cap(duo):
    for expect in (1, 2, 3, 3):                      # 第 4 次无效果
        duo.act("A", "ADD_CHILD")
        assert duo.player("A").child_count == expect
    assert F.child_expense(duo.player("A")) == 640 * 3
