"""Daily expenses table: for each day, the expenses of every category side by side, with sums.

`build_daily_table` only calculates; the Reports tab draws it and exporter.py writes it to Excel.
In the table, an expense's "item" is its subcategory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .reports import ZERO, in_month
from .storage import Expense, format_money, total_in

# Colors shared by the tab and the Excel file
DAY_FILL = "#fff176"  # the date cells and each day's sums row
TOTAL_FILL = "#ffe082"  # the totals row at the end


def header_color(color: str, strength: float = 0.4) -> str:
    """A category's color, lightened for the header cell behind its name."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(255 - (255 - v) * strength):02x}" for v in (r, g, b))


@dataclass
class Day:
    day: date
    items: dict[str, list[Expense]]  # category -> that day's expenses in it, in the order they were entered
    sums: dict[str, Decimal]  # category -> that day's total in it
    total: Decimal

    @property
    def rows(self) -> int:
        """Item rows the day needs: as many as its busiest category."""
        return max((len(items) for items in self.items.values()), default=0)


@dataclass
class DailyTable:
    currency: str
    categories: list[str]  # the column groups: categories with expenses, in the user's category order
    days: list[Day]  # days with expenses, oldest first
    sums: dict[str, Decimal]  # category -> total over all the days
    total: Decimal
    count: int  # expenses in the table
    missing_rate: int  # expenses that couldn't be converted into `currency` (not in the sums)


def build_daily_table(
    expenses: list[Expense], period: str | None, currency: str, category_order: list[str],
) -> DailyTable:
    """The table for a month ('2026-10'), a year ('2026') or everything (None), amounts in `currency`."""
    chosen = in_month(expenses, period)
    names: dict[str, str] = {}  # one spelling per category, whatever the case it was typed in
    for e in chosen:
        names.setdefault(e.category.lower(), e.category)
    order = {name.lower(): i for i, name in enumerate(category_order)}
    categories = sorted(names.values(), key=lambda c: (order.get(c.lower(), len(order)), c.lower()))

    by_day: dict[date, dict[str, list[Expense]]] = {}
    for e in chosen:
        by_day.setdefault(e.date, {}).setdefault(names[e.category.lower()], []).append(e)
    days = []
    for day in sorted(by_day):
        items = by_day[day]
        sums = {cat: total_in(spent, currency)[0] for cat, spent in items.items()}
        days.append(Day(day, items, sums, sum(sums.values(), ZERO)))
    total, missing = total_in(chosen, currency)
    return DailyTable(
        currency=currency, categories=categories, days=days,
        sums={cat: sum((d.sums.get(cat, ZERO) for d in days), ZERO) for cat in categories},
        total=total, count=len(chosen), missing_rate=missing,
    )


def amount_text(expense: Expense, currency: str) -> str:
    """The expense in `currency`, or in its own currency when there's no exchange rate to convert it."""
    value = expense.amount_in(currency)
    if value is None:
        return f"{format_money(expense.amount, expense.currency)} (no rate)"
    return format_money(value, currency)
