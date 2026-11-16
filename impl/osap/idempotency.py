# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Idempotency index from standard.md §7.8.

A repeated `id` MUST return the cached result or `DUPLICATE`; it MUST NOT
execute side effects twice, including across a Bus restart. Without a `store`
this index is memory-only; passing a `JsonStore` persists every entry so a
restarted Bus replays instead of re-executing.

The persisted value is plain JSON, so a cached result must be JSON-serializable
when a store is configured. The whole section is rewritten on each change: the
reference implementation favours a simple, atomic file over incremental writes.
"""

from __future__ import annotations

from typing import Any, Callable

from .store import JsonStore

SECTION = "idempotency"


class IdempotencyIndex:
    """Cache of results keyed by message id."""

    def __init__(self, *, store: JsonStore | None = None, section: str = SECTION) -> None:
        self._store = store
        self._section = section
        if store is None:
            self._entries: dict[str, Any] = {}
        else:
            loaded = store.get(section)
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                raise ValueError(f"idempotency section {section!r} must be a JSON object")
            self._entries = loaded

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, message_id: str) -> Any | None:
        """Return the cached result, or None when the id is new."""

        return self._entries.get(message_id)

    def remember(self, message_id: str, result: Any) -> Any:
        self._entries[message_id] = result
        self._persist()
        return result

    def execute_once(self, message_id: str, action: Callable[[], Any]) -> tuple[Any, bool]:
        """Run `action` only for a new id; return `(result, replayed)`."""

        if message_id in self._entries:
            return self._entries[message_id], True
        return self.remember(message_id, action()), False

    def forget(self, message_id: str) -> None:
        if message_id in self._entries:
            del self._entries[message_id]
            self._persist()

    def clear(self) -> None:
        if not self._entries and self._store is None:
            return
        self._entries.clear()
        self._persist()

    def _persist(self) -> None:
        if self._store is not None:
            self._store.put(self._section, self._entries)
