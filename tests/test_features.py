import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.catalog import category_look, default_categories
from expense_tracker.importer import (
    ImportOptions,
    build_expenses,
    guess_columns,
    parse_amount_flexible,
    parse_date_flexible,
    read_csv,
)
from expense_tracker.reports import (
    balance,
    budget_statuses,
    by_subcategory,
    change_pct,
    compare_with_previous_month,
    format_change,
    last_n_months,
    matches,
    monthly_totals,
)
from expense_tracker.storage import (
    Expense,
    ExpenseStore,
    Income,
    RecurringExpense,
    add_months,
    parse_tags,
)

D = Decimal


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = ExpenseStore(self.dir / "expenses.json")

    def tearDown(self):
        self.tmp.cleanup()


class DataTest(StoreTestCase):
    def test_upgrades_version_2_file(self):
        self.store.path.write_text(json.dumps({
            "version": 2, "settings": {"last_rate": "3.15"},
            "expenses": [{"id": "d3e6d47a", "date": "2026-09-29", "category": "Food", "description": "sqw",
                          "currency": "PEN", "amount": "213.00", "rate": "3.1500",
                          "amount_pen": "213.00", "amount_usd": "67.62"}],
        }), encoding="utf-8")
        [e] = self.store.load()
        self.assertEqual((e.subcategory, e.payment_method, e.tags, e.receipt), ("", "", [], None))
        self.store.add(Expense(D("1"), "Food", rate=D("3.2")))
        doc = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["version"], 3)
        self.assertEqual(doc["expenses"][0]["id"], "d3e6d47a")
        self.assertEqual(self.store.last_rate(), D("3.2"))

    def test_new_fields_round_trip(self):
        e = self.store.add(Expense(D("25"), "Transport", subcategory="Taxi", payment_method="Yape",
                                   tags=parse_tags("Work, #Lima trip"), rate=D("3.7")))
        loaded = self.store.get(e.id)
        self.assertEqual((loaded.subcategory, loaded.payment_method, loaded.tags),
                         ("Taxi", "Yape", ["work", "lima-trip"]))

    def test_income(self):
        inc = self.store.add_income(Income(D("3000"), "Salary", currency="USD", rate=D("3.75")))
        self.assertEqual(self.store.load_incomes()[0].amount_pen, D("11250.00"))
        self.assertEqual(self.store.last_rate(), D("3.75"))
        inc.description = "September"
        self.assertTrue(self.store.update_income(inc))
        self.assertEqual(self.store.load_incomes()[0].description, "September")
        self.assertTrue(self.store.delete_income(inc.id))
        self.assertEqual(self.store.load_incomes(), [])

    def test_categories_default_then_custom_and_rename(self):
        self.assertEqual(self.store.categories()[0].name, "Food")
        self.store.add(Expense(D("10"), "Transport", subcategory="Taxi", rate=D("3.7")))
        self.store.set_budget("Transport", D("300"))
        self.store.save_recurring(RecurringExpense(D("50"), "Transport", subcategory="Taxi"))
        self.assertEqual(self.store.rename_category("transport", "Getting around"), 1)
        self.assertEqual(self.store.load()[0].category, "Getting around")
        self.assertIn("Getting around", self.store.budgets())
        self.assertEqual(self.store.recurring()[0].category, "Getting around")
        self.assertTrue(any(c.name == "Getting around" for c in self.store.categories()))
        self.assertEqual(self.store.rename_subcategory("Getting around", "Taxi", "Cab"), 1)
        self.assertEqual(self.store.load()[0].subcategory, "Cab")
        cat = next(c for c in self.store.categories() if c.name == "Getting around")
        self.assertIsNotNone(cat.subcategory("Cab"))

    def test_rename_payment_method(self):
        self.store.add(Expense(D("10"), "Food", payment_method="Yape", rate=D("3.7")))
        self.assertEqual(self.store.rename_value(("expenses", "recurring"), "payment_method", "yape", "Yape app"), 1)
        self.assertEqual(self.store.load()[0].payment_method, "Yape app")

    def test_budgets(self):
        self.store.set_budget("Food", D("800"))
        self.store.set_budget("food", D("900"), "USD")  # replaces, case-insensitive
        budgets = self.store.budgets()
        self.assertEqual(list(budgets), ["food"])
        self.assertEqual((budgets["food"].amount, budgets["food"].currency), (D("900.00"), "USD"))
        self.store.set_budget("Food", None)
        self.assertEqual(self.store.budgets(), {})

    def test_budget_with_months_that_differ(self):
        # A mortgage: usually S/ 3,000, but nothing in November
        self.store.set_budget("Mortgage", D("3000"))
        self.store.set_budget("Mortgage", D("0"), month="2026-11")
        b = self.store.budgets()["Mortgage"]
        self.assertEqual((b.amount_for("2026-10"), b.amount_for("2026-11")), (D("3000.00"), D("0.00")))
        # Changing the usual amount keeps the exceptions; removing an exception goes back to usual
        self.store.set_budget("mortgage", D("3200"))
        b = self.store.budgets()["mortgage"]
        self.assertEqual((b.amount_for("2026-10"), b.amount_for("2026-11")), (D("3200.00"), D("0.00")))
        self.store.set_budget("Mortgage", None, month="2026-11")  # keeps the saved spelling ("mortgage")
        self.assertEqual(self.store.budgets()["mortgage"].months, {})
        # Removing the budget removes everything
        self.store.set_budget("Mortgage", D("0"), month="2026-12")
        self.store.set_budget("Mortgage", None)
        self.assertEqual(self.store.budgets(), {})
        # A budget for just one month: every other month is 0
        self.store.set_budget("Taxes", D("450"), month="2027-04")
        t = self.store.budgets()["Taxes"]
        self.assertEqual((t.amount, t.amount_for("2027-04")), (D("0.00"), D("450.00")))
        self.store.set_budget("Nothing", None, month="2027-04")  # removing an exception that doesn't exist
        self.assertNotIn("Nothing", self.store.budgets())

    def test_budget_amounts_allow_zero(self):
        from expense_tracker.storage import Budget, parse_budget_amount
        self.assertEqual([parse_budget_amount(v) for v in ("0", "0,00", "12,5")], [D("0.00"), D("0.00"), D("12.50")])
        for bad in ("-1", "abc", ""):
            with self.assertRaises(ValueError):
                parse_budget_amount(bad)
        budget = Budget("Mortgage", D("3000.00"), "PEN", {"2026-11": D("0.00")})
        self.assertEqual(Budget.from_dict("Mortgage", budget.to_dict()), budget)
        self.assertNotIn("months", Budget("Food", D("1")).to_dict())  # same file format as before when unused

    def test_daily_backup_and_manual_backup(self):
        self.store.add(Expense(D("1"), "Food", rate=D("3.7")))
        self.assertFalse(self.store.backups_dir.exists())  # nothing to back up before the first save
        self.store.add(Expense(D("2"), "Food", rate=D("3.7")))
        daily = list(self.store.backups_dir.glob("expenses-*.json"))
        self.assertEqual(len(daily), 1)
        self.assertEqual(len(json.loads(daily[0].read_text(encoding="utf-8"))["expenses"]), 1)
        self.store.add(Expense(D("3"), "Food", rate=D("3.7")))
        self.assertEqual(len(list(self.store.backups_dir.glob("expenses-*.json"))), 1)  # once per day
        manual = self.store.backup_now()
        self.assertEqual(len(json.loads(manual.read_text(encoding="utf-8"))["expenses"]), 3)

    def test_receipts(self):
        e = self.store.add(Expense(D("10"), "Food", rate=D("3.7"), date=date(2026, 9, 3)))
        source = self.dir / "photo.JPG"
        source.write_bytes(b"fake image")
        e = self.store.attach_receipt(e.id, source)
        self.assertEqual(e.receipt, f"2026-09-03_{e.id}.jpg")
        self.assertEqual(self.store.receipt_path(self.store.get(e.id)).read_bytes(), b"fake image")
        self.store.remove_receipt(e.id)
        self.assertIsNone(self.store.get(e.id).receipt)
        self.assertTrue((self.store.receipts_dir / "removed" / f"2026-09-03_{e.id}.jpg").exists())
        self.store.attach_receipt(e.id, source)
        self.store.delete(e.id)  # deleting the expense keeps the file in receipts/removed
        self.assertEqual(list(self.store.receipts_dir.glob("*.jpg")), [])


