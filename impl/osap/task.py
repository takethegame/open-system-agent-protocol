# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Task tree, budgets, cancellation, results, and handoff (§8).

Scope is M2.5. The Bus keeps an in-memory task index:

- delegation creates a child node whose budget fits inside the parent
  remainder (§8.3, §8.5, §8.6);
- cancellation walks the tree downwards and skips detached children (§8.7);
- results are accepted only from the assignee and only with the declared
  `result_schema` (§8.8);
- handoff transfers ownership without creating a node, and a rejected or
  expired handoff leaves the task untouched (§8.9).

Two error codes carry the budget rules. Delegating a budget larger than the
parent's remainder is a policy refusal (`POLICY_DENIED`): the standard defines
no delegation-specific code. Exceeding a budget while executing is
`TASK_BUDGET_EXCEEDED` (§8.6).

Passing a `JsonStore` to `TaskBoard` persists the whole tree, including
`consumed` counters, parent links, and the detached flag. Canonical state is
written once at the end of each mutating public method, so a crash sees either
the previous tree or the new one, never a half-applied transition.

The board also keeps an effect journal (`task.effects`) for §8.11. An
irreversible side effect records an intent before it runs and an outcome
afterwards; `recover()` fails every non-terminal task and marks every
intent-only effect `unknown`. With a `max_effects` limit the oldest resolved
effects move into `task.effects.archive`, still in one atomic write;
intent-only effects are never archived, so the replay gate keeps its teeth.

`recover(ledger=...)` closes the last gap: with an `AuditLedger` that shares
the board's `JsonStore`, the recovered tree, the effect journal, and the
audit chain land in one atomic `put_many`. A failure rolls the statuses, the
journal, and the staged audit events back, so the restart can be retried.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import schema
from .audit import AuditLedger
from .capability import HIGH_RISK
from .errors import OsapError
from .store import JsonStore

TASK_SCHEMA = "task.schema.json"
DELEGATE_SCHEMA = "delegate.schema.json"
HANDOFF_SCHEMA = "handoff.schema.json"
TASKS_SECTION = "task.tasks"
EFFECTS_SECTION = "task.effects"
EFFECT_ARCHIVE_SECTION = "task.effects.archive"

STATUSES = (
    "created",
    "accepted",
    "running",
    "waiting_consent",
    "succeeded",
    "failed",
    "cancelled",
    "rejected",
)

#: States from which a task never moves again (§8.10).
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "rejected"})

#: §8.11 effect states tracked by the board's journal.
EFFECT_STATUSES = ("pending", "executed", "unknown", "reconciled")

#: Reconciliation outcomes accepted by `reconcile_effect()`.
RECONCILED_OUTCOMES = ("executed", "not_executed")

#: Actor recorded on recovery events emitted by the Bus.
RECOVERY_ACTOR = "system://osap/bus"

#: Legal transitions of the state machine in §8.10.
TRANSITIONS = {
    "created": frozenset({"accepted", "rejected", "cancelled"}),
    "accepted": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"waiting_consent", "succeeded", "failed", "cancelled"}),
    "waiting_consent": frozenset({"running", "cancelled", "failed"}),
}

BUDGET_DIMENSIONS = ("wall_ms", "tool_calls", "tokens")


def check_budget(budget: dict, consumed: dict) -> None:
    """Raise `TASK_BUDGET_EXCEEDED` when `consumed` exceeds `budget` (§8.6)."""

    for dimension in BUDGET_DIMENSIONS:
        if dimension not in budget:
            continue
        used = consumed.get(dimension, 0)
        if used > budget[dimension]:
            raise OsapError(
                "TASK_BUDGET_EXCEEDED",
                f"{dimension} budget exceeded",
                details={
                    "dimension": dimension,
                    "budget": budget[dimension],
                    "consumed": used,
                },
            )

    if "money" in budget:
        limit = budget["money"]
        spent = consumed.get("money") or {}
        if spent:
            if spent.get("currency") != limit.get("currency"):
                raise OsapError(
                    "TASK_BUDGET_EXCEEDED",
                    "money budget currency mismatch",
                    details={"budget": limit, "consumed": spent},
                )
            if spent.get("amount", 0) > limit.get("amount", 0):
                raise OsapError(
                    "TASK_BUDGET_EXCEEDED",
                    "money budget exceeded",
                    details={"dimension": "money", "budget": limit, "consumed": spent},
                )


