# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Integration tests for the real local transport bindings (§7.9, §7.10)."""

import copy
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from osap import AdmissionController, Quota, framing, transport
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
