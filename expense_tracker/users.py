"""Users: each one has a separate folder with its own expenses, receipts and backups.

Layout inside the data folder:
  users.json                    list of users + who was used last
  users/<id>/expenses.json      that user's data (expenses, income, budgets, …)
  users/<id>/receipts/          that user's receipts
  users/<id>/backups/           that user's automatic backups
  users/_deleted/               folders of deleted users (kept, never erased)
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .storage import DEFAULT_DATA_FILE, ExpenseStore, write_json_atomic

DEFAULT_DATA_DIR = DEFAULT_DATA_FILE.parent
DEFAULT_USER_NAME = "Default User"

# (type, icon, color) offered when creating a user.
USER_TYPES = [
    ("Personal", "👤", "#577590"),
    ("Work", "💼", "#2a9d8f"),
    ("Family", "🏡", "#f4a261"),
    ("Business", "🏢", "#8d6cab"),
    ("Savings", "🐷", "#e76f51"),
    ("Travel", "✈", "#277da1"),
    ("Other", "⭐", "#adb5bd"),
]


def type_look(user_type: str) -> tuple[str, str]:
    return next(((i, c) for t, i, c in USER_TYPES if t.lower() == user_type.lower()), ("⭐", "#adb5bd"))


@dataclass
class User:
    name: str
    type: str = "Personal"
    icon: str = "👤"
    color: str = "#577590"
    created: str = field(default_factory=lambda: date.today().isoformat())
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type, "icon": self.icon,
                "color": self.color, "created": self.created}

    @classmethod
    def from_dict(cls, d: dict) -> User:
        return cls(id=d["id"], name=d["name"], type=d.get("type") or "Personal", icon=d.get("icon") or "👤",
                   color=d.get("color") or "#577590", created=d.get("created") or date.today().isoformat())


class UserRegistry:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.path = self.data_dir / "users.json"

    # --- file ---

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, users: list[User], last_user: str | None) -> None:
        write_json_atomic(self.path, {"version": 1, "last_user": last_user, "users": [u.to_dict() for u in users]})

    def ensure_ready(self) -> None:
        """Create the Default User on first run, moving any existing single-user data into it."""
        if self.users():
            return
        user = User(DEFAULT_USER_NAME, "Personal", "👤", "#577590")
        folder = self.folder(user)
        folder.mkdir(parents=True, exist_ok=True)
        legacy = self.data_dir / "expenses.json"
        if legacy.exists():
            backups = folder / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, backups / "expenses-before-users.json")  # safety copy
            os.replace(legacy, folder / "expenses.json")
            for sub in ("receipts", "backups"):
                old = self.data_dir / sub
                if old.is_dir():
                    for item in old.iterdir():
                        target = folder / sub / item.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            shutil.move(str(item), str(target))
                    if not any(old.iterdir()):
                        old.rmdir()
        self._write([user], user.id)

    # --- users ---

    def users(self) -> list[User]:
        return [User.from_dict(u) for u in self._read().get("users", [])]

    def get(self, user_id: str) -> User | None:
        return next((u for u in self.users() if u.id == user_id), None)

    def find(self, name_or_id: str) -> User | None:
        key = name_or_id.strip().lower()
        return next((u for u in self.users() if u.id == key or u.name.lower() == key), None)

    def last_user(self) -> User | None:
        users = self.users()
        last = self._read().get("last_user")
        return next((u for u in users if u.id == last), users[0] if users else None)

    def set_last_user(self, user_id: str) -> None:
        self._write(self.users(), user_id)

    def _check_name(self, name: str, exclude_id: str | None = None) -> str:
        name = " ".join(name.split())
        if not name:
            raise ValueError("The user needs a name")
        if any(u.name.lower() == name.lower() and u.id != exclude_id for u in self.users()):
            raise ValueError(f"There is already a user called '{name}'")
        return name

    def create(self, name: str, user_type: str = "Personal", icon: str | None = None, color: str | None = None) -> User:
        default_icon, default_color = type_look(user_type)
        user = User(self._check_name(name), user_type, icon or default_icon, color or default_color)
        self.folder(user).mkdir(parents=True, exist_ok=True)
        self._write([*self.users(), user], self._read().get("last_user") or user.id)
        return user

    def update(self, user: User) -> None:
        user.name = self._check_name(user.name, exclude_id=user.id)
        users = [user if u.id == user.id else u for u in self.users()]
        self._write(users, self._read().get("last_user"))

    def delete(self, user_id: str) -> Path | None:
        """Remove a user from the list. Their folder is moved to users/_deleted/, not erased."""
        users = self.users()
        if len(users) <= 1:
            raise ValueError("You can't delete the only user")
        user = next((u for u in users if u.id == user_id), None)
        if user is None:
            return None
        remaining = [u for u in users if u.id != user_id]
        last = self._read().get("last_user")
        self._write(remaining, remaining[0].id if last == user_id else last)
        folder = self.folder(user)
        if folder.exists():
            target = self.data_dir / "users" / "_deleted" / f"{user.id}-{datetime.now():%Y%m%d-%H%M%S}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(target))
            return target
        return None

    # --- per-user data ---

    def folder(self, user: User) -> Path:
        return self.data_dir / "users" / user.id

    def store_for(self, user: User) -> ExpenseStore:
        return ExpenseStore(self.folder(user) / "expenses.json")
