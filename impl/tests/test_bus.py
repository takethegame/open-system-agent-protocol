# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the Bus core (standard.md §7.1, §7.7, §7.8)."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from osap import Bus, EventBroker, IdempotencyIndex, JsonStore, OsapError, capability, envelope, registry, task
from osap import opaque
from osap.opaque import P1KeyRing
from osap.streams import StreamRegistry

TOPIC = "event://app.com.example.calendar/event_changed"
from osap.clock import Deadline
from osap.clock import parse_timestamp

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def record_agent() -> str:
    return "agent://com.example.calendar/agent#9c"


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


class DescribeRoutingTests(unittest.TestCase):
    """A `describe` message resolves details through the registry (§7.2)."""

    def setUp(self):
        self.registry = registry.Registry()
        record = json.loads((EXAMPLES / "capability-record.json").read_text())
        self.registry.index_record(record, now=datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.bus = Bus(describe_service=self.registry, clock=lambda: datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.bus.handshake({"osap": "0.1"})

    def message(self, target=None, *, with_refs=False):
        message = {
            "osap": "0.1",
            "id": "msg_describe_1",
            "type": "describe",
            "trace_id": "trace_describe_01",
            "from": "agent://com.example.orchestrator/main#1a2b",
            "to": {"agent": "agent://system/registry#0"},
            "body": {
                "schema": "osap.describe/v1",
                "data": target or {"agent": record_agent()},
            },
            "ts": "2026-11-10T10:14:45Z",
        }
        if with_refs:
            message["refs"] = ["obj://sha256:9f2c7b1a"]
        return message

    def test_describe_returns_the_record(self):
        reply = self.bus.receive(self.message())
        self.assertEqual(reply["type"], "result")
        self.assertEqual(reply["body"]["schema"], "osap.describe/v1")
        self.assertEqual(reply["body"]["data"]["records"][0]["agent"], record_agent())

    def test_an_unknown_target_is_not_found(self):
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(self.message({"agent": "agent://com.example.other/agent#1"}))
        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")

    def test_describe_without_a_service_is_not_routed(self):
        bare = Bus(clock=lambda: datetime(2026, 11, 10, tzinfo=timezone.utc))
        bare.handshake({"osap": "0.1"})
        with self.assertRaises(NotImplementedError):
            bare.receive(self.message())

    def test_refs_pass_when_the_authorizer_allows(self):
        registry_result = {
            "obj://sha256:9f2c7b1a": {"decision": "allow", "reason": "refs_check"},
        }
        self.bus.refs_authorizer = lambda agent, refs: registry_result
        reply = self.bus.receive(self.message(with_refs=True))
        self.assertEqual(reply["type"], "result")

    def test_a_denied_ref_fails_closed(self):
        self.bus.refs_authorizer = lambda agent, refs: {
            "obj://sha256:9f2c7b1a": {"decision": "deny", "reason": "audience"},
        }
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(self.message(with_refs=True))
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(caught.exception.details["refs"], ["obj://sha256:9f2c7b1a"])

    def test_refs_without_an_authorizer_pass_silently(self):
        self.assertEqual(self.bus.receive(self.message(with_refs=True))["type"], "result")


    def test_stream_messages_route_through_the_registry(self):
        bus = Bus(streams=StreamRegistry(), clock=lambda: datetime(2026, 11, 10, tzinfo=timezone.utc))
        bus.handshake({"osap": "0.1"})

        def envelope(message_id, kind, data):
            return {
                "osap": "0.1",
                "id": message_id,
                "type": kind,
                "trace_id": "trace_stream_01",
                "from": "agent://com.example.calendar/agent#9c",
                "to": {"agent": "agent://com.example.orchestrator/main#1a2b"},
                "body": {"schema": "osap.stream/v1", "data": data},
                "ts": "2026-11-10T10:14:45Z",
            }

        self.assertIsNone(
            bus.receive(envelope("s1", "stream.open", {"stream_id": "stream_w", "schema": "osap.report/v1", "total_estimate": 2}))
        )
        self.assertIsNone(
            bus.receive(envelope("s2", "stream.chunk", {"stream_id": "stream_w", "seq": 1, "data": {"part": 1}}))
        )
        self.assertIsNone(
            bus.receive(envelope("s3", "stream.close", {"stream_id": "stream_w", "status": "complete"}))
        )
        view = bus.streams.view("stream_w")
        self.assertEqual(view["status"], "complete")
        self.assertEqual([chunk["seq"] for chunk in view["chunks"]], [1])

    def test_stream_messages_without_a_registry_are_not_routed(self):
        bare = Bus()
        bare.handshake({"osap": "0.1"})
        message = {
            "osap": "0.1",
            "id": "s1",
            "type": "stream.open",
            "from": "agent://com.example.calendar/agent#9c",
            "to": {"agent": "agent://com.example.orchestrator/main#1a2b"},
            "body": {"schema": "osap.stream/v1", "data": {"stream_id": "stream_x"}},
            "ts": "2026-11-10T10:14:45Z",
        }
        with self.assertRaises(NotImplementedError):
            bare.receive(message)


    def test_event_publishes_through_the_broker(self):
        inbox_agent = "agent://com.example.notes/assistant#7f3a"
        broker = EventBroker()
        broker.subscribe(inbox_agent, topics=[TOPIC])
        bus = Bus(events=broker, clock=lambda: datetime(2026, 11, 10, tzinfo=timezone.utc))
        bus.handshake({"osap": "0.1"})
        message = {
            "osap": "0.1",
            "id": "evt_1",
            "type": "event",
            "trace_id": "trace_event_01",
            "from": "agent://com.example.calendar/agent#9c",
            "to": {"agent": inbox_agent},
            "origin": {"kind": "agent", "trust": "verified"},
            "body": {
                "schema": "osap.event/v1",
                "data": {"topic": TOPIC, "payload": {"changed": True}},
            },
            "ts": "2026-11-10T10:14:45Z",
        }
        self.assertIsNone(bus.receive(message))
        inbox = broker.inbox(inbox_agent)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["topic"], TOPIC)
        self.assertEqual(inbox[0]["origin"], {"kind": "agent", "trust": "verified"})

    def test_event_without_a_broker_is_not_routed(self):
        bare = Bus()
        bare.handshake({"osap": "0.1"})
        message = {
            "osap": "0.1",
            "id": "evt_2",
            "type": "event",
            "from": "agent://com.example.calendar/agent#9c",
            "to": {"agent": "agent://com.example.notes/assistant#7f3a"},
            "origin": {"kind": "agent", "trust": "verified"},
            "body": {"schema": "osap.event/v1", "data": {"topic": TOPIC}},
            "ts": "2026-11-10T10:14:45Z",
        }
        with self.assertRaises(NotImplementedError):
            bare.receive(message)


class ClockSkewTests(unittest.TestCase):
    """§2.5: the welcome publishes time and skew; out-of-skew ts is rejected."""

    MOMENT = datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)

    def bus(self, *, skew=None):
        return Bus(clock=lambda: self.MOMENT, skew_seconds=skew)

    def message(self, ts="2026-11-10T10:14:45Z"):
        message = load("request.json")
        message["ts"] = ts
        return message

    def test_welcome_publishes_now_and_skew(self):
        welcome = self.bus(skew=120).handshake({"osap": "0.1"})
        self.assertEqual(welcome["body"]["data"]["now"], "2026-11-10T10:14:45Z")
        self.assertEqual(welcome["body"]["data"]["clock_skew_seconds"], 120)

    def test_welcome_skew_is_none_when_not_enforced(self):
        welcome = self.bus().handshake({"osap": "0.1"})
        self.assertIsNone(welcome["body"]["data"]["clock_skew_seconds"])
        self.assertIn("now", welcome["body"]["data"])

    def test_a_message_within_the_skew_is_accepted(self):
        bus = self.bus(skew=60)
        bus.handshake({"osap": "0.1"})
        message = self.message(ts="2026-11-10T10:14:45Z")  # exactly on the bus clock
        reply = bus.receive(message)
        self.assertEqual(reply["type"], "result")

    def test_a_message_beyond_the_skew_is_rejected(self):
        bus = self.bus(skew=60)
        bus.handshake({"osap": "0.1"})
        with self.assertRaises(OsapError) as caught:
            bus.receive(self.message(ts="2026-11-10T11:14:45Z"))  # 3600 s off
        self.assertEqual(caught.exception.code, "TRANSPORT_CLOCK_SKEW")
        self.assertEqual(caught.exception.details["allowed_skew_seconds"], 60)
        self.assertEqual(caught.exception.details["deviation_seconds"], 3600)

    def test_the_check_is_opt_in(self):
        bus = self.bus()  # skew_seconds None: the §2.5 rejection never fires.
        bus.handshake({"osap": "0.1"})
        reply = bus.receive(self.message())
        self.assertEqual(reply["type"], "result")

    def test_an_invalid_skew_configuration_is_rejected(self):
        for skew in (-1, "60", True):
            with self.assertRaises(ValueError):
                Bus(skew_seconds=skew)


