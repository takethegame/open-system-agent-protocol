# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Audit chain, redacted export, replay, and recovery (§10.5–§10.7, §8.11).

`verify_chain` checks what the fixtures actually contain: each event is a
valid audit event, every event shares the chain trace, and every `prev_hash`
links to the previous `hash`. It does not recompute hashes from event bodies,
because the example hashes are short placeholders and the standard does not
fix a canonical audit encoding.

`AuditLedger` is the writable side. It records one trace, fills `audit_id`,
`ts`, `prev_hash`, and `hash`, and can persist the chain through a
`JsonStore`. Because the ledger defines its own encoding — key-sorted,
separator-minimal UTF-8 JSON with `hash` removed — it also rechecks each body
hash on restore, so a rewritten event cannot pass with a stale hash. A corrupt
or broken chain raises `AUDIT_CHAIN_INVALID`, which keeps L3/L4 state closed
after a restart (§3.7).

Redaction replaces target, policy, consent receipt, and context references
with per-export salted commitments. The hash chain stays untouched, so a
verifier can still prove that the chain was not altered and that each
commitment matches the original field, but cannot recover plaintext (§10.6).

`AuditLedger(max_events=...)` adds retention without losing verifiability. Each
trim moves the oldest events into an `audit.archive.<trace_id>` section, and
the next live event keeps pointing at the last archived hash. A verifier that
has both sections can therefore walk one chain from genesis; a live section
that was re-rooted after a trim fails verification because its first
`prev_hash` no longer matches the archive tail.

`AUDIT_CHAIN_INVALID` is a domain extension: §10.5 requires verification to
fail but defines no audit-specific standard code.
"""

from __future__ import annotations

import copy
import hashlib
import secrets
from datetime import datetime, timezone

from . import crypto, schema
from .errors import OsapError
from .idempotency import IdempotencyIndex
from .store import JsonStore

EVENT_SCHEMA = "audit-event.schema.json"
CHAIN_INVALID = "AUDIT_CHAIN_INVALID"

#: Prefix of the per-trace section a persisted ledger writes.
LEDGER_SECTION_PREFIX = "audit.chain."

#: Prefix of the per-trace section a trimming ledger archives into.
ARCHIVE_SECTION_PREFIX = "audit.archive."

#: `prev_hash` of the first event in a new chain.
GENESIS_HASH = "sha256:0000000000000000"

#: Fields replaced by commitments in a redacted export (§10.6).
REDACTED_FIELDS = ("target", "policy", "consent_receipt_id", "context_refs")

#: Effect events and the phase each must carry (§10.5).
EFFECT_PHASES = {"effect.intent": "intent", "effect.executed": "outcome"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_hash(event: dict) -> str:
    """Hash one event body with the ledger's canonical encoding."""

    body = {key: value for key, value in event.items() if key != "hash"}
    digest = hashlib.sha256(crypto.canonical_bytes(body, drop=())).hexdigest()
    return f"sha256:{digest}"


def verify_chain(chain: dict) -> bool:
    """Verify event schemas, trace consistency, and hash linkage (§10.6)."""

    events = chain.get("events") or []
    trace_id = chain.get("trace_id")
    seen: set[str] = set()

    for index, event in enumerate(events):
        schema.validate(EVENT_SCHEMA, event)

        if event["trace_id"] != trace_id:
            raise OsapError(
                CHAIN_INVALID,
                "audit event does not belong to the chain trace",
                details={
                    "index": index,
                    "trace_id": event["trace_id"],
                    "chain_trace_id": trace_id,
                },
            )
        if event["audit_id"] in seen:
            raise OsapError(
                CHAIN_INVALID,
                "duplicate audit_id in the chain",
                details={"index": index, "audit_id": event["audit_id"]},
            )
        seen.add(event["audit_id"])

        if index == 0:
            continue
        previous = events[index - 1]
        if event["prev_hash"] != previous["hash"]:
            raise OsapError(
                CHAIN_INVALID,
                "audit event does not link to the previous hash",
                details={
                    "index": index,
                    "audit_id": event["audit_id"],
                    "expected": previous["hash"],
                    "actual": event["prev_hash"],
                },
            )

    return True


