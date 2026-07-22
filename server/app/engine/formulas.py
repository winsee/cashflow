"""派生公式（design/02 §3.2）。服务器每次变更后重算，客户端只显示。"""
from __future__ import annotations

from .models import PlayerState

BANK_LOAN_MONTHLY_RATE = 0.10   # P.4：每借 $1,000 月息 $100


def _stock_income(p: PlayerState, category: str) -> int:
    return sum(s.shares * s.dividend_per_share
               for s in p.stocks if s.income_category == category)


def interest_income(p: PlayerState) -> int:
    """记录卡「利息」栏：职业卡固定利息 + 银行存单（CD）等计息证券。"""
    return p.interest_income + _stock_income(p, "INTEREST")


def dividend_income(p: PlayerState) -> int:
    """记录卡「股利」栏：只含按股分红的证券，不含 CD 的利息（说明书 p7）。"""
    return _stock_income(p, "DIVIDEND")


def real_estate_income(p: PlayerState) -> int:
    return sum(r.cashflow for r in p.real_estates)


def business_income(p: PlayerState) -> int:
    return sum(b.cashflow for b in p.businesses)


def installment_cashflow(p: PlayerState) -> int:
    """未结清的分期收款挂账对月现金流的影响（mk-029：收齐前 −$500/月）。"""
    return sum(r.monthly_delta for r in p.installment_receivables if not r.settled)


def passive_income(p: PlayerState) -> int:
    """非工资收入 = 利息 + 股利 + 房地产 + 企业投资（说明书 p7 记录卡四行）。

    分期收款挂账计入此处：房产已移交，它顶替的正是原来那笔租金现金流。
    """
    return (
        interest_income(p)
        + dividend_income(p)
        + real_estate_income(p)
        + business_income(p)
        + installment_cashflow(p)
    )


def total_income(p: PlayerState) -> int:
    return p.salary + passive_income(p)


def child_expense(p: PlayerState) -> int:
    return p.per_child_expense * p.child_count


def bank_loan_expense(p: PlayerState) -> int:
    return p.liabilities.bank_loan // 10   # 贷款恒为 $1,000 整数倍，整除无误差


def card_monthly_expenses(p: PlayerState) -> int:
    return sum(l.monthly for l in p.extra_liabilities)


def total_expenses(p: PlayerState) -> int:
    return (
        p.taxes
        + p.mortgage_payment
        + p.school_loan_payment
        + p.car_loan_payment
        + p.credit_card_payment
        + p.extra_expenses
        + p.other_expenses
        + child_expense(p)
        + bank_loan_expense(p)
        + card_monthly_expenses(p)
    )


def monthly_cashflow(p: PlayerState) -> int:
    return total_income(p) - total_expenses(p)


def can_enter_fasttrack(p: PlayerState) -> bool:
    """进入快车道条件 = 非工资收入 > 总支出（P.3、P.5）"""
    return passive_income(p) > total_expenses(p)


def fasttrack_initial_income(passive: int) -> int:
    """财产 = 非工资收入以千元为单位四舍五入 ×100（design/02 §9）。
    2,640→300,000；2,400→200,000；2,500→300,000（half-up）。
    """
    thousands = (passive + 500) // 1000
    return thousands * 100_000


def derived(p: PlayerState) -> dict:
    """打包给客户端显示的派生数值。"""
    return {
        # 记录卡收入栏四行（说明书 p7）
        "interestIncome": interest_income(p),
        "dividendIncome": dividend_income(p),
        "realEstateIncome": real_estate_income(p),
        "businessIncome": business_income(p),
        "installmentCashflow": installment_cashflow(p),
        "passiveIncome": passive_income(p),
        "totalIncome": total_income(p),
        "childExpense": child_expense(p),
        "bankLoanExpense": bank_loan_expense(p),
        "cardMonthlyExpenses": card_monthly_expenses(p),
        "totalExpenses": total_expenses(p),
        "monthlyCashflow": monthly_cashflow(p),
        "canEnterFasttrack": can_enter_fasttrack(p),
    }
