"""Data model and local JSON storage.

Everything lives in one JSON file (default: data/expenses.json) next to two folders:
  data/receipts/  copies of receipt files attached to expenses
  data/backups/   an automatic copy of the data file, once per day (last 30 kept)
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from .catalog import (
    Category,
    Item,
    default_categories,
    default_income_sources,
    default_payment_methods,
)

DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "expenses.json"
DATA_VERSION = 3
BACKUPS_TO_KEEP = 30

CURRENCIES = ("PEN", "USD")
DEFAULT_CURRENCY = "PEN"
SYMBOLS = {"PEN": "S/", "USD": "US$"}
CENT = Decimal("0.01")
RATE_STEP = Decimal("0.0001")


def data_file_path() -> Path:
    """Location of the expenses file; override with the EXPENSES_FILE env var."""
    override = os.environ.get("EXPENSES_FILE")
    return Path(override).expanduser() if override else DEFAULT_DATA_FILE


# ---------- parsing & formatting ----------

def _parse_positive(value: str | Decimal, step: Decimal, label: str) -> Decimal:
    text = str(value).strip()
    if "," in text and "." not in text and text.count(",") == 1:
        text = text.replace(",", ".")  # accept a comma as the decimal separator, e.g. "12,50"
    try:
        number = Decimal(text).quantize(step, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"Invalid {label}: {value!r}") from None
    if number <= 0:
        raise ValueError(f"{label.capitalize()} must be greater than zero")
    return number


def parse_amount(value: str | Decimal) -> Decimal:
    return _parse_positive(value, CENT, "amount")


def parse_rate(value: str | Decimal) -> Decimal:
    """Exchange rate expressed as soles (PEN) per 1 US dollar, e.g. 3.75."""
    return _parse_positive(value, RATE_STEP, "exchange rate")


def parse_currency(value: str | None) -> str:
    currency = (value or DEFAULT_CURRENCY).strip().upper()
    if currency not in CURRENCIES:
        raise ValueError(f"Currency must be one of {', '.join(CURRENCIES)}")
    return currency


def parse_date(value: str | date | None) -> date:
    if value is None or value == "":
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD") from None


def parse_tags(value: str | list[str] | None) -> list[str]:
    """'Vacation, #cusco 2026' -> ['vacation', 'cusco-2026'] (comma separated, no duplicates)."""
    parts = value if isinstance(value, list) else (value or "").split(",")
    tags: list[str] = []
    for part in parts:
        tag = "-".join(part.strip().lstrip("#").lower().split())
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def format_money(value: Decimal | None, currency: str) -> str:
    return "—" if value is None else f"{SYMBOLS[currency]} {value:,.2f}"


def format_rate(rate: Decimal | None) -> str:
    """3.7500 -> '3.75', 3.8000 -> '3.80' (at least 2 decimals, trailing zeros dropped)."""
    if rate is None:
        return "—"
    text = f"{rate:.4f}".rstrip("0")
    return text + "0" * max(0, 2 - len(text.split(".")[1]))


def convert(amount: Decimal, currency: str, rate: Decimal | None, target: str) -> Decimal | None:
    """Convert with a given PEN-per-USD rate; None when a conversion is needed but there's no rate."""
    if target == currency:
        return amount
    if rate is None:
        return None
    converted = amount / rate if target == "USD" else amount * rate
    return converted.quantize(CENT, rounding=ROUND_HALF_UP)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def write_json_atomic(path: Path, doc: dict) -> None:
    """Write to a temp file first, then swap it in, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------- months ----------

def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def add_months(month: str, n: int) -> str:
    year, mon = map(int, month.split("-"))
    index = year * 12 + (mon - 1) + n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_range(first: str, last: str) -> list[str]:
    months = []
    current = first
    while current <= last:
        months.append(current)
        current = add_months(current, 1)
    return months


# ---------- records ----------

class _Money:
    amount: Decimal
    currency: str
    rate: Decimal | None

    def amount_in(self, currency: str) -> Decimal | None:
        """This record's amount in `currency`, converted with its own rate (None if no rate)."""
        return convert(self.amount, self.currency, self.rate, currency)

    @property
    def amount_pen(self) -> Decimal | None:
        return self.amount_in("PEN")

    @property
    def amount_usd(self) -> Decimal | None:
        return self.amount_in("USD")


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Expense(_Money):
    amount: Decimal  # in `currency`, exactly as entered
    category: str
    description: str = ""
    date: date = field(default_factory=date.today)
    currency: str = DEFAULT_CURRENCY
    # PEN per 1 USD at the moment this expense was entered. Each expense keeps its own rate,
    # so later rate changes never affect it. None only for entries saved before rates existed.
    rate: Decimal | None = None
    subcategory: str = ""
    payment_method: str = ""
    tags: list[str] = field(default_factory=list)
    receipt: str | None = None  # file name inside data/receipts/
    recurring_id: str | None = None  # set when created from a recurring expense
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "currency": self.currency,
            "amount": str(self.amount),
            "rate": _s(self.rate),
            # Saved for readability; always derived from amount + this item's own rate.
            "amount_pen": _s(self.amount_pen),
            "amount_usd": _s(self.amount_usd),
            "payment_method": self.payment_method,
            "tags": self.tags,
            "receipt": self.receipt,
            "recurring_id": self.recurring_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Expense:
        return cls(
            id=d["id"],
            amount=parse_amount(d["amount"]),
            category=d["category"],
            subcategory=d.get("subcategory") or "",
            description=d.get("description", ""),
            date=parse_date(d["date"]),
            currency=parse_currency(d.get("currency")),
            rate=parse_rate(d["rate"]) if d.get("rate") else None,
            payment_method=d.get("payment_method") or "",
            tags=parse_tags(d.get("tags") or []),
            receipt=d.get("receipt"),
            recurring_id=d.get("recurring_id"),
        )


