"""Daily expenses (Reports tab): a block per day with the categories side by side — each with its
items, descriptions and amounts — and a yellow row with the day's sums. Drawn on a canvas."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from ...daily import DAY_FILL, TOTAL_FILL, DailyTable, amount_text, build_daily_table, header_color
from ...exporter import export_daily_xlsx
from ...storage import Expense, format_money
from ..forms import ExpenseDialog
from ..widgets import month_label
from .base import PageData

if TYPE_CHECKING:
    from ..app import ExpenseApp

BORDER, TEXT, MUTED = "#374151", "#1f2937", "#6b7280"
SHEET = "#ffffff"
MAX_DESCRIPTION = 260  # wider descriptions are cut with "…" (the full text is in the edit dialog)


class DailyExpensesView(ttk.Frame):
    def __init__(self, master: tk.Misc, app: ExpenseApp):
        super().__init__(master, padding=(0, 8, 0, 0))
        self.app = app
        self.scale = app.icons.scale
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.heading = ttk.Label(top, style="Title.TLabel")
        self.heading.pack(side="left")
        self.note = ttk.Label(top, style="Muted.TLabel")
        self.note.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Export to Excel…", command=self.export_excel).pack(side="right")

        # The dates have a canvas of their own that scrolls up and down with the table but not
        # sideways, so they stay in view while scrolling through the categories.
        box = ttk.Frame(self)
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(1, weight=1)
        box.rowconfigure(0, weight=1)
        self.dates = tk.Canvas(box, background=SHEET, highlightthickness=0, width=0)
        self.canvas = tk.Canvas(box, background=SHEET, highlightthickness=0)
        down = ttk.Scrollbar(box, orient="vertical", command=self._yview)
        across = ttk.Scrollbar(box, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        self.dates.grid(row=0, column=0, sticky="ns")
        self.canvas.grid(row=0, column=1, sticky="nsew")
        down.grid(row=0, column=2, sticky="ns")
        across.grid(row=1, column=1, sticky="ew")
        for canvas in (self.dates, self.canvas):
            canvas.bind("<Enter>", lambda _e: self._wheel(True))
            canvas.bind("<Leave>", lambda _e: self._wheel(False))
        self.canvas.tag_bind("expense", "<Double-1>", self._edit_at)
        self.canvas.tag_bind("expense", "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind("expense", "<Leave>", lambda _e: self.canvas.configure(cursor=""))

        self.font = tkfont.Font(self, family="Segoe UI", size=9)
        self.bold = tkfont.Font(self, family="Segoe UI", size=9, weight="bold")
        self._data: PageData | None = None
        self.table: DailyTable | None = None
        self._shown: DailyTable | None = None
        self._expenses: dict[str, Expense] = {}

    # ---------- data ----------

    def set_data(self, data: PageData) -> None:
        self._data = data
        self.table = None

    def current_table(self) -> DailyTable | None:
        if self.table is None and self._data is not None:
            data = self._data
            self.table = build_daily_table(data.expenses, data.period, data.show_in, [c.name for c in self.app.categories])
        return self.table

    def _period_label(self) -> str:
        period = self._data.period if self._data else None
        return month_label(period) if period else "all months"

    def export_excel(self) -> None:
        table = self.current_table()
        if table is None:
            return
        colors = {cat: self.app.look(cat)[1] for cat in table.categories}
        user = self.app.user.name if self.app.user else ""
        self.app.export_file(
            "Export daily expenses", "daily-expenses", ".xlsx",
            lambda path: export_daily_xlsx(Path(path), table, f"Daily expenses — {self._period_label()}", colors, user),
            f"{table.count} expense{'s' * (table.count != 1)} on {len(table.days)} day{'s' * (len(table.days) != 1)}")

    def _edit_at(self, event: tk.Event) -> None:
        """Open the expense under the pointer (double-click) in the usual edit dialog."""
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            expense = next((self._expenses.get(t[3:]) for t in self.canvas.gettags(item) if t.startswith("id:")), None)
            if expense is not None:
                ExpenseDialog(self.app, expense)
                return

    def _yview(self, *args) -> None:
        self.canvas.yview(*args)
        self.dates.yview(*args)

    def _wheel(self, active: bool) -> None:
        if not active:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Shift-MouseWheel>")
            return
        self.canvas.bind_all("<MouseWheel>", lambda e: self._yview("scroll", int(-e.delta / 120), "units"))
        self.canvas.bind_all("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(int(-e.delta / 120), "units"))

    # ---------- drawing ----------

    def show(self) -> None:
        table = self.current_table()
        if table is None or table is self._shown:
            return
        self._shown = table
        self.heading.configure(text=f"Daily expenses — {self._period_label()}")
        days = len(table.days)
        notes = [f"{table.count} expense{'s' * (table.count != 1)} on {days} day{'s' * (days != 1)}",
                 f"amounts in {table.currency}", "double-click an expense to edit it"]
        if table.missing_rate:
            notes.append(f"{table.missing_rate} without an exchange rate aren't in the sums")
        self.note.configure(text=" · ".join(notes))
        self._expenses = {e.id: e for d in table.days for items in d.items.values() for e in items}
        self._draw(table)
        self.canvas.xview_moveto(0)
        self._yview("moveto", 0)

    def _fit(self, text: str, width: int) -> str:
        """`text`, cut with "…" to fit in `width` pixels."""
        if self.font.measure(text) <= width:
            return text
        while text and self.font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def _draw(self, table: DailyTable) -> None:
        c, dates, font, bold, s = self.canvas, self.dates, self.font, self.bold, self.scale
        c.delete("all")
        dates.delete("all")
        pad, margin, line = round(6 * s), round(10 * s), max(1, round(1.5 * s))
        row_h = max(font.metrics("linespace"), self.app.icons.size) + round(6 * s)
        if not table.days:
            dates.configure(width=0, scrollregion=(0, 0, 0, 0))
            c.create_text(margin, margin, text="No expenses in this period.", anchor="nw", font=font, fill=MUTED)
            c.configure(scrollregion=(0, 0, 0, 0))
            return

        def money(value) -> str:
            return format_money(value, table.currency)

        # The date column, on its own canvas (its border fully inside it, so it shows while the
        # table scrolls sideways).
        date_w = max(bold.measure("0000-00-00"), font.measure("Wednesday"), bold.measure("Total")) + 2 * pad
        left, date_right = margin, margin + date_w
        dates.configure(width=date_right)
        # Column widths: each category gets item | description | amount, wide enough for its header.
        groups = []  # (category, x, item width, description width, amount width, header image, header color)
        x = 0
        for cat in table.categories:
            items = [e for d in table.days for e in d.items.get(cat, [])]
            item_w = max((font.measure(e.subcategory) for e in items), default=0) + 2 * pad
            desc_w = min(max((font.measure(e.description) for e in items), default=0), round(MAX_DESCRIPTION * s)) + 2 * pad
            amount_w = max([font.measure(amount_text(e, table.currency)) for e in items]
                           + [bold.measure(money(table.sums[cat]))]) + 2 * pad
            icon, color = self.app.look(cat)
            image = self.app.icons.get(icon, color)
            header_w = bold.measure(cat) + 3 * pad + (image.width() + pad if image else 0)
            if item_w + desc_w + amount_w < header_w:
                desc_w = header_w - item_w - amount_w
            groups.append((cat, x, item_w, desc_w, amount_w, image, header_color(color)))
            x += item_w + desc_w + amount_w
        total_w = max(bold.measure(money(table.total)), font.measure("Day total")) + 2 * pad
        right_edge = x + total_w

        y = margin
        for day in table.days:
            top, first = y, y + row_h
            sums_top = first + max(day.rows, 1) * row_h
            bottom = sums_top + row_h
            mid = top + row_h / 2
            sums_mid = sums_top + row_h / 2
            dates.create_rectangle(left, top, date_right, first, fill=DAY_FILL, outline="")
            dates.create_rectangle(left, sums_top, date_right, bottom, fill=DAY_FILL, outline="")
            c.create_rectangle(0, sums_top, right_edge, bottom, fill=DAY_FILL, outline="")
            dates.create_text(left + pad, mid, text=day.day.isoformat(), anchor="w", font=bold, fill=TEXT)
            dates.create_text(left + pad, first + row_h / 2, text=f"{day.day:%A}", anchor="w", font=font, fill=MUTED)
            dates.create_text(left + pad, sums_mid, text=day.day.isoformat(), anchor="w", font=bold, fill=TEXT)
            for cat, gx, item_w, desc_w, amount_w, image, fill in groups:
                right = gx + item_w + desc_w + amount_w
                name_w = bold.measure(cat) + 2 * pad + (image.width() + pad if image else 0)
                c.create_rectangle(right - name_w, top, right, first, fill=fill, outline="")
                c.create_text(right - pad, mid, text=cat, anchor="e", font=bold, fill=TEXT)
                if image:
                    c.create_image(right - 2 * pad - bold.measure(cat), mid, image=image, anchor="e")
                for i, e in enumerate(day.items.get(cat, [])):
                    row_top = first + i * row_h
                    ry = row_top + row_h / 2
                    tags = ("expense", f"id:{e.id}")
                    c.create_rectangle(gx + 1, row_top, right - 1, row_top + row_h, fill=SHEET, outline="", tags=tags)
                    c.create_text(gx + pad, ry, text=e.subcategory, anchor="w", font=font, fill=TEXT, tags=tags)
                    c.create_text(gx + item_w + pad, ry, text=self._fit(e.description, desc_w - 2 * pad), anchor="w",
                                  font=font, fill=TEXT, tags=tags)
                    c.create_text(right - pad, ry, text=amount_text(e, table.currency), anchor="e", font=font,
                                  fill=TEXT if e.amount_in(table.currency) is not None else MUTED, tags=tags)
                if cat in day.sums:
                    c.create_text(right - pad, sums_mid, text=money(day.sums[cat]), anchor="e", font=bold, fill=TEXT)
                c.create_rectangle(gx, top, right, bottom, outline=BORDER, width=line)
            c.create_text(right_edge - pad, mid, text="Day total", anchor="e", font=font, fill=MUTED)
            c.create_text(right_edge - pad, sums_mid, text=money(day.total), anchor="e", font=bold, fill=TEXT)
            c.create_line(0, sums_top, right_edge, sums_top, fill=BORDER)
            dates.create_line(left, sums_top, date_right, sums_top, fill=BORDER)
            dates.create_rectangle(left, top, date_right - line / 2, bottom, outline=BORDER, width=line)
            c.create_rectangle(right_edge - total_w, top, right_edge, bottom, outline=BORDER, width=line)
            y = bottom

        # Totals for the whole period
        y += round(8 * s)
        mid = y + row_h / 2
        dates.create_rectangle(left, y, date_right - line / 2, y + row_h, fill=TOTAL_FILL, outline=BORDER, width=line)
        dates.create_text(left + pad, mid, text="Total", anchor="w", font=bold, fill=TEXT)
        c.create_rectangle(0, y, right_edge, y + row_h, fill=TOTAL_FILL, outline=BORDER, width=line)
        for cat, gx, item_w, desc_w, amount_w, _, _ in groups:
            right = gx + item_w + desc_w + amount_w
            c.create_text(right - pad, mid, text=money(table.sums[cat]), anchor="e", font=bold, fill=TEXT)
            c.create_line(gx, y, gx, y + row_h, fill=BORDER, width=line)
        c.create_line(right_edge - total_w, y, right_edge - total_w, y + row_h, fill=BORDER, width=line)
        c.create_text(right_edge - pad, mid, text=money(table.total), anchor="e", font=bold, fill=TEXT)
        height = y + row_h + margin
        c.configure(scrollregion=(0, 0, right_edge + margin, height))
        dates.configure(scrollregion=(0, 0, date_right, height))
