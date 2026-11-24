# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the Bus core (standard.md §7.1, §7.7, §7.8)."""

import json
import tempfile
import unittest
from pathlib import Path

from osap import Bus, IdempotencyIndex, JsonStore, OsapError, capability, envelope, task
from osap.clock import Deadline
from osap.clock import parse_timestamp

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class HandshakeTests(unittest.TestCase):
    def test_request_before_hello_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            Bus().receive(load("request.json"))
        self.assertEqual(caught.exception.code, "TRANSPORT_HANDSHAKE_REQUIRED")

    def test_incompatible_version_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            Bus().handshake({"osap": "1.0"})
        self.assertEqual(caught.exception.code, "TRANSPORT_VERSION_UNSUPPORTED")

    def test_welcome_is_a_valid_envelope(self):
        bus = Bus()
        welcome = bus.handshake(load("hello.json"))
        envelope.validate(welcome)
        self.assertEqual(bus.state, "ready")
        self.assertEqual(welcome["body"]["data"]["binding"], "stream")

    def test_hello_completes_the_handshake(self):
        bus = Bus()
        welcome = bus.receive(load("hello.json"))
        self.assertEqual(welcome["type"], "welcome")
        self.assertEqual(bus.state, "ready")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.bus.handshake({"osap": "0.1"})

    def test_unknown_type_is_schema_unsupported(self):
        message = load("request.json")
        message["type"] = "bogus"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(message)
        self.assertEqual(caught.exception.code, "SCHEMA_UNSUPPORTED")

    def test_duplicate_id_runs_side_effects_once(self):
        message = load("request.json")
        first = self.bus.receive(message)
        second = self.bus.receive(message)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(self.bus.side_effects, 1)
        self.assertEqual(self.bus.replays, 1)

    def test_unrouted_type_raises_not_implemented(self):
        message = load("request.json")
        message["type"] = "discover"
        with self.assertRaises(NotImplementedError):
            self.bus.receive(message)

    def test_error_envelope_is_valid(self):
        message = load("request.json")
        reply = self.bus.error_envelope(message, OsapError("POLICY_DENIED", "denied"))
        envelope.validate(reply)
        self.assertEqual(reply["body"]["data"]["code"], "POLICY_DENIED")
        self.assertEqual(reply["causation_id"], message["id"])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"

    def test_duplicate_after_restart_is_replayed_without_side_effects(self):
        message = load("request.json")

        first = Bus(store=self.path)
        first.handshake({"osap": "0.1"})
        self.assertFalse(first.receive(message)["replayed"])
        self.assertEqual(first.side_effects, 1)

        second = Bus(store=self.path)
        second.handshake({"osap": "0.1"})
        reply = second.receive(message)
        self.assertTrue(reply["replayed"])
        self.assertEqual(second.side_effects, 0)
        self.assertEqual(second.replays, 1)

    def test_explicit_index_is_used(self):
        index = IdempotencyIndex()
        self.assertIs(Bus(idempotency=index).idempotency, index)

    def test_store_and_index_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            Bus(store=self.path, idempotency=IdempotencyIndex())

    def test_a_shared_store_carries_more_than_one_subsystem(self):
        store = JsonStore(self.path)
        bus = Bus(store=store)
        bus.handshake({"osap": "0.1"})
        bus.receive(load("request.json"))
        authority = capability.CapabilityAuthority(store=store)
        token = load("capability.json")
        authority.issue(token)
        self.assertEqual(
            JsonStore(self.path).sections(),
            ["capability.issued", "idempotency"],
        )


class ClockTests(unittest.TestCase):
    def test_wall_rollback_does_not_revive_a_deadline(self):
        now = [0.0]
        deadline = Deadline(15.0, monotonic=lambda: now[0])
        now[0] = 16.0
        with self.assertRaises(OsapError) as caught:
            deadline.check()
        self.assertEqual(caught.exception.code, "TIMEOUT")

    def test_deadline_from_envelope(self):
        message = load("request.json")
        deadline = Deadline.from_envelope(message)
        self.assertAlmostEqual(deadline.budget, 15.0)
        self.assertFalse(deadline.expired())

    def test_timestamp_requires_timezone_aware_input(self):
        self.assertEqual(parse_timestamp("2026-11-10T10:14:45Z").utcoffset().total_seconds(), 0)


class StatusRoutingTests(unittest.TestCase):
    """A `status` message updates the progress board one-way (§8.6)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"
        self.store = JsonStore(self.path)
        self.board = task.TaskBoard(store=self.store)
        record = self.board.add(task.Task.from_document(load("task.json")))
        self.board.transition(record, "accepted")
        self.board.transition(record, "running")
        self.bus = Bus(progress_board=self.board)
        self.bus.handshake({"osap": "0.1"})
        self.record = record

    def status(self) -> dict:
        return {
            "osap": "0.1",
            "id": "msg_status_1",
            "type": "status",
            "trace_id": "trace_status_01",
            "session_id": "session_01J9Z6Q3V8N2K4M7P1R5T0WX09",
            "from": self.record.assignee,
            "to": {"agent": self.record.owner},
            "task": {"id": self.record.task_id, "mode": "supervisor"},
            "body": {"schema": "osap.status/v1", "data": {"consumed": {"tool_calls": 1}}},
            "ts": "2026-11-10T10:14:45Z",
        }

    def test_status_updates_the_board_and_returns_nothing(self):
        self.assertIsNone(self.bus.receive(self.status()))
        self.assertEqual(self.board.require(self.record.task_id).consumed["tool_calls"], 1)

    def test_status_without_a_board_is_not_routed(self):
        bare = Bus()
        bare.handshake({"osap": "0.1"})
        with self.assertRaises(NotImplementedError):
            bare.receive(self.status())

    def test_a_non_assignee_status_is_denied(self):
        message = self.status()
        message["from"] = "agent://com.example.other/agent#1"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_consumption_must_be_monotonic(self):
        self.bus.receive(self.status())
        message = self.status()
        message["id"] = "msg_status_2"
        message["body"]["data"]["consumed"] = {"tool_calls": 0}
        with self.assertRaises(OsapError):
            self.bus.receive(message)

    def test_progress_survives_a_restart(self):
        self.bus.receive(self.status())
        reopened_board = task.TaskBoard(store=JsonStore(self.path))
        self.assertEqual(reopened_board.require(self.record.task_id).consumed["tool_calls"], 1)


if __name__ == "__main__":
    unittest.main()
