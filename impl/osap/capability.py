# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Capability tokens, attenuation, binding, and revocation (standard.md §5).

Scope is M2.3: issuance bookkeeping, the attenuation rules from §5.3, the
binding checks from §5.4, revocation with cascade, and the consent linkage
required for L3/L4 actions. Token proofs are structurally validated but not
cryptographically verified: issuer key distribution is not part of M2.3.

Revocation is also durable as an append-only journal (`capability.revocations`).
Every `revoke` appends one `{seq, cap_id, ts}` entry per newly revoked token
and writes the journal and the revoked set in one atomic `put_many`. A replica
in another process applies a source's journal with
`apply_revocations(entries, source=...)`: entries are keyed by the source's
own sequence plus a per-source cursor, so distribution is idempotent, a
missing batch fails closed with `REVOCATION_GAP` (a domain extension code
like `AUDIT_CHAIN_INVALID`), and a failed write rolls the replica's memory
back instead of half-applying.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import schema
from .clock import parse_timestamp
from .errors import OsapError
from .store import JsonStore

CAPABILITY_SCHEMA = "capability.schema.json"

ISSUED_SECTION = "capability.issued"
REVOKED_SECTION = "capability.revoked"
REVOCATIONS_SECTION = "capability.revocations"

#: Domain extension code for a revocation journal with a sequence gap.
REVOCATION_GAP = "REVOCATION_GAP"

HIGH_RISK = frozenset({"L3", "L4"})

_RATE = re.compile(r"^(?P<count>\d+)/(?P<period>s|min|hour|day)$")
_PERIOD_MINUTES = {"s": 1 / 60, "min": 1.0, "hour": 60.0, "day": 1440.0}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def rate_per_minute(value: str) -> float | None:
    """Convert `5/min`, `100/hour`, or `1/s` to a per-minute rate."""

    match = _RATE.match(value or "")
    if not match:
        return None
    return int(match["count"]) / _PERIOD_MINUTES[match["period"]]


def _budget_violations(child: dict, parent: dict) -> list[str]:
    violations = []
    child_budget = child.get("max_budget") or {}
    parent_budget = parent.get("max_budget") or {}
    for key in ("wall_ms", "tool_calls", "tokens"):
        if key in parent_budget:
            # Omitting a bounded dimension leaves it unbounded, which widens.
            if key not in child_budget or child_budget[key] > parent_budget[key]:
                violations.append(f"max_budget.{key}")
    if "money" in parent_budget:
        parent_money = parent_budget["money"]
        child_money = child_budget.get("money")
        if child_money is None:
            violations.append("max_budget.money")
        elif child_money.get("currency") != parent_money.get("currency"):
            violations.append("max_budget.money.currency")
        elif child_money.get("amount", 0) > parent_money.get("amount", 0):
            violations.append("max_budget.money")
    return violations


def attenuation_violations(parent: dict, child: dict) -> list[str]:
    """Return every §5.3 rule the requested child breaks."""

    violations: list[str] = []

    if not set(child["actions"]) <= set(parent["actions"]):
        violations.append("actions")
    if not set(child["resources"]) <= set(parent["resources"]):
        violations.append("resources")

    if child["exp"] > parent["exp"]:
        violations.append("exp")
    if child["nbf"] < parent["nbf"]:
        violations.append("nbf")

    parent_limits = parent.get("constraints") or {}
    child_limits = child.get("constraints") or {}

    parent_uses = parent_limits.get("max_uses")
    child_uses = child_limits.get("max_uses")
    if parent_uses is not None and (child_uses is None or child_uses > parent_uses):
        violations.append("constraints.max_uses")

    parent_rate = parent_limits.get("rate")
    child_rate = child_limits.get("rate")
    if parent_rate is not None:
        allowed = rate_per_minute(parent_rate)
        requested = rate_per_minute(child_rate) if child_rate else None
        if requested is None or (allowed is not None and requested > allowed):
            violations.append("constraints.rate")

    violations.extend(_budget_violations(child_limits, parent_limits))

    expected_depth = int(parent.get("depth", 0)) + 1
    if child["depth"] != expected_depth:
        violations.append("depth")
    max_depth = parent_limits.get("max_depth")
    if max_depth is not None and child["depth"] > max_depth:
        violations.append("constraints.max_depth")

    if not parent_limits.get("can_delegate", False):
        violations.append("constraints.can_delegate")

    parent_receipt = parent.get("consent_receipt_id")
    if parent_receipt and child.get("consent_receipt_id") != parent_receipt:
        violations.append("consent_receipt_id")

    return violations


