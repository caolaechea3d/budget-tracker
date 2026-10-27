"""The month in review as one self-contained HTML page: opens in any browser and prints on A4."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path

from . import APP_NAME, __version__
from .catalog import Category, category_look
from .debts import DIRECTION_LABELS
from .reports import OTHER, BudgetStatus, budget_text
from .review import (
    INSIGHT_LOOKS,
    MonthReview,
    budgets_note,
    change_label,
    change_tone,
    comparisons,
    forecast_details,
    forecast_headline,
    month_name,
    period_note,
    savings_note,
    usual_note,
)
from .storage import format_money

# The app's colors (gui/tabs/base.py)
INCOME_COLOR, EXPENSE_COLOR = "#43aa8b", "#e76f51"
LEVEL_COLORS = {"ok": "#43aa8b", "warning": "#f4a261", "over": "#e63946"}

CSS = """
:root { --text: #1f2937; --muted: #6b7280; --line: #e5e7eb; --page: #f4f5f7; --card: #ffffff;
        --good: #2f855a; --bad: #c0392b; --link: #1d6fb8; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--page); color: var(--text);
       font: 14px/1.5 "Segoe UI", system-ui, -apple-system, "Segoe UI Emoji", sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 32px 20px 40px; }
header { margin-bottom: 18px; }
.eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: 12px; font-weight: 600; color: var(--muted); }
h1 { font-size: 32px; line-height: 1.2; margin: 2px 0 4px; }
h2 { font-size: 16px; margin: 0 0 10px; }
h3 { font-size: 13px; margin: 12px 0 4px; color: var(--muted); font-weight: 600; }
.meta, .muted { color: var(--muted); }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.card, section { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; }
section { margin-top: 14px; }
.card .label { color: var(--muted); font-size: 13px; }
.card .value { font-size: 24px; font-weight: 700; margin: 2px 0; white-space: nowrap; }
.card .note { color: var(--muted); font-size: 13px; }
.good { color: var(--good); }
.bad { color: var(--bad); }
.cmp { font-size: 13px; }
.headline { font-size: 16px; font-weight: 600; margin: 0 0 6px; }
ul.plain { margin: 0; padding-left: 18px; }
ul.insights { list-style: none; margin: 0; padding: 0; }
ul.insights li { padding: 5px 0; border-bottom: 1px solid var(--line); }
ul.insights li:last-child { border-bottom: 0; }
.ico { display: inline-block; width: 26px; }
table { width: 100%; border-collapse: collapse; }
th { font-size: 12px; color: var(--muted); font-weight: 600; text-align: left; padding: 4px 8px;
     border-bottom: 1px solid var(--line); }
td { padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
tr.total td { font-weight: 700; border-top: 2px solid var(--line); }
tr.part td:first-child { padding-left: 32px; }
.dot { display: inline-block; width: 22px; height: 22px; border-radius: 6px; text-align: center; line-height: 22px;
       font-size: 13px; margin-right: 8px; }
.bar { height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; min-width: 80px; }
.bar > span { display: block; height: 100%; border-radius: 4px; }
.legend span { display: inline-block; margin-right: 16px; font-size: 13px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
.trend { width: 100%; height: auto; display: block; margin: 6px 0 8px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0 24px; }
.tag { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 4px; background: #fde2e1; color: var(--bad); }
footer { margin-top: 18px; color: var(--muted); font-size: 12px; }
@media (max-width: 640px) { .cards, .cols { grid-template-columns: 1fr; } h1 { font-size: 26px; } }
@media print {
  body { background: #fff; font-size: 12px; }
  main { max-width: none; padding: 0; }
  .card, section { break-inside: avoid; border-color: #d1d5db; }
}
@page { size: A4; margin: 14mm; }
"""


def save_html(review: MonthReview, path: Path, categories: list[Category], user: str = "") -> None:
    Path(path).write_text(render_html(review, categories, user), encoding="utf-8")


def render_html(review: MonthReview, categories: list[Category], user: str = "") -> str:
    title = f"{month_name(review.month)} {review.month[:4]}"
    meta = " · ".join(filter(None, [user, period_note(review), f"Amounts in {review.currency}"]))
    body = "".join([
        f'<header><div class="eyebrow">Month in review</div><h1>{escape(title)}</h1>'
        f'<div class="meta">{escape(meta)}</div></header>',
        _cards(review),
        _forecast(review),
        _insights(review),
        _categories(review, categories),
        _trend(review),
        _biggest(review, categories),
        _budgets(review, categories),
        _debts(review),
        _footer(review),
    ])
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Month in review — {escape(title)}</title><style>{CSS}</style></head>'
            f'<body><main>{body}</main></body></html>\n')


def _money(review: MonthReview, value: Decimal | None) -> str:
    return escape(format_money(value, review.currency))


def _section(title: str, content: str) -> str:
    return f"<section><h2>{escape(title)}</h2>{content}</section>"


def _dot(categories: list[Category], category: str, subcategory: str = "") -> str:
    icon, color = category_look(categories, category, subcategory)
    return f'<span class="dot" style="background:{escape(color)}33">{escape(icon)}</span>'


def _bar(fill: float, color: str) -> str:
    width = max(0.0, min(fill, 1.0)) * 100
    return f'<div class="bar"><span style="width:{width:.1f}%;background:{escape(color)}"></span></div>'


def _cards(review: MonthReview) -> str:
    so_far = " so far" if review.is_current else ""
    saved = review.totals.saved

    def card(label: str, value: Decimal, tone: str, note: str, key: str) -> str:
        lines = "".join(f'<div class="cmp {line_tone}">{escape(text)}</div>'
                        for text, line_tone in comparisons(review, key))
        return (f'<div class="card"><div class="label">{escape(label)}</div>'
                f'<div class="value {tone}">{_money(review, value)}</div>'
                f'<div class="note">{escape(note)}</div>{lines}</div>')

    count = f"{review.count} expense{'s' * (review.count != 1)}"
    return ('<div class="cards">'
            + card(f"Income{so_far}", review.totals.income, "good", "", "income")
            + card(f"Expenses{so_far}", review.totals.expenses, "bad", count, "expenses")
            + card(f"Saved{so_far}", saved, "good" if saved >= 0 else "bad", savings_note(review), "saved")
            + "</div>")


def _forecast(review: MonthReview) -> str:
    if review.forecast is None:
        return ""
    details = "".join(f"<li>{escape(line)}</li>" for line in forecast_details(review))
    return _section(f"Where {month_name(review.month)} is heading",
                    f'<p class="headline">{escape(forecast_headline(review))}</p><ul class="plain">{details}</ul>')


def _insights(review: MonthReview) -> str:
    if review.insights:
        items = "".join(f'<li><span class="ico">{INSIGHT_LOOKS[i.kind][0]}</span>{escape(i.text)}</li>'
                        for i in review.insights)
        content = f'<ul class="insights">{items}</ul>'
    elif not review.history:
        content = '<p class="muted">Not much to compare with yet: this starts working after a month of records.</p>'
    else:
        content = f'<p class="muted">Nothing unusual{" so far" if review.is_current else ""}: a month like most.</p>'
    return _section("What stood out", content)


def _categories(review: MonthReview, categories: list[Category]) -> str:
    if not review.categories:
        return _section("Spending by category", '<p class="muted">No expenses this month.</p>')
    largest = max(line.amount for line in review.categories) or Decimal(1)
    current = review.is_current
    compare_head = "Usual month" if current else "vs usual"
    rows = []
    for line in review.categories:
        _, color = category_look(categories, line.category)
        if current and line.usual is not None:  # half a month vs a whole one: show what's usual, not a % change
            compare, tone = (_money(review, line.usual) if line.usual else "new"), ""
        else:
            compare, tone = escape(change_label(line)), change_tone(line)
        rows.append(
            f"<tr><td>{_dot(categories, line.category)}{escape(line.category)}</td>"
            f"<td>{_bar(float(line.amount / largest), color)}</td>"
            f'<td class="num">{_money(review, line.amount)}</td><td class="num">{line.share}%</td>'
            f'<td class="num {tone}">{compare}</td></tr>')
    usual_total = ""
    if review.usual:
        usual_total = _money(review, review.usual.expenses) if current else ""
    rows.append(f'<tr class="total"><td>Total</td><td></td><td class="num">{_money(review, review.totals.expenses)}</td>'
                f'<td class="num">100%</td><td class="num">{usual_total}</td></tr>')
    head = (f'<tr><th>Category</th><th style="width:30%"></th><th class="num">Amount</th><th class="num">Share</th>'
            f'<th class="num">{compare_head if review.history else ""}</th></tr>')
    return _section("Spending by category", f"<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>")


def _nice_step(maximum: float, ticks: int = 4) -> float:
    raw = maximum / ticks
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 2.5, 5, 10) if raw <= m * power)


def _trend(review: MonthReview) -> str:
    months = list(review.trend)
    if len(months) < 2:
        return ""
    width, height, left, right, top, bottom = 640, 190, 52, 8, 10, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    maximum = float(max(max(t.income, t.expenses) for t in review.trend.values()))
    step = _nice_step(maximum) if maximum > 0 else 1
    top_value = step * max(1, math.ceil(maximum / step)) if maximum > 0 else 4
    parts = []
    for i in range(int(round(top_value / step)) + 1):
        y = top + plot_h - plot_h * (step * i) / top_value
        label = f"{step * i / 1000:g}k" if step * i >= 1000 else f"{step * i:g}"
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e5e7eb"/>'
                     f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{label}</text>')
    group = plot_w / len(months)
    bar = min(24, group * 0.32)
    for i, month in enumerate(months):
        totals = review.trend[month]
        x = left + i * group
        if month == review.month:
            parts.append(f'<rect x="{x + 2:.1f}" y="{top}" width="{group - 4:.1f}" height="{plot_h}" fill="#f1f3f6"/>')
        for j, (name, value, color) in enumerate((("Income", totals.income, INCOME_COLOR),
                                                  ("Expenses", totals.expenses, EXPENSE_COLOR))):
            h = plot_h * float(value) / top_value
            bx = x + group / 2 - bar + j * bar
            tip = f"{month_name(month)} {month[:4]} · {name}: {format_money(value, review.currency)}"
            parts.append(f'<rect x="{bx + 1:.1f}" y="{top + plot_h - h:.1f}" width="{bar - 2:.1f}" height="{h:.1f}" '
                         f'rx="2" fill="{color}"><title>{escape(tip)}</title></rect>')
        weight = ' font-weight="700"' if month == review.month else ""
        parts.append(f'<text x="{x + group / 2:.1f}" y="{height - 10}" text-anchor="middle" font-size="12" '
                     f'fill="#374151"{weight}>{date(int(month[:4]), int(month[5:]), 1):%b}</text>')
    svg = (f'<svg class="trend" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="Income and expenses per month">{"".join(parts)}</svg>')
    legend = (f'<div class="legend"><span><i style="background:{INCOME_COLOR}"></i>Income</span>'
              f'<span><i style="background:{EXPENSE_COLOR}"></i>Expenses</span></div>')
    head = "".join(f'<th class="num">{date(int(m[:4]), int(m[5:]), 1):%b}</th>' for m in months)
    rows = ""
    for label, key in (("Income", "income"), ("Expenses", "expenses"), ("Saved", "saved")):
        cells = "".join(f'<td class="num">{escape(f"{getattr(review.trend[m], key):,.0f}")}</td>' for m in months)
        rows += f"<tr><td>{label}</td>{cells}</tr>"
    table = f"<table><thead><tr><th></th>{head}</tr></thead><tbody>{rows}</tbody></table>"
    return _section(f"The last {len(months)} months", legend + svg + table)


def _biggest(review: MonthReview, categories: list[Category]) -> str:
    if not review.biggest:
        return ""
    rows = "".join(
        f'<tr><td class="num">{e.date.day} {e.date:%b}</td>'
        f"<td>{_dot(categories, e.category, e.subcategory)}{escape(e.category)}"
        f"{escape(' › ' + e.subcategory) if e.subcategory else ''}</td>"
        f"<td>{escape(e.description)}</td><td>{escape(e.payment_method)}</td>"
        f'<td class="num">{_money(review, e.amount_in(review.currency))}</td></tr>'
        for e in review.biggest)
    head = '<tr><th class="num">Date</th><th>Category</th><th>Description</th><th>Paid with</th><th class="num">Amount</th></tr>'
    return _section("Biggest expenses", f"<table><thead>{head}</thead><tbody>{rows}</tbody></table>")


def _budgets(review: MonthReview, categories: list[Category]) -> str:
    if not review.budgets:
        return _section("Budgets", f'<p class="muted">{escape(budgets_note(review))}</p>')

    def row(status: BudgetStatus, part: bool) -> str:
        sub = "" if status.subcategory in (None, OTHER) else status.subcategory
        return (f'<tr class="{"part" if part else ""}"><td>{_dot(categories, status.category, sub)}{escape(status.label)}</td>'
                f"<td>{_bar(status.fill, LEVEL_COLORS[status.level])}</td>"
                f'<td class="{"bad" if status.level == "over" else ""}">{escape(budget_text(status))}</td></tr>')

    rows = "".join(row(s, False) + "".join(row(p, True) for p in s.parts) for s in review.budgets)
    return _section("Budgets", f'<p class="headline">{escape(budgets_note(review))}</p>'
                               f'<table><tbody>{rows}</tbody></table>')


def _debts(review: MonthReview) -> str:
    debts = review.debts
    if debts.is_empty:
        return ""

    def moves(title: str, items: list) -> str:
        if not items:
            return f'<div><h3>{escape(title)}</h3><p class="muted">None</p></div>'
        rows = "".join(f'<tr><td class="num">{m.date.day} {m.date:%b}</td><td>{escape(m.debt.counterparty)}</td>'
                       f'<td class="num">{_money(review, m.amount)}</td></tr>' for m in items)
        total = sum((m.amount for m in items if m.amount is not None), Decimal("0"))
        rows += f'<tr class="total"><td></td><td>Total</td><td class="num">{_money(review, total)}</td></tr>'
        return f"<div><h3>{escape(title)}</h3><table><tbody>{rows}</tbody></table></div>"

    when = "today" if review.is_current else f"at the end of {month_name(review.month)}"
    content = (f'<div class="cols">{moves("Paid this month", debts.paid)}{moves("Received this month", debts.received)}</div>'
               f"<h3>Still owed {escape(when)}</h3><p>You owe <b>{_money(review, debts.i_owe)}</b> · "
               f"owed to you <b>{_money(review, debts.owed_to_me)}</b></p>")
    if debts.upcoming:
        rows = []
        for m in debts.upcoming:
            overdue = ' <span class="tag">Overdue</span>' if m.date < review.today else ""
            rows.append(f'<tr><td class="num">{m.date.day} {m.date:%b}{overdue}</td><td>{escape(m.debt.counterparty)}</td>'
                        f"<td>{escape(DIRECTION_LABELS[m.debt.direction])}</td>"
                        f'<td class="num">{_money(review, m.amount)}</td></tr>')
        content += f"<h3>Coming up</h3><table><tbody>{''.join(rows)}</tbody></table>"
    return _section("Debts", content)


def _footer(review: MonthReview) -> str:
    notes = [usual_note(review)]
    if review.missing_rate:
        notes.append(f"{review.missing_rate} record(s) without an exchange rate aren't counted.")
    today = review.today
    notes.append(f"Made with {APP_NAME} {__version__} on {today.day} {today:%b %Y}.")
    return "<footer>" + " ".join(escape(n) for n in notes) + "</footer>"
