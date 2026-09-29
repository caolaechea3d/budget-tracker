"""Income tab: quick-add form and the income list."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from ...catalog import find_item
from ...reports import in_month
from ...storage import Income, format_money, format_rate, month_key, total_in
from ..forms import IncomeDialog, MoneyFields, income_from_fields
from ..widgets import DateField, Picker, SortableColumns, text_key
from .base import INCOME_COLOR, PageData, Tab


class IncomeTab(Tab):
    label = "Income"
    tab_icon = "💵"
    tab_color = INCOME_COLOR

    def build(self) -> None:
        self.shown: list[Income] = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_form()
        self._build_list()

    def _build_form(self) -> None:
        app = self.app
        form = ttk.LabelFrame(self, text="Add income", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        last = app.last_rate()
        self.quick = MoneyFields(form, rate="" if last is None else format_rate(last))
        self.i_date = tk.StringVar(value=date.today().isoformat())
        self.i_source = tk.StringVar(value="Salary")
        self.i_description = tk.StringVar()
        description = ttk.Entry(form, textvariable=self.i_description)
        widgets = [
            ("Date", DateField(form, self.i_date, icons=self.icons)),
            ("Amount", self.quick.amount),
            ("Currency", self.quick.currency),
            ("Rate (S/ per US$1)", self.quick.rate),
            ("Source", Picker(form, self.icons, self.i_source, app.source_options, on_new=app.add_income_source,
                              new_label="New income source…", width=16)),
            ("Description", description),
        ]
        self.quick.amount.configure(width=10)
        self.quick.rate.configure(width=8)
        for col, (label, widget) in enumerate(widgets):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=col, sticky="ew", padx=(0, 8))
            if isinstance(widget, ttk.Entry):
                widget.bind("<Return>", lambda _e: self.add_income())
        ttk.Button(form, text="Add", command=self.add_income).grid(row=1, column=6)
        self.quick.preview.grid(row=2, column=1, columnspan=4, sticky="w", pady=(4, 0))
        form.columnconfigure(5, weight=1)

    def _build_list(self) -> None:
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(body, columns=("date", "amount", "entered", "rate", "description"),
                                 show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Source", anchor="w")
        self.tree.column("#0", width=180, stretch=False)
        for col, text, width, anchor, stretch in (
            ("date", "Date", 90, "w", False), ("amount", "Amount", 110, "e", False),
            ("entered", "Entered as", 110, "e", False), ("rate", "Rate", 60, "e", False),
            ("description", "Description", 200, "w", True),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.sort = SortableColumns(
            self.tree,
            {"#0": "Source", "date": "Date", "amount": "Amount", "entered": "Entered as",
             "rate": "Rate", "description": "Description"},
            keys={
                "#0": lambda i: i.source.lower(),
                "date": lambda i: (i.date, i.id),
                "amount": lambda i: i.amount_in(self.app.show_in_var.get()),
                "entered": lambda i: (i.currency, i.amount),
                "rate": lambda i: i.rate,
                "description": lambda i: text_key(i.description),
            },
            default=("date", True), on_change=self.app.refresh, descending_first=("date", "amount", "entered", "rate"),
        )
        self.tree.bind("<Double-1>", lambda e: self._edit_at(e.y))
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        actions = ttk.Frame(body)
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Edit", command=self.edit_selected).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Delete", command=self.delete_selected).pack(side="left")
        self.total_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.total_var, style="Bold.TLabel").pack(side="right")

    def redraw(self, data: PageData) -> None:
        show_in = data.show_in
        newest_first = sorted(in_month(data.incomes, data.period), key=lambda i: (i.date, i.id), reverse=True)
        self.shown = self.sort.apply(newest_first)
        self.sort.set_heading("amount", f"Amount ({show_in})")
        self.tree.delete(*self.tree.get_children())
        for inc in self.shown:
            source = find_item(self.app.income_sources, inc.source)
            self.tree.insert("", "end", iid=inc.id,
                             **self.app.icon_text(source.icon if source else "💰", INCOME_COLOR, inc.source),
                             values=(inc.date.isoformat(), format_money(inc.amount_in(show_in), show_in),
                                     format_money(inc.amount, inc.currency), format_rate(inc.rate), inc.description))
        total, _ = total_in(self.shown, show_in)
        self.total_var.set(f"Total: {format_money(total, show_in)}   ({len(self.shown)} entries)")
        if data.select_income and self.tree.exists(data.select_income):
            self.tree.selection_set(data.select_income)
            self.tree.see(data.select_income)

    def add_income(self) -> None:
        try:
            income = income_from_fields(
                self.i_date.get(), self.quick.amount_var.get(), self.quick.currency_var.get(),
                self.quick.rate_var.get(), self.i_source.get(), self.i_description.get(),
            )
            self.app.store.add_income(income)
        except ValueError as exc:
            messagebox.showerror("Invalid income", str(exc))
            return
        self.quick.amount_var.set("")
        self.i_description.set("")
        self.app.income_saved(income, "Added")

    def reveal(self, income: Income) -> None:
        """Switch to the income's month if the selected period would hide it."""
        month = month_key(income.date)
        period = self.app.selected_month()
        if period and not month.startswith(period):
            self.app.month_var.set(month)

    def _edit_at(self, y: int) -> None:
        row = self.tree.identify_row(y)
        if row:
            self.tree.selection_set(row)
            self.edit_selected()

    def edit_selected(self) -> None:
        selected = self.tree.selection()
        income = next((i for i in self.shown if selected and i.id == selected[0]), None)
        if income:
            IncomeDialog(self.app, income)

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if selected and messagebox.askyesno(
            "Delete", f"Delete {len(selected)} income entr{'y' if len(selected) == 1 else 'ies'}?"
        ):
            for income_id in selected:
                self.app.store.delete_income(income_id)
            self.app.refresh()