class RecurringTest(StoreTestCase):
    def test_due_months_and_apply(self):
        rent = RecurringExpense(D("950"), "Housing", subcategory="Rent", day=5, start_month="2026-08")
        netflix = RecurringExpense(D("10"), "Entertainment", currency="USD", day=28, start_month="2026-09")
        self.store.save_recurring(rent)
        self.store.save_recurring(netflix)
        today = date(2026, 9, 20)
        due = [(r.id, m) for r, m in self.store.due_recurring(today)]
        self.assertEqual(due, [(rent.id, "2026-08"), (rent.id, "2026-09")])  # netflix not due until the 28th
        created = self.store.apply_recurring([(rent.id, "2026-09")], [(rent.id, "2026-08")], D("3.7"))
        self.assertEqual([(e.date, e.amount, e.recurring_id) for e in created], [(date(2026, 9, 5), D("950.00"), rent.id)])
        self.assertEqual(self.store.due_recurring(today), [])
        self.assertEqual(len(self.store.due_recurring(date(2026, 9, 28))), 1)
        self.assertEqual(self.store.last_rate(), D("3.7"))

    def test_paused_and_day_validation(self):
        r = RecurringExpense(D("5"), "Other", day=1, start_month="2026-01", active=False)
        self.assertEqual(r.due_months(date(2026, 9, 1)), [])
        for bad_day in (0, 32):
            with self.assertRaises(ValueError):
                RecurringExpense(D("5"), "Other", day=bad_day)

    def test_end_of_month_days(self):
        # Day 31 = the last day of every month; day 30 becomes 28/29 Feb.
        r = RecurringExpense(D("100"), "Housing", day=31, start_month="2027-01")
        self.assertEqual([r.occurrence_date(m) for m in ("2027-01", "2027-02", "2027-04", "2028-02")],
                         [date(2027, 1, 31), date(2027, 2, 28), date(2027, 4, 30), date(2028, 2, 29)])
        self.assertEqual(RecurringExpense(D("1"), "Other", day=30).occurrence_date("2027-02"), date(2027, 2, 28))
        # It's due on the last day of a short month, not skipped until the next one
        r.handled_through = "2027-01"
        self.assertEqual(r.due_months(date(2027, 2, 27)), [])
        self.assertEqual(r.due_months(date(2027, 2, 28)), ["2027-02"])
        self.assertEqual(r.due_months(date(2027, 4, 29)), ["2027-02", "2027-03"])
        self.assertEqual(r.due_months(date(2027, 4, 30)), ["2027-02", "2027-03", "2027-04"])


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.expenses = [
            Expense(D("100"), "Food", subcategory="Restaurant", date=date(2026, 8, 3), rate=D("4")),
            Expense(D("150"), "Food", subcategory="Coffee", date=date(2026, 9, 3), rate=D("3")),
            Expense(D("50"), "Food", date=date(2026, 9, 4), rate=D("5"), tags=["work"]),
            Expense(D("40"), "Transport", subcategory="Taxi", description="Airport ride", date=date(2026, 9, 5),
                    rate=D("4"), payment_method="Yape"),
        ]

    def test_subcategories_and_comparison(self):
        self.assertEqual(by_subcategory(self.expenses, "food", "PEN"), {"Coffee": D("150"), "Restaurant": D("100"), "": D("50")})
        comparison = compare_with_previous_month(self.expenses, "2026-09", "PEN")
        self.assertEqual(comparison["Food"], (D("200"), D("100")))
        self.assertEqual(format_change(change_pct(D("200"), D("100"))), "▲ 100%")
        self.assertEqual(format_change(change_pct(D("40"), D("0")), new=True), "new")

    def test_budget_statuses(self):
        from expense_tracker.storage import Budget
        budgets = {"Food": Budget("Food", D("220")), "Transport": Budget("Transport", D("100"), "USD")}
        statuses = {s.budget.category: s for s in budget_statuses(self.expenses, budgets, "2026-09")}
        self.assertEqual((statuses["Food"].spent, statuses["Food"].level), (D("200"), "warning"))
        self.assertEqual((statuses["Transport"].spent, statuses["Transport"].level), (D("10.00"), "ok"))

    def test_zero_and_month_specific_budgets(self):
        from expense_tracker.storage import Budget
        budgets = {
            "Food": Budget("Food", D("1000"), months={"2026-09": D("0")}),  # September: 0, and S/ 200 spent
            "Health": Budget("Health", D("0")),  # 0 and nothing spent
            "Transport": Budget("Transport", D("50"), months={"2026-08": D("0")}),  # exception in another month
        }
        statuses = budget_statuses(self.expenses, budgets, "2026-09")
        food, transport, health = statuses  # over a 0 budget first, nothing planned last
        self.assertEqual([s.budget.category for s in statuses], ["Food", "Transport", "Health"])
        self.assertEqual((food.limit, food.is_exception, food.ratio, food.level, food.fill),
                         (D("0"), True, None, "over", 1.0))
        self.assertEqual((health.limit, health.ratio, health.level, health.fill, health.remaining),
                         (D("0"), None, "ok", 0.0, D("0")))
        self.assertEqual((transport.limit, transport.is_exception, transport.level), (D("50"), False, "warning"))

    def test_monthly_totals_and_balance(self):
        months = last_n_months("2026-09", 3)
        self.assertEqual(months, ["2026-07", "2026-08", "2026-09"])
        self.assertEqual(monthly_totals(self.expenses, months, "USD"),
                         {"2026-07": D("0"), "2026-08": D("25.00"), "2026-09": D("70.00")})
        incomes = [Income(D("1000"), "Salary", date=date(2026, 9, 1), rate=D("4"))]
        self.assertEqual(balance(self.expenses, incomes, "2026-09", "PEN"), (D("1000"), D("240"), D("760")))

    def test_suggest_budget_category(self):
        from expense_tracker.reports import suggest_budget_category
        from expense_tracker.storage import Budget
        catalog = ["Food", "Groceries", "Transport", "Housing"]
        # Most spending in Sep without a budget: Food (S/ 200) beats Transport (S/ 40)
        self.assertEqual(suggest_budget_category(catalog, self.expenses, {}, "2026-09"), ("Food", True))
        food = {"Food": Budget("Food", D("300"))}
        self.assertEqual(suggest_budget_category(catalog, self.expenses, food, "2026-09"), ("Transport", True))
        # No spending without a budget: first catalog category that has none
        both = {**food, "Transport": Budget("Transport", D("100"))}
        self.assertEqual(suggest_budget_category(catalog, self.expenses, both, "2026-09"), ("Groceries", False))
        everything = {c: Budget(c, D("1")) for c in catalog}
        self.assertEqual(suggest_budget_category(catalog, self.expenses, everything, "2026-09"), ("Food", False))
        self.assertEqual(suggest_budget_category([], [], {}, "2026-09"), ("", False))

    def test_recent_tags(self):
        from expense_tracker.reports import recent_tags
        expenses = [
            Expense(D("1"), "Food", date=date(2026, 9, 1), tags=["work", "lunch"]),
            Expense(D("1"), "Food", date=date(2026, 9, 20), tags=["cusco-trip"]),
            Expense(D("1"), "Food", date=date(2026, 9, 10), tags=["work"]),
            Expense(D("1"), "Food", date=date(2026, 9, 20), tags=["airport"]),
        ]
        self.assertEqual(recent_tags(expenses), ["airport", "cusco-trip", "work", "lunch"])
        self.assertEqual(recent_tags([]), [])

    def test_search(self):
        taxi = self.expenses[3]
        self.assertTrue(matches(taxi, "airport"))
        self.assertTrue(matches(taxi, "yape taxi"))
        self.assertFalse(matches(taxi, "airport coffee"))
        self.assertTrue(matches(self.expenses[2], "#work"))
        self.assertFalse(matches(taxi, "#work"))

    def test_year_periods(self):
        from expense_tracker.reports import in_month, is_year, previous_period
        extra = Expense(D("70"), "Food", date=date(2025, 12, 30), rate=D("4"))
        expenses = [*self.expenses, extra]
        self.assertEqual(len(in_month(expenses, "2026")), 4)
        self.assertEqual(in_month(expenses, "2025"), [extra])
        self.assertEqual(len(in_month(expenses, "2026-09")), 3)
        self.assertEqual((is_year("2026"), is_year("2026-09"), is_year(None)), (True, False, False))
        self.assertEqual((previous_period("2026"), previous_period("2026-01")), ("2025", "2025-12"))
        self.assertEqual(compare_with_previous_month(expenses, "2026", "PEN")["Food"], (D("300"), D("70")))

    def test_add_months(self):
        self.assertEqual(add_months("2026-12", 1), "2027-01")
        self.assertEqual(add_months("2026-01", -1), "2025-12")

    def test_subcategory_own_color(self):
        from expense_tracker.catalog import Category, Item
        housing = Category("Housing", "🏠", "#8d6cab", [Item("Mortgage", "🏠", "#ff0000"), Item("Property tax", "🏠")])
        self.assertEqual(category_look([housing], "Housing", "Mortgage"), ("🏠", "#ff0000"))
        self.assertEqual(category_look([housing], "Housing", "Property tax"), ("🏠", "#8d6cab"))  # follows category
        again = Category.from_dict(housing.to_dict())
        self.assertEqual(again, housing)
        self.assertNotIn("color", Item("Cash", "💵").to_dict())  # payment methods etc. stay as before

    def test_category_look_fallbacks(self):
        cats = default_categories()
        self.assertEqual(category_look(cats, "transport", "Gasoline")[0], "⛽")
        self.assertEqual(category_look(cats, "Transport", "Unknown")[0], "🚕")
        icon, color = category_look(cats, "Mystery")
        self.assertEqual(icon, "🏷")
        self.assertEqual(color, category_look(cats, "mystery")[1])  # stable


