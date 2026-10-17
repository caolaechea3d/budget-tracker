"""Budgets tab: monthly limit per category with progress bars."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ...reports import OTHER, BudgetStatus, budget_statuses, category_totals, is_year
from ...storage import DEFAULT_CURRENCY, format_money
from ..forms import BudgetDialog
from ..widgets import ScrollableFrame, month_label
from .base import LEVEL_COLORS, PageData, Tab


class BudgetsTab(Tab):
    label = "Budgets"
    tab_icon = "🎯"
    tab_color = "#e63946"

    def build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.heading = ttk.Label(top, style="Title.TLabel")
        self.heading.pack(side="left")
        ttk.Button(top, text="Set budget…", command=lambda: BudgetDialog(self.app)).pack(side="right")
        self.rows = ScrollableFrame(self)
        self.rows.grid(row=1, column=0, sticky="nsew")
        self.rows.inner.columnconfigure(2, weight=1)

    def redraw(self, data: PageData) -> None:
        month = data.focus_month
        note = "" if data.period and not is_year(data.period) else "  (budgets are per month)"
        self.heading.configure(text=f"Monthly budgets — {month_label(month)}{note}")
        inner = self.rows.inner
        for child in inner.winfo_children():
            child.destroy()
        row = self._budget_rows(inner, data, month)
        self._unbudgeted_rows(inner, data, month, row)

    def _budget_rows(self, inner: ttk.Frame, data: PageData, month: str) -> int:
        """One row per budget: icon, progress bar, spent/limit text, Edit/Remove. Returns the next row."""
        statuses = budget_statuses(data.expenses, data.budgets, month)
        if not statuses:
            ttk.Label(inner, text="No budgets yet. Click “Set budget…” to set a monthly limit for a category.",
                      style="Muted.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=6)
            return 1
        row = 0
        for status in statuses:
            self._row(inner, row, status, month)
            row += 1
            for part in status.parts:  # subcategory budgets (and "Other <category>") under their category
                self._row(inner, row, part, month)
                row += 1
        return row

    def _row(self, inner: ttk.Frame, row: int, status: BudgetStatus, month: str) -> None:
        """Icon + name, progress bar, spent/limit text (+ notes), Edit/Remove."""
        category, sub = status.category, status.subcategory
        is_part = sub is not None
        if sub == OTHER:
            icon, color = self.app.look(category)
        else:
            icon, color = self.app.look(category, sub or "")
        ttk.Label(inner, **self.app.icon_text(icon, color, status.label), compound="left",
                  style="TLabel" if is_part else "Bold.TLabel").grid(
            row=row, column=0, sticky="w", pady=(2, 2) if is_part else (8, 2), padx=(28 if is_part else 0, 10))
        height = round((10 if is_part else 14) * self.icons.scale)
        bar = tk.Canvas(inner, height=height, highlightthickness=0, background="#e5e7eb")
        bar.grid(row=row, column=2, sticky="ew", padx=(0, 12))
        bar_color = LEVEL_COLORS[status.level]
        bar.bind("<Configure>", lambda e, c=bar, r=status.fill, col=bar_color: self._draw_progress(c, r, col))

        label_style = {"ok": "TLabel", "warning": "Warning.TLabel", "over": "Over.TLabel"}[status.level]
        details = ttk.Frame(inner)
        details.grid(row=row, column=3, sticky="w", padx=(0, 10))
        ttk.Label(details, text=self._status_text(status), style=label_style).pack(anchor="w")
        notes = []
        if status.parts:
            notes.append("Sum of: " + ", ".join(p.label for p in status.parts))
        if sub == OTHER:
            notes.append("Everything not in a subcategory budget")
        if status.is_exception:
            differs = "differs" if status.parts else "only"
            notes.append(f"{month_label(month)} {differs} · usually {format_money(status.usual, status.currency)} a month")
        for note in notes:
            ttk.Label(details, text=note, style="Muted.TLabel").pack(anchor="w")

        edit_sub = None if sub in (None, OTHER) else sub  # "Other <category>" is the category's own amount
        ttk.Button(inner, text="Edit", width=6,
                   command=lambda: BudgetDialog(self.app, category, edit_sub)).grid(row=row, column=4)
        if sub != OTHER:
            ttk.Button(inner, text="Remove", width=8,
                       command=lambda: self.remove_budget(category, edit_sub)).grid(row=row, column=5, padx=(4, 0))

    def _unbudgeted_rows(self, inner: ttk.Frame, data: PageData, month: str, row: int) -> None:
        """Categories with spending this month but no budget, each with a 'Set budget' button."""
        budgeted = {b.lower() for b in data.budgets}
        unbudgeted = {c: v for c, v in category_totals(data.expenses, month, DEFAULT_CURRENCY).items()
                      if c.lower() not in budgeted}
        if not unbudgeted:
            return
        ttk.Separator(inner).grid(row=row, column=0, columnspan=6, sticky="ew", pady=10)
        ttk.Label(inner, text="Spending without a budget this month", style="Muted.TLabel").grid(
            row=row + 1, column=0, columnspan=6, sticky="w")
        row += 2
        for category, value in sorted(unbudgeted.items(), key=lambda kv: kv[1], reverse=True):
            icon, color = self.app.look(category)
            ttk.Label(inner, **self.app.icon_text(icon, color, category), compound="left").grid(
                row=row, column=0, sticky="w", pady=3)
            ttk.Label(inner, text=format_money(value, DEFAULT_CURRENCY)).grid(row=row, column=3, sticky="w")
            ttk.Button(inner, text="Set budget", command=lambda c=category: BudgetDialog(self.app, c)).grid(
                row=row, column=4, columnspan=2, sticky="w")
            row += 1

    @staticmethod
    def _status_text(status: BudgetStatus) -> str:
        currency = status.currency
        spent, limit = format_money(status.spent, currency), format_money(status.limit, currency)
        if status.ratio is None:  # a 0 budget this month
            text = (f"Nothing planned this month (budget {limit})" if status.spent == 0
                    else f"{spent} spent · budget {limit} this month · over by {spent}")
        else:
            left = (f"{format_money(status.remaining, currency)} left" if status.remaining >= 0
                    else f"over by {format_money(-status.remaining, currency)}")
            text = f"{spent} of {limit} · {status.ratio * 100:.0f}% · {left}"
        if status.missing_rate:
            text += f" · {status.missing_rate} without rate"
        return text

    @staticmethod
    def _draw_progress(canvas: tk.Canvas, ratio: float, color: str) -> None:
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.create_rectangle(0, 0, width * min(ratio, 1.0), height, fill=color, outline="")
        if ratio > 1:
            canvas.create_line(width - 1, 0, width - 1, height, fill="#7f1d1d", width=2)

    def remove_budget(self, category: str, subcategory: str | None = None) -> None:
        if subcategory:
            name = f"{category} › {subcategory}"
            detail = "It's removed for every month; the rest of the category's budget stays."
        else:
            name = category
            budget = next((b for key, b in self.app.store.budgets().items() if key.lower() == category.lower()), None)
            subs = list(budget.subcategories) if budget else []
            detail = ("This removes it for every month, including any month with its own amount"
                      + (f" and the subcategory budgets ({', '.join(subs)})" if subs else "") + ".")
        if messagebox.askyesno("Remove budget", f"Remove the budget for {name}?\n\n{detail}\n"
                                                "To change just one month, use Edit."):
            self.app.store.set_budget(category, None, subcategory=subcategory)
            self.app.budgets_changed(name, False)
