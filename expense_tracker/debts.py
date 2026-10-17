"""Debts: money you owe, and money others owe you.

A debt has a counterparty (who or what), an amount in PEN or USD with its own exchange rate,
an optional deadline, an optional plan of monthly installments, and a history of payments.
Debts are saved in the user's data file under "debts".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .catalog import Category, Item, find_category, find_item
from .storage import (
    CENT,
    DEFAULT_CURRENCY,
    Expense,
    ExpenseStore,
    Income,
    add_months,
    convert,
    day_in_month,
    month_key,
    parse_amount,
    parse_currency,
    parse_date,
    parse_rate,
)

OWE = "owe"  # I owe someone
OWED = "owed"  # someone owes me
DIRECTION_LABELS = {OWE: "I owe", OWED: "Owes me"}
DUE_SOON_DAYS = 7

# (type, icon, color) for "who or what" the debt is with.
COUNTERPARTY_TYPES = [
    ("Person", "👤", "#577590"),
    ("Family", "🏡", "#f4a261"),
    ("Friend", "🙂", "#90be6d"),
    ("Bank", "🏦", "#277da1"),
    ("Credit card", "💳", "#8d6cab"),
    ("Store", "🛍", "#f28482"),
    ("Company", "🏢", "#4d908e"),
    ("Government", "🏛", "#6c757d"),
    ("Other", "📄", "#8d99ae"),
]

STATUS_LABELS = {
    "overdue": "Overdue",
    "due_soon": "Due soon",
    "on_track": "On track",
    "open": "No deadline",
    "paid": "Paid off",
}
STATUS_ORDER = ["overdue", "due_soon", "on_track", "open", "paid"]

# Where payments go when you also record them as an expense / income.
PAYMENT_CATEGORY = Category("Debt payments", "🤝", "#6d597a")
REPAYMENT_SOURCE = Item("Debt repayment", "🤝")


def counterparty_look(kind: str) -> tuple[str, str]:
    return next(((i, c) for t, i, c in COUNTERPARTY_TYPES if t.lower() == kind.lower()), ("📄", "#8d99ae"))


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _monthly(start: date, day: int, count: int) -> list[date]:
    """`count` monthly dates on `day` (the month's last day when it's shorter), the first one after `start`."""
    this_month = month_key(start)
    first_month = this_month if day_in_month(this_month, day) > start else add_months(this_month, 1)
    return [day_in_month(add_months(first_month, n), day) for n in range(count)]


@dataclass
class DebtPayment:
    amount: Decimal  # in the debt's currency
    date: date = field(default_factory=date.today)
    note: str = ""
    rate: Decimal | None = None  # PEN per USD on the payment day (used for the linked expense/income)
    record_id: str | None = None  # the expense or income created together with this payment
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return {"id": self.id, "date": self.date.isoformat(), "amount": str(self.amount), "note": self.note,
                "rate": None if self.rate is None else str(self.rate), "record_id": self.record_id}

    @classmethod
    def from_dict(cls, d: dict) -> DebtPayment:
        return cls(id=d["id"], date=parse_date(d["date"]), amount=parse_amount(d["amount"]),
                   note=d.get("note", ""), rate=parse_rate(d["rate"]) if d.get("rate") else None,
                   record_id=d.get("record_id"))


@dataclass
class Debt:
    counterparty: str  # who or what: "Juan", "BCP", "Saga Falabella card"…
    amount: Decimal  # total to pay back, in `currency`
    direction: str = OWE
    counterparty_type: str = "Person"
    description: str = ""
    currency: str = DEFAULT_CURRENCY
    rate: Decimal | None = None  # PEN per USD when the debt started (for showing totals in the other currency)
    start_date: date = field(default_factory=date.today)
    deadline: date | None = None  # None = no deadline
    installments: int | None = None  # number of monthly payments, or None
    payment_day: int | None = None  # day of the month installments are due (1-31; shorter months: last day)
    notes: str = ""
    settled: bool = False  # marked as paid off by hand (e.g. settled for less)
    payments: list[DebtPayment] = field(default_factory=list)
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if self.direction not in (OWE, OWED):
            raise ValueError("Direction must be 'owe' or 'owed'")
        if not self.counterparty.strip():
            raise ValueError("Say who or what the debt is with")
        if self.installments is not None:
            if not 1 <= int(self.installments) <= 360:
                raise ValueError("Installments must be between 1 and 360")
            if self.payment_day is None or not 1 <= int(self.payment_day) <= 31:
                raise ValueError("Installments need a day of the month between 1 and 31")
            self.installments, self.payment_day = int(self.installments), int(self.payment_day)
        if self.deadline is not None and self.deadline < self.start_date:
            raise ValueError("The deadline can't be before the start date")

    # --- amounts ---

    @property
    def paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), Decimal("0"))

    @property
    def remaining(self) -> Decimal:
        if self.settled:
            return Decimal("0")
        return max(Decimal("0"), self.amount - self.paid)

    @property
    def is_closed(self) -> bool:
        return self.settled or self.remaining == 0

    @property
    def progress(self) -> Decimal:
        """Share already paid, 0..1."""
        if self.is_closed:
            return Decimal("1")
        return min(Decimal("1"), self.paid / self.amount) if self.amount else Decimal("0")

    def amount_in(self, currency: str, value: Decimal | None = None) -> Decimal | None:
        """`value` (default: the total) converted with the debt's own rate."""
        return convert(self.amount if value is None else value, self.currency, self.rate, currency)

    # --- schedule ---

    @property
    def installment_amount(self) -> Decimal | None:
        if not self.installments:
            return None
        return (self.amount / self.installments).quantize(CENT, rounding=ROUND_HALF_UP)

    def schedule(self) -> list[date]:
        """Due dates of the installments (empty when there's no installment plan)."""
        if not self.installments:
            return []
        return _monthly(self.start_date, self.payment_day, self.installments)

    @property
    def final_date(self) -> date | None:
        """The deadline, or else the last installment date."""
        if self.deadline:
            return self.deadline
        dates = self.schedule()
        return dates[-1] if dates else None

    def next_due(self) -> tuple[date, Decimal] | None:
        """(date, amount) of the next payment expected, or None if there's no date to meet."""
        if self.is_closed:
            return None
        dates = self.schedule()
        if dates:
            covered = int(self.paid // self.installment_amount) if self.installment_amount else 0
            if covered < len(dates):
                expected = min(self.installment_amount, self.remaining)
                # The last installment absorbs rounding, so it's whatever is left.
                if covered == len(dates) - 1:
                    expected = self.remaining
                return dates[covered], expected
            return dates[-1], self.remaining
        if self.deadline:
            return self.deadline, self.remaining
        return None

    def status(self, today: date | None = None) -> str:
        today = today or date.today()
        if self.is_closed:
            return "paid"
        due = self.next_due()
        if due is None:
            return "open"
        days = (due[0] - today).days
        if days < 0:
            return "overdue"
        return "due_soon" if days <= DUE_SOON_DAYS else "on_track"

    # --- saving ---

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "direction": self.direction,
            "counterparty": self.counterparty,
            "counterparty_type": self.counterparty_type,
            "description": self.description,
            "currency": self.currency,
            "amount": str(self.amount),
            "rate": None if self.rate is None else str(self.rate),
            "start_date": self.start_date.isoformat(),
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "installments": self.installments,
            "payment_day": self.payment_day,
            "notes": self.notes,
            "settled": self.settled,
            "payments": [p.to_dict() for p in self.payments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Debt:
        return cls(
            id=d["id"],
            direction=d.get("direction", OWE),
            counterparty=d["counterparty"],
            counterparty_type=d.get("counterparty_type") or "Person",
            description=d.get("description", ""),
            currency=parse_currency(d.get("currency")),
            amount=parse_amount(d["amount"]),
            rate=parse_rate(d["rate"]) if d.get("rate") else None,
            start_date=parse_date(d["start_date"]),
            deadline=parse_date(d["deadline"]) if d.get("deadline") else None,
            installments=d.get("installments"),
            payment_day=d.get("payment_day"),
            notes=d.get("notes", ""),
            settled=d.get("settled", False),
            payments=[DebtPayment.from_dict(p) for p in d.get("payments", [])],
        )


# ---------- storage ----------

def load_debts(store: ExpenseStore) -> list[Debt]:
    return [Debt.from_dict(d) for d in store.snapshot().get("debts", [])]


def get_debt(store: ExpenseStore, debt_id: str) -> Debt | None:
    return next((d for d in load_debts(store) if d.id == debt_id), None)


def save_debt(store: ExpenseStore, debt: Debt) -> None:
    """Add the debt, or replace the saved one with the same id."""
    def change(doc: dict) -> None:
        debts = doc.setdefault("debts", [])
        for i, item in enumerate(debts):
            if item["id"] == debt.id:
                debts[i] = debt.to_dict()
                return
        debts.append(debt.to_dict())
    store.update_document(change)


def delete_debt(store: ExpenseStore, debt_id: str) -> None:
    """Delete a debt and its payment history. Expenses/income created from payments are kept."""
    store.update_document(lambda doc: doc.__setitem__(
        "debts", [d for d in doc.get("debts", []) if d["id"] != debt_id]))


def payment_record(debt: Debt, payment: DebtPayment) -> Expense | Income:
    """The expense (for debts I owe) or income (for debts owed to me) that mirrors a payment."""
    note = f" · {payment.note}" if payment.note else ""
    if debt.direction == OWE:
        return Expense(amount=payment.amount, category=PAYMENT_CATEGORY.name, date=payment.date,
                       currency=debt.currency, rate=payment.rate,
                       description=f"Payment to {debt.counterparty}{note}")
    return Income(amount=payment.amount, source=REPAYMENT_SOURCE.name, date=payment.date,
                  currency=debt.currency, rate=payment.rate,
                  description=f"Repayment from {debt.counterparty}{note}")


def add_payment(store: ExpenseStore, debt_id: str, payment: DebtPayment, also_record: bool = False) -> None:
    """Add a payment to a debt; optionally also add it as an expense/income, all in one save."""
    debt = get_debt(store, debt_id)
    if debt is None:
        raise ValueError("This debt no longer exists")
    record = payment_record(debt, payment) if also_record else None
    if record is not None:
        if record.rate is None:
            raise ValueError("Enter the exchange rate to also record this payment")
        payment.record_id = record.id
    categories = store.categories()
    sources = store.income_sources()

    def change(doc: dict) -> None:
        for item in doc.get("debts", []):
            if item["id"] == debt_id:
                item.setdefault("payments", []).append(payment.to_dict())
        if isinstance(record, Expense):
            doc.setdefault("expenses", []).append(record.to_dict())
            if not find_category(categories, PAYMENT_CATEGORY.name):
                doc["categories"] = [c.to_dict() for c in [*categories, PAYMENT_CATEGORY]]
        elif isinstance(record, Income):
            doc.setdefault("incomes", []).append(record.to_dict())
            if not find_item(sources, REPAYMENT_SOURCE.name):
                doc["income_sources"] = [i.to_dict() for i in [*sources, REPAYMENT_SOURCE]]
        if payment.rate is not None:
            doc.setdefault("settings", {})["last_rate"] = str(payment.rate)

    store.update_document(change)


def delete_payment(store: ExpenseStore, debt_id: str, payment_id: str) -> None:
    """Remove a payment, and the expense/income that was created with it (if it still exists)."""
    def change(doc: dict) -> None:
        record_id = None
        for item in doc.get("debts", []):
            if item["id"] == debt_id:
                kept = []
                for p in item.get("payments", []):
                    if p["id"] == payment_id:
                        record_id = p.get("record_id")
                    else:
                        kept.append(p)
                item["payments"] = kept
        if record_id:
            for section in ("expenses", "incomes"):
                doc[section] = [r for r in doc.get(section, []) if r["id"] != record_id]

    store.update_document(change)


# ---------- summaries ----------

@dataclass
class DebtSummary:
    i_owe: Decimal
    owed_to_me: Decimal
    overdue: int
    due_soon: int
    next_due: tuple[Debt, date, Decimal] | None  # the soonest payment among open debts
    missing_rate: int  # debts that couldn't be converted into the chosen currency


def summarize(debts: list[Debt], currency: str, today: date | None = None) -> DebtSummary:
    today = today or date.today()
    totals = {OWE: Decimal("0"), OWED: Decimal("0")}
    overdue = due_soon = missing = 0
    soonest = None
    for debt in debts:
        if debt.is_closed:
            continue
        value = debt.amount_in(currency, debt.remaining)
        if value is None:
            missing += 1
        else:
            totals[debt.direction] += value
        status = debt.status(today)
        overdue += status == "overdue"
        due_soon += status == "due_soon"
        due = debt.next_due()
        if due and (soonest is None or due[0] < soonest[1]):
            soonest = (debt, due[0], due[1])
    return DebtSummary(totals[OWE], totals[OWED], overdue, due_soon, soonest, missing)


def counterparty_names(debts: list[Debt]) -> list[str]:
    return sorted({d.counterparty for d in debts}, key=str.lower)
