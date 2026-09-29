"""Charts tab: spending by category (donut) and income vs expenses over 12 months (bars)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from ...reports import category_totals, last_n_months, monthly_totals
from ...storage import format_money
from ..charts import draw_bars, draw_donut
from ..widgets import month_label
from .base import EXPENSE_COLOR, INCOME_COLOR, PageData, Tab


class ChartsTab(Tab):
    label = "Charts"
    tab_icon = "📊"
    tab_color = "#577590"

    def build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.donut_box = ttk.LabelFrame(self, text="Spending by category", padding=6)
        self.donut_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.bars_box = ttk.LabelFrame(self, text="Income vs expenses — last 12 months", padding=6)
        self.bars_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.donut = tk.Canvas(self.donut_box, highlightthickness=0, background=background)
        self.donut.pack(fill="both", expand=True)
        self.bars = tk.Canvas(self.bars_box, highlightthickness=0, background=background)
        self.bars.pack(fill="both", expand=True)
        # Canvases redraw themselves whenever they're resized.
        self.donut.bind("<Configure>", lambda _e: self._draw())
        self.bars.bind("<Configure>", lambda _e: self._draw())
        self._chart_data = None

    def redraw(self, data: PageData) -> None:
        show_in, period = data.show_in, data.period
        totals = category_totals(data.expenses, period, show_in)
        slices = []
        for category, value in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            icon, color = self.app.look(category)
            slices.append((category, value, color, self.icons.get(icon, color)))
        months = last_n_months(data.focus_month)
        series = [
            ("Income", monthly_totals(data.incomes, months, show_in), INCOME_COLOR),
            ("Expenses", monthly_totals(data.expenses, months, show_in), EXPENSE_COLOR),
        ]
        total = sum(totals.values(), Decimal("0"))
        self.donut_box.configure(
            text=f"Spending by category — {month_label(period) if period else 'all time'} ({show_in})")
        self.bars_box.configure(text=f"Income vs expenses — last 12 months ({show_in})")
        self._chart_data = (slices, format_money(total, show_in), months, series, data.focus_month)
        self._draw()

    def _draw(self) -> None:
        if not self._chart_data:
            return
        slices, total_text, months, series, end = self._chart_data
        draw_donut(self.donut, slices, "Total", total_text)
        draw_bars(self.bars, months, series, highlight=end)
