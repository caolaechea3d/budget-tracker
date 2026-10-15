"""Create a data folder full of made-up data, for screenshots or for trying the app.

    python tools/demo_data.py FOLDER
    set BUDGET_TRACKER_DATA=FOLDER
    python main.py

Dates are relative to today, so the demo always looks current. Nothing here is real.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from expense_tracker.debts import OWED, Debt, DebtPayment, save_debt  # noqa: E402
from expense_tracker.storage import Expense, Income, RecurringExpense, add_months, month_key  # noqa: E402
from expense_tracker.users import UserRegistry  # noqa: E402

D = Decimal
RATE = D("3.74")

# (day, amount, category, subcategory, payment method, description, tags) — repeated every month
MONTHLY = [
    (2, "1200", "Housing", "Rent", "Bank transfer", "Rent", ""),
    (4, "142.30", "Groceries", "Supermarket", "Debit card", "Weekly shop", ""),
    (5, "18", "Transport", "Taxi", "Yape", "Taxi to work", "work"),
    (7, "86.50", "Groceries", "Market", "Cash", "Mercado", ""),
    (9, "12.50", "Food", "Coffee", "Yape", "Coffee", ""),
    (11, "119.90", "Utilities", "Internet", "Debit card", "Fiber internet", ""),
    (12, "140", "Transport", "Gasoline", "Credit card", "Full tank", ""),
    (14, "158.70", "Groceries", "Supermarket", "Debit card", "Weekly shop", ""),
    (15, "96.40", "Utilities", "Electricity", "Debit card", "Electricity bill", ""),
    (17, "64", "Food", "Delivery", "Credit card", "Pizza night", ""),
    (19, "45", "Food", "Restaurant", "Cash", "Lunch with Sam", ""),
    (20, "39.90", "Entertainment", "Streaming", "Credit card", "Netflix", ""),
    (22, "131.20", "Groceries", "Supermarket", "Debit card", "Weekly shop", ""),
    (24, "35", "Transport", "Bus / Metro", "Debit card", "Metro card top-up", ""),
    (26, "59.90", "Utilities", "Phone", "Debit card", "Phone plan", ""),
    (27, "28", "Food", "Coffee", "Yape", "Coffee & cake", ""),
]
# Extra expenses in specific months: (months ago, day, amount, currency, category, subcategory, payment, description, tags)
EXTRAS = [
    (3, 10, "189", "PEN", "Shopping", "Clothes", "Credit card", "Running shoes", ""),
    (2, 16, "48.50", "PEN", "Health", "Pharmacy", "Cash", "Pharmacy", ""),
    (2, 21, "75", "PEN", "Entertainment", "Events", "Credit card", "Concert", ""),
    (1, 8, "120", "USD", "Travel", "Flights", "Credit card", "Flight to Cusco", "cusco-trip"),
    (1, 9, "320", "PEN", "Travel", "Lodging", "Credit card", "Hostel, 3 nights", "cusco-trip"),
    (1, 10, "150", "PEN", "Travel", "Tours", "Cash", "Sacred Valley tour", "cusco-trip"),
    (1, 23, "260", "PEN", "Health", "Dentist", "Debit card", "Cleaning", ""),
    (0, 3, "35", "PEN", "Personal care", "Haircut", "Cash", "Haircut", ""),
]


def on(month: str, day: int) -> date:
    year, mon = map(int, month.split("-"))
    return date(year, mon, day)


def create_demo(folder: Path, today: date | None = None) -> None:
    today = today or date.today()
    this_month = month_key(today)

    def ago(n: int) -> str:
        return add_months(this_month, -n)

    months = [ago(n) for n in range(11, -1, -1)]  # a year of history, oldest first
    registry = UserRegistry(folder)
    registry.ensure_ready()
    alex = registry.last_user()
    alex.name = "Alex"
    registry.update(alex)
    store = registry.store_for(alex)

    expenses = []
    for i, month in enumerate(months):
        swing = D(1) + D("0.07") * (D((i * 5) % 4) - D("1.5"))  # spending varies a little month to month
        for day, amount, cat, sub, pay, desc, tags in MONTHLY:
            value = D(amount) if cat in ("Housing", "Utilities") or sub == "Streaming" else D(amount) * swing
            if on(month, day) <= today:
                expenses.append(Expense(value.quantize(D("0.01")), cat, desc, on(month, day), rate=RATE,
                                        subcategory=sub, payment_method=pay, tags=[tags] if tags else []))
    for months_back, day, amount, currency, cat, sub, pay, desc, tags in EXTRAS:
        when = on(ago(months_back), day)
        if when <= today:
            expenses.append(Expense(D(amount), cat, desc, when, currency=currency, rate=RATE, subcategory=sub,
                                    payment_method=pay, tags=[tags] if tags else []))
    store.add_many(expenses)

    for month in months:
        store.add_income(Income(D("5200"), "Salary", "Monthly salary", on(month, 1), rate=RATE))
    store.add_income(Income(D("400"), "Freelance", "Logo design", on(ago(1), 18), currency="USD", rate=RATE))
    store.add_income(Income(D("650"), "Freelance", "Website", on(ago(6), 12), currency="USD", rate=RATE))

    # One budget comfortably under, one close to its limit and one over, to show the colors.
    for category, amount in (("Food", "250"), ("Groceries", "440"), ("Transport", "150"), ("Entertainment", "120")):
        store.set_budget(category, D(amount))

    next_month = add_months(this_month, 1)  # already handled this month, so no "due" prompt on opening
    for amount, cat, sub, desc, day in (("1200", "Housing", "Rent", "Rent", 2),
                                        ("39.90", "Entertainment", "Streaming", "Netflix", 20),
                                        ("119.90", "Utilities", "Internet", "Fiber internet", 11)):
        store.save_recurring(RecurringExpense(D(amount), cat, subcategory=sub, description=desc, day=day,
                                              payment_method="Debit card", start_month=next_month,
                                              handled_through=this_month))

    laptop = Debt("Saga card", D("1200"), counterparty_type="Credit card", description="Laptop in 6 installments",
                  rate=RATE, start_date=on(ago(3), 20), installments=6, payment_day=5)
    laptop.payments = [DebtPayment(D("200"), d, rate=RATE) for d in laptop.schedule() if d <= today]
    save_debt(store, laptop)
    save_debt(store, Debt("Bank loan", D("1500"), counterparty_type="Bank", currency="USD", rate=RATE,
                          description="Personal loan", start_date=on(ago(3), 1),
                          deadline=date.fromordinal(today.toordinal() + 5),
                          payments=[DebtPayment(D("500"), on(ago(1), 1), rate=RATE)]))
    save_debt(store, Debt("Uncle Tom", D("600"), counterparty_type="Family", description="Help with the deposit",
                          rate=RATE, start_date=on(ago(2), 12),
                          payments=[DebtPayment(D("150"), on(this_month, 1), rate=RATE)]))
    save_debt(store, Debt("Sam", D("180"), direction=OWED, counterparty_type="Friend", rate=RATE,
                          description="Concert tickets", start_date=on(ago(1), 21),
                          deadline=date.fromordinal(today.toordinal() + 30)))

    home = registry.create("Home", "Family")
    home_store = registry.store_for(home)
    home_store.add_many([Expense(D("320"), "Groceries", "Big shop", on(this_month, 1), rate=RATE,
                                 subcategory="Supermarket")])
    work = registry.create("Side business", "Business")
    registry.store_for(work).add_income(Income(D("900"), "Freelance", "Client project", on(this_month, 2), rate=RATE))
    registry.set_last_user(alex.id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = Path(sys.argv[1])
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} isn't empty; choose a new folder so no real data is touched.")
    create_demo(target)
    print(f"Demo data created in {target}")
