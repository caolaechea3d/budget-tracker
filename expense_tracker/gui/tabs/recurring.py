"""Recurring tab: rent, subscriptions and bills that are added each month."""

from __future__ import annotations

from tkinter import messagebox, ttk

from ...storage import RecurringExpense, format_money
from ..forms import RecurringDialog
from .base import PageData, Tab


class RecurringTab(Tab):
    label = "Recurring"
    tab_icon = "🔁"
    tab_color = "#8d6cab"

    def build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="Rent, subscriptions, bills… added for you each month.",
                  style="Muted.TLabel").pack(side="left")
        for text, command in (("Check what's due", lambda: self.app.check_recurring(manual=True)),
                              ("Delete", self.delete_selected), ("Pause / resume", self.toggle_selected),
                              ("Edit…", self.edit_selected), ("New…", lambda: RecurringDialog(self.app))):
            ttk.Button(top, text=text, command=command).pack(side="right", padx=(6, 0))
        self.tree = ttk.Treeview(self, columns=("amount", "category", "day", "payment", "next", "status"),
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Recurring expense", anchor="w")
        self.tree.column("#0", width=220)
        for col, text, width, anchor in (("amount", "Amount", 110, "e"), ("category", "Category", 180, "w"),
                                         ("day", "Day", 60, "center"), ("payment", "Payment", 110, "w"),
                                         ("next", "Next", 100, "w"), ("status", "Status", 80, "w")):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=col == "category")
        self.tree.tag_configure("paused", foreground="#9ca3af")
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda _e: self.edit_selected())

    def redraw(self, data: PageData) -> None:
        tree = self.tree
        keep = tree.selection()
        tree.delete(*tree.get_children())
        for r in self.app.store.recurring():
            icon, color = self.app.look(r.category, r.subcategory)
            name = r.description or r.subcategory or r.category
            category = f"{r.category} › {r.subcategory}" if r.subcategory else r.category
            next_date = r.occurrence_date(r.next_month()).isoformat()
            tree.insert("", "end", iid=r.id, **self.app.icon_text(icon, color, name),
                        tags=() if r.active else ("paused",),
                        values=(format_money(r.amount, r.currency), category, r.day, r.payment_method, next_date,
                                "Active" if r.active else "Paused"))
        for iid in keep:
            if tree.exists(iid):
                tree.selection_set(iid)

    def _selected(self) -> RecurringExpense | None:
        selected = self.tree.selection()
        return next((r for r in self.app.store.recurring() if selected and r.id == selected[0]), None)

    def edit_selected(self) -> None:
        item = self._selected()
        if item:
            RecurringDialog(self.app, item)

    def toggle_selected(self) -> None:
        item = self._selected()
        if item:
            item.active = not item.active
            self.app.store.save_recurring(item)
            self.app.refresh()

    def delete_selected(self) -> None:
        item = self._selected()
        if item and messagebox.askyesno("Delete", "Delete this recurring expense?\n\n"
                                                  "Expenses already added from it are kept."):
            self.app.store.delete_recurring(item.id)
            self.app.refresh()