def validate_token(token: dict) -> dict:
    """Validate one capability token against the schema (§5.2)."""

    schema.validate(CAPABILITY_SCHEMA, token)
    return token


def attenuate(parent: dict, requested: dict) -> dict:
    """Return `requested` as a child token, or raise `CAPABILITY_ATTENUATION_INVALID`."""

    schema.validate(CAPABILITY_SCHEMA, parent)
    schema.validate(CAPABILITY_SCHEMA, requested)
    violations = attenuation_violations(parent, requested)
    if violations:
        raise OsapError(
            "CAPABILITY_ATTENUATION_INVALID",
            "child capability widens its parent",
            details={"violations": violations},
        )
    return requested


def _validated_revocation(entry, index: int, *, what: str = REVOCATIONS_SECTION) -> dict:
    """Validate one journal entry; shape errors raise `ValueError`."""

    where = f"{what!r} entry {index}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be a JSON object")
    seq = entry.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ValueError(f"{where} has an invalid seq")
    cap_id = entry.get("cap_id")
    if not isinstance(cap_id, str) or not cap_id:
        raise ValueError(f"{where} has an invalid cap_id")
    ts = entry.get("ts")
    if not isinstance(ts, str) or not ts:
        raise ValueError(f"{where} has an invalid ts")
    try:
        parse_timestamp(ts)
    except OsapError:
        raise ValueError(f"{where} has a malformed ts") from None
    origin = entry.get("origin")
    source_seq = entry.get("source_seq")
    if (origin is None) != (source_seq is None):
        raise ValueError(f"{where} needs origin and source_seq together")
    if origin is not None:
        if not isinstance(origin, str) or not origin:
            raise ValueError(f"{where} has an invalid origin")
        if not isinstance(source_seq, int) or isinstance(source_seq, bool) or source_seq < 1:
            raise ValueError(f"{where} has an invalid source_seq")
    record = {"seq": seq, "cap_id": cap_id, "ts": ts}
    if origin is not None:
        record["origin"] = origin
        record["source_seq"] = source_seq
    return record


