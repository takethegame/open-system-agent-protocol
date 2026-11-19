# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Integration tests for the real local transport bindings (§7.9, §7.10)."""

import copy
import json
import os
import select
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from osap import AdmissionController, JsonStore, Quota, capability, framing, transport
from osap.bus import Bus
from osap.errors import OsapError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def hello() -> dict:
    return copy.deepcopy(load("hello.json"))


def request() -> dict:
    message = copy.deepcopy(load("request.json"))
    message["deadline"] = "2099-01-01T00:00:00Z"
    message["ts"] = "2026-11-15T00:00:00Z"
    return message


def start(target, **kwargs):
    thread = threading.Thread(target=target, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition was not reached before the timeout")


def _readable(sock) -> bool:
    readable, _, _ = select.select([sock], [], [], 0)
    return bool(readable)


class Gate:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()


class GatedBus(Bus):
    """A Bus whose busy-Agent dispatch waits for the test to release it."""

    def __init__(self, gate, **kwargs):
        super().__init__(**kwargs)
        self.gate = gate

    def dispatch(self, message):
        if message.get("from") == "agent://busy":
            self.gate.started.set()
            if not self.gate.release.wait(2):
                raise TimeoutError("gate was not released")
        return super().dispatch(message)


class PeerCredentialTests(unittest.TestCase):
    def test_socketpair_reports_the_current_process(self):
        server, client = transport.UnixMessagePair.pair()
        try:
            self.assertEqual(server.peer.uid, os.getuid())
            self.assertEqual(server.peer.gid, os.getgid())
            self.assertEqual(server.peer.pid, os.getpid())
            self.assertIsNotNone(server.peer.executable)
            self.assertIsNotNone(client.peer.uid)
        finally:
            server.close()
            client.close()

    def test_exact_policy_accepts_the_current_peer(self):
        policy = transport.PeerPolicy(
            uid=os.getuid(),
            gid=os.getgid(),
            pid=os.getpid(),
            executable=sys.executable,
        )
        server, client = transport.UnixMessagePair.pair(peer_policy=policy)
        server.close()
        client.close()

    def test_wrong_uid_is_denied(self):
        policy = transport.PeerPolicy(uid=os.getuid() + 1)
        with self.assertRaises(OsapError) as caught:
            transport.UnixMessagePair.pair(peer_policy=policy)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")
        self.assertEqual(caught.exception.details["reason"], "peer_mismatch")

    def test_wrong_executable_is_denied(self):
        policy = transport.PeerPolicy(executable="/bin/definitely-not-this-process")
        with self.assertRaises(OsapError) as caught:
            transport.UnixMessagePair.pair(peer_policy=policy)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_unavailable_field_fails_closed(self):
        policy = transport.PeerPolicy(pid=4242)
        peer = transport.PeerCredentials(uid=1, gid=1, pid=None)
        with self.assertRaises(OsapError) as caught:
            policy.check(peer)
        self.assertEqual(caught.exception.details["reason"], "peer_field_unavailable")

    def test_missing_executable_fails_closed(self):
        policy = transport.PeerPolicy(executable=sys.executable)
        peer = transport.PeerCredentials(uid=1, gid=1, pid=1, executable=None)
        with self.assertRaises(OsapError) as caught:
            policy.check(peer)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")


class MessageTransportTests(unittest.TestCase):
    def test_hello_then_request_round_trip(self):
        server, client = transport.UnixMessagePair.pair(timeout=2)
        thread = start(server.serve_forever, max_messages=2)
        try:
            welcome = client.call(hello())
            self.assertEqual(welcome["type"], "welcome")
            self.assertEqual(
                welcome["body"]["data"]["binding"],
                framing.Binding.MESSAGE.value,
            )
            result = client.call(request())
            self.assertEqual(result["type"], "result")
            self.assertFalse(result["replayed"])
            self.assertTrue(thread.join(2) is None)
        finally:
            client.close()
            server.close()

    def test_two_datagrams_keep_two_boundaries(self):
        server, client = transport.UnixMessagePair.pair(timeout=2)
        thread = start(server.serve_forever, max_messages=2)
        try:
            client.send(hello())
            client.send({"osap": "0.1"})
            welcome = client.receive()
            error = client.receive()
            self.assertEqual(welcome["type"], "welcome")
            self.assertEqual(error["type"], "error")
            self.assertTrue(thread.join(2) is None)
        finally:
            client.close()
            server.close()

    def test_oversized_message_is_rejected_before_sending(self):
        server, client = transport.UnixMessagePair.pair(timeout=2)
        try:
            with self.assertRaises(OsapError) as caught:
                client.send({"osap": "0.1", "padding": "x" * framing.MAX_FRAME_BYTES})
            self.assertEqual(caught.exception.code, "TRANSPORT_FRAME_TOO_LARGE")
        finally:
            client.close()
            server.close()


class StreamTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bus.sock")
        self.server = transport.UnixStreamServer(self.path)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        return transport.UnixStreamClient.connect(self.path, timeout=2)

    def test_hello_then_request_round_trip(self):
        thread = start(self.server.serve_forever, max_messages=2)
        client = self.connect()
        try:
            self.assertEqual(client.call(hello())["type"], "welcome")
            self.assertEqual(client.call(request())["type"], "result")
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_request_before_hello_is_rejected(self):
        thread = start(self.server.serve_forever, max_messages=1)
        client = self.connect()
        try:
            reply = client.call(request())
            self.assertEqual(reply["type"], "error")
            self.assertEqual(
                reply["body"]["data"]["code"],
                "TRANSPORT_HANDSHAKE_REQUIRED",
            )
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_connections_have_independent_handshake_state(self):
        thread = start(self.server.serve_forever, max_messages=2)
        first = self.connect()
        second = self.connect()
        try:
            self.assertEqual(first.call(hello())["type"], "welcome")
            first.close()
            reply = second.call(request())
            self.assertEqual(reply["body"]["data"]["code"], "TRANSPORT_HANDSHAKE_REQUIRED")
        finally:
            first.close()
            second.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_oversized_length_header_is_rejected(self):
        thread = start(self.server.serve_forever, max_messages=1)
        client = self.connect()
        try:
            client.sock.sendall(struct.pack(">I", framing.MAX_FRAME_BYTES + 1))
            reply = client.receive()
            self.assertEqual(
                reply["body"]["data"]["code"],
                "TRANSPORT_FRAME_TOO_LARGE",
            )
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_peer_policy_denies_accept_and_closes_the_connection(self):
        self.server.close()
        self.server = transport.UnixStreamServer(
            self.path,
            peer_policy=transport.PeerPolicy(uid=os.getuid() + 1),
        )
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.connect(self.path)
        try:
            with self.assertRaises(OsapError) as caught:
                self.server.accept()
            self.assertEqual(caught.exception.code, "AUTH_DENIED")
        finally:
            raw.close()

    def test_close_removes_the_socket_file(self):
        self.assertTrue(Path(self.path).exists())
        self.server.close()
        self.assertFalse(Path(self.path).exists())

    def test_refuses_to_replace_a_regular_file(self):
        self.server.close()
        Path(self.path).write_text("not a socket", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            transport.UnixStreamServer(self.path)
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), "not a socket")


class ConcurrentStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bus.sock")
        self.server = transport.UnixStreamServer(self.path)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        return transport.UnixStreamClient.connect(self.path, timeout=2)

    def test_concurrency_must_be_a_positive_int(self):
        with self.assertRaises(ValueError):
            self.server.serve_forever(concurrency=0)
        with self.assertRaises(ValueError):
            self.server.serve_forever(concurrency=True)

    def test_an_idle_connection_does_not_block_another(self):
        thread = start(self.server.serve_forever, max_messages=2, concurrency=2)
        idle = self.connect()
        active = self.connect()
        try:
            self.assertEqual(active.call(hello())["type"], "welcome")
            self.assertEqual(active.call(request())["type"], "result")
        finally:
            idle.close()
            active.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_the_same_agent_queues_on_its_shared_in_flight_slot(self):
        self.server.close()
        gate = Gate()
        controller = AdmissionController(
            Quota(max_in_flight=1, max_queued=1, rate=None)
        )
        self.server = transport.UnixStreamServer(
            self.path,
            admission=controller,
            admission_wait=2.0,
            bus_factory=lambda: GatedBus(
                gate,
                binding=framing.Binding.STREAM,
                admission=controller,
                admission_wait=2.0,
            ),
        )
        thread = start(self.server.serve_forever, concurrency=2)
        first = self.connect()
        second = self.connect()
        hello_message = hello()
        hello_message["from"] = "agent://busy"
        request_message = request()
        request_message["from"] = "agent://busy"
        try:
            self.assertEqual(first.call(hello_message)["type"], "welcome")
            first.send(request_message)
            self.assertTrue(gate.started.wait(2))
            second.send(hello_message)
            wait_until(
                lambda: controller.snapshot("agent://busy")["queued"] == 1
            )
            gate.release.set()
            self.assertEqual(first.receive()["type"], "result")
            self.assertEqual(second.receive()["type"], "welcome")
        finally:
            gate.release.set()
            self.server.close()
            first.close()
            second.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class SelectorStreamTests(unittest.TestCase):
    """The single-threaded event loop shares the concurrent-mode guarantees."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bus.sock")
        self.server = transport.UnixStreamServer(self.path)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        return transport.UnixStreamClient.connect(self.path, timeout=2)

    def test_selector_mode_rejects_a_concurrency(self):
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode="selector", concurrency=2)
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode="event-loop")
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode=True)

    def test_an_idle_connection_does_not_block_another(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="selector"
        )
        idle = self.connect()
        active = self.connect()
        try:
            self.assertEqual(active.call(hello())["type"], "welcome")
            self.assertEqual(active.call(request())["type"], "result")
        finally:
            idle.close()
            active.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_broken_peer_is_dropped_and_the_loop_continues(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="selector"
        )
        client = self.connect()
        abrupt = self.connect()
        try:
            abrupt.sock.close()  # the peer vanishes without a hello
            self.assertEqual(client.call(hello())["type"], "welcome")
            self.assertEqual(client.call(request())["type"], "result")
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_max_messages_stops_the_loop(self):
        thread = start(
            self.server.serve_forever, max_messages=1, mode="selector"
        )
        first = self.connect()
        try:
            self.assertEqual(first.call(hello())["type"], "welcome")
        finally:
            first.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        late = self.connect()
        try:
            with self.assertRaises((OSError, OsapError)):
                late.call(hello())
        finally:
            late.close()

    def test_a_closed_listener_stops_the_loop(self):
        thread = start(self.server.serve_forever, mode="selector")
        client = self.connect()
        try:
            self.assertEqual(client.call(hello())["type"], "welcome")
        finally:
            client.close()
        self.server.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_connection_quota_is_enforced_in_selector_mode(self):
        self.server.close()
        controller = AdmissionController(Quota(max_connections=1))
        self.server = transport.UnixStreamServer(self.path, admission=controller)
        thread = start(
            self.server.serve_forever, max_messages=2, mode="selector"
        )
        first = self.connect()
        second = self.connect()
        try:
            self.assertEqual(first.call(hello())["type"], "welcome")
            # The rejection is sent and the connection is closed before any
            # hello from the second peer, so wait for the envelope instead of
            # writing into a socket that is already gone.
            wait_until(lambda: _readable(second.sock))
            rejected = second.receive()
            self.assertEqual(rejected["type"], "error")
            self.assertEqual(
                rejected["body"]["data"]["code"], "RATE_LIMIT"
            )
            self.assertEqual(
                rejected["body"]["data"]["details"]["reason"],
                "connection_limit",
            )
            self.assertEqual(first.call(request())["type"], "result")
        finally:
            first.close()
            second.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class AsyncioStreamTests(unittest.TestCase):
    """The asyncio loop buffers frames, so a stalled peer holds only itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bus.sock")
        self.server = transport.UnixStreamServer(self.path)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        return transport.UnixStreamClient.connect(self.path, timeout=2)

    def test_asyncio_mode_rejects_a_concurrency(self):
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode="asyncio", concurrency=2)
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode="fiber")
        with self.assertRaises(ValueError):
            self.server.serve_forever(mode=True)

    def test_hello_then_request_round_trip(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="asyncio"
        )
        client = self.connect()
        try:
            self.assertEqual(client.call(hello())["type"], "welcome")
            self.assertEqual(client.call(request())["type"], "result")
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_an_idle_connection_does_not_block_another(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="asyncio"
        )
        idle = self.connect()
        active = self.connect()
        try:
            self.assertEqual(active.call(hello())["type"], "welcome")
            self.assertEqual(active.call(request())["type"], "result")
        finally:
            idle.close()
            active.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_stalled_half_frame_does_not_block_another_peer(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="asyncio"
        )
        stalled = self.connect()
        active = self.connect()
        try:
            # Exactly half of a length header, then silence: the selector and
            # thread-pool loops would wait on the stalled socket here.
            stalled.sock.send(b"\x00\x00")
            self.assertEqual(active.call(hello())["type"], "welcome")
            self.assertEqual(active.call(request())["type"], "result")
        finally:
            stalled.close()
            active.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_broken_peer_is_dropped_and_the_loop_continues(self):
        thread = start(
            self.server.serve_forever, max_messages=2, mode="asyncio"
        )
        client = self.connect()
        abrupt = self.connect()
        try:
            abrupt.sock.close()
            self.assertEqual(client.call(hello())["type"], "welcome")
            self.assertEqual(client.call(request())["type"], "result")
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_connection_quota_is_enforced_in_asyncio_mode(self):
        self.server.close()
        controller = AdmissionController(Quota(max_connections=1))
        self.server = transport.UnixStreamServer(self.path, admission=controller)
        thread = start(
            self.server.serve_forever, max_messages=2, mode="asyncio"
        )
        first = self.connect()
        second = self.connect()
        try:
            self.assertEqual(first.call(hello())["type"], "welcome")
            wait_until(lambda: _readable(second.sock))
            rejected = second.receive()
            self.assertEqual(rejected["type"], "error")
            self.assertEqual(rejected["body"]["data"]["code"], "RATE_LIMIT")
            self.assertEqual(first.call(request())["type"], "result")
        finally:
            first.close()
            second.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_max_messages_stops_the_loop(self):
        thread = start(
            self.server.serve_forever, max_messages=1, mode="asyncio"
        )
        first = self.connect()
        try:
            self.assertEqual(first.call(hello())["type"], "welcome")
        finally:
            first.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_a_closed_listener_stops_the_loop(self):
        thread = start(self.server.serve_forever, mode="asyncio")
        client = self.connect()
        try:
            self.assertEqual(client.call(hello())["type"], "welcome")
        finally:
            client.close()
        self.server.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class RevocationFeedTests(unittest.TestCase):
    """The push channel delivers journal batches to subscribers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source_path = os.path.join(self.tmp.name, "source.json")
        self.replica_path = os.path.join(self.tmp.name, "replica.json")
        self.path = os.path.join(self.tmp.name, "feed.sock")
        self.source = capability.CapabilityAuthority(store=JsonStore(self.source_path))
        self.replica = capability.CapabilityAuthority(store=JsonStore(self.replica_path))
        self.source_store = JsonStore(self.source_path)
        self.server = transport.RevocationFeedServer(
            self.path,
            # A fresh store per call: the journal file is the transport, so a
            # subscriber must always re-read it, never trust a cached copy.
            lambda: JsonStore(self.source_path).get("capability.revocations"),
            source="issuer",
        )

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def journal(self):
        return self.source_store.get("capability.revocations")

    def stop(self, thread):
        """The feed serves until close(); stop it before joining the thread."""

        self.server.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def revoke_chain(self, prefix: str, length: int = 1) -> int:
        template = load("capability.json")
        template.pop("parent_cap_id", None)
        template["cap_id"] = f"{prefix}_0"
        template["depth"] = 0
        self.source.issue(template)
        parent = f"{prefix}_0"
        for position in range(1, length + 1):
            child = copy.deepcopy(load("capability.json"))
            child["cap_id"] = f"{prefix}_{position}"
            child["parent_cap_id"] = parent
            child["depth"] = position
            self.source.issue(child)
            parent = child["cap_id"]
        self.source.revoke(f"{prefix}_0")
        self.server.notify()
        return length + 1

    def test_a_pushed_batch_is_applied_to_the_replica(self):
        thread = start(self.server.serve_forever)
        expected = self.revoke_chain("cap_feed_a")
        with transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        ) as session:
            report = session.receive()
        self.assertEqual(report["applied"], expected)
        self.assertEqual(report["cursor"], expected)
        self.assertTrue(self.replica.is_revoked({"cap_id": "cap_feed_a_0"}))
        self.assertTrue(self.replica.is_revoked({"cap_id": "cap_feed_a_1"}))
        self.stop(thread)

    def test_a_late_subscriber_gets_the_catch_up_batch(self):
        thread = start(self.server.serve_forever)
        expected = self.revoke_chain("cap_feed_b")
        time.sleep(0.1)
        with transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        ) as session:
            report = session.receive()
        self.assertEqual(report["applied"], expected)
        self.assertEqual(self.replica.applied_sources().get("issuer"), expected)
        self.stop(thread)

    def test_two_subscribers_each_get_the_batch(self):
        thread = start(self.server.serve_forever)
        expected = self.revoke_chain("cap_feed_c")
        other = capability.CapabilityAuthority(
            store=JsonStore(os.path.join(self.tmp.name, "replica2.json"))
        )
        first = transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        )
        second = transport.RevocationFeedClient.connect(
            self.path, other, source="issuer"
        )
        try:
            self.assertEqual(first.receive()["applied"], expected)
            self.assertEqual(second.receive()["applied"], expected)
        finally:
            first.close()
            second.close()
        self.stop(thread)

    def test_only_new_entries_are_pushed_after_the_first_batch(self):
        thread = start(self.server.serve_forever)
        with transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        ) as session:
            first = self.revoke_chain("cap_feed_d1")
            self.assertEqual(session.receive()["applied"], first)
            second = self.revoke_chain("cap_feed_d2")
            report = session.receive()
            self.assertEqual(report["applied"], second)
            self.assertEqual(session.batches, 2)
        self.stop(thread)

    def test_a_disconnected_subscriber_does_not_break_the_server(self):
        thread = start(self.server.serve_forever)
        dangling = transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        )
        dangling.close()
        expected = self.revoke_chain("cap_feed_e")
        with transport.RevocationFeedClient.connect(
            self.path, self.replica, source="issuer"
        ) as session:
            self.assertEqual(session.receive()["applied"], expected)
        # The dangling subscriber's push thread must be gone.
        time.sleep(0.1)
        self.assertEqual(len(self.server._connections), 1)
        self.stop(thread)

    def test_a_denied_peer_gets_no_batches(self):
        self.server.close()
        policy = transport.PeerPolicy(uid=os.getuid() + 12345)
        self.server = transport.RevocationFeedServer(
            self.path,
            lambda: JsonStore(self.source_path).get("capability.revocations"),
            source="issuer",
            peer_policy=policy,
        )
        thread = start(self.server.serve_forever)
        self.revoke_chain("cap_feed_f")
        session = transport.UnixStreamClient.connect(self.path, timeout=2)
        try:
            with self.assertRaises((ConnectionError, OSError)):
                session.receive()
        finally:
            session.close()
        self.stop(thread)

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            transport.RevocationFeedServer(self.path, "not callable")
        with self.assertRaises(ValueError):
            transport.RevocationFeedServer(self.path, self.server.journal, source="")
        with self.assertRaises(ValueError):
            transport.RevocationFeedSession(self.replica, object())

    def test_close_removes_the_socket_file(self):
        thread = start(self.server.serve_forever)
        time.sleep(0.1)
        self.server.close()
        self.assertFalse(os.path.exists(self.path))
        self.stop(thread)


class AdmissionTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "bus.sock")
        self.controller = AdmissionController(Quota(max_connections=1, rate=None))
        self.server = transport.UnixStreamServer(
            self.path, admission=self.controller
        )

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        return transport.UnixStreamClient.connect(self.path, timeout=2)

    def test_connection_quota_sends_rate_limit_before_closing(self):
        first_client = self.connect()
        first = self.server.accept()
        second_client = self.connect()
        try:
            with self.assertRaises(OsapError) as caught:
                self.server.accept()
            self.assertEqual(caught.exception.code, "RATE_LIMIT")
            reply = second_client.receive()
            self.assertEqual(reply["type"], "error")
            data = reply["body"]["data"]
            self.assertEqual(data["code"], "RATE_LIMIT")
            self.assertEqual(data["details"]["reason"], "connection_limit")
        finally:
            first.close()
            first_client.close()
            second_client.close()

        third_client = self.connect()
        third = self.server.accept()
        try:
            self.assertIs(third.bus.admission, self.controller)
        finally:
            third.close()
            third_client.close()

    def test_default_bus_factory_shares_the_controller(self):
        client = self.connect()
        session = self.server.accept()
        try:
            self.assertIs(session.bus.admission, self.controller)
        finally:
            session.close()
            client.close()

    def test_message_rate_limit_is_per_agent_over_the_wire(self):
        self.server.close()
        controller = AdmissionController(
            Quota(rate=1, window=60.0, max_connections=None)
        )
        self.controller = controller
        self.server = transport.UnixStreamServer(self.path, admission=controller)
        thread = start(self.server.serve_forever, max_messages=3)
        client = self.connect()
        hello_message = hello()
        request_message = request()
        request_message["from"] = hello_message["from"]
        other_message = request()
        other_message["id"] = "req_other"
        other_message["from"] = "agent://com.example.orchestrator/main#1a2b"
        try:
            self.assertEqual(client.call(hello_message)["type"], "welcome")
            rejected = client.call(request_message)
            self.assertEqual(rejected["type"], "error")
            self.assertEqual(rejected["body"]["data"]["code"], "RATE_LIMIT")
            self.assertEqual(
                rejected["body"]["data"]["details"]["identity"],
                hello_message["from"],
            )
            accepted = client.call(other_message)
            self.assertEqual(accepted["type"], "result")
        finally:
            client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class ConnectionIdentityTests(unittest.TestCase):
    def test_executable_wins_then_pid_then_uid(self):
        executable = transport.PeerCredentials(
            uid=1, pid=2, executable="/bin/sh"
        )
        self.assertEqual(
            transport.connection_identity(executable),
            "exe:" + os.path.realpath("/bin/sh"),
        )
        self.assertEqual(
            transport.connection_identity(transport.PeerCredentials(uid=1, pid=2)),
            "pid:2",
        )
        self.assertEqual(
            transport.connection_identity(transport.PeerCredentials(uid=1)),
            "uid:1",
        )
        self.assertEqual(
            transport.connection_identity(transport.PeerCredentials()),
            "unknown",
        )


if __name__ == "__main__":
    unittest.main()
