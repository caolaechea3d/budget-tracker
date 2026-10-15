import re
import unittest
from datetime import date
from decimal import Decimal

from expense_tracker.gui import RATE_MISSING, expense_from_fields, preview_text
from expense_tracker.gui.widgets import MonthChoices, SortableColumns, TagField, month_label, text_key

D = Decimal


def hidden_root(test: unittest.TestCase):
    """A hidden Tk window for widget tests, or skip the test where no window can be opened."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        test.skipTest(f"Tk can't open a window here: {exc}")
    root.withdraw()
    return root


class GuiHelpersTest(unittest.TestCase):
    def test_expense_from_fields_keeps_id_when_editing(self):
        e = expense_from_fields("2026-09-29", "213", "PEN", "3,8", " food ", "test", expense_id="d3e6d47a")
        self.assertEqual(e.id, "d3e6d47a")
        self.assertEqual((e.amount, e.rate, e.category, e.date), (Decimal("213.00"), Decimal("3.8000"), "Food", date(2026, 9, 29)))
        self.assertEqual(e.amount_usd, Decimal("56.05"))

    def test_rate_is_required(self):
        with self.assertRaisesRegex(ValueError, re.escape(RATE_MISSING)):
            expense_from_fields("", "10", "PEN", "  ", "Food", "")

    def test_month_label(self):
        self.assertEqual(month_label("2026-09"), "September 2026")
        self.assertEqual(month_label("2027-01"), "January 2027")

    def test_month_choices_maps_labels_to_keys(self):
        import tkinter as tk
        from tkinter import ttk
        root = hidden_root(self)
        try:
            key = tk.StringVar(root, value="2026-09")
            box = ttk.Combobox(root, state="readonly")
            choices = MonthChoices(box, key, {"All months": "All months"})
            choices.set_months(["2026-09", "2026-08"])
            self.assertEqual(list(box["values"]), ["All months", "September 2026", "August 2026"])
            self.assertEqual(box.get(), "September 2026")
            choices.label_var.set("August 2026")
            choices._chosen()
            self.assertEqual(key.get(), "2026-08")
            key.set("All months")
            self.assertEqual(box.get(), "All months")
        finally:
            root.destroy()

    def test_year_label_round_trip(self):
        import tkinter as tk
        from tkinter import ttk
        self.assertEqual(month_label("2026"), "2026 · whole year")
        root = hidden_root(self)
        try:
            key = tk.StringVar(root, value="2026-09")
            choices = MonthChoices(ttk.Combobox(root), key)
            choices.set_months(["2026", "2026-09", "2025", "2025-12"])
            choices.label_var.set("2025 · whole year")
            choices._chosen()
            self.assertEqual(key.get(), "2025")
        finally:
            root.destroy()

    def test_sortable_columns(self):
        from tkinter import ttk
        root = hidden_root(self)
        try:
            tree = ttk.Treeview(root, columns=("amount", "payment"))
            calls = []
            sorter = SortableColumns(
                tree, {"amount": "Amount", "payment": "Payment"},
                keys={"amount": lambda r: r[0], "payment": lambda r: text_key(r[1])},
                default=("amount", True), on_change=lambda: calls.append(1), descending_first=("amount",),
            )
            rows = [(D("5"), "Yape"), (None, "cash"), (D("50"), ""), (D("20"), "Credit card")]
            self.assertEqual(sorter.apply(rows), [(D("50"), ""), (D("20"), "Credit card"), (D("5"), "Yape"), (None, "cash")])
            self.assertEqual(tree.heading("amount", "text"), "Amount ▼")
            sorter.toggle("amount")  # same column: reverse, missing values stay last
            self.assertEqual([r[0] for r in sorter.apply(rows)], [D("5"), D("20"), D("50"), None])
            sorter.toggle("payment")  # new text column starts A→Z, empty last
            self.assertEqual([r[1] for r in sorter.apply(rows)], ["cash", "Credit card", "Yape", ""])
            self.assertEqual((tree.heading("payment", "text"), tree.heading("amount", "text")), ("Payment ▲", "Amount"))
            self.assertEqual(len(calls), 2)
        finally:
            root.destroy()

    def test_tag_field_menu(self):
        import tkinter as tk
        root = hidden_root(self)
        try:
            var = tk.StringVar(root, value="Lima Trip")
            field = TagField(root, var, lambda: ["cusco-trip", "work", "lima-trip"])
            field._rebuild()
            labels = [field.menu.entrycget(i, "label") for i in range(field.menu.index("end") + 1)
                      if field.menu.type(i) != "separator"]
            self.assertEqual(labels, ["Recent tags", "#cusco-trip", "#work", "#lima-trip", "Clear tags"])
            self.assertEqual([v.get() for v in field._checks], [False, False, True])  # typed tag is ticked
            field.toggle("work")
            self.assertEqual(var.get(), "lima-trip, work")
            field.toggle("lima-trip")
            self.assertEqual(var.get(), "work")
            var.set("brand new")  # typed but not saved anywhere yet: still listed so it can be unticked
            field._rebuild()
            self.assertEqual(field.menu.entrycget(1, "label"), "#brand-new")
            field.menu.invoke(field.menu.index("end"))  # "Clear tags"
            self.assertEqual(var.get(), "")
            empty = TagField(root, tk.StringVar(root), lambda: [])
            empty._rebuild()
            self.assertEqual(empty.menu.entrycget(0, "state"), "disabled")
        finally:
            root.destroy()

    def test_preview(self):
        self.assertEqual(preview_text("20", "USD", "3.75"), "= S/ 75.00  /  US$ 20.00")
        self.assertEqual(preview_text("20", "USD", ""), "")


if __name__ == "__main__":
    unittest.main()
