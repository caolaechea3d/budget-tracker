import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.debts import (
    OWED,
    Debt,
    DebtPayment,
    add_payment,
    counterparty_names,
    delete_debt,
    delete_payment,
    get_debt,
    load_debts,
    save_debt,
    summarize,
)
from expense_tracker.storage import ExpenseStore
from expense_tracker.undo import UndoHistory

D = Decimal
TODAY = date(2026, 10, 15)


class DebtModelTest(unittest.TestCase):
    def test_no_deadline(self):
        debt = Debt("Juan", D("200"), start_date=date(2026, 9, 1))
        self.assertIsNone(debt.next_due())
        self.assertEqual(debt.status(TODAY), "open")
        self.assertIsNone(debt.final_date)

    def test_deadline_statuses(self):
        debt = Debt("Juan", D("200"), start_date=date(2026, 9, 1), deadline=date(2026, 10, 20))
        self.assertEqual(debt.next_due(), (date(2026, 10, 20), D("200")))
        self.assertEqual(debt.status(TODAY), "due_soon")
        self.assertEqual(debt.status(date(2026, 10, 1)), "on_track")
        self.assertEqual(debt.status(date(2026, 10, 21)), "overdue")
        debt.payments.append(DebtPayment(D("200")))
        self.assertEqual((debt.remaining, debt.status(date(2026, 12, 1))), (D("0"), "paid"))

    def test_installments(self):
        # 3 monthly payments on the 5th, starting after 2026-09-10 → Oct 5, Nov 5, Dec 5
        debt = Debt("Saga card", D("100"), counterparty_type="Credit card", start_date=date(2026, 9, 10),
                    installments=3, payment_day=5)
        self.assertEqual(debt.schedule(), [date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)])
        self.assertEqual(debt.installment_amount, D("33.33"))
        self.assertEqual(debt.final_date, date(2026, 12, 5))
        self.assertEqual(debt.next_due(), (date(2026, 10, 5), D("33.33")))
        self.assertEqual(debt.status(TODAY), "overdue")  # Oct 5 passed without a payment
        debt.payments.append(DebtPayment(D("33.33")))
        self.assertEqual(debt.next_due(), (date(2026, 11, 5), D("33.33")))
        self.assertEqual(debt.status(TODAY), "on_track")
        debt.payments.append(DebtPayment(D("33.33")))
        self.assertEqual(debt.next_due(), (date(2026, 12, 5), D("33.34")))  # last one absorbs rounding
        debt.payments.append(DebtPayment(D("33.34")))
        self.assertTrue(debt.is_closed)
        self.assertIsNone(debt.next_due())

    def test_first_installment_same_month_when_day_not_reached(self):
        debt = Debt("Bank", D("600"), start_date=date(2026, 9, 2), installments=2, payment_day=15)
        self.assertEqual(debt.schedule(), [date(2026, 9, 15), date(2026, 10, 15)])

    def test_settled_and_progress(self):
        debt = Debt("Ana", D("400"), direction=OWED)
        debt.payments.append(DebtPayment(D("100")))
        self.assertEqual((debt.paid, debt.remaining, debt.progress), (D("100"), D("300"), D("0.25")))
        debt.settled = True
        self.assertEqual((debt.remaining, debt.status(TODAY), debt.progress), (D("0"), "paid", D("1")))

    def test_validation(self):
        for kwargs in ({"counterparty": " "}, {"installments": 0, "payment_day": 5},
                       {"installments": 3, "payment_day": None}, {"installments": 3, "payment_day": 31},
                       {"direction": "maybe"},
                       {"start_date": date(2026, 9, 10), "deadline": date(2026, 9, 1)}):
            args = {"counterparty": "Juan", "amount": D("10"), **kwargs}
            with self.assertRaises(ValueError, msg=str(kwargs)):
                Debt(**args)

    def test_round_trip(self):
        debt = Debt("BCP", D("1500"), counterparty_type="Bank", currency="USD", rate=D("3.75"),
                    start_date=date(2026, 9, 1), installments=6, payment_day=10, notes="12% TEA")
        debt.payments.append(DebtPayment(D("250"), date(2026, 9, 10), "first", D("3.74"), "abc12345"))
        again = Debt.from_dict(debt.to_dict())
        self.assertEqual(again, debt)


class DebtStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExpenseStore(Path(self.tmp.name) / "expenses.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_update_delete(self):
        debt = Debt("Juan", D("200"))
        save_debt(self.store, debt)
        debt.description = "Concert tickets"
        save_debt(self.store, debt)
        self.assertEqual([d.description for d in load_debts(self.store)], ["Concert tickets"])
        delete_debt(self.store, debt.id)
        self.assertEqual(load_debts(self.store), [])

    def test_payment_also_recorded_as_expense(self):
        debt = Debt("Saga card", D("300"), counterparty_type="Credit card")
        save_debt(self.store, debt)
        payment = DebtPayment(D("100"), date(2026, 10, 5), "October", rate=D("3.71"))
        add_payment(self.store, debt.id, payment, also_record=True)
        [expense] = self.store.load()
        self.assertEqual((expense.amount, expense.category, expense.description, expense.rate),
                         (D("100.00"), "Debt payments", "Payment to Saga card · October", D("3.71")))
        self.assertTrue(any(c.name == "Debt payments" for c in self.store.categories()))
        self.assertEqual(get_debt(self.store, debt.id).payments[0].record_id, expense.id)
        self.assertEqual(self.store.last_rate(), D("3.71"))

        delete_payment(self.store, debt.id, payment.id)  # removes the expense created with it
        self.assertEqual(get_debt(self.store, debt.id).payments, [])
        self.assertEqual(self.store.load(), [])

    def test_repayment_recorded_as_income(self):
        debt = Debt("Ana", D("400"), direction=OWED)
        save_debt(self.store, debt)
        add_payment(self.store, debt.id, DebtPayment(D("150"), rate=D("3.7")), also_record=True)
        [income] = self.store.load_incomes()
        self.assertEqual((income.source, income.amount), ("Debt repayment", D("150.00")))
        self.assertTrue(any(i.name == "Debt repayment" for i in self.store.income_sources()))

    def test_payment_without_record_and_rate_checks(self):
        debt = Debt("Juan", D("200"))
        save_debt(self.store, debt)
        add_payment(self.store, debt.id, DebtPayment(D("50")))
        self.assertEqual((self.store.load(), get_debt(self.store, debt.id).paid), ([], D("50")))
        with self.assertRaises(ValueError):  # recording as expense needs a rate
            add_payment(self.store, debt.id, DebtPayment(D("10")), also_record=True)
        with self.assertRaises(ValueError):
            add_payment(self.store, "missing", DebtPayment(D("10")))

    def test_undo_payment(self):
        history = UndoHistory(self.store)
        debt = Debt("Juan", D("200"))
        history.record("Add debt", lambda: save_debt(self.store, debt))
        history.record("Pay", lambda: add_payment(self.store, debt.id, DebtPayment(D("80"), rate=D("3.7")),
                                                  also_record=True))
        self.assertEqual(len(self.store.load()), 1)
        history.undo()
        self.assertEqual((get_debt(self.store, debt.id).paid, self.store.load()), (D("0"), []))
        history.undo()
        self.assertEqual(load_debts(self.store), [])

    def test_summary(self):
        debts = [
            Debt("Juan", D("200"), deadline=date(2026, 10, 1), start_date=date(2026, 9, 1)),  # overdue
            Debt("BCP", D("100"), currency="USD", rate=D("3.70"), deadline=date(2026, 10, 18),
                 start_date=date(2026, 9, 1)),  # due soon
            Debt("Ana", D("500"), direction=OWED),
            Debt("Old", D("50"), settled=True),
            Debt("Pepe", D("10"), currency="USD"),  # no rate: can't be shown in PEN
        ]
        s = summarize(debts, "PEN", TODAY)
        self.assertEqual((s.i_owe, s.owed_to_me, s.overdue, s.due_soon, s.missing_rate),
                         (D("570.00"), D("500"), 1, 1, 1))
        self.assertEqual((s.next_due[0].counterparty, s.next_due[1]), ("Juan", date(2026, 10, 1)))
        self.assertEqual(counterparty_names(debts), ["Ana", "BCP", "Juan", "Old", "Pepe"])


if __name__ == "__main__":
    unittest.main()