class ImporterTest(StoreTestCase):
    def test_amount_formats(self):
        cases = {"S/ -1.234,56": D("-1234.56"), "(45.00)": D("-45.00"), "1,234.56": D("1234.56"),
                 "12,5": D("12.5"), "1.234.567": D("1234567"), "US$ 20": D("20"), "-7,00": D("-7.00")}
        for text, expected in cases.items():
            self.assertEqual(parse_amount_flexible(text), expected, text)

    def test_dates(self):
        self.assertEqual(parse_date_flexible("05/09/2026"), date(2026, 9, 5))  # day first
        self.assertEqual(parse_date_flexible("2026-09-05 13:22"), date(2026, 9, 5))
        self.assertEqual(parse_date_flexible("09/05/2026", "%m/%d/%Y"), date(2026, 9, 5))
        with self.assertRaises(ValueError):
            parse_date_flexible("yesterday")

    def test_bank_statement_import(self):
        csv_path = self.dir / "banco.csv"
        csv_path.write_bytes(
            "Fecha;Descripción;Monto;Categoría\n"
            "05/09/2026;PLAZA VEA;-120,50;supermercado\n"
            "06/09/2026;SUELDO;3.500,00;\n"
            "07/09/2026;TAXI BEAT;-15,00;transport\n"
            "bad;ROW;-1;\n".encode("cp1252")
        )
        data = read_csv(csv_path)
        self.assertEqual((data.delimiter, data.headers[1]), (";", "Descripción"))
        cols = guess_columns(data.headers)
        self.assertEqual((cols["date"], cols["description"], cols["amount"], cols["category"]), (0, 1, 2, 3))
        existing = [Expense(D("15.00"), "Transport", "TAXI BEAT", date(2026, 9, 7))]
        opts = ImportOptions(date_col=0, amount_col=2, description_col=1, category_col=3, sign="negative",
                             default_category="Other", rate=D("3.7"), payment_method="Debit card", tags=["bank"])
        result = build_expenses(data, opts, existing, default_categories())
        self.assertEqual(len(result.expenses), 1)
        e = result.expenses[0]
        self.assertEqual((e.date, e.amount, e.category, e.description, e.payment_method, e.tags),
                         (date(2026, 9, 5), D("120.50"), "Supermercado", "PLAZA VEA", "Debit card", ["bank"]))
        self.assertEqual((result.duplicates, result.skipped_by_sign, len(result.errors)), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