class AuditLedger:
    """One trace's append-only audit chain, optionally durable.

    The ledger owns hash computation. `append` fills `trace_id`, `audit_id`,
    `ts`, `prev_hash`, and `hash` when absent, while callers provide the
    semantic fields (`actor`, `action`, `target`, `decision`, and optional
    references). The chain is validated before the first append is recorded,
    and `verify` rechecks schemas, links, and body hashes.

    Persisting writes one `audit.chain.<trace_id>` section per append. A
    ledger reopened over the same store must carry the same `trace_id`; a
    mismatched or corrupt section raises instead of returning a partial chain,
    so a Bus can keep L3/L4 actions closed (§3.7).

    With `max_events=N`, an append that would exceed N moves the oldest events
    into `audit.archive.<trace_id>` and writes both sections atomically. The
    live chain keeps its first event's `prev_hash` pointing at the last
    archived hash, so `verify()` still proves the whole history from genesis;
    `history()` returns the archive plus the live events as one chain.
    """

    def __init__(
        self,
        *,
        trace_id: str,
        store: JsonStore | None = None,
        clock=None,
        section: str | None = None,
        max_events: int | None = None,
        archive_section: str | None = None,
    ) -> None:
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("trace_id must be a non-empty string")
        if max_events is not None and (
            not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1
        ):
            raise ValueError("max_events must be a positive integer")
        self.trace_id = trace_id
        self.chain_id = f"audit_chain_{trace_id}"
        self.created_at = _stamp((clock or _now)())
        self.events: list[dict] = []
        self.max_events = max_events
        self._archived: list[dict] = []
        self._archive_chain_id: str | None = None
        self._clock = clock or _now
        self._store = store
        self._section = section or f"{LEDGER_SECTION_PREFIX}{trace_id}"
        self._archive_section = archive_section or f"{ARCHIVE_SECTION_PREFIX}{trace_id}"
        if store is not None:
            self._restore()

    # --- persistence -------------------------------------------------------

    def _restore(self) -> None:
        self._restore_archive()
        loaded = self._store.get(self._section)
        if loaded is None:
            if self._archived:
                raise ValueError(
                    f"{self._archive_section!r} has events but "
                    f"{self._section!r} is empty"
                )
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{self._section!r} must be a JSON object")
        if loaded.get("trace_id") != self.trace_id:
            raise ValueError(
                f"{self._section!r} holds trace {loaded.get('trace_id')!r}, "
                f"not {self.trace_id!r}"
            )
        events = loaded.get("events")
        if not isinstance(events, list):
            raise ValueError(f"{self._section!r} events must be a JSON array")
        chain_id = loaded.get("chain_id", self.chain_id)
        created_at = loaded.get("created_at", self.created_at)
        if not isinstance(chain_id, str) or not chain_id:
            raise ValueError(f"{self._section!r} chain_id must be a string")
        if not isinstance(created_at, str) or not created_at:
            raise ValueError(f"{self._section!r} created_at must be a string")
        if self._archive_chain_id is not None and self._archive_chain_id != chain_id:
            raise ValueError(
                f"{self._archive_section!r} chain_id does not match the live chain"
            )
        self.chain_id = chain_id
        self.created_at = created_at
        self.events = copy.deepcopy(events)
        try:
            self.verify()
        except OsapError as error:
            if error.code == CHAIN_INVALID:
                raise
            raise OsapError(
                CHAIN_INVALID,
                "stored audit chain is invalid",
                details={"reason": error.code, "message": error.message},
            ) from error

    def _restore_archive(self) -> None:
        loaded = self._store.get(self._archive_section)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{self._archive_section!r} must be a JSON object")
        if loaded.get("trace_id") != self.trace_id:
            raise ValueError(
                f"{self._archive_section!r} holds trace "
                f"{loaded.get('trace_id')!r}, not {self.trace_id!r}"
            )
        chain_id = loaded.get("chain_id")
        if not isinstance(chain_id, str) or not chain_id:
            raise ValueError(f"{self._archive_section!r} chain_id must be a string")
        events = loaded.get("events")
        if not isinstance(events, list):
            raise ValueError(f"{self._archive_section!r} events must be a JSON array")
        self._archive_chain_id = chain_id
        self._archived = copy.deepcopy(events)
        try:
            self._verify_archive()
        except OsapError as error:
            if error.code == CHAIN_INVALID:
                raise
            raise OsapError(
                CHAIN_INVALID,
                "stored audit archive is invalid",
                details={"reason": error.code, "message": error.message},
            ) from error

    def _persist(self, *, archive_changed: bool = False) -> None:
        if self._store is None:
            return
        live = {
            "chain_id": self.chain_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "events": copy.deepcopy(self.events),
        }
        if not archive_changed:
            self._store.put(self._section, live)
            return
        self._store.put_many(
            {
                self._section: live,
                self._archive_section: {
                    "chain_id": self.chain_id,
                    "trace_id": self.trace_id,
                    "events": copy.deepcopy(self._archived),
                },
            }
        )

    # --- writing -----------------------------------------------------------

    @property
    def head(self) -> str:
        """The last hash, or the anchor for an empty live chain."""

        return self.events[-1]["hash"] if self.events else self._anchor()

    @property
    def archive_section(self) -> str:
        return self._archive_section

    @property
    def archived_events(self) -> list[dict]:
        """Detached copy of the events moved out of the live chain."""

        return copy.deepcopy(self._archived)

    def _anchor(self) -> str:
        return self._archived[-1]["hash"] if self._archived else GENESIS_HASH

    def __len__(self) -> int:
        return len(self.events)

    def append(self, event: dict) -> dict:
        """Validate, hash, and append one event, then flush it."""

        if not isinstance(event, dict):
            raise ValueError("an audit event must be a JSON object")
        record = copy.deepcopy(event)
        record.setdefault("trace_id", self.trace_id)
        if record["trace_id"] != self.trace_id:
            raise OsapError(
                CHAIN_INVALID,
                "audit event does not belong to this ledger's trace",
                details={"trace_id": record["trace_id"], "ledger_trace_id": self.trace_id},
            )
        record.setdefault("audit_id", f"audit_{secrets.token_hex(8)}")
        record.setdefault("ts", _stamp(self._clock()))
        record["prev_hash"] = self.head
        record.pop("hash", None)
        record["hash"] = _event_hash(record)
        schema.validate(EVENT_SCHEMA, record)
        duplicate = any(
            existing["audit_id"] == record["audit_id"] for existing in self.events
        ) or any(
            existing["audit_id"] == record["audit_id"] for existing in self._archived
        )
        if duplicate:
            raise OsapError(
                CHAIN_INVALID,
                "duplicate audit_id in the chain",
                details={"audit_id": record["audit_id"]},
            )
        self.events.append(record)
        self._persist(archive_changed=self._trim())
        return copy.deepcopy(record)

    def _trim(self) -> bool:
        """Move the oldest events to the archive until `max_events` holds."""

        if self.max_events is None or len(self.events) <= self.max_events:
            return False
        overflow = len(self.events) - self.max_events
        self._archived.extend(self.events[:overflow])
        del self.events[:overflow]
        return True

    # --- verification and export ------------------------------------------

    def verify(self) -> bool:
        """Require schemas, the archive anchor, links, and body hashes."""

        verify_chain(self.chain())
        anchor = self._anchor()
        if self.events and self.events[0]["prev_hash"] != anchor:
            raise OsapError(
                CHAIN_INVALID,
                "audit chain does not link to the archived anchor",
                details={
                    "expected": anchor,
                    "actual": self.events[0]["prev_hash"],
                    "audit_id": self.events[0]["audit_id"],
                },
            )
        self._verify_body_hashes(self.events)
        if self._archived:
            self._verify_archive()
            archived_ids = {event["audit_id"] for event in self._archived}
            for index, event in enumerate(self.events):
                if event["audit_id"] in archived_ids:
                    raise OsapError(
                        CHAIN_INVALID,
                        "duplicate audit_id across the archive",
                        details={"index": index, "audit_id": event["audit_id"]},
                    )
        return True

    def _verify_body_hashes(self, events: list[dict]) -> None:
        for index, event in enumerate(events):
            expected = _event_hash(event)
            if event["hash"] != expected:
                raise OsapError(
                    CHAIN_INVALID,
                    "audit event body does not match its hash",
                    details={
                        "index": index,
                        "audit_id": event["audit_id"],
                        "expected": expected,
                        "actual": event["hash"],
                    },
                )

    def _verify_archive(self) -> None:
        """Require archive schemas, genesis start, links, and body hashes."""

        if not self._archived:
            return
        verify_chain({"trace_id": self.trace_id, "events": self._archived})
        if self._archived[0]["prev_hash"] != GENESIS_HASH:
            raise OsapError(
                CHAIN_INVALID,
                "audit archive does not start at genesis",
                details={
                    "expected": GENESIS_HASH,
                    "actual": self._archived[0]["prev_hash"],
                    "audit_id": self._archived[0]["audit_id"],
                },
            )
        self._verify_body_hashes(self._archived)

    def chain(self) -> dict:
        """Return a detached live-chain object for redaction or export."""

        return {
            "chain_id": self.chain_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "events": copy.deepcopy(self.events),
        }

    def history(self) -> dict:
        """Return the archive plus live events as one chronological chain."""

        return {
            "chain_id": self.chain_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "events": copy.deepcopy(self._archived) + copy.deepcopy(self.events),
        }


