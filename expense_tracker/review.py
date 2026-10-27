"""Month in review: how a month went, what changed, and where the current month is heading.

`build_month_review` only calculates; the Reports tab and the HTML page (review_html.py) show it.
"Usual" means the average of up to HISTORY_MONTHS months before the reviewed one, counting only
months since the first record (so a new user isn't compared with empty months).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from operator import attrgetter
from statistics import median

from .debts import OWE, OWED, Debt
from .reports import ZERO, BudgetStatus, budget_statuses, category_totals, change_pct, in_month, monthly_totals
from .storage import (
    CENT,
    Budget,
    Expense,
    Income,
    RecurringExpense,
    add_months,
    convert,
    day_in_month,
    format_money,
    month_key,
    month_range,
    total_in,
)

HISTORY_MONTHS = 6
BIGGEST = 5  # largest expenses listed
CHANGE_PCT = 25  # a category this much above/below usual is worth a mention…
NOTABLE_SHARE = Decimal("0.03")  # …if the difference is also at least 3% of a usual month's spending
UNUSUAL_TIMES = 3  # an expense this many times its category's typical expense is "unusually large"
FORECAST_FROM_DAY = 7  # before this, a month is too young to project
BIG_SHARE = Decimal("0.10")  # an expense of 10% of a usual month or more counts once in the forecast
UPCOMING_DAYS = 31  # debt payments listed when due within this many days
# (icon, color) for each kind of insight, in the tab and on the HTML page
INSIGHT_LOOKS = {"duplicate": ("⚠️", "#e63946"), "unusual": ("🔎", "#f4a261"), "up": ("📈", "#e76f51"),
                 "new": ("✨", "#577590"), "down": ("📉", "#43aa8b")}


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _day(d: date) -> str:
    return f"{d.day} {d:%b}"


@dataclass
class Totals:
    income: Decimal = ZERO
    expenses: Decimal = ZERO

    @property
    def saved(self) -> Decimal:
        return self.income - self.expenses

    @property
    def savings_rate(self) -> Decimal | None:
        """Share of the income not spent, in % (negative when spending more than earned)."""
        if self.income <= 0:
            return None
        return (self.saved / self.income * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass
class CategoryLine:
    category: str
    amount: Decimal
    share: Decimal  # % of the month's spending
    previous: Decimal  # the month before
    usual: Decimal | None  # None without history

    @property
    def change(self) -> Decimal | None:
        """% above (+) or below (-) a usual month; None when there's nothing to compare with."""
        return None if self.usual is None else change_pct(self.amount, self.usual)


@dataclass
class Insight:
    kind: str  # "duplicate", "unusual", "up", "new" or "down"
    text: str
    category: str = ""


@dataclass
class Bill:
    """A recurring expense that hasn't been added this month yet."""

    name: str
    category: str
    date: date
    amount: Decimal | None  # in the review's currency; None without an exchange rate


@dataclass
class Forecast:
    day: int  # today's day of the month
    days: int  # days in the month
    spent: Decimal  # so far
    pace: Decimal  # everyday spending per day so far (bills and one-off large expenses aside)
    projected: Decimal | None  # about where the month ends; None while it's too early to tell
    bills: list[Bill]

    @property
    def bills_total(self) -> Decimal:
        return sum((b.amount for b in self.bills if b.amount is not None), ZERO)


@dataclass
class DebtMove:
    debt: Debt
    date: date
    amount: Decimal | None  # in the review's currency


@dataclass
class DebtsReview:
    paid: list[DebtMove]  # payments made on debts I owe
    received: list[DebtMove]  # payments received on debts owed to me
    i_owe: Decimal  # still owed at the end of the month (today, for the current month)
    owed_to_me: Decimal
    upcoming: list[DebtMove]  # current month only: the next payment of each debt due soon (or overdue)

    @property
    def is_empty(self) -> bool:
        return not (self.paid or self.received or self.i_owe or self.owed_to_me or self.upcoming)


