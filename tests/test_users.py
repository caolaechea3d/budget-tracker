import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expense_tracker.storage import Expense
from expense_tracker.users import DEFAULT_USER_NAME, UserRegistry


class UsersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.registry = UserRegistry(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_creates_default_user(self):
        self.registry.ensure_ready()
        self.registry.ensure_ready()  # running again changes nothing
        [user] = self.registry.users()
        self.assertEqual((user.name, user.type), (DEFAULT_USER_NAME, "Personal"))
        self.assertEqual(self.registry.last_user().id, user.id)
        self.assertEqual(self.registry.store_for(user).load(), [])

    def test_existing_data_moves_into_default_user(self):
        legacy = self.dir / "expenses.json"
        legacy.write_text(json.dumps({"version": 3, "expenses": [
            {"id": "d3e6d47a", "date": "2026-09-29", "category": "Food", "amount": "213.00", "rate": "3.15"},
        ]}), encoding="utf-8")
        (self.dir / "receipts").mkdir()
        (self.dir / "receipts" / "2026-09-29_d3e6d47a.jpg").write_bytes(b"img")
        (self.dir / "backups").mkdir()
        (self.dir / "backups" / "expenses-2026-09-28.json").write_text("{}", encoding="utf-8")

        self.registry.ensure_ready()
        user = self.registry.last_user()
        store = self.registry.store_for(user)
        self.assertEqual([e.id for e in store.load()], ["d3e6d47a"])
        self.assertFalse(legacy.exists())
        self.assertTrue((store.receipts_dir / "2026-09-29_d3e6d47a.jpg").exists())
        self.assertTrue((store.backups_dir / "expenses-2026-09-28.json").exists())
        self.assertTrue((store.backups_dir / "expenses-before-users.json").exists())
        self.assertFalse((self.dir / "receipts").exists())

    def test_users_have_separate_data_and_backups(self):
        self.registry.ensure_ready()
        a = self.registry.last_user()
        b = self.registry.create("Work stuff", "Work")
        self.assertEqual((b.icon, b.type), ("💼", "Work"))
        store_a, store_b = self.registry.store_for(a), self.registry.store_for(b)
        for amount in ("10", "20", "30"):
            store_a.add(Expense(Decimal(amount), "Food", rate=Decimal("3.7")))
        store_b.add(Expense(Decimal("99"), "Travel", rate=Decimal("3.8")))
        store_a.set_budget("Food", Decimal("500"))

        self.assertEqual(len(store_a.load()), 3)
        self.assertEqual([e.amount for e in store_b.load()], [Decimal("99.00")])
        self.assertEqual(store_b.budgets(), {})
        self.assertEqual(store_b.last_rate(), Decimal("3.8"))
        self.assertEqual(store_a.last_rate(), Decimal("3.7"))

        self.assertNotEqual(store_a.backups_dir, store_b.backups_dir)
        backup_a = store_a.backup_now()
        backup_b = store_b.backup_now()
        self.assertEqual(len(json.loads(backup_a.read_text(encoding="utf-8"))["expenses"]), 3)
        self.assertEqual(len(json.loads(backup_b.read_text(encoding="utf-8"))["expenses"]), 1)
        self.assertTrue(all(p.parent == store_a.backups_dir for p in store_a.backups_dir.iterdir()))

    def test_names_are_unique_and_findable(self):
        self.registry.ensure_ready()
        user = self.registry.create("Ana", "Family")
        with self.assertRaises(ValueError):
            self.registry.create("  ana ", "Personal")
        with self.assertRaises(ValueError):
            self.registry.create("   ", "Personal")
        self.assertEqual(self.registry.find("ANA").id, user.id)
        self.assertEqual(self.registry.find(user.id).name, "Ana")
        user.name = "Ana María"
        self.registry.update(user)
        self.assertEqual(self.registry.get(user.id).name, "Ana María")

    def test_delete_keeps_the_data_folder(self):
        self.registry.ensure_ready()
        default = self.registry.last_user()
        extra = self.registry.create("Temp", "Other")
        self.registry.store_for(extra).add(Expense(Decimal("5"), "Food", rate=Decimal("3.7")))
        self.registry.set_last_user(extra.id)
        moved = self.registry.delete(extra.id)
        self.assertTrue((moved / "expenses.json").exists())
        self.assertEqual([u.id for u in self.registry.users()], [default.id])
        self.assertEqual(self.registry.last_user().id, default.id)
        with self.assertRaises(ValueError):
            self.registry.delete(default.id)  # can't delete the only user


if __name__ == "__main__":
    unittest.main()