def _commitment(salt: str, value: str) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _redact_value(salt: str, value):
    if isinstance(value, list):
        return [_commitment(salt, item) for item in value]
    return _commitment(salt, value)


def redact_chain(chain: dict, *, salt: str | None = None) -> dict:
    """Verify a chain, then replace sensitive fields with salted commitments."""

    verify_chain(chain)
    export_salt = salt or secrets.token_hex(16)
    redacted = copy.deepcopy(chain)
    committed = 0

    for event in redacted["events"]:
        for field in REDACTED_FIELDS:
            if field in event:
                event[field] = _redact_value(export_salt, event[field])
                committed += 1

    return {
        "chain": redacted,
        "export_salt": export_salt,
        "redacted": True,
        "chain_verified": True,
        "plaintext_recoverable": False,
        "redacted_fields": committed,
    }


def recover_effects(events: list) -> dict:
    """Mark an intent without an outcome as unknown and require reconciliation."""

    executed = {
        event.get("intent_ref") for event in events if event["action"] == "effect.executed"
    }
    pending = [
        event["audit_id"]
        for event in events
        if event["action"] == "effect.intent" and event["audit_id"] not in executed
    ]
    return {
        "effect_state": "unknown" if pending else "complete",
        "alerted": bool(pending),
        "pending_intents": pending,
        "requires_reconciliation": bool(pending),
    }


