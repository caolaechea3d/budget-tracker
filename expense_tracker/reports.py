"""Summaries built from stored records: breakdowns, comparisons, budgets, charts data, search."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .storage import Budget, Expense, Income, add_months, month_key, month_range

ZERO = Decimal("0")


def in_month(records: list, period: str | None) -> list:
    """Records in a period: a month ('2026-09'), a whole year ('2026'), or everything (None)."""
    return [r for r in records if period is None or month_key(r.date).startswith(period)]


def is_year(period: str | None) -> bool:
    return period is not None and len(period) == 4


def previous_period(period: str) -> str:
    """The month before a month, or the year before a year."""
    return str(int(period) - 1) if is_year(period) else add_months(period, -1)


def by_subcategory(expenses: list[Expense], category: str, currency: str) -> dict[str, Decimal]:
    """Totals per subcategory ('' = no subcategory) for one category, largest first."""
    totals: dict[str, Decimal] = {}
    for e in expenses:
        if e.category.lower() != category.lower():
            continue
        value = e.amount_in(currency)
        if value is not None:
            totals[e.subcategory] = totals.get(e.subcategory, ZERO) + value
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def change_pct(current: Decimal, previous: Decimal) -> Decimal | None:
    """Percentage change from previous to current; None when there's nothing to compare against."""
    if previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("1"))


def format_change(pct: Decimal | None, new: bool = False) -> str:
    if pct is None:
        return "new" if new else ""
    if pct == 0:
        return "= 0%"
    return f"{'▲' if pct > 0 else '▼'} {abs(pct)}%"


def category_totals(expenses: list[Expense], month: str | None, currency: str) -> dict[str, Decimal]:
    """Totals per category for a month (or all time when month is None)."""
    totals: dict[str, Decimal] = {}
    for e in in_month(expenses, month):
        value = e.amount_in(currency)
        if value is not None:
            totals[e.category] = totals.get(e.category, ZERO) + value
    return totals


def compare_with_previous_month(
    expenses: list[Expense], month: str, currency: str
) -> dict[str, tuple[Decimal, Decimal]]:
    """{category: (this period, previous period)} for every category with spending in either.

    Works for a month (vs the month before) or a year (vs the year before).
    """
    now = category_totals(expenses, month, currency)
    before = category_totals(expenses, previous_period(month), currency)
    return {cat: (now.get(cat, ZERO), before.get(cat, ZERO)) for cat in set(now) | set(before)}


def monthly_totals(records: list, months: list[str], currency: str) -> dict[str, Decimal]:
    totals = {m: ZERO for m in months}
    for r in records:
        key = month_key(r.date)
        if key in totals:
            value = r.amount_in(currency)
            if value is not None:
                totals[key] += value
    return totals


def last_n_months(end_month: str, n: int = 12) -> list[str]:
    return month_range(add_months(end_month, -(n - 1)), end_month)


@dataclass
class BudgetStatus:
    budget: Budget
    spent: Decimal
    missing_rate: int  # expenses that couldn't be converted into the budget's currency

    @property
    def ratio(self) -> Decimal:
        return self.spent / self.budget.amount

    @property
    def remaining(self) -> Decimal:
        return self.budget.amount - self.spent

    @property
    def level(self) -> str:
        """'ok' below 80%, 'warning' from 80% up to 100%, 'over' above the budget."""
        if self.spent > self.budget.amount:
            return "over"
        return "warning" if self.ratio >= Decimal("0.8") else "ok"


def budget_statuses(expenses: list[Expense], budgets: dict[str, Budget], month: str) -> list[BudgetStatus]:
    """Spending vs budget for each budgeted category in `month`, fullest first."""
    statuses = []
    month_expenses = in_month(expenses, month)
    for budget in budgets.values():
        spent, missing = ZERO, 0
        for e in month_expenses:
            if e.category.lower() == budget.category.lower():
                value = e.amount_in(budget.currency)
                if value is None:
                    missing += 1
                else:
                    spent += value
        statuses.append(BudgetStatus(budget, spent, missing))
    return sorted(statuses, key=lambda s: s.ratio, reverse=True)


def balance(expenses: list[Expense], incomes: list[Income], month: str | None, currency: str) -> tuple[Decimal, Decimal, Decimal]:
    """(income, expenses, income - expenses) for a month (or everything when month is None)."""
    def total(records: list) -> Decimal:
        values = (r.amount_in(currency) for r in in_month(records, month))
        return sum((v for v in values if v is not None), ZERO)

    earned, spent = total(incomes), total(expenses)
    return earned, spent, earned - spent


def matches(expense: Expense, query: str) -> bool:
    """Case-insensitive search over description, category, subcategory, payment method and tags.

    Every word must match somewhere; '#tag' only matches tags.
    """
    haystack = " ".join([
        expense.description, expense.category, expense.subcategory, expense.payment_method,
    ]).lower()
    for word in query.lower().split():
        if word.startswith("#"):
            if not any(word[1:] in tag for tag in expense.tags):
                return False
        elif word not in haystack and not any(word in tag for tag in expense.tags):
            return False
    return True
