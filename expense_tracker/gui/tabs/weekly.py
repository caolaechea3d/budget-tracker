"""Weekly (Reports tab): spending per week, Monday to Sunday — summary cards, a bar chart with the
average, and a table of the weeks with their categories side by side."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import ttk
from typing import TYPE_CHECKING

from ...storage import day_in_month, format_money
from ...weekly import Week, WeeklyTable, build_weekly, change_text, week_label
from ..charts import draw_week_bars
from .base import EXPENSE_COLOR, PageData

if TYPE_CHECKING:
    from ..app import ExpenseApp

WEEK_CHOICES = ("8", "12", "26", "52")


class WeeklyView(ttk.Frame):
    def __init__(self, master: tk.Misc, app: ExpenseApp):
        super().__init__(master, padding=(0, 8, 0, 0))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.heading = ttk.Label(top, style="Title.TLabel")
        self.heading.pack(side="left")
        self.note = ttk.Label(top, style="Muted.TLabel")
        self.note.pack(side="left", padx=(12, 0))
        self.count_var = tk.StringVar(value="12")
        box = ttk.Combobox(top, textvariable=self.count_var, values=WEEK_CHOICES, width=4, state="readonly")
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda _e: self._rebuild())
        ttk.Label(top, text="Weeks").pack(side="right", padx=(0, 6))

        self.cards = ttk.Frame(self)
        self.cards.grid(row=1, column=0, sticky="ew")
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.chart = tk.Canvas(self, height=round(210 * app.icons.scale), highlightthickness=0, background=background)
        self.chart.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())
        self.table_box = ttk.Frame(self)
        self.table_box.grid(row=3, column=0, sticky="nsew")
        self.table_box.columnconfigure(0, weight=1)
        self.table_box.rowconfigure(0, weight=1)

        self._data: PageData | None = None
        self.table: WeeklyTable | None = None
        self._shown: WeeklyTable | None = None
        self.tree: ttk.Treeview | None = None

    # ---------- data ----------

    def set_data(self, data: PageData) -> None:
        self._data = data
        self.table = None

    def end_date(self) -> date:
        """Today, or the last day of the month chosen at the top when that's an earlier month."""
        return min(date.today(), day_in_month(self._data.focus_month, 31))

    def current_table(self) -> WeeklyTable | None:
        if self.table is None and self._data is not None:
            data = self._data
            self.table = build_weekly(data.expenses, self.end_date(), int(self.count_var.get()), data.show_in,
                                      [c.name for c in self.app.categories])
        return self.table

    def _rebuild(self) -> None:
        self.table = None
        self.show()

    # ---------- drawing ----------

    def show(self) -> None:
        table = self.current_table()
        if table is None or table is self._shown:
            return
        self._shown = table
        end = self.end_date()
        self.heading.configure(text=f"Weekly spending — to {end.day} {end:%b %Y}")
        notes = ["weeks run Monday to Sunday", f"amounts in {table.currency}"]
        if table.missing_rate:
            notes.append(f"{table.missing_rate} without an exchange rate aren't counted")
        self.note.configure(text=" · ".join(notes))
        self._cards(table)
        self._draw_chart()
        self._table(table)

    def _money(self, value: Decimal | None) -> str:
        return format_money(value, self.table.currency) if value is not None else "—"

    def _cards(self, table: WeeklyTable) -> None:
        for child in self.cards.winfo_children():
            child.destroy()
        if not table.weeks:
            ttk.Label(self.cards, text="No expenses in these weeks.", style="Muted.TLabel").grid(sticky="w")
            return
        latest = table.weeks[-1]
        before = table.previous(latest)
        cards = []
        if latest.is_partial:
            cards.append(("This week so far", latest.total,
                          f"day {latest.days} of 7 · about {self._money(latest.per_day)} a day"))
        else:
            cards.append(("Latest week", latest.total, self._versus(table, latest)))
        if before is not None:
            cards.append(("The week before" if not latest.is_partial else "Last week", before.total,
                          self._versus(table, before) or week_label(before.start)))
        if table.average is not None:
            finished = len(table.finished)
            per_day = self._money((table.average / 7).quantize(Decimal("0.01")))
            cards.append(("Average week", table.average,
                          f"of {finished} finished week{'s' * (finished != 1)} · {per_day} a day"))
        highest = table.highest
        if highest is not None:
            cards.append(("Highest week", highest.total, week_label(highest.start)))
        for i, (title, value, note) in enumerate(cards):
            self.cards.columnconfigure(i, weight=1, uniform="card")
            card = ttk.LabelFrame(self.cards, text=title, padding=(12, 2, 12, 6))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == len(cards) - 1 else 5))
            ttk.Label(card, text=self._money(value), style="Expense.CardValue.TLabel").pack(anchor="w")
            ttk.Label(card, text=note, style="Muted.TLabel").pack(anchor="w")

    def _versus(self, table: WeeklyTable, week: Week) -> str:
        """'▲ 12% vs the week before · ▼ 3% vs average' (what's known)."""
        parts = []
        if (pct := table.change_vs_previous(week)) is not None:
            parts.append(f"{change_text(pct)} vs the week before")
        if (pct := table.change_vs_average(week)) is not None:
            parts.append(f"{change_text(pct)} vs average")
        return " · ".join(parts)

    def _draw_chart(self) -> None:
        table = self._shown
        if table is None:
            return
        partial = len(table.weeks) - 1 if table.weeks and table.weeks[-1].is_partial else None
        draw_week_bars(self.chart, [f"{w.start.day} {w.start:%b}" for w in table.weeks],
                       [w.total for w in table.weeks], EXPENSE_COLOR, table.average, partial)

    def _table(self, table: WeeklyTable) -> None:
        for child in self.table_box.winfo_children():
            child.destroy()
        fixed = [("week", "Week (Mon–Sun)", 150, "w"), ("total", "Total", 105, "e"),
                 ("previous", "vs week before", 105, "e"), ("average", "vs average", 90, "e"),
                 ("count", "Expenses", 70, "e")]
        columns = [c[0] for c in fixed] + [f"cat{i}" for i in range(len(table.categories))]
        tree = ttk.Treeview(self.table_box, columns=columns, show="headings", selectmode="browse")
        for key, text, width, anchor in fixed:
            tree.heading(key, text=text, anchor=anchor)
            tree.column(key, width=width, minwidth=width, anchor=anchor, stretch=False)
        for i, cat in enumerate(table.categories):
            tree.heading(f"cat{i}", text=cat, anchor="e")
            tree.column(f"cat{i}", width=max(95, len(cat) * 8), anchor="e", stretch=False)
        tree.tag_configure("partial", foreground="#6b7280")
        tree.tag_configure("highest", font=("Segoe UI", 9, "bold"))
        with_year = len({w.end.year for w in table.weeks}) > 1
        highest = table.highest
        for week in reversed(table.weeks):  # newest first, like the other lists
            if week.is_partial:
                versus = ("so far", f"day {week.days} of 7")
            else:
                versus = (change_text(table.change_vs_previous(week)), change_text(table.change_vs_average(week)))
            cells = [format_money(week.by_category[c], table.currency) if c in week.by_category else ""
                     for c in table.categories]
            tags = ("partial",) if week.is_partial else ("highest",) if week is highest else ()
            tree.insert("", "end", values=(week_label(week.start, with_year), self._money(week.total), *versus,
                                           week.count, *cells), tags=tags)
        down = ttk.Scrollbar(self.table_box, orient="vertical", command=tree.yview)
        across = ttk.Scrollbar(self.table_box, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        tree.grid(row=0, column=0, sticky="nsew")
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        self.tree = tree
