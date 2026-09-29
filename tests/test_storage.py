import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.storage import (
    Expense,
    ExpenseStore,
    format_rate,
    parse_amount,
    parse_currency,
    parse_rate,
    summarize_by_category,
    total_in,
)


class ExpenseStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExpenseStore(Path(self.tmp.name) / "expenses.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_when_no_file(self):
        self.assertEqual(self.store.load(), [])

    def test_add_persists_to_disk(self):
        e = self.store.add(Expense(Decimal("12.50"), "Food", "lunch", date(2026, 9, 1)))
        reloaded = ExpenseStore(self.store.path).load()
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].id, e.id)
        self.assertEqual(reloaded[0].amount, Decimal("12.50"))
        self.assertEqual(reloaded[0].date, date(2026, 9, 1))

    def test_delete(self):
        e = self.store.add(Expense(Decimal("5"), "Food"))
        self.assertTrue(self.store.delete(e.id))
        self.assertFalse(self.store.delete(e.id))
        self.assertEqual(self.store.load(), [])

    def test_filter_by_month_and_category(self):
        self.store.add(Expense(Decimal("10"), "Food", date=date(2026, 8, 30)))
        self.store.add(Expense(Decimal("20"), "Food", date=date(2026, 9, 2)))
        self.store.add(Expense(Decimal("30"), "Rent", date=date(2026, 9, 1)))
        self.assertEqual(len(self.store.filter(month="2026-09")), 2)
        self.assertEqual(len(self.store.filter(month="2026-09", category="food")), 1)

    def test_summary(self):
        expenses = [Expense(Decimal("10"), "Food"), Expense(Decimal("5"), "Food"), Expense(Decimal("30"), "Rent")]
        self.assertEqual(summarize_by_category(expenses), {"Rent": Decimal("30"), "Food": Decimal("15")})

    def test_parse_amount_accepts_decimal_comma(self):
        self.assertEqual(parse_amount("12,5"), Decimal("12.50"))
        self.assertEqual(parse_amount(" 7.25 "), Decimal("7.25"))

    def test_parse_amount_rejects_bad_input(self):
        for bad in ("abc", "0", "-3"):
            with self.assertRaises(ValueError):
                parse_amount(bad)


class CurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExpenseStore(Path(self.tmp.name) / "expenses.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_pen_is_default_and_converts_with_own_rate(self):
        e = Expense(Decimal("37.50"), "Food", rate=Decimal("3.75"))
        self.assertEqual(e.currency, "PEN")
        self.assertEqual(e.amount_pen, Decimal("37.50"))
        self.assertEqual(e.amount_usd, Decimal("10.00"))

    def test_usd_entry_converts_to_pen(self):
        e = Expense(Decimal("10"), "Food", currency="USD", rate=Decimal("3.7512"))
        self.assertEqual(e.amount_usd, Decimal("10"))
        self.assertEqual(e.amount_pen, Decimal("37.51"))

    def test_each_expense_keeps_its_own_rate(self):
        a = self.store.add(Expense(Decimal("100"), "Food", rate=Decimal("4")))
        b = self.store.add(Expense(Decimal("100"), "Food", rate=Decimal("2")))
        by_id = {e.id: e for e in self.store.load()}
        self.assertEqual(by_id[a.id].amount_usd, Decimal("25.00"))
        self.assertEqual(by_id[b.id].amount_usd, Decimal("50.00"))
        self.assertEqual(total_in(list(by_id.values()), "USD"), (Decimal("75.00"), 0))

    def test_last_rate_is_remembered(self):
        self.assertIsNone(self.store.last_rate())
        self.store.add(Expense(Decimal("1"), "Food", rate=Decimal("3.70")))
        self.store.add(Expense(Decimal("1"), "Food", rate=Decimal("3.81")))
        self.assertEqual(ExpenseStore(self.store.path).last_rate(), Decimal("3.81"))
        # Deleting an expense keeps the remembered rate.
        self.store.delete(self.store.load()[0].id)
        self.assertEqual(self.store.last_rate(), Decimal("3.81"))

    def test_update_replaces_expense_but_not_last_rate(self):
        e = self.store.add(Expense(Decimal("213"), "Food", rate=Decimal("3.80")))
        self.store.add(Expense(Decimal("5"), "Food", rate=Decimal("3.75")))
        edited = Expense(Decimal("200"), "Groceries", currency="USD", rate=Decimal("3.70"), date=e.date)
        edited.id = e.id
        self.assertTrue(self.store.update(edited))
        stored = self.store.get(e.id)
        self.assertEqual((stored.amount, stored.category, stored.currency, stored.rate),
                         (Decimal("200.00"), "Groceries", "USD", Decimal("3.7000")))
        self.assertEqual(len(self.store.load()), 2)
        self.assertEqual(self.store.last_rate(), Decimal("3.75"))  # editing never changes the default rate
        edited.id = "missing"
        self.assertFalse(self.store.update(edited))

    def test_format_rate(self):
        self.assertEqual(
            [format_rate(parse_rate(r)) for r in ("3.75", "3.8", "3.7512", "4")],
            ["3.75", "3.80", "3.7512", "4.00"],
        )
        self.assertEqual(format_rate(None), "—")

    def test_parse_rate(self):
        self.assertEqual(parse_rate("3,75"), Decimal("3.7500"))
        for bad in ("", "x", "0", "-1"):
            with self.assertRaises(ValueError):
                parse_rate(bad)
        with self.assertRaises(ValueError):
            parse_currency("EUR")

    def test_loads_old_entries_without_currency_or_rate(self):
        self.store.path.write_text(
            json.dumps({"version": 1, "expenses": [
                {"id": "old1", "amount": "213.00", "category": "Food", "description": "", "date": "2026-09-29"}
            ]}),
            encoding="utf-8",
        )
        [old] = self.store.load()
        self.assertEqual((old.currency, old.rate, old.amount_pen, old.amount_usd), ("PEN", None, Decimal("213.00"), None))
        new = self.store.add(Expense(Decimal("10"), "Food", currency="USD", rate=Decimal("3.75")))
        self.assertEqual(total_in(self.store.load(), "USD"), (Decimal("10"), 1))
        self.assertEqual(total_in(self.store.load(), "PEN"), (Decimal("250.50"), 0))
        self.assertEqual(len(self.store.load()), 2)
        self.assertTrue(self.store.delete(new.id))


if __name__ == "__main__":
    unittest.main()
