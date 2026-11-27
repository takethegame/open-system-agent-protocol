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
from .clock import Deadline, parse_timestamp
from .errors import OsapError
from .flowcontrol import AdmissionController
from .opaque import open_p1 as _p1_open, seal_p1 as _p1_seal
from .idempotency import IdempotencyIndex
from .store import JsonStore

AWAITING_HELLO = "awaiting_hello"
READY = "ready"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def base64_url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


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
        describe_service=None,
        refs_authorizer=None,
        clock=None,
        streams=None,
        events=None,
        skew_seconds: float | None = None,
        p1_keys=None,
        p1_required: bool = False,
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
        if describe_service is not None and not callable(
            getattr(describe_service, "describe", None)
        ):
            raise ValueError("describe_service must expose describe()")
        if refs_authorizer is not None and not callable(refs_authorizer):
            raise ValueError("refs_authorizer must be callable")
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable")
        if streams is not None and not callable(getattr(streams, "chunk", None)):
            raise ValueError("streams must expose chunk()")
        if events is not None and not callable(getattr(events, "publish", None)):
            raise ValueError("events must expose publish()")
        self.binding = binding
        self.version = version
        self.state = AWAITING_HELLO
        self.idempotency = idempotency
        self.admission = admission or AdmissionController()
        self.admission_wait = admission_wait
        self.progress_board = progress_board
        self.describe_service = describe_service
        self.refs_authorizer = refs_authorizer
        self.streams = streams
        self.events = events
        self._clock = clock
        self.skew_seconds = skew_seconds
        if skew_seconds is not None and (
            not isinstance(skew_seconds, (int, float))
            or isinstance(skew_seconds, bool)
            or skew_seconds < 0
        ):
            raise ValueError("skew_seconds must be a non-negative number or None")
        if p1_keys is not None and not callable(getattr(p1_keys, "private_for", None)):
            raise ValueError("p1_keys must expose private_for()")
        if p1_required and p1_keys is None:
            raise ValueError("p1_required requires p1_keys")
        self.p1_keys = p1_keys
        self.p1_required = p1_required
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
                    # §2.5: the bus publishes its time and the tolerated skew
                    # so senders can pre-screen their own timestamps.
                    "now": _stamp(self._clock() if self._clock else datetime.now(timezone.utc)),
                    "clock_skew_seconds": self.skew_seconds,
                },
            },
            "ts": _now(),
        }
        if hello.get("id"):
            welcome["causation_id"] = hello["id"]
        if self.p1_keys is not None:
            # P1 feature bit + current key so peers can seal immediately (§4.3
            # of docs/p1-opaque-bus.md).
            welcome["features"] = ["p1"]
            welcome["p1_kid"] = self.p1_keys.active_kid
            welcome["p1_public_key"] = base64_url(self.p1_keys.active_public_key)
        return welcome
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

            if isinstance(message, dict) and (message.get("body") or {}).get("schema") == "osap.opaque/v1":
                # P1 opaque envelope: auth/body/refs/consent live inside the
                # ciphertext, so only the reduced routing shape is checked
                # here; the merged envelope is fully validated after unsealing.
                self._validate_opaque(message)
            else:
                envelope.validate(message)
            self._check_skew(message)
            self.received.append(message["id"])
            return self.dispatch(message)

    def receive_bytes(self, data: bytes) -> list[dict]:
        """Decode a stream binding buffer and dispatch every complete frame."""

        if self.binding != framing.Binding.STREAM:
            raise RuntimeError("raw bytes require a stream binding")
        messages, _remainder = framing.decode_stream(data)
        return [reply for message in messages if (reply := self.receive(message)) is not None]

    def _check_skew(self, message: dict) -> None:
        """Reject messages whose `ts` deviates beyond the tolerated skew (§2.5).

        Opt-in: `skew_seconds=None` (the default) disables the check, which
        keeps the SHOULD satisfied by capability rather than enforcement.
        """

        if self.skew_seconds is None:
            return
        raw = message.get("ts")
        if not isinstance(raw, str) or not raw:
            return
        message_ts = parse_timestamp(raw)
        bus_now = self._clock() if self._clock else datetime.now(timezone.utc)
        delta = abs((message_ts - bus_now).total_seconds())
        if delta > self.skew_seconds:
            raise OsapError(
                "TRANSPORT_CLOCK_SKEW",
                "message timestamp deviates beyond the tolerated skew",
                details={
                    "message_ts": raw,
                    "bus_now": _stamp(bus_now),
                    "allowed_skew_seconds": self.skew_seconds,
                    "deviation_seconds": delta,
                },
            )

    #: Fields that live inside the encrypted P1 payload (§4.3 of the design).
    P1_INNER_FIELDS = frozenset({"auth", "body", "refs", "consent", "extensions"})

    def seal(self, envelope: dict, *, peer_public_key: bytes) -> dict:
        """Seal a P0 envelope into an `osap.opaque/v1` P1 envelope."""

        inner = {
            key: envelope[key]
            for key in ("auth", "body", "refs", "consent", "extensions")
            if key in envelope
        }
        outer = {
            key: value for key, value in envelope.items()
            if key not in self.P1_INNER_FIELDS
        }
        outer["body"] = {
            "schema": "osap.opaque/v1",
            "data": _p1_seal(outer, inner, pk_r=peer_public_key),
        }
        return outer

    def _unseal_p1(self, message: dict) -> dict:
        if self.p1_keys is None:
            raise NotImplementedError(
                "bus does not unseal opaque bodies without p1_keys"
            )
        data = (message.get("body") or {}).get("data") or {}
        kid = data.get("p1_kid")
        private_key = self.p1_keys.private_for(kid)
        if private_key is None:
            raise OsapError(
                "AUTH_DENIED",
                "opaque body carries an unknown, rotated, or destroyed p1_kid",
                details={"p1_kid": kid},
            )
        # The AAD is the routing metadata WITHOUT the opaque body — exactly
        # what `seal` computed over (docs/p1-opaque-bus.md §4.2).
        outer = {
            key: value for key, value in message.items()
            if key not in self.P1_INNER_FIELDS
        }
        inner = _p1_open(outer, data, sk_r=private_key)
        merged = dict(outer)
        merged.update(inner)
        return merged

    def _validate_opaque(self, message: dict) -> None:
        """Reduced envelope validation for `osap.opaque/v1` bodies (§3.6).

        Checks everything the outer envelope can honestly carry: version,
        known type, the routing fields, and a task for task-scoped types.
        Everything else is inside the ciphertext and is validated on the
        merged envelope after unsealing.
        """

        if not isinstance(message, dict):
            raise OsapError("SCHEMA_INVALID", "envelope must be a JSON object")
        version = message.get("osap")
        if not isinstance(version, str):
            raise OsapError("SCHEMA_INVALID", "osap version must be a string")
        if envelope.major_version(version) != envelope.SUPPORTED_MAJOR:
            raise OsapError(
                "TRANSPORT_VERSION_UNSUPPORTED",
                f"unsupported osap major version: {version}",
                details={"supported_major": envelope.SUPPORTED_MAJOR},
            )
        if message.get("type") not in envelope.KNOWN_TYPES:
            raise OsapError(
                "SCHEMA_UNSUPPORTED",
                f"unknown message type: {message.get('type')!r}",
            )
        for field in ("id", "from", "to", "body", "ts"):
            if field not in message:
                raise OsapError("SCHEMA_INVALID", f"{field} is required")
        if message["type"] in ("request", "delegate", "handoff") and "task" not in message:
            raise OsapError("SCHEMA_INVALID", f"{message['type']} requires task")

    def dispatch(self, message: dict) -> dict | None:
        """Route a validated message; None for one-way types like `status`."""

        kind = message["type"]

        # §3.6 / docs/p1-opaque-bus.md: an opaque body carries the sealed
        # inner payload. Unseal it, merge the inner fields back onto the
        # outer envelope, and dispatch the reconstructed message through the
        # normal routing — so authorization, progress, and audit behave
        # exactly as in P0 after the cryptographic boundary.
        body = message.get("body") or {}
        if body.get("schema") == "osap.opaque/v1":
            merged = self._unseal_p1(message)
            envelope.validate(merged)
            return self.dispatch(merged)

        # §3.6: a P1-required deployment rejects any task-scoped plaintext.
        if self.p1_required and kind in ("request", "delegate", "handoff"):
            raise OsapError(
                "POLICY_DENIED",
                "this bus requires P1 opaque bodies for task-scoped messages",
                details={"reason": "p1_required"},
            )

        # §7.1: the sender must be allowed to pass every handle in refs. The
        # check is wired through an authorizer because handle ownership lives
        # in the Context Fabric, not the Bus core.
        refs = message.get("refs") or []
        if refs and self.refs_authorizer is not None:
            verdicts = self.refs_authorizer(
                agent=message.get("from"), refs=refs
            )
            denied = sorted(
                ref for ref, verdict in verdicts.items()
                if verdict.get("decision") == "deny"
            )
            if denied:
                raise OsapError(
                    "CONTEXT_DENIED",
                    "a ref is not passable by the sender",
                    details={"refs": denied},
                )

        if kind == "describe":
            if self.describe_service is None:
                raise NotImplementedError(
                    f"bus does not route {kind!r} without a describe service"
                )
            target = (message.get("body") or {}).get("data") or {}
            records = self.describe_service.describe(
                target, now=self._clock() if self._clock else None
            )
            if not records:
                raise OsapError(
                    "ROUTING_NOT_FOUND",
                    "describe found no matching record",
                    details={"target": target},
                )
            return {
                "type": "result",
                "id": message["id"],
                "causation_id": message["id"],
                "body": {"schema": "osap.describe/v1", "data": {"records": records}},
            }
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
        if kind in ("stream.open", "stream.chunk", "stream.close"):
            if self.streams is None:
                raise NotImplementedError(
                    f"bus does not route {kind!r} without a stream registry"
                )
            data = (message.get("body") or {}).get("data") or {}
            stream_id = data.get("stream_id")
            if kind == "stream.open":
                self.streams.open(
                    stream_id,
                    schema=data.get("schema"),
                    total_estimate=data.get("total_estimate"),
                )
            elif kind == "stream.chunk":
                self.streams.chunk(
                    stream_id,
                    seq=data.get("seq"),
                    data=data.get("data"),
                    ref=data.get("ref"),
                )
            else:
                self.streams.close(stream_id, status=data.get("status"))
            # One-way: the receiver builds the result from its stream view.
            return None
        if kind == "event":
            if self.events is None:
                raise NotImplementedError(
                    f"bus does not route {kind!r} without an event broker"
                )
            data = (message.get("body") or {}).get("data") or {}
            topic = data.get("topic") or ""
            payload = data.get("payload")
            self.events.publish(
                topic,
                event={
                    "id": message.get("id"),
                    "origin": message.get("origin") or data.get("origin"),
                    "payload": payload,
                    "refs": message.get("refs") or [],
                },
                sender=message.get("from"),
            )
            # One-way publication; delivery is at-most-once per subscriber.
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
