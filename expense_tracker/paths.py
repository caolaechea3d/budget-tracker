"""Where the app keeps its data, depending on how it's run.

- From source (python main.py): the project's data/ folder, as always.
- Packaged, portable (a `portable.txt` file next to the .exe): a data/ folder next to the .exe,
  so the whole app and its data travel together (e.g. on a USB stick).
- Packaged, installed: %APPDATA%\\Budget Tracker\\data, so the data survives updates and uninstalls.

The BUDGET_TRACKER_DATA environment variable overrides all of these.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER_NAME = "Budget Tracker"
PORTABLE_MARKER = "portable.txt"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True when running as a packaged .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_folder() -> Path:
    """The folder of the .exe when packaged, or the project folder when running from source."""
    return Path(sys.executable).resolve().parent if is_frozen() else PROJECT_ROOT


def is_portable() -> bool:
    return is_frozen() and (app_folder() / PORTABLE_MARKER).exists()


def data_dir() -> Path:
    override = os.environ.get("BUDGET_TRACKER_DATA")
    if override:
        return Path(override).expanduser()
    if not is_frozen():
        return PROJECT_ROOT / "data"
    if is_portable():
        return app_folder() / "data"
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / APP_FOLDER_NAME / "data"


def log_file() -> Path:
    return data_dir() / "logs" / "errors.log"