@dataclass
class MonthReview:
    month: str
    currency: str
    today: date
    totals: Totals
    count: int  # expenses in the month
    previous: Totals | None  # the month before; None before the first records
    usual: Totals | None  # average of the history months; None without history
    history: int  # how many months `usual` averages
    trend: dict[str, Totals]  # the history months and this one, oldest first
    categories: list[CategoryLine]  # largest first
    biggest: list[Expense]
    budgets: list[BudgetStatus]
    debts: DebtsReview
    insights: list[Insight]
    forecast: Forecast | None  # current month only
    missing_rate: int  # expenses and income that couldn't be converted into `currency`

    @property
    def days(self) -> int:
        year, mon = map(int, self.month.split("-"))
        return calendar.monthrange(year, mon)[1]

    @property
    def is_current(self) -> bool:
        return self.month == month_key(self.today)

    @property
    def is_future(self) -> bool:
        return self.month > month_key(self.today)


def build_month_review(
    month: str,
    currency: str,
    expenses: list[Expense],
    incomes: list[Income],
    budgets: dict[str, Budget],
    debts: list[Debt],
    recurring: list[RecurringExpense],
    rate: Decimal | None = None,
    today: date | None = None,
) -> MonthReview:
    """Everything the month-in-review report shows for `month` ('2026-10'), in `currency`.

    `rate` (PEN per USD, e.g. the last rate used) converts recurring bills in the other currency.
    """
    today = today or date.today()
    month_expenses, month_incomes = in_month(expenses, month), in_month(incomes, month)
    spent, missing_spent = total_in(month_expenses, currency)
    earned, missing_earned = total_in(month_incomes, currency)

    first = min((month_key(r.date) for r in [*expenses, *incomes]), default=month)
    history = [m for m in month_range(add_months(month, -HISTORY_MONTHS), add_months(month, -1)) if m >= first]
    spent_by_month = monthly_totals(expenses, [*history, month], currency)
    earned_by_month = monthly_totals(incomes, [*history, month], currency)
    trend = {m: Totals(earned_by_month[m], spent_by_month[m]) for m in [*history, month]}
    usual = None
    if history:
        usual = Totals(_cents(sum((trend[m].income for m in history), ZERO) / len(history)),
                       _cents(sum((trend[m].expenses for m in history), ZERO) / len(history)))

    now = category_totals(expenses, month, currency)
    before = category_totals(expenses, add_months(month, -1), currency)
    past = [category_totals(expenses, m, currency) for m in history]
    usual_by_category = {cat: _cents(sum((p.get(cat, ZERO) for p in past), ZERO) / len(history))
                         for cat in {c for p in past for c in p}} if history else {}
    categories = [
        CategoryLine(cat, value, (value / spent * 100).quantize(Decimal("0.1")) if spent else ZERO,
                     before.get(cat, ZERO), usual_by_category.get(cat, ZERO) if history else None)
        for cat, value in sorted(now.items(), key=lambda kv: kv[1], reverse=True)
    ]

    valued = [(e.amount_in(currency), e) for e in month_expenses]
    biggest = [e for v, e in sorted((x for x in valued if x[0] is not None), key=lambda x: x[0], reverse=True)]

    threshold = max(Decimal("1"), _cents((usual.expenses if usual else spent) * NOTABLE_SHARE))
    history_expenses = [e for e in expenses if month_key(e.date) in history]
    unusual = _unusual(month_expenses, history_expenses, currency, threshold)
    is_current = month == month_key(today)
    insights = [
        *_duplicates(month_expenses),
        *(Insight("unusual", f"Unusually large: “{e.description or e.category}”, {format_money(value, currency)} "
                             f"in {e.category} (usually about {format_money(typical, currency)})", e.category)
          for e, value, typical in unusual[:3]),
        *_category_changes(now, usual_by_category, len(history), threshold, currency, complete=not is_current),
    ]
    forecast = None
    if is_current:
        one_offs = [e for e, _, _ in unusual]
        if usual:  # big expenses (rent, a new phone…) happen once, not every day
            big = usual.expenses * BIG_SHARE
            one_offs += [e for v, e in valued if v is not None and v >= big]
        forecast = _forecast(month_expenses, one_offs, recurring, month, currency, rate, today, spent)

    return MonthReview(
        month=month, currency=currency, today=today, totals=Totals(earned, spent), count=len(month_expenses),
        previous=trend.get(add_months(month, -1)), usual=usual, history=len(history), trend=trend,
        categories=categories, biggest=biggest[:BIGGEST], budgets=budget_statuses(expenses, budgets, month),
        debts=_debts_review(debts, month, currency, today), insights=insights, forecast=forecast,
        missing_rate=missing_spent + missing_earned,
    )


