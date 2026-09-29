"""Dialogs for managing categories/subcategories, payment methods and income sources."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import colorchooser, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING

from ..catalog import ICON_CHOICES, Category, Item, find_category, find_item
from .widgets import Dialog, regrab

if TYPE_CHECKING:
    from .app import ExpenseApp


class IconChooser(Dialog):
    """Pick an emoji (and optionally a color). Result in `.result` as (icon, color) or None."""

    def __init__(self, app: ExpenseApp, icon: str, color: str | None, parent: tk.Misc | None = None):
        self.app = app
        self.result: tuple[str, str | None] | None = None
        self.icon_var = tk.StringVar(value=icon)
        self.color = color
        super().__init__(parent or app, "Choose icon", ok_text="Use this icon")
        b = self.body
        grid = ttk.Frame(b)
        grid.grid(row=0, column=0, columnspan=3, sticky="w")
        size = round(app.icons.size * 1.4)
        per_row = 12
        for i, emoji in enumerate(ICON_CHOICES):
            image = app.icons.get(emoji, color or "#8d99ae", size=size)
            ttk.Button(
                grid, image=image or "", text="" if image else emoji, width=0 if image else 3,
                command=lambda e=emoji: self.icon_var.set(e), style="Icon.TButton",
            ).grid(row=i // per_row, column=i % per_row, padx=1, pady=1)

        ttk.Label(b, text="Or type/paste any emoji:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        entry = ttk.Entry(b, textvariable=self.icon_var, width=6, font=("Segoe UI Emoji", 12))
        entry.grid(row=1, column=1, sticky="w", pady=(10, 0), padx=(6, 0))
        self.preview = ttk.Label(b)
        self.preview.grid(row=1, column=2, sticky="w", pady=(10, 0), padx=(10, 0))
        if color is not None:
            ttk.Button(b, text="Change color…", command=self._pick_color).grid(
                row=2, column=0, sticky="w", pady=(8, 0))
        self.icon_var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()
        self.show(entry, bind_return=True)

    def _pick_color(self) -> None:
        _, hex_color = colorchooser.askcolor(color=self.color, parent=self, title="Category color")
        regrab(self)
        if hex_color:
            self.color = hex_color
            self._update_preview()

    def _update_preview(self) -> None:
        icon = self.icon_var.get().strip()
        image = self.app.icons.get(icon, self.color or "#8d99ae", size=round(self.app.icons.size * 2)) if icon else None
        self.preview.configure(image=image or "", text="" if image else icon, font=("Segoe UI Emoji", 20))

    def on_ok(self) -> bool:
        icon = self.icon_var.get().strip()
        if not icon:
            messagebox.showerror("Icon", "Choose an icon.", parent=self)
            return False
        self.result = (icon, self.color)
        return True


def ask_icon(
    app: ExpenseApp, icon: str, color: str | None = None, parent: tk.Misc | None = None
) -> tuple[str, str | None] | None:
    dialog = IconChooser(app, icon, color, parent)
    app.wait_window(dialog)
    return dialog.result


def ask_name(parent: tk.Misc, title: str, initial: str = "") -> str | None:
    name = simpledialog.askstring(title, "Name:", initialvalue=initial, parent=parent)
    regrab(parent)
    return " ".join(name.split()) if name and name.strip() else None


class CategoriesDialog(Dialog):
    """Add, rename, re-icon, reorder and remove categories and subcategories."""

    def __init__(self, app: ExpenseApp):
        self.app = app
        super().__init__(app, "Categories & icons", ok_text="", cancel_text="Close")
        self.resizable(True, True)
        b = self.body
        b.columnconfigure(0, weight=1)
        b.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(b, show="tree", height=16, selectmode="browse")
        self.tree.column("#0", width=300)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(b, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        side = ttk.Frame(b)
        side.grid(row=0, column=2, sticky="n", padx=(10, 0))
        for text, command in (
            ("Add category…", self.add_category),
            ("Add subcategory…", self.add_subcategory),
            ("Rename…", self.rename),
            ("Icon / color…", self.change_icon),
            ("Move up", lambda: self.move(-1)),
            ("Move down", lambda: self.move(1)),
            ("Delete", self.delete),
        ):
            ttk.Button(side, text=text, command=command, width=18).pack(fill="x", pady=2)
        ttk.Label(b, text="Renaming also updates your existing expenses. Deleting only removes the choice\n"
                          "from the lists; expenses that use it keep their category.",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.tree.bind("<Double-1>", lambda _e: self.change_icon())
        self.reload()
        self.show(self.tree, bind_return=False)

    @property
    def categories(self) -> list[Category]:
        return self.app.categories

    def reload(self, select: str | None = None) -> None:
        open_items = {self.tree.item(i, "text").strip() for i in self.tree.get_children() if self.tree.item(i, "open")}
        self.tree.delete(*self.tree.get_children())
        icons = self.app.icons
        for ci, cat in enumerate(self.categories):
            cid = f"c{ci}"
            image = icons.get(cat.icon, cat.color)
            self.tree.insert("", "end", iid=cid, text=f" {cat.name}" if image else icons.text(cat.icon, cat.name),
                             image=image or "", open=cat.name in open_items)
            for si, sub in enumerate(cat.subcategories):
                simage = icons.get(sub.icon, cat.color)
                self.tree.insert(cid, "end", iid=f"c{ci}s{si}", text=f" {sub.name}" if simage else icons.text(sub.icon, sub.name),
                                 image=simage or "")
        if select and self.tree.exists(select):
            parent = self.tree.parent(select)
            if parent:
                self.tree.item(parent, open=True)
            self.tree.selection_set(select)
            self.tree.see(select)

    def _selected(self) -> tuple[int | None, int | None]:
        sel = self.tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        if "s" in iid:
            c, s = iid[1:].split("s")
            return int(c), int(s)
        return int(iid[1:]), None

    def _save(self, select: str | None = None) -> None:
        self.app.store.save_categories(self.categories)
        self.app.catalog_changed()
        self.reload(select)

    def add_category(self) -> None:
        name = ask_name(self, "New category")
        if not name:
            return
        if find_category(self.categories, name):
            messagebox.showinfo("Categories", f"'{name}' already exists.", parent=self)
            return
        self.categories.append(Category(name, color=self.app.next_color()))
        self._save(f"c{len(self.categories) - 1}")

    def add_subcategory(self) -> None:
        c, _ = self._selected()
        if c is None:
            messagebox.showinfo("Categories", "Select the category to add a subcategory to.", parent=self)
            return
        cat = self.categories[c]
        name = ask_name(self, f"New subcategory of {cat.name}")
        if not name:
            return
        if cat.subcategory(name):
            messagebox.showinfo("Categories", f"'{name}' already exists in {cat.name}.", parent=self)
            return
        cat.subcategories.append(Item(name, cat.icon))
        self._save(f"c{c}s{len(cat.subcategories) - 1}")

    def rename(self) -> None:
        c, s = self._selected()
        if c is None:
            return
        cat = self.categories[c]
        old = cat.name if s is None else cat.subcategories[s].name
        new = ask_name(self, "Rename", old)
        if not new or new == old:
            return
        if s is None:
            if find_category(self.categories, new) and new.lower() != old.lower():
                messagebox.showinfo("Categories", f"'{new}' already exists.", parent=self)
                return
            changed = self.app.store.rename_category(old, new)
        else:
            changed = self.app.store.rename_subcategory(cat.name, old, new)
        self.app.catalog_changed()
        self.reload(f"c{c}" if s is None else f"c{c}s{s}")
        self.app.set_status(f"Renamed '{old}' to '{new}' ({changed} expenses updated).")

    def change_icon(self) -> None:
        c, s = self._selected()
        if c is None:
            return
        cat = self.categories[c]
        if s is None:
            result = ask_icon(self.app, cat.icon, cat.color, parent=self)
            if result:
                cat.icon, cat.color = result[0], result[1] or cat.color
        else:
            result = ask_icon(self.app, cat.subcategories[s].icon, None, parent=self)
            if result:
                cat.subcategories[s].icon = result[0]
        if result:
            self._save(f"c{c}" if s is None else f"c{c}s{s}")

    def move(self, step: int) -> None:
        c, s = self._selected()
        if c is None:
            return
        items = self.categories if s is None else self.categories[c].subcategories
        i = c if s is None else s
        j = i + step
        if not 0 <= j < len(items):
            return
        items[i], items[j] = items[j], items[i]
        self._save(f"c{j}" if s is None else f"c{c}s{j}")

    def delete(self) -> None:
        c, s = self._selected()
        if c is None:
            return
        cat = self.categories[c]
        name = cat.name if s is None else f"{cat.name} › {cat.subcategories[s].name}"
        if not messagebox.askyesno("Delete", f"Remove '{name}' from the lists?\n\n"
                                   "Existing expenses keep it.", parent=self):
            return
        if s is None:
            del self.categories[c]
        else:
            del cat.subcategories[s]
        self._save()


class ItemsDialog(Dialog):
    """Manage a simple list of named items with icons (payment methods, income sources)."""

    def __init__(
        self,
        app: ExpenseApp,
        title: str,
        items: list[Item],
        save: Callable[[list[Item]], None],
        rename: Callable[[str, str], int],
    ):
        self.app = app
        self.items = items
        self.save_items = save
        self.rename_items = rename
        super().__init__(app, title, ok_text="", cancel_text="Close")
        b = self.body
        self.tree = ttk.Treeview(b, show="tree", height=10, selectmode="browse")
        self.tree.column("#0", width=240)
        self.tree.grid(row=0, column=0, sticky="nsew")
        side = ttk.Frame(b)
        side.grid(row=0, column=1, sticky="n", padx=(10, 0))
        for text, command in (
            ("Add…", self.add), ("Rename…", self.rename), ("Icon…", self.change_icon),
            ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1)), ("Delete", self.delete),
        ):
            ttk.Button(side, text=text, command=command, width=14).pack(fill="x", pady=2)
        self.tree.bind("<Double-1>", lambda _e: self.change_icon())
        self.reload()
        self.show(self.tree, bind_return=False)

    def reload(self, select: int | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.items):
            image = self.app.icons.get(item.icon, "#8d99ae")
            self.tree.insert("", "end", iid=str(i), text=f" {item.name}" if image else self.app.icons.text(item.icon, item.name),
                             image=image or "")
        if select is not None and self.tree.exists(str(select)):
            self.tree.selection_set(str(select))

    def _index(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _save(self, select: int | None = None) -> None:
        self.save_items(self.items)
        self.app.catalog_changed()
        self.reload(select)

    def add(self) -> None:
        name = ask_name(self, "Add")
        if name and not find_item(self.items, name):
            self.items.append(Item(name, "🏷"))
            self._save(len(self.items) - 1)

    def rename(self) -> None:
        i = self._index()
        if i is None:
            return
        old = self.items[i].name
        new = ask_name(self, "Rename", old)
        if new and new != old:
            self.items[i].name = new
            self.save_items(self.items)
            changed = self.rename_items(old, new)
            self.app.catalog_changed()
            self.reload(i)
            self.app.set_status(f"Renamed '{old}' to '{new}' ({changed} records updated).")

    def change_icon(self) -> None:
        i = self._index()
        if i is None:
            return
        result = ask_icon(self.app, self.items[i].icon, None, parent=self)
        if result:
            self.items[i].icon = result[0]
            self._save(i)

    def move(self, step: int) -> None:
        i = self._index()
        if i is None or not 0 <= i + step < len(self.items):
            return
        self.items[i], self.items[i + step] = self.items[i + step], self.items[i]
        self._save(i + step)

    def delete(self) -> None:
        i = self._index()
        if i is not None and messagebox.askyesno("Delete", f"Remove '{self.items[i].name}' from the list?", parent=self):
            del self.items[i]
            self._save()
