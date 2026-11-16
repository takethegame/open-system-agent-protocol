# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""A small JSON document store for state that must survive a restart.

The reference implementation is single-process; this is not a multi-writer
database. Each section is replaced with an atomic `os.replace` so a crash
cannot leave a half-written JSON file, and the file (and its temporary
sibling) is created with mode 0600.

Open one store per path per process and share the instance: two live stores
over the same file each flush their own snapshot, so the later write drops the
other's sections. Values are stored as plain JSON. When a write cannot be
serialized the store keeps its previous contents instead of leaving a value
that no later flush can write out.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class JsonStore:
    """A JSON object of named sections with atomic whole-file replacement."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        if not text.strip():
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} must contain a JSON object")
        return data

    def get(self, section: str, default=None):
        """Return a copy of one section, or `default` when it is absent."""

        with self._lock:
            if section not in self._data:
                return default
            return json.loads(json.dumps(self._data[section], ensure_ascii=False))

    def put(self, section: str, value) -> None:
        """Replace one section and flush the whole document atomically."""

        with self._lock:
            self._commit({section: value})

    def put_many(self, sections: dict) -> None:
        """Replace several sections in one atomic flush."""

        with self._lock:
            updates = dict(sections)
            if not updates:
                return
            self._commit(updates)

    def _commit(self, updates: dict) -> None:
        candidate = dict(self._data)
        candidate.update(updates)
        self._flush(candidate)
        self._data = candidate

    def delete(self, section: str) -> None:
        """Drop one section; a missing section is a no-op."""

        with self._lock:
            if section not in self._data:
                return
            candidate = dict(self._data)
            del candidate[section]
            self._flush(candidate)
            self._data = candidate

    def sections(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    def _flush(self, data: dict) -> None:
        """Serialize `data` and replace the file; never mutates `self._data`."""

        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        self._fsync_parent()

    def _fsync_parent(self) -> None:
        try:
            descriptor = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
