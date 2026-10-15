"""Regenerate the README screenshots (docs/screenshots/*.png) from made-up demo data.

    python tools/screenshots.py

Opens the app on a temporary demo folder (see demo_data.py), captures the start screen and
the main tabs, and closes. Windows only. Don't touch the mouse/keyboard while it runs.
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_data import create_demo  # noqa: E402
from PIL import ImageGrab  # noqa: E402

from expense_tracker import APP_NAME, __version__  # noqa: E402
from expense_tracker.gui.icons import enable_dpi_awareness  # noqa: E402
from expense_tracker.gui.start import Shell  # noqa: E402
from expense_tracker.users import UserRegistry  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def main() -> None:
    enable_dpi_awareness()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        create_demo(Path(tmp) / "data")
        registry = UserRegistry(Path(tmp) / "data")
        root = tk.Tk()
        root.geometry("1280x800+40+40")
        root.attributes("-topmost", True)
        shell = Shell(root, registry)

        def pump(times: int = 12) -> None:
            for _ in range(times):
                root.update()
                root.after(50)

        def snap(name: str) -> None:
            pump()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            image = ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), all_screens=True)
            image.save(OUT / name, optimize=True)
            print(f"  {OUT / name}")

        # Start screen, without the (machine-specific) data folder path
        pump(20)
        for widget in shell.current.winfo_children():
            if isinstance(widget, ttk.Label) and "Data folder" in str(widget.cget("text")):
                widget.configure(text=f"{APP_NAME} {__version__}")
        snap("start.png")

        shell.open_user(registry.last_user())
        app = shell.current
        pump(30)  # let the debt reminder appear in the status bar
        if "Data file" in app.status_var.get():
            app.status_var.set("")
        ex = app.expenses_tab
        for iid in ex.summary.get_children():
            if "Groceries" in ex.summary.item(iid, "text"):
                ex.summary.item(iid, open=True)
        snap("expenses.png")
        for tab, name in ((app.debts_tab, "debts.png"), (app.charts_tab, "charts.png"),
                          (app.budgets_tab, "budgets.png")):
            app.notebook.select(tab)
            snap(name)
        root.destroy()


if __name__ == "__main__":
    print("Taking screenshots…")
    main()
