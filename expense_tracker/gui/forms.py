"""Validation helpers and the add/edit dialogs."""

from __future__ import annotations

import os
import tkinter as tk
from datetime import date
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from ..reports import suggest_budget_category
from ..storage import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    Expense,
    Income,
    RecurringExpense,
    add_months,
    format_money,
    format_rate,
    month_key,
    parse_amount,
    parse_budget_amount,
    parse_currency,
    parse_date,
    parse_rate,
    parse_tags,
)
from .widgets import DateField, Dialog, MonthChoices, Picker, TagField, labeled, month_label

if TYPE_CHECKING:
    from .app import ExpenseApp

RATE_MISSING = "Enter the exchange rate: how many soles (PEN) one US dollar costs, e.g. 3.75"
RECEIPT_TYPES = [("Images and PDFs", "*.png *.jpg *.jpeg *.gif *.webp *.pdf"), ("All files", "*.*")]


def _required_rate(rate_text: str) -> Decimal:
    if not rate_text.strip():
        raise ValueError(RATE_MISSING)
    return parse_rate(rate_text)


def expense_from_fields(
    date_text: str,
    amount_text: str,
    currency_text: str,
    rate_text: str,
    category_text: str,
    description_text: str,
    expense_id: str | None = None,
    *,
    subcategory: str = "",
    payment_method: str = "",
    tags: str | list[str] = "",
) -> Expense:
    """Validate form input and build an Expense (raises ValueError with a readable message)."""
    amount = parse_amount(amount_text)
    rate = _required_rate(rate_text)
    category = category_text.strip()
    if not category:
        raise ValueError("Category is required")
    expense = Expense(
        amount=amount,
        currency=parse_currency(currency_text),
        rate=rate,
        category=category[0].upper() + category[1:],
        subcategory=subcategory.strip(),
        payment_method=payment_method.strip(),
        tags=parse_tags(tags),
        description=description_text.strip(),
        date=parse_date(date_text.strip()),
    )
    if expense_id:
        expense.id = expense_id
    return expense


def income_from_fields(
    date_text: str, amount_text: str, currency_text: str, rate_text: str, source: str, description: str,
    income_id: str | None = None,
) -> Income:
    if not source.strip():
        raise ValueError("Choose where the income comes from")
    income = Income(
        amount=parse_amount(amount_text),
        currency=parse_currency(currency_text),
        rate=_required_rate(rate_text),
        source=source.strip(),
        description=description.strip(),
        date=parse_date(date_text.strip()),
    )
    if income_id:
        income.id = income_id
    return income


def preview_text(amount_text: str, currency_text: str, rate_text: str) -> str:
    """'= S/ 37.50  /  US$ 10.00' for valid input, otherwise an empty string."""
    try:
        e = Expense(
            amount=parse_amount(amount_text),
            currency=parse_currency(currency_text),
            rate=parse_rate(rate_text),
            category="",
        )
    except ValueError:
        return ""
    return f"= {format_money(e.amount_pen, 'PEN')}  /  {format_money(e.amount_usd, 'USD')}"


def short_name(record: Expense | Income) -> str:
    """A short quoted name for undo labels: the description, or else the (sub)category/source."""
    name = record.description or getattr(record, "subcategory", "") or getattr(record, "category", "") \
        or getattr(record, "source", "")
    return f"“{name[:28]}…”" if len(name) > 28 else f"“{name}”"


