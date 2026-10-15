"""Shared pieces for the tabs of the main page."""

from __future__ import annotations

from dataclasses import dataclass, field
from tkinter import ttk
from typing import TYPE_CHECKING

from ...debts import Debt
from ...storage import Budget, Expense, Income

if TYPE_CHECKING:
    from ..app import ExpenseApp

EXPENSE_COLOR = "#e76f51"
INCOME_COLOR = "#43aa8b"
LEVEL_COLORS = {"ok": "#43aa8b", "warning": "#f4a261", "over": "#e63946"}


@dataclass
class PageData:
    """Everything the tabs need to redraw, loaded once per refresh."""

    expenses: list[Expense]
    incomes: list[Income]
    budgets: dict[str, Budget]
    show_in: str  # 'PEN' or 'USD'
    period: str | None  # '2026-09', '2026' (whole year) or None (all months)
    focus_month: str  # the single month used by budgets and the 12-month chart
    select_expense: str | None = None  # expense to select after redrawing
    select_income: str | None = None
    debts: list[Debt] = field(default_factory=list)
    select_debt: str | None = None


class Tab(ttk.Frame):
    """One tab of the notebook. Subclasses set the label/icon, build their widgets and redraw."""

    label = ""
    tab_icon = ""
    tab_color = "#8d99ae"

    def __init__(self, app: ExpenseApp):
        super().__init__(app.notebook, padding=10)
        self.app = app
        self.icons = app.icons
        image = self.icons.get(self.tab_icon, self.tab_color)
        app.notebook.add(self, text=f" {self.label}" if image else self.icons.text(self.tab_icon, self.label),
                         image=image or "", compound="left")
        self.build()

    def build(self) -> None:
        raise NotImplementedError

    def redraw(self, data: PageData) -> None:
        raise NotImplementedError
