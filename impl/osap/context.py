# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Context fabric subset: handles, labels, blackboard, objects (§9).

The reference implementation is an authorization broker over OS primitives,
not a new file system (§9.9). It covers what the C5 cases exercise:

- resolution needs a `resolve` grant, and long-term memory needs a separate
  `memory.read` grant (§9.2, §9.3);
- expiry is checked, and a handle is never renewed implicitly (§9.3);
- OS permissions are enforced before any grant is considered (§9.9);
- labels only get stricter when an object is derived (§9.4);
- `secret` data does not leave the device without explicit approval (§9.8);
- the blackboard dies with the task and never becomes memory (§9.5);
- deletion of a referenced object tombstones instead of hard-deleting (§9.6);
- cache TTLs are clamped to the handle TTL (§9.7).

Audit events are kept in memory by default. With a `JsonStore` they are also
written to one `context.events` section after every resolution, and a restart
restores the list so "who resolved which handle when" survives the process.
`context.resolve` records the caller, the handle, the label, and the decision,
as §9.2 requires. The same store can hold the handle registry
(`context.handles`), task blackboards (`context.blackboards`), and object
metadata plus tombstones (`context.objects`); each mutation is one atomic
section write, and a reopen validates every record before restoring it. A
handle passed as a string is resolved through the registry, so an
unregistered identifier fails closed with `CONTEXT_NOT_FOUND`.
"""

from __future__ import annotations

import copy
from datetime import timedelta

from .clock import parse_timestamp
from .errors import OsapError
from .store import JsonStore

LABELS = ("public", "personal", "sensitive", "secret")
LABEL_RANK = {label: rank for rank, label in enumerate(LABELS)}

#: Labels that may not leave the device without explicit user approval (§9.4, §9.8).
EGRESS_GUARDED = frozenset({"sensitive", "secret"})

MEMORY_PREFIX = "ctx://user/memory"
MEMORY_ACTION = "memory.read"
RESOLVE_ACTION = "resolve"

#: Storage duties a `managed_store` declaration must cover (§9.10).
STORAGE_DUTIES = (
    "quota",
    "garbage_collection",
    "crash_recovery",
    "encryption",
    "path_safety",
    "deletion",
)

#: Section a persistent fabric writes its resolution events to.
EVENTS_SECTION = "context.events"
#: Section a persistent fabric writes the handle registry to.
HANDLES_SECTION = "context.handles"
#: Section a persistent fabric writes open and closed task blackboards to.
BLACKBOARDS_SECTION = "context.blackboards"
#: Section a persistent fabric writes object metadata and tombstones to.
OBJECTS_SECTION = "context.objects"
DECISIONS = frozenset({"allow", "deny"})

#: State that must never be promoted to long-term memory (§3.7, §9.3, §9.5).
NON_MEMORY_SOURCES = frozenset(
    {"idempotency_index", "audit_log", "task_tree", "blackboard", "object_metadata"}
)


def label_rank(label: str) -> int:
    """Return the strictness rank of a label, lower is looser."""

    try:
        return LABEL_RANK[label]
    except KeyError:
        raise OsapError("SCHEMA_INVALID", f"unknown information-flow label: {label!r}") from None


def stricter_label(*labels: str | None) -> str | None:
    """Return the strictest label of the arguments, ignoring None."""

    present = [label for label in labels if label]
    if not present:
        return None
    return max(present, key=label_rank)


def is_memory_handle(handle: dict) -> bool:
    """True for a long-term memory handle, which needs its own grant (§9.3)."""

    name = handle.get("handle", "")
    return name.startswith(MEMORY_PREFIX) or (
        handle.get("scope") == "user" and MEMORY_PREFIX in name
    )


def required_action(handle: dict) -> str:
    """Return the action a capability must grant before this handle resolves."""

    return MEMORY_ACTION if is_memory_handle(handle) else RESOLVE_ACTION


def expiry_of(handle: dict):
    """Return the absolute expiry, from `expires_at` or `created_at + ttl`."""

    if handle.get("expires_at"):
        return parse_timestamp(handle["expires_at"])
    if handle.get("ttl") is not None and handle.get("created_at"):
        return parse_timestamp(handle["created_at"]) + timedelta(seconds=int(handle["ttl"]))
    return None


def label_violation(handle: dict, source_labels: dict) -> dict:
    """Report whether a derived object lowered its information-flow label (§9.4)."""

    declared = handle.get("label")
    sources = handle.get("derived_from") or []
    present = [source_labels[source] for source in sources if source in source_labels]
    inherited = stricter_label(*present)
    effective = stricter_label(declared, inherited)
    lowered = (
        declared is not None
        and inherited is not None
        and label_rank(declared) < label_rank(inherited)
    )
    return {
        "declared_label": declared,
        "inherited_label": inherited,
        "effective_label": effective,
        "lowered": lowered,
        "conforming": not lowered,
    }


class ContextFabric:
    """CF that resolves handles, owns task blackboards, and records events.

    A `JsonStore` makes the four context sections durable: resolution events,
    the handle registry, task blackboards, and object metadata. Every public
    mutation rewrites only the section it changes, and a reopen validates each
    record before restoring it. `limit` optionally keeps only the newest
    events, which is a retention floor rather than an archive; the in-memory
    list follows the same rule so memory and disk cannot drift. Blackboards
    are cleared when their task ends and are never promoted to memory.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        section: str = EVENTS_SECTION,
        limit: int | None = None,
    ) -> None:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer")
        self._store = store
        self._section = section
        self.limit = limit
        self.audit: list[dict] = []
        self._handles: dict[str, dict] = {}
        self._blackboards: dict[str, dict] = {}
        self._objects: dict[str, dict] = {}
        if store is not None:
            self._restore()

    # --- persistence ------------------------------------------------------

    def _restore(self) -> None:
        loaded = self._store.get(self._section)
        if loaded is not None:
            if not isinstance(loaded, list):
                raise ValueError(f"{self._section!r} must be a JSON array")
            events = [self._restore_event(index, item) for index, item in enumerate(loaded)]
            self.audit = self._clamp(events)
        self._restore_handles()
        self._restore_blackboards()
        self._restore_objects()

    def _restore_handles(self) -> None:
        loaded = self._store.get(HANDLES_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{HANDLES_SECTION!r} must be a JSON object")
        handles: dict[str, dict] = {}
        for identifier, record in loaded.items():
            where = f"context handle {identifier!r}"
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("context handle keys must be non-empty strings")
            handle = self._validated_handle(record, where)
            if handle["handle"] != identifier:
                raise ValueError(f"{where} must match its registry key")
            handles[identifier] = handle
        self._handles = handles

    def _restore_blackboards(self) -> None:
        loaded = self._store.get(BLACKBOARDS_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{BLACKBOARDS_SECTION!r} must be a JSON object")
        boards: dict[str, dict] = {}
        for task_id, record in loaded.items():
            where = f"context blackboard {task_id!r}"
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("context blackboard keys must be non-empty strings")
            board = self._validated_blackboard(record, where)
            if board["task_id"] != task_id:
                raise ValueError(f"{where} must match its registry key")
            boards[task_id] = board
        self._blackboards = boards

    def _restore_objects(self) -> None:
        loaded = self._store.get(OBJECTS_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{OBJECTS_SECTION!r} must be a JSON object")
        objects: dict[str, dict] = {}
        for uri, record in loaded.items():
            where = f"context object {uri!r}"
            if not isinstance(uri, str) or not uri:
                raise ValueError("context object keys must be non-empty strings")
            state = self._validated_object(record, where)
            if state["uri"] != uri:
                raise ValueError(f"{where} must match its registry key")
            objects[uri] = state
        self._objects = objects

    def _restore_event(self, index: int, event) -> dict:
        where = f"context event {index}"
        if not isinstance(event, dict):
            raise ValueError(f"{where} must be a JSON object")
        if event.get("action") != "context.resolve":
            raise ValueError(f"{where} has an unknown action")
        if event.get("decision") not in DECISIONS:
            raise ValueError(f"{where} has an unknown decision")
        if not isinstance(event.get("handle"), str) or not event["handle"]:
            raise ValueError(f"{where} needs a handle")
        if not isinstance(event.get("reason"), str) or not event["reason"]:
            raise ValueError(f"{where} needs a reason")
        for field in ("agent", "label"):
            if event.get(field) is not None and not isinstance(event[field], str):
                raise ValueError(f"{where} has a non-string {field}")
        return {
            "action": event["action"],
            "handle": event["handle"],
            "agent": event.get("agent"),
            "label": event.get("label"),
            "decision": event["decision"],
            "reason": event["reason"],
        }

    def _clamp(self, events: list[dict]) -> list[dict]:
        if self.limit is None:
            return events
        if self.limit == 0:
            return []
        return events[-self.limit :]

    def _persist(self) -> None:
        if self._store is not None:
            self._store.put(self._section, [dict(event) for event in self.audit])

    def _write(self, section: str, value) -> None:
        if self._store is not None:
            self._store.put(section, copy.deepcopy(value))

    @staticmethod
    def _validated_handle(record, where: str) -> dict:
        if not isinstance(record, dict):
            raise ValueError(f"{where} must be a JSON object")
        identifier = record.get("handle")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{where} needs a non-empty 'handle'")
        for field in ("scheme", "scope", "audience"):
            value = record.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{where} has a non-string {field}")
        for field in ("created_at", "expires_at"):
            value = record.get(field)
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"{where} has an invalid {field}")
                try:
                    parse_timestamp(value)
                except OsapError:
                    raise ValueError(f"{where} has a malformed {field}") from None
        label = record.get("label")
        if label is not None and label not in LABELS:
            raise ValueError(f"{where} has an unknown label {label!r}")
        ttl = record.get("ttl")
        if ttl is not None and (
            not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 0
        ):
            raise ValueError(f"{where} has an invalid ttl")
        derived = record.get("derived_from")
        if derived is not None and (
            not isinstance(derived, list)
            or any(not isinstance(item, str) for item in derived)
        ):
            raise ValueError(f"{where} has an invalid derived_from")
        constraints = record.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            raise ValueError(f"{where} has an invalid constraints")
        return copy.deepcopy(record)

    @staticmethod
    def _validated_blackboard(record, where: str) -> dict:
        if not isinstance(record, dict):
            raise ValueError(f"{where} must be a JSON object")
        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"{where} needs a non-empty 'task_id'")
        board_name = record.get("blackboard")
        if board_name is not None and not isinstance(board_name, str):
            raise ValueError(f"{where} has a non-string blackboard")
        entries = record.get("entries")
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) for entry in entries
        ):
            raise ValueError(f"{where} needs an entries array of objects")
        closed = record.get("closed", False)
        if not isinstance(closed, bool):
            raise ValueError(f"{where} has a non-boolean closed")
        archived = record.get("entries_archived", 0)
        if not isinstance(archived, int) or isinstance(archived, bool) or archived < 0:
            raise ValueError(f"{where} has an invalid entries_archived")
        promoted = record.get("promoted_to_memory", False)
        if not isinstance(promoted, bool):
            raise ValueError(f"{where} has a non-boolean promoted_to_memory")
        if closed and entries:
            raise ValueError(f"{where} is closed but still has entries")
        if closed and promoted:
            raise ValueError(f"{where} must not promote a closed blackboard to memory")
        state = {
            "task_id": task_id,
            "blackboard": board_name if board_name is not None else task_id,
            "entries": copy.deepcopy(entries),
            "closed": closed,
            "entries_archived": archived,
            "promoted_to_memory": promoted,
        }
        for field in ("version", "ttl"):
            value = record.get(field)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{where} has an invalid {field}")
            state[field] = value
        for field in ("created_at", "expires_at", "updated_at"):
            value = record.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise ValueError(f"{where} has an invalid {field}")
            try:
                parse_timestamp(value)
            except OsapError:
                raise ValueError(f"{where} has a malformed {field}") from None
            state[field] = value
        return state

    @staticmethod
    def _validated_object(record, where: str) -> dict:
        if not isinstance(record, dict):
            raise ValueError(f"{where} must be a JSON object")
        uri = record.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ValueError(f"{where} needs a non-empty 'uri'")
        count = record.get("reference_count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"{where} has an invalid reference_count")
        deleted = record.get("deleted", False)
        tombstoned = record.get("tombstoned", False)
        if not isinstance(deleted, bool) or not isinstance(tombstoned, bool):
            raise ValueError(f"{where} has a non-boolean deleted/tombstoned")
        if deleted and tombstoned:
            raise ValueError(f"{where} cannot be both deleted and tombstoned")
        if deleted and count:
            raise ValueError(f"{where} cannot be deleted while referenced")
        label = record.get("label")
        if label is not None and label not in LABELS:
            raise ValueError(f"{where} has an unknown label {label!r}")
        metadata = record.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError(f"{where} has invalid metadata")
        state = {
            "uri": uri,
            "reference_count": count,
            "deleted": deleted,
            "tombstoned": tombstoned,
        }
        if label is not None:
            state["label"] = label
        if metadata is not None:
            state["metadata"] = copy.deepcopy(metadata)
        return state

    def _event(self, handle: dict, agent: str | None, decision: str, reason: str) -> dict:
        identifier = handle.get("handle")
        if not isinstance(identifier, str) or not identifier:
            # Every persisted event must be restorable, so refuse a handle
            # without an identifier before it reaches the store.
            raise ValueError("a context event needs a non-empty handle")
        event = {
            "action": "context.resolve",
            "handle": identifier,
            "agent": agent,
            "label": handle.get("label"),
            "decision": decision,
            "reason": reason,
        }
        self.audit.append(event)
        self.audit = self._clamp(self.audit)
        self._persist()
        return event

    def _deny(self, handle: dict, agent: str | None, reason: str, **details) -> None:
        self._event(handle, agent, "deny", reason)
        raise OsapError(
            "CONTEXT_DENIED",
            f"context handle cannot be resolved: {reason}",
            details={"handle": handle.get("handle"), "reason": reason, **details},
        )

    def resolve(
        self,
        handle: dict | str,
        *,
        agent: str | None,
        granted_actions: list[str],
        now,
        os_permission: str = "granted",
        egress: bool = False,
        user_approval: bool = False,
    ) -> dict:
        """Resolve one handle or raise `CONTEXT_DENIED`/`CONTEXT_EXPIRED` (§9.2).

        A string is looked up in the handle registry; an unknown identifier is
        audited as a denial and raises `CONTEXT_NOT_FOUND`. A dict keeps the
        original behaviour, so a caller that already holds a handle does not
        have to register it first.
        """

        if isinstance(handle, str):
            identifier = handle
            if not identifier:
                raise ValueError("handle identifier must be a non-empty string")
            stored = self._handles.get(identifier)
            if stored is None:
                self._event(
                    {"handle": identifier, "label": None},
                    agent,
                    "deny",
                    "not_found",
                )
                raise OsapError(
                    "CONTEXT_NOT_FOUND",
                    "context handle is not registered",
                    details={"handle": identifier, "reason": "not_found"},
                )
            handle = stored
        elif not isinstance(handle, dict):
            raise ValueError("handle must be a context handle object or identifier")

        decision, failure = self._authorize(
            handle,
            agent=agent,
            now=now,
            os_permission=os_permission,
            granted_actions=granted_actions,
            egress=egress,
            user_approval=user_approval,
        )
        if decision == "deny":
            reason = failure["reason"]
            if reason == "expired":
                self._event(handle, agent, "deny", "expired")
                raise OsapError(
                    "CONTEXT_EXPIRED",
                    "context handle has expired and is not renewed automatically",
                    details={"handle": handle.get("handle"), "expires_at": handle.get("expires_at")},
                )
            if reason == "egress_requires_approval":
                self._event(handle, agent, "deny", "egress_requires_approval")
                raise OsapError(
                    "POLICY_CONSENT_REQUIRED",
                    f"{handle.get('label')} data may not leave the device without explicit approval",
                    details={"handle": handle.get("handle"), "label": handle.get("label")},
                )
            self._deny(handle, agent, reason, **(failure.get("details") or {}))

        self._event(handle, agent, "allow", "resolved")
        return {
            "handle": handle.get("handle"),
            "scheme": handle.get("scheme"),
            "scope": handle.get("scope"),
            "label": handle.get("label"),
            "expires_at": handle.get("expires_at"),
        }

    def authorize_refs(
        self,
        *,
        agent: str | None,
        refs: list[str],
        now,
        os_permission: str = "granted",
        granted_actions: list[str] | None = None,
        user_approval: bool = False,
    ) -> dict:
        """Check §7.1 refs ownership: the sender must be able to pass each ref.

        Registered handles go through exactly the §9.2 check sequence a
        `resolve` would run (audience, `allowed_agents`, OS permission, the
        `resolve` grant, expiry), each decision audited with the same reason
        vocabulary. Unregistered refs — `obj://` digests and other opaque
        handles — have no ownership model yet and are reported as
        `unmodeled`; they pass, and the limitation is declared in
        impl/README and the roadmap 0.2 freeze table.

        Returns `{ref: {"decision": "allow"|"deny"|"unmodeled", "reason": …}}`.
        The caller (typically the sending path in `Bus`) fails closed with
        `CONTEXT_DENIED` on any `deny`.
        """

        actions = list(granted_actions) if granted_actions is not None else ["resolve"]
        verdicts: dict[str, dict] = {}
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                raise ValueError("each ref must be a non-empty string")
            record = self._handles.get(ref)
            if record is None:
                verdicts[ref] = {"decision": "unmodeled", "reason": "not_registered"}
                continue
            decision, failure = self._authorize(
                record,
                agent=agent,
                now=now,
                os_permission=os_permission,
                granted_actions=actions,
                egress=False,
                user_approval=user_approval,
            )
            if decision == "deny":
                reason = failure["reason"]
                self._event(record, agent, "deny", reason)
                verdicts[ref] = {"decision": "deny", "reason": reason}
            else:
                self._event(record, agent, "allow", "refs_check")
                verdicts[ref] = {"decision": "allow", "reason": "refs_check"}
        return verdicts

    def _authorize(
        self,
        handle: dict,
        *,
        agent: str | None,
        now,
        os_permission: str,
        granted_actions: list[str],
        egress: bool,
        user_approval: bool,
    ) -> tuple[str, dict | None]:
        """Run the §9.2 check sequence; return ("allow", None) or ("deny", failure).

        Identity and OS checks come first so a caller that cannot use the
        handle learns nothing about its expiry state (§9.2). The failure
        carries the audit reason plus the details the caller needs to raise
        the right error code (`expired` → `CONTEXT_EXPIRED`,
        `egress_requires_approval` → `POLICY_CONSENT_REQUIRED`, everything
        else → `CONTEXT_DENIED` via `_deny`).
        """

        audience = handle.get("audience")
        if audience is not None and agent != audience:
            return "deny", {"reason": "audience"}
        allowed = (handle.get("constraints") or {}).get("allowed_agents")
        if allowed and agent not in allowed:
            return "deny", {"reason": "agent_not_allowed"}

        # The OS permission is the outer boundary: a handle never widens it (§9.9).
        if os_permission == "denied":
            return "deny", {"reason": "os_permission"}

        needed = required_action(handle)
        if needed not in granted_actions:
            return "deny", {
                "reason": "missing_grant",
                "details": {
                    "required_action": needed,
                    "granted_actions": list(granted_actions),
                },
            }

        expires_at = expiry_of(handle)
        if expires_at is not None and expires_at <= now:
            return "deny", {"reason": "expired"}

        label = handle.get("label")
        if egress and label in EGRESS_GUARDED and not user_approval:
            return "deny", {"reason": "egress_requires_approval"}

        return "allow", None

    # --- handle registry --------------------------------------------------

    def register_handle(self, handle: dict) -> dict:
        """Register a handle so it can be resolved by identifier after restart.

        Registration is idempotent for an identical body and rejects a second,
        different body: silently overwriting a live handle would change what a
        capability is allowed to resolve.
        """

        record = self._validated_handle(handle, "context handle")
        identifier = record["handle"]
        existing = self._handles.get(identifier)
        if existing is not None:
            if existing != record:
                raise ValueError(
                    f"context handle {identifier!r} is already registered "
                    "with a different body"
                )
            return copy.deepcopy(existing)
        self._handles[identifier] = record
        self._write(HANDLES_SECTION, self._handles)
        return copy.deepcopy(record)

    def handle(self, identifier: str) -> dict | None:
        """Return a registered handle, or None when it is unknown."""

        if not isinstance(identifier, str) or not identifier:
            raise ValueError("handle identifier must be a non-empty string")
        record = self._handles.get(identifier)
        return copy.deepcopy(record) if record is not None else None

    def drop_handle(self, identifier: str) -> bool:
        """Remove a handle from the registry; return whether it existed."""

        if not isinstance(identifier, str) or not identifier:
            raise ValueError("handle identifier must be a non-empty string")
        if identifier not in self._handles:
            return False
        del self._handles[identifier]
        self._write(HANDLES_SECTION, self._handles)
        return True

    # --- task blackboards -------------------------------------------------

    def open_blackboard(
        self,
        task_id: str,
        *,
        board: dict | None = None,
        entries: list | None = None,
    ) -> dict:
        """Open (or return) the blackboard for a running task (§9.5).

        `board` may carry the fields from an existing blackboard object (name,
        version, TTL, timestamps); `entries` is a shortcut for an empty board
        with the given entries. Passing both is rejected.
        """

        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be a non-empty string")
        if board is not None and entries is not None:
            raise ValueError("pass either board or entries, not both")
        record = copy.deepcopy(board) if board is not None else {}
        if not isinstance(record, dict):
            raise ValueError("blackboard must be a JSON object")
        record.setdefault("task_id", task_id)
        if record["task_id"] != task_id:
            raise ValueError("blackboard task_id must match the registry key")
        record.setdefault("blackboard", task_id)
        record.setdefault("entries", copy.deepcopy(list(entries or [])))
        record.setdefault("closed", False)
        record.setdefault("entries_archived", 0)
        record.setdefault("promoted_to_memory", False)
        record = self._validated_blackboard(
            record, f"context blackboard {task_id!r}"
        )
        existing = self._blackboards.get(task_id)
        if existing is not None:
            if existing["closed"]:
                raise ValueError(f"context blackboard {task_id!r} is closed")
            if existing != record:
                raise ValueError(
                    f"context blackboard {task_id!r} is already open "
                    "with different entries"
                )
            return copy.deepcopy(existing)
        self._blackboards[task_id] = record
        self._write(BLACKBOARDS_SECTION, self._blackboards)
        return copy.deepcopy(record)

    def blackboard(self, task_id: str) -> dict | None:
        """Return a blackboard, open or closed, or None when unknown."""

        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be a non-empty string")
        record = self._blackboards.get(task_id)
        return copy.deepcopy(record) if record is not None else None

    def write_blackboard(self, task_id: str, entries: list) -> dict:
        """Replace the entries of an open blackboard and persist them."""

        record = self._blackboards.get(task_id)
        if record is None:
            raise OsapError(
                "CONTEXT_NOT_FOUND",
                "context blackboard is not open",
                details={"task_id": task_id, "reason": "not_found"},
            )
        if record["closed"]:
            raise ValueError(f"context blackboard {task_id!r} is closed")
        updated = self._validated_blackboard(
            {**copy.deepcopy(record), "entries": copy.deepcopy(entries)},
            f"context blackboard {task_id!r}",
        )
        if updated == record:
            return copy.deepcopy(record)
        self._blackboards[task_id] = updated
        self._write(BLACKBOARDS_SECTION, self._blackboards)
        return copy.deepcopy(updated)

    def close_blackboard(self, task_id: str, *, task_ended: bool = True) -> dict:
        """Close a blackboard, clear its entries, and never promote it (§9.5).

        Closing is idempotent: a second call returns the recorded summary and
        does not write again.
        """

        record = self._blackboards.get(task_id)
        if record is None:
            raise OsapError(
                "CONTEXT_NOT_FOUND",
                "context blackboard is not open",
                details={"task_id": task_id, "reason": "not_found"},
            )
        if record["closed"]:
            return {
                "task_id": task_id,
                "blackboard": record["blackboard"],
                "task_ended": task_ended,
                "cleared_or_archived": True,
                "entries_archived": record["entries_archived"],
                "promoted_to_memory": False,
                "closed": True,
            }
        report = _close_blackboard_report(
            {"blackboard": record["blackboard"], "entries": record["entries"]},
            task_ended=task_ended,
        )
        closed = self._validated_blackboard(
            {
                "task_id": task_id,
                "blackboard": record["blackboard"],
                "entries": [],
                "closed": True,
                "entries_archived": report["entries_archived"],
                "promoted_to_memory": False,
            },
            f"context blackboard {task_id!r}",
        )
        self._blackboards[task_id] = closed
        self._write(BLACKBOARDS_SECTION, self._blackboards)
        return {**report, "task_id": task_id, "closed": True}

    # --- object metadata and tombstones -----------------------------------

    def register_object(
        self,
        uri: str,
        *,
        label: str | None = None,
        reference_count: int = 0,
        metadata: dict | None = None,
    ) -> dict:
        """Record object metadata, including a label and reference count (§9.6)."""

        record = {
            "uri": uri,
            "reference_count": reference_count,
            "deleted": False,
            "tombstoned": False,
        }
        if label is not None:
            record["label"] = label
        if metadata is not None:
            record["metadata"] = metadata
        state = self._validated_object(record, f"context object {uri!r}")
        existing = self._objects.get(uri)
        if existing is not None:
            if existing != state:
                raise ValueError(
                    f"context object {uri!r} is already registered "
                    "with a different body"
                )
            return copy.deepcopy(existing)
        self._objects[uri] = state
        self._write(OBJECTS_SECTION, self._objects)
        return copy.deepcopy(state)

    def object_state(self, uri: str) -> dict | None:
        """Return object metadata, including deletion and tombstone flags."""

        if not isinstance(uri, str) or not uri:
            raise ValueError("object uri must be a non-empty string")
        state = self._objects.get(uri)
        return copy.deepcopy(state) if state is not None else None

    def retain_object(self, uri: str) -> dict:
        """Increment an object's reference count and persist it."""

        state = self._objects.get(uri)
        if state is None or state["deleted"]:
            raise OsapError(
                "CONTEXT_NOT_FOUND",
                "context object is not registered",
                details={"object": uri, "reason": "not_found"},
            )
        updated = copy.deepcopy(state)
        updated["reference_count"] += 1
        self._objects[uri] = updated
        self._write(OBJECTS_SECTION, self._objects)
        return copy.deepcopy(updated)

    def release_object(self, uri: str) -> dict:
        """Decrement an object's reference count without auto-deleting it."""

        state = self._objects.get(uri)
        if state is None or state["deleted"]:
            raise OsapError(
                "CONTEXT_NOT_FOUND",
                "context object is not registered",
                details={"object": uri, "reason": "not_found"},
            )
        updated = copy.deepcopy(state)
        updated["reference_count"] = max(0, updated["reference_count"] - 1)
        if updated == state:
            return copy.deepcopy(state)
        self._objects[uri] = updated
        self._write(OBJECTS_SECTION, self._objects)
        return copy.deepcopy(updated)

    def delete_object(self, uri: str, *, hard_delete: bool = False) -> dict:
        """Delete or tombstone an object using its stored reference count (§9.6)."""

        state = self._objects.get(uri)
        if state is None or state["deleted"]:
            raise OsapError(
                "CONTEXT_NOT_FOUND",
                "context object is not registered",
                details={"object": uri, "reason": "not_found"},
            )
        report = _delete_object_report(
            uri,
            reference_count=state["reference_count"],
            hard_delete=hard_delete,
        )
        if report["deleted"] or report["tombstoned"]:
            updated = copy.deepcopy(state)
            updated["deleted"] = report["deleted"]
            updated["tombstoned"] = report["tombstoned"]
            self._objects[uri] = self._validated_object(
                updated, f"context object {uri!r}"
            )
            self._write(OBJECTS_SECTION, self._objects)
        return {**report, "uri": uri}


def close_blackboard(board: dict, *, task_ended: bool) -> dict:
    """Archive a task blackboard when its task ends; never promote it (§9.5)."""

    return {
        "blackboard": board.get("blackboard"),
        "task_ended": task_ended,
        "cleared_or_archived": True,
        "entries_archived": len(board.get("entries") or []),
        "promoted_to_memory": False,
    }


def delete_object(uri: str, *, reference_count: int, hard_delete: bool) -> dict:
    """Check references before deleting, and refuse to hard-delete a referenced object (§9.6)."""

    if reference_count > 0 and hard_delete:
        return {
            "object": uri,
            "references_checked": True,
            "reference_count": reference_count,
            "audit_written": True,
            "deleted": False,
            "tombstoned": False,
            "conforming": False,
            "reason": "referenced objects must be tombstoned, not hard-deleted",
        }
    deleted = reference_count == 0
    return {
        "object": uri,
        "references_checked": True,
        "reference_count": reference_count,
        "audit_written": True,
        "deleted": deleted,
        "tombstoned": not deleted,
        "conforming": True,
    }


# The ContextFabric methods of the same name call these pure helpers through
# module aliases so a method name cannot shadow the helper it wraps.
_close_blackboard_report = close_blackboard
_delete_object_report = delete_object


def cache_window(handle: dict, *, requested_ttl: int, elapsed_seconds: int) -> dict:
    """Clamp a cache TTL to the handle TTL and report whether the entry is still valid (§9.7)."""

    handle_ttl = handle.get("ttl")
    effective = int(requested_ttl)
    if handle_ttl is not None:
        effective = min(effective, int(handle_ttl))
    return {
        "requested_ttl": int(requested_ttl),
        "handle_ttl": handle_ttl,
        "effective_ttl": effective,
        "clamped": effective < int(requested_ttl),
        "cache_hit": elapsed_seconds < effective,
    }


def storage_declaration(cf_mode: str, declares: dict) -> dict:
    """Report the duties a storage declaration still owes (§9.10)."""

    if cf_mode != "managed_store":
        return {
            "cf_mode": cf_mode,
            "declares_managed_store": False,
            "missing": [],
            "conforming": True,
        }
    missing = [duty for duty in STORAGE_DUTIES if not declares.get(duty)]
    return {
        "cf_mode": cf_mode,
        "declares_managed_store": True,
        "missing": missing,
        "conforming": not missing,
    }


def memory_promotions(sources: list[str]) -> dict:
    """Report which queried sources must not become long-term memory (§3.7, §9.3)."""

    promoted = [source for source in sources if source in NON_MEMORY_SOURCES]
    return {
        "sources": list(sources),
        "promoted_to_memory": promoted,
        "conforming": not promoted,
    }