class CapabilityAuthority:
    """Issuance, revocation with cascade, and use checks.

    Passing a `JsonStore` persists the issuance log and the revoked set; a new
    authority built over the same store rebuilds the `parent -> children` index
    so revocation still cascades after a restart.
    """

    def __init__(self, *, clock=None, store: JsonStore | None = None) -> None:
        self._clock = clock or _now
        self._store = store
        self.issued: dict[str, dict] = {}
        self.revoked: set[str] = set()
        self.revocations: list[dict] = []
        self.audit: list[dict] = []
        self._sources: dict[str, int] = {}
        self._children: dict[str, set[str]] = {}
        if store is not None:
            self._restore()

    def _restore(self) -> None:
        issued = self._store.get(ISSUED_SECTION)
        if issued is None:
            issued = {}
        if not isinstance(issued, dict):
            raise ValueError(f"{ISSUED_SECTION!r} must be a JSON object")
        revoked = self._store.get(REVOKED_SECTION)
        if revoked is None:
            revoked = []
        if not isinstance(revoked, list):
            raise ValueError(f"{REVOKED_SECTION!r} must be a JSON array")
        journal = self._store.get(REVOCATIONS_SECTION)
        if journal is None:
            journal = []
        if not isinstance(journal, list):
            raise ValueError(f"{REVOCATIONS_SECTION!r} must be a JSON array")
        entries = []
        seen: set[str] = set()
        sources: dict[str, int] = {}
        for index, entry in enumerate(journal):
            record = _validated_revocation(entry, index)
            if record["seq"] != index + 1:
                raise OsapError(
                    REVOCATION_GAP,
                    "revocation journal sequence is not contiguous",
                    details={
                        "index": index,
                        "expected": index + 1,
                        "actual": record["seq"],
                    },
                )
            if record["cap_id"] not in revoked:
                raise ValueError(
                    f"{REVOCATIONS_SECTION!r} entry {index} references a "
                    "cap_id outside the revoked set"
                )
            if record["cap_id"] in seen:
                raise ValueError(
                    f"{REVOCATIONS_SECTION!r} entry {index} repeats cap_id "
                    f"{record['cap_id']!r}"
                )
            seen.add(record["cap_id"])
            if record.get("origin") is not None:
                origin = record["origin"]
                expected = sources.get(origin, 0) + 1
                if record["source_seq"] != expected:
                    raise ValueError(
                        f"{REVOCATIONS_SECTION!r} entry {index} does not "
                        f"continue the {origin!r} source sequence"
                    )
                sources[origin] = record["source_seq"]
            entries.append(record)
        self.issued = issued
        self.revoked = set(revoked)
        self.revocations = entries
        self._sources = sources
        self._children = {}
        for cap_id, token in issued.items():
            parent = token.get("parent_cap_id") if isinstance(token, dict) else None
            if parent is not None:
                self._children.setdefault(parent, set()).add(cap_id)

    def _persist_issued(self) -> None:
        if self._store is not None:
            self._store.put(ISSUED_SECTION, self.issued)

    def _persist_revocations(self, journal_changed: bool = False) -> None:
        if self._store is None:
            return
        updates = {REVOKED_SECTION: sorted(self.revoked)}
        if journal_changed:
            updates[REVOCATIONS_SECTION] = [dict(entry) for entry in self.revocations]
        if len(updates) == 1:
            self._store.put(REVOKED_SECTION, updates[REVOKED_SECTION])
        else:
            self._store.put_many(updates)

    def issue(self, token: dict) -> dict:
        validate_token(token)
        cap_id = token["cap_id"]
        if cap_id in self.revoked:
            raise OsapError(
                "CAPABILITY_REVOKED",
                "a revoked cap_id cannot be issued again",
                details={"cap_id": cap_id},
            )
        parent = token.get("parent_cap_id")
        if parent is not None and parent in self.revoked:
            raise OsapError(
                "CAPABILITY_REVOKED",
                "cannot derive a capability from a revoked parent",
                details={"cap_id": cap_id, "parent_cap_id": parent},
            )
        previous = self.issued.get(cap_id)
        if previous is not None:
            old_parent = previous.get("parent_cap_id")
            if old_parent is not None:
                siblings = self._children.get(old_parent)
                if siblings is not None:
                    siblings.discard(cap_id)
        self.issued[cap_id] = token
        if parent is not None:
            self._children.setdefault(parent, set()).add(cap_id)
        self._persist_issued()
        return token

    def revoke(self, cap_id: str) -> int:
        """Revoke `cap_id` and every descendant; return the number revoked.

        Every newly revoked token is appended to the revocation journal with
        the next sequence number, and the journal and the revoked set are
        flushed in one atomic write so another process can pick the batch up.
        """

        if cap_id in self.revoked:
            return 0
        # Walk the parent -> children index breadth first so a deep chain is
        # visited once per token instead of once per level.
        before_revoked = set(self.revoked)
        before_audit = list(self.audit)
        before_journal = list(self.revocations)
        fresh = self._revoke_local(cap_id)
        if not fresh:
            return 0
        stamp = _stamp(self._clock())
        next_seq = self.last_seq
        journal = list(self.revocations)
        for target in fresh:
            next_seq += 1
            journal.append({"seq": next_seq, "cap_id": target, "ts": stamp})
        self.revocations = journal
        try:
            self._persist_revocations(journal_changed=True)
        except BaseException:
            self.revoked = before_revoked
            self.audit = before_audit
            self.revocations = before_journal
            raise
        return len(fresh)

    @property
    def last_seq(self) -> int:
        """The highest journal sequence this authority has recorded."""

        return self.revocations[-1]["seq"] if self.revocations else 0

    def applied_sources(self) -> dict[str, int]:
        """Per-source cursors: the last source sequence applied per origin."""

        return dict(self._sources)

    def apply_revocations(self, entries, *, source: str) -> dict:
        """Apply a revocation journal batch from one other process.

        `source` names the origin stream, and each entry carries that
        stream's sequence in `seq`. Entries at or below the cursor for
        `source` are already applied and skipped; the first new entry must
        continue the cursor exactly, so a missing batch fails closed with
        `REVOCATION_GAP` instead of silently skipping revocations, and the
        entries inside one batch must be contiguous. Each new entry goes
        through the same cascade as a local `revoke`, is recorded in the
        local journal under the next local sequence with its `origin` and
        `source_seq`, and both sections are persisted in one atomic write.
        A failure rolls the memory state back, so the caller can retry the
        same batch unchanged.
        """

        if not isinstance(source, str) or not source:
            raise ValueError("source must be a non-empty string")
        if not isinstance(entries, list):
            raise ValueError("a revocation batch must be a JSON array")
        cursor = self._sources.get(source, 0)
        pending = []
        for index, entry in enumerate(entries):
            record = _validated_revocation(entry, index, what="revocation batch")
            if record.get("origin") is not None and record["origin"] != source:
                raise ValueError(
                    f"revocation batch entry {index} names origin "
                    f"{record['origin']!r}, not {source!r}"
                )
            if pending and record["seq"] != pending[-1]["seq"] + 1:
                raise ValueError(
                    f"revocation batch entry {index} is not contiguous"
                )
            if record["seq"] <= cursor:
                continue
            if pending or record["seq"] == cursor + 1:
                pending.append(record)
                continue
            raise OsapError(
                REVOCATION_GAP,
                "revocation batch does not continue the applied source sequence",
                details={
                    "source": source,
                    "index": index,
                    "expected": cursor + 1,
                    "actual": record["seq"],
                    "cursor": cursor,
                },
            )
        if not pending:
            return {
                "applied": 0,
                "revoked_now": 0,
                "skipped": len(entries),
                "last_seq": self.last_seq,
                "cursor": cursor,
            }
        before_revoked = set(self.revoked)
        before_audit = list(self.audit)
        before_journal = list(self.revocations)
        before_sources = dict(self._sources)
        revoked_now = 0
        try:
            for record in pending:
                fresh = self._revoke_local(record["cap_id"])
                revoked_now += len(fresh)
                next_seq = self.last_seq + 1
                self.revocations.append(
                    {
                        "seq": next_seq,
                        "cap_id": record["cap_id"],
                        "ts": record["ts"],
                        "origin": source,
                        "source_seq": record["seq"],
                    }
                )
                self._sources[source] = record["seq"]
            self._persist_revocations(journal_changed=True)
        except BaseException:
            self.revoked = before_revoked
            self.audit = before_audit
            self.revocations = before_journal
            self._sources = before_sources
            raise
        return {
            "applied": len(pending),
            "revoked_now": revoked_now,
            "skipped": len(entries) - len(pending),
            "last_seq": self.last_seq,
            "cursor": self._sources[source],
        }

    def _revoke_local(self, cap_id: str) -> list[str]:
        """Revoke in memory only; journaling and persistence are the caller's.

        Returns the cap_ids revoked by this call (the subtree), in walk order.
        """

        if cap_id in self.revoked:
            return []
        queue = [cap_id]
        fresh: list[str] = []
        while queue:
            current = queue.pop()
            if current in self.revoked:
                continue
            self.revoked.add(current)
            self.audit.append({"action": "capability.revoked", "target": current})
            fresh.append(current)
            queue.extend(self._children.get(current, ()))
        return fresh

    def is_revoked(self, token: dict) -> bool:
        cap_id = token.get("cap_id")
        if cap_id in self.revoked:
            return True
        seen = set()
        parent = token.get("parent_cap_id")
        while parent and parent not in seen:
            if parent in self.revoked:
                return True
            seen.add(parent)
            ancestor = self.issued.get(parent)
            parent = ancestor.get("parent_cap_id") if ancestor else None
        return False

    # --- use checks --------------------------------------------------------

    def check_binding(self, token: dict, envelope: dict, *, audience: str) -> None:
        """Stateless binding rules the Bus can check before routing (§5.4)."""

        if token["audience"] != audience:
            raise OsapError(
                "CAPABILITY_AUDIENCE_MISMATCH",
                "capability audience is not the receiving agent",
                details={"audience": token["audience"], "receiver": audience},
            )
        task = envelope.get("task") or {}
        if token["task_id"] != task.get("id"):
            raise OsapError(
                "CAPABILITY_TASK_MISMATCH",
                "capability task does not match the envelope task",
                details={"capability_task": token["task_id"], "envelope_task": task.get("id")},
            )
        if token["subject"] != envelope.get("from"):
            raise OsapError(
                "CAPABILITY_SUBJECT_MISMATCH",
                "capability subject is not the envelope sender",
                details={"subject": token["subject"], "sender": envelope.get("from")},
            )

    def check_validity(self, token: dict, *, now: datetime | None = None) -> None:
        """Temporal and revocation checks the receiver runs before executing."""

        moment = now or self._clock()
        if self.is_revoked(token):
            raise OsapError("CAPABILITY_REVOKED", "capability or an ancestor is revoked")

        not_before = datetime.fromtimestamp(token["nbf"], tz=timezone.utc)
        expires = datetime.fromtimestamp(token["exp"], tz=timezone.utc)
        if moment < not_before:
            raise OsapError("CAPABILITY_REVOKED", "capability is not valid yet")
        if moment >= expires:
            raise OsapError("CAPABILITY_REVOKED", "capability has expired")

        window = (token.get("constraints") or {}).get("time_window")
        if window:
            start, end = (parse_timestamp(item) for item in window)
            if not start <= moment <= end:
                raise OsapError("CAPABILITY_REVOKED", "capability is outside its time window")

    def require_consent(self, token: dict, *, risk: str | None) -> None:
        """L3/L4 actions must reference a consent receipt (§5.2, §5.8)."""

        if risk in HIGH_RISK and not token.get("consent_receipt_id"):
            raise OsapError(
                "POLICY_CONSENT_REQUIRED",
                f"{risk} actions require a consent receipt",
                details={"risk": risk},
            )


