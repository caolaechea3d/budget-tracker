"""Expenses tab: quick-add form, filters, the expense list and the 'By category' panel."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk

from ...reports import (
    budget_statuses,
    by_subcategory,
    category_totals,
    change_pct,
    compare_with_previous_month,
    format_change,
    in_month,
    is_year,
    matches,
)
from ...storage import Expense, format_money, format_rate, month_key, total_in
from ..forms import ExpenseDialog, MoneyFields, expense_from_fields, open_file, short_name
from ..widgets import DateField, Picker, SortableColumns, TagField, text_key
from .base import EXPENSE_COLOR, PageData, Tab


class ExpensesTab(Tab):
    label = "Expenses"
    tab_icon = "💸"
    tab_color = EXPENSE_COLOR

    def build(self) -> None:
        self.expenses: list[Expense] = []  # all of this user's expenses (from the last refresh)
        self.shown: list[Expense] = []  # what the list currently shows, in order
        self.category_filter_var = tk.StringVar()
        self.payment_filter_var = tk.StringVar()
        self.tag_filter_var = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_form()
        self._build_filters()
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")
        panes.add(self._build_list(panes), weight=3)
        panes.add(self._build_summary(panes), weight=2)

        # Give the list about 64% of the width the first time the window is shown.
        def place_sash(_event: tk.Event) -> None:
            panes.unbind("<Map>")
            panes.after_idle(lambda: panes.sashpos(0, int(panes.winfo_width() * 0.64)))
        panes.bind("<Map>", place_sash)

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Edit…", command=self.edit_selected)
        self.menu.add_command(label="Duplicate…", command=self.duplicate_selected)
        self.menu.add_command(label="Open receipt", command=self.open_receipt)
        self.menu.add_separator()
        self.menu.add_command(label="Delete", command=self.delete_selected)

    # ---------- layout ----------

    def _build_form(self) -> None:
        app = self.app
        form = ttk.LabelFrame(self, text="Add expense", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        last = app.last_rate()
        self.quick = MoneyFields(form, rate="" if last is None else format_rate(last))
        self.q_date = tk.StringVar(value=date.today().isoformat())
        self.q_category = tk.StringVar(value="Food")
        self.q_subcategory = tk.StringVar()
        self.q_payment = tk.StringVar()
        self.q_description = tk.StringVar()
        self.q_tags = tk.StringVar()
        date_field = DateField(form, self.q_date, icons=self.icons)
        widgets = [
            ("Date", date_field),
            ("Amount", self.quick.amount),
            ("Currency", self.quick.currency),
            ("Rate (S/ per US$1)", self.quick.rate),
            ("Category", Picker(form, self.icons, self.q_category, app.category_options,
                                on_new=app.add_category, new_label="New category…",
                                on_change=lambda: self.q_subcategory.set(""), width=16)),
            ("Subcategory", Picker(form, self.icons, self.q_subcategory,
                                   lambda: app.subcategory_options(self.q_category.get()), none_label="(none)",
                                   on_new=lambda n: app.add_subcategory(self.q_category.get(), n),
                                   new_label="New subcategory…", width=16)),
            ("Payment", Picker(form, self.icons, self.q_payment, app.payment_options, none_label="(none)",
                               on_new=app.add_payment_method, new_label="New payment method…", width=14)),
        ]
        self.quick.amount.configure(width=10)
        self.quick.rate.configure(width=8)
        for col, (label, widget) in enumerate(widgets):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=col, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Description").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(form, text="Tags (type, or pick a recent one)").grid(row=2, column=4, sticky="w", pady=(6, 0))
        description = ttk.Entry(form, textvariable=self.q_description)
        description.grid(row=3, column=0, columnspan=4, sticky="ew", padx=(0, 8))
        tag_field = TagField(form, self.q_tags, app.recent_tags, icons=self.icons)
        tag_field.grid(row=3, column=4, columnspan=2, sticky="ew", padx=(0, 8))
        tags = tag_field.entry
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=6, sticky="ew")
        ttk.Button(buttons, text="Add", command=self.add_expense).pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="More…", width=7, command=self.add_expense_full).pack(side="left", padx=(4, 0))
        self.quick.preview.grid(row=4, column=1, columnspan=4, sticky="w", pady=(4, 0))
        form.columnconfigure(7, weight=1)  # empty spacer: fields keep their natural width
        for widget in (date_field.entry, self.quick.amount, self.quick.rate, description, tags):
            widget.bind("<Return>", lambda _e: self.add_expense())

    def _build_filters(self) -> None:
        app = self.app
        filters = ttk.Frame(self)
        filters.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(filters, text="Filter:").pack(side="left")
        Picker(filters, self.icons, self.category_filter_var, app.category_options,
               none_label="All categories", on_change=app.refresh, width=16).pack(side="left", padx=(6, 6))
        Picker(filters, self.icons, self.payment_filter_var, app.payment_options,
               none_label="All payment methods", on_change=app.refresh, width=21).pack(side="left")
        Picker(filters, self.icons, self.tag_filter_var, self.tag_options,
               none_label="All tags", on_change=app.refresh, width=16).pack(side="left", padx=(6, 0))
        ttk.Button(filters, text="Clear filters", command=self.clear_filters).pack(side="left", padx=(6, 0))
        self.filter_note = ttk.Label(filters, style="Warning.TLabel")
        self.filter_note.pack(side="left", padx=(12, 0))

    def _build_list(self, parent: ttk.PanedWindow) -> ttk.Frame:
        left = ttk.Frame(parent)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        columns = ("date", "amount", "entered", "payment", "description", "tags")
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Category", anchor="w")
        self.tree.column("#0", width=185, stretch=False)
        for col, text, width, anchor, stretch in (
            ("date", "Date", 84, "w", False),
            ("amount", "Amount", 96, "e", False),
            ("entered", "Entered as @ rate", 132, "e", False),
            ("payment", "Payment", 92, "w", False),
            ("description", "Description", 130, "w", True),
            ("tags", "Tags", 90, "w", False),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.sort = SortableColumns(
            self.tree,
            {"#0": "Category", "date": "Date", "amount": "Amount", "entered": "Entered as @ rate",
             "payment": "Payment", "description": "Description", "tags": "Tags"},
            keys={
                "#0": lambda e: (e.category.lower(), e.subcategory.lower()),
                "date": lambda e: (e.date, e.id),
                "amount": lambda e: e.amount_in(self.app.show_in_var.get()),
                "entered": lambda e: (e.currency, e.amount),
                "payment": lambda e: text_key(e.payment_method),
                "description": lambda e: text_key(e.description),
                "tags": lambda e: text_key(" ".join(e.tags)),
            },
            default=("date", True), on_change=self.app.refresh, descending_first=("date", "amount", "entered"),
        )
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", lambda _e: self.edit_selected())
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.tree.bind("<Button-3>", self._context_menu)

        actions = ttk.Frame(left)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, command in (("Edit", self.edit_selected), ("Duplicate", self.duplicate_selected),
                              ("Open receipt", self.open_receipt), ("Delete", self.delete_selected)):
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 6))
        self.total_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.total_var, style="Bold.TLabel").pack(side="right")
        return left

    def _build_summary(self, parent: ttk.PanedWindow) -> ttk.LabelFrame:
        right = ttk.LabelFrame(parent, text="By category", padding=6)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.summary = ttk.Treeview(right, columns=("total", "share", "change", "budget"), show="tree headings")
        self.summary.heading("#0", text="Category", anchor="w")
        self.summary.column("#0", width=150)
        for col, text, width in (("total", "Total", 92), ("share", "%", 42), ("change", "vs prev.", 66),
                                 ("budget", "Budget", 54)):
            self.summary.heading(col, text=text, anchor="e")
            self.summary.column(col, width=width, anchor="e", stretch=False)
        # Tags configured later win when a row has several: budget warnings beat the grey of subcategory rows.
        self.summary.tag_configure("sub", foreground="#4b5563")
        self.summary.tag_configure("over", foreground="#c0392b")
        self.summary.tag_configure("warning", foreground="#b35c00")
        self.summary.grid(row=0, column=0, sticky="nsew")
        return right

    # ---------- filters ----------

    def clear_filters(self) -> None:
        self.category_filter_var.set("")
        self.payment_filter_var.set("")
        self.tag_filter_var.set("")
        self.app.search_var.set("")
        self.app.refresh()

    def tag_options(self) -> list[tuple[str, str, str]]:
        tags = sorted({t for e in self.expenses for t in e.tags})
        return [(t, "🏷", "#8d99ae") for t in tags]

    def _visible(self, period: str | None) -> tuple[list[Expense], str]:
        search = self.app.search_var.get().strip()
        expenses = self.expenses if search else in_month(self.expenses, period)
        notes = []
        if search:
            expenses = [e for e in expenses if matches(e, search)]
            notes.append(f"Searching all months for “{search}”")
        category = self.category_filter_var.get()
        if category:
            expenses = [e for e in expenses if e.category.lower() == category.lower()]
        payment = self.payment_filter_var.get()
        if payment:
            expenses = [e for e in expenses if e.payment_method.lower() == payment.lower()]
        tag = self.tag_filter_var.get()
        if tag:
            expenses = [e for e in expenses if tag in e.tags]
        if category or payment or tag:
            notes.append("Filtered")
        # Newest first as the tie-breaker; the clicked column decides the main order.
        expenses = sorted(expenses, key=lambda e: (e.date, e.id), reverse=True)
        return self.sort.apply(expenses), " · ".join(notes)

    # ---------- redraw ----------

    def redraw(self, data: PageData) -> None:
        self.expenses = data.expenses
        self._redraw_list(data)
        self._redraw_summary(data)

    def _redraw_list(self, data: PageData) -> None:
        show_in = data.show_in
        keep = set(self.tree.selection())
        self.shown, note = self._visible(data.period)
        self.filter_note.configure(text=note)
        self.sort.set_heading("amount", f"Amount ({show_in})")
        self.tree.delete(*self.tree.get_children())
        for e in self.shown:
            icon, color = self.app.look(e.category, e.subcategory)
            label = f"{e.category} › {e.subcategory}" if e.subcategory else e.category
            self.tree.insert("", "end", iid=e.id, **self.app.icon_text(icon, color, label), values=(
                e.date.isoformat(),
                format_money(e.amount_in(show_in), show_in),
                f"{format_money(e.amount, e.currency)} @ {format_rate(e.rate)}",
                e.payment_method,
                ("📎 " if e.receipt else "") + e.description,
                " ".join(f"#{t}" for t in e.tags),
            ))
        total, missing = total_in(self.shown, show_in)
        count = len(self.shown)
        extra = f", {missing} without rate not counted" if missing else ""
        self.total_var.set(f"Total: {format_money(total, show_in)}   ({count} expense{'s' * (count != 1)}{extra})")
        wanted = [data.select_expense] if data.select_expense else list(keep)
        wanted = [i for i in wanted if i and self.tree.exists(i)]
        if wanted:
            self.tree.selection_set(wanted)
            self.tree.see(wanted[0])

    def _redraw_summary(self, data: PageData) -> None:
        show_in, period = data.show_in, data.period
        open_rows = {iid for iid in self.summary.get_children() if self.summary.item(iid, "open")}
        self.summary.delete(*self.summary.get_children())
        period_expenses = in_month(data.expenses, period)
        totals = category_totals(data.expenses, period, show_in)
        grand = sum(totals.values(), Decimal("0"))
        comparison = compare_with_previous_month(data.expenses, period, show_in) if period else {}
        is_single_month = period is not None and not is_year(period)  # budgets are monthly
        statuses = ({s.budget.category.lower(): s for s in budget_statuses(data.expenses, data.budgets, period)}
                    if is_single_month else {})
        self.summary.heading("change", text="vs prev." if period else "")
        self.summary.heading("budget", text="Budget" if is_single_month else "")
        for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            icon, color = self.app.look(category)
            now, before = comparison.get(category, (amount, Decimal("0")))
            status = statuses.get(category.lower())
            iid = f"cat:{category}"
            self.summary.insert("", "end", iid=iid, open=iid in open_rows, **self.app.icon_text(icon, color, category),
                                tags=(status.level,) if status and status.level != "ok" else (),
                                values=(format_money(amount, show_in), f"{amount / grand * 100:.1f}" if grand else "",
                                        format_change(change_pct(now, before), new=bool(period) and before == 0),
                                        self._budget_text(status)))
            # Subcategory budgets, so each subcategory row can show its own usage
            parts = {p.subcategory.lower(): p for p in status.parts if p.subcategory} if status else {}
            subs = by_subcategory(period_expenses, category, show_in)
            if len(subs) > 1 or (len(subs) == 1 and "" not in subs):
                for sub, value in subs.items():
                    sub_icon, sub_color = self.app.look(category, sub) if sub else ("▫", color)
                    part = parts.get(sub.lower()) if sub else None
                    tags = ("sub", part.level) if part and part.level != "ok" else ("sub",)
                    self.summary.insert(iid, "end", tags=tags,
                                        **self.app.icon_text(sub_icon, sub_color, sub or "(no subcategory)"),
                                        values=(format_money(value, show_in),
                                                f"{value / grand * 100:.1f}" if grand else "", "",
                                                self._budget_text(part)))

    @staticmethod
    def _budget_text(status) -> str:
        """The 'Budget' column: share of the budget used this month."""
        if status is None:
            return ""
        if status.ratio is None:  # a 0 budget this month
            return "over" if status.spent > 0 else "—"
        return f"{status.ratio * 100:.0f}%"

    # ---------- adding ----------

    def focus_quick_add(self) -> None:
        (self.quick.amount if self.quick.rate_var.get() else self.quick.rate).focus_set()

    def set_rate(self, rate: Decimal | None) -> None:
        if rate is not None:
            self.quick.rate_var.set(format_rate(rate))

    def add_expense(self) -> None:
        try:
            expense = expense_from_fields(
                self.q_date.get(), self.quick.amount_var.get(), self.quick.currency_var.get(),
                self.quick.rate_var.get(), self.q_category.get(), self.q_description.get(),
                subcategory=self.q_subcategory.get(), payment_method=self.q_payment.get(), tags=self.q_tags.get(),
            )
            self.app.history.record(f"Add {short_name(expense)}", lambda: self.app.store.add(expense))
        except ValueError as exc:
            messagebox.showerror("Invalid expense", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        # Keep date, currency, rate, category and payment for the next entry; clear the rest.
        self.set_rate(expense.rate)
        self.quick.amount_var.set("")
        self.q_description.set("")
        self.q_tags.set("")
        self.app.expense_saved(expense, "Added")
        self.quick.amount.focus_set()

    def add_expense_full(self) -> None:
        """Open the full form (with receipt) pre-filled with what's typed in the quick form."""
        draft = Expense(
            amount=Decimal("0"), category=self.q_category.get() or "Food", subcategory=self.q_subcategory.get(),
            payment_method=self.q_payment.get(), description=self.q_description.get(),
            currency=self.quick.currency_var.get(), tags=[t for t in self.q_tags.get().split(",") if t.strip()],
        )
        dialog = ExpenseDialog(self.app, draft, duplicate=True)
        dialog.title("New expense")
        dialog.money.amount_var.set(self.quick.amount_var.get())
        dialog.money.rate_var.set(self.quick.rate_var.get())
        dialog.date_var.set(self.q_date.get())

    def reveal(self, expense: Expense) -> None:
        """Clear whatever filter would hide this (just saved) expense."""
        app = self.app
        month = month_key(expense.date)
        period = app.selected_month()
        if period and not month.startswith(period):
            app.month_var.set(month)
        if self.category_filter_var.get() and self.category_filter_var.get().lower() != expense.category.lower():
            self.category_filter_var.set("")
        if self.payment_filter_var.get() and self.payment_filter_var.get().lower() != expense.payment_method.lower():
            self.payment_filter_var.set("")
        if self.tag_filter_var.get() and self.tag_filter_var.get() not in expense.tags:
            self.tag_filter_var.set("")
        if app.search_var.get() and not matches(expense, app.search_var.get()):
            app.search_var.set("")

    # ---------- actions on the list ----------

    def _selected_expense(self) -> Expense | None:
        selected = self.tree.selection()
        if len(selected) != 1:
            self.app.set_status("Select one expense first (or double-click it).")
            return None
        return next((e for e in self.shown if e.id == selected[0]), None)

    def _on_double_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.edit_selected()

    def _context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def edit_selected(self) -> None:
        expense = self._selected_expense()
        if expense:
            ExpenseDialog(self.app, expense)

    def duplicate_selected(self) -> None:
        expense = self._selected_expense()
        if expense:
            ExpenseDialog(self.app, expense, duplicate=True)

    def open_receipt(self) -> None:
        expense = self._selected_expense()
        if not expense:
            return
        path = self.app.store.receipt_path(expense)
        if path is None:
            self.app.set_status("This expense has no receipt. Use Edit → Attach… to add one.")
            return
        open_file(path)

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.app.set_status("Select one or more expenses to delete.")
            return
        noun = "this expense" if len(selected) == 1 else f"these {len(selected)} expenses"
        if not messagebox.askyesno("Delete", f"Delete {noun}?\n\nYou can undo this with Ctrl+Z."):
            return
        if len(selected) == 1:
            one = next((e for e in self.shown if e.id == selected[0]), None)
            label = f"Delete {short_name(one)}" if one else "Delete 1 expense"
        else:
            label = f"Delete {len(selected)} expenses"
        self.app.history.record(label, lambda: [self.app.store.delete(i) for i in selected])
        self.app.set_status(f"Deleted {len(selected)} expense(s).")
        self.app.refresh()
