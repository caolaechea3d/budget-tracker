"""Main window: header with month/balance, and tabs for expenses, income, charts, budgets, recurring."""

from __future__ import annotations

import csv
import tkinter as tk
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME
from ..catalog import PALETTE, Category, Item, category_look, find_category, find_item
from ..reports import (
    balance,
    budget_statuses,
    by_subcategory,
    category_totals,
    change_pct,
    compare_with_previous_month,
    format_change,
    in_month,
    is_year,
    last_n_months,
    matches,
    monthly_totals,
)
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
    total_in,
)
from ..users import User
from .charts import draw_bars, draw_donut
from .forms import (
    BudgetDialog,
    DueRecurringDialog,
    ExpenseDialog,
    IncomeDialog,
    MoneyFields,
    RecurringDialog,
    expense_from_fields,
    income_from_fields,
    open_file,
)
from .icons import Icons
from .import_dialog import ImportDialog
from .manage import CategoriesDialog, ItemsDialog
from .widgets import (
    DateField,
    MonthChoices,
    Picker,
    ScrollableFrame,
    SortableColumns,
    month_label,
    setup_style,
    text_key,
)

ALL = "All months"
EXPENSE_COLOR = "#e76f51"
INCOME_COLOR = "#43aa8b"
LEVEL_COLORS = {"ok": "#43aa8b", "warning": "#f4a261", "over": "#e63946"}


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
        self._setup_style()
        self.reload_catalog()

        self.month_var = tk.StringVar(value=month_key(date.today()))
        self.show_in_var = tk.StringVar(value=DEFAULT_CURRENCY)
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value=f"Data file: {store.path}")
        self.category_filter_var = tk.StringVar()
        self.payment_filter_var = tk.StringVar()
        self.tag_filter_var = tk.StringVar()
        self.shown_expenses: list[Expense] = []
        self.shown_incomes: list[Income] = []
        self.all_expenses: list[Expense] = []

        self._build_menu(master)
        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 4))
        self._build_expenses_tab()
        self._build_income_tab()
        self._build_charts_tab()
        self._build_budgets_tab()
        self._build_recurring_tab()
        ttk.Label(self, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=12, pady=(0, 6))

        self.search_var.trace_add("write", lambda *_: self.refresh())
        master.bind("<Control-f>", lambda _e: self.search_entry.focus_set())
        master.bind("<Control-n>", lambda _e: (self.notebook.select(0), self.quick.amount.focus_set()))
        self.refresh()
        (self.quick.amount if self.quick.rate_var.get() else self.quick.rate).focus_set()
        self.after(500, self.check_recurring)

    # ---------- style ----------

    def _setup_style(self) -> None:
        setup_style(self, self.icons)

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

    def add_category(self, name: str) -> None:
        if not find_category(self.categories, name):
            self.categories.append(Category(name, color=self.next_color()))
            self.store.save_categories(self.categories)

    def add_subcategory(self, category: str, name: str) -> None:
        if not category:
            return
        cat = find_category(self.categories, category)
        if cat is None:
            cat = Category(category, color=self.next_color())
            self.categories.append(cat)
        if not cat.subcategory(name):
            cat.subcategories.append(Item(name, cat.icon))
            self.store.save_categories(self.categories)

    def add_payment_method(self, name: str) -> None:
        if not find_item(self.payment_methods, name):
            self.payment_methods.append(Item(name, "💳"))
            self.store.save_payment_methods(self.payment_methods)

    def add_income_source(self, name: str) -> None:
        if not find_item(self.income_sources, name):
            self.income_sources.append(Item(name, "💰"))
            self.store.save_income_sources(self.income_sources)

    def look(self, category: str, subcategory: str = "") -> tuple[str, str]:
        return category_look(self.categories, category, subcategory)

    def last_rate(self) -> Decimal | None:
        try:
            return self.store.last_rate()
        except (ValueError, OSError):
            return None

    def _icon_text(self, icon: str, color: str, text: str) -> dict:
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

        # Row 0: who is using the app (left) and the month's balance (right)
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

    def _tab(self, text: str, icon: str, color: str) -> ttk.Frame:
        frame = ttk.Frame(self.notebook, padding=10)
        image = self.icons.get(icon, color)
        self.notebook.add(frame, text=f" {text}" if image else self.icons.text(icon, text),
                          image=image or "", compound="left")
        return frame

    # ---------- expenses tab ----------

    def _build_expenses_tab(self) -> None:
        tab = self._tab("Expenses", "💸", EXPENSE_COLOR)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(tab, text="Add expense", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        last = self.last_rate()
        self.quick = MoneyFields(form, rate="" if last is None else format_rate(last))
        self.q_date = tk.StringVar(value=date.today().isoformat())
        self.q_category = tk.StringVar(value="Food")
        self.q_subcategory = tk.StringVar()
        self.q_payment = tk.StringVar()
        self.q_description = tk.StringVar()
        self.q_tags = tk.StringVar()
        widgets = [
            ("Date", DateField(form, self.q_date, icons=self.icons)),
            ("Amount", self.quick.amount),
            ("Currency", self.quick.currency),
            ("Rate (S/ per US$1)", self.quick.rate),
            ("Category", Picker(form, self.icons, self.q_category, self.category_options,
                                on_new=self.add_category, new_label="New category…",
                                on_change=lambda: self.q_subcategory.set(""), width=16)),
            ("Subcategory", Picker(form, self.icons, self.q_subcategory,
                                   lambda: self.subcategory_options(self.q_category.get()), none_label="(none)",
                                   on_new=lambda n: self.add_subcategory(self.q_category.get(), n),
                                   new_label="New subcategory…", width=16)),
            ("Payment", Picker(form, self.icons, self.q_payment, self.payment_options, none_label="(none)",
                               on_new=self.add_payment_method, new_label="New payment method…", width=14)),
        ]
        self.quick.amount.configure(width=10)
        self.quick.rate.configure(width=8)
        for col, (label, widget) in enumerate(widgets):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=col, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Description").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(form, text="Tags (comma separated)").grid(row=2, column=4, sticky="w", pady=(6, 0))
        description = ttk.Entry(form, textvariable=self.q_description)
        description.grid(row=3, column=0, columnspan=4, sticky="ew", padx=(0, 8))
        tags = ttk.Entry(form, textvariable=self.q_tags)
        tags.grid(row=3, column=4, columnspan=2, sticky="ew", padx=(0, 8))
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=6, sticky="ew")
        ttk.Button(buttons, text="Add", command=self.add_expense).pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="More…", width=7, command=self.add_expense_full).pack(side="left", padx=(4, 0))
        self.quick.preview.grid(row=4, column=1, columnspan=4, sticky="w", pady=(4, 0))
        form.columnconfigure(7, weight=1)  # empty spacer: fields keep their natural width
        for widget in (widgets[0][1].entry, self.quick.amount, self.quick.rate, description, tags):
            widget.bind("<Return>", lambda _e: self.add_expense())

        filters = ttk.Frame(tab)
        filters.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(filters, text="Filter:").pack(side="left")
        Picker(filters, self.icons, self.category_filter_var, self.category_options,
               none_label="All categories", on_change=self.refresh, width=16).pack(side="left", padx=(6, 6))
        Picker(filters, self.icons, self.payment_filter_var, self.payment_options,
               none_label="All payment methods", on_change=self.refresh, width=21).pack(side="left")
        Picker(filters, self.icons, self.tag_filter_var, self.tag_options,
               none_label="All tags", on_change=self.refresh, width=16).pack(side="left", padx=(6, 0))
        ttk.Button(filters, text="Clear filters", command=self.clear_filters).pack(side="left", padx=(6, 0))
        self.filter_note = ttk.Label(filters, style="Warning.TLabel")
        self.filter_note.pack(side="left", padx=(12, 0))

        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")
        left = ttk.Frame(panes)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        columns = ("date", "amount", "entered", "payment", "description", "tags")
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Category", anchor="w")
        self.tree.column("#0", width=185, stretch=False)
        for col, text, width, anchor, stretch in (
            ("date", "Date", 84, "w", False),
            ("amount", "Amount", 96, "e", False),
            ("entered", "Entered as @ rate", 132, "e", False),
            ("payment", "Payment", 92, "w", False),
            ("description", "Description", 130, "w", True),
            ("tags", "Tags", 90, "w", False),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.expense_sort = SortableColumns(
            self.tree,
            {"#0": "Category", "date": "Date", "amount": "Amount", "entered": "Entered as @ rate",
             "payment": "Payment", "description": "Description", "tags": "Tags"},
            keys={
                "#0": lambda e: (e.category.lower(), e.subcategory.lower()),
                "date": lambda e: (e.date, e.id),
                "amount": lambda e: e.amount_in(self.show_in_var.get()),
                "entered": lambda e: (e.currency, e.amount),
                "payment": lambda e: text_key(e.payment_method),
                "description": lambda e: text_key(e.description),
                "tags": lambda e: text_key(" ".join(e.tags)),
            },
            default=("date", True), on_change=self.refresh, descending_first=("date", "amount", "entered"),
        )
        self.tree.bind("<Double-1>", self._on_expense_double_click)
        self.tree.bind("<Return>", lambda _e: self.edit_selected())
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.tree.bind("<Button-3>", self._expense_context_menu)

        actions = ttk.Frame(left)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for text, command in (("Edit", self.edit_selected), ("Duplicate", self.duplicate_selected),
                              ("Open receipt", self.open_receipt), ("Delete", self.delete_selected)):
            ttk.Button(actions, text=text, command=command).pack(side="left", padx=(0, 6))
        self.expense_total_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.expense_total_var, style="Bold.TLabel").pack(side="right")
        panes.add(left, weight=3)

        right = ttk.LabelFrame(panes, text="By category", padding=6)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.summary = ttk.Treeview(right, columns=("total", "share", "change", "budget"), show="tree headings")
        self.summary.heading("#0", text="Category", anchor="w")
        self.summary.column("#0", width=150)
        for col, text, width in (("total", "Total", 92), ("share", "%", 42), ("change", "vs prev.", 66),
                                 ("budget", "Budget", 54)):
            self.summary.heading(col, text=text, anchor="e")
            self.summary.column(col, width=width, anchor="e", stretch=False)
        self.summary.tag_configure("over", foreground="#c0392b")
        self.summary.tag_configure("warning", foreground="#b35c00")
        self.summary.tag_configure("sub", foreground="#4b5563")
        self.summary.grid(row=0, column=0, sticky="nsew")
        panes.add(right, weight=2)
        # Give the list about 64% of the width the first time the window is shown.
        def place_sash(_event: tk.Event) -> None:
            panes.unbind("<Map>")
            panes.after_idle(lambda: panes.sashpos(0, int(panes.winfo_width() * 0.64)))
        panes.bind("<Map>", place_sash)

        self.expense_menu = tk.Menu(self, tearoff=False)
        self.expense_menu.add_command(label="Edit…", command=self.edit_selected)
        self.expense_menu.add_command(label="Duplicate…", command=self.duplicate_selected)
        self.expense_menu.add_command(label="Open receipt", command=self.open_receipt)
        self.expense_menu.add_separator()
        self.expense_menu.add_command(label="Delete", command=self.delete_selected)

    def clear_filters(self) -> None:
        self.category_filter_var.set("")
        self.payment_filter_var.set("")
        self.tag_filter_var.set("")
        self.search_var.set("")
        self.refresh()

    def tag_options(self) -> list[tuple[str, str, str]]:
        tags = sorted({t for e in self.all_expenses for t in e.tags})
        return [(t, "🏷", "#8d99ae") for t in tags]

    def _visible_expenses(self) -> tuple[list[Expense], str]:
        search = self.search_var.get().strip()
        month = self.selected_month()
        expenses = self.all_expenses if search else in_month(self.all_expenses, month)
        notes = []
        if search:
            expenses = [e for e in expenses if matches(e, search)]
            notes.append(f"Searching all months for “{search}”")
        category = self.category_filter_var.get()
        if category:
            expenses = [e for e in expenses if e.category.lower() == category.lower()]
        payment = self.payment_filter_var.get()
        if payment:
            expenses = [e for e in expenses if e.payment_method.lower() == payment.lower()]
        tag = self.tag_filter_var.get()
        if tag:
            expenses = [e for e in expenses if tag in e.tags]
        if category or payment or tag:
            notes.append("Filtered")
        # Newest first as the tie-breaker; the clicked column decides the main order.
        expenses = sorted(expenses, key=lambda e: (e.date, e.id), reverse=True)
        return self.expense_sort.apply(expenses), " · ".join(notes)

    def _refresh_expenses(self, show_in: str, select_id: str | None) -> None:
        keep = set(self.tree.selection())
        self.shown_expenses, note = self._visible_expenses()
        self.filter_note.configure(text=note)
        self.expense_sort.set_heading("amount", f"Amount ({show_in})")
        self.tree.delete(*self.tree.get_children())
        for e in self.shown_expenses:
            icon, color = self.look(e.category, e.subcategory)
            label = f"{e.category} › {e.subcategory}" if e.subcategory else e.category
            self.tree.insert("", "end", iid=e.id, **self._icon_text(icon, color, label), values=(
                e.date.isoformat(),
                format_money(e.amount_in(show_in), show_in),
                f"{format_money(e.amount, e.currency)} @ {format_rate(e.rate)}",
                e.payment_method,
                ("📎 " if e.receipt else "") + e.description,
                " ".join(f"#{t}" for t in e.tags),
            ))
        total, missing = total_in(self.shown_expenses, show_in)
        count = len(self.shown_expenses)
        extra = f", {missing} without rate not counted" if missing else ""
        self.expense_total_var.set(f"Total: {format_money(total, show_in)}   ({count} expense{'s' * (count != 1)}{extra})")
        wanted = [select_id] if select_id else [i for i in keep if self.tree.exists(i)]
        wanted = [i for i in wanted if i and self.tree.exists(i)]
        if wanted:
            self.tree.selection_set(wanted)
            self.tree.see(wanted[0])

    def _refresh_summary(self, show_in: str, budgets: dict) -> None:
        open_rows = {iid for iid in self.summary.get_children() if self.summary.item(iid, "open")}
        self.summary.delete(*self.summary.get_children())
        month = self.selected_month()
        month_expenses = in_month(self.all_expenses, month)
        totals = category_totals(self.all_expenses, month, show_in)
        grand = sum(totals.values(), Decimal("0"))
        comparison = compare_with_previous_month(self.all_expenses, month, show_in) if month else {}
        is_single_month = month is not None and not is_year(month)  # budgets are monthly
        statuses = ({s.budget.category.lower(): s for s in budget_statuses(self.all_expenses, budgets, month)}
                    if is_single_month else {})
        self.summary.heading("change", text="vs prev." if month else "")
        self.summary.heading("budget", text="Budget" if is_single_month else "")
        for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            icon, color = self.look(category)
            now, before = comparison.get(category, (amount, Decimal("0")))
            status = statuses.get(category.lower())
            budget_text = f"{status.ratio * 100:.0f}%" if status else ""
            iid = f"cat:{category}"
            self.summary.insert("", "end", iid=iid, open=iid in open_rows, **self._icon_text(icon, color, category),
                                tags=(status.level,) if status and status.level != "ok" else (),
                                values=(format_money(amount, show_in), f"{amount / grand * 100:.1f}" if grand else "",
                                        format_change(change_pct(now, before), new=bool(month) and before == 0),
                                        budget_text))
            subs = by_subcategory(month_expenses, category, show_in)
            if len(subs) > 1 or (len(subs) == 1 and "" not in subs):
                for sub, value in subs.items():
                    sub_icon, _ = self.look(category, sub) if sub else ("▫", color)
                    self.summary.insert(iid, "end", tags=("sub",), **self._icon_text(sub_icon, color, sub or "(no subcategory)"),
                                        values=(format_money(value, show_in), f"{value / grand * 100:.1f}" if grand else "", "", ""))

    def add_expense(self) -> None:
        try:
            expense = expense_from_fields(
                self.q_date.get(), self.quick.amount_var.get(), self.quick.currency_var.get(),
                self.quick.rate_var.get(), self.q_category.get(), self.q_description.get(),
                subcategory=self.q_subcategory.get(), payment_method=self.q_payment.get(), tags=self.q_tags.get(),
            )
            self.store.add(expense)
        except ValueError as exc:
            messagebox.showerror("Invalid expense", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        # Keep date, currency, rate, category and payment for the next entry; clear the rest.
        self.quick.rate_var.set(format_rate(expense.rate))
        self.quick.amount_var.set("")
        self.q_description.set("")
        self.q_tags.set("")
        self.expense_saved(expense, "Added")
        self.quick.amount.focus_set()

    def add_expense_full(self) -> None:
        """Open the full form (with receipt) pre-filled with what's typed in the quick form."""
        draft = Expense(
            amount=Decimal("0"), category=self.q_category.get() or "Food", subcategory=self.q_subcategory.get(),
            payment_method=self.q_payment.get(), description=self.q_description.get(),
            currency=self.quick.currency_var.get(), tags=[t for t in self.q_tags.get().split(",") if t.strip()],
        )
        dialog = ExpenseDialog(self, draft, duplicate=True)
        dialog.title("New expense")
        dialog.money.amount_var.set(self.quick.amount_var.get())
        dialog.money.rate_var.set(self.quick.rate_var.get())
        dialog.date_var.set(self.q_date.get())

    def expense_saved(self, expense: Expense, verb: str) -> None:
        """After adding or editing: make the expense visible and select it."""
        month = month_key(expense.date)
        period = self.selected_month()
        if period and not month.startswith(period):
            self.month_var.set(month)
        if self.category_filter_var.get() and self.category_filter_var.get().lower() != expense.category.lower():
            self.category_filter_var.set("")
        if self.payment_filter_var.get() and self.payment_filter_var.get().lower() != expense.payment_method.lower():
            self.payment_filter_var.set("")
        if self.tag_filter_var.get() and self.tag_filter_var.get() not in expense.tags:
            self.tag_filter_var.set("")
        if self.search_var.get() and not matches(expense, self.search_var.get()):
            self.search_var.set("")
        self.set_status(
            f"{verb} {format_money(expense.amount_pen, 'PEN')} / {format_money(expense.amount_usd, 'USD')} "
            f"· {expense.category}{' › ' + expense.subcategory if expense.subcategory else ''} · {expense.date}"
            f" · rate {format_rate(expense.rate)}"
        )
        self.notebook.select(0)
        self.refresh(select_expense=expense.id)

    def _selected_expense(self) -> Expense | None:
        selected = self.tree.selection()
        if len(selected) != 1:
            self.set_status("Select one expense first (or double-click it).")
            return None
        return next((e for e in self.shown_expenses if e.id == selected[0]), None)

    def _on_expense_double_click(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.edit_selected()

    def _expense_context_menu(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.expense_menu.tk_popup(event.x_root, event.y_root)

    def edit_selected(self) -> None:
        expense = self._selected_expense()
        if expense:
            ExpenseDialog(self, expense)

    def duplicate_selected(self) -> None:
        expense = self._selected_expense()
        if expense:
            ExpenseDialog(self, expense, duplicate=True)

    def open_receipt(self) -> None:
        expense = self._selected_expense()
        if not expense:
            return
        path = self.store.receipt_path(expense)
        if path is None:
            self.set_status("This expense has no receipt. Use Edit → Attach… to add one.")
            return
        open_file(path)

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            self.set_status("Select one or more expenses to delete.")
            return
        noun = "this expense" if len(selected) == 1 else f"these {len(selected)} expenses"
        if not messagebox.askyesno("Delete", f"Delete {noun}?"):
            return
        for expense_id in selected:
            self.store.delete(expense_id)
        self.set_status(f"Deleted {len(selected)} expense(s).")
        self.refresh()

    # ---------- income tab ----------

    def _build_income_tab(self) -> None:
        tab = self._tab("Income", "💵", INCOME_COLOR)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        form = ttk.LabelFrame(tab, text="Add income", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        last = self.last_rate()
        self.income_quick = MoneyFields(form, rate="" if last is None else format_rate(last))
        self.i_date = tk.StringVar(value=date.today().isoformat())
        self.i_source = tk.StringVar(value="Salary")
        self.i_description = tk.StringVar()
        description = ttk.Entry(form, textvariable=self.i_description)
        widgets = [
            ("Date", DateField(form, self.i_date, icons=self.icons)),
            ("Amount", self.income_quick.amount),
            ("Currency", self.income_quick.currency),
            ("Rate (S/ per US$1)", self.income_quick.rate),
            ("Source", Picker(form, self.icons, self.i_source, self.source_options, on_new=self.add_income_source,
                              new_label="New income source…", width=16)),
            ("Description", description),
        ]
        self.income_quick.amount.configure(width=10)
        self.income_quick.rate.configure(width=8)
        for col, (label, widget) in enumerate(widgets):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=col, sticky="ew", padx=(0, 8))
            if isinstance(widget, ttk.Entry):
                widget.bind("<Return>", lambda _e: self.add_income())
        ttk.Button(form, text="Add", command=self.add_income).grid(row=1, column=6)
        self.income_quick.preview.grid(row=2, column=1, columnspan=4, sticky="w", pady=(4, 0))
        form.columnconfigure(5, weight=1)

        body = ttk.Frame(tab)
        body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.income_tree = ttk.Treeview(body, columns=("date", "amount", "entered", "rate", "description"),
                                        show="tree headings", selectmode="extended")
        self.income_tree.heading("#0", text="Source", anchor="w")
        self.income_tree.column("#0", width=180, stretch=False)
        for col, text, width, anchor, stretch in (
            ("date", "Date", 90, "w", False), ("amount", "Amount", 110, "e", False),
            ("entered", "Entered as", 110, "e", False), ("rate", "Rate", 60, "e", False),
            ("description", "Description", 200, "w", True),
        ):
            self.income_tree.heading(col, text=text, anchor=anchor)
            self.income_tree.column(col, width=width, anchor=anchor, stretch=stretch)
        self.income_tree.grid(row=0, column=0, sticky="nsew")
        self.income_sort = SortableColumns(
            self.income_tree,
            {"#0": "Source", "date": "Date", "amount": "Amount", "entered": "Entered as",
             "rate": "Rate", "description": "Description"},
            keys={
                "#0": lambda i: i.source.lower(),
                "date": lambda i: (i.date, i.id),
                "amount": lambda i: i.amount_in(self.show_in_var.get()),
                "entered": lambda i: (i.currency, i.amount),
                "rate": lambda i: i.rate,
                "description": lambda i: text_key(i.description),
            },
            default=("date", True), on_change=self.refresh, descending_first=("date", "amount", "entered", "rate"),
        )
        self.income_tree.bind("<Double-1>", lambda e: self._edit_income_at(e.y))
        self.income_tree.bind("<Delete>", lambda _e: self.delete_incomes())
        actions = ttk.Frame(body)
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Edit", command=self.edit_income).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Delete", command=self.delete_incomes).pack(side="left")
        self.income_total_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.income_total_var, style="Bold.TLabel").pack(side="right")

    def _refresh_income(self, incomes: list[Income], show_in: str, select_id: str | None) -> None:
        month = self.selected_month()
        newest_first = sorted(in_month(incomes, month), key=lambda i: (i.date, i.id), reverse=True)
        self.shown_incomes = self.income_sort.apply(newest_first)
        self.income_sort.set_heading("amount", f"Amount ({show_in})")
        self.income_tree.delete(*self.income_tree.get_children())
        for inc in self.shown_incomes:
            source = find_item(self.income_sources, inc.source)
            self.income_tree.insert("", "end", iid=inc.id, **self._icon_text(source.icon if source else "💰", INCOME_COLOR, inc.source),
                                    values=(inc.date.isoformat(), format_money(inc.amount_in(show_in), show_in),
                                            format_money(inc.amount, inc.currency), format_rate(inc.rate), inc.description))
        total, _ = total_in(self.shown_incomes, show_in)
        self.income_total_var.set(f"Total: {format_money(total, show_in)}   ({len(self.shown_incomes)} entries)")
        if select_id and self.income_tree.exists(select_id):
            self.income_tree.selection_set(select_id)
            self.income_tree.see(select_id)

    def add_income(self) -> None:
        try:
            income = income_from_fields(
                self.i_date.get(), self.income_quick.amount_var.get(), self.income_quick.currency_var.get(),
                self.income_quick.rate_var.get(), self.i_source.get(), self.i_description.get(),
            )
            self.store.add_income(income)
        except ValueError as exc:
            messagebox.showerror("Invalid income", str(exc))
            return
        self.income_quick.amount_var.set("")
        self.i_description.set("")
        self.income_saved(income, "Added")

    def income_saved(self, income: Income, verb: str) -> None:
        month = month_key(income.date)
        period = self.selected_month()
        if period and not month.startswith(period):
            self.month_var.set(month)
        self.set_status(f"{verb} income {format_money(income.amount_pen, 'PEN')} / "
                        f"{format_money(income.amount_usd, 'USD')} · {income.source} · {income.date}")
        self.notebook.select(1)
        self.refresh(select_income=income.id)

    def _edit_income_at(self, y: int) -> None:
        row = self.income_tree.identify_row(y)
        if row:
            self.income_tree.selection_set(row)
            self.edit_income()

    def edit_income(self) -> None:
        selected = self.income_tree.selection()
        income = next((i for i in self.shown_incomes if selected and i.id == selected[0]), None)
        if income:
            IncomeDialog(self, income)

    def delete_incomes(self) -> None:
        selected = self.income_tree.selection()
        if selected and messagebox.askyesno("Delete", f"Delete {len(selected)} income entr{'y' if len(selected) == 1 else 'ies'}?"):
            for income_id in selected:
                self.store.delete_income(income_id)
            self.refresh()

    # ---------- charts tab ----------

    def _build_charts_tab(self) -> None:
        tab = self._tab("Charts", "📊", "#577590")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.donut_box = ttk.LabelFrame(tab, text="Spending by category", padding=6)
        self.donut_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.bars_box = ttk.LabelFrame(tab, text="Income vs expenses — last 12 months", padding=6)
        self.bars_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.donut = tk.Canvas(self.donut_box, highlightthickness=0, background=background)
        self.donut.pack(fill="both", expand=True)
        self.bars = tk.Canvas(self.bars_box, highlightthickness=0, background=background)
        self.bars.pack(fill="both", expand=True)
        self.donut.bind("<Configure>", lambda _e: self._draw_charts())
        self.bars.bind("<Configure>", lambda _e: self._draw_charts())
        self._chart_data = None

    def _prepare_charts(self, incomes: list[Income], show_in: str) -> None:
        month = self.selected_month()
        totals = category_totals(self.all_expenses, month, show_in)
        slices = []
        for category, value in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
            icon, color = self.look(category)
            slices.append((category, value, color, self.icons.get(icon, color)))
        end = self.focus_month()
        months = last_n_months(end)
        series = [
            ("Income", monthly_totals(incomes, months, show_in), INCOME_COLOR),
            ("Expenses", monthly_totals(self.all_expenses, months, show_in), EXPENSE_COLOR),
        ]
        total = sum(totals.values(), Decimal("0"))
        self.donut_box.configure(text=f"Spending by category — {month_label(month) if month else 'all time'} ({show_in})")
        self.bars_box.configure(text=f"Income vs expenses — last 12 months ({show_in})")
        self._chart_data = (slices, format_money(total, show_in), months, series, end)
        self._draw_charts()

    def _draw_charts(self) -> None:
        if not self._chart_data:
            return
        slices, total_text, months, series, end = self._chart_data
        draw_donut(self.donut, slices, "Total", total_text)
        draw_bars(self.bars, months, series, highlight=end)

    # ---------- budgets tab ----------

    def _build_budgets_tab(self) -> None:
        tab = self._tab("Budgets", "🎯", "#e63946")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.budget_title = ttk.Label(top, style="Title.TLabel")
        self.budget_title.pack(side="left")
        ttk.Button(top, text="Set budget…", command=lambda: BudgetDialog(self)).pack(side="right")
        self.budget_list = ScrollableFrame(tab)
        self.budget_list.grid(row=1, column=0, sticky="nsew")
        self.budget_list.inner.columnconfigure(2, weight=1)

    def _refresh_budgets(self, budgets: dict) -> None:
        month = self.focus_month()
        period = self.selected_month()
        note = "" if period and not is_year(period) else "  (budgets are per month)"
        self.budget_title.configure(text=f"Monthly budgets — {month_label(month)}{note}")
        inner = self.budget_list.inner
        for child in inner.winfo_children():
            child.destroy()
        statuses = budget_statuses(self.all_expenses, budgets, month)
        row = 0
        if not statuses:
            ttk.Label(inner, text="No budgets yet. Click “Set budget…” to set a monthly limit for a category.",
                      style="Muted.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=6)
            row = 1
        for status in statuses:
            b = status.budget
            icon, color = self.look(b.category)
            ttk.Label(inner, **self._icon_text(icon, color, b.category), compound="left",
                      style="Bold.TLabel").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 10))
            bar = tk.Canvas(inner, height=round(14 * self.icons.scale), highlightthickness=0,
                            background="#e5e7eb")
            bar.grid(row=row, column=2, sticky="ew", padx=(0, 12))
            ratio = float(status.ratio)
            bar_color = LEVEL_COLORS[status.level]
            bar.bind("<Configure>", lambda e, c=bar, r=ratio, col=bar_color: self._draw_progress(c, r, col))
            left_text = (f"{format_money(status.remaining, b.currency)} left" if status.remaining >= 0
                         else f"over by {format_money(-status.remaining, b.currency)}")
            text = f"{format_money(status.spent, b.currency)} of {format_money(b.amount, b.currency)} · {ratio * 100:.0f}% · {left_text}"
            if status.missing_rate:
                text += f" · {status.missing_rate} without rate"
            label_style = {"ok": "TLabel", "warning": "Warning.TLabel", "over": "Over.TLabel"}[status.level]
            ttk.Label(inner, text=text, style=label_style).grid(
                row=row, column=3, sticky="w", padx=(0, 10))
            ttk.Button(inner, text="Edit", width=6, command=lambda c=b.category: BudgetDialog(self, c)).grid(row=row, column=4)
            ttk.Button(inner, text="Remove", width=8, command=lambda c=b.category: self.remove_budget(c)).grid(
                row=row, column=5, padx=(4, 0))
            row += 1

        budgeted = {b.lower() for b in budgets}
        unbudgeted = {c: v for c, v in category_totals(self.all_expenses, month, DEFAULT_CURRENCY).items()
                      if c.lower() not in budgeted}
        if unbudgeted:
            ttk.Separator(inner).grid(row=row, column=0, columnspan=6, sticky="ew", pady=10)
            ttk.Label(inner, text="Spending without a budget this month", style="Muted.TLabel").grid(
                row=row + 1, column=0, columnspan=6, sticky="w")
            row += 2
            for category, value in sorted(unbudgeted.items(), key=lambda kv: kv[1], reverse=True):
                icon, color = self.look(category)
                ttk.Label(inner, **self._icon_text(icon, color, category), compound="left").grid(
                    row=row, column=0, sticky="w", pady=3)
                ttk.Label(inner, text=format_money(value, DEFAULT_CURRENCY)).grid(row=row, column=3, sticky="w")
                ttk.Button(inner, text="Set budget", command=lambda c=category: BudgetDialog(self, c)).grid(
                    row=row, column=4, columnspan=2, sticky="w")
                row += 1

    @staticmethod
    def _draw_progress(canvas: tk.Canvas, ratio: float, color: str) -> None:
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.create_rectangle(0, 0, width * min(ratio, 1.0), height, fill=color, outline="")
        if ratio > 1:
            canvas.create_line(width - 1, 0, width - 1, height, fill="#7f1d1d", width=2)

    def remove_budget(self, category: str) -> None:
        if messagebox.askyesno("Remove budget", f"Remove the monthly budget for {category}?"):
            self.store.set_budget(category, None)
            self.budgets_changed(category, False)

    def budgets_changed(self, category: str, is_set: bool) -> None:
        self.set_status(f"Budget for {category} {'saved' if is_set else 'removed'}.")
        self.refresh()

    # ---------- recurring tab ----------

    def _build_recurring_tab(self) -> None:
        tab = self._tab("Recurring", "🔁", "#8d6cab")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="Rent, subscriptions, bills… added for you each month.", style="Muted.TLabel").pack(side="left")
        for text, command in (("Check what's due", lambda: self.check_recurring(manual=True)),
                              ("Delete", self.delete_recurring), ("Pause / resume", self.toggle_recurring),
                              ("Edit…", self.edit_recurring), ("New…", lambda: RecurringDialog(self))):
            ttk.Button(top, text=text, command=command).pack(side="right", padx=(6, 0))
        self.recurring_tree = ttk.Treeview(tab, columns=("amount", "category", "day", "payment", "next", "status"),
                                           show="tree headings", selectmode="browse")
        self.recurring_tree.heading("#0", text="Recurring expense", anchor="w")
        self.recurring_tree.column("#0", width=220)
        for col, text, width, anchor in (("amount", "Amount", 110, "e"), ("category", "Category", 180, "w"),
                                         ("day", "Day", 60, "center"), ("payment", "Payment", 110, "w"),
                                         ("next", "Next", 100, "w"), ("status", "Status", 80, "w")):
            self.recurring_tree.heading(col, text=text, anchor=anchor)
            self.recurring_tree.column(col, width=width, anchor=anchor, stretch=col == "category")
        self.recurring_tree.tag_configure("paused", foreground="#9ca3af")
        self.recurring_tree.grid(row=1, column=0, sticky="nsew")
        self.recurring_tree.bind("<Double-1>", lambda _e: self.edit_recurring())

    def _refresh_recurring(self) -> None:
        tree = self.recurring_tree
        keep = tree.selection()
        tree.delete(*tree.get_children())
        for r in self.store.recurring():
            icon, color = self.look(r.category, r.subcategory)
            name = r.description or r.subcategory or r.category
            category = f"{r.category} › {r.subcategory}" if r.subcategory else r.category
            next_date = r.occurrence_date(r.next_month()).isoformat()
            tree.insert("", "end", iid=r.id, **self._icon_text(icon, color, name), tags=() if r.active else ("paused",),
                        values=(format_money(r.amount, r.currency), category, r.day, r.payment_method, next_date,
                                "Active" if r.active else "Paused"))
        for iid in keep:
            if tree.exists(iid):
                tree.selection_set(iid)

    def _selected_recurring(self) -> RecurringExpense | None:
        selected = self.recurring_tree.selection()
        return next((r for r in self.store.recurring() if selected and r.id == selected[0]), None)

    def edit_recurring(self) -> None:
        item = self._selected_recurring()
        if item:
            RecurringDialog(self, item)

    def toggle_recurring(self) -> None:
        item = self._selected_recurring()
        if item:
            item.active = not item.active
            self.store.save_recurring(item)
            self.refresh()

    def delete_recurring(self) -> None:
        item = self._selected_recurring()
        if item and messagebox.askyesno("Delete", "Delete this recurring expense?\n\n"
                                                  "Expenses already added from it are kept."):
            self.store.delete_recurring(item.id)
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
            self.quick.rate_var.set(format_rate(created[-1].rate))
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

    def imported(self, count: int, duplicates: int) -> None:
        self.set_status(f"Imported {count} expenses" + (f" ({duplicates} duplicates skipped)." if duplicates else "."))
        self.refresh()

    def export(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export expenses", defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            initialfile=f"expenses-{self.selected_month() or 'all'}.csv",
        )
        if not path:
            return
        try:
            export_csv(self.shown_expenses, path)
        except OSError as exc:
            messagebox.showerror("Could not export", str(exc))
            return
        self.set_status(f"Exported {len(self.shown_expenses)} expenses to {path}")

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

    def refresh(self, select_expense: str | None = None, select_income: str | None = None) -> None:
        try:
            self.all_expenses = self.store.load()
            incomes = self.store.load_incomes()
            budgets = self.store.budgets()
        except (ValueError, KeyError, OSError) as exc:
            messagebox.showerror("Could not read data file", f"{self.store.path}\n\n{exc}")
            return
        show_in = self.show_in_var.get()
        today_month = month_key(date.today())
        months = {month_key(r.date) for r in [*self.all_expenses, *incomes]} | {today_month}
        period = self.selected_month()
        if period and not is_year(period):
            months.add(period)
        years = {m[:4] for m in months} | ({period} if is_year(period) else set())
        # Each year ("2026 · whole year") followed by its months, newest first.
        choices = []
        for year in sorted(years, reverse=True):
            choices.append(year)
            choices.extend(sorted((m for m in months if m.startswith(year)), reverse=True))
        self.month_choices.set_months(choices)

        earned, spent, net = balance(self.all_expenses, incomes, self.selected_month(), show_in)
        self.card_vars["income"][0].set(format_money(earned, show_in))
        self.card_vars["expenses"][0].set(format_money(spent, show_in))
        balance_var, balance_label = self.card_vars["balance"]
        balance_var.set(format_money(net, show_in))
        balance_label.configure(style="Income.CardValue.TLabel" if net >= 0 else "Expense.CardValue.TLabel")

        self._refresh_expenses(show_in, select_expense)
        self._refresh_summary(show_in, budgets)
        self._refresh_income(incomes, show_in, select_income)
        self._prepare_charts(incomes, show_in)
        self._refresh_budgets(budgets)
        self._refresh_recurring()

