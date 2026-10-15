"""Reusable widgets: icon dropdowns, date field with calendar, modal dialog base, scrollable frame."""

from __future__ import annotations

import calendar
import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import simpledialog, ttk

from ..storage import parse_tags
from .icons import Icons

# (name, icon, color) for each choice in a Picker.
Option = tuple[str, str, str]

ACCENT = "#2a9d8f"
MAX_TAGS_IN_MENU = 20


class TagField(ttk.Frame):
    """A comma-separated tags entry with a 🏷 ▾ menu of existing tags to tick on/off.

    `get_tags` returns the known tags, most recently used first. Typing new tags still works.
    """

    def __init__(self, master: tk.Misc, variable: tk.StringVar, get_tags: Callable[[], list[str]],
                 width: int = 24, icons: Icons | None = None):
        super().__init__(master)
        self.variable = variable
        self.get_tags = get_tags
        self.entry = ttk.Entry(self, textvariable=variable, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        image = icons.get("🏷", "#8d99ae", badge=False) if icons else None
        # The menubutton draws its own ▾ arrow next to the tag icon.
        self.button = ttk.Menubutton(self, image=image or "", text="" if image else "🏷",
                                     compound="left", style="Picker.TMenubutton", takefocus=False)
        self.button.pack(side="left", padx=(2, 0))
        self.menu = tk.Menu(self.button, tearoff=False, postcommand=self._rebuild)
        self.button["menu"] = self.menu
        self._checks: list[tk.BooleanVar] = []  # keep the menu's check variables alive
        self.entry.bind("<Alt-Down>", lambda _e: self.open_menu())

    def current(self) -> list[str]:
        return parse_tags(self.variable.get())

    def _rebuild(self) -> None:
        self.menu.delete(0, "end")
        self._checks = []
        chosen = self.current()
        known = self.get_tags()[:MAX_TAGS_IN_MENU]
        # Tags typed here that aren't saved anywhere yet still show, so they can be unticked.
        tags = [*[t for t in chosen if t not in known], *known]
        if not tags:
            self.menu.add_command(label="No tags yet — type one, e.g. work", state="disabled")
            return
        self.menu.add_command(label="Recent tags", state="disabled")
        for tag in tags:
            var = tk.BooleanVar(value=tag in chosen)
            self._checks.append(var)
            self.menu.add_checkbutton(label=f"#{tag}", variable=var, command=lambda t=tag: self.toggle(t))
        if chosen:
            self.menu.add_separator()
            self.menu.add_command(label="Clear tags", command=lambda: self.variable.set(""))

    def toggle(self, tag: str) -> None:
        tags = self.current()
        if tag in tags:
            tags.remove(tag)
        else:
            tags.append(tag)
        self.variable.set(", ".join(tags))
        self.entry.focus_set()
        self.entry.icursor("end")

    def open_menu(self) -> str:
        self._rebuild()
        self.menu.tk_popup(self.entry.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height())
        return "break"


YEAR_SUFFIX = " · whole year"


def month_label(month: str) -> str:
    """'2026-09' -> 'September 2026'; a year '2026' -> '2026 · whole year'."""
    if len(month) == 4:
        return f"{int(month)}{YEAR_SUFFIX}"
    year, mon = map(int, month.split("-"))
    return f"{calendar.month_name[mon]} {year}"


class MonthChoices:
    """Keeps a combobox showing 'September 2026' while a variable holds '2026-09'.

    Keys can also be whole years ('2026', shown as '2026 · whole year').
    `special` maps extra display labels to themselves, e.g. {"All months": "All months"}.
    """

    def __init__(self, combobox: ttk.Combobox, key_var: tk.StringVar, special: dict[str, str] | None = None):
        self.combobox = combobox
        self.key_var = key_var
        self.special = special or {}
        self.label_var = tk.StringVar()
        combobox.configure(textvariable=self.label_var)
        combobox.bind("<<ComboboxSelected>>", lambda _e: self._chosen(), add="+")
        key_var.trace_add("write", lambda *_: self._show())
        self._show()

    def set_months(self, months: list[str]) -> None:
        """Offer these keys, in this order (months and/or years), after the special entries."""
        self.combobox["values"] = [*self.special, *(month_label(m) for m in months)]
        self._show()

    def _label(self, key: str) -> str:
        if key in self.special.values():
            return next(label for label, value in self.special.items() if value == key)
        try:
            return month_label(key)
        except (ValueError, IndexError):
            return key

    def _show(self) -> None:
        self.label_var.set(self._label(self.key_var.get()))

    def _chosen(self) -> None:
        label = self.label_var.get()
        if label in self.special:
            self.key_var.set(self.special[label])
            return
        if label.endswith(YEAR_SUFFIX):
            self.key_var.set(label[: -len(YEAR_SUFFIX)])
            return
        name, _, year = label.rpartition(" ")
        mon = list(calendar.month_name).index(name)
        self.key_var.set(f"{int(year):04d}-{mon:02d}")


class SortableColumns:
    """Click a Treeview heading to sort by it; click again to reverse. Shows ▲/▼ on the active column.

    `keys` maps each column ('#0' for the tree column) to a function giving the sort value of a record.
    A value of None is always placed last. Columns in `descending_first` start from the largest value.
    """

    def __init__(
        self,
        tree: ttk.Treeview,
        headings: dict[str, str],
        keys: dict[str, Callable],
        default: tuple[str, bool],
        on_change: Callable[[], None],
        descending_first: tuple[str, ...] = (),
    ):
        self.tree = tree
        self.headings = dict(headings)
        self.keys = keys
        self.column, self.reverse = default
        self.on_change = on_change
        self.descending_first = descending_first
        for col in headings:
            tree.heading(col, command=lambda c=col: self.toggle(c))
        self._paint()

    def toggle(self, column: str) -> None:
        if column == self.column:
            self.reverse = not self.reverse
        else:
            self.column, self.reverse = column, column in self.descending_first
        self._paint()
        self.on_change()

    def set_heading(self, column: str, text: str) -> None:
        self.headings[column] = text
        self._paint()

    def _paint(self) -> None:
        for col, text in self.headings.items():
            arrow = (" ▼" if self.reverse else " ▲") if col == self.column else ""
            self.tree.heading(col, text=text + arrow)

    def apply(self, records: list) -> list:
        key = self.keys[self.column]
        with_value = [(key(r), r) for r in records]
        present = [pair for pair in with_value if pair[0] is not None]
        missing = [r for value, r in with_value if value is None]
        present.sort(key=lambda pair: pair[0], reverse=self.reverse)
        return [r for _, r in present] + missing


def text_key(value: str) -> str | None:
    """Case-insensitive text sort key; empty text sorts last."""
    return value.strip().lower() or None


class CalendarPopup(tk.Toplevel):
    """A small month calendar under a widget; calls `on_pick(date)` when a day is clicked."""

    def __init__(self, anchor: tk.Widget, selected: date, on_pick: Callable[[date], None]):
        super().__init__(anchor)
        self.anchor = anchor
        self.selected = selected
        self.on_pick = on_pick
        self.shown = (selected.year, selected.month)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(anchor.winfo_toplevel())
        self.attributes("-topmost", True)  # always above the window (or dialog) it was opened from
        self.configure(bg="#d1d5db")  # 1px border around the white body
        self.body = tk.Frame(self, bg="white", padx=8, pady=8)
        self.body.pack(padx=1, pady=1)

        head = tk.Frame(self.body, bg="white")
        head.grid(row=0, column=0, columnspan=7, sticky="ew", pady=(0, 6))
        head.columnconfigure(1, weight=1)
        nav = dict(bg="white", relief="flat", bd=0, font=("Segoe UI", 11), cursor="hand2",
                   activebackground="#eef2f7", width=3)
        tk.Button(head, text="◀", command=lambda: self.move(-1), **nav).grid(row=0, column=0)
        self.title_label = tk.Label(head, bg="white", font=("Segoe UI", 10, "bold"))
        self.title_label.grid(row=0, column=1)
        tk.Button(head, text="▶", command=lambda: self.move(1), **nav).grid(row=0, column=2)

        for col, name in enumerate(calendar.day_abbr):
            tk.Label(self.body, text=name[:2], bg="white", fg="#6b7280", font=("Segoe UI", 8),
                     width=4).grid(row=1, column=col)
        self.cells: list[tk.Label] = []
        for i in range(42):
            cell = tk.Label(self.body, width=4, bg="white", font=("Segoe UI", 9), cursor="hand2", pady=3)
            cell.grid(row=2 + i // 7, column=i % 7, padx=1, pady=1)
            self.cells.append(cell)

        footer = tk.Frame(self.body, bg="white")
        footer.grid(row=8, column=0, columnspan=7, sticky="ew", pady=(6, 0))
        tk.Button(footer, text="Today", command=lambda: self.pick(date.today()), relief="flat",
                  bg="#eef2f7", activebackground="#e2e8f0", font=("Segoe UI", 9), cursor="hand2",
                  padx=10).pack(side="left")
        tk.Label(footer, text="Esc to close", bg="white", fg="#9ca3af", font=("Segoe UI", 8)).pack(side="right")

        self.draw()
        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        if y + self.winfo_reqheight() > anchor.winfo_screenheight():
            y = anchor.winfo_rooty() - self.winfo_reqheight() - 2  # not enough room below: open above
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<MouseWheel>", lambda e: self.move(-1 if e.delta > 0 else 1))
        self.bind("<Button-1>", self._click_outside)
        self.lift()
        self.focus_force()
        self.grab_set()

    def draw(self) -> None:
        year, month = self.shown
        self.title_label.configure(text=f"{calendar.month_name[month]} {year}")
        today = date.today()
        days = list(calendar.Calendar(firstweekday=0).itermonthdates(year, month))
        days += [date.fromordinal(days[-1].toordinal() + n) for n in range(1, 42 - len(days) + 1)]
        for cell, day in zip(self.cells, days):
            bg, fg, font = "white", "#111827", ("Segoe UI", 9)
            if day.month != month:
                fg = "#c0c4cc"
            if day == today:
                fg, font = ACCENT, ("Segoe UI", 9, "bold")
            if day == self.selected:
                bg, fg, font = ACCENT, "white", ("Segoe UI", 9, "bold")
            cell.configure(text=str(day.day), bg=bg, fg=fg, font=font)
            cell.bind("<Button-1>", lambda _e, d=day: self.pick(d))
            cell.bind("<Enter>", lambda _e, c=cell, d=day: c.configure(bg="#e6f4f1") if d != self.selected else None)
            cell.bind("<Leave>", lambda _e, c=cell, b=bg: c.configure(bg=b))

    def move(self, step: int) -> None:
        year, month = self.shown
        index = year * 12 + month - 1 + step
        self.shown = (index // 12, index % 12 + 1)
        self.draw()

    def pick(self, day: date) -> str:
        self.on_pick(day)
        self.close()
        return "break"  # don't let the click reach anything under the popup

    def _click_outside(self, event: tk.Event) -> None:
        inside = self.winfo_containing(event.x_root, event.y_root)
        if inside is None or not str(inside).startswith(str(self)):
            self.close()

    def close(self) -> None:
        anchor = self.anchor
        self.grab_release()
        self.destroy()
        regrab(anchor)  # if we were opened from a dialog, make it modal again


class DateField(ttk.Frame):
    """A date entry (YYYY-MM-DD) that opens a calendar when clicked. Typing still works."""

    def __init__(self, master: tk.Misc, variable: tk.StringVar, width: int = 11, icons: Icons | None = None):
        super().__init__(master)
        self.variable = variable
        self.entry = ttk.Entry(self, textvariable=variable, width=width, cursor="hand2")
        self.entry.pack(side="left", fill="x", expand=True)
        image = icons.get("📅", "#8d99ae", badge=False) if icons else None
        self.button = ttk.Button(self, image=image or "", text="" if image else "📅", width=0 if image else 3,
                                 command=self.open, style="Icon.TButton", takefocus=False)
        self.button.pack(side="left", padx=(2, 0))
        self.entry.bind("<Button-1>", lambda _e: self.after_idle(self.open))
        self.entry.bind("<Alt-Down>", lambda _e: self.open())
        self._popup: CalendarPopup | None = None
        self.enabled = True

    def set_enabled(self, enabled: bool) -> None:
        """Grey out the field (e.g. an optional deadline that's switched off)."""
        self.enabled = enabled
        state = ["!disabled"] if enabled else ["disabled"]
        self.entry.state(state)
        self.button.state(state)

    def open(self) -> None:
        if not self.enabled or (self._popup is not None and self._popup.winfo_exists()):
            return
        try:
            current = date.fromisoformat(self.variable.get().strip())
        except ValueError:
            current = date.today()
        self._popup = CalendarPopup(self, current, self._picked)

    def _picked(self, day: date) -> None:
        self.variable.set(day.isoformat())
        self.entry.focus_set()
        self.entry.icursor("end")


class Picker(ttk.Menubutton):
    """A dropdown whose entries show an icon next to the name.

    `get_options` is called each time the menu opens, so it always shows the current catalog.
    """

    def __init__(
        self,
        master: tk.Misc,
        icons: Icons,
        variable: tk.StringVar,
        get_options: Callable[[], list[Option]],
        none_label: str | None = None,
        on_new: Callable[[str], None] | None = None,
        new_label: str = "New…",
        on_change: Callable[[], None] | None = None,
        width: int = 16,
    ):
        super().__init__(master, width=width, style="Picker.TMenubutton")
        self.icons = icons
        self.variable = variable
        self.get_options = get_options
        self.none_label = none_label
        self.on_new = on_new
        self.new_label = new_label
        self.on_change = on_change
        self.menu = tk.Menu(self, tearoff=False, postcommand=self._rebuild)
        self["menu"] = self.menu
        variable.trace_add("write", lambda *_: self.update_display())
        self.update_display()

    def _choose(self, name: str) -> None:
        self.variable.set(name)
        if self.on_change:
            self.on_change()

    def _rebuild(self) -> None:
        self.menu.delete(0, "end")
        if self.none_label is not None:
            self.menu.add_command(label=self.none_label, command=lambda: self._choose(""))
            self.menu.add_separator()
        for name, icon, color in self.get_options():
            image = self.icons.get(icon, color)
            self.menu.add_command(
                label=self.icons.text(icon, name) if image is None else f" {name}",
                image=image or "", compound="left",
                command=lambda n=name: self._choose(n),
            )
        if self.on_new:
            self.menu.add_separator()
            self.menu.add_command(label=f"➕ {self.new_label}", command=self._new)

    def _new(self) -> None:
        name = simpledialog.askstring(self.new_label.rstrip("…"), "Name:", parent=self.winfo_toplevel())
        regrab(self)
        if name and name.strip():
            name = " ".join(name.split())
            self.on_new(name)
            self._choose(name)

    def update_display(self) -> None:
        name = self.variable.get()
        option = next((o for o in self.get_options() if o[0].lower() == name.lower()), None) if name else None
        if not name:
            self.configure(text=self.none_label or "", image="")
            return
        icon, color = (option[1], option[2]) if option else ("🏷", "#8d99ae")
        image = self.icons.get(icon, color)
        self.configure(text=f" {name}" if image else self.icons.text(icon, name), image=image or "", compound="left")


class Dialog(tk.Toplevel):
    """Modal dialog: subclasses fill `self.body` and implement `on_ok` (return True to close)."""

    def __init__(self, parent: tk.Misc, title: str, ok_text: str = "Save", cancel_text: str = "Cancel"):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        outer = ttk.Frame(self, padding=14)
        outer.grid(sticky="nsew")
        self.body = ttk.Frame(outer)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.buttons = ttk.Frame(outer)
        self.buttons.grid(row=1, column=0, sticky="e", pady=(12, 0))
        if cancel_text:
            ttk.Button(self.buttons, text=cancel_text, command=self.destroy).pack(side="right")
        if ok_text:
            ttk.Button(self.buttons, text=ok_text, command=self._ok, style="Accent.TButton").pack(
                side="right", padx=(0, 6)
            )
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._parent_dialog = parent.winfo_toplevel() if isinstance(parent.winfo_toplevel(), Dialog) else None

    def destroy(self) -> None:
        parent = self._parent_dialog
        super().destroy()
        if parent is not None and parent.winfo_exists():
            parent.grab_set()  # a nested dialog closed: make the one below modal again

    def show(self, focus: tk.Widget | None = None, bind_return: bool = True) -> None:
        """Center over the parent window, make modal, and focus a widget."""
        if bind_return:
            self.bind("<Return>", lambda _e: self._ok())
        self.update_idletasks()
        top = self.master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        if focus is not None:
            focus.focus_set()
            if isinstance(focus, ttk.Entry):
                focus.select_range(0, "end")

    def _ok(self) -> None:
        if self.on_ok():
            self.destroy()

    def on_ok(self) -> bool:
        return True


class ScrollableFrame(ttk.Frame):
    """A frame with a vertical scrollbar; put children in `.inner`."""

    def __init__(self, master: tk.Misc, **kwargs):
        super().__init__(master, **kwargs)
        style = ttk.Style(self)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=style.lookup("TFrame", "background"))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


def setup_style(widget: tk.Misc, icons: Icons) -> None:
    """Named ttk styles shared by every screen."""
    style = ttk.Style(widget)
    style.configure("Treeview", rowheight=icons.size + round(8 * icons.scale))
    style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
    style.configure("Picker.TMenubutton", anchor="w", padding=(4, 1))
    style.configure("Muted.TLabel", foreground="#6b7280")
    style.configure("Warning.TLabel", foreground="#b35c00")
    style.configure("Over.TLabel", foreground="#c0392b", font=("Segoe UI", 9, "bold"))
    style.configure("Bold.TLabel", font=("Segoe UI", 10, "bold"))
    style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
    style.configure("CardTitle.TLabel", foreground="#6b7280", font=("Segoe UI", 9))
    style.configure("CardValue.TLabel", font=("Segoe UI", 14, "bold"))
    style.configure("Income.CardValue.TLabel", foreground="#2f855a", font=("Segoe UI", 14, "bold"))
    style.configure("Expense.CardValue.TLabel", foreground="#c0392b", font=("Segoe UI", 14, "bold"))
    style.configure("UserName.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Link.TButton", padding=(6, 0))
    style.configure("Icon.TButton", padding=2)
    style.configure("TNotebook.Tab", padding=(12, 4))


def regrab(widget: tk.Misc) -> None:
    """After a standard pop-up (askstring, colorchooser…) closes, make our dialog modal again."""
    top = widget.winfo_toplevel()
    if isinstance(top, Dialog) and top.winfo_exists():
        top.grab_set()


def labeled(parent: tk.Misc, row: int, text: str, widget: tk.Widget, sticky: str = "w", pady: int = 3) -> tk.Widget:
    """Grid a label + widget pair in a 2-column form."""
    ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=pady)
    widget.grid(row=row, column=1, sticky=sticky, pady=pady)
    return widget
