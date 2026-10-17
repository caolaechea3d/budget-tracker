"""Summaries built from stored records: breakdowns, comparisons, budgets, charts data, search."""

from __future__ import annotations

from dataclasses import dataclass, field
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


OTHER = ""  # BudgetStatus.subcategory for the rest of a category, outside its subcategory budgets


@dataclass
class BudgetStatus:
    """Spending vs budget in one month, for a whole category or one part of it."""

    budget: Budget  # the category's budget
    spent: Decimal
    missing_rate: int  # expenses that couldn't be converted into the budget's currency
    month: str = ""
    subcategory: str | None = None  # None: the whole category; a name: that subcategory; OTHER: the rest
    limit: Decimal = ZERO  # the budget for this month
    usual: Decimal = ZERO  # the budget in a normal month (for "usually …" notes)
    is_exception: bool = False  # this month has a different amount than usual
    parts: list[BudgetStatus] = field(default_factory=list)  # a category's subcategory rows (+ the rest)

    @property
    def category(self) -> str:
        return self.budget.category

    @property
    def currency(self) -> str:
        return self.budget.currency

    @property
    def label(self) -> str:
        if self.subcategory is None:
            return self.category
        return f"Other {self.category}" if self.subcategory == OTHER else self.subcategory

    @property
    def ratio(self) -> Decimal | None:
        """Share of the budget spent; None when the budget is 0."""
        return None if self.limit == 0 else self.spent / self.limit

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.spent

    @property
    def level(self) -> str:
        """'ok' below 80%, 'warning' from 80% up to 100%, 'over' above the budget."""
        if self.spent > self.limit:
            return "over"
        if self.ratio is None:
            return "ok"  # a 0 budget with nothing spent
        return "warning" if self.ratio >= Decimal("0.8") else "ok"

    @property
    def fill(self) -> float:
        """How full the progress bar is (0..1+): over a 0 budget counts as full."""
        if self.ratio is None:
            return 1.0 if self.spent > 0 else 0.0
        return float(self.ratio)


def budget_statuses(expenses: list[Expense], budgets: dict[str, Budget], month: str) -> list[BudgetStatus]:
    """Spending vs budget for each budgeted category in `month`, fullest first.

    A category with subcategory budgets gets `parts`: one per subcategory budget, plus "Other
    <category>" for the rest of its spending (when it has spending or a budget of its own).
    """
    statuses = []
    month_expenses = in_month(expenses, month)
    for budget in budgets.values():
        total, missing = ZERO, 0
        by_subcategory: dict[str, Decimal] = {}
        for e in month_expenses:
            if e.category.lower() != budget.category.lower():
                continue
            value = e.amount_in(budget.currency)
            if value is None:
                missing += 1
                continue
            total += value
            by_subcategory[e.subcategory.lower()] = by_subcategory.get(e.subcategory.lower(), ZERO) + value
        parts = []
        if budget.subcategories:
            covered = ZERO
            for name, sub in budget.subcategories.items():
                spent = by_subcategory.get(name.lower(), ZERO)
                covered += spent
                parts.append(BudgetStatus(budget, spent, 0, month, name, sub.amount_for(month), sub.amount,
                                          month in sub.months))
            rest = total - covered
            if rest > 0 or budget.amount > 0 or budget.amount_for(month) > 0:
                parts.append(BudgetStatus(budget, rest, 0, month, OTHER, budget.amount_for(month), budget.amount,
                                          month in budget.months))
        is_exception = month in budget.months or any(month in s.months for s in budget.subcategories.values())
        statuses.append(BudgetStatus(budget, total, missing, month, None, budget.total_for(month),
                                     budget.usual_total, is_exception, parts))

    def fullness(s: BudgetStatus) -> Decimal:
        if s.ratio is not None:
            return s.ratio
        return Decimal(1000) if s.spent > 0 else Decimal(-1)  # over a 0 budget: top; nothing planned: bottom

    return sorted(statuses, key=fullness, reverse=True)


def suggest_budget_category(
    categories: list[str], expenses: list[Expense], budgets: dict[str, Budget], month: str
) -> tuple[str, bool]:
    """The category to preselect when setting a new budget, and whether it was chosen by spending.

    Prefers the category with the most spending in `month` that has no budget yet, then the first
    category (in catalog order) without a budget, then simply the first category.
    """
    budgeted = {name.lower() for name in budgets}
    spending = category_totals(expenses, month, "PEN")
    by_spending = sorted((c for c in spending if c.lower() not in budgeted), key=lambda c: spending[c], reverse=True)
    if by_spending:
        return by_spending[0], True
    unbudgeted = [c for c in categories if c.lower() not in budgeted]
    if unbudgeted:
        return unbudgeted[0], False
    return (categories[0] if categories else ""), False


def balance(expenses: list[Expense], incomes: list[Income], month: str | None, currency: str) -> tuple[Decimal, Decimal, Decimal]:
    """(income, expenses, income - expenses) for a month (or everything when month is None)."""
    def total(records: list) -> Decimal:
        values = (r.amount_in(currency) for r in in_month(records, month))
        return sum((v for v in values if v is not None), ZERO)

    earned, spent = total(incomes), total(expenses)
    return earned, spent, earned - spent


def recent_tags(expenses: list[Expense]) -> list[str]:
    """Every tag in use, most recently used first (by expense date; ties in A→Z order)."""
    last_used: dict[str, object] = {}
    for e in expenses:
        for tag in e.tags:
            if tag not in last_used or e.date > last_used[tag]:
                last_used[tag] = e.date
    return sorted(last_used, key=lambda t: (-last_used[t].toordinal(), t))


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