@dataclass
class Income(_Money):
    amount: Decimal
    source: str
    description: str = ""
    date: date = field(default_factory=date.today)
    currency: str = DEFAULT_CURRENCY
    rate: Decimal | None = None
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "source": self.source,
            "description": self.description,
            "currency": self.currency,
            "amount": str(self.amount),
            "rate": _s(self.rate),
            "amount_pen": _s(self.amount_pen),
            "amount_usd": _s(self.amount_usd),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Income:
        return cls(
            id=d["id"],
            amount=parse_amount(d["amount"]),
            source=d["source"],
            description=d.get("description", ""),
            date=parse_date(d["date"]),
            currency=parse_currency(d.get("currency")),
            rate=parse_rate(d["rate"]) if d.get("rate") else None,
        )


@dataclass
class Budget:
    """Monthly spending limit for one category."""

    category: str
    amount: Decimal
    currency: str = DEFAULT_CURRENCY

    def to_dict(self) -> dict:
        return {"amount": str(self.amount), "currency": self.currency}

    @classmethod
    def from_dict(cls, category: str, d: dict) -> Budget:
        return cls(category, parse_amount(d["amount"]), parse_currency(d.get("currency")))


@dataclass
class RecurringExpense:
    """A template (rent, subscriptions…) that becomes a real expense once a month."""

    amount: Decimal
    category: str
    subcategory: str = ""
    description: str = ""
    currency: str = DEFAULT_CURRENCY
    payment_method: str = ""
    day: int = 1  # day of the month it's due (1-28)
    start_month: str = field(default_factory=lambda: month_key(date.today()))
    handled_through: str | None = None  # last month already added or skipped
    active: bool = True
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if not 1 <= int(self.day) <= 28:
            raise ValueError("Day of month must be between 1 and 28")
        self.day = int(self.day)

    def next_month(self) -> str:
        return add_months(self.handled_through, 1) if self.handled_through else self.start_month

    def due_months(self, today: date) -> list[str]:
        """Months whose occurrence is due (on or before `today`) and not handled yet."""
        if not self.active:
            return []
        current = month_key(today)
        last = current if today.day >= self.day else add_months(current, -1)
        return month_range(self.next_month(), last)

    def occurrence_date(self, month: str) -> date:
        year, mon = map(int, month.split("-"))
        return date(year, mon, self.day)

    def to_expense(self, month: str, rate: Decimal | None) -> Expense:
        return Expense(
            amount=self.amount,
            category=self.category,
            subcategory=self.subcategory,
            description=self.description,
            date=self.occurrence_date(month),
            currency=self.currency,
            rate=rate,
            payment_method=self.payment_method,
            recurring_id=self.id,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "amount": str(self.amount),
            "currency": self.currency,
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "payment_method": self.payment_method,
            "day": self.day,
            "start_month": self.start_month,
            "handled_through": self.handled_through,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RecurringExpense:
        return cls(
            id=d["id"],
            amount=parse_amount(d["amount"]),
            currency=parse_currency(d.get("currency")),
            category=d["category"],
            subcategory=d.get("subcategory") or "",
            description=d.get("description", ""),
            payment_method=d.get("payment_method") or "",
            day=d.get("day", 1),
            start_month=d.get("start_month") or month_key(date.today()),
            handled_through=d.get("handled_through"),
            active=d.get("active", True),
        )


# ---------- store ----------

class ExpenseStore:
    """Loads and saves everything to one JSON file, with daily backups."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_file_path()

    @property
    def receipts_dir(self) -> Path:
        return self.path.parent / "receipts"

    @property
    def backups_dir(self) -> Path:
        return self.path.parent / "backups"

    # --- raw file access ---

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._daily_backup()
        doc["version"] = DATA_VERSION
        write_json_atomic(self.path, doc)

    # --- whole-document snapshots (used by undo) ---

    def snapshot(self) -> dict:
        """A copy of everything in the data file, as it is right now."""
        return self._read()

    def update_document(self, change: Callable[[dict], None]) -> None:
        """Apply `change` to the whole document and save it in a single write (all or nothing)."""
        doc = self._read()
        change(doc)
        self._write(doc)

    def restore(self, doc: dict) -> None:
        """Put back a snapshot, then bring receipt files in line with it."""
        self._write(doc)
        self._reconcile_receipts(doc)

    def _reconcile_receipts(self, doc: dict) -> None:
        """Receipts the data refers to are brought back from receipts/removed; unused ones are set aside there."""
        if not self.receipts_dir.exists():
            return
        referenced = {e["receipt"] for e in doc.get("expenses", []) if e.get("receipt")}
        removed = self.receipts_dir / "removed"
        for name in referenced:
            path, parked = self.receipts_dir / name, removed / name
            if not path.exists() and parked.exists():
                os.replace(parked, path)
        for path in self.receipts_dir.iterdir():
            if path.is_file() and path.name not in referenced:
                self._retire_receipt(path.name)

    # --- backups ---

    def _daily_backup(self) -> None:
        if not self.path.exists():
            return
        target = self.backups_dir / f"{self.path.stem}-{date.today().isoformat()}.json"
        if not target.exists():
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, target)
            self._prune_backups()

    def _prune_backups(self) -> None:
        backups = sorted(self.backups_dir.glob(f"{self.path.stem}-*.json"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-BACKUPS_TO_KEEP]:
            old.unlink(missing_ok=True)

    def backup_now(self) -> Path:
        if not self.path.exists():
            raise ValueError("There is no data to back up yet")
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        target = self.backups_dir / f"{self.path.stem}-{datetime.now():%Y-%m-%d_%H%M%S}.json"
        shutil.copy2(self.path, target)
        return target

    # --- expenses ---

    def load(self) -> list[Expense]:
        return [Expense.from_dict(item) for item in self._read().get("expenses", [])]

    def get(self, expense_id: str) -> Expense | None:
        return next((e for e in self.load() if e.id == expense_id), None)

    def last_rate(self) -> Decimal | None:
        """The exchange rate used for the most recently added expense or income, if any."""
        value = self._read().get("settings", {}).get("last_rate")
        return parse_rate(value) if value else None

    def add(self, expense: Expense) -> Expense:
        self.add_many([expense])
        return expense

    def add_many(self, expenses: list[Expense]) -> None:
        doc = self._read()
        doc.setdefault("expenses", []).extend(e.to_dict() for e in expenses)
        rates = [e.rate for e in expenses if e.rate is not None]
        if rates:
            doc.setdefault("settings", {})["last_rate"] = str(rates[-1])
        self._write(doc)

    def update(self, expense: Expense) -> bool:
        """Replace the stored expense that has the same id. Doesn't change the remembered last rate."""
        return self._replace("expenses", expense.id, expense.to_dict())

    def delete(self, expense_id: str) -> bool:
        expense = self.get(expense_id)
        if expense is None:
            return False
        if expense.receipt:
            self._retire_receipt(expense.receipt)
        return self._replace("expenses", expense_id, None)

    def save(self, expenses: list[Expense]) -> None:
        doc = self._read()
        doc["expenses"] = [e.to_dict() for e in expenses]
        self._write(doc)

    def filter(self, month: str | None = None, category: str | None = None) -> list[Expense]:
        """Return expenses sorted by date, optionally filtered by month (YYYY-MM) or year (YYYY) and category."""
        result = self.load()
        if month:
            result = [e for e in result if month_key(e.date).startswith(month)]
        if category:
            result = [e for e in result if e.category.lower() == category.lower()]
        return sorted(result, key=lambda e: e.date)

    def _replace(self, section: str, item_id: str, new: dict | None) -> bool:
        doc = self._read()
        items = doc.get(section, [])
        for i, item in enumerate(items):
            if item["id"] == item_id:
                if new is None:
                    del items[i]
                else:
                    items[i] = new
                self._write(doc)
                return True
        return False

    # --- income ---

    def load_incomes(self) -> list[Income]:
        return [Income.from_dict(item) for item in self._read().get("incomes", [])]

    def add_income(self, income: Income) -> Income:
        doc = self._read()
        doc.setdefault("incomes", []).append(income.to_dict())
        if income.rate is not None:
            doc.setdefault("settings", {})["last_rate"] = str(income.rate)
        self._write(doc)
        return income

    def update_income(self, income: Income) -> bool:
        return self._replace("incomes", income.id, income.to_dict())

    def delete_income(self, income_id: str) -> bool:
        return self._replace("incomes", income_id, None)

    # --- catalog: categories, payment methods, income sources ---

    def categories(self) -> list[Category]:
        raw = self._read().get("categories")
        return [Category.from_dict(c) for c in raw] if raw else default_categories()

    def save_categories(self, categories: list[Category]) -> None:
        doc = self._read()
        doc["categories"] = [c.to_dict() for c in categories]
        self._write(doc)

    def rename_category(self, old: str, new: str) -> int:
        """Rename a category everywhere (catalog, expenses, budgets, recurring). Returns expenses changed."""
        doc = self._read()
        doc.setdefault("categories", [c.to_dict() for c in self.categories()])
        for cat in doc["categories"]:
            if cat["name"].lower() == old.lower():
                cat["name"] = new
        changed = 0
        for section in ("expenses", "recurring"):
            for item in doc.get(section, []):
                if item["category"].lower() == old.lower():
                    item["category"] = new
                    changed += section == "expenses"
        budgets = doc.get("budgets", {})
        for key in [k for k in budgets if k.lower() == old.lower()]:
            budgets[new] = budgets.pop(key)
        self._write(doc)
        return changed

    def rename_subcategory(self, category: str, old: str, new: str) -> int:
        doc = self._read()
        doc.setdefault("categories", [c.to_dict() for c in self.categories()])
        for cat in doc["categories"]:
            if cat["name"].lower() == category.lower():
                for sub in cat.get("subcategories", []):
                    if sub["name"].lower() == old.lower():
                        sub["name"] = new
        changed = 0
        for section in ("expenses", "recurring"):
            for item in doc.get(section, []):
                if item["category"].lower() == category.lower() and (item.get("subcategory") or "").lower() == old.lower():
                    item["subcategory"] = new
                    changed += section == "expenses"
        self._write(doc)
        return changed

    def rename_value(self, sections: tuple[str, ...], field_name: str, old: str, new: str) -> int:
        """Rename a payment method / income source on every record that uses it. Returns count."""
        doc = self._read()
        changed = 0
        for section in sections:
            for item in doc.get(section, []):
                if (item.get(field_name) or "").lower() == old.lower():
                    item[field_name] = new
                    changed += 1
        if changed:
            self._write(doc)
        return changed

    def payment_methods(self) -> list[Item]:
        raw = self._read().get("payment_methods")
        return [Item.from_dict(i) for i in raw] if raw else default_payment_methods()

    def save_payment_methods(self, items: list[Item]) -> None:
        doc = self._read()
        doc["payment_methods"] = [i.to_dict() for i in items]
        self._write(doc)

    def income_sources(self) -> list[Item]:
        raw = self._read().get("income_sources")
        return [Item.from_dict(i) for i in raw] if raw else default_income_sources()

    def save_income_sources(self, items: list[Item]) -> None:
        doc = self._read()
        doc["income_sources"] = [i.to_dict() for i in items]
        self._write(doc)

    # --- budgets ---

    def budgets(self) -> dict[str, Budget]:
        return {name: Budget.from_dict(name, d) for name, d in self._read().get("budgets", {}).items()}

    def set_budget(self, category: str, amount: Decimal | None, currency: str = DEFAULT_CURRENCY) -> None:
        """Set (or with amount=None, remove) the monthly budget for a category."""
        doc = self._read()
        budgets = doc.setdefault("budgets", {})
        for key in [k for k in budgets if k.lower() == category.lower()]:
            del budgets[key]
        if amount is not None:
            budgets[category] = Budget(category, amount, currency).to_dict()
        self._write(doc)

    # --- recurring expenses ---

    def recurring(self) -> list[RecurringExpense]:
        return [RecurringExpense.from_dict(r) for r in self._read().get("recurring", [])]

    def save_recurring(self, item: RecurringExpense) -> None:
        """Add a recurring expense, or update it if one with the same id exists."""
        if not self._replace("recurring", item.id, item.to_dict()):
            doc = self._read()
            doc.setdefault("recurring", []).append(item.to_dict())
            self._write(doc)

    def delete_recurring(self, item_id: str) -> bool:
        return self._replace("recurring", item_id, None)

    def due_recurring(self, today: date | None = None) -> list[tuple[RecurringExpense, str]]:
        today = today or date.today()
        return [(r, month) for r in self.recurring() for month in r.due_months(today)]

    def apply_recurring(
        self,
        add: list[tuple[str, str]],
        skip: list[tuple[str, str]],
        rate: Decimal | None,
    ) -> list[Expense]:
        """Create expenses for the (recurring id, month) pairs in `add`; mark `skip` as handled."""
        doc = self._read()
        templates = {r["id"]: RecurringExpense.from_dict(r) for r in doc.get("recurring", [])}
        created = [templates[rid].to_expense(month, rate) for rid, month in add if rid in templates]
        doc.setdefault("expenses", []).extend(e.to_dict() for e in created)
        for rid, month in [*add, *skip]:
            template = templates.get(rid)
            if template and (template.handled_through is None or month > template.handled_through):
                template.handled_through = month
        doc["recurring"] = [t.to_dict() for t in templates.values()]
        if created and rate is not None:
            doc.setdefault("settings", {})["last_rate"] = str(rate)
        self._write(doc)
        return created

    # --- receipts ---

    def attach_receipt(self, expense_id: str, source: str | Path) -> Expense:
        expense = self.get(expense_id)
        if expense is None:
            raise ValueError("This expense no longer exists")
        source = Path(source)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        if expense.receipt:
            self._retire_receipt(expense.receipt)
        name = f"{expense.date.isoformat()}_{expense.id}{source.suffix.lower()}"
        shutil.copy2(source, self.receipts_dir / name)
        expense.receipt = name
        self.update(expense)
        return expense

    def remove_receipt(self, expense_id: str) -> None:
        expense = self.get(expense_id)
        if expense and expense.receipt:
            self._retire_receipt(expense.receipt)
            expense.receipt = None
            self.update(expense)

    def receipt_path(self, expense: Expense) -> Path | None:
        if not expense.receipt:
            return None
        path = self.receipts_dir / expense.receipt
        return path if path.exists() else None

    def _retire_receipt(self, name: str) -> None:
        """Move a receipt that's no longer used into receipts/removed/ instead of deleting it."""
        path = self.receipts_dir / name
        if path.exists():
            removed = self.receipts_dir / "removed"
            removed.mkdir(parents=True, exist_ok=True)
            os.replace(path, removed / name)


# ---------- export & totals ----------

def export_csv(expenses: list[Expense], path: Path) -> None:
    def s(value: Decimal | None) -> str:
        return "" if value is None else str(value)

    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "date", "category", "subcategory", "description", "payment_method", "tags",
            "currency", "amount", "rate_pen_per_usd", "amount_pen", "amount_usd",
        ])
        for e in expenses:
            writer.writerow([
                e.id, e.date.isoformat(), e.category, e.subcategory, e.description,
                e.payment_method, ", ".join(e.tags),
                e.currency, str(e.amount), s(e.rate), s(e.amount_pen), s(e.amount_usd),
            ])


def total_in(records: list[_Money], currency: str) -> tuple[Decimal, int]:
    """Sum of records in `currency`, plus how many had to be skipped for lacking a rate."""
    values = [r.amount_in(currency) for r in records]
    total = sum((v for v in values if v is not None), Decimal("0"))
    return total, sum(v is None for v in values)


def summarize_by_category(expenses: list[Expense], currency: str = DEFAULT_CURRENCY) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for e in expenses:
        value = e.amount_in(currency)
        if value is not None:
            totals[e.category] = totals.get(e.category, Decimal("0")) + value
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))
