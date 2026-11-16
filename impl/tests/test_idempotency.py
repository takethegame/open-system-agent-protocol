# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the idempotency index (standard.md §7.8)."""

import tempfile
import unittest
from pathlib import Path

from osap.idempotency import IdempotencyIndex
from osap.store import JsonStore


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.index = IdempotencyIndex()
        self.calls = 0

    def effect(self, result=None):
        self.calls += 1
        return result

    def test_first_call_executes(self):
        result, replayed = self.index.execute_once("msg_1", lambda: self.effect("ok"))
        self.assertEqual(result, "ok")
        self.assertFalse(replayed)
        self.assertEqual(self.calls, 1)

    def test_second_call_returns_the_cached_result(self):
        self.index.execute_once("msg_1", lambda: self.effect("ok"))
        result, replayed = self.index.execute_once("msg_1", lambda: self.effect("again"))
        self.assertEqual(result, "ok")
        self.assertTrue(replayed)
        self.assertEqual(self.calls, 1)

    def test_none_result_is_still_cached(self):
        self.index.execute_once("msg_1", self.effect)
        result, replayed = self.index.execute_once("msg_1", self.effect)
        self.assertIsNone(result)
        self.assertTrue(replayed)
        self.assertEqual(self.calls, 1)

    def test_distinct_ids_execute_separately(self):
        self.index.execute_once("msg_1", self.effect)
        self.index.execute_once("msg_2", self.effect)
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(self.index), 2)

    def test_lookup_is_none_for_an_unknown_id(self):
        self.assertIsNone(self.index.lookup("msg_missing"))

    def test_forget_forces_the_next_execution(self):
        self.index.execute_once("msg_1", self.effect)
        self.index.forget("msg_1")
        self.index.execute_once("msg_1", self.effect)
        self.assertEqual(self.calls, 2)

    def test_clear_forces_the_next_execution(self):
        self.index.execute_once("msg_1", self.effect)
        self.index.clear()
        self.index.execute_once("msg_1", self.effect)
        self.assertEqual(self.calls, 2)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.calls = 0

    def effect(self, result=None):
        self.calls += 1
        return result

    def test_duplicate_after_reopen_is_replayed(self):
        first = IdempotencyIndex(store=JsonStore(self.path))
        first.execute_once("msg_1", lambda: self.effect("ok"))

        second = IdempotencyIndex(store=JsonStore(self.path))
        result, replayed = second.execute_once("msg_1", lambda: self.effect("again"))
        self.assertEqual(result, "ok")
        self.assertTrue(replayed)
        self.assertEqual(self.calls, 1)

    def test_forget_is_persisted(self):
        first = IdempotencyIndex(store=JsonStore(self.path))
        first.execute_once("msg_1", self.effect)
        first.forget("msg_1")

        second = IdempotencyIndex(store=JsonStore(self.path))
        second.execute_once("msg_1", self.effect)
        self.assertEqual(self.calls, 2)

    def test_clear_is_persisted(self):
        first = IdempotencyIndex(store=JsonStore(self.path))
        first.execute_once("msg_1", self.effect)
        first.clear()

        second = IdempotencyIndex(store=JsonStore(self.path))
        self.assertEqual(len(second), 0)
        second.execute_once("msg_1", self.effect)
        self.assertEqual(self.calls, 2)

    def test_entries_are_loaded_from_the_store(self):
        JsonStore(self.path).put("idempotency", {"msg_1": {"status": "accepted"}})
        index = IdempotencyIndex(store=JsonStore(self.path))
        self.assertEqual(len(index), 1)
        self.assertEqual(index.lookup("msg_1"), {"status": "accepted"})

    def test_custom_section_is_used(self):
        store = JsonStore(self.path)
        index = IdempotencyIndex(store=store, section="other")
        index.remember("msg_1", "ok")
        self.assertEqual(store.get("other"), {"msg_1": "ok"})
        self.assertIsNone(store.get("idempotency"))

    def test_non_object_section_is_rejected(self):
        JsonStore(self.path).put("idempotency", [])
        with self.assertRaises(ValueError):
            IdempotencyIndex(store=JsonStore(self.path))


if __name__ == "__main__":
    unittest.main()