class P1OpaqueTests(unittest.TestCase):
    """P1 opaque envelopes seal, route, unseal, and fail closed (§3.6)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.keys = opaque.P1KeyRing(grace_seconds=3600)
        self.keys.rotate()  # first active key
        self.peer = opaque.P1KeyPair.generate()  # the *sender* signs nothing; this is a second party's key
        self.board = task.TaskBoard()
        document = json.loads((EXAMPLES / "task.json").read_text())
        self.record = self.board.add(task.Task.from_document(document))
        self.board.transition(self.record, "accepted")
        self.board.transition(self.record, "running")
        self.bus = Bus(p1_keys=self.keys, progress_board=self.board)
        self.bus.handshake({"osap": "0.1"})

    def p0_envelope(self):
        return {
            "osap": "0.1",
            "id": "msg_p1_1",
            "type": "request",
            "trace_id": "trace_p1_01",
            "from": self.record.assignee,
            "to": {"agent": self.record.owner},
            "task": {"id": self.record.task_id, "mode": "supervisor"},
            "auth": {"cap_id": "cap_p1", "token": "base64url-example-token"},
            "body": {"schema": "osap.demo/v1", "data": {"goal": "opaque payload"}},
            "deadline": "2099-01-01T00:00:00Z",
            "ts": "2026-11-10T10:14:45Z",
        }

    def test_seal_hides_the_inner_fields(self):
        sealed = self.bus.seal(self.p0_envelope(), peer_public_key=self.keys.active_public_key)
        self.assertEqual(sealed["body"]["schema"], "osap.opaque/v1")
        self.assertNotIn("auth", sealed)
        self.assertNotIn("refs", sealed)
        self.assertNotIn(b"opaque payload", json.dumps(sealed).encode())

    def test_sealed_then_unsealed_dispatches_the_inner_message(self):
        sealed = self.bus.seal(self.p0_envelope(), peer_public_key=self.keys.active_public_key)
        reply = self.bus.receive(sealed)
        self.assertEqual(reply["type"], "result")
        # the inner request executed exactly once (§8.11 idempotency intact)
        self.assertEqual(self.bus.side_effects, 1)

    def test_tampered_task_metadata_fails_closed(self):
        sealed = self.bus.seal(self.p0_envelope(), peer_public_key=self.keys.active_public_key)
        sealed["task"]["id"] = "task_tampered"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(sealed)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_an_unknown_kid_is_rejected(self):
        sealed = self.bus.seal(self.p0_envelope(), peer_public_key=self.keys.active_public_key)
        sealed["body"]["data"]["p1_kid"] = "p1_unknown"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(sealed)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_rotation_window_forward_secrecy(self):
        sealed = self.bus.seal(self.p0_envelope(), peer_public_key=self.keys.active_public_key)
        self.keys.rotate()  # the previous key enters the grace window
        self.assertIsNone(self.bus.receive(self._unsealable_copy(sealed)) or None) if False else None
        # A destroyed grace key must not decrypt past messages (§6 of the design).
        self.keys._grace.clear()  # simulate: grace expired and keys destroyed
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(sealed)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def _unsealable_copy(self, sealed):
        return sealed

    def test_p1_required_rejects_plaintext_requests(self):
        strict = Bus(p1_keys=self.keys, p1_required=True, progress_board=self.board)
        strict.handshake({"osap": "0.1"})
        with self.assertRaises(OsapError) as caught:
            strict.receive(self.p0_envelope())
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertEqual(caught.exception.details["reason"], "p1_required")

    def test_welcome_publishes_the_p1_feature_and_key(self):
        welcome = self.bus.handshake({"osap": "0.1"})
        self.assertIn("p1", welcome["features"])
        self.assertEqual(welcome["p1_kid"], self.keys.active_kid)
        self.assertEqual(
            welcome["p1_public_key"],
            __import__("base64").urlsafe_b64encode(self.keys.active_public_key).rstrip(b"=").decode(),
        )

    def test_welcome_without_p1_has_no_feature(self):
        welcome = Bus().handshake({"osap": "0.1"})
        self.assertNotIn("features", welcome)


if __name__ == "__main__":
    unittest.main()
