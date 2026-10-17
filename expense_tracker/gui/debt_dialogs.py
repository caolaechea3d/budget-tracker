"""Dialogs for debts: create/edit a debt, and record a payment."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..debts import (
    COUNTERPARTY_TYPES,
    OWE,
    OWED,
    PAYMENT_CATEGORY,
    REPAYMENT_SOURCE,
    Debt,
    DebtPayment,
    add_payment,
    counterparty_names,
    save_debt,
)
from ..storage import format_money, format_rate, parse_amount, parse_currency, parse_date, parse_rate
from .forms import RATE_MISSING, MoneyFields
from .widgets import DateField, Dialog, Picker, labeled

if TYPE_CHECKING:
    from .app import ExpenseApp


def _whole_number(text: str, label: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise ValueError(f"{label} must be a whole number")
    return int(text)


def debt_from_fields(
    *,
    direction: str,
    counterparty: str,
    counterparty_type: str,
    description: str,
    amount_text: str,
    currency_text: str,
    rate_text: str,
    start_text: str,
    has_deadline: bool,
    deadline_text: str,
    has_installments: bool,
    installments_text: str,
    payment_day_text: str,
    notes: str,
    original: Debt | None = None,
) -> Debt:
    """Validate the form and build a Debt (keeping id, payments and 'paid off' of the original)."""
    if not rate_text.strip():
        raise ValueError(RATE_MISSING)
    extra = {"id": original.id, "payments": original.payments, "settled": original.settled} if original else {}
    return Debt(
        direction=direction,
        counterparty=" ".join(counterparty.split()),
        counterparty_type=counterparty_type or "Other",
        description=description.strip(),
        amount=parse_amount(amount_text),
        currency=parse_currency(currency_text),
        rate=parse_rate(rate_text),
        start_date=parse_date(start_text.strip()),
        deadline=parse_date(deadline_text.strip()) if has_deadline else None,
        installments=_whole_number(installments_text, "Installments") if has_installments else None,
        payment_day=_whole_number(payment_day_text, "Day of the month") if has_installments else None,
        notes=notes.strip(),
        **extra,
    )


class DebtDialog(Dialog):
    def __init__(self, app: ExpenseApp, debt: Debt | None = None):
        self.app = app
        self.original = debt
        super().__init__(app, "Edit debt" if debt else "New debt")
        base = debt or Debt(counterparty="?", amount=Decimal("0"), rate=app.last_rate())
        b = self.body
        b.columnconfigure(1, weight=1)
        known = app.debts_tab.debts

        self.direction_var = tk.StringVar(value=base.direction)
        self.name_var = tk.StringVar(value=debt.counterparty if debt else "")
        self.type_var = tk.StringVar(value=base.counterparty_type)
        self.description_var = tk.StringVar(value=base.description)
        self.money = MoneyFields(b, amount="" if debt is None else f"{base.amount:.2f}", currency=base.currency,
                                 rate="" if base.rate is None else format_rate(base.rate))
        self.start_var = tk.StringVar(value=base.start_date.isoformat())
        self.has_deadline = tk.BooleanVar(value=base.deadline is not None)
        self.deadline_var = tk.StringVar(value=(base.deadline or date.today()).isoformat())
        self.has_installments = tk.BooleanVar(value=base.installments is not None)
        self.installments_var = tk.StringVar(value=str(base.installments or 12))
        self.day_var = tk.StringVar(value=str(base.payment_day or date.today().day))
        self.notes_var = tk.StringVar(value=base.notes)
        self.plan_var = tk.StringVar()

        direction = ttk.Frame(b)
        ttk.Radiobutton(direction, text="I owe money", value=OWE, variable=self.direction_var).pack(side="left")
        ttk.Radiobutton(direction, text="Someone owes me", value=OWED,
                        variable=self.direction_var).pack(side="left", padx=(12, 0))
        labeled(b, 0, "Debt", direction)
        name = ttk.Combobox(b, textvariable=self.name_var, values=counterparty_names(known), width=30)
        name.bind("<<ComboboxSelected>>", lambda _e: self._name_chosen())
        labeled(b, 1, "Who / what", name, sticky="ew")
        labeled(b, 2, "Type", Picker(b, app.icons, self.type_var, lambda: COUNTERPARTY_TYPES, width=20))
        labeled(b, 3, "What for", ttk.Entry(b, textvariable=self.description_var, width=34), sticky="ew")
        labeled(b, 4, "Total to pay back", self.money.amount)
        labeled(b, 5, "Currency", self.money.currency)
        labeled(b, 6, "Rate (S/ per US$1)", self.money.rate)
        self.money.preview.grid(row=7, column=1, sticky="w")
        labeled(b, 8, "Since", DateField(b, self.start_var, width=12, icons=app.icons))

        deadline_row = ttk.Frame(b)
        ttk.Checkbutton(deadline_row, text="Has a deadline:", variable=self.has_deadline,
                        command=self._toggle).pack(side="left")
        self.deadline_field = DateField(deadline_row, self.deadline_var, width=12, icons=app.icons)
        self.deadline_field.pack(side="left", padx=(6, 0))
        labeled(b, 9, "Deadline", deadline_row)

        plan_row = ttk.Frame(b)
        ttk.Checkbutton(plan_row, text="Monthly installments:", variable=self.has_installments,
                        command=self._toggle).pack(side="left")
        self.count_box = ttk.Spinbox(plan_row, from_=1, to=360, width=5, textvariable=self.installments_var)
        self.count_box.pack(side="left", padx=(6, 4))
        ttk.Label(plan_row, text="payments, on day").pack(side="left")
        self.day_box = ttk.Spinbox(plan_row, from_=1, to=31, width=4, textvariable=self.day_var)
        self.day_box.pack(side="left", padx=(4, 0))
        labeled(b, 10, "Installments", plan_row)
        ttk.Label(b, textvariable=self.plan_var, style="Muted.TLabel").grid(row=11, column=1, sticky="w")
        labeled(b, 12, "Notes", ttk.Entry(b, textvariable=self.notes_var, width=34), sticky="ew")
        ttk.Label(b, text="Leave both off for a debt without a deadline. Payments are recorded "
                          "afterwards with “Record payment…”.",
                  style="Muted.TLabel", wraplength=420).grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 0))

        for var in (self.money.amount_var, self.money.currency_var, self.start_var, self.installments_var,
                    self.day_var, self.deadline_var):
            var.trace_add("write", lambda *_: self._update_plan())
        self._toggle()
        self.show(name if debt is None else self.money.amount)

    def _name_chosen(self) -> None:
        """Picking a known name also picks the type used for it before."""
        match = next((d for d in self.app.debts_tab.debts if d.counterparty == self.name_var.get()), None)
        if match:
            self.type_var.set(match.counterparty_type)

    def _toggle(self) -> None:
        self.deadline_field.set_enabled(self.has_deadline.get())
        state = ["!disabled"] if self.has_installments.get() else ["disabled"]
        self.count_box.state(state)
        self.day_box.state(state)
        self._update_plan()

    def _update_plan(self) -> None:
        if not self.has_installments.get():
            self.plan_var.set("")
            return
        try:
            debt = Debt(counterparty="x", amount=parse_amount(self.money.amount_var.get()),
                        currency=parse_currency(self.money.currency_var.get()),
                        start_date=parse_date(self.start_var.get().strip()),
                        installments=_whole_number(self.installments_var.get(), "x"),
                        payment_day=_whole_number(self.day_var.get(), "x"))
        except ValueError:
            self.plan_var.set("")
            return
        dates = debt.schedule()
        short_months = (" · on the last day of every month" if debt.payment_day == 31
                        else " · shorter months: their last day" if debt.payment_day > 28 else "")
        self.plan_var.set(f"≈ {format_money(debt.installment_amount, debt.currency)} per month · "
                          f"first {dates[0]:%d %b %Y} · last {dates[-1]:%d %b %Y}{short_months}")

    def on_ok(self) -> bool:
        try:
            debt = debt_from_fields(
                direction=self.direction_var.get(), counterparty=self.name_var.get(),
                counterparty_type=self.type_var.get(), description=self.description_var.get(),
                amount_text=self.money.amount_var.get(), currency_text=self.money.currency_var.get(),
                rate_text=self.money.rate_var.get(), start_text=self.start_var.get(),
                has_deadline=self.has_deadline.get(), deadline_text=self.deadline_var.get(),
                has_installments=self.has_installments.get(), installments_text=self.installments_var.get(),
                payment_day_text=self.day_var.get(), notes=self.notes_var.get(), original=self.original,
            )
            verb = "Edit" if self.original else "Add"
            self.app.history.record(f"{verb} debt with {debt.counterparty}",
                                    lambda: save_debt(self.app.store, debt))
        except ValueError as exc:
            messagebox.showerror("Debt", str(exc), parent=self)
            return False
        self.app.debt_saved(debt.id, f"{'Updated' if self.original else 'Added'} debt with {debt.counterparty}: "
                                     f"{format_money(debt.amount, debt.currency)}")
        return True


class PaymentDialog(Dialog):
    """Record a payment on a debt (or a repayment someone made to me)."""

    def __init__(self, app: ExpenseApp, debt: Debt):
        self.app = app
        self.debt = debt
        owe = debt.direction == OWE
        super().__init__(app, f"{'Payment to' if owe else 'Repayment from'} {debt.counterparty}",
                         ok_text="Record payment")
        b = self.body
        b.columnconfigure(1, weight=1)
        due = debt.next_due()
        suggested = due[1] if due else debt.remaining
        last = app.last_rate()
        self.date_var = tk.StringVar(value=date.today().isoformat())
        self.amount_var = tk.StringVar(value=f"{suggested:.2f}" if suggested else "")
        self.rate_var = tk.StringVar(value="" if last is None else format_rate(last))
        self.note_var = tk.StringVar()
        self.record_var = tk.BooleanVar(value=False)

        summary = f"Remaining {format_money(debt.remaining, debt.currency)} of {format_money(debt.amount, debt.currency)}"
        if due:
            summary += f"\nNext payment {format_money(due[1], debt.currency)} on {due[0]:%d %b %Y}"
        ttk.Label(b, text=summary, style="Bold.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        labeled(b, 1, "Date", DateField(b, self.date_var, width=12, icons=app.icons))
        amount = labeled(b, 2, f"Amount ({debt.currency})",
                         ttk.Entry(b, textvariable=self.amount_var, width=14, justify="right"))
        labeled(b, 3, "Rate (S/ per US$1)", ttk.Entry(b, textvariable=self.rate_var, width=14, justify="right"))
        labeled(b, 4, "Note", ttk.Entry(b, textvariable=self.note_var, width=30), sticky="ew")
        what = (f"an expense (category “{PAYMENT_CATEGORY.name}”)" if owe
                else f"income (source “{REPAYMENT_SOURCE.name}”)")
        ttk.Checkbutton(b, text=f"Also add it as {what}", variable=self.record_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        hint = ("Tick this when the money isn't already in your expenses — e.g. paying back a loan.\n"
                "Leave it off for card installments whose purchase you already recorded."
                if owe else "Tick this to count the money you got back in your income.")
        ttk.Label(b, text=hint, style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w")
        self.show(amount)

    def on_ok(self) -> bool:
        debt = self.debt
        try:
            amount = parse_amount(self.amount_var.get())
            when = parse_date(self.date_var.get().strip())
            rate = parse_rate(self.rate_var.get()) if self.rate_var.get().strip() else None
            if self.record_var.get() and rate is None:
                raise ValueError(RATE_MISSING)
        except ValueError as exc:
            messagebox.showerror("Payment", str(exc), parent=self)
            return False
        if debt.remaining and amount > debt.remaining and not messagebox.askyesno(
            "Payment", f"That's more than what's left ({format_money(debt.remaining, debt.currency)}).\n"
                       "Record it anyway?", parent=self):
            return False
        payment = DebtPayment(amount, when, self.note_var.get().strip(), rate)
        label = f"{'Payment to' if debt.direction == OWE else 'Repayment from'} {debt.counterparty}"
        try:
            self.app.history.record(label, lambda: add_payment(self.app.store, debt.id, payment,
                                                               also_record=self.record_var.get()))
        except ValueError as exc:
            messagebox.showerror("Payment", str(exc), parent=self)
            return False
        left = max(Decimal("0"), debt.remaining - amount)
        self.app.debt_saved(debt.id, f"{label}: {format_money(amount, debt.currency)} · "
                                     f"{format_money(left, debt.currency)} left")
        return True
