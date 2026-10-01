"""Dialog for importing expenses from a CSV file (e.g. a bank statement)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..importer import DATE_FORMATS, SIGN_CHOICES, ImportOptions, build_expenses, guess_columns, read_csv
from ..storage import CURRENCIES, DEFAULT_CURRENCY, format_rate, parse_currency, parse_rate, parse_tags
from .forms import RATE_MISSING
from .widgets import Dialog, Picker, TagField

if TYPE_CHECKING:
    from .app import ExpenseApp

NONE = "(none)"
PREVIEW_ROWS = 8


class ImportDialog(Dialog):
    def __init__(self, app: ExpenseApp, path: str):
        self.app = app
        self.data = read_csv(path)
        super().__init__(app, f"Import expenses — {Path(path).name}", ok_text="Import")
        b = self.body
        b.columnconfigure(0, weight=1)

        # Preview of the file
        headers = self.data.headers
        preview = ttk.Treeview(b, columns=[str(i) for i in range(len(headers))], show="headings", height=6)
        for i, h in enumerate(headers):
            preview.heading(str(i), text=h or f"Column {i + 1}")
            preview.column(str(i), width=110, stretch=True)
        for row in self.data.rows[:PREVIEW_ROWS]:
            preview.insert("", "end", values=row)
        preview.grid(row=0, column=0, sticky="ew")
        ttk.Label(b, text=f"{len(self.data.rows)} rows · separator '{self.data.delimiter}' · {self.data.encoding}",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 10))

        form = ttk.Frame(b)
        form.grid(row=2, column=0, sticky="ew")
        guess = guess_columns(headers)
        names = [h or f"Column {i + 1}" for i, h in enumerate(headers)]
        self.column_names = names

        def col_var(key: str, optional: bool) -> tk.StringVar:
            index = guess.get(key)
            if index is None and not optional:
                index = 0
            return tk.StringVar(value=names[index] if index is not None else NONE)

        self.date_var = col_var("date", False)
        self.date_format_var = tk.StringVar(value="Auto")
        self.amount_var = col_var("amount", False)
        self.sign_var = tk.StringVar(value=SIGN_CHOICES["all"])
        self.description_var = col_var("description", True)
        self.category_col_var = col_var("category", True)
        self.default_category_var = tk.StringVar(value="Other")
        self.currency_var = tk.StringVar(value=DEFAULT_CURRENCY)
        last = app.last_rate()
        self.rate_var = tk.StringVar(value="" if last is None else format_rate(last))
        self.payment_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.summary_var = tk.StringVar()

        def row(r: int, c: int, label: str, widget: tk.Widget) -> None:
            ttk.Label(form, text=label).grid(row=r, column=c * 2, sticky="w", padx=(0 if c == 0 else 20, 8), pady=3)
            widget.grid(row=r, column=c * 2 + 1, sticky="w", pady=3)

        combo = lambda var, values, w=22: ttk.Combobox(form, textvariable=var, values=values, width=w, state="readonly")
        row(0, 0, "Date column", combo(self.date_var, names))
        row(0, 1, "Date format", combo(self.date_format_var, list(DATE_FORMATS), 14))
        row(1, 0, "Amount column", combo(self.amount_var, names))
        row(1, 1, "Which rows", combo(self.sign_var, list(SIGN_CHOICES.values()), 30))
        row(2, 0, "Description column", combo(self.description_var, [NONE, *names]))
        row(2, 1, "Category column", combo(self.category_col_var, [NONE, *names]))
        row(3, 0, "Default category", Picker(form, app.icons, self.default_category_var, app.category_options, width=20))
        row(3, 1, "Payment method", Picker(form, app.icons, self.payment_var, app.payment_options, none_label="(none)", width=20))
        row(4, 0, "Currency", combo(self.currency_var, list(CURRENCIES), 7))
        row(4, 1, "Rate (S/ per US$1)", ttk.Entry(form, textvariable=self.rate_var, width=10))
        row(5, 0, "Tags for all rows", TagField(form, self.tags_var, app.recent_tags, width=20, icons=app.icons))

        ttk.Label(b, textvariable=self.summary_var, style="Bold.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.errors_label = ttk.Label(b, style="Warning.TLabel", wraplength=640, justify="left")
        self.errors_label.grid(row=4, column=0, sticky="w")

        for var in (self.date_var, self.date_format_var, self.amount_var, self.sign_var, self.description_var,
                    self.category_col_var, self.default_category_var, self.currency_var, self.rate_var):
            var.trace_add("write", lambda *_: self.update_summary())
        self.update_summary()
        self.show(preview, bind_return=False)

    def _col(self, var: tk.StringVar) -> int | None:
        value = var.get()
        return None if value == NONE else self.column_names.index(value)

    def _import_options(self) -> ImportOptions:
        if not self.rate_var.get().strip():
            raise ValueError(RATE_MISSING)
        sign = next(key for key, text in SIGN_CHOICES.items() if text == self.sign_var.get())
        return ImportOptions(
            date_col=self._col(self.date_var),
            amount_col=self._col(self.amount_var),
            description_col=self._col(self.description_var),
            category_col=self._col(self.category_col_var),
            date_format=DATE_FORMATS[self.date_format_var.get()],
            sign=sign,
            default_category=self.default_category_var.get() or "Other",
            currency=parse_currency(self.currency_var.get()),
            rate=parse_rate(self.rate_var.get()),
            payment_method=self.payment_var.get(),
            tags=parse_tags(self.tags_var.get()),
        )

    def _result(self):
        return build_expenses(self.data, self._import_options(), self.app.store.load(), self.app.categories)

    def update_summary(self) -> None:
        try:
            result = self._result()
        except ValueError as exc:
            self.summary_var.set(str(exc))
            self.errors_label.configure(text="")
            return
        parts = [f"Ready to import {len(result.expenses)} expenses"]
        if result.duplicates:
            parts.append(f"{result.duplicates} already in your data (skipped)")
        if result.skipped_by_sign:
            parts.append(f"{result.skipped_by_sign} skipped by 'Which rows'")
        if result.errors:
            parts.append(f"{len(result.errors)} rows couldn't be read")
        self.summary_var.set(" · ".join(parts))
        shown = result.errors[:4] + ([f"…and {len(result.errors) - 4} more"] if len(result.errors) > 4 else [])
        self.errors_label.configure(text="\n".join(shown))

    def on_ok(self) -> bool:
        try:
            result = self._result()
        except ValueError as exc:
            messagebox.showerror("Import", str(exc), parent=self)
            return False
        if not result.expenses:
            messagebox.showinfo("Import", "There is nothing to import with these settings.", parent=self)
            return False
        self.app.history.record(f"Import {len(result.expenses)} expenses",
                                lambda: self.app.store.add_many(result.expenses))
        self.app.imported(len(result.expenses), result.duplicates)
        return True