def remaining_budget(budget: dict, consumed: dict | None = None) -> dict:
    """Return the budget left in each dimension."""

    consumed = consumed or {}
    left: dict = {}
    for dimension in BUDGET_DIMENSIONS:
        if dimension in budget:
            left[dimension] = max(budget[dimension] - consumed.get(dimension, 0), 0)
    if "money" in budget:
        limit = budget["money"]
        spent = consumed.get("money") or {}
        left["money"] = {
            "currency": limit.get("currency"),
            "amount": max(limit.get("amount", 0) - spent.get("amount", 0), 0),
        }
    if "depth" in budget:
        left["depth"] = budget["depth"]
    return left


@dataclass
class Task:
    """One node of the task tree (§8.1)."""

    task_id: str
    root_task_id: str
    mode: str
    owner: str
    assignee: str
    budget: dict = field(default_factory=dict)
    status: str = "created"
    parent_task_id: str | None = None
    session_id: str | None = None
    result_schema: str | None = None
    authority: dict = field(default_factory=dict)
    consumed: dict = field(default_factory=dict)
    detached: bool = False

    @classmethod
    def from_document(cls, document: dict) -> "Task":
        """Build a task from a validated `task.schema.json` fixture."""

        schema.validate(TASK_SCHEMA, document)
        return cls(
            task_id=document["task_id"],
            root_task_id=document["root_task_id"],
            mode=document["mode"],
            owner=document["owner"],
            assignee=document["assignee"],
            budget=dict(document["budget"]),
            status=document["status"],
            parent_task_id=document.get("parent_task_id"),
            session_id=document.get("session_id"),
            result_schema=document.get("result_schema"),
            authority=dict(document.get("authority") or {}),
            detached=bool(document.get("detached", False)),
        )

    @classmethod
    def from_message(cls, message: dict) -> "Task":
        """Project a task from an envelope that carries no task record yet.

        Used by the handoff path, where the sender is the owner by definition.
        """

        task = message.get("task") or {}
        return cls(
            task_id=task["id"],
            root_task_id=task.get("root") or task["id"],
            mode=task.get("mode", "supervisor"),
            owner=message["from"],
            assignee=(message["body"].get("data") or {}).get("new_owner", message["from"]),
            parent_task_id=task.get("parent"),
            session_id=message.get("session_id"),
        )

    def snapshot(self) -> dict:
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "assignee": self.assignee,
            "status": self.status,
            "budget": dict(self.budget),
            "authority": dict(self.authority),
        }

    def to_state(self) -> dict:
        """A lossless record for durable storage, unlike `snapshot()`."""

        return {
            "task_id": self.task_id,
            "root_task_id": self.root_task_id,
            "mode": self.mode,
            "owner": self.owner,
            "assignee": self.assignee,
            "budget": dict(self.budget),
            "status": self.status,
            "parent_task_id": self.parent_task_id,
            "session_id": self.session_id,
            "result_schema": self.result_schema,
            "authority": dict(self.authority),
            "consumed": dict(self.consumed),
            "detached": self.detached,
        }

    @classmethod
    def from_state(cls, state: dict) -> "Task":
        """Rebuild a task from `to_state()` output, rejecting bad records.

        Stored records are stricter than `task.schema.json`: the board can hold
        tasks built from envelopes rather than fixtures, and `consumed` is not
        part of the wire schema. Structural checks here keep a corrupt section
        from silently becoming a half-restored tree.
        """

        if not isinstance(state, dict):
            raise ValueError("a stored task must be a JSON object")
        for key in ("task_id", "root_task_id", "mode", "owner", "assignee"):
            if not isinstance(state.get(key), str) or not state[key]:
                raise ValueError(f"stored task needs a non-empty {key}")
        status = state.get("status")
        if status not in STATUSES:
            raise ValueError(f"stored task has an unknown status: {status!r}")
        budget = state.get("budget")
        if not isinstance(budget, dict):
            raise ValueError("stored task budget must be a JSON object")
        authority = state.get("authority", {})
        consumed = state.get("consumed", {})
        if not isinstance(authority, dict):
            raise ValueError("stored task authority must be a JSON object")
        if not isinstance(consumed, dict):
            raise ValueError("stored task consumed must be a JSON object")
        detached = state.get("detached", False)
        if not isinstance(detached, bool):
            raise ValueError("stored task detached must be a boolean")
        for key in ("parent_task_id", "session_id", "result_schema"):
            if state.get(key) is not None and not isinstance(state[key], str):
                raise ValueError(f"stored task {key} must be a string or null")
        return cls(
            task_id=state["task_id"],
            root_task_id=state["root_task_id"],
            mode=state["mode"],
            owner=state["owner"],
            assignee=state["assignee"],
            budget=dict(budget),
            status=status,
            parent_task_id=state.get("parent_task_id"),
            session_id=state.get("session_id"),
            result_schema=state.get("result_schema"),
            authority=dict(authority),
            consumed=dict(consumed),
            detached=detached,
        )


