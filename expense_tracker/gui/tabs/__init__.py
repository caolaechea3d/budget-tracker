"""The tabs of the main page, one module each."""

from .base import EXPENSE_COLOR, INCOME_COLOR, PageData, Tab
from .budgets import BudgetsTab
from .charts import ChartsTab
from .debts import DebtsTab
from .expenses import ExpensesTab
from .income import IncomeTab
from .recurring import RecurringTab
from .reports import ReportsTab

__all__ = [
    "Tab", "PageData", "EXPENSE_COLOR", "INCOME_COLOR",
    "ExpensesTab", "IncomeTab", "DebtsTab", "ChartsTab", "ReportsTab", "BudgetsTab", "RecurringTab",
]
