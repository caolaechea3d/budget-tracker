import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.debts import OWED, Debt, DebtPayment
from expense_tracker.review import (
    CategoryLine,
    build_month_review,
    budgets_note,
    change_label,
    change_tone,
    comparisons,
    forecast_headline,
    period_note,
    usual_note,
)
from expense_tracker.review_html import render_html, save_html
from expense_tracker.storage import Budget, Expense, Income, RecurringExpense

D = Decimal
TODAY = date(2026, 10, 20)  # day 20 of October; July to September are finished months


def usual_month(mon: int) -> list[Expense]:
    """S/ 1,530 a month: food 300, transport 230 (taxis + a full tank), rent 1,000."""
    return [
        *(Expense(D("100"), "Food", "Weekly shop", date(2026, mon, d), subcategory="Supermarket") for d in (3, 10, 17)),
        *(Expense(D("20"), "Transport", "Taxi", date(2026, mon, d), subcategory="Taxi") for d in (4, 11, 18, 25)),
        Expense(D("150"), "Transport", "Full tank", date(2026, mon, 12), subcategory="Gasoline"),
        Expense(D("1000"), "Housing", "Rent", date(2026, mon, 1), recurring_id="r1"),
    ]


def sample_data():
    expenses = [*usual_month(7), *usual_month(8), *usual_month(9)]
    expenses += [Expense(D("100"), "Gym", "Membership", date(2026, mon, 7)) for mon in (7, 8)]  # none in September
    expenses += [  # October so far: S/ 2,120
        *(Expense(D("100"), "Food", "Weekly shop", date(2026, 10, d), subcategory="Supermarket") for d in (3, 10, 17)),
        Expense(D("20"), "Transport", "Taxi", date(2026, 10, 4), subcategory="Taxi"),
        Expense(D("20"), "Transport", "Taxi", date(2026, 10, 11), subcategory="Taxi"),
        Expense(D("150"), "Transport", "Full tank", date(2026, 10, 12), subcategory="Gasoline"),  # normal for gasoline
        Expense(D("200"), "Transport", "Airport taxi", date(2026, 10, 15), subcategory="Taxi"),  # 10× a usual taxi
        Expense(D("1000"), "Housing", "Rent", date(2026, 10, 1), recurring_id="r1"),
        Expense(D("15"), "Fun", "Coffee", date(2026, 10, 5)),
        Expense(D("15"), "Fun", "Coffee", date(2026, 10, 5)),  # entered twice?
        Expense(D("400"), "Health", "Dentist", date(2026, 10, 8)),
    ]
    incomes = [Income(D("3000"), "Salary", date=date(2026, mon, 1)) for mon in (7, 8, 9, 10)]
    debts = [
        Debt("Bank", D("1000"), start_date=date(2026, 8, 1), deadline=date(2026, 11, 15),
             payments=[DebtPayment(D("200"), date(2026, 9, 10)), DebtPayment(D("300"), date(2026, 10, 5))]),
        Debt("Ana", D("200"), direction=OWED, start_date=date(2026, 9, 1), payments=[DebtPayment(D("50"), date(2026, 10, 10))]),
        Debt("Old loan", D("300"), start_date=date(2026, 7, 1), settled=True, payments=[DebtPayment(D("100"), date(2026, 9, 1))]),
    ]
    recurring = [
        RecurringExpense(D("1000"), "Housing", description="Rent", day=1, start_month="2026-07", handled_through="2026-10",
                         id="r1"),
        RecurringExpense(D("100"), "Utilities", description="Internet", day=25, start_month="2026-07",
                         handled_through="2026-09"),
        RecurringExpense(D("10"), "Fun", description="Netflix", currency="USD", day=31, start_month="2026-07",
                         handled_through="2026-09"),
        RecurringExpense(D("50"), "Fun", description="Old gym", day=2, start_month="2026-07", active=False),
        RecurringExpense(D("70"), "Fun", description="Starts later", day=2, start_month="2026-11"),
    ]
    return expenses, incomes, debts, recurring


def review(month: str, **kwargs):
    expenses, incomes, debts, recurring = sample_data()
    budgets = {"Transport": Budget("Transport", D("300"))}
    return build_month_review(month, "PEN", expenses, incomes, budgets, debts, recurring, rate=D("3.5"), today=TODAY,
                              **kwargs)


