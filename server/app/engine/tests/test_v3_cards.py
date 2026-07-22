"""v3 全量卡库回归（design/07 §5）——每条对应一个真实会算错钱的场景。

用真实的 194 张卡跑，不构造假卡：这些用例存在的意义就是盯住「引擎读的数值
是否等于实体卡上印的数值」，用假卡就把要防的东西防掉了。
"""
import pytest

from .. import engine as E
from .. import formulas as F
from ..errors import EngineError
from ..models import OwnedBusiness, Phase, RealEstate


def _cycle(duo, pid="A"):
    duo.act(duo.state.current_player_id, "END_TURN")
    while duo.state.current_player_id != pid:
        duo.act(duo.state.current_player_id, "END_TURN")


def _give(duo, pid, **kw):
    """直接塞一份资产给玩家，省掉抽卡买入的铺垫。"""
    kind = kw.pop("kind", "REALESTATE")
    base = dict(id=kw.pop("id", f"a-{pid}-{len(duo.player(pid).real_estates)}"),
                card_id="x", cost=0, down_payment=0, mortgage=0, cashflow=0)
    base.update(kw)
    asset = (RealEstate(**base) if kind == "REALESTATE" else OwnedBusiness(**base))
    target = (duo.player(pid).real_estates if kind == "REALESTATE"
              else duo.player(pid).businesses)
    target.append(asset)
    return asset


def _prompts(duo, pid=None):
    return [p for p in duo.state.prompts
            if p.kind == "MARKET_SELL" and (pid is None or p.target_player_id == pid)]


# ---------- 1. 按间计价：算错基准最大差 13 倍 ----------

def test_per_room_pricing_counts_rooms(duo):
    """持 8 室公寓遇 mk-020（PER_ROOM $40,000）→ $320,000，不是 $40,000。"""
    _give(duo, "B", id="apt8", asset_type="公寓", rooms=8, name="8室公寓",
          cost=220000, down_payment=20000, mortgage=200000, cashflow=1700)
    duo.act("A", "DRAW_CARD", cardId="mk-020")
    pr = _prompts(duo, "B")[0]
    assert pr.payload["price"] == 8 * 40000 == 320000


def test_per_room_pricing_scales_with_room_count(duo):
    """同一张卡对 2 室公寓只值 $80,000——房间数必须真的参与计算。"""
    _give(duo, "B", id="apt2", asset_type="公寓", rooms=2, name="2室公寓",
          cost=60000, down_payment=6000, mortgage=54000, cashflow=450)
    duo.act("A", "DRAW_CARD", cardId="mk-020")
    assert _prompts(duo, "B")[0].payload["price"] == 2 * 40000


# ---------- 2. 套数门槛 ----------

def test_min_units_threshold_blocks_and_allows(duo):
    """mk-015 求购 12 套以上：8 套不可售，24 套按 $30,000/套 = $720,000。"""
    _give(duo, "A", id="apt8u", asset_type="公寓楼", units=8, name="8套公寓楼",
          cost=200000, down_payment=20000, mortgage=180000, cashflow=800)
    duo.act("A", "DRAW_CARD", cardId="mk-015")
    assert _prompts(duo) == []                      # 不满门槛：连要约都不该推

    _cycle(duo)
    _give(duo, "B", id="apt24u", asset_type="公寓楼", units=24, name="24套公寓楼",
          cost=575000, down_payment=75000, mortgage=500000, cashflow=2500)
    duo.act("A", "DRAW_CARD", cardId="mk-015")
    assert _prompts(duo, "B")[0].payload["price"] == 24 * 30000 == 720000


# ---------- 3. chargeOnce：持有多套也只付一套 ----------

def test_charge_once_bills_single_unit(duo):
    """持 3 套 8 室公寓遇 bd-003 → 只扣 $2,000（旧逻辑会扣 $6,000）。"""
    for i in range(3):
        _give(duo, "A", id=f"apt8-{i}", asset_type="公寓", rooms=8,
              name="8室公寓", cost=220000, down_payment=20000,
              mortgage=200000, cashflow=1700)
    cash_before = duo.player("A").cash
    duo.act("A", "DRAW_CARD", cardId="bd-003")
    assert E.settlement_preview(duo.state, duo.lib)["due"] == 2000
    duo.act("A", "CARD_DECISION", decision="pay")
    assert duo.player("A").cash == cash_before - 2000