def open_file(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(path)  # Windows
    else:
        import subprocess
        import sys
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class MoneyFields:
    """Amount + currency + rate entries with a live 'S/ … / US$ …' preview line."""

    def __init__(self, parent: ttk.Frame, amount: str = "", currency: str = DEFAULT_CURRENCY, rate: str = ""):
        self.amount_var = tk.StringVar(value=amount)
        self.currency_var = tk.StringVar(value=currency)
        self.rate_var = tk.StringVar(value=rate)
        self.preview_var = tk.StringVar()
        self.amount = ttk.Entry(parent, textvariable=self.amount_var, width=14, justify="right")
        self.currency = ttk.Combobox(parent, textvariable=self.currency_var, values=CURRENCIES, width=7, state="readonly")
        self.rate = ttk.Entry(parent, textvariable=self.rate_var, width=14, justify="right")
        self.preview = ttk.Label(parent, textvariable=self.preview_var, style="Muted.TLabel")
        for var in (self.amount_var, self.currency_var, self.rate_var):
            var.trace_add("write", lambda *_: self.update_preview())
        self.update_preview()

    def update_preview(self) -> None:
        self.preview_var.set(preview_text(self.amount_var.get(), self.currency_var.get(), self.rate_var.get()))


def _rate_text(rate: Decimal | None) -> str:
    return "" if rate is None else format_rate(rate)


# ---------- expense ----------

class ExpenseDialog(Dialog):
    """Add, edit or duplicate an expense, including tags and a receipt."""

    def __init__(self, app: ExpenseApp, expense: Expense | None = None, duplicate: bool = False):
        self.app = app
        self.original = None if duplicate else expense
        title = "Edit expense" if self.original else ("Duplicate expense" if duplicate else "New expense")
        super().__init__(app, title)
        base = expense or Expense(amount=Decimal("0"), category="Food", rate=app.last_rate())
        self.pending_receipt: Path | None = None
        self.remove_receipt = False
        b = self.body
        b.columnconfigure(1, weight=1)

        self.date_var = tk.StringVar(value=(date.today() if duplicate else base.date).isoformat())
        self.money = MoneyFields(
            b, amount="" if expense is None else f"{base.amount:.2f}", currency=base.currency, rate=_rate_text(base.rate)
        )
        self.category_var = tk.StringVar(value=base.category)
        self.subcategory_var = tk.StringVar(value=base.subcategory)
        self.payment_var = tk.StringVar(value=base.payment_method)
        self.description_var = tk.StringVar(value=base.description)
        self.tags_var = tk.StringVar(value=", ".join(base.tags))

        labeled(b, 0, "Date", DateField(b, self.date_var, width=12, icons=app.icons))
        labeled(b, 1, "Amount", self.money.amount)
        labeled(b, 2, "Currency", self.money.currency)
        labeled(b, 3, "Rate (S/ per US$1)", self.money.rate)
        self.money.preview.grid(row=4, column=1, sticky="w")
        labeled(b, 5, "Category", Picker(
            b, app.icons, self.category_var, app.category_options, on_new=app.add_category,
            new_label="New category…", on_change=lambda: self.subcategory_var.set(""), width=22,
        ), sticky="ew")
        labeled(b, 6, "Subcategory", Picker(
            b, app.icons, self.subcategory_var, lambda: app.subcategory_options(self.category_var.get()),
            none_label="(none)", on_new=lambda n: app.add_subcategory(self.category_var.get(), n),
            new_label="New subcategory…", width=22,
        ), sticky="ew")
        labeled(b, 7, "Payment method", Picker(
            b, app.icons, self.payment_var, app.payment_options, none_label="(none)",
            on_new=app.add_payment_method, new_label="New payment method…", width=22,
        ), sticky="ew")
        labeled(b, 8, "Description", ttk.Entry(b, textvariable=self.description_var, width=38), sticky="ew")
        labeled(b, 9, "Tags", TagField(b, self.tags_var, app.recent_tags, width=34, icons=app.icons), sticky="ew")

        receipt_row = ttk.Frame(b)
        self.receipt_label = ttk.Label(receipt_row, style="Muted.TLabel")
        self.receipt_label.pack(side="left")
        ttk.Button(receipt_row, text="Attach…", command=self._choose_receipt).pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(receipt_row, text="Open", command=self._open_receipt)
        self.open_button.pack(side="left", padx=(4, 0))
        self.clear_button = ttk.Button(receipt_row, text="Remove", command=self._clear_receipt)
        self.clear_button.pack(side="left", padx=(4, 0))
        labeled(b, 10, "Receipt", receipt_row, sticky="ew")
        self._update_receipt_row()

        if self.original and self.original.rate is None:
            ttk.Label(b, text="This expense has no exchange rate yet — add one to see it in USD.",
                      style="Warning.TLabel").grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 0))

        focus = self.money.rate if not self.money.rate_var.get() else self.money.amount
        self.show(focus)

    def _current_receipt_name(self) -> str | None:
        if self.pending_receipt:
            return self.pending_receipt.name
        if self.original and self.original.receipt and not self.remove_receipt:
            return self.original.receipt
        return None

    def _update_receipt_row(self) -> None:
        name = self._current_receipt_name()
        self.receipt_label.configure(text=f"📎 {name}" if name else "No receipt")
        state = "normal" if name else "disabled"
        self.open_button.configure(state=state)
        self.clear_button.configure(state=state)

    def _choose_receipt(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Attach receipt", filetypes=RECEIPT_TYPES)
        if path:
            self.pending_receipt = Path(path)
            self._update_receipt_row()

    def _open_receipt(self) -> None:
        if self.pending_receipt:
            open_file(self.pending_receipt)
        elif self.original and (path := self.app.store.receipt_path(self.original)):
            open_file(path)
        else:
            messagebox.showwarning("Receipt", "The receipt file can't be found.", parent=self)

    def _clear_receipt(self) -> None:
        self.pending_receipt = None
        self.remove_receipt = True
        self._update_receipt_row()

    def on_ok(self) -> bool:
        try:
            expense = expense_from_fields(
                self.date_var.get(), self.money.amount_var.get(), self.money.currency_var.get(),
                self.money.rate_var.get(), self.category_var.get(), self.description_var.get(),
                expense_id=self.original.id if self.original else None,
                subcategory=self.subcategory_var.get(), payment_method=self.payment_var.get(),
                tags=self.tags_var.get(),
            )
            store = self.app.store

            def save() -> Expense:
                saved = expense
                if self.original:
                    saved.receipt = self.original.receipt
                    saved.recurring_id = self.original.recurring_id
                    if not store.update(saved):
                        raise ValueError("This expense no longer exists (was it deleted?)")
                    if self.remove_receipt and not self.pending_receipt:
                        store.remove_receipt(saved.id)
                else:
                    store.add(saved)
                if self.pending_receipt:
                    saved = store.attach_receipt(saved.id, self.pending_receipt)
                return saved

            verb = "Edit" if self.original else "Add"
            expense = self.app.history.record(f"{verb} {short_name(expense)}", save)
        except ValueError as exc:
            messagebox.showerror("Invalid expense", str(exc), parent=self)
            return False
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return False
        self.app.expense_saved(expense, "Updated" if self.original else "Added")
        return True


# ---------- income ----------

class IncomeDialog(Dialog):
    def __init__(self, app: ExpenseApp, income: Income | None = None):
        self.app = app
        self.original = income
        super().__init__(app, "Edit income" if income else "New income")
        base = income or Income(amount=Decimal("0"), source="Salary", rate=app.last_rate())
        b = self.body
        b.columnconfigure(1, weight=1)
        self.date_var = tk.StringVar(value=base.date.isoformat())
        self.money = MoneyFields(
            b, amount="" if income is None else f"{base.amount:.2f}", currency=base.currency, rate=_rate_text(base.rate)
        )
        self.source_var = tk.StringVar(value=base.source)
        self.description_var = tk.StringVar(value=base.description)
        labeled(b, 0, "Date", DateField(b, self.date_var, width=12, icons=app.icons))
        labeled(b, 1, "Amount", self.money.amount)
        labeled(b, 2, "Currency", self.money.currency)
        labeled(b, 3, "Rate (S/ per US$1)", self.money.rate)
        self.money.preview.grid(row=4, column=1, sticky="w")
        labeled(b, 5, "Source", Picker(
            b, app.icons, self.source_var, app.source_options, on_new=app.add_income_source,
            new_label="New income source…", width=22,
        ), sticky="ew")
        labeled(b, 6, "Description", ttk.Entry(b, textvariable=self.description_var, width=38), sticky="ew")
        self.show(self.money.amount if self.money.rate_var.get() else self.money.rate)

    def on_ok(self) -> bool:
        try:
            income = income_from_fields(
                self.date_var.get(), self.money.amount_var.get(), self.money.currency_var.get(),
                self.money.rate_var.get(), self.source_var.get(), self.description_var.get(),
                income_id=self.original.id if self.original else None,
            )
            store = self.app.store

            def save() -> None:
                if self.original:
                    if not store.update_income(income):
                        raise ValueError("This income no longer exists (was it deleted?)")
                else:
                    store.add_income(income)

            verb = "Edit" if self.original else "Add"
            self.app.history.record(f"{verb} income {short_name(income)}", save)
        except ValueError as exc:
            messagebox.showerror("Invalid income", str(exc), parent=self)
            return False
        self.app.income_saved(income, "Updated" if self.original else "Added")
        return True


# ---------- recurring ----------

class RecurringDialog(Dialog):
    def __init__(self, app: ExpenseApp, item: RecurringExpense | None = None):
        self.app = app
        self.original = item
        super().__init__(app, "Edit recurring expense" if item else "New recurring expense")
        base = item or RecurringExpense(amount=Decimal("0"), category="Housing", subcategory="Rent")
        b = self.body
        b.columnconfigure(1, weight=1)
        self.amount_var = tk.StringVar(value="" if item is None else f"{base.amount:.2f}")
        self.currency_var = tk.StringVar(value=base.currency)
        self.category_var = tk.StringVar(value=base.category)
        self.subcategory_var = tk.StringVar(value=base.subcategory)
        self.payment_var = tk.StringVar(value=base.payment_method)
        self.description_var = tk.StringVar(value=base.description)
        self.day_var = tk.StringVar(value=str(base.day))
        self.start_var = tk.StringVar(value=base.next_month() if item else base.start_month)
        self.active_var = tk.BooleanVar(value=base.active)

        amount = labeled(b, 0, "Amount", ttk.Entry(b, textvariable=self.amount_var, width=14, justify="right"))
        labeled(b, 1, "Currency", ttk.Combobox(b, textvariable=self.currency_var, values=CURRENCIES, width=7, state="readonly"))
        labeled(b, 2, "Category", Picker(
            b, app.icons, self.category_var, app.category_options, on_new=app.add_category,
            new_label="New category…", on_change=lambda: self.subcategory_var.set(""), width=22,
        ), sticky="ew")
        labeled(b, 3, "Subcategory", Picker(
            b, app.icons, self.subcategory_var, lambda: app.subcategory_options(self.category_var.get()),
            none_label="(none)", on_new=lambda n: app.add_subcategory(self.category_var.get(), n),
            new_label="New subcategory…", width=22,
        ), sticky="ew")
        labeled(b, 4, "Payment method", Picker(
            b, app.icons, self.payment_var, app.payment_options, none_label="(none)",
            on_new=app.add_payment_method, new_label="New payment method…", width=22,
        ), sticky="ew")
        labeled(b, 5, "Description", ttk.Entry(b, textvariable=self.description_var, width=34), sticky="ew")
        day_row = ttk.Frame(b)
        ttk.Spinbox(day_row, from_=1, to=31, textvariable=self.day_var, width=6).pack(side="left")
        day_hint = ttk.Label(day_row, style="Muted.TLabel")
        day_hint.pack(side="left", padx=(8, 0))
        labeled(b, 6, "Day of the month", day_row)

        def explain_day(*_) -> None:
            day = self.day_var.get().strip()
            if day == "31":
                day_hint.configure(text="= the last day of every month")
            elif day in ("29", "30"):
                day_hint.configure(text="shorter months: their last day (e.g. 28 Feb)")
            else:
                day_hint.configure(text="")
        self.day_var.trace_add("write", explain_day)
        explain_day()
        this_month = month_key(date.today())
        months = [add_months(this_month, n) for n in range(-12, 13)]
        month_box = labeled(b, 7, "Next month to add", ttk.Combobox(b, width=16, state="readonly"))
        MonthChoices(month_box, self.start_var).set_months(months)
        labeled(b, 8, "", ttk.Checkbutton(b, text="Active", variable=self.active_var))
        ttk.Label(b, text="The app asks you to add it each month once its day arrives.\n"
                          "The exchange rate is asked for at that moment.",
                  style="Muted.TLabel").grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.show(amount)

    def on_ok(self) -> bool:
        try:
            start = self.start_var.get().strip()
            add_months(start, 0)  # validates YYYY-MM
            if len(start) != 7:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid recurring expense", "Next month must look like 2026-10", parent=self)
            return False
        try:
            if not self.category_var.get().strip():
                raise ValueError("Category is required")
            item = RecurringExpense(
                amount=parse_amount(self.amount_var.get()),
                currency=parse_currency(self.currency_var.get()),
                category=self.category_var.get().strip(),
                subcategory=self.subcategory_var.get().strip(),
                payment_method=self.payment_var.get().strip(),
                description=self.description_var.get().strip(),
                day=int(self.day_var.get()) if self.day_var.get().strip().isdigit() else 0,
                start_month=start,
                handled_through=add_months(start, -1),
                active=self.active_var.get(),
            )
            if self.original:
                item.id = self.original.id
            self.app.store.save_recurring(item)
        except ValueError as exc:
            messagebox.showerror("Invalid recurring expense", str(exc), parent=self)
            return False
        self.app.recurring_saved(item)
        return True


class DueRecurringDialog(Dialog):
    """Asks which due recurring expenses to add now."""

    def __init__(self, app: ExpenseApp, due: list[tuple[RecurringExpense, str]]):
        self.app = app
        self.due = due
        super().__init__(app, "Recurring expenses due", ok_text="Add selected", cancel_text="Remind me later")
        b = self.body
        ttk.Label(b, text="These recurring expenses are due. Unticked ones are skipped for that month.",
                  wraplength=460).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.checks: list[tk.BooleanVar] = []
        for row, (item, month) in enumerate(due, start=1):
            var = tk.BooleanVar(value=True)
            self.checks.append(var)
            icon, color = app.look(item.category, item.subcategory)
            image = app.icons.get(icon, color)
            label = item.description or item.subcategory or item.category
            ttk.Checkbutton(
                b, variable=var, image=image or "", compound="left",
                text=f" {label}" if image else app.icons.text(icon, label),
            ).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(b, text=item.occurrence_date(month).isoformat()).grid(row=row, column=1, sticky="w", padx=12)
            ttk.Label(b, text=format_money(item.amount, item.currency)).grid(row=row, column=2, sticky="e")
        self.rate_var = tk.StringVar(value=_rate_text(app.last_rate()))
        rate_row = ttk.Frame(b)
        rate_row.grid(row=len(due) + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(rate_row, text="Exchange rate today (S/ per US$1)").pack(side="left")
        rate = ttk.Entry(rate_row, textvariable=self.rate_var, width=10, justify="right")
        rate.pack(side="left", padx=(8, 0))
        self.show(rate)

    def on_ok(self) -> bool:
        try:
            rate = _required_rate(self.rate_var.get())
        except ValueError as exc:
            messagebox.showerror("Exchange rate", str(exc), parent=self)
            return False
        add, skip = [], []
        for (item, month), var in zip(self.due, self.checks):
            (add if var.get() else skip).append((item.id, month))
        created = self.app.history.record(
            "Add recurring expenses" if add else "Skip recurring expenses",
            lambda: self.app.store.apply_recurring(add, skip, rate),
        )
        self.app.recurring_applied(created, len(skip))
        return True


# ---------- budget ----------

class BudgetDialog(Dialog):
    """Set a category's usual monthly budget, or a different amount for one month (0 allowed)."""

    EVERY_MONTH, ONE_MONTH = "every", "one"

    def __init__(self, app: ExpenseApp, category: str = ""):
        self.app = app
        self.month = app.focus_month()  # the month shown in the Budgets tab
        super().__init__(app, "Monthly budget")
        suggested_by_spending = False
        if not category:  # "Set budget…": start from a sensible category instead of none
            category, suggested_by_spending = suggest_budget_category(
                [c.name for c in app.categories], app.expenses_tab.expenses, app.store.budgets(), self.month)
        b = self.body
        self.category_var = tk.StringVar(value=category)
        self.amount_var = tk.StringVar()
        self.currency_var = tk.StringVar(value=DEFAULT_CURRENCY)
        self.scope_var = tk.StringVar(value=self.EVERY_MONTH)
        self.hint_var = tk.StringVar()
        self.suggested_by_spending = suggested_by_spending

        labeled(b, 0, "Category", Picker(
            b, app.icons, self.category_var, app.category_options, on_change=self._load_existing, width=22,
        ), sticky="ew")
        amount = labeled(b, 1, "Budget", ttk.Entry(b, textvariable=self.amount_var, width=14, justify="right"))
        labeled(b, 2, "Currency", ttk.Combobox(b, textvariable=self.currency_var, values=CURRENCIES, width=7,
                                               state="readonly"))
        scope = ttk.Frame(b)
        ttk.Radiobutton(scope, text="Every month", value=self.EVERY_MONTH, variable=self.scope_var,
                        command=self._scope_changed).pack(anchor="w")
        ttk.Radiobutton(scope, text=f"Only {month_label(self.month)}", value=self.ONE_MONTH,
                        variable=self.scope_var, command=self._scope_changed).pack(anchor="w")
        labeled(b, 3, "Applies to", scope)
        ttk.Label(b, textvariable=self.hint_var, style="Muted.TLabel", justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._load_existing()
        self.show(amount)

    def _budget(self):
        name = self.category_var.get().lower()
        return next((bud for key, bud in self.app.store.budgets().items() if key.lower() == name), None)

    def _load_existing(self) -> None:
        """Show the category's current budget; open on "Only <month>" if that month has its own amount."""
        budget = self._budget()
        if budget:
            self.currency_var.set(budget.currency)
        self.scope_var.set(self.ONE_MONTH if budget and self.month in budget.months else self.EVERY_MONTH)
        self._scope_changed()

    def _scope_changed(self) -> None:
        budget = self._budget()
        month = month_label(self.month)
        if self.scope_var.get() == self.ONE_MONTH:
            value = budget.months.get(self.month) if budget else None
            hint = (f"Use 0 for a month with nothing planned (e.g. a payment that isn't due in {month}).\n"
                    f"Leave it empty to use the usual amount again in {month}.")
        else:
            value = budget.amount if budget else None
            hint = "0 is allowed. Leave it empty to remove this budget from every month."
        self.amount_var.set("" if value is None else f"{value:.2f}")
        if budget:
            usual = f"Usually {format_money(budget.amount, budget.currency)} a month"
            exceptions = len(budget.months)
            if exceptions:
                usual += f" · {exceptions} month{'s' * (exceptions != 1)} with a different amount"
            hint = f"{usual}.\n{hint}"
        if self.suggested_by_spending:
            hint = f"Suggested: your biggest spending this month without a budget.\n{hint}"
        self.hint_var.set(hint)

    def on_ok(self) -> bool:
        category = self.category_var.get().strip()
        one_month = self.scope_var.get() == self.ONE_MONTH
        try:
            if not category:
                raise ValueError("Choose a category")
            text = self.amount_var.get().strip()
            amount = parse_budget_amount(text) if text else None
            self.app.store.set_budget(category, amount, parse_currency(self.currency_var.get()),
                                      month=self.month if one_month else None)
        except ValueError as exc:
            messagebox.showerror("Invalid budget", str(exc), parent=self)
            return False
        self.app.budgets_changed(category, amount is not None, self.month if one_month else None)
        return True

