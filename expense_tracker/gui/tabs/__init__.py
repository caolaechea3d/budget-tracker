"""The tabs of the main page, one module each."""

from .base import EXPENSE_COLOR, INCOME_COLOR, PageData, Tab
from .budgets import BudgetsTab
from .charts import ChartsTab
from .expenses import ExpensesTab
from .income import IncomeTab
from .recurring import RecurringTab

__all__ = [
    "Tab", "PageData", "EXPENSE_COLOR", "INCOME_COLOR",
    "ExpensesTab", "IncomeTab", "ChartsTab", "BudgetsTab", "RecurringTab",
]
