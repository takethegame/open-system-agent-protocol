# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Admission control and backpressure tests (standard.md §7.11, §11.7)."""

import copy
import json
import threading
import time
import unittest
from pathlib import Path

from osap import (
    AdmissionController,
    Bus,
    OsapError,
    Quota,
    envelope,
    sender_identity,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def message(name: str) -> dict:
    value = copy.deepcopy(load(name))
    value["deadline"] = "2099-01-01T00:00:00Z"
    value["ts"] = "2026-11-15T00:00:00Z"
    return value


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition was not reached before the timeout")


class QuotaTests(unittest.TestCase):
    def test_negative_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            Quota(max_in_flight=-1)
        with self.assertRaises(ValueError):
            Quota(rate=-1)

    def test_window_must_be_positive_and_finite(self):
        with self.assertRaises(ValueError):
            Quota(window=0)
        with self.assertRaises(ValueError):
            Quota(window=float("inf"))

    def test_bool_is_not_an_integer_limit(self):
        with self.assertRaises(ValueError):
            Quota(max_queued=True)


class RateLimitTests(unittest.TestCase):
    def controller(self, **quota) -> AdmissionController:
        self.clock = Clock()
        return AdmissionController(Quota(**quota), clock=self.clock)

    def test_a_burst_is_allowed_then_rejected_with_retry_after(self):
        controller = self.controller(rate=2, window=1.0)
        for _ in range(2):
            with controller.admit("agent://a"):
                pass
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a")
        error = caught.exception
        self.assertEqual(error.code, "RATE_LIMIT")
        self.assertTrue(error.retryable)
        self.assertEqual(error.details["reason"], "rate_limited")
        self.assertEqual(error.details["limit"], 2)
        self.assertEqual(error.details["retry_after_ms"], 500)

    def test_tokens_refill_on_the_monotonic_clock(self):
        controller = self.controller(rate=2, window=1.0)
        for _ in range(2):
            controller.admit("agent://a").release()
        self.clock.advance(0.5)
        with controller.admit("agent://a"):
            pass

    def test_refill_is_capped_at_the_burst(self):
        controller = self.controller(rate=2, window=1.0)
        for _ in range(2):
            controller.admit("agent://a").release()
        self.clock.advance(60)
        self.assertEqual(controller.snapshot("agent://a")["tokens"], 2.0)
        for _ in range(2):
            controller.admit("agent://a").release()
        with self.assertRaises(OsapError):
            controller.admit("agent://a")

    def test_one_agent_cannot_exhaust_another(self):
        controller = self.controller(rate=1, window=60.0)
        controller.admit("agent://busy").release()
        with self.assertRaises(OsapError):
            controller.admit("agent://busy")
        with controller.admit("agent://calm"):
            pass

    def test_a_zero_rate_rejects_every_message(self):
        controller = self.controller(rate=0)
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a")
        self.assertEqual(caught.exception.details["reason"], "rate_limited")
        self.assertIsNone(caught.exception.details.get("retry_after_ms"))

    def test_releasing_a_lease_does_not_refund_a_token(self):
        controller = self.controller(rate=1, window=60.0)
        with controller.admit("agent://a"):
            pass
        with self.assertRaises(OsapError):
            controller.admit("agent://a")


class InFlightTests(unittest.TestCase):
    def test_in_flight_limit_rejects_when_the_queue_is_disabled(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=0, rate=None)
        )
        held = controller.admit("agent://a")
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a")
        self.assertEqual(caught.exception.code, "RATE_LIMIT")
        self.assertEqual(caught.exception.details["reason"], "in_flight_limit")
        held.release()
        with controller.admit("agent://a"):
            pass

    def test_a_waiter_is_granted_a_slot_on_release(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=None)
        )
        held = controller.admit("agent://a")
        admitted = threading.Event()

        def worker():
            with controller.admit("agent://a", timeout=2.0):
                admitted.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        wait_until(lambda: controller.snapshot("agent://a")["queued"] == 1)
        self.assertEqual(controller.snapshot("agent://a")["in_flight"], 1)
        held.release()
        self.assertTrue(admitted.wait(2.0))
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        snapshot = controller.snapshot("agent://a")
        self.assertEqual(snapshot["in_flight"], 0)
        self.assertEqual(snapshot["queued"], 0)

    def test_queue_full_is_rejected_without_waiting(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=None)
        )
        held = controller.admit("agent://a")
        admitted = threading.Event()

        def worker():
            with controller.admit("agent://a", timeout=2.0):
                admitted.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        wait_until(lambda: controller.snapshot("agent://a")["queued"] == 1)
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a", timeout=2.0)
        self.assertEqual(caught.exception.details["reason"], "queue_full")
        self.assertEqual(caught.exception.details["queued"], 1)
        held.release()
        self.assertTrue(admitted.wait(2.0))
        thread.join(2.0)

    def test_queue_timeout_removes_the_waiter_and_keeps_the_slot(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=None)
        )
        held = controller.admit("agent://a")
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a", timeout=0.01)
        self.assertEqual(caught.exception.details["reason"], "queue_timeout")
        snapshot = controller.snapshot("agent://a")
        self.assertEqual(snapshot["in_flight"], 1)
        self.assertEqual(snapshot["queued"], 0)
        held.release()

    def test_a_timed_out_waiter_gets_its_rate_token_back(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=2, window=60.0)
        )
        held = controller.admit("agent://a")
        with self.assertRaises(OsapError) as caught:
            controller.admit("agent://a", timeout=0.01)
        self.assertEqual(caught.exception.details["reason"], "queue_timeout")
        held.release()
        with controller.admit("agent://a"):
            pass

    def test_one_agent_can_fill_its_queue_without_blocking_another(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=None)
        )
        held = controller.admit("agent://busy")
        admitted = threading.Event()

        def worker():
            with controller.admit("agent://busy", timeout=2.0):
                admitted.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        wait_until(lambda: controller.snapshot("agent://busy")["queued"] == 1)
        with controller.admit("agent://calm"):
            pass
        self.assertEqual(controller.snapshot("agent://busy")["queued"], 1)
        held.release()
        self.assertTrue(admitted.wait(2.0))
        thread.join(2.0)


