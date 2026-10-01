"""Undo / redo for changes to a user's data.

Before an undoable change, the whole data document is kept in memory; undo writes it back.
Each step also remembers a fingerprint of the data right after the change. If the data no
longer matches it (something that isn't undoable changed it in between, like a budget), the
step can't be undone safely, so the history is cleared instead of overwriting that change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from .storage import ExpenseStore

T = TypeVar("T")
HISTORY_LIMIT = 30


def fingerprint(doc: dict) -> str:
    return hashlib.sha1(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class Step:
    label: str  # e.g. "Delete 2 expenses"
    restore: dict  # the document to write back
    expected: str  # fingerprint the data must have for this step to apply


class UndoHistory:
    def __init__(self, store: ExpenseStore, limit: int = HISTORY_LIMIT):
        self.store = store
        self.limit = limit
        self.undo_steps: list[Step] = []
        self.redo_steps: list[Step] = []

    def record(self, label: str, change: Callable[[], T]) -> T:
        """Run `change` (which writes to the store) and remember how to undo it.

        If `change` raises, nothing is recorded and the error is passed on.
        """
        before = self.store.snapshot()
        result = change()
        after = self.store.snapshot()
        if fingerprint(after) != fingerprint(before):
            self.undo_steps.append(Step(label, before, fingerprint(after)))
            del self.undo_steps[:-self.limit]
            self.redo_steps.clear()
        return result

    def next_undo(self) -> str | None:
        """Label of the step Undo would revert, or None if there's nothing (valid) to undo."""
        return self._valid(self.undo_steps)

    def next_redo(self) -> str | None:
        return self._valid(self.redo_steps)

    def undo(self) -> str:
        return self._move(self.undo_steps, self.redo_steps)

    def redo(self) -> str:
        return self._move(self.redo_steps, self.undo_steps)

    def clear(self) -> None:
        self.undo_steps.clear()
        self.redo_steps.clear()

    def _valid(self, steps: list[Step]) -> str | None:
        if steps and steps[-1].expected == fingerprint(self.store.snapshot()):
            return steps[-1].label
        return None

    def _move(self, source: list[Step], target: list[Step]) -> str:
        if not source:
            raise ValueError("Nothing to undo")
        current = self.store.snapshot()
        step = source[-1]
        if step.expected != fingerprint(current):
            self.clear()
            raise ValueError("Can't undo: the data was changed in a way that can't be undone "
                             "(for example a budget or category change) after that step.")
        source.pop()
        self.store.restore(step.restore)
        target.append(Step(step.label, current, fingerprint(self.store.snapshot())))
        return step.label
