import unittest
from datetime import date
from decimal import Decimal

from expense_tracker.storage import Expense
from expense_tracker.weekly import build_weekly, change_text, week_label, week_start

D = Decimal
TODAY = date(2026, 11, 18)  # a Wednesday: day 3 of the week of Monday 16 November


def sample() -> list[Expense]:
    return [
        Expense(D("100"), "Food", date=date(2026, 10, 26), rate=D("3.5")),  # Monday
        Expense(D("50"), "Transport", date=date(2026, 11, 1), rate=D("3.5")),  # Sunday: same week
        Expense(D("200"), "Food", date=date(2026, 11, 3), rate=D("3.5")),
        Expense(D("20"), "Fun", date=date(2026, 11, 8), rate=D("3.5")),
        # nothing in the week of 9 November
        Expense(D("60"), "food", date=date(2026, 11, 16), rate=D("3.5")),
        Expense(D("10"), "Transport", date=date(2026, 11, 17), currency="USD", rate=D("3.5")),
        Expense(D("5"), "Transport", date=date(2026, 11, 17), currency="USD"),  # no rate: not counted
    ]


class WeeklyTest(unittest.TestCase):
    def test_weeks(self):
        t = build_weekly(sample(), TODAY, 8, "PEN", ["Transport", "Food"], today=TODAY)
        # Only from the week of the first expense, not 8 weeks back
        self.assertEqual([w.start for w in t.weeks],
                         [date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)])
        self.assertEqual([w.total for w in t.weeks], [D("150"), D("220"), D("0"), D("95.00")])
        self.assertEqual([w.count for w in t.weeks], [2, 2, 0, 2])
        self.assertEqual(t.weeks[0].by_category, {"Food": D("100"), "Transport": D("50")})
        self.assertEqual(t.weeks[3].by_category, {"Food": D("60"), "Transport": D("35.00")})  # "food" = "Food"
        self.assertEqual(t.categories, ["Transport", "Food", "Fun"])  # the user's order, then the rest
        self.assertEqual(t.missing_rate, 1)

    def test_current_week_is_so_far_and_not_averaged(self):
        t = build_weekly(sample(), TODAY, 8, "PEN", [], today=TODAY)
        current = t.weeks[-1]
        self.assertEqual((current.is_partial, current.days, current.per_day), (True, 3, D("31.67")))
        self.assertEqual(t.average, D("123.33"))  # (150 + 220 + 0) / 3 finished weeks
        self.assertEqual((t.highest.start, t.lowest.start), (date(2026, 11, 2), date(2026, 11, 9)))
        changes = [(t.change_vs_previous(w), t.change_vs_average(w)) for w in t.weeks]
        self.assertEqual(changes, [(None, D("22")), (D("47"), D("78")), (D("-100"), D("-100")), (None, None)])
        # On its Sunday the week is still going: "so far", not in the average yet
        sunday = build_weekly(sample(), date(2026, 11, 22), 8, "PEN", [], today=date(2026, 11, 22))
        self.assertEqual((sunday.weeks[-1].is_partial, sunday.weeks[-1].days, sunday.average),
                         (True, 7, D("123.33")))
        # After an empty week there's no % to give
        weeks = build_weekly(sample()[:4] + [Expense(D("9"), "Food", date=date(2026, 11, 10), rate=D("3.5"))],
                             date(2026, 11, 15), 8, "PEN", [], today=TODAY)
        self.assertIsNone(weeks.change_vs_previous(weeks.weeks[0]))

    def test_end_and_count(self):
        past = build_weekly(sample(), date(2026, 11, 8), 2, "PEN", [], today=TODAY)
        self.assertEqual([w.start for w in past.weeks], [date(2026, 10, 26), date(2026, 11, 2)])
        self.assertEqual((past.weeks[-1].is_partial, past.average), (False, D("185.00")))
        recent = build_weekly(sample(), TODAY, 2, "PEN", [], today=TODAY)
        self.assertEqual([w.start for w in recent.weeks], [date(2026, 11, 9), date(2026, 11, 16)])
        self.assertEqual(recent.average, D("0.00"))
        in_usd = build_weekly(sample(), TODAY, 8, "USD", [], today=TODAY)
        # 60 PEN = 17.14 USD, + 10 USD, + the 5 USD without a rate (needs no converting into USD)
        self.assertEqual((in_usd.weeks[-1].total, in_usd.missing_rate), (D("32.14"), 0))
        empty = build_weekly([], TODAY, 8, "PEN", [], today=TODAY)
        self.assertEqual((empty.weeks, empty.average, empty.highest), ([], None, None))

    def test_change_text(self):
        self.assertEqual([change_text(D(p)) for p in ("63", "-63", "0", "199", "318", "1596")],
                         ["▲ 63%", "▼ 63%", "= 0%", "▲ 199%", "▲ ×4", "▲ ×17"])
        self.assertEqual(change_text(None), "")

    def test_labels(self):
        self.assertEqual(week_start(date(2026, 11, 22)), date(2026, 11, 16))  # a Sunday
        self.assertEqual(week_start(date(2026, 11, 16)), date(2026, 11, 16))
        self.assertEqual(week_label(date(2026, 11, 16)), "16–22 Nov")
        self.assertEqual(week_label(date(2026, 10, 26)), "26 Oct – 1 Nov")
        self.assertEqual(week_label(date(2026, 12, 28), with_year=True), "28 Dec – 3 Jan 2027")


if __name__ == "__main__":
    unittest.main()
