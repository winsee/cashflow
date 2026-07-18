"""§13.1 公式回归：三组说明书数值逐项吻合（design/02 §3.2）。"""
from .. import formulas as F
from ..models import OwnedBusiness, PlayerState, RealEstate, StockHolding, Liabilities


def make_doctor() -> PlayerState:
    return PlayerState(
        id="p", nickname="医生", salary=13200, taxes=3420, mortgage_payment=1900,
        school_loan_payment=750, car_loan_payment=380, credit_card_payment=270,
        extra_expenses=50, other_expenses=2880, per_child_expense=640,
        liabilities=Liabilities(mortgage=190000, school_loan=150000,
                                car_loan=19000, credit_card=9000, extra=1000),
    )


def test_doctor_p7():
    p = make_doctor()
    assert F.total_expenses(p) == 9650
    assert F.total_income(p) == 13200
    assert F.monthly_cashflow(p) == 3550


def test_manager_card():
    p = PlayerState(
        id="p", nickname="经理", salary=4600, taxes=910, mortgage_payment=700,
        school_loan_payment=60, car_loan_payment=120, credit_card_payment=90,
        extra_expenses=50, other_expenses=1000, per_child_expense=240,
        liabilities=Liabilities(mortgage=75000, school_loan=12000,
                                car_loan=7000, credit_card=4000, extra=1000),
    )
    assert F.total_expenses(p) == 2930
    assert F.monthly_cashflow(p) == 1670


def test_p12_example():
    """P.12：工资2,500 + 股利100 + 房产140+800 + 企业1,600 → 非工资2,640 > 总支出2,490。"""
    p = PlayerState(
        id="p", nickname="示例", salary=2500,
        stocks=[StockHolding(symbol="X", shares=100, cost_per_share=1, dividend_per_share=1)],
        real_estates=[
            RealEstate(id="r1", card_id="c", asset_type="2室1厅", name="房1",
                       cost=0, down_payment=0, mortgage=0, cashflow=140),
            RealEstate(id="r2", card_id="c", asset_type="8室公寓", name="房2",
                       cost=0, down_payment=0, mortgage=0, cashflow=800),
        ],
        businesses=[OwnedBusiness(id="b1", card_id="c", name="企业", cost=0,
                                  down_payment=0, cashflow=1600)],
        taxes=2490,   # 其余支出合并计入，使总支出=2,490
    )
    assert F.dividend_income(p) == 100
    assert F.passive_income(p) == 2640
    assert F.total_income(p) == 5140
    assert F.total_expenses(p) == 2490
    assert F.monthly_cashflow(p) == 2650
    assert F.can_enter_fasttrack(p) is True


def test_bank_loan_expense():
    p = make_doctor()
    p.liabilities.bank_loan = 3000
    assert F.bank_loan_expense(p) == 300   # 每借$1,000月息$100
    assert F.total_expenses(p) == 9650 + 300


def test_child_expense():
    p = make_doctor()
    p.child_count = 2
    assert F.child_expense(p) == 1280
    assert F.total_expenses(p) == 9650 + 1280


def test_fasttrack_conversion_rounding():
    """进入快车道换算边界：2,640→300,000；2,400→200,000；2,500→300,000（§13.2）。"""
    assert F.fasttrack_initial_income(2640) == 300_000
    assert F.fasttrack_initial_income(2400) == 200_000
    assert F.fasttrack_initial_income(2500) == 300_000
