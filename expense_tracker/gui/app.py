"""Main page of a user: header (user, period, currency, search, balance), menu and the tabs.

Each tab lives in its own module under `gui/tabs/`. This page owns what they share: the selected
period and currency, the catalog (categories, payment methods, income sources), the file actions,
and `refresh()`, which loads the data once and asks every tab to redraw.
"""

from __future__ import annotations

import csv
import tkinter as tk
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME
from ..catalog import PALETTE, Category, Item, category_look, find_category, find_item
from ..debts import DUE_SOON_DAYS, load_debts
from ..debts import summarize as summarize_debts
from ..reports import balance, is_year, recent_tags
from ..storage import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    Expense,
    ExpenseStore,
    Income,
    RecurringExpense,
    add_months,
    export_csv,
    format_money,
    format_rate,
    month_key,
)
from ..undo import UndoHistory
from ..users import User
from .forms import DueRecurringDialog, open_file
from .icons import Icons
from .import_dialog import ImportDialog
from .manage import CategoriesDialog, ItemsDialog
from .tabs import (
    INCOME_COLOR,
    BudgetsTab,
    ChartsTab,
    DebtsTab,
    ExpensesTab,
    IncomeTab,
    PageData,
    RecurringTab,
)
from .widgets import MonthChoices, setup_style

ALL = "All months"