def _duplicates(month_expenses: list[Expense]) -> list[Insight]:
    """Expenses with the same date, amount and category: often entered twice by mistake."""
    groups: dict[tuple, list[Expense]] = {}
    for e in month_expenses:
        groups.setdefault((e.date, e.currency, e.amount, e.category.lower()), []).append(e)
    found = []
    for (when, currency, amount, _), same in sorted(groups.items(), key=lambda kv: kv[0][0]):
        if len(same) > 1:
            name = same[0].description or same[0].category
            found.append(Insight("duplicate", f"Possible duplicate: {len(same)} × {format_money(amount, currency)} "
                                              f"“{name}” on {_day(when)}", same[0].category))
    return found


def _unusual(
    month_expenses: list[Expense], history_expenses: list[Expense], currency: str, threshold: Decimal,
) -> list[tuple[Expense, Decimal, Decimal]]:
    """(expense, value, typical) for expenses far above what they usually cost, most unusual first.

    "Usually" is the median of earlier expenses in the same subcategory (a full tank vs earlier full
    tanks, not vs taxi rides), or in the same category for a subcategory with no history yet.
    """
    past: dict[tuple[str, str], list[Decimal]] = {}
    for e in history_expenses:
        value = e.amount_in(currency)
        if value is not None:
            past.setdefault((e.category.lower(), e.subcategory.lower()), []).append(value)
            if e.subcategory:
                past.setdefault((e.category.lower(), ""), []).append(value)
    found = []
    for e in month_expenses:
        value = e.amount_in(currency)
        values = past.get((e.category.lower(), e.subcategory.lower()), [])
        if not (e.subcategory and values):  # a new subcategory: compare with its category
            values = past.get((e.category.lower(), ""), [])
        if value is None or len(values) < 3:  # too little history to know what's normal
            continue
        typical = _cents(median(values))
        if value >= typical * UNUSUAL_TIMES and value - typical >= threshold:
            found.append((e, value, typical))
    return sorted(found, key=lambda f: f[1] / f[2], reverse=True)


def _category_changes(
    now: dict[str, Decimal], usual: dict[str, Decimal], history: int, threshold: Decimal, currency: str,
    complete: bool,
) -> list[Insight]:
    """Categories well above (or, for a finished month, below) a usual month, and new ones."""
    if not history:
        return []

    def money(value: Decimal) -> str:
        return format_money(value, currency)

    ups, news, downs = [], [], []
    for cat in set(now) | set(usual):
        amount, avg = now.get(cat, ZERO), usual.get(cat, ZERO)
        if avg == 0:
            if amount >= threshold and history >= 2:
                news.append((amount, Insight("new", f"{cat}: {money(amount)}, nothing in the previous {history} months",
                                             cat)))
            continue
        pct, diff = change_pct(amount, avg), amount - avg
        if pct >= CHANGE_PCT and diff >= threshold:
            if pct >= 200:  # "3118% more" says less than the two amounts
                text = f"{cat}: {'already ' if not complete else ''}{money(amount)}, usually {money(avg)} a month"
            elif complete:
                text = f"{cat}: {money(amount)}, {pct}% more than usual ({money(avg)} a month)"
            else:
                text = f"{cat}: already {money(amount)}, {pct}% more than a usual month ({money(avg)})"
            ups.append((diff, Insight("up", text, cat)))
        elif complete and pct <= -CHANGE_PCT and -diff >= threshold:
            text = (f"{cat}: nothing this month (usually {money(avg)})" if amount == 0
                    else f"{cat}: {money(amount)}, {abs(pct)}% less than usual ({money(avg)} a month)")
            downs.append((-diff, Insight("down", text, cat)))

    def biggest(found: list, n: int) -> list[Insight]:
        return [insight for _, insight in sorted(found, key=lambda f: f[0], reverse=True)[:n]]

    return [*biggest(ups, 3), *biggest(news, 2), *biggest(downs, 2)]