class ConnectionTests(unittest.TestCase):
    def test_connection_limit_is_released_on_close(self):
        controller = AdmissionController(
            Quota(max_connections=1, rate=None)
        )
        first = controller.open_connection("exe:/app")
        with self.assertRaises(OsapError) as caught:
            controller.open_connection("exe:/app")
        self.assertEqual(caught.exception.details["reason"], "connection_limit")
        self.assertEqual(caught.exception.details["connections"], 1)
        first.release()
        second = controller.open_connection("exe:/app")
        second.release()

    def test_connection_admission_does_not_queue(self):
        controller = AdmissionController(Quota(max_connections=1))
        with self.assertRaises(ValueError):
            controller.open_connection("exe:/app", timeout=1.0)

    def test_connections_are_isolated_per_identity(self):
        controller = AdmissionController(Quota(max_connections=1))
        first = controller.open_connection("exe:/one")
        second = controller.open_connection("exe:/two")
        first.release()
        second.release()


class LeaseTests(unittest.TestCase):
    def test_release_is_idempotent(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=0, rate=None)
        )
        lease = controller.admit("agent://a")
        lease.release()
        lease.release()
        with controller.admit("agent://a"):
            pass

    def test_context_manager_releases_on_an_exception(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=0, rate=None)
        )
        with self.assertRaises(RuntimeError):
            with controller.admit("agent://a"):
                raise RuntimeError("boom")
        self.assertEqual(controller.snapshot("agent://a")["in_flight"], 0)
        with controller.admit("agent://a"):
            pass

    def test_snapshot_reports_counters_and_rejections(self):
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=0, rate=None)
        )
        held = controller.admit("agent://a")
        with self.assertRaises(OsapError):
            controller.admit("agent://a")
        snapshot = controller.snapshot("agent://a")
        self.assertEqual(snapshot["in_flight"], 1)
        self.assertEqual(snapshot["rejected"], 1)
        self.assertEqual(snapshot["last_reject"], "in_flight_limit")
        held.release()

    def test_unknown_identity_shares_one_bucket(self):
        self.assertEqual(sender_identity({}), "unknown")
        self.assertEqual(sender_identity(None), "unknown")
        self.assertEqual(sender_identity({"from": "agent://a"}), "agent://a")
        self.assertEqual(
            sender_identity({"from": {"agent": "agent://b"}}), "agent://b"
        )


class BusAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.controller = AdmissionController(
            Quota(rate=1, window=60.0), clock=self.clock
        )
        self.bus = Bus(admission=self.controller)
        self.bus.handshake({"osap": "0.1"})

    def test_a_second_message_from_the_same_sender_is_rate_limited(self):
        first = message("request.json")
        first["id"] = "req_first"
        self.bus.receive(first)
        second = copy.deepcopy(first)
        second["id"] = "req_second"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(second)
        self.assertEqual(caught.exception.code, "RATE_LIMIT")

    def test_another_sender_still_passes(self):
        first = message("request.json")
        self.bus.receive(first)
        other = copy.deepcopy(first)
        other["id"] = "req_other"
        other["from"] = "agent://com.example.notes/assistant#7f3a"
        self.bus.receive(other)

    def test_the_error_envelope_is_retryable_and_keeps_details(self):
        first = message("request.json")
        self.bus.receive(first)
        second = copy.deepcopy(first)
        second["id"] = "req_second"
        with self.assertRaises(OsapError) as caught:
            self.bus.receive(second)
        reply = self.bus.error_envelope(second, caught.exception)
        envelope.validate(reply)
        data = reply["body"]["data"]
        self.assertEqual(data["code"], "RATE_LIMIT")
        self.assertTrue(data["retryable"])
        self.assertEqual(data["details"]["reason"], "rate_limited")
        self.assertEqual(data["details"]["identity"], first["from"])

    def test_hello_also_consumes_a_token(self):
        bus = Bus(
            admission=AdmissionController(
                Quota(rate=1, window=60.0), clock=self.clock
            )
        )
        hello = load("hello.json")
        bus.receive(hello)
        with self.assertRaises(OsapError) as caught:
            bus.receive(hello)
        self.assertEqual(caught.exception.code, "RATE_LIMIT")

    def test_a_rejected_message_does_not_execute_a_side_effect(self):
        first = message("request.json")
        self.bus.receive(first)
        self.assertEqual(self.bus.side_effects, 1)
        second = copy.deepcopy(first)
        second["id"] = "req_second"
        with self.assertRaises(OsapError):
            self.bus.receive(second)
        self.assertEqual(self.bus.side_effects, 1)
        self.assertEqual(self.bus.received, [first["id"]])

    def test_a_dispatch_failure_releases_the_slot(self):
        bus = Bus(
            admission=AdmissionController(
                Quota(max_in_flight=1, max_queued=0, rate=None)
            )
        )
        bus.handshake({"osap": "0.1"})
        unsupported = message("request.json")
        unsupported["type"] = "discover"
        with self.assertRaises(NotImplementedError):
            bus.receive(unsupported)
        self.assertEqual(bus.admission.snapshot(unsupported["from"])["in_flight"], 0)
        bus.receive(message("request.json"))


if __name__ == "__main__":
    unittest.main()