class RevocationWatcher:
    """Poll a source store's revocation journal and apply new entries.

    This is the pull-mode subscription on top of the journal: the watcher
    re-reads the source `JsonStore` file on an interval, hands the whole
    journal to the replica's `apply_revocations`, and relies on the
    per-source cursor for idempotence. The file — or whatever populates
    `source_path` — is the transport; there is no push channel and no
    protocol messages. Callers that need lower latency should build a push
    channel and call `apply_revocations` directly with the fetched batch.
    """

    def __init__(
        self,
        source_path,
        replica: "CapabilityAuthority",
        *,
        source: str = "issuer",
        interval: float = 0.05,
    ) -> None:
        if not isinstance(source, str) or not source:
            raise ValueError("source must be a non-empty string")
        if not isinstance(replica, CapabilityAuthority):
            raise ValueError("replica must be a CapabilityAuthority")
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
            raise ValueError("interval must be a positive number")
        self.source_path = Path(source_path)
        self.replica = replica
        self.source = source
        self.interval = float(interval)
        self.last_report: dict | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> dict | None:
        """Read the source journal once and apply it; None when absent.

        A fresh `JsonStore` is opened per poll so external writes by another
        process are always seen; the single-writer rule is never broken
        because the watcher never writes the source file.
        """

        entries = JsonStore(self.source_path).get(REVOCATIONS_SECTION)
        if entries is None:
            return None
        report = self.replica.apply_revocations(entries, source=self.source)
        self.last_report = report
        return report

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("watcher is already running")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll_once()
            except Exception:
                # Distribution failures are retried on the next tick; the
                # replica state never moves on a failed apply.
                continue

    def stop(self, *, timeout: float = 2.0) -> bool:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is None:
            return False
        thread.join(timeout)
        return not thread.is_alive()
