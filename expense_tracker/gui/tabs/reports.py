"""Reports tab: the daily expenses table (daily.py) and the month in review — how the month went,
what changed, where it's heading."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from ...debts import DIRECTION_LABELS
from ...reports import OTHER, BudgetStatus, budget_text, is_year
from ...review import (
    INSIGHT_LOOKS,
    DebtMove,
    MonthReview,
    budgets_note,
    build_month_review,
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
from ...review_html import save_html
from ...storage import format_money
from ..charts import draw_bars
from ..forms import open_file
from ..widgets import ScrollableFrame, month_label, progress_bar
from .base import EXPENSE_COLOR, INCOME_COLOR, LEVEL_COLORS, PageData, Tab
from .daily import DailyExpensesView

if TYPE_CHECKING:
    from ..app import ExpenseApp

TONE_STYLES = {"good": "Good.TLabel", "bad": "Bad.TLabel", "": "Muted.TLabel"}


class ReportsTab(Tab):
    label = "Reports"
    tab_icon = "📋"
    tab_color = "#3d5a80"

    def build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.views = ttk.Notebook(self)
        self.views.grid(row=0, column=0, sticky="nsew")
        self.daily_view = DailyExpensesView(self.views, self.app)
        self.review_view = MonthReviewView(self.views, self.app)
        self.views.add(self.daily_view, text="Daily expenses")
        self.views.add(self.review_view, text="Month in review")
        # Reports take a moment to build, so only the one in view is built, when it comes into view.
        self.bind("<Map>", lambda _e: self._show())
        self.views.bind("<<NotebookTabChanged>>", lambda _e: self._show())

    def redraw(self, data: PageData) -> None:
        self.daily_view.set_data(data)
        self.review_view.set_data(data)
        self._show()

    def _show(self) -> None:
        if self.winfo_ismapped():
            self.views.nametowidget(self.views.select()).show()


class MonthReviewView(ttk.Frame):
    def __init__(self, master: tk.Misc, app: ExpenseApp):
        super().__init__(master, padding=(0, 8, 0, 0))
        self.app = app
        self.icons = app.icons
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.heading = ttk.Label(top, style="Title.TLabel")
        self.heading.pack(side="left")
        self.note = ttk.Label(top, style="Muted.TLabel")
        self.note.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Save as HTML…", command=self.save_html).pack(side="right")
        self.body = ScrollableFrame(self)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.inner.columnconfigure((0, 1), weight=1, uniform="half")
        self._data: PageData | None = None
        self.review: MonthReview | None = None  # built when shown or saved
        self._shown: MonthReview | None = None

    def set_data(self, data: PageData) -> None:
        self._data = data
        self.review = None

    def current_review(self) -> MonthReview | None:
        if self.review is None and self._data is not None:
            data = self._data
            self.review = build_month_review(data.focus_month, data.show_in, data.expenses, data.incomes, data.budgets,
                                             data.debts, self.app.store.recurring(), self.app.last_rate())
        return self.review

    def save_html(self) -> None:
        review = self.current_review()
        if review is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save the month in review", defaultextension=".html", filetypes=[("Web page", "*.html")],
            initialfile=f"month-in-review-{review.month}.html")
        if not path:
            return
        try:
            save_html(review, Path(path), self.app.categories, self.app.user.name if self.app.user else "")
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.app.set_status(f"Saved the month in review to {path} (opening it in your browser; print it from there)")
        open_file(Path(path))

    # ---------- drawing ----------

    def show(self) -> None:
        review = self.current_review()
        if review is None or review is self._shown:
            return
        self._shown = review
        period = self._data.period
        self.heading.configure(text=f"Month in review — {month_label(review.month)}")
        hint = "choose a month at the top to review another" if period is None or is_year(period) else ""
        self.note.configure(text=" · ".join(filter(None, [period_note(review), hint])))
        inner = self.body.inner
        for child in inner.winfo_children():
            child.destroy()
        self._cards(inner, review).grid(row=0, column=0, columnspan=2, sticky="ew")
        if review.forecast:
            self._forecast(self._section(inner, f"Where {month_name(review.month)} is heading", 1), review)
        self._insights(self._section(inner, "What stood out", 2), review)
        self._categories(self._section(inner, "Spending by category", 3, column=0), review)
        self._trend(self._section(inner, f"The last {len(review.trend)} months", 3, column=1), review)
        self._biggest(self._section(inner, "Biggest expenses", 4, column=0), review)
        self._budgets(self._section(inner, "Budgets", 4, column=1), review)
        if not review.debts.is_empty:
            self._debts(self._section(inner, "Debts", 5), review)
        notes = [usual_note(review)]
        if review.missing_rate:
            notes.append(f"{review.missing_rate} record(s) without an exchange rate aren't counted.")
        ttk.Label(inner, text=" ".join(notes), style="Muted.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))

    @staticmethod
    def _section(inner: ttk.Frame, title: str, row: int, column: int | None = None) -> ttk.LabelFrame:
        box = ttk.LabelFrame(inner, text=title, padding=10)
        if column is None:
            box.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        else:
            box.grid(row=row, column=column, sticky="nsew", pady=(10, 0), padx=(0, 5) if column == 0 else (5, 0))
        return box

    def _money(self, review: MonthReview, value) -> str:
        return format_money(value, review.currency)

    def _cards(self, inner: ttk.Frame, review: MonthReview) -> ttk.Frame:
        cards = ttk.Frame(inner)
        so_far = " so far" if review.is_current else ""
        saved = review.totals.saved
        count = f"{review.count} expense{'s' * (review.count != 1)}"
        for i, (label, value, style, note, key) in enumerate([
            (f"Income{so_far}", review.totals.income, "Income", "", "income"),
            (f"Expenses{so_far}", review.totals.expenses, "Expense", count, "expenses"),
            (f"Saved{so_far}", saved, "Income" if saved >= 0 else "Expense", savings_note(review), "saved"),
        ]):
            cards.columnconfigure(i, weight=1, uniform="card")
            card = ttk.LabelFrame(cards, text=label, padding=(12, 4, 12, 8))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == 2 else 5))
            ttk.Label(card, text=self._money(review, value), style=f"{style}.CardValue.TLabel").pack(anchor="w")
            if note:
                ttk.Label(card, text=note, style="Muted.TLabel").pack(anchor="w")
            for text, tone in comparisons(review, key):
                ttk.Label(card, text=text, style=TONE_STYLES[tone]).pack(anchor="w")
        return cards

    def _forecast(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        ttk.Label(box, text=forecast_headline(review), style="Bold.TLabel").pack(anchor="w", pady=(0, 4))
        for line in forecast_details(review):
            ttk.Label(box, text=f"•  {line}").pack(anchor="w")

    def _insights(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        if not review.insights:
            text = ("Not much to compare with yet: this starts working after a month of records." if not review.history
                    else f"Nothing unusual{' so far' if review.is_current else ''}: a month like most.")
            ttk.Label(box, text=text, style="Muted.TLabel").pack(anchor="w")
        for insight in review.insights:
            icon, color = INSIGHT_LOOKS[insight.kind]
            ttk.Label(box, **self.app.icon_text(icon, color, insight.text), compound="left").pack(anchor="w", pady=1)

    def _categories(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        if not review.categories:
            ttk.Label(box, text="No expenses this month.", style="Muted.TLabel").grid(sticky="w")
            return
        box.columnconfigure(1, weight=1)
        current = review.is_current
        if review.history:
            ttk.Label(box, text="Usual month" if current else "vs usual", style="Muted.TLabel").grid(
                row=0, column=4, sticky="e")
        largest = max(line.amount for line in review.categories)
        height = round(8 * self.icons.scale)
        for row, line in enumerate(review.categories, start=1):
            icon, color = self.app.look(line.category)
            ttk.Label(box, **self.app.icon_text(icon, color, line.category), compound="left").grid(
                row=row, column=0, sticky="w", pady=1, padx=(0, 10))
            progress_bar(box, float(line.amount / largest), color, height).grid(row=row, column=1, sticky="ew")
            ttk.Label(box, text=self._money(review, line.amount)).grid(row=row, column=2, sticky="e", padx=(10, 0))
            ttk.Label(box, text=f"{line.share}%", style="Muted.TLabel").grid(row=row, column=3, sticky="e", padx=(8, 0))
            if current and line.usual is not None:  # half a month vs a whole one: show what's usual instead
                compare, tone = (self._money(review, line.usual) if line.usual else "new"), ""
            else:
                compare, tone = change_label(line), change_tone(line)
            ttk.Label(box, text=compare, style=TONE_STYLES[tone]).grid(row=row, column=4, sticky="e", padx=(8, 0))
        total = len(review.categories) + 1
        ttk.Label(box, text="Total", style="Bold.TLabel").grid(row=total, column=0, sticky="w", pady=(4, 0))
        ttk.Label(box, text=self._money(review, review.totals.expenses), style="Bold.TLabel").grid(
            row=total, column=2, sticky="e", pady=(4, 0))

    def _trend(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        canvas = tk.Canvas(box, height=round(220 * self.icons.scale), highlightthickness=0, background=background)
        canvas.pack(fill="both", expand=True)
        months = list(review.trend)
        series = [("Income", {m: t.income for m, t in review.trend.items()}, INCOME_COLOR),
                  ("Expenses", {m: t.expenses for m, t in review.trend.items()}, EXPENSE_COLOR)]
        canvas.bind("<Configure>", lambda _e: draw_bars(canvas, months, series, highlight=review.month))

    def _biggest(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        if not review.biggest:
            ttk.Label(box, text="No expenses this month.", style="Muted.TLabel").grid(sticky="w")
            return
        box.columnconfigure(2, weight=1)
        for row, e in enumerate(review.biggest):
            icon, color = self.app.look(e.category, e.subcategory)
            name = f"{e.category} › {e.subcategory}" if e.subcategory else e.category
            ttk.Label(box, text=f"{e.date.day} {e.date:%b}", style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 8))
            ttk.Label(box, **self.app.icon_text(icon, color, name), compound="left").grid(
                row=row, column=1, sticky="w", pady=1, padx=(0, 8))
            ttk.Label(box, text=e.description, style="Muted.TLabel").grid(row=row, column=2, sticky="w")
            ttk.Label(box, text=self._money(review, e.amount_in(review.currency))).grid(
                row=row, column=3, sticky="e", padx=(8, 0))

    def _budgets(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        ttk.Label(box, text=budgets_note(review), style="Bold.TLabel" if review.budgets else "Muted.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        box.columnconfigure(1, weight=1)
        height = round(8 * self.icons.scale)
        row = 1
        for status in review.budgets:
            for item, part in ((status, False), *((p, True) for p in status.parts)):
                self._budget_row(box, row, item, part, height)
                row += 1

    def _budget_row(self, box: ttk.LabelFrame, row: int, status: BudgetStatus, part: bool, height: int) -> None:
        sub = "" if status.subcategory in (None, OTHER) else status.subcategory
        icon, color = self.app.look(status.category, sub)
        ttk.Label(box, **self.app.icon_text(icon, color, status.label), compound="left").grid(
            row=row, column=0, sticky="w", pady=1, padx=(20 if part else 0, 10))
        progress_bar(box, status.fill, LEVEL_COLORS[status.level], height).grid(row=row, column=1, sticky="ew")
        style = {"ok": "TLabel", "warning": "Warning.TLabel", "over": "Bad.TLabel"}[status.level]
        ttk.Label(box, text=budget_text(status), style=style).grid(row=row, column=2, sticky="w", padx=(10, 0))

    def _debts(self, box: ttk.LabelFrame, review: MonthReview) -> None:
        debts = review.debts
        box.columnconfigure((0, 1), weight=1, uniform="debts")

        def moves(column: int, title: str, items: list[DebtMove]) -> None:
            frame = ttk.Frame(box)
            frame.grid(row=0, column=column, sticky="nw", padx=(0, 20))
            ttk.Label(frame, text=title, style="Bold.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
            if not items:
                ttk.Label(frame, text="None", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
            for row, m in enumerate(items, start=1):
                ttk.Label(frame, text=f"{m.date.day} {m.date:%b}", style="Muted.TLabel").grid(
                    row=row, column=0, sticky="w", padx=(0, 8))
                ttk.Label(frame, text=m.debt.counterparty).grid(row=row, column=1, sticky="w", padx=(0, 12))
                ttk.Label(frame, text=self._money(review, m.amount)).grid(row=row, column=2, sticky="e")
            if len(items) > 1:
                total = sum((m.amount for m in items if m.amount is not None), Decimal("0"))
                ttk.Label(frame, text="Total", style="Bold.TLabel").grid(row=len(items) + 1, column=1, sticky="w")
                ttk.Label(frame, text=self._money(review, total), style="Bold.TLabel").grid(
                    row=len(items) + 1, column=2, sticky="e")

        moves(0, "Paid this month", debts.paid)
        moves(1, "Received this month", debts.received)
        when = "today" if review.is_current else f"at the end of {month_name(review.month)}"
        ttk.Label(box, text=f"Still owed {when}: you owe {self._money(review, debts.i_owe)} · "
                            f"owed to you {self._money(review, debts.owed_to_me)}").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        if debts.upcoming:
            ttk.Label(box, text="Coming up", style="Bold.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
            for row, m in enumerate(debts.upcoming, start=3):
                overdue = m.date < review.today
                text = (f"{m.date.day} {m.date:%b}{'  (overdue)' if overdue else ''}   {m.debt.counterparty} · "
                        f"{DIRECTION_LABELS[m.debt.direction]} · {self._money(review, m.amount)}")
                ttk.Label(box, text=text, style="Bad.TLabel" if overdue else "TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w")
