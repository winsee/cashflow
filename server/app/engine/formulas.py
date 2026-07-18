"""派生公式（design/02 §3.2）。服务器每次变更后重算，客户端只显示。"""
from __future__ import annotations

from .models import PlayerState

BANK_LOAN_MONTHLY_RATE = 0.10   # P.4：每借 $1,000 月息 $100


def dividend_income(p: PlayerState) -> int:
    return sum(s.shares * s.dividend_per_share for s in p.stocks)


def passive_income(p: PlayerState) -> int:
    """非工资收入 = 利息 + 股利 + Σ房地产现金流 + Σ企业现金流"""
    return (
        p.interest_income
        + dividend_income(p)
        + sum(r.cashflow for r in p.real_estates)
        + sum(b.cashflow for b in p.businesses)
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
        "dividendIncome": dividend_income(p),
        "passiveIncome": passive_income(p),
        "totalIncome": total_income(p),
        "childExpense": child_expense(p),
        "bankLoanExpense": bank_loan_expense(p),
        "cardMonthlyExpenses": card_monthly_expenses(p),
        "totalExpenses": total_expenses(p),
        "monthlyCashflow": monthly_cashflow(p),
        "canEnterFasttrack": can_enter_fasttrack(p),
    }