class ExpenseApp(ttk.Frame):
    def __init__(
        self,
        master: tk.Tk,
        store: ExpenseStore,
        icons: Icons | None = None,
        user: User | None = None,
        on_switch_user: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self.store = store
        self.icons = icons or Icons(master)
        self.user = user
        self.on_switch_user = on_switch_user
        master.title(f"{APP_NAME} — {user.name}" if user else APP_NAME)
        master.minsize(1120, 700)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        setup_style(self, self.icons)
        self.reload_catalog()
        self.history = UndoHistory(store)  # undo/redo for expense & income changes (this session only)

        self.month_var = tk.StringVar(value=month_key(date.today()))
        self.show_in_var = tk.StringVar(value=DEFAULT_CURRENCY)
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value=f"Data file: {store.path}")

        self._build_menu(master)
        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))
        self.expenses_tab = ExpensesTab(self)
        self.income_tab = IncomeTab(self)
        self.debts_tab = DebtsTab(self)
        self.charts_tab = ChartsTab(self)
        self.budgets_tab = BudgetsTab(self)
        self.recurring_tab = RecurringTab(self)
        self.tabs = [self.expenses_tab, self.income_tab, self.debts_tab, self.charts_tab, self.budgets_tab,
                     self.recurring_tab]
        self._build_status_bar()

        self.search_var.trace_add("write", lambda *_: self.refresh())
        master.bind("<Control-z>", lambda _e: self.undo())
        master.bind("<Control-y>", lambda _e: self.redo())
        master.bind("<Control-f>", lambda _e: self.search_entry.focus_set())
        master.bind("<Control-n>", lambda _e: (self.notebook.select(self.expenses_tab),
                                               self.expenses_tab.focus_quick_add()))
        self.refresh()
        self.expenses_tab.focus_quick_add()
        self.after(400, self.remind_debts)
        self.after(500, self.check_recurring)

    # ---------- catalog helpers (used by pickers and dialogs) ----------

    def reload_catalog(self) -> None:
        self.categories: list[Category] = self.store.categories()
        self.payment_methods: list[Item] = self.store.payment_methods()
        self.income_sources: list[Item] = self.store.income_sources()

    def catalog_changed(self) -> None:
        self.reload_catalog()
        self.refresh()

    def category_options(self) -> list[tuple[str, str, str]]:
        return [(c.name, c.icon, c.color) for c in self.categories]

    def subcategory_options(self, category: str) -> list[tuple[str, str, str]]:
        cat = find_category(self.categories, category)
        return [(s.name, s.icon, cat.color) for s in cat.subcategories] if cat else []

    def payment_options(self) -> list[tuple[str, str, str]]:
        return [(i.name, i.icon, "#8d99ae") for i in self.payment_methods]

    def source_options(self) -> list[tuple[str, str, str]]:
        return [(i.name, i.icon, INCOME_COLOR) for i in self.income_sources]

    def next_color(self) -> str:
        return PALETTE[len(self.categories) % len(PALETTE)]

    # "New…" entries in the dropdowns. They're undoable steps too, so they don't block undoing
    # the changes made before them.

    def add_category(self, name: str) -> None:
        if not find_category(self.categories, name):
            self.categories.append(Category(name, color=self.next_color()))
            self.history.record(f"Add category “{name}”", lambda: self.store.save_categories(self.categories))

    def add_subcategory(self, category: str, name: str) -> None:
        if not category:
            return
        cat = find_category(self.categories, category)
        if cat is None:
            cat = Category(category, color=self.next_color())
            self.categories.append(cat)
        if not cat.subcategory(name):
            cat.subcategories.append(Item(name, cat.icon))
            self.history.record(f"Add subcategory “{name}”", lambda: self.store.save_categories(self.categories))

    def add_payment_method(self, name: str) -> None:
        if not find_item(self.payment_methods, name):
            self.payment_methods.append(Item(name, "💳"))
            self.history.record(f"Add payment method “{name}”",
                                lambda: self.store.save_payment_methods(self.payment_methods))

    def add_income_source(self, name: str) -> None:
        if not find_item(self.income_sources, name):
            self.income_sources.append(Item(name, "💰"))
            self.history.record(f"Add income source “{name}”",
                                lambda: self.store.save_income_sources(self.income_sources))

    def recent_tags(self) -> list[str]:
        """Tags for the 🏷 ▾ menus, most recently used first (from the data of the last refresh)."""
        return recent_tags(self.expenses_tab.expenses)

    def look(self, category: str, subcategory: str = "") -> tuple[str, str]:
        return category_look(self.categories, category, subcategory)

    def last_rate(self) -> Decimal | None:
        try:
            return self.store.last_rate()
        except (ValueError, OSError):
            return None

    def icon_text(self, icon: str, color: str, text: str) -> dict:
        """Keyword args for a tree row / label: image + text (or emoji text without Pillow)."""
        image = self.icons.get(icon, color)
        return {"image": image or "", "text": f" {text}" if image else self.icons.text(icon, text)}

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    # ---------- menu & header ----------

    def _build_menu(self, master: tk.Tk) -> None:
        menubar = tk.Menu(master)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Import expenses from CSV…", command=self.import_csv)
        file_menu.add_command(label="Export shown expenses to CSV…", command=self.export)
        file_menu.add_separator()
        file_menu.add_command(label="Back up now", command=self.backup_now)
        file_menu.add_command(label="Open data folder", command=self.open_data_folder)
        file_menu.add_separator()
        if self.on_switch_user:
            file_menu.add_command(label="Switch user…", command=self.on_switch_user)
        file_menu.add_command(label="Exit", command=master.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.edit_menu = tk.Menu(menubar, tearoff=False, postcommand=self._update_edit_menu)
        self.edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        self.edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        menubar.add_cascade(label="Edit", menu=self.edit_menu)
        settings = tk.Menu(menubar, tearoff=False)
        settings.add_command(label="Categories & icons…", command=lambda: CategoriesDialog(self))
        settings.add_command(label="Payment methods…", command=lambda: ItemsDialog(
            self, "Payment methods", self.payment_methods, self.store.save_payment_methods,
            lambda old, new: self.store.rename_value(("expenses", "recurring"), "payment_method", old, new)))
        settings.add_command(label="Income sources…", command=lambda: ItemsDialog(
            self, "Income sources", self.income_sources, self.store.save_income_sources,
            lambda old, new: self.store.rename_value(("incomes",), "source", old, new)))
        menubar.add_cascade(label="Settings", menu=settings)
        master.configure(menu=menubar)

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(10, 10, 10, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(3, weight=1)

        # Row 0: who is using the app (left) and the period's balance (right)
        badge = ttk.Frame(header)
        badge.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        if self.user:
            image = self.icons.get(self.user.icon, self.user.color, size=round(self.icons.size * 1.9))
            ttk.Label(badge, image=image or "", text="" if image else self.user.icon,
                      font=("Segoe UI Emoji", 20)).grid(row=0, column=0, rowspan=2, padx=(0, 10))
            ttk.Label(badge, text=self.user.name, style="UserName.TLabel").grid(row=0, column=1, sticky="sw")
            ttk.Label(badge, text=f"{self.user.type} budget", style="Muted.TLabel").grid(row=1, column=1, sticky="nw")
        if self.on_switch_user:
            switch_icon = self.icons.get("🔄", "#8d99ae", badge=False)
            ttk.Button(badge, text=" Switch user", image=switch_icon or "", compound="left", style="Link.TButton",
                       command=self.on_switch_user).grid(row=0, column=2, rowspan=2, padx=(16, 0))

        # Row 1: period, currency and search
        nav = ttk.Frame(header)
        nav.grid(row=1, column=0, sticky="w")
        ttk.Button(nav, text="◀", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.month_box = ttk.Combobox(nav, width=16, state="readonly")
        self.month_box.pack(side="left", padx=4)
        # Shows "September 2026" while month_var keeps "2026-09" for filtering.
        self.month_choices = MonthChoices(self.month_box, self.month_var, {ALL: ALL})
        self.month_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh(), add="+")
        ttk.Button(nav, text="▶", width=3, command=lambda: self.shift_month(1)).pack(side="left")

        show = ttk.Frame(header)
        show.grid(row=1, column=1, sticky="w", padx=(18, 0))
        ttk.Label(show, text="Show in").pack(side="left")
        for currency in CURRENCIES:
            ttk.Radiobutton(show, text=currency, value=currency, variable=self.show_in_var,
                            command=self.refresh).pack(side="left", padx=(6, 0))

        search = ttk.Frame(header)
        search.grid(row=1, column=2, sticky="w", padx=(18, 0))
        search_icon = self.icons.get("🔍", "#8d99ae", badge=False)
        ttk.Label(search, image=search_icon or "", text="" if search_icon else "🔍").pack(side="left")
        self.search_entry = ttk.Entry(search, textvariable=self.search_var, width=24)
        self.search_entry.pack(side="left", padx=(4, 2))
        ttk.Button(search, text="✕", width=3, command=lambda: self.search_var.set("")).pack(side="left")

        cards = ttk.Frame(header)
        cards.grid(row=0, column=4, rowspan=2, sticky="e")
        self.card_vars = {}
        for i, (key, title, style) in enumerate((
            ("income", "Income", "Income.CardValue.TLabel"),
            ("expenses", "Expenses", "Expense.CardValue.TLabel"),
            ("balance", "Balance", "CardValue.TLabel"),
        )):
            card = ttk.Frame(cards, padding=(14, 0, 0, 0))
            card.grid(row=0, column=i)
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="e")
            var = tk.StringVar()
            label = ttk.Label(card, textvariable=var, style=style)
            label.pack(anchor="e")
            self.card_vars[key] = (var, label)

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.undo_button = ttk.Button(bar, style="Link.TButton", command=self.undo)
        self.redo_button = ttk.Button(bar, style="Link.TButton", command=self.redo)
        self.undo_button.grid(row=0, column=1, padx=(8, 0))
        self.redo_button.grid(row=0, column=2, padx=(6, 0))

    # ---------- undo / redo ----------

    def undo(self) -> None:
        self._step(self.history.undo, "Undone")

    def redo(self) -> None:
        self._step(self.history.redo, "Redone")

    def _step(self, action: Callable[[], str], verb: str) -> None:
        if self.grab_current():  # a dialog is open: don't change data underneath it
            return
        try:
            label = action()
        except ValueError as exc:
            self.set_status(str(exc))
            self.refresh()
            return
        self.reload_catalog()  # the restored data may include catalog changes made in dialogs
        self.set_status(f"{verb}: {label}")
        self.refresh()

    def _update_undo_buttons(self) -> None:
        for button, label, arrow, name in ((self.undo_button, self.history.next_undo(), "↶", "Undo"),
                                          (self.redo_button, self.history.next_redo(), "↷", "Redo")):
            if label:
                button.configure(text=f"{arrow} {name}: {label}")
                button.grid()
            else:
                button.grid_remove()

    def _update_edit_menu(self) -> None:
        undo, redo = self.history.next_undo(), self.history.next_redo()
        self.edit_menu.entryconfigure(0, label=f"Undo {undo}" if undo else "Undo",
                                      state="normal" if undo else "disabled")
        self.edit_menu.entryconfigure(1, label=f"Redo {redo}" if redo else "Redo",
                                      state="normal" if redo else "disabled")

    # ---------- period ----------

    def shift_month(self, step: int) -> None:
        """◀ / ▶: previous/next month, or previous/next year when a whole year is selected."""
        period = self.selected_month()
        if period is None:
            self.month_var.set(month_key(date.today()))
        elif is_year(period):
            self.month_var.set(str(int(period) + step))
        else:
            self.month_var.set(add_months(period, step))
        self.refresh()

    def selected_month(self) -> str | None:
        """The selected period: a month ('2026-09'), a whole year ('2026'), or None for all months."""
        month = self.month_var.get()
        return None if month == ALL else month

    def focus_month(self) -> str:
        """The single month used by budgets and the 12-month chart."""
        period, today = self.selected_month(), month_key(date.today())
        if period is None:
            return today
        if is_year(period):
            return today if today.startswith(period) else f"{period}-12"
        return period

    def _update_period_choices(self, expenses: list[Expense], incomes: list[Income]) -> None:
        """Each year ('2026 · whole year') followed by its months, newest first."""
        months = {month_key(r.date) for r in [*expenses, *incomes]} | {month_key(date.today())}
        period = self.selected_month()
        if period and not is_year(period):
            months.add(period)
        years = {m[:4] for m in months} | ({period} if is_year(period) else set())
        choices = []
        for year in sorted(years, reverse=True):
            choices.append(year)
            choices.extend(sorted((m for m in months if m.startswith(year)), reverse=True))
        self.month_choices.set_months(choices)

    # ---------- called by dialogs and tabs after a change ----------

    def expense_saved(self, expense: Expense, verb: str) -> None:
        """After adding or editing: make the expense visible and select it."""
        self.expenses_tab.reveal(expense)
        self.set_status(
            f"{verb} {format_money(expense.amount_pen, 'PEN')} / {format_money(expense.amount_usd, 'USD')} "
            f"· {expense.category}{' › ' + expense.subcategory if expense.subcategory else ''} · {expense.date}"
            f" · rate {format_rate(expense.rate)}"
        )
        self.notebook.select(self.expenses_tab)
        self.refresh(select_expense=expense.id)

    def income_saved(self, income: Income, verb: str) -> None:
        self.income_tab.reveal(income)
        self.set_status(f"{verb} income {format_money(income.amount_pen, 'PEN')} / "
                        f"{format_money(income.amount_usd, 'USD')} · {income.source} · {income.date}")
        self.notebook.select(self.income_tab)
        self.refresh(select_income=income.id)

    def debt_saved(self, debt_id: str, message: str) -> None:
        """After a debt or payment change: show the Debts tab with that debt selected."""
        self.reload_catalog()  # recording a payment may have added "Debt payments" / "Debt repayment"
        self.set_status(message)
        self.notebook.select(self.debts_tab)
        self.refresh(select_debt=debt_id)

    def remind_debts(self) -> None:
        """On opening: a status-bar note when debts are overdue or due within a week."""
        if not self.winfo_exists():
            return
        summary = summarize_debts(self.debts_tab.debts, self.show_in_var.get())
        parts = [f"{summary.overdue} overdue"] if summary.overdue else []
        parts += [f"{summary.due_soon} due within {DUE_SOON_DAYS} days"] if summary.due_soon else []
        if parts:
            self.set_status(f"⚠ Debts: {' and '.join(parts)} — see the Debts tab.")

    def budgets_changed(self, category: str, is_set: bool) -> None:
        self.set_status(f"Budget for {category} {'saved' if is_set else 'removed'}.")
        self.refresh()

    def recurring_saved(self, item: RecurringExpense) -> None:
        self.set_status(f"Saved recurring expense: {item.description or item.subcategory or item.category}.")
        self.refresh()
        self.check_recurring()

    def check_recurring(self, manual: bool = False) -> None:
        if not self.winfo_exists():  # the user switched away before this delayed check ran
            return
        try:
            due = self.store.due_recurring()
        except (ValueError, OSError):
            return
        if due:
            DueRecurringDialog(self, due)
        elif manual:
            self.set_status("No recurring expenses are due right now.")

    def recurring_applied(self, created: list[Expense], skipped: int) -> None:
        self.set_status(f"Added {len(created)} recurring expense(s)" + (f", skipped {skipped}." if skipped else "."))
        if created:
            self.expenses_tab.set_rate(created[-1].rate)
        self.refresh()

    def imported(self, count: int, duplicates: int) -> None:
        self.set_status(f"Imported {count} expenses" + (f" ({duplicates} duplicates skipped)." if duplicates else "."))
        self.refresh()

    # ---------- file actions ----------

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(title="Import expenses from CSV",
                                          filetypes=[("CSV files", "*.csv *.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            ImportDialog(self, path)
        except (ValueError, OSError, csv.Error) as exc:
            messagebox.showerror("Import", f"Couldn't read this file:\n{exc}")

    def export(self) -> None:
        shown = self.expenses_tab.shown
        path = filedialog.asksaveasfilename(
            title="Export expenses", defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=f"expenses-{self.selected_month() or 'all'}.csv",
        )
        if not path:
            return
        try:
            export_csv(shown, path)
        except OSError as exc:
            messagebox.showerror("Could not export", str(exc))
            return
        self.set_status(f"Exported {len(shown)} expenses to {path}")

    def backup_now(self) -> None:
        try:
            path = self.store.backup_now()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Backup", str(exc))
            return
        self.set_status(f"Backup saved: {path}")

    def open_data_folder(self) -> None:
        folder = self.store.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        open_file(folder)

    # ---------- refresh everything ----------

    def refresh(
        self, select_expense: str | None = None, select_income: str | None = None, select_debt: str | None = None
    ) -> None:
        """Load the data once, update the header, and ask every tab to redraw."""
        try:
            expenses = self.store.load()
            incomes = self.store.load_incomes()
            budgets = self.store.budgets()
            debts = load_debts(self.store)
        except (ValueError, KeyError, OSError) as exc:
            messagebox.showerror("Could not read data file", f"{self.store.path}\n\n{exc}")
            return
        self._update_period_choices(expenses, incomes)
        data = PageData(
            expenses=expenses, incomes=incomes, budgets=budgets,
            show_in=self.show_in_var.get(), period=self.selected_month(), focus_month=self.focus_month(),
            select_expense=select_expense, select_income=select_income,
            debts=debts, select_debt=select_debt,
        )

        earned, spent, net = balance(expenses, incomes, data.period, data.show_in)
        self.card_vars["income"][0].set(format_money(earned, data.show_in))
        self.card_vars["expenses"][0].set(format_money(spent, data.show_in))
        balance_var, balance_label = self.card_vars["balance"]
        balance_var.set(format_money(net, data.show_in))
        balance_label.configure(style="Income.CardValue.TLabel" if net >= 0 else "Expense.CardValue.TLabel")

        for tab in self.tabs:
            tab.redraw(data)
        self._update_undo_buttons()