class MonthReviewTest(unittest.TestCase):
    def test_current_month_totals_and_usual(self):
        r = review("2026-10")
        self.assertTrue(r.is_current)
        self.assertEqual((r.totals.income, r.totals.expenses, r.totals.saved, r.count), (D("3000"), D("2120"), D("880"), 11))
        self.assertEqual(r.history, 3)  # July (the first records) to September
        self.assertEqual((r.usual.income, r.usual.expenses), (D("3000.00"), D("1596.67")))
        self.assertEqual((r.previous.income, r.previous.expenses), (D("3000"), D("1530")))
        self.assertEqual(list(r.trend), ["2026-07", "2026-08", "2026-09", "2026-10"])
        self.assertEqual(period_note(r), "Month so far: day 20 of 31")
        self.assertEqual(comparisons(r, "expenses"), [])  # half a month isn't compared with whole ones
        self.assertEqual(usual_note(r), "“Usual” is the average of the previous 3 months (Jul 2026 – Sep 2026).")

    def test_categories_and_biggest(self):
        r = review("2026-10")
        lines = {c.category: c for c in r.categories}
        self.assertEqual([c.category for c in r.categories][:3], ["Housing", "Health", "Transport"])
        self.assertEqual((lines["Transport"].amount, lines["Transport"].usual, lines["Transport"].change),
                         (D("390"), D("230.00"), D("70")))
        self.assertEqual(lines["Health"].usual, D("0"))
        self.assertEqual(lines["Housing"].share, D("47.2"))
        self.assertEqual([e.description for e in r.biggest[:4]], ["Rent", "Dentist", "Airport taxi", "Full tank"])

    def test_insights_of_the_current_month(self):
        texts = [(i.kind, i.text) for i in review("2026-10").insights]
        self.assertEqual(texts, [
            ("duplicate", "Possible duplicate: 2 × S/ 15.00 “Coffee” on 5 Oct"),
            # compared with earlier taxis, not with the full tanks in the same category
            ("unusual", "Unusually large: “Airport taxi”, S/ 200.00 in Transport (usually about S/ 20.00)"),
            ("up", "Transport: already S/ 390.00, 70% more than a usual month (S/ 230.00)"),
            ("new", "Health: S/ 400.00, nothing in the previous 3 months"),
        ])  # no "less than usual" while the month isn't over (Gym)

    def test_forecast(self):
        r = review("2026-10")
        f = r.forecast
        # Everyday spending: food 300 + taxis 40 + gasoline 150 + coffee 30 = 520 in 20 days. The rent
        # (recurring), the dentist and the airport taxi (big / unusual) count once.
        self.assertEqual((f.day, f.days, f.spent, f.pace), (20, 31, D("2120"), D("26.00")))
        self.assertEqual([(b.name, b.date, b.amount) for b in f.bills],
                         [("Internet", date(2026, 10, 25), D("100")), ("Netflix", date(2026, 10, 31), D("35.00"))])
        self.assertEqual(f.projected, D("2541.00"))  # 2120 + 11 days × 26 + 135 in bills
        self.assertEqual(forecast_headline(r), "At this pace, October ends at about S/ 2,541.00 of spending: "
                                               "S/ 944.33 more than usual (S/ 1,596.67).")
        expenses, incomes, debts, recurring = sample_data()
        early = build_month_review("2026-10", "PEN", expenses, incomes, {}, debts, recurring, today=date(2026, 10, 5))
        self.assertIsNone(early.forecast.projected)
        self.assertEqual(early.forecast.bills[1].amount, None)  # USD bill without an exchange rate

    def test_debts(self):
        d = review("2026-10").debts
        self.assertEqual([(m.debt.counterparty, m.amount) for m in d.paid], [("Bank", D("300"))])
        self.assertEqual([(m.debt.counterparty, m.amount) for m in d.received], [("Ana", D("50"))])
        self.assertEqual((d.i_owe, d.owed_to_me), (D("500"), D("150")))  # the settled loan is closed
        self.assertEqual([(m.debt.counterparty, m.date, m.amount) for m in d.upcoming],
                         [("Bank", date(2026, 11, 15), D("500"))])
        august = review("2026-08").debts
        # At the end of August the settled loan still had its last payment ahead: still owed then
        self.assertEqual((august.i_owe, august.owed_to_me, august.upcoming), (D("1300"), D("0"), []))

    def test_finished_month(self):
        r = review("2026-09")
        self.assertIsNone(r.forecast)
        self.assertEqual(period_note(r), "")
        self.assertEqual(r.totals.savings_rate, D("49"))
        self.assertEqual(comparisons(r, "expenses"), [("▼ 6% vs August", "good"), ("▼ 6% vs usual", "good")])
        self.assertEqual(comparisons(r, "income"), [("same as August", ""), ("same as usual", "")])
        self.assertEqual(comparisons(r, "saved"), [("S/ 100.00 more than August", "good"),
                                                   ("S/ 100.00 more than usual", "good")])
        # The full tank isn't "unusual": gasoline has history of its own, even if short (not vs taxis)
        self.assertEqual([(i.kind, i.text) for i in r.insights], [("down", "Gym: nothing this month (usually S/ 100.00)")])
        self.assertEqual(budgets_note(r), "1 of 1 budget kept")
        self.assertEqual(budgets_note(review("2026-10")), "0 of 1 budget on track so far")

    def test_first_month_has_nothing_to_compare_with(self):
        r = review("2026-07")
        self.assertEqual((r.history, r.usual, r.previous, r.insights), (0, None, None, []))
        self.assertEqual({c.usual for c in r.categories}, {None})
        self.assertEqual(usual_note(r), "No earlier months to compare with yet.")

    def test_change_labels(self):
        def line(amount, usual):
            return CategoryLine("X", D(amount), D("0"), D("0"), None if usual is None else D(usual))
        self.assertEqual([change_label(line(*a)) for a in [("390", "230"), ("200", "230"), ("300", "300"),
                                                          ("35", "0"), ("260", "8.08"), ("5", None)]],
                         ["▲ 70%", "▼ 13%", "=", "new", "▲ ×32", ""])
        self.assertEqual([change_tone(line(*a)) for a in [("390", "230"), ("200", "230"), ("105", "100")]],
                         ["bad", "good", ""])


class MonthReviewHtmlTest(unittest.TestCase):
    def test_page(self):
        html = render_html(review("2026-10"), [], user="<script>alert(1)</script>")
        self.assertIn("<title>Month in review — October 2026</title>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)  # text is escaped
        self.assertNotIn("<script>", html)
        for part in ("Where October is heading", "What stood out", "Spending by category", "The last 4 months",
                     "Biggest expenses", "Budgets", "Debts", "Airport taxi", "S/ 2,541.00"):
            self.assertIn(part, html)
        september = render_html(review("2026-09"), [])
        self.assertNotIn("is heading", september)
        self.assertIn("▼ 6% vs August", september)

    def test_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.html"
            save_html(review("2026-09"), path, [])
            self.assertTrue(path.read_text(encoding="utf-8").startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
