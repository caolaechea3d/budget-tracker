"""Import expenses from a CSV file, such as a bank statement export."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from .catalog import Category, find_category
from .storage import CENT, Expense

DATE_FORMATS = {
    "Auto": None,
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
}
# Tried in order when the format is "Auto" (day-first, as used in Peru).
AUTO_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y/%m/%d"]

SIGN_CHOICES = {
    "all": "All rows (use the absolute amount)",
    "negative": "Only negative amounts (charges)",
    "positive": "Only positive amounts",
}

_HEADER_HINTS = {
    "date": ("fecha", "date", "día", "dia"),
    "amount": ("monto", "importe", "amount", "cargo", "valor", "total", "debit", "débito"),
    "description": ("descrip", "concepto", "detalle", "glosa", "description", "operación", "operacion", "comercio", "memo"),
    "category": ("categor",),
}


@dataclass
class CsvData:
    headers: list[str]
    rows: list[list[str]]
    delimiter: str
    encoding: str


def read_csv(path: str | Path) -> CsvData:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The file is empty")
    return CsvData(headers=[h.strip() for h in rows[0]], rows=rows[1:], delimiter=delimiter, encoding=encoding)


def guess_columns(headers: list[str]) -> dict[str, int | None]:
    """Best guess of which column holds the date, amount, description and category."""
    guesses: dict[str, int | None] = {}
    for key, hints in _HEADER_HINTS.items():
        guesses[key] = next(
            (i for i, h in enumerate(headers) if any(hint in h.lower() for hint in hints)), None
        )
    return guesses


def parse_date_flexible(text: str, fmt: str | None = None) -> date:
    text = text.strip().split(" ")[0].split("T")[0]
    for candidate in [fmt] if fmt else AUTO_FORMATS:
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def parse_amount_flexible(text: str) -> Decimal:
    """Signed amount from bank-style text: 'S/ -1.234,56', '(45.00)', '1,234.56', '12,5'."""
    raw = text.strip()
    negative = raw.startswith("-") or raw.endswith("-") or (raw.startswith("(") and raw.endswith(")"))
    negative = negative or bool(re.search(r"[-−]\s*\d", raw))
    s = re.sub(r"[^\d,.]", "", raw)
    if not s:
        raise ValueError(f"no amount in {text!r}")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"invalid amount {text!r}") from None
    return -value if negative else value


@dataclass
class ImportOptions:
    date_col: int
    amount_col: int
    description_col: int | None = None
    category_col: int | None = None
    date_format: str | None = None  # a strptime format, or None for auto-detect
    sign: str = "all"
    default_category: str = "Other"
    currency: str = "PEN"
    rate: Decimal | None = None
    payment_method: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    expenses: list[Expense]
    duplicates: int = 0
    skipped_by_sign: int = 0
    errors: list[str] = field(default_factory=list)


def build_expenses(
    data: CsvData, opts: ImportOptions, existing: list[Expense], categories: list[Category]
) -> ImportResult:
    """Turn CSV rows into expenses, skipping rows already in `existing` (same date, amount, description)."""
    seen = {(e.date, e.amount, e.description.strip().lower()) for e in existing}
    result = ImportResult(expenses=[])
    for line, row in enumerate(data.rows, start=2):
        try:
            if row[opts.date_col].strip().lower().startswith("total"):  # a totals line, as in our own CSV export
                continue
            when = parse_date_flexible(row[opts.date_col], opts.date_format)
            signed = parse_amount_flexible(row[opts.amount_col])
            if signed == 0:
                raise ValueError("amount is zero")
            if (opts.sign == "negative" and signed > 0) or (opts.sign == "positive" and signed < 0):
                result.skipped_by_sign += 1
                continue
            amount = abs(signed).quantize(CENT, rounding=ROUND_HALF_UP)
            description = row[opts.description_col].strip() if opts.description_col is not None else ""
            category = opts.default_category
            if opts.category_col is not None and row[opts.category_col].strip():
                name = row[opts.category_col].strip()
                known = find_category(categories, name)
                category = known.name if known else name.title()
        except (ValueError, IndexError) as exc:
            result.errors.append(f"Line {line}: {exc}")
            continue
        key = (when, amount, description.lower())
        if key in seen:
            result.duplicates += 1
            continue
        result.expenses.append(Expense(
            amount=amount, category=category, description=description, date=when,
            currency=opts.currency, rate=opts.rate, payment_method=opts.payment_method, tags=list(opts.tags),
        ))
    return result
