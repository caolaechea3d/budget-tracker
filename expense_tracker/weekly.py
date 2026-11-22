"""Weekly spending: totals per week (Monday to Sunday), by category, compared with each other.

`build_weekly` only calculates; the Reports tab shows it. Weeks before the first expense aren't
included, so a new user's average isn't pulled down by empty weeks. The current week counts as
"so far" and is left out of the average.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .reports import ZERO, change_pct, format_change
from .storage import CENT, Expense


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def week_label(start: date, with_year: bool = False) -> str:
    """'16–22 Nov', '26 Oct – 1 Nov', or with the year: '16–22 Nov 2026'."""
    end = start + timedelta(days=6)
    year = f" {end.year}" if with_year else ""
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%b}{year}"
    return f"{start.day} {start:%b} – {end.day} {end:%b}{year}"


def change_text(pct: Decimal | None) -> str:
    """'▲ 12%', '▼ 5%', '= 0%', '' — or '▲ ×17' for a jump too big for a % to say much."""
    if pct is not None and pct >= 200:
        return f"▲ ×{1 + pct / 100:.0f}"
    return format_change(pct)


@dataclass
class Week:
    start: date  # a Monday
    total: Decimal
    count: int  # expenses in the week
    by_category: dict[str, Decimal]
    days: int = 7  # 7, or the days so far for the current week
    current: bool = False  # the week of today: still going, even on its Sunday

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)

    @property
    def is_partial(self) -> bool:
        return self.current

    @property
    def per_day(self) -> Decimal:
        return (self.total / self.days).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class WeeklyTable:
    currency: str
    weeks: list[Week]  # oldest first; the last one may be the current week, so far
    categories: list[str]  # the categories with spending in these weeks, in the user's order
    average: Decimal | None  # of the finished weeks; None when there are none
    missing_rate: int  # expenses that couldn't be converted into `currency` (not counted)

    @property
    def finished(self) -> list[Week]:
        return [w for w in self.weeks if not w.is_partial]

    @property
    def highest(self) -> Week | None:
        return max(self.finished, key=lambda w: w.total, default=None)

    @property
    def lowest(self) -> Week | None:
        return min(self.finished, key=lambda w: w.total, default=None)

    def previous(self, week: Week) -> Week | None:
        i = self.weeks.index(week)
        return self.weeks[i - 1] if i > 0 else None

    def change_vs_previous(self, week: Week) -> Decimal | None:
        """% change from the week before; None for the first week, after an empty week, or so far."""
        before = self.previous(week)
        return None if before is None or week.is_partial else change_pct(week.total, before.total)

    def change_vs_average(self, week: Week) -> Decimal | None:
        if self.average is None or week.is_partial:
            return None
        return change_pct(week.total, self.average)


def build_weekly(
    expenses: list[Expense], end: date, count: int, currency: str, category_order: list[str],
    today: date | None = None,
) -> WeeklyTable:
    """The last `count` weeks up to the week of `end`, amounts in `currency`."""
    today = today or date.today()
    last = week_start(end)
    first = last - timedelta(weeks=count - 1)
    first = max(first, week_start(min(e.date for e in expenses))) if expenses else last + timedelta(weeks=1)
    starts = []
    while first <= last:
        starts.append(first)
        first += timedelta(weeks=1)

    names: dict[str, str] = {}  # one spelling per category
    weeks = {start: Week(start, ZERO, 0, {}) for start in starts}
    missing = 0
    for e in expenses:
        week = weeks.get(week_start(e.date))
        if week is None:
            continue
        value = e.amount_in(currency)
        if value is None:
            missing += 1
            continue
        name = names.setdefault(e.category.lower(), e.category)
        week.total += value
        week.count += 1
        week.by_category[name] = week.by_category.get(name, ZERO) + value
    current = weeks.get(week_start(today))
    if current is not None:
        current.days, current.current = (today - current.start).days + 1, True

    order = {name.lower(): i for i, name in enumerate(category_order)}
    categories = sorted(names.values(), key=lambda c: (order.get(c.lower(), len(order)), c.lower()))
    ordered = [weeks[s] for s in starts]
    finished = [w for w in ordered if not w.is_partial]
    average = (sum((w.total for w in finished), ZERO) / len(finished)).quantize(CENT, rounding=ROUND_HALF_UP) \
        if finished else None
    return WeeklyTable(currency, ordered, categories, average, missing)
