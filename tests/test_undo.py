import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expense_tracker.storage import Expense, ExpenseStore, Income
from expense_tracker.undo import UndoHistory

D = Decimal


class UndoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = ExpenseStore(self.dir / "expenses.json")
        self.history = UndoHistory(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def amounts(self):
        return sorted(e.amount for e in self.store.load())

    def test_undo_and_redo_several_steps(self):
        a = self.history.record("Add a", lambda: self.store.add(Expense(D("10"), "Food", rate=D("3.7"))))
        self.history.record("Add b", lambda: self.store.add(Expense(D("20"), "Food", rate=D("3.7"))))
        edited = self.store.get(a.id)
        edited.amount = D("15")
        self.history.record("Edit a", lambda: self.store.update(edited))
        self.history.record("Delete a", lambda: self.store.delete(a.id))
        self.assertEqual(self.amounts(), [D("20")])

        self.assertEqual(self.history.next_undo(), "Delete a")
        self.assertEqual(self.history.undo(), "Delete a")
        self.assertEqual(self.amounts(), [D("15"), D("20")])
        self.assertEqual(self.history.undo(), "Edit a")
        self.assertEqual(self.amounts(), [D("10"), D("20")])
        self.assertEqual(self.history.next_redo(), "Edit a")
        self.assertEqual(self.history.redo(), "Edit a")
        self.assertEqual(self.amounts(), [D("15"), D("20")])
        self.assertEqual(self.history.undo(), "Edit a")
        self.assertEqual(self.history.undo(), "Add b")
        self.assertEqual(self.history.undo(), "Add a")
        self.assertEqual(self.amounts(), [])
        self.assertIsNone(self.history.next_undo())
        with self.assertRaises(ValueError):
            self.history.undo()

    def test_new_change_clears_redo(self):
        self.history.record("Add", lambda: self.store.add(Expense(D("10"), "Food", rate=D("3.7"))))
        self.history.undo()
        self.history.record("Add income", lambda: self.store.add_income(Income(D("5"), "Salary", rate=D("3.7"))))
        self.assertIsNone(self.history.next_redo())
        self.assertEqual(self.history.next_undo(), "Add income")

    def test_refuses_to_overwrite_changes_that_cannot_be_undone(self):
        self.history.record("Add", lambda: self.store.add(Expense(D("10"), "Food", rate=D("3.7"))))
        self.store.set_budget("Food", D("100"))  # not recorded
        self.assertIsNone(self.history.next_undo())
        with self.assertRaises(ValueError):
            self.history.undo()
        self.assertEqual(self.amounts(), [D("10")])  # nothing was overwritten
        self.assertIn("Food", self.store.budgets())

    def test_failed_change_is_not_recorded(self):
        def fail():
            raise ValueError("bad input")
        with self.assertRaises(ValueError):
            self.history.record("Nothing", fail)
        self.assertIsNone(self.history.next_undo())

    def test_receipts_follow_undo(self):
        source = self.dir / "photo.jpg"
        source.write_bytes(b"img")
        e = self.store.add(Expense(D("10"), "Food", rate=D("3.7")))
        e = self.store.attach_receipt(e.id, source)
        receipt = self.store.receipts_dir / e.receipt

        self.history.record("Delete", lambda: self.store.delete(e.id))
        self.assertFalse(receipt.exists())  # set aside in receipts/removed
        self.history.undo()
        self.assertTrue(receipt.exists())  # back where it belongs
        self.assertEqual(self.store.get(e.id).receipt, e.receipt)

        other = self.dir / "other.png"
        other.write_bytes(b"png")
        self.history.record("Attach", lambda: self.store.attach_receipt(e.id, other))
        new_name = self.store.get(e.id).receipt
        self.history.undo()  # the old receipt returns, the new one is set aside
        self.assertEqual(self.store.get(e.id).receipt, e.receipt)
        self.assertTrue(receipt.exists())
        self.assertFalse((self.store.receipts_dir / new_name).exists())
        self.assertTrue((self.store.receipts_dir / "removed" / new_name).exists())


if __name__ == "__main__":
    unittest.main()
