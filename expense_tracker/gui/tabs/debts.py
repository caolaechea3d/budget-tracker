"""Debts tab: what I owe and what others owe me, with deadlines, installments and payments."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk

from ...debts import (
    DIRECTION_LABELS,
    OWE,
    OWED,
    STATUS_LABELS,
    STATUS_ORDER,
    Debt,
    counterparty_look,
    delete_debt,
    delete_payment,
    save_debt,
    summarize,
)
from ...storage import format_money
from ..debt_dialogs import DebtDialog, PaymentDialog
from ..widgets import SortableColumns, text_key
from .base import PageData, Tab

STATUS_COLORS = {"overdue": "#c0392b", "due_soon": "#b35c00", "paid": "#9ca3af"}
ALL, ONLY_OWE, ONLY_OWED = "all", OWE, OWED


def progress_bar(ratio: Decimal, width: int = 10) -> str:
    filled = round(float(ratio) * width)
    return "■" * filled + "□" * (width - filled) + f"  {float(ratio) * 100:.0f}%"


class DebtsTab(Tab):
    label = "Debts"
    tab_icon = "🤝"
    tab_color = "#6d597a"

    def build(self) -> None:
        self.debts: list[Debt] = []
        self.shown: list[Debt] = []
        self.show_var = tk.StringVar(value=ALL)
        self.show_paid_var = tk.BooleanVar(value=False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_summary()
        self._build_toolbar()
        panes = ttk.PanedWindow(self, orient="vertical")
        panes.grid(row=2, column=0, sticky="nsew")
        panes.add(self._build_list(panes), weight=3)
        panes.add(self._build_details(panes), weight=2)

    # ---------- layout ----------

    def _build_summary(self) -> None:
        cards = ttk.Frame(self)
        cards.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.card_vars = {}
        for i, (key, title, style) in enumerate((
            ("owe", "I owe", "Expense.CardValue.TLabel"),
            ("owed", "Owed to me", "Income.CardValue.TLabel"),
            ("overdue", "Overdue", "CardValue.TLabel"),
            ("next", "Next payment", "CardValue.TLabel"),
        )):
            card = ttk.Frame(cards, padding=(0 if i == 0 else 28, 0, 0, 0))
            card.grid(row=0, column=i, sticky="w")
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
            var = tk.StringVar()
            label = ttk.Label(card, textvariable=var, style=style)
            label.pack(anchor="w")
            self.card_vars[key] = (var, label)
        ttk.Button(cards, text="New debt…", command=lambda: DebtDialog(self.app)).grid(row=0, column=5, sticky="e")
        cards.columnconfigure(4, weight=1)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="Show:").pack(side="left")
        for value, text in ((ALL, "All"), (ONLY_OWE, "I owe"), (ONLY_OWED, "Owed to me")):
            ttk.Radiobutton(bar, text=text, value=value, variable=self.show_var,
                            command=self.app.refresh).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(bar, text="Show paid off", variable=self.show_paid_var,
                        command=self.app.refresh).pack(side="left", padx=(16, 0))

    def _build_list(self, parent: ttk.PanedWindow) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("kind", "description", "total", "paid", "remaining", "progress", "due", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.column("#0", width=170, stretch=False)
        for col, width, anchor, stretch in (
            ("kind", 70, "w", False), ("description", 150, "w", True), ("total", 100, "e", False),
            ("paid", 95, "e", False), ("remaining", 100, "e", False), ("progress", 125, "w", False),
            ("due", 175, "w", False), ("status", 85, "w", False),
        ):
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
            self.tree.heading(col, anchor=anchor)
        self.tree.heading("#0", anchor="w")
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, foreground=color)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        today = date.today()
        self.sort = SortableColumns(
            self.tree,
            {"#0": "Who / what", "kind": "Debt", "description": "What for", "total": "Total", "paid": "Paid",
             "remaining": "Remaining", "progress": "Progress", "due": "Next payment / deadline", "status": "Status"},
            keys={
                "#0": lambda d: d.counterparty.lower(),
                "kind": lambda d: d.direction,
                "description": lambda d: text_key(d.description),
                "total": lambda d: d.amount_in(self.app.show_in_var.get()),
                "paid": lambda d: d.amount_in(self.app.show_in_var.get(), d.paid),
                "remaining": lambda d: d.amount_in(self.app.show_in_var.get(), d.remaining),
                "progress": lambda d: d.progress,
                "due": lambda d: (d.next_due() or (None,))[0],
                "status": lambda d: (STATUS_ORDER.index(d.status(today)), (d.next_due() or (date.max,))[0]),
            },
            default=("status", False), on_change=self.app.refresh,
            descending_first=("total", "paid", "remaining", "progress"),
        )
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_details())
        self.tree.bind("<Double-1>", lambda e: self._edit_at(e.y))

        actions = ttk.Frame(frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, command in (("Record payment…", self.record_payment), ("Edit…", self.edit_selected),
                              ("Delete", self.delete_selected)):
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 6))
        self.settle_button = ttk.Button(actions, text="Mark as paid off", command=self.toggle_settled)
        self.settle_button.pack(side="left")
        return frame

    def _build_details(self, parent: ttk.PanedWindow) -> ttk.LabelFrame:
        box = ttk.LabelFrame(parent, text="Details", padding=8)
        box.columnconfigure(1, weight=1)
        box.rowconfigure(0, weight=1)
        self.info_label = ttk.Label(box, justify="left", anchor="nw", wraplength=330)
        self.info_label.grid(row=0, column=0, sticky="nw", padx=(0, 16))
        right = ttk.Frame(box)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.payments = ttk.Treeview(right, columns=("date", "amount", "note", "linked"), show="headings", height=5)
        for col, text, width, anchor, stretch in (("date", "Date", 90, "w", False), ("amount", "Amount", 100, "e", False),
                                                  ("note", "Note", 160, "w", True),
                                                  ("linked", "Also recorded as", 130, "w", False)):
            self.payments.heading(col, text=text, anchor=anchor)
            self.payments.column(col, width=width, anchor=anchor, stretch=stretch)
        self.payments.grid(row=0, column=0, sticky="nsew")
        self.payments.bind("<Delete>", lambda _e: self.delete_payment())
        ttk.Button(right, text="Delete payment", command=self.delete_payment).grid(row=1, column=0, sticky="w",
                                                                                  pady=(6, 0))
        return box

    # ---------- redraw ----------

    def redraw(self, data: PageData) -> None:
        self.debts = data.debts
        show_in = data.show_in
        today = date.today()
        summary = summarize(self.debts, show_in, today)
        self.card_vars["owe"][0].set(format_money(summary.i_owe, show_in))
        self.card_vars["owed"][0].set(format_money(summary.owed_to_me, show_in))
        overdue_var, overdue_label = self.card_vars["overdue"]
        overdue_var.set(str(summary.overdue) + (f"  ·  {summary.due_soon} due soon" if summary.due_soon else ""))
        overdue_label.configure(style="Expense.CardValue.TLabel" if summary.overdue else "CardValue.TLabel")
        if summary.next_due:
            debt, when, amount = summary.next_due
            self.card_vars["next"][0].set(f"{format_money(amount, debt.currency)} · {debt.counterparty} · {when:%d %b}")
        else:
            self.card_vars["next"][0].set("—")
        problems = [f"{summary.overdue} overdue"] if summary.overdue else []
        problems += [f"{summary.due_soon} due soon"] if summary.due_soon else []
        image = self.icons.get(self.tab_icon, self.tab_color)
        label = f"{self.label} ({', '.join(problems)})" if problems else self.label
        self.app.notebook.tab(self, text=f" {label}" if image else self.icons.text(self.tab_icon, label))

        keep = self.tree.selection()
        visible = [d for d in self.debts
                   if (self.show_var.get() == ALL or d.direction == self.show_var.get())
                   and (self.show_paid_var.get() or not d.is_closed)]
        self.shown = self.sort.apply(sorted(visible, key=lambda d: d.start_date, reverse=True))
        self.tree.delete(*self.tree.get_children())
        for d in self.shown:
            status = d.status(today)
            icon, color = counterparty_look(d.counterparty_type)
            due = d.next_due()
            if due:
                due_text = f"{due[0]:%d %b %Y} · {format_money(due[1], d.currency)}"
            elif d.is_closed:
                due_text = "—"
            else:
                due_text = "No deadline"
            self.tree.insert("", "end", iid=d.id, **self.app.icon_text(icon, color, d.counterparty),
                             tags=(status,) if status in STATUS_COLORS else (),
                             values=(DIRECTION_LABELS[d.direction], d.description,
                                     format_money(d.amount, d.currency), format_money(d.paid, d.currency),
                                     format_money(d.remaining, d.currency), progress_bar(d.progress), due_text,
                                     STATUS_LABELS[status]))
        wanted = data.select_debt or (keep[0] if keep else None)
        if wanted and self.tree.exists(wanted):
            self.tree.selection_set(wanted)
            self.tree.see(wanted)
        elif self.shown:
            self.tree.selection_set(self.shown[0].id)
        self._show_details()

    def _selected(self) -> Debt | None:
        selected = self.tree.selection()
        return next((d for d in self.shown if selected and d.id == selected[0]), None)

    def _show_details(self) -> None:
        debt = self._selected()
        self.payments.delete(*self.payments.get_children())
        if debt is None:
            self.info_label.configure(text="Select a debt to see its details and payments.\n\n"
                                     "Use “New debt…” to add money you owe or money someone owes you.")
            self.settle_button.configure(text="Mark as paid off")
            return
        lines = [
            f"{DIRECTION_LABELS[debt.direction]} {debt.counterparty} ({debt.counterparty_type})",
            f"{debt.description}" if debt.description else "",
            f"Total {format_money(debt.amount, debt.currency)} · since {debt.start_date:%d %b %Y}",
            f"Paid {format_money(debt.paid, debt.currency)} · remaining {format_money(debt.remaining, debt.currency)}",
        ]
        if debt.installments:
            dates = debt.schedule()
            lines.append(f"{debt.installments} monthly installments of "
                         f"{format_money(debt.installment_amount, debt.currency)} on day {debt.payment_day} "
                         f"({dates[0]:%b %Y} – {dates[-1]:%b %Y})")
        if debt.deadline:
            lines.append(f"Deadline {debt.deadline:%d %b %Y}")
        if not debt.installments and not debt.deadline:
            lines.append("No deadline")
        if debt.settled:
            lines.append("Marked as paid off")
        if debt.notes:
            lines.append(f"Notes: {debt.notes}")
        self.info_label.configure(text="\n".join(line for line in lines if line))
        record_kind = "Expense" if debt.direction == OWE else "Income"
        for p in sorted(debt.payments, key=lambda p: p.date, reverse=True):
            self.payments.insert("", "end", iid=p.id, values=(
                p.date.isoformat(), format_money(p.amount, debt.currency), p.note,
                record_kind if p.record_id else ""))
        self.settle_button.configure(text="Reopen" if debt.settled else "Mark as paid off")

    # ---------- actions ----------

    def _edit_at(self, y: int) -> None:
        row = self.tree.identify_row(y)
        if row:
            self.tree.selection_set(row)
            self.edit_selected()

    def _need_selection(self) -> Debt | None:
        debt = self._selected()
        if debt is None:
            self.app.set_status("Select a debt first.")
        return debt

    def edit_selected(self) -> None:
        debt = self._need_selection()
        if debt:
            DebtDialog(self.app, debt)

    def record_payment(self) -> None:
        debt = self._need_selection()
        if debt:
            PaymentDialog(self.app, debt)

    def toggle_settled(self) -> None:
        debt = self._need_selection()
        if not debt:
            return
        debt.settled = not debt.settled
        verb = "Mark as paid off" if debt.settled else "Reopen"
        self.app.history.record(f"{verb}: {debt.counterparty}", lambda: save_debt(self.app.store, debt))
        self.app.debt_saved(debt.id, f"{'Marked as paid off' if debt.settled else 'Reopened'}: {debt.counterparty}")

    def delete_selected(self) -> None:
        debt = self._need_selection()
        if not debt:
            return
        count = len(debt.payments)
        if not messagebox.askyesno(
            "Delete debt", f"Delete the debt with {debt.counterparty}"
                           + (f" and its {count} payment(s)" if count else "") + "?\n\n"
                           "Expenses or income already created from payments are kept.\n"
                           "You can undo this with Ctrl+Z."):
            return
        self.app.history.record(f"Delete debt with {debt.counterparty}",
                                lambda: delete_debt(self.app.store, debt.id))
        self.app.set_status(f"Deleted the debt with {debt.counterparty}.")
        self.app.refresh()

    def delete_payment(self) -> None:
        debt = self._selected()
        selected = self.payments.selection()
        if not debt or not selected:
            self.app.set_status("Select a payment in the details first.")
            return
        payment = next(p for p in debt.payments if p.id == selected[0])
        linked = " and the expense/income created with it" if payment.record_id else ""
        if not messagebox.askyesno("Delete payment",
                                   f"Delete the payment of {format_money(payment.amount, debt.currency)} "
                                   f"from {payment.date:%d %b %Y}{linked}?\n\nYou can undo this with Ctrl+Z."):
            return
        self.app.history.record(f"Delete payment ({debt.counterparty})",
                                lambda: delete_payment(self.app.store, debt.id, payment.id))
        self.app.debt_saved(debt.id, f"Deleted a payment of {format_money(payment.amount, debt.currency)}.")