def test_charge_once_respects_target_rooms(duo):
    """bd-003 只针对 8 室公寓：手上只有 4 室公寓时豁免。"""
    _give(duo, "A", id="apt4", asset_type="公寓", rooms=4, name="4室公寓",
          cost=125000, down_payment=15000, mortgage=110000, cashflow=900)
    cash_before = duo.player("A").cash
    duo.act("A", "DRAW_CARD", cardId="bd-003")
    assert E.settlement_preview(duo.state, duo.lib) == {
        "due": 0, "note": "无相关房产，无需支付", "waived": True}
    duo.act("A", "CARD_DECISION", decision="pay")
    assert duo.player("A").cash == cash_before


# ---------- 4. appliesTo：只有抽卡人付 ----------

def test_drawer_only_expense_leaves_others_untouched(duo):
    """bd-038 只扣抽卡人，其他持房玩家不动账。"""
    _give(duo, "A", id="hA", asset_type="3室2厅", name="A的房",
          cost=50000, down_payment=3000, mortgage=47000, cashflow=100)
    _give(duo, "B", id="hB", asset_type="3室2厅", name="B的房",
          cost=50000, down_payment=3000, mortgage=47000, cashflow=100)
    a_before, b_before = duo.player("A").cash, duo.player("B").cash
    duo.act("A", "DRAW_CARD", cardId="bd-038")
    duo.act("A", "CARD_DECISION", decision="pay")
    assert duo.player("A").cash == a_before - 1000
    assert duo.player("B").cash == b_before          # 同样持房，分文不动


# ---------- 5. buyerScope：谁能买 ----------

def test_buyer_scope_drawer_only_rejects_others(duo):
    """sd-008 印「只有你一个买主」→ 非抽卡人买入被拒。"""
    duo.act("A", "DRAW_CARD", cardId="sd-008")
    with pytest.raises(EngineError) as ei:
        duo.act("B", "STOCK_BUY", qty=1)
    assert ei.value.code == "NOT_DRAWER"


def test_buyer_scope_all_allows_everyone(duo):
    """sd-001 优先股 / sd-029 CD 印「每个人都能以此价格购买」→ 人人可买。"""
    duo.act("A", "DRAW_CARD", cardId="sd-001")
    b_before = duo.player("B").cash
    duo.act("B", "STOCK_BUY", qty=1)
    assert duo.player("B").cash == b_before - 1200
    assert duo.player("B").stocks[0].symbol == "2BIG"


# ---------- 6. incomeCategory：利息 ≠ 股利 ----------

def test_cd_income_lands_in_interest_row(duo):
    """买入 CD 后「利息」栏 +$20，「股利」栏不变（说明书 p7 记录卡）。"""
    a = duo.player("A")
    interest_before, dividend_before = F.interest_income(a), F.dividend_income(a)
    a.cash += 5000                                   # 备够本金
    duo.act("A", "DRAW_CARD", cardId="sd-029")
    duo.act("A", "STOCK_BUY", qty=1)
    a = duo.player("A")
    assert F.interest_income(a) == interest_before + 20
    assert F.dividend_income(a) == dividend_before
    assert F.passive_income(a) == interest_before + dividend_before + 20


def test_preferred_stock_income_lands_in_dividend_row(duo):
    a = duo.player("A")
    interest_before, dividend_before = F.interest_income(a), F.dividend_income(a)
    duo.act("A", "DRAW_CARD", cardId="sd-001")
    duo.act("A", "STOCK_BUY", qty=2)
    a = duo.player("A")
    assert F.dividend_income(a) == dividend_before + 20   # 2 股 × $10
    assert F.interest_income(a) == interest_before


# ---------- 7. 负现金流资产 ----------

def test_negative_cashflow_asset_reduces_monthly(duo):
    """买入 bd-041 后月现金流减少 $100——cashflow 可为负。"""
    a = duo.player("A")
    a.cash += 10000
    cf_before = F.monthly_cashflow(a)
    duo.act("A", "DRAW_CARD", cardId="bd-041")
    duo.act("A", "CARD_DECISION", decision="buy")
    assert F.monthly_cashflow(duo.player("A")) == cf_before - 100


