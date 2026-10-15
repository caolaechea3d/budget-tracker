"""Command-line interface for the expense tracker."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import APP_NAME
from .reports import budget_statuses, by_subcategory
from .storage import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    Expense,
    ExpenseStore,
    Income,
    export_csv,
    format_money,
    format_rate,
    month_key,
    parse_amount,
    parse_currency,
    parse_date,
    parse_rate,
    parse_tags,
    summarize_by_category,
    total_in,
)
from .debts import DIRECTION_LABELS, STATUS_LABELS, STATUS_ORDER, load_debts
from .debts import summarize as summarize_debts
from .users import USER_TYPES, UserRegistry

NO_RATE_HELP = "No exchange rate saved yet; give one (PEN per 1 USD), e.g. 3.75"


def category_label(e: Expense) -> str:
    return f"{e.category} › {e.subcategory}" if e.subcategory else e.category


def print_table(expenses: list[Expense], currency: str = DEFAULT_CURRENCY) -> None:
    if not expenses:
        print("No expenses found.")
        return
    print(f"{'ID':<9}{'Date':<12}{'Category':<26}{'Amount (' + currency + ')':>16}  {'Entered as':<14}{'Rate':>7}  "
          f"{'Payment':<14}Description")
    print("-" * 120)
    for e in expenses:
        tags = " ".join(f"#{t}" for t in e.tags)
        print(
            f"{e.id:<9}{e.date.isoformat():<12}{category_label(e)[:25]:<26}"
            f"{format_money(e.amount_in(currency), currency):>16}  "
            f"{format_money(e.amount, e.currency):<14}{format_rate(e.rate):>7}  "
            f"{e.payment_method[:13]:<14}{e.description}{'  ' + tags if tags else ''}{'  📎' if e.receipt else ''}"
        )
    print("-" * 120)
    total, missing = total_in(expenses, currency)
    print(f"{'Total':<47}{format_money(total, currency):>16}")
    if missing:
        print(f"({missing} expense(s) without an exchange rate are not included in the {currency} total)")


def print_summary(expenses: list[Expense], currency: str = DEFAULT_CURRENCY) -> None:
    totals = summarize_by_category(expenses, currency)
    if not totals:
        print("No expenses found.")
        return
    grand = sum(totals.values())
    for category, amount in totals.items():
        print(f"{category[:24]:<26}{format_money(amount, currency):>16}  {amount / grand * 100:5.1f}%")
        subs = by_subcategory(expenses, category, currency)
        if len(subs) > 1 or "" not in subs:
            for sub, value in subs.items():
                print(f"   {(sub or '(no subcategory)')[:21]:<23}{format_money(value, currency):>16}")
    print("-" * 50)
    print(f"{'Total':<26}{format_money(grand, currency):>16}")


def describe(expense: Expense) -> str:
    return (
        f"{format_money(expense.amount_pen, 'PEN')} / {format_money(expense.amount_usd, 'USD')} "
        f"({category_label(expense)}) on {expense.date} at {format_rate(expense.rate)} PEN/USD [id {expense.id}]"
    )


def resolve_rate(store: ExpenseStore, text: str | None) -> object:
    rate = parse_rate(text) if text else store.last_rate()
    if rate is None:
        raise ValueError(NO_RATE_HELP + " with --rate")
    return rate


# ---------- subcommand handlers ----------

def cmd_add(store: ExpenseStore, args: argparse.Namespace) -> None:
    expense = Expense(
        amount=parse_amount(args.amount),
        currency=parse_currency(args.currency),
        rate=resolve_rate(store, args.rate),
        category=args.category.strip().title(),
        subcategory=(args.subcategory or "").strip(),
        payment_method=(args.payment or "").strip(),
        tags=parse_tags(args.tags),
        description=args.description or "",
        date=parse_date(args.date),
    )
    store.add(expense)
    print(f"Added {describe(expense)}")


def cmd_edit(store: ExpenseStore, args: argparse.Namespace) -> None:
    expense = store.get(args.id)
    if expense is None:
        print(f"No expense with id {args.id}", file=sys.stderr)
        sys.exit(1)
    changes: dict = {}
    if args.amount is not None:
        changes["amount"] = parse_amount(args.amount)
    if args.currency is not None:
        changes["currency"] = parse_currency(args.currency)
    if args.rate is not None:
        changes["rate"] = parse_rate(args.rate)
    if args.category is not None:
        changes["category"] = args.category.strip().title()
    if args.subcategory is not None:
        changes["subcategory"] = args.subcategory.strip()
    if args.payment is not None:
        changes["payment_method"] = args.payment.strip()
    if args.tags is not None:
        changes["tags"] = parse_tags(args.tags)
    if args.description is not None:
        changes["description"] = args.description
    if args.date is not None:
        changes["date"] = parse_date(args.date)
    if not changes:
        raise ValueError("Nothing to change; pass e.g. --rate 3.75 or --amount 20")
    updated = replace(expense, **changes)
    store.update(updated)
    print(f"Updated {describe(updated)}")


def cmd_list(store: ExpenseStore, args: argparse.Namespace) -> None:
    print_table(store.filter(month=args.month, category=args.category), args.show_in)


def cmd_summary(store: ExpenseStore, args: argparse.Namespace) -> None:
    print_summary(store.filter(month=args.month), args.show_in)


def cmd_delete(store: ExpenseStore, args: argparse.Namespace) -> None:
    if store.delete(args.id):
        print(f"Deleted expense {args.id}")
    else:
        print(f"No expense with id {args.id}", file=sys.stderr)
        sys.exit(1)


def cmd_export(store: ExpenseStore, args: argparse.Namespace) -> None:
    expenses = store.filter(month=args.month)
    export_csv(expenses, Path(args.output))
    print(f"Exported {len(expenses)} expenses to {args.output}")


def cmd_income_add(store: ExpenseStore, args: argparse.Namespace) -> None:
    income = Income(
        amount=parse_amount(args.amount),
        source=args.source.strip().title(),
        currency=parse_currency(args.currency),
        rate=resolve_rate(store, args.rate),
        description=args.description or "",
        date=parse_date(args.date),
    )
    store.add_income(income)
    print(f"Added income {format_money(income.amount_pen, 'PEN')} / {format_money(income.amount_usd, 'USD')} "
          f"({income.source}) on {income.date} [id {income.id}]")


def cmd_income_list(store: ExpenseStore, args: argparse.Namespace) -> None:
    incomes = sorted((i for i in store.load_incomes() if not args.month or month_key(i.date) == args.month),
                     key=lambda i: i.date)
    if not incomes:
        print("No income found.")
        return
    for i in incomes:
        print(f"{i.id:<9}{i.date.isoformat():<12}{i.source[:15]:<16}"
              f"{format_money(i.amount_in(args.show_in), args.show_in):>16}  {i.description}")
    total, _ = total_in(incomes, args.show_in)
    print(f"{'Total':<37}{format_money(total, args.show_in):>16}")


def cmd_budget_set(store: ExpenseStore, args: argparse.Namespace) -> None:
    amount = None if args.amount.lower() in ("none", "remove", "0") else parse_amount(args.amount)
    category = args.category.strip().title()
    store.set_budget(category, amount, parse_currency(args.currency))
    print(f"Budget for {category}: {format_money(amount, parse_currency(args.currency)) if amount else 'removed'}")


def cmd_budget_list(store: ExpenseStore, args: argparse.Namespace) -> None:
    month = args.month or month_key(date.today())
    statuses = budget_statuses(store.load(), store.budgets(), month)
    if not statuses:
        print("No budgets set. Example: python -m expense_tracker budget set food 800")
        return
    print(f"Budgets for {month}")
    for s in statuses:
        marker = {"ok": " ", "warning": "!", "over": "✗"}[s.level]
        print(f"{marker} {s.budget.category[:20]:<22}{format_money(s.spent, s.budget.currency):>14} of "
              f"{format_money(s.budget.amount, s.budget.currency):<14}{s.ratio * 100:5.0f}%")


def cmd_backup(store: ExpenseStore, args: argparse.Namespace) -> None:
    print(f"Backup saved: {store.backup_now()}")


def cmd_debts(store: ExpenseStore, args: argparse.Namespace) -> None:
    debts = [d for d in load_debts(store) if args.all or not d.is_closed]
    if not debts:
        print("No open debts." + ("" if args.all else " (Use --all to include paid-off ones.)"))
        return
    summary = summarize_debts(debts, args.show_in)
    print(f"I owe {format_money(summary.i_owe, args.show_in)} · owed to me {format_money(summary.owed_to_me, args.show_in)}"
          f" · {summary.overdue} overdue · {summary.due_soon} due soon")
    print("-" * 104)
    for d in sorted(debts, key=lambda d: (STATUS_ORDER.index(d.status()), d.counterparty.lower())):
        due = d.next_due()
        due_text = f"{due[0].isoformat()} {format_money(due[1], d.currency)}" if due else ""
        print(f"{DIRECTION_LABELS[d.direction]:<8}{d.counterparty[:22]:<23}{format_money(d.remaining, d.currency):>15} "
              f"left of {format_money(d.amount, d.currency):<15}{STATUS_LABELS[d.status()]:<12}{due_text}")


# ---------- interactive menu ----------

def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def interactive(store: ExpenseStore) -> None:
    print(f"{APP_NAME}  (data file: {store.path})")
    menu = (
        "\n1) Add expense\n2) List expenses\n3) Summary by category\n"
        "4) Edit expense\n5) Delete expense\n6) Export to CSV\n0) Quit"
    )
    while True:
        print(menu)
        choice = input("> ").strip()
        try:
            if choice == "1":
                amount = parse_amount(prompt("Amount"))
                currency = parse_currency(prompt("Currency (PEN/USD)", DEFAULT_CURRENCY))
                last = store.last_rate()
                rate_text = prompt("Exchange rate, PEN per 1 USD", format_rate(last) if last else "")
                if not rate_text:
                    raise ValueError(NO_RATE_HELP)
                expense = Expense(
                    amount=amount,
                    currency=currency,
                    rate=parse_rate(rate_text),
                    category=prompt("Category", "Other").title(),
                    subcategory=prompt("Subcategory (optional)"),
                    payment_method=prompt("Payment method (optional)"),
                    description=prompt("Description"),
                    tags=parse_tags(prompt("Tags, comma separated (optional)")),
                    date=parse_date(prompt("Date (YYYY-MM-DD)", "today").replace("today", "")),
                )
                store.add(expense)
                print(f"Saved {describe(expense)}")
            elif choice == "2":
                month = prompt("Month (YYYY-MM, blank for all)")
                currency = parse_currency(prompt("Show in (PEN/USD)", DEFAULT_CURRENCY))
                print_table(store.filter(month=month or None), currency)
            elif choice == "3":
                month = prompt("Month (YYYY-MM, blank for all)")
                currency = parse_currency(prompt("Show in (PEN/USD)", DEFAULT_CURRENCY))
                print_summary(store.filter(month=month or None), currency)
            elif choice == "4":
                expense = store.get(prompt("Expense id"))
                if expense is None:
                    print("Not found.")
                    continue
                print("Press Enter to keep the current value.")
                rate_text = prompt("Exchange rate, PEN per 1 USD", "" if expense.rate is None else format_rate(expense.rate))
                updated = replace(
                    expense,
                    amount=parse_amount(prompt("Amount", f"{expense.amount:.2f}")),
                    currency=parse_currency(prompt("Currency (PEN/USD)", expense.currency)),
                    rate=parse_rate(rate_text) if rate_text else None,
                    category=prompt("Category", expense.category).title(),
                    subcategory=prompt("Subcategory", expense.subcategory),
                    payment_method=prompt("Payment method", expense.payment_method),
                    description=prompt("Description", expense.description),
                    tags=parse_tags(prompt("Tags", ", ".join(expense.tags))),
                    date=parse_date(prompt("Date (YYYY-MM-DD)", expense.date.isoformat())),
                )
                store.update(updated)
                print(f"Updated {describe(updated)}")
            elif choice == "5":
                expense_id = prompt("Expense id")
                print("Deleted." if store.delete(expense_id) else "Not found.")
            elif choice == "6":
                path = prompt("Output file", "expenses.csv")
                expenses = store.filter()
                export_csv(expenses, Path(path))
                print(f"Exported {len(expenses)} expenses to {path}")
            elif choice in ("0", "q", "quit", "exit"):
                return
            else:
                print("Unknown option.")
        except ValueError as exc:
            print(f"Error: {exc}")


# ---------- entry point ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expense_tracker",
        description="Track personal expenses in a local file. Run with no arguments for an interactive menu. "
                    "For the desktop window, run main.py.",
    )
    parser.add_argument("-u", "--user", help="User name or id (default: the last user you used)")
    parser.add_argument("--file", help="Use this data file directly instead of a user's data")
    sub = parser.add_subparsers(dest="command")
    currency = dict(choices=CURRENCIES, type=str.upper)
    show_in = dict(choices=CURRENCIES, default=DEFAULT_CURRENCY, type=str.upper,
                   help="Currency to show amounts in (default: PEN)")

    def expense_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("-s", "--subcategory", help="e.g. Taxi")
        p.add_argument("-p", "--payment", help="Payment method, e.g. Yape")
        p.add_argument("-t", "--tags", help="Comma separated, e.g. 'work, cusco-trip'")
        p.add_argument("-d", "--description", help="Optional note")
        p.add_argument("--date", help="Date as YYYY-MM-DD (default: today)")

    p = sub.add_parser("add", help="Add an expense")
    p.add_argument("amount", help="Amount, e.g. 12.50")
    p.add_argument("category", help="Category, e.g. food, transport")
    expense_options(p)
    p.add_argument("--currency", default=DEFAULT_CURRENCY, help="Currency of the amount (default: PEN)", **currency)
    p.add_argument("--rate", help="Exchange rate, PEN per 1 USD (default: the last rate you used)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("edit", help="Change an expense by id (only the options you pass are changed)")
    p.add_argument("id")
    p.add_argument("--amount")
    p.add_argument("--category")
    expense_options(p)
    p.add_argument("--currency", **currency)
    p.add_argument("--rate", help="Exchange rate, PEN per 1 USD")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("list", help="List expenses")
    p.add_argument("-m", "--month", help="Only this month, YYYY-MM")
    p.add_argument("-c", "--category", help="Only this category")
    p.add_argument("--in", dest="show_in", **show_in)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("summary", help="Totals per category and subcategory")
    p.add_argument("-m", "--month", help="Only this month, YYYY-MM")
    p.add_argument("--in", dest="show_in", **show_in)
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("delete", help="Delete an expense by id")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("export", help="Export expenses to CSV")
    p.add_argument("output", help="CSV file to write")
    p.add_argument("-m", "--month", help="Only this month, YYYY-MM")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("income", help="Add or list income")
    income = p.add_subparsers(dest="income_command", required=True)
    q = income.add_parser("add", help="Add income")
    q.add_argument("amount")
    q.add_argument("source", help="e.g. salary, freelance")
    q.add_argument("-d", "--description")
    q.add_argument("--date", help="YYYY-MM-DD (default: today)")
    q.add_argument("--currency", default=DEFAULT_CURRENCY, **currency)
    q.add_argument("--rate", help="Exchange rate, PEN per 1 USD (default: the last rate you used)")
    q.set_defaults(func=cmd_income_add)
    q = income.add_parser("list", help="List income")
    q.add_argument("-m", "--month", help="Only this month, YYYY-MM")
    q.add_argument("--in", dest="show_in", **show_in)
    q.set_defaults(func=cmd_income_list)

    p = sub.add_parser("budget", help="Monthly budgets per category")
    budget = p.add_subparsers(dest="budget_command", required=True)
    q = budget.add_parser("set", help="Set a budget (use 'none' as amount to remove it)")
    q.add_argument("category")
    q.add_argument("amount")
    q.add_argument("--currency", default=DEFAULT_CURRENCY, **currency)
    q.set_defaults(func=cmd_budget_set)
    q = budget.add_parser("list", help="Show spending vs budget")
    q.add_argument("-m", "--month", help="YYYY-MM (default: this month)")
    q.set_defaults(func=cmd_budget_list)

    p = sub.add_parser("backup", help="Save a copy of this user's data in their backups folder")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("debts", help="List debts (what you owe and what you're owed)")
    p.add_argument("--all", action="store_true", help="Include paid-off debts")
    p.add_argument("--in", dest="show_in", **show_in)
    p.set_defaults(func=cmd_debts)

    p = sub.add_parser("users", help="List or add users (each has separate data)")
    users = p.add_subparsers(dest="users_command", required=True)
    q = users.add_parser("list", help="List users")
    q.set_defaults(func=cmd_users_list)
    q = users.add_parser("add", help="Create a user")
    q.add_argument("name")
    q.add_argument("--type", default="Personal", help=", ".join(t for t, _, _ in USER_TYPES))
    q.add_argument("--icon", help="An emoji (default: depends on the type)")
    q.set_defaults(func=cmd_users_add)

    return parser


def cmd_users_list(registry: UserRegistry, args: argparse.Namespace) -> None:
    last = registry.last_user()
    for user in registry.users():
        marker = "*" if last and user.id == last.id else " "
        print(f"{marker} {user.id}  {user.icon} {user.name:<24}{user.type}")
    print("(* = used by default; pick another with --user NAME)")


def cmd_users_add(registry: UserRegistry, args: argparse.Namespace) -> None:
    user = registry.create(args.name, args.type.title(), args.icon)
    print(f"Created user {user.icon} {user.name} ({user.type}) [id {user.id}]")


def open_store(args: argparse.Namespace) -> ExpenseStore:
    """The data of --file / EXPENSES_FILE if given, otherwise of --user (default: last used user)."""
    if args.file or os.environ.get("EXPENSES_FILE"):
        return ExpenseStore(Path(args.file) if args.file else None)
    registry = UserRegistry()
    registry.ensure_ready()
    user = registry.find(args.user) if args.user else registry.last_user()
    if user is None:
        raise ValueError(f"No user called {args.user!r}. See: python -m expense_tracker users list")
    return registry.store_for(user)


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # emoji/› on older Windows consoles
    args = build_parser().parse_args(argv)
    try:
        if args.command == "users":
            registry = UserRegistry()
            registry.ensure_ready()
            args.func(registry, args)
            return
        store = open_store(args)
        if args.command is None:
            try:
                interactive(store)
            except (KeyboardInterrupt, EOFError):
                print()
            return
        args.func(store, args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
