"""Unexpected errors: save the details to a log file and tell the user where it is.

A packaged app has no console, so without this a tester would only see the app misbehave.
"""

from __future__ import annotations

import sys
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from .. import APP_NAME, __version__
from ..paths import log_file


def write_log(exc_type, exc, tb) -> Path | None:
    """Append the error with its traceback to the log. Returns the log path, or None if it can't be written."""
    path = log_file()
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} · {APP_NAME} {__version__} ===\n{details}")
    except OSError:
        return None
    return path


def report_error(exc_type, exc, tb) -> None:
    path = write_log(exc_type, exc, tb)
    where = f"\n\nThe details were saved to:\n{path}\nPlease send that file to whoever gave you the app." if path else ""
    try:
        messagebox.showerror(APP_NAME, f"Something went wrong:\n{exc_type.__name__}: {exc}{where}")
    except tk.TclError:
        pass  # no window to show it in; the log still has it


def install(root: tk.Tk) -> None:
    """Route errors in button clicks (Tk callbacks) and anywhere else to report_error."""
    root.report_callback_exception = report_error
    sys.excepthook = report_error