# ---------- 8. 零首付 ----------

def test_zero_down_payment_purchase(duo):
    """sd-031：现金不变、负债 +$50,000、月现金流 +$100。"""
    a = duo.player("A")
    cash_before, cf_before = a.cash, F.monthly_cashflow(a)
    duo.act("A", "DRAW_CARD", cardId="sd-031")
    duo.act("A", "CARD_DECISION", decision="buy")
    a = duo.player("A")
    assert a.cash == cash_before                     # 零首付：不掏钱
    assert a.real_estates[-1].mortgage == 50000
    assert F.monthly_cashflow(a) == cf_before + 100


# ---------- 9. 并股：总成本不变 ----------

def test_stock_merge_keeps_total_cost(duo):
    """sd-009 并股 2:1：股数减半而总成本不变，事件期间交易窗口关闭。"""
    duo.player("A").cash += 10000
    duo.act("A", "DRAW_CARD", cardId="sd-003")       # MYT4U $30
    duo.act("A", "STOCK_BUY", qty=10)
    _cycle(duo)
    held = duo.player("A").stocks[0]
    cost_before = held.shares * held.cost_per_share

    duo.act("A", "DRAW_CARD", cardId="sd-009")
    with pytest.raises(EngineError):                 # 并股期间不能交易
        duo.act("A", "STOCK_BUY", qty=1)
    duo.act("A", "CARD_DECISION", decision="apply")
    held = duo.player("A").stocks[0]
    assert held.shares == 5                          # 每两股并一股
    assert held.cost_per_share == 60                 # 单价翻倍抵消股数减半
    assert held.shares * held.cost_per_share == cost_before   # 总成本不变


# ---------- 10. 骰子赌局 ----------

@pytest.mark.parametrize("roll,expect_payout", [(4, 10000), (5, 10000),
                                                (6, 10000), (1, 0), (2, 0), (3, 0)])
def test_dice_gamble_payout_by_roll(duo, monkeypatch, roll, expect_payout):
    """sd-013：付 $5,000 掷 1 骰，>3 得 $10,000，否则血本无归。"""
    monkeypatch.setattr(E._dice_rng, "randint", lambda a, b: roll)
    duo.player("A").cash += 5000                     # 备够本金
    cash_before = duo.player("A").cash
    duo.act("A", "DRAW_CARD", cardId="sd-013")
    evs = duo.act("A", "CARD_DECISION", decision="buy")
    ev = evs[0]["payload"]
    assert ev["rolls"] == [roll] and ev["won"] is (roll > 3)
    assert duo.player("A").cash == cash_before - 5000 + expect_payout


def test_dice_gamble_roll_is_recorded_and_replayable(duo, monkeypatch):
    """骰子结果必须进事件流：重放同一串事件得到同样的钱。"""
    monkeypatch.setattr(E._dice_rng, "randint", lambda a, b: 5)
    duo.act("A", "TAKE_LOAN", amount=5000)           # 走事件，重放才看得见
    duo.act("A", "DRAW_CARD", cardId="sd-013")
    duo.act("A", "CARD_DECISION", decision="buy")
    assert duo.replay().players["A"].cash == duo.player("A").cash


# ---------- 11. 企业细分匹配 ----------

def test_business_kind_must_match_by_name(duo):
    """持 sd-018 小型机械公司：mk-033（求购软件公司）不匹配，mk-025 可售 $50,000。"""
    duo.act("A", "DRAW_CARD", cardId="sd-018")
    duo.act("A", "CARD_DECISION", decision="buy")
    _cycle(duo)

    duo.act("A", "DRAW_CARD", cardId="mk-033")       # 求购软件公司
    assert _prompts(duo) == []
    _cycle(duo)

    duo.act("A", "DRAW_CARD", cardId="mk-025")       # 求购小机械公司
    assert _prompts(duo, "A")[0].payload["price"] == 50000


