# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the persistent JSON store (§7.8)."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from osap.store import JsonStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"

    def test_missing_file_reads_as_empty(self):
        store = JsonStore(self.path)
        self.assertEqual(store.sections(), [])
        self.assertIsNone(store.get("idempotency"))
        self.assertEqual(store.get("idempotency", {}), {})

    def test_sections_survive_reopen(self):
        JsonStore(self.path).put("idempotency", {"msg_1": {"ok": True}})
        reopened = JsonStore(self.path)
        self.assertEqual(reopened.get("idempotency"), {"msg_1": {"ok": True}})
        self.assertEqual(reopened.sections(), ["idempotency"])

    def test_get_returns_an_independent_copy(self):
        store = JsonStore(self.path)
        store.put("section", {"items": [1, 2]})
        snapshot = store.get("section")
        snapshot["items"].append(3)
        self.assertEqual(store.get("section"), {"items": [1, 2]})

    def test_delete_drops_one_section(self):
        store = JsonStore(self.path)
        store.put("a", 1)
        store.put("b", 2)
        store.delete("a")
        self.assertEqual(store.sections(), ["b"])
        self.assertIsNone(JsonStore(self.path).get("a"))
        store.delete("missing")

    def test_put_many_replaces_sections_in_one_flush(self):
        store = JsonStore(self.path)
        store.put("a", 1)
        store.put_many({"b": 2, "c": 3})
        self.assertEqual(store.get("a"), 1)
        self.assertEqual(store.get("b"), 2)
        self.assertEqual(store.get("c"), 3)
        reopened = JsonStore(self.path)
        self.assertEqual(reopened.sections(), ["a", "b", "c"])
        self.assertEqual(reopened.get("c"), 3)

    def test_put_many_with_no_sections_is_a_noop(self):
        store = JsonStore(self.path)
        store.put_many({})
        self.assertFalse(self.path.exists())

    def test_empty_file_reads_as_empty(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(JsonStore(self.path).sections(), [])

    def test_non_object_document_is_rejected(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            JsonStore(self.path)

    def test_file_is_not_group_or_world_readable(self):
        store = JsonStore(self.path)
        store.put("section", {})
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode & 0o077, 0)

    def test_failed_write_keeps_previous_state(self):
        store = JsonStore(self.path)
        store.put("section", {"ok": True})
        with self.assertRaises(TypeError):
            store.put("section", {"bad": object()})
        self.assertEqual(store.get("section"), {"ok": True})
        self.assertEqual(JsonStore(self.path).get("section"), {"ok": True})

    def test_file_contains_sorted_json(self):
        store = JsonStore(self.path)
        store.put("section", {"b": 2, "a": 1})
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), {"section": {"a": 1, "b": 2}})
        self.assertLess(text.index('"a"'), text.index('"b"'))

    def test_replacement_leaves_no_temporary_sibling(self):
        store = JsonStore(self.path)
        store.put("one", 1)
        store.put("two", 2)
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], ["state.json"])


if __name__ == "__main__":
    unittest.main()