class TaskBoard:
    """Task tree with delegation, cancel, result, handoff, and recovery.

    An optional `JsonStore` makes the tree survive a restart. The board writes
    the canonical `task.tasks` section once per mutating public method; the
    in-memory `audit` list is not persisted, matching the other subsystems.
    The effect journal lives in `task.effects`, and `recover()` writes both
    sections through one `put_many`.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        ledger: AuditLedger | None = None,
        max_effects: int | None = None,
    ) -> None:
        if max_effects is not None and (
            not isinstance(max_effects, int)
            or isinstance(max_effects, bool)
            or max_effects < 1
        ):
            raise ValueError("max_effects must be a positive integer")
        if ledger is not None:
            if not isinstance(ledger, AuditLedger):
                raise ValueError("ledger must be an AuditLedger")
            if store is None:
                raise ValueError("a ledger requires a store to share")
            if ledger.store is not store:
                raise ValueError("the ledger must share the task board's store")
        self.tasks: dict[str, Task] = {}
        self.effects: dict[str, dict] = {}
        self._archived_effects: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.max_effects = max_effects
        self._ledger = ledger
        self._store = store
        if store is not None:
            self._restore()

    # --- persistence -------------------------------------------------------

    def _restore(self) -> None:
        self._restore_tasks()
        self._restore_effects()
        self._restore_effect_archive()

    def _restore_tasks(self) -> None:
        loaded = self._store.get(TASKS_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{TASKS_SECTION!r} must be a JSON object")
        tasks: dict[str, Task] = {}
        for task_id, state in loaded.items():
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("stored task ids must be non-empty strings")
            record = Task.from_state(state)
            if record.task_id != task_id:
                raise ValueError(
                    f"stored task {task_id!r} carries task_id {record.task_id!r}"
                )
            tasks[task_id] = record
        self.tasks = tasks

    def _restore_effects(self) -> None:
        loaded = self._store.get(EFFECTS_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{EFFECTS_SECTION!r} must be a JSON object")
        effects: dict[str, dict] = {}
        for intent_ref, state in loaded.items():
            effects[intent_ref] = self._effect_state(intent_ref, state)
        self.effects = effects

    def _restore_effect_archive(self) -> None:
        loaded = self._store.get(EFFECT_ARCHIVE_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{EFFECT_ARCHIVE_SECTION!r} must be a JSON object")
        archived: dict[str, dict] = {}
        for intent_ref, state in loaded.items():
            archived[intent_ref] = self._effect_state(intent_ref, state)
        self._archived_effects = archived

    def _effect_state(self, intent_ref: str, state) -> dict:
        """Validate one stored effect record shared by live and archived."""

        if not isinstance(intent_ref, str) or not intent_ref:
            raise ValueError("stored effect refs must be non-empty strings")
        if not isinstance(state, dict):
            raise ValueError("a stored effect must be a JSON object")
        stored_ref = state.get("intent_ref")
        if stored_ref != intent_ref:
            raise ValueError(
                f"stored effect {intent_ref!r} carries intent_ref {stored_ref!r}"
            )
        for key in ("task_id", "target"):
            if not isinstance(state.get(key), str) or not state[key]:
                raise ValueError(f"stored effect needs a non-empty {key}")
        if state["task_id"] not in self.tasks:
            raise ValueError(
                f"stored effect {intent_ref!r} references an unknown task"
            )
        status = state.get("status")
        if status not in EFFECT_STATUSES:
            raise ValueError(f"stored effect has an unknown status: {status!r}")
        outcome = state.get("reconciled_outcome")
        if status == "reconciled":
            if outcome not in RECONCILED_OUTCOMES:
                raise ValueError(
                    f"stored effect has an invalid reconciled outcome: {outcome!r}"
                )
        elif outcome is not None:
            raise ValueError(
                "stored effect has a reconciled outcome but is not reconciled"
            )
        key = state.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or not key):
            raise ValueError("stored effect idempotency_key must be a non-empty string")
        return copy.deepcopy(state)

    def _persist(self) -> None:
        if self._store is None:
            return
        self._store.put(
            TASKS_SECTION,
            {task_id: record.to_state() for task_id, record in self.tasks.items()},
        )

    def _persist_effects(self, *, archive_changed: bool = False) -> None:
        if self._store is None:
            return
        live = copy.deepcopy(self.effects)
        if archive_changed:
            self._store.put_many(
                {
                    EFFECTS_SECTION: live,
                    EFFECT_ARCHIVE_SECTION: copy.deepcopy(self._archived_effects),
                }
            )
        else:
            self._store.put(EFFECTS_SECTION, live)

    def _commit_effects(self) -> None:
        """Trim the journal if needed, then flush one atomic write."""

        archive_changed = self._trim_effects()
        self._persist_effects(archive_changed=archive_changed)

    def _trim_effects(self) -> bool:
        """Move the oldest resolved effects to the archive (§8.11 retention).

        Pending and unknown effects stay live no matter how far over the
        limit the journal is: archiving them would lift the replay gate and
        let a restart repeat a side effect.
        """

        if self.max_effects is None:
            return False
        overflow = len(self.effects) - self.max_effects
        if overflow <= 0:
            return False
        movable = [
            intent_ref
            for intent_ref, effect in self.effects.items()
            if effect["status"] in ("executed", "reconciled")
        ]
        if not movable:
            return False
        for intent_ref in movable[:overflow]:
            self._archived_effects[intent_ref] = self.effects.pop(intent_ref)
        return True

    def archived_effects(self) -> dict[str, dict]:
        """Detached copy of the effect journal's archive."""

        return copy.deepcopy(self._archived_effects)

    def _persist_recovery(self) -> None:
        """Flush the recovered tree and journal in one atomic store write."""

        if self._store is None:
            return
        self._store.put_many(
            {
                TASKS_SECTION: {
                    task_id: record.to_state() for task_id, record in self.tasks.items()
                },
                EFFECTS_SECTION: copy.deepcopy(self.effects),
            }
        )

    # --- index -------------------------------------------------------------

    def add(self, task: Task) -> Task:
        self._insert(task)
        self._persist()
        return task

    def _insert(self, task: Task) -> Task:
        self.tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def require(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task is None:
            raise OsapError("ROUTING_NOT_FOUND", f"unknown task: {task_id}")
        return task

    def children(self, task_id: str) -> list[Task]:
        return [task for task in self.tasks.values() if task.parent_task_id == task_id]

    # --- state machine -----------------------------------------------------

    def transition(self, task: Task, status: str) -> Task:
        """Apply one legal state transition, or refuse it (§8.10)."""

        if self._apply_transition(task, status):
            self._persist()
        return task

    def _apply_transition(self, task: Task, status: str) -> bool:
        if status not in STATUSES:
            raise OsapError("SCHEMA_INVALID", f"unknown task status: {status!r}")
        if status == task.status:
            return False
        if status not in TRANSITIONS.get(task.status, frozenset()):
            raise OsapError(
                "POLICY_DENIED",
                f"illegal task transition: {task.status} -> {status}",
                details={"from": task.status, "to": status},
            )
        self.audit.append(
            {"action": "task.status", "task_id": task.task_id, "from": task.status, "to": status}
        )
        task.status = status
        return True

    # --- cancellation ------------------------------------------------------

    def cancel(self, task_id: str) -> list[str]:
        """Cancel `task_id` and every non-detached descendant; return the ids."""

        root = self.require(task_id)
        cancelled: list[str] = []
        stack = [root]
        while stack:
            task = stack.pop()
            if task.detached:
                # Detached children keep running but lose the parent's authority (§8.7).
                continue
            if task.status not in TERMINAL:
                self._apply_transition(task, "cancelled")
                cancelled.append(task.task_id)
            stack.extend(self.children(task.task_id))
        if cancelled:
            self._persist()
        return cancelled

    # --- delegation --------------------------------------------------------

    def delegate(self, parent_id: str, message: dict) -> Task:
        """Create a child task from a `delegate` envelope (§8.5)."""

        data = message["body"]["data"]
        schema.validate(DELEGATE_SCHEMA, data)

        parent = self.require(parent_id)
        task = message.get("task") or {}
        if task.get("parent") != parent.task_id:
            raise OsapError(
                "POLICY_DENIED",
                "delegate task.parent is not the delegating task",
                details={"parent": parent.task_id, "message_parent": task.get("parent")},
            )
        if task["id"] in self.tasks:
            raise OsapError("DUPLICATE", f"task already exists: {task['id']}")

        requested = data["budget"]
        left = remaining_budget(parent.budget, parent.consumed)
        for dimension in BUDGET_DIMENSIONS:
            if dimension not in requested or dimension not in left:
                continue
            if requested[dimension] > left[dimension]:
                raise OsapError(
                    "POLICY_DENIED",
                    f"delegated {dimension} exceeds the parent remainder",
                    details={
                        "dimension": dimension,
                        "requested": requested[dimension],
                        "remaining": left[dimension],
                    },
                )
        if "depth" in requested and "depth" in parent.budget:
            if requested["depth"] != parent.budget["depth"] + 1:
                raise OsapError(
                    "POLICY_DENIED",
                    "delegated depth must be the parent depth plus one",
                    details={"requested": requested["depth"], "parent": parent.budget["depth"]},
                )

        child = Task(
            task_id=task["id"],
            root_task_id=task.get("root") or parent.root_task_id,
            mode=task.get("mode", parent.mode),
            owner=message["from"],
            assignee=(message.get("to") or {}).get("agent", parent.assignee),
            budget=dict(requested),
            status="created",
            parent_task_id=parent.task_id,
            session_id=message.get("session_id"),
            result_schema=data["result_schema"],
            authority={"cap_id": data["delegated_capability"]["cap_id"]},
        )
        self._insert(child)
        self.audit.append(
            {
                "action": "task.delegated",
                "task_id": child.task_id,
                "parent": parent.task_id,
            }
        )
        self._persist()
        return child

    # --- results -----------------------------------------------------------

    def accept_result(self, message: dict) -> Task:
        """Validate and apply a `result` message (§8.8)."""

        task = self.require(message["task"]["id"])
        if task.assignee != message["from"]:
            raise OsapError(
                "POLICY_DENIED",
                "only the assignee may return a result",
                details={"assignee": task.assignee, "sender": message["from"]},
            )
        claimed = message["body"]["schema"]
        if task.result_schema and claimed != task.result_schema:
            raise OsapError(
                "SCHEMA_INVALID",
                "result schema does not match the task contract",
                details={"expected": task.result_schema, "claimed": claimed},
            )
        status = (message.get("task") or {}).get("status")
        if status:
            self.transition(task, status)
        return task

    # --- handoff -----------------------------------------------------------

    def handoff(
        self,
        task: Task,
        message: dict,
        *,
        risk: str | None = None,
        renewed_consent: bool = False,
        accepted: bool = True,
    ) -> str:
        """Transfer ownership, or record a rejection without touching the task (§8.9)."""

        data = message["body"]["data"]
        schema.validate(HANDOFF_SCHEMA, data)

        if task.owner != message["from"]:
            raise OsapError(
                "POLICY_DENIED",
                "only the current owner may hand off a task",
                details={"owner": task.owner, "sender": message["from"]},
            )

        capability = data["delegated_capability"]
        new_owner = data["new_owner"]
        if data["task_id"] != task.task_id or capability["task_id"] != task.task_id:
            raise OsapError(
                "CAPABILITY_TASK_MISMATCH",
                "handoff capability is bound to a different task",
                details={"task_id": task.task_id},
            )
        if capability["audience"] != new_owner:
            raise OsapError(
                "CAPABILITY_AUDIENCE_MISMATCH",
                "handoff capability audience is not the new owner",
                details={"audience": capability["audience"], "new_owner": new_owner},
            )
        if capability["subject"] != new_owner:
            raise OsapError(
                "CAPABILITY_SUBJECT_MISMATCH",
                "handoff capability subject is not the new owner",
                details={"subject": capability["subject"], "new_owner": new_owner},
            )

        if risk in HIGH_RISK and (not renewed_consent or not capability.get("consent_receipt_id")):
            raise OsapError(
                "POLICY_CONSENT_REQUIRED",
                f"{risk} handoff requires a fresh consent receipt for the new owner",
                details={"risk": risk, "new_owner": new_owner},
            )

        if not accepted:
            self.audit.append(
                {
                    "action": "task.handoff",
                    "task_id": task.task_id,
                    "result": "rejected",
                    "owner": task.owner,
                }
            )
            return "rejected"

        previous = task.owner
        task.owner = new_owner
        task.assignee = new_owner
        task.authority = {"cap_id": capability["cap_id"]}
        self.audit.append(
            {
                "action": "task.handoff",
                "task_id": task.task_id,
                "result": "accepted",
                "from": previous,
                "to": new_owner,
                "cap_id": capability["cap_id"],
            }
        )
        self._persist()
        return "accepted"

    # --- effect journal and restart recovery -------------------------------

    def record_effect_intent(
        self,
        task_id: str,
        *,
        intent_ref: str,
        target: str,
        idempotency_key: str | None = None,
    ) -> dict:
        """Persist an `effect.intent` before an irreversible side effect (§8.11)."""

        record = self.require(task_id)
        if record.status in TERMINAL:
            raise OsapError(
                "POLICY_DENIED",
                "a terminal task cannot start a side effect",
                details={"task_id": task_id, "status": record.status},
            )
        if not isinstance(intent_ref, str) or not intent_ref:
            raise ValueError("intent_ref must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty string")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not idempotency_key
        ):
            raise ValueError("idempotency_key must be a non-empty string")
        if intent_ref in self.effects:
            raise OsapError(
                "DUPLICATE",
                f"effect intent already exists: {intent_ref}",
                details={"intent_ref": intent_ref},
            )
        before_effects = copy.deepcopy(self.effects)
        before_archived = copy.deepcopy(self._archived_effects)
        effect = {
            "intent_ref": intent_ref,
            "task_id": task_id,
            "target": target,
            "status": "pending",
        }
        if idempotency_key is not None:
            effect["idempotency_key"] = idempotency_key
        try:
            self.effects[intent_ref] = effect
            self.audit.append(
                {
                    "action": "effect.intent",
                    "task_id": task_id,
                    "intent_ref": intent_ref,
                    "target": target,
                }
            )
            self._commit_effects()
        except BaseException:
            self.effects = before_effects
            self._archived_effects = before_archived
            raise
        return copy.deepcopy(effect)

    def record_effect_outcome(self, intent_ref: str) -> dict:
        """Record `effect.executed`; an already-executed intent is idempotent."""

        effect = self._effect(intent_ref)
        if effect["status"] == "executed":
            return copy.deepcopy(effect)
        if effect["status"] != "pending":
            raise OsapError(
                "POLICY_DENIED",
                "an effect with an unknown outcome must be reconciled first",
                details={"intent_ref": intent_ref, "reason": "reconciliation_required"},
            )
        before_effects = copy.deepcopy(self.effects)
        before_archived = copy.deepcopy(self._archived_effects)
        try:
            effect["status"] = "executed"
            self.audit.append(
                {
                    "action": "effect.executed",
                    "task_id": effect["task_id"],
                    "intent_ref": intent_ref,
                    "target": effect["target"],
                }
            )
            self._commit_effects()
        except BaseException:
            self.effects = before_effects
            self._archived_effects = before_archived
            raise
        return copy.deepcopy(effect)

    def reconcile_effect(self, intent_ref: str, *, outcome: str) -> dict:
        """Write a reconciliation result back to an `unknown` effect (§8.11)."""

        if outcome not in RECONCILED_OUTCOMES:
            raise ValueError(f"reconciliation outcome must be one of {RECONCILED_OUTCOMES}")
        effect = self._effect(intent_ref)
        if effect["status"] != "unknown":
            raise OsapError(
                "POLICY_DENIED",
                "only an unknown effect can be reconciled",
                details={"intent_ref": intent_ref, "status": effect["status"]},
            )
        before_effects = copy.deepcopy(self.effects)
        before_archived = copy.deepcopy(self._archived_effects)
        try:
            effect["status"] = "reconciled"
            effect["reconciled_outcome"] = outcome
            self.audit.append(
                {
                    "action": "effect.reconciled",
                    "task_id": effect["task_id"],
                    "intent_ref": intent_ref,
                    "target": effect["target"],
                    "outcome": outcome,
                }
            )
            self._commit_effects()
        except BaseException:
            self.effects = before_effects
            self._archived_effects = before_archived
            raise
        return copy.deepcopy(effect)

    def require_replay_allowed(self, intent_ref: str) -> dict:
        """Refuse a replay while the effect outcome is still unknown."""

        effect = self._effect(intent_ref)
        status = effect["status"]
        if status in ("pending", "unknown"):
            raise OsapError(
                "POLICY_DENIED",
                "effect outcome is unknown; reconcile before replay",
                details={"intent_ref": intent_ref, "reason": "reconciliation_required"},
            )
        if status == "reconciled" and effect["reconciled_outcome"] == "executed":
            raise OsapError(
                "POLICY_DENIED",
                "reconciliation confirmed the effect; replay would duplicate it",
                details={"intent_ref": intent_ref, "reason": "already_executed"},
            )
        return copy.deepcopy(effect)

    def recover(self, *, policy: str = "fail") -> dict:
        """Recover after a Bus restart (§3.7, §8.10, §8.11).

        Every non-terminal task becomes `failed`, or returns to `created` when
        `policy="reschedule"`. Every intent-only effect becomes `unknown` and
        is reported for reconciliation. Both sections are written atomically;
        with a shared `AuditLedger` the recovered tree, the effect journal,
        and the audit chain land in one store flush. A failure rolls the
        statuses, the journal, and the staged audit events back, so the
        restart can be retried unchanged.
        """

        if policy not in ("fail", "reschedule"):
            raise ValueError("policy must be 'fail' or 'reschedule'")
        before_statuses = {
            task_id: record.status for task_id, record in self.tasks.items()
        }
        before_effects = copy.deepcopy(self.effects)
        before_audit = len(self.audit)
        recovered, task_events = self._recover_tasks(policy)
        effects_changed, effect_events = self._recover_effects()
        events = task_events + effect_events
        try:
            if self._ledger is not None:
                if events:
                    self._ledger.append_many(
                        copy.deepcopy(events),
                        companion=lambda record: {
                            TASKS_SECTION: {
                                task_id: record_state.to_state()
                                for task_id, record_state in self.tasks.items()
                            },
                            EFFECTS_SECTION: copy.deepcopy(self.effects),
                        },
                    )
            elif recovered or effects_changed:
                self._persist_recovery()
        except BaseException:
            for task_id, status in before_statuses.items():
                self.tasks[task_id].status = status
            self.effects = before_effects
            del self.audit[before_audit:]
            raise
        unknown = [
            intent_ref
            for intent_ref, effect in self.effects.items()
            if effect["status"] == "unknown"
        ]
        return {
            "policy": policy,
            "recovered_tasks": recovered,
            "ledger_trace_id": (
                self._ledger.trace_id if self._ledger is not None else None
            ),
            "task_statuses": {
                task_id: record.status for task_id, record in self.tasks.items()
            },
            "effects": {
                "effect_state": "unknown" if unknown else "complete",
                "pending_intents": unknown,
                "requires_reconciliation": bool(unknown),
            },
            "audit": task_events + effect_events,
        }

    def _recover_tasks(self, policy: str) -> tuple[list[dict], list[dict]]:
        target = "failed" if policy == "fail" else "created"
        recovered: list[dict] = []
        events: list[dict] = []
        for record in self.tasks.values():
            if record.status in TERMINAL or record.status == target:
                continue
            previous = record.status
            record.status = target
            recovered.append(
                {"task_id": record.task_id, "from": previous, "to": target}
            )
            events.append(
                {
                    "actor": RECOVERY_ACTOR,
                    "action": "task.failed" if target == "failed" else "task.created",
                    "target": record.task_id,
                    "decision": "allow",
                    "task_id": record.task_id,
                    "extensions": {
                        "reason": "restart_recovery",
                        "from": previous,
                        "to": target,
                        "policy": policy,
                    },
                }
            )
        self.audit.extend(copy.deepcopy(events))
        return recovered, events

    def _recover_effects(self) -> tuple[bool, list[dict]]:
        changed = False
        events: list[dict] = []
        for effect in self.effects.values():
            if effect["status"] != "pending":
                continue
            effect["status"] = "unknown"
            changed = True
            events.append(
                {
                    "actor": RECOVERY_ACTOR,
                    "action": "error",
                    "target": effect["target"],
                    "decision": "deny",
                    "task_id": effect["task_id"],
                    "extensions": {
                        "reason": "effect_outcome_unknown",
                        "intent_ref": effect["intent_ref"],
                        "requires_reconciliation": True,
                    },
                }
            )
        self.audit.extend(copy.deepcopy(events))
        return changed, events

    def _effect(self, intent_ref: str) -> dict:
        effect = self.effects.get(intent_ref)
        if effect is None:
            raise OsapError(
                "ROUTING_NOT_FOUND",
                f"unknown effect intent: {intent_ref}",
                details={"intent_ref": intent_ref},
            )
        return effect

    # --- ownership ---------------------------------------------------------

    def require_owner(self, task_id: str, sender: str) -> Task:
        """Refuse control commands from anyone but the current owner (§8.9)."""

        task = self.require(task_id)
        if task.owner != sender:
            raise OsapError(
                "POLICY_DENIED",
                "sender no longer owns the task",
                details={"owner": task.owner, "sender": sender},
            )
        return task