def test_cashflow_modifier_targets_asset_type(duo):
    """mk-008 泛指「自建企业」：给资产条目本身加 $250/月。"""
    duo.act("A", "DRAW_CARD", cardId="sd-018")
    duo.act("A", "CARD_DECISION", decision="buy")
    _cycle(duo)
    cf_before = F.monthly_cashflow(duo.player("A"))
    duo.act("A", "DRAW_CARD", cardId="mk-008")
    a = duo.player("A")
    assert a.businesses[-1].cashflow == 250           # 原本 0
    assert F.monthly_cashflow(a) == cf_before + 250


def test_carwash_matched_across_asset_types(duo):
    """mk-035 只写 targetBusinessKind → 同时命中洗车店与自动化企业（design/06 §6.5）。"""
    _give(duo, "A", kind="BUSINESS", id="cw1", asset_type="洗车店",
          business_kind="汽车清洗公司", name="洗车店",
          cost=350000, down_payment=50000, mortgage=300000, cashflow=1500)
    _give(duo, "B", kind="BUSINESS", id="cw2", asset_type="自动化企业",
          business_kind="汽车清洗公司", name="4家投币式洗车店",
          cost=125000, down_payment=25000, mortgage=100000, cashflow=1800)
    duo.act("A", "DRAW_CARD", cardId="mk-035")
    assert len(_prompts(duo, "A")) == 1 and len(_prompts(duo, "B")) == 1


def test_loss_making_offer_is_still_pushed(duo):
    """卖了会亏也必须推要约——玩家可能为套现渡过破产危机而主动贱卖（§6.5）。"""
    _give(duo, "A", kind="BUSINESS", id="cw1", asset_type="洗车店",
          business_kind="汽车清洗公司", name="洗车店",
          cost=350000, down_payment=50000, mortgage=300000, cashflow=1500)
    duo.act("A", "DRAW_CARD", cardId="mk-035")       # 报价 $25,000 vs 抵押 $300,000
    pr = _prompts(duo, "A")[0]
    assert pr.payload["price"] == 25000 and pr.payload["mortgage"] == 300000


# ---------- 12. 土地变现 ----------

def test_land_matches_merged_asset_type(duo):
    """sd-017（$5,000 买入）遇 mk-026 可售 $150,000——全库唯一的 30 倍路径。"""
    duo.player("A").cash += 5000
    duo.act("A", "DRAW_CARD", cardId="sd-017")
    duo.act("A", "CARD_DECISION", decision="buy")
    _cycle(duo)
    cash_before = duo.player("A").cash
    duo.act("A", "DRAW_CARD", cardId="mk-026")
    pr = _prompts(duo, "A")[0]
    assert pr.payload["price"] == 150000
    duo.act("A", "MARKET_SELL", promptId=pr.id, accept=True)
    assert duo.player("A").cash == cash_before + 150000   # 无抵押，全额到手
    assert duo.player("A").real_estates == []


# ---------- 13. 分期收款（mk-029 亲戚分期买房：冻结房产模型，design/06 §6.4） ----------

def _sell_house_on_installment(duo, mortgage=0):
    """给 A 一套 3室2厅（月租 $100，抵押可选）并接受 mk-029 的分期收购。

    返回 (持房状态下的月现金流, 房产 id)。房子成交后只是冻结，不移除。
    """
    house = _give(duo, "A", id="h3b2b", asset_type="3室2厅", name="3室2厅",
                  cost=50000, down_payment=3000, mortgage=mortgage, cashflow=100)
    cf_holding = F.monthly_cashflow(duo.player("A"))
    duo.act("A", "DRAW_CARD", cardId="mk-029")
    pr = _prompts(duo, "A")[0]
    duo.act("A", "MARKET_SELL", promptId=pr.id, accept=True)
    return cf_holding, house.id


def test_installment_sale_freezes_house_no_cash_move(duo):
    """成交只是冻结房子：不动现金、不移房、租金照收，月现金流仅额外 −$500。"""
    cash_before = duo.player("A").cash
    cf_holding, house_id = _sell_house_on_installment(duo)
    a = duo.player("A")
    assert [r.id for r in a.real_estates] == [house_id]   # 房子仍在（冻结，非移除）
    assert house_id in a.frozen_asset_ids
    assert a.cash == cash_before                          # 不收首付、不动现金
    assert F.monthly_cashflow(a) == cf_holding - 500      # 租金仍在，只额外扣 500
    assert a.installment_receivables[0].months_elapsed == 0