def trace_complete(messages: list) -> dict:
    """Check that a multi-hop trace shares one trace_id and links its hops (§10.6)."""

    trace_ids = {message.get("trace_id") for message in messages}
    missing = [
        message["id"]
        for index, message in enumerate(messages)
        if index > 0 and not message.get("causation_id")
    ]
    return {
        "trace_ids": sorted(trace_id for trace_id in trace_ids if trace_id),
        "single_trace": len(trace_ids) == 1,
        "missing_causation": missing,
        "complete": len(trace_ids) == 1 and not missing,
    }


def authorize_cross_user(
    sender_user: str,
    receiver_user: str,
    *,
    enabled: bool,
    sender_consented: bool = False,
    receiver_consented: bool = False,
) -> dict:
    """Allow cross-user traffic only when it is enabled and both sides consent."""

    if sender_user == receiver_user:
        return {"cross_user": False, "allowed": True}

    if not enabled:
        raise OsapError(
            "POLICY_DENIED",
            "cross-user traffic is disabled for this Bus",
            details={"sender_user": sender_user, "receiver_user": receiver_user},
        )
    if not (sender_consented and receiver_consented):
        raise OsapError(
            "POLICY_CONSENT_REQUIRED",
            "both users must consent before cross-user traffic",
            details={
                "sender_user": sender_user,
                "receiver_user": receiver_user,
                "sender_consented": sender_consented,
                "receiver_consented": receiver_consented,
            },
        )
    return {"cross_user": True, "allowed": True}


def replay_effect(idempotency_key: str, *, repeat: int, replay: bool = True) -> dict:
    """Re-run a request without repeating a side effect when replay is on."""

    if not replay:
        return {
            "side_effects": repeat,
            "idempotent_replay": False,
            "replays": 0,
        }

    index = IdempotencyIndex()
    executed = 0

    def side_effect() -> None:
        nonlocal executed
        executed += 1

    for _ in range(repeat):
        index.execute_once(idempotency_key, side_effect)

    return {
        "side_effects": executed,
        "idempotent_replay": executed == 1,
        "replays": repeat - executed,
    }


def compromised_bus_declaration(
    *, bus_compromised: bool, claims_p0_protection: bool
) -> dict:
    """Report whether a 0.1 claim about a compromised Bus is conforming (§3.6, §11.1)."""

    return {
        "bus_compromised": bus_compromised,
        "claims_p0_protection": claims_p0_protection,
        "p0_protection": False,
        "p1_required": True,
        "conforming": not claims_p0_protection,
    }
