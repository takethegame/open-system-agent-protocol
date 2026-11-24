# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Minimal Bus core: handshake, envelope validation, routing, idempotency.

Scope is M2.1. Identity, capabilities, consent, and the task model arrive in
later milestones; message types outside this scope raise `NotImplementedError`
so the conformance adapter can report them as `skip` rather than `fail`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from . import envelope, framing
from .clock import Deadline
from .errors import OsapError
from .flowcontrol import AdmissionController
from .idempotency import IdempotencyIndex
from .store import JsonStore

AWAITING_HELLO = "awaiting_hello"
READY = "ready"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sender_identity(message: object) -> str:
    """The per-Agent admission key for an envelope.

    `from` is a string in the current schema. The dict form is accepted too so
    an older or extended envelope cannot silently share the `unknown` bucket.
    """

    if not isinstance(message, dict):
        return "unknown"
    sender = message.get("from")
    if isinstance(sender, str) and sender:
        return sender
    if isinstance(sender, dict):
        agent = sender.get("agent")
        if isinstance(agent, str) and agent:
            return agent
    return "unknown"


class Bus:
    """A single-user, in-process Bus.

    The idempotency index is memory-only by default. Pass `store` (a file path
    or a shared `JsonStore`) or an explicit `idempotency` index to replay
    duplicates across a restart instead of re-executing their side effects.

    Every envelope passes through an `AdmissionController` (§7.11). The default
    is generous; pass one controller to several Buses to enforce one message
    quota per Agent across connections. `admission_wait` is how long a caller
    may wait for an in-flight slot before `RATE_LIMIT` is returned (default 0,
    which never blocks).
    """

    def __init__(
        self,
        *,
        binding: framing.Binding = framing.Binding.STREAM,
        version: str = "0.1",
        idempotency: IdempotencyIndex | None = None,
        store: JsonStore | str | os.PathLike[str] | None = None,
        admission: AdmissionController | None = None,
        admission_wait: float = 0.0,
        progress_board=None,
    ) -> None:
        if idempotency is not None and store is not None:
            raise ValueError("pass either idempotency or store, not both")
        if idempotency is None:
            if isinstance(store, JsonStore):
                idempotency = IdempotencyIndex(store=store)
            elif store is not None:
                idempotency = IdempotencyIndex(store=JsonStore(store))
            else:
                idempotency = IdempotencyIndex()
        if admission_wait < 0:
            raise ValueError("admission_wait must not be negative")
        if progress_board is not None and not callable(
            getattr(progress_board, "report_progress", None)
        ):
            raise ValueError("progress_board must expose report_progress()")
        self.binding = binding
        self.version = version
        self.state = AWAITING_HELLO
        self.idempotency = idempotency
        self.admission = admission or AdmissionController()
        self.admission_wait = admission_wait
        self.progress_board = progress_board
        self.side_effects = 0
        self.replays = 0
        self.received: list[str] = []

    # --- lifecycle ---------------------------------------------------------

    def handshake(self, hello: dict) -> dict:
        """Negotiate versions and answer with `welcome` (§7.1, §7.9)."""

        if not isinstance(hello, dict):
            raise OsapError("SCHEMA_INVALID", "hello must be an envelope object")
        version = hello.get("osap")
        if not isinstance(version, str):
            raise OsapError("SCHEMA_INVALID", "hello must carry an osap version")
        if envelope.major_version(version) != envelope.SUPPORTED_MAJOR:
            raise OsapError(
                "TRANSPORT_VERSION_UNSUPPORTED",
                f"unsupported osap major version: {version}",
                details={"supported_major": envelope.SUPPORTED_MAJOR},
            )
        if hello.get("type") not in (None, "hello"):
            raise OsapError("SCHEMA_INVALID", "handshake expects a hello message")
        if hello.get("type") == "hello":
            envelope.validate(hello)

        self.state = READY
        welcome = {
            "osap": self.version,
            "id": f"welcome_{hello.get('id', 'anonymous')}",
            "type": "welcome",
            "from": "agent://system/bus#0",
            "to": {"agent": hello.get("from", "agent://system/bus#0")},
            "body": {
                "schema": "osap.welcome/v1",
                "data": {
                    "osap": self.version,
                    "binding": self.binding.value,
                    "max_frame_bytes": framing.MAX_FRAME_BYTES,
                },
            },
            "ts": _now(),
        }
        if hello.get("id"):
            welcome["causation_id"] = hello["id"]
        return welcome

    # --- receive -----------------------------------------------------------

    def receive(self, message: dict) -> dict:
        """Validate and dispatch one logical message through admission control."""

        identity = sender_identity(message)
        with self.admission.admit(identity, timeout=self.admission_wait):
            if self.state == AWAITING_HELLO:
                if not isinstance(message, dict) or message.get("type") != "hello":
                    raise OsapError(
                        "TRANSPORT_HANDSHAKE_REQUIRED",
                        "hello/welcome has not completed on this connection",
                    )
                return self.handshake(message)

            envelope.validate(message)
            self.received.append(message["id"])
            return self.dispatch(message)

    def receive_bytes(self, data: bytes) -> list[dict]:
        """Decode a stream binding buffer and dispatch every complete frame."""

        if self.binding != framing.Binding.STREAM:
            raise RuntimeError("raw bytes require a stream binding")
        messages, _remainder = framing.decode_stream(data)
        return [reply for message in messages if (reply := self.receive(message)) is not None]

    def dispatch(self, message: dict) -> dict | None:
        """Route a validated message; None for one-way types like `status`."""

        kind = message["type"]
        if kind == "status":
            if self.progress_board is None:
                raise NotImplementedError(
                    f"bus does not route {kind!r} without a progress board"
                )
            data = (message.get("body") or {}).get("data") or {}
            self.progress_board.report_progress(
                envelope.task_id(message),
                consumed=data.get("consumed") or {},
                sender=message.get("from"),
            )
            return None
        if kind == "request":
            deadline = Deadline.from_envelope(message)
            deadline.check()

            def execute() -> dict:
                self.side_effects += 1
                return {"status": "accepted", "task_id": envelope.task_id(message)}

            result, replayed = self.idempotency.execute_once(message["id"], execute)
            if replayed:
                self.replays += 1
            return {
                "type": "result",
                "id": message["id"],
                "causation_id": message["id"],
                "replayed": replayed,
                "body": {"schema": "osap.result/v1", "data": result},
            }

        raise NotImplementedError(f"bus does not route {kind!r} before M2.3")

    # --- errors ------------------------------------------------------------

    def error_envelope(self, request: dict, error: OsapError) -> dict:
        """Build the `osap.error/v1` reply for a rejected request."""

        envelope_out = {
            "osap": self.version,
            "id": f"err_{request.get('id', 'unknown')}",
            "type": "error",
            "from": "agent://system/bus#0",
            "to": {"agent": request.get("from", "agent://system/bus#0")},
            "body": {"schema": "osap.error/v1", "data": error.to_data()},
            "ts": _now(),
        }
        if request.get("id"):
            envelope_out["causation_id"] = request["id"]
        if request.get("trace_id"):
            envelope_out["trace_id"] = request["trace_id"]
        return envelope_out