def _forecast(
    month_expenses: list[Expense], one_offs: list[Expense], recurring: list[RecurringExpense], month: str,
    currency: str, rate: Decimal | None, today: date, spent: Decimal,
) -> Forecast:
    """Spent so far, plus everyday spending at this month's pace, plus recurring bills still to come.

    Bills already added (from recurring expenses) and `one_offs` (big or unusual expenses) count
    once, not towards the daily pace.
    """
    year, mon = map(int, month.split("-"))
    days = calendar.monthrange(year, mon)[1]
    excluded = {id(e) for e in one_offs}
    everyday = [e for e in month_expenses if not e.recurring_id and id(e) not in excluded]
    pace = _cents(total_in(everyday, currency)[0] / today.day)
    bills = sorted(
        (Bill(r.description or r.subcategory or r.category, r.category, r.occurrence_date(month),
              convert(r.amount, r.currency, rate, currency))
         for r in recurring
         if r.active and r.start_month <= month and (r.handled_through is None or r.handled_through < month)),
        key=lambda b: b.date,
    )
    forecast = Forecast(today.day, days, spent, pace, None, bills)
    if today.day >= FORECAST_FROM_DAY:
        forecast.projected = spent + pace * (days - today.day) + forecast.bills_total
    return forecast


def _debts_review(debts: list[Debt], month: str, currency: str, today: date) -> DebtsReview:
    is_current = month == month_key(today)
    end = today if is_current else day_in_month(month, 31)
    paid, received = [], []
    left = {OWE: ZERO, OWED: ZERO}
    for debt in debts:
        for p in debt.payments:
            if month_key(p.date) == month:
                (paid if debt.direction == OWE else received).append(
                    DebtMove(debt, p.date, debt.amount_in(currency, p.amount)))
        # A debt marked as settled has no settle date: it counts as closed once its last payment is in.
        if debt.start_date > end or (debt.settled and all(p.date <= end for p in debt.payments)):
            continue
        paid_by_end = sum((p.amount for p in debt.payments if p.date <= end), ZERO)
        value = debt.amount_in(currency, max(ZERO, debt.amount - paid_by_end))
        if value is not None:
            left[debt.direction] += value
    upcoming = []
    if is_current:
        for debt in debts:
            due = debt.next_due()
            if due and (due[0] - today).days <= UPCOMING_DAYS:
                upcoming.append(DebtMove(debt, due[0], debt.amount_in(currency, due[1])))
    by_date = attrgetter("date")
    return DebtsReview(sorted(paid, key=by_date), sorted(received, key=by_date), left[OWE], left[OWED],
                       sorted(upcoming, key=by_date))


# ---------- wording shared by the Reports tab and the HTML page ----------

def month_name(month: str) -> str:
    """'2026-09' -> 'September'."""
    return calendar.month_name[int(month[5:])]


def short_month(month: str) -> str:
    """'2026-09' -> 'Sep 2026'."""
    return f"{calendar.month_abbr[int(month[5:])]} {month[:4]}"


def period_note(review: MonthReview) -> str:
    if review.is_future:
        return "This month hasn't started yet"
    if review.is_current:
        return f"Month so far: day {review.today.day} of {review.days}"
    return ""


def usual_note(review: MonthReview) -> str:
    """What "usual" means in this review."""
    if not review.history:
        return "No earlier months to compare with yet."
    months = list(review.trend)[:-1]
    span = short_month(months[0]) if len(months) == 1 else f"{short_month(months[0])} – {short_month(months[-1])}"
    count = "month" if review.history == 1 else f"{review.history} months"
    return f"“Usual” is the average of the previous {count} ({span})."