def test_installment_sale_keeps_mortgage_no_payoff(duo):
    """带抵押的房子分期卖出：不当场结清抵押，卖方一分钱不掏。"""
    cash_before = duo.player("A").cash
    _cf, house_id = _sell_house_on_installment(duo, mortgage=47000)
    a = duo.player("A")
    assert a.cash == cash_before                          # 抵押不解押，无现金流出
    house = next(h for h in a.real_estates if h.id == house_id)
    assert house.mortgage == 47000                        # 房贷照旧挂着


def test_installment_frozen_house_immune_to_market_cards(duo):
    """冻结房不在市场上：求购/溢价收购推不到它，通货膨胀也没收不了它（Q2 裁决）。"""
    _sell_house_on_installment(duo)
    _cycle(duo)                                       # 成交那回合的停留格已用掉
    # 溢价收购 3室2厅（mk-006）：冻结房不应被推要约
    duo.act("A", "DRAW_CARD", cardId="mk-006")
    assert _prompts(duo, "A") == []
    _cycle(duo)
    # 通货膨胀强制没收全部 3室2厅（mk-002）：冻结房免疫，仍在手上
    duo.act("A", "DRAW_CARD", cardId="mk-002")
    assert len(duo.player("A").real_estates) == 1


def test_installment_sale_settles_on_completion(duo):
    """第 200 个结算日：移交房产、一次性入账 $100,000、−$500 停止。"""
    cf_holding, house_id = _sell_house_on_installment(duo)
    r = duo.player("A").installment_receivables[0]
    assert r.duration_months == 200 and r.asset_id == house_id
    r.months_elapsed = 199                            # 快进到最后一个月
    cf_with_hold = F.monthly_cashflow(duo.player("A"))   # = cf_holding − 500

    _cycle(duo)
    cash_before = duo.player("A").cash
    duo.act("A", "PAYDAY")
    a = duo.player("A")
    assert a.installment_receivables[0].settled
    assert a.real_estates == []                       # 全款收齐，房产移交
    assert a.cash == cash_before + cf_with_hold + 100000
    # 房子没了，租金也停：月现金流回到「没有这套房」的基线
    assert F.monthly_cashflow(a) == cf_holding - 100


def test_installment_multi_payday_does_not_overcharge(duo):
    """一次过 3 个结算日跨过期满月：期满后的月份多算的「租金 + (−500)」要退回。"""
    _sell_house_on_installment(duo)                   # 租金 +100，挂账 −500 → 净 −400/月
    r = duo.player("A").installment_receivables[0]
    r.months_elapsed = 198                            # 还剩 2 个月，却要过 3 个
    cf = F.monthly_cashflow(duo.player("A"))

    _cycle(duo)
    cash_before = duo.player("A").cash
    duo.act("A", "PAYDAY", times=3)
    a = duo.player("A")
    # 第 3 个月房已移交：那个月不该有 +100 租金也不该扣 −500，退回净 400
    assert a.cash == cash_before + cf * 3 + 400 + 100000
    assert a.installment_receivables[0].months_elapsed == 200
    assert a.real_estates == []


def test_installment_bankruptcy_wipes_receivable_and_house(duo):
    """中途破产出局：冻结房被银行收回、未收欠款直接清零，玩家一分未得（Q1 裁决）。"""
    _sell_house_on_installment(duo)
    a = duo.player("A")
    a.cash = 0
    a.extra_expenses += 10000                         # 逼出负现金流，且现金不足支付
    assert F.monthly_cashflow(a) < 0
    duo.act("A", "BANKRUPTCY_START")
    # 唯一资产是冻结房，不能变卖 → 直接结算 → 资不抵债出局
    with pytest.raises(EngineError, match="冻结"):
        duo.act("A", "BANKRUPTCY_SELL_ASSET", assetId="h3b2b")
    duo.act("A", "BANKRUPTCY_RESOLVE")
    a = duo.player("A")
    assert a.phase == Phase.OUT
    assert a.installment_receivables == []            # 欠款清零，未兑现一分
    assert a.real_estates == []                       # 冻结房被银行收走
