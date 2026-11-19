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

`AuditJournal` adds two things a single-trace ledger cannot provide. It
partitions chains by user under `audit.user.<user>.*`, so one user's history is
never opened together with another's, and it keeps one cross-trace order index
in `audit.order.<user>`. Each append writes the trace chain and the next order
entry in one atomic `put_many`, so the global order can never miss an event
that was persisted. Sequence numbers start at 1 and stay contiguous; a reopen
rejects a gap, a duplicate, or an order entry that does not match the chain.

`AUDIT_CHAIN_INVALID` is a domain extension: §10.5 requires verification to
fail but defines no audit-specific standard code.
"""

from __future__ import annotations

import copy
import hashlib
import secrets
from datetime import datetime, timezone

from . import crypto, schema
from .clock import parse_timestamp
from .errors import OsapError
from .idempotency import IdempotencyIndex
from .store import JsonStore

EVENT_SCHEMA = "audit-event.schema.json"
CHAIN_INVALID = "AUDIT_CHAIN_INVALID"

#: Prefix of the per-trace section a persisted ledger writes.
LEDGER_SECTION_PREFIX = "audit.chain."

#: Prefix of the per-trace section a trimming ledger archives into.
ARCHIVE_SECTION_PREFIX = "audit.archive."

#: Prefix of a per-user partition written by `AuditJournal`.
USER_PARTITION_PREFIX = "audit.user."

#: Prefix of the per-user cross-trace order index.
ORDER_SECTION_PREFIX = "audit.order."

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

    def _persist(self, *, archive_changed: bool = False, extra: dict | None = None) -> None:
        if self._store is None:
            return
        live = {
            "chain_id": self.chain_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "events": copy.deepcopy(self.events),
        }
        updates = {self._section: live}
        if archive_changed:
            updates[self._archive_section] = {
                "chain_id": self.chain_id,
                "trace_id": self.trace_id,
                "events": copy.deepcopy(self._archived),
            }
        if extra:
            if not isinstance(extra, dict):
                raise ValueError("extra sections must be a JSON object")
            updates.update(copy.deepcopy(extra))
        if len(updates) == 1:
            self._store.put(self._section, live)
        else:
            self._store.put_many(updates)

    # --- writing -----------------------------------------------------------

    @property
    def store(self):
        """The backing `JsonStore`, or None for an in-memory ledger."""

        return self._store

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

    def append(self, event: dict, *, companion=None) -> dict:
        """Validate, hash, and append one event, then flush it.

        `companion`, when given, is called with the finalized record and must
        return extra `{section: value}` entries. They are flushed in the same
        atomic write as the chain, which is how `AuditJournal` and
        `TaskBoard.recover()` keep their sections consistent with the event.
        The callback must not mutate caller-visible state until `append`
        returns, because a failed write rolls the ledger back.
        """

        before_events = list(self.events)
        before_archived = list(self._archived)
        record = self._stage(event)
        try:
            trimmed = self._trim()
            extra = companion(record) if companion is not None else None
            self._persist(archive_changed=trimmed, extra=extra)
        except BaseException:
            self.events = before_events
            self._archived = before_archived
            raise
        return copy.deepcopy(record)

    def append_many(self, events, *, companion=None) -> list[dict]:
        """Validate, hash, and append several events, then flush once.

        The whole batch shares one atomic write, so `TaskBoard.recover()` can
        put the recovered task tree, the effect journal, and the audit chain
        into the same store flush. `companion` is called with the last
        finalized record and returns extra `{section: value}` entries merged
        into that write. A failure — including a duplicate `audit_id` late in
        the batch — rolls every staged event back, so the caller can retry
        the whole batch unchanged.
        """

        if not isinstance(events, list):
            raise ValueError("events must be a list")
        if not events:
            return []
        before_events = list(self.events)
        before_archived = list(self._archived)
        records = []
        try:
            for event in events:
                records.append(self._stage(event))
            trimmed = self._trim()
            extra = (
                companion(records[-1])
                if companion is not None and records
                else None
            )
            self._persist(archive_changed=trimmed, extra=extra)
        except BaseException:
            self.events = before_events
            self._archived = before_archived
            raise
        return [copy.deepcopy(record) for record in records]

    def _stage(self, event) -> dict:
        """Validate, hash, and append one event to memory without persisting."""

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
        return record

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


class AuditJournal:
    """A per-user audit partition with one cross-trace order index (§10.5).

    Every trace keeps its own hash chain under
    `audit.user.<user_id>.chain.<trace_id>` and an optional archive under
    `audit.user.<user_id>.archive.<trace_id>`. `append` also adds the next
    sequence entry to `audit.order.<user_id>` and writes the chain, archive,
    and order index in one atomic `put_many`, so a crash cannot leave an event
    that the global order does not know about.

    Sequence numbers start at 1 and are contiguous. A reopen rejects a gap, a
    duplicate `audit_id`, an order entry whose timestamp does not match the
    chain event, or a chain event that has no order entry. A journal stores one
    `user://` partition only; authorization for a cross-user read is still the
    caller's responsibility through `authorize_cross_user`. Journals for
    different users must share one `JsonStore` instance per path, because two
    live stores over one file would overwrite each other's partitions.
    """

    def __init__(
        self,
        *,
        user_id: str,
        store: JsonStore | None = None,
        clock=None,
        max_events: int | None = None,
    ) -> None:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id must be a non-empty string")
        if max_events is not None and (
            not isinstance(max_events, int)
            or isinstance(max_events, bool)
            or max_events < 1
        ):
            raise ValueError("max_events must be a positive integer")
        self.user_id = user_id
        self.max_events = max_events
        self._clock = clock or _now
        self._store = store
        self._order: list[dict] = []
        self._next_seq = 1
        self._ledgers: dict[str, AuditLedger] = {}
        if store is not None:
            self._restore()

    # --- section naming ----------------------------------------------------

    @property
    def order_section(self) -> str:
        return f"{ORDER_SECTION_PREFIX}{self.user_id}"

    def chain_section(self, trace_id: str) -> str:
        return f"{USER_PARTITION_PREFIX}{self.user_id}.chain.{trace_id}"

    def archive_section(self, trace_id: str) -> str:
        return f"{USER_PARTITION_PREFIX}{self.user_id}.archive.{trace_id}"

    # --- restore -----------------------------------------------------------

    def _restore(self) -> None:
        self._restore_order()
        self._restore_ledgers()
        self._check_order_matches()

    def _restore_order(self) -> None:
        loaded = self._store.get(self.order_section)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.order_section!r} must be a JSON object")
        if loaded.get("user_id") != self.user_id:
            raise ValueError(
                f"{self.order_section!r} holds user {loaded.get('user_id')!r}, "
                f"not {self.user_id!r}"
            )
        entries = loaded.get("entries")
        if not isinstance(entries, list):
            raise ValueError(f"{self.order_section!r} entries must be a JSON array")
        order: list[dict] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{self.order_section!r} entry {index} must be a JSON object"
                )
            seq = entry.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool):
                raise ValueError(
                    f"{self.order_section!r} entry {index} has an invalid seq"
                )
            if seq != index + 1:
                raise OsapError(
                    CHAIN_INVALID,
                    "audit order sequence is not contiguous",
                    details={"index": index, "expected": index + 1, "actual": seq},
                )
            for field in ("trace_id", "audit_id", "ts"):
                value = entry.get(field)
                if not isinstance(value, str) or not value:
                    raise ValueError(
                        f"{self.order_section!r} entry {index} has an invalid {field}"
                    )
            try:
                parse_timestamp(entry["ts"])
            except OsapError:
                raise ValueError(
                    f"{self.order_section!r} entry {index} has a malformed ts"
                ) from None
            if entry["audit_id"] in seen:
                raise OsapError(
                    CHAIN_INVALID,
                    "duplicate audit_id in the audit order",
                    details={"index": index, "audit_id": entry["audit_id"]},
                )
            seen.add(entry["audit_id"])
            order.append(
                {
                    "seq": seq,
                    "trace_id": entry["trace_id"],
                    "audit_id": entry["audit_id"],
                    "ts": entry["ts"],
                }
            )
        self._order = order
        self._next_seq = len(order) + 1

    def _restore_ledgers(self) -> None:
        prefix = f"{USER_PARTITION_PREFIX}{self.user_id}.chain."
        for section in self._store.sections():
            if not section.startswith(prefix):
                continue
            trace_id = section[len(prefix) :]
            if not trace_id:
                raise ValueError(f"{section!r} has no trace identifier")
            self._ledgers[trace_id] = AuditLedger(
                trace_id=trace_id,
                store=self._store,
                clock=self._clock,
                section=section,
                max_events=self.max_events,
                archive_section=self.archive_section(trace_id),
            )

    def _check_order_matches(self) -> None:
        events: dict[tuple[str, str], dict] = {}
        for trace_id, ledger in self._ledgers.items():
            for event in ledger.history()["events"]:
                key = (trace_id, event["audit_id"])
                if key in events:
                    raise OsapError(
                        CHAIN_INVALID,
                        "duplicate audit_id across journal traces",
                        details={"trace_id": trace_id, "audit_id": event["audit_id"]},
                    )
                events[key] = event
        ordered = {
            (entry["trace_id"], entry["audit_id"]): entry for entry in self._order
        }
        missing = sorted(set(events) - set(ordered))
        orphaned = sorted(set(ordered) - set(events))
        if missing or orphaned:
            raise OsapError(
                CHAIN_INVALID,
                "audit order does not match the stored chains",
                details={
                    "unordered_events": [list(item) for item in missing],
                    "orphaned_entries": [list(item) for item in orphaned],
                },
            )
        for key, entry in ordered.items():
            if events[key]["ts"] != entry["ts"]:
                raise OsapError(
                    CHAIN_INVALID,
                    "audit order timestamp does not match the chain event",
                    details={
                        "trace_id": key[0],
                        "audit_id": key[1],
                        "expected": events[key]["ts"],
                        "actual": entry["ts"],
                    },
                )
        if self._next_seq != len(self._order) + 1:
            raise OsapError(
                CHAIN_INVALID,
                "audit order next sequence is inconsistent",
                details={
                    "expected": len(self._order) + 1,
                    "actual": self._next_seq,
                },
            )

    # --- writing -----------------------------------------------------------

    def trace(self, trace_id: str) -> AuditLedger:
        """Return (and lazily create) the ledger for one trace."""

        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("trace_id must be a non-empty string")
        ledger = self._ledgers.get(trace_id)
        if ledger is None:
            ledger = AuditLedger(
                trace_id=trace_id,
                store=self._store,
                clock=self._clock,
                section=self.chain_section(trace_id),
                max_events=self.max_events,
                archive_section=self.archive_section(trace_id),
            )
            self._ledgers[trace_id] = ledger
        return ledger

    def traces(self) -> list[str]:
        """Trace identifiers currently held by this user partition."""

        return sorted(self._ledgers)

    def append(self, trace_id: str, event: dict) -> dict:
        """Append one event and its global order entry in one atomic write."""

        ledger = self.trace(trace_id)
        if not isinstance(event, dict):
            raise ValueError("an audit event must be a JSON object")
        record = copy.deepcopy(event)
        record.setdefault("trace_id", trace_id)
        if record["trace_id"] != trace_id:
            raise OsapError(
                CHAIN_INVALID,
                "audit event does not belong to this trace",
                details={"trace_id": record["trace_id"], "journal_trace_id": trace_id},
            )
        record.setdefault("audit_id", f"audit_{secrets.token_hex(8)}")
        record.setdefault("ts", _stamp(self._clock()))
        try:
            parse_timestamp(record["ts"])
        except OsapError:
            raise ValueError("audit order timestamp must be RFC 3339") from None
        if any(entry["audit_id"] == record["audit_id"] for entry in self._order):
            raise OsapError(
                CHAIN_INVALID,
                "duplicate audit_id in the audit order",
                details={"audit_id": record["audit_id"]},
            )

        seq = self._next_seq
        entry = {
            "seq": seq,
            "trace_id": trace_id,
            "audit_id": record["audit_id"],
            "ts": record["ts"],
        }
        proposed = self._order + [entry]

        def companion(_record: dict) -> dict:
            return {
                self.order_section: {
                    "user_id": self.user_id,
                    "entries": copy.deepcopy(proposed),
                }
            }

        saved = ledger.append(record, companion=companion)
        self._order = proposed
        self._next_seq = seq + 1
        return saved

    # --- inspection --------------------------------------------------------

    def order(self) -> list[dict]:
        """Detached copy of the cross-trace order, oldest first."""

        return copy.deepcopy(self._order)

    def verify(self) -> bool:
        """Verify every trace chain and the cross-trace order index."""

        for ledger in self._ledgers.values():
            ledger.verify()
        self._check_order_matches()
        return True


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