def comparisons(review: MonthReview, key: str) -> list[tuple[str, str]]:
    """Lines under a summary card ('income', 'expenses' or 'saved'): (text, tone), tone 'good', 'bad' or ''.

    Empty for a month that isn't over: comparing half a month with whole months says nothing.
    """
    if review.is_current or review.is_future:
        return []
    lines = []
    for label, other in ((month_name(add_months(review.month, -1)), review.previous), ("usual", review.usual)):
        if other is None:
            continue
        now, then = getattr(review.totals, key), getattr(other, key)
        if key == "saved":  # a % change of savings is meaningless around zero; say the difference
            diff = now - then
            if diff == 0:
                lines.append((f"same as {label}", ""))
            else:
                more = "more" if diff > 0 else "less"
                lines.append((f"{format_money(abs(diff), review.currency)} {more} than {label}",
                              "good" if diff > 0 else "bad"))
            continue
        pct = change_pct(now, then)
        if pct is None:
            continue
        if pct == 0:
            lines.append((f"same as {label}", ""))
        else:
            up_is_good = key == "income"
            lines.append((f"{'▲' if pct > 0 else '▼'} {abs(pct)}% vs {label}", "good" if (pct > 0) == up_is_good else "bad"))
    return lines


def savings_note(review: MonthReview) -> str:
    rate = review.totals.savings_rate
    if rate is None:
        return "No income this month" if not review.is_current else "No income so far"
    return f"{rate}% of income" if rate >= 0 else f"{-rate}% more than the income"


def forecast_headline(review: MonthReview) -> str:
    f = review.forecast
    if f is None:
        return ""
    if f.projected is None:
        return f"Too early in the month for a forecast: check back from day {FORECAST_FROM_DAY}."
    money = format_money(f.projected, review.currency)
    text = f"At this pace, {month_name(review.month)} ends at about {money} of spending"
    if review.usual and review.usual.expenses:
        usual, diff = review.usual.expenses, f.projected - review.usual.expenses
        if abs(diff) <= usual * Decimal("0.05"):
            return f"{text}, about the same as usual ({format_money(usual, review.currency)})."
        more = "more" if diff > 0 else "less"
        return f"{text}: {format_money(abs(diff), review.currency)} {more} than usual ({format_money(usual, review.currency)})."
    return f"{text}."


def forecast_details(review: MonthReview) -> list[str]:
    f = review.forecast
    if f is None:
        return []

    def money(value: Decimal) -> str:
        return format_money(value, review.currency)

    lines = [f"{money(f.spent)} spent so far, in {f.day} of {f.days} days.",
             f"Everyday spending: about {money(f.pace)} a day (bills and big one-off expenses count once)."]
    if f.bills:
        bills = ", ".join(f"{b.name} ({money(b.amount) if b.amount is not None else 'no exchange rate'}, {_day(b.date)})"
                          for b in f.bills)
        lines.append(f"Recurring bills still to add: {bills}.")
    if f.projected is not None and review.totals.income > 0:
        left = review.totals.income - f.projected
        income = money(review.totals.income)
        lines.append(f"With {income} of income so far, that leaves about {money(left)}." if left >= 0
                     else f"That's {money(-left)} more than the {income} of income so far.")
    return lines


def budgets_note(review: MonthReview) -> str:
    if not review.budgets:
        return "No budgets set yet (see the Budgets tab)."
    kept = sum(s.level != "over" for s in review.budgets)
    total = len(review.budgets)
    return (f"{kept} of {total} budget{'s' * (total != 1)} "
            f"{'on track so far' if review.is_current else 'kept'}")


def change_label(line: CategoryLine) -> str:
    """A category vs a usual month: '▲ 6%', '▼ 24%', '=', 'new', or '▲ ×32' for a jump too big for a %."""
    if line.usual is None:
        return ""
    change = line.change
    if change is None:
        return "new"
    if change == 0:
        return "="
    if change >= 200:
        return f"▲ ×{line.amount / line.usual:.0f}"
    return f"{'▲' if change > 0 else '▼'} {abs(change)}%"


def change_tone(line: CategoryLine) -> str:
    """'bad' for spending clearly above usual, 'good' for clearly below, '' otherwise."""
    if line.change is None:
        return ""
    return "bad" if line.change >= 10 else "good" if line.change <= -10 else ""
