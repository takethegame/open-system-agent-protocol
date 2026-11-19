# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the task model (standard.md §8)."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from osap import JsonStore, OsapError, audit, task

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

ORCHESTRATOR = "agent://com.example.orchestrator/main#1a2b"
CALENDAR = "agent://com.example.calendar/agent#9c"
TRACE = "trace_recovery_01J9Z6Q3V8N2K4M7P1R5T0WX"


def clock():
    return datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def parent_task() -> task.Task:
    return task.Task.from_document(load("task.json"))


def child_record(
    task_id: str = "task_child",
    parent: str = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAB",
    **overrides,
) -> task.Task:
    record = {
        "task_id": task_id,
        "parent_task_id": parent,
        "root_task_id": "task_01J9Z6Q3V8N2K4M7P1R5T0WXAA",
        "mode": "supervisor",
        "owner": ORCHESTRATOR,
        "assignee": CALENDAR,
        "budget": {"wall_ms": 1000},
        "status": "running",
    }
    record.update(overrides)
    return task.Task.from_document(record)


class BudgetTests(unittest.TestCase):
    def test_within_budget_is_accepted(self):
        task.check_budget({"wall_ms": 5000, "tool_calls": 2}, {"wall_ms": 5000, "tool_calls": 2})

    def test_wall_ms_overflow_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            task.check_budget({"wall_ms": 5000}, {"wall_ms": 6000})
        self.assertEqual(caught.exception.code, "TASK_BUDGET_EXCEEDED")
        self.assertEqual(caught.exception.details["dimension"], "wall_ms")

    def test_tool_call_overflow_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            task.check_budget({"tool_calls": 2}, {"tool_calls": 3})
        self.assertEqual(caught.exception.details["dimension"], "tool_calls")

    def test_unbounded_dimension_is_not_checked(self):
        task.check_budget({"wall_ms": 5000}, {"tokens": 10_000})

    def test_money_overflow_is_rejected(self):
        budget = {"money": {"currency": "USD", "amount": 1}}
        with self.assertRaises(OsapError) as caught:
            task.check_budget(budget, {"money": {"currency": "USD", "amount": 2}})
        self.assertEqual(caught.exception.details["dimension"], "money")

    def test_money_currency_mismatch_is_rejected(self):
        budget = {"money": {"currency": "USD", "amount": 1}}
        with self.assertRaises(OsapError):
            task.check_budget(budget, {"money": {"currency": "EUR", "amount": 1}})

    def test_remaining_budget_never_goes_negative(self):
        left = task.remaining_budget({"wall_ms": 1000, "tool_calls": 2}, {"wall_ms": 1500})
        self.assertEqual(left["wall_ms"], 0)
        self.assertEqual(left["tool_calls"], 2)


class TaskDocumentTests(unittest.TestCase):
    def test_example_task_is_valid(self):
        record = parent_task()
        self.assertEqual(record.owner, ORCHESTRATOR)
        self.assertEqual(record.result_schema, "osap.calendar.proposal/v1")

    def test_missing_budget_is_schema_invalid(self):
        document = load("task.json")
        del document["budget"]
        with self.assertRaises(OsapError) as caught:
            task.Task.from_document(document)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_snapshot_is_independent(self):
        record = parent_task()
        snapshot = record.snapshot()
        snapshot["budget"]["wall_ms"] = 1
        self.assertEqual(record.budget["wall_ms"], 8000)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.record = self.board.add(parent_task())

    def test_created_to_accepted_to_running(self):
        self.board.transition(self.record, "accepted")
        self.board.transition(self.record, "running")
        self.assertEqual(self.record.status, "running")

    def test_created_to_succeeded_is_illegal(self):
        with self.assertRaises(OsapError) as caught:
            self.board.transition(self.record, "succeeded")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_unknown_status_is_schema_invalid(self):
        with self.assertRaises(OsapError) as caught:
            self.board.transition(self.record, "sleeping")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_transitions_are_audited(self):
        self.board.transition(self.record, "accepted")
        self.assertEqual(self.board.audit[-1]["action"], "task.status")


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.root = self.board.add(parent_task())
        self.child = self.board.add(child_record("task_child", parent=self.root.task_id))
        self.grandchild = self.board.add(child_record("task_grandchild", parent="task_child"))

    def test_cancel_propagates_to_descendants(self):
        cancelled = self.board.cancel(self.root.task_id)
        self.assertEqual(cancelled, [self.root.task_id, "task_child", "task_grandchild"])
        self.assertEqual(self.grandchild.status, "cancelled")

    def test_detached_child_keeps_running(self):
        self.child.detached = True
        cancelled = self.board.cancel(self.root.task_id)
        self.assertEqual(cancelled, [self.root.task_id])
        self.assertEqual(self.child.status, "running")

    def test_terminal_tasks_are_not_cancelled_again(self):
        self.child.status = "succeeded"
        cancelled = self.board.cancel(self.root.task_id)
        self.assertNotIn("task_child", cancelled)
        self.assertEqual(self.child.status, "succeeded")

    def test_unknown_task_is_routing_not_found(self):
        with self.assertRaises(OsapError) as caught:
            self.board.cancel("task_missing")
        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.parent = self.board.add(parent_task())
        self.message = load("delegate.json")

    def test_valid_delegation_creates_a_child(self):
        child = self.board.delegate(self.parent.task_id, self.message)
        self.assertEqual(child.task_id, "task_01J9Z6Q3V8N2K4M7P1R5T0WXAE")
        self.assertEqual(child.parent_task_id, self.parent.task_id)
        self.assertEqual(child.authority["cap_id"], "cap_01J9Z6Q3V8N2K4M7P1R5T0WXAD")

    def test_budget_above_the_parent_remainder_is_rejected(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["budget"]["wall_ms"] = 9000
        with self.assertRaises(OsapError) as caught:
            self.board.delegate(self.parent.task_id, message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertEqual(caught.exception.details["dimension"], "wall_ms")

    def test_budget_equal_to_the_remainder_is_accepted(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["budget"]["wall_ms"] = 8000
        self.board.delegate(self.parent.task_id, message)

    def test_depth_must_be_parent_plus_one(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["budget"]["depth"] = 3
        with self.assertRaises(OsapError) as caught:
            self.board.delegate(self.parent.task_id, message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertIn("depth", caught.exception.message)

    def test_parent_mismatch_is_rejected(self):
        message = copy.deepcopy(self.message)
        message["task"]["parent"] = "task_other"
        with self.assertRaises(OsapError) as caught:
            self.board.delegate(self.parent.task_id, message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_duplicate_child_is_rejected(self):
        self.board.delegate(self.parent.task_id, self.message)
        with self.assertRaises(OsapError) as caught:
            self.board.delegate(self.parent.task_id, self.message)
        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_delegation_is_audited(self):
        child = self.board.delegate(self.parent.task_id, self.message)
        self.assertEqual(self.board.audit[-1]["action"], "task.delegated")
        self.assertEqual(self.board.audit[-1]["task_id"], child.task_id)


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.record = self.board.add(parent_task())
        self.board.transition(self.record, "accepted")
        self.board.transition(self.record, "running")
        self.message = load("result.json")

    def test_matching_result_is_accepted(self):
        self.board.accept_result(self.message)
        self.assertEqual(self.record.status, "succeeded")

    def test_schema_mismatch_is_rejected(self):
        message = copy.deepcopy(self.message)
        message["body"]["schema"] = "osap.calendar.propose/v1"
        with self.assertRaises(OsapError) as caught:
            self.board.accept_result(message)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_non_assignee_result_is_rejected(self):
        message = copy.deepcopy(self.message)
        message["from"] = "agent://com.example.notes/agent#77"
        with self.assertRaises(OsapError) as caught:
            self.board.accept_result(message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.record = self.board.add(parent_task())
        self.message = load("handoff.json")

    def test_accepted_handoff_transfers_ownership(self):
        result = self.board.handoff(self.record, self.message)
        self.assertEqual(result, "accepted")
        self.assertEqual(self.record.owner, CALENDAR)
        self.assertEqual(self.record.assignee, CALENDAR)
        self.assertEqual(self.record.authority["cap_id"], "cap_01J9Z6Q3V8N2K4M7P1R5T0WXAF")

    def test_rejected_handoff_changes_nothing(self):
        before = self.record.snapshot()
        result = self.board.handoff(self.record, self.message, accepted=False)
        self.assertEqual(result, "rejected")
        self.assertEqual(self.record.snapshot(), before)

    def test_non_owner_cannot_hand_off(self):
        message = copy.deepcopy(self.message)
        message["from"] = CALENDAR
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, message)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_l3_handoff_needs_a_fresh_receipt(self):
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, self.message, risk="L3", renewed_consent=True)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_l3_handoff_with_receipt_and_renewal_is_accepted(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["delegated_capability"]["consent_receipt_id"] = "consent_1"
        self.assertEqual(
            self.board.handoff(self.record, message, risk="L3", renewed_consent=True),
            "accepted",
        )

    def test_l3_handoff_with_receipt_but_no_renewal_is_rejected(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["delegated_capability"]["consent_receipt_id"] = "consent_1"
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, message, risk="L3", renewed_consent=False)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_audience_must_match_the_new_owner(self):
        message = copy.deepcopy(self.message)
        capability = message["body"]["data"]["delegated_capability"]
        capability["audience"] = "agent://com.example.notes/a#1"
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, message)
        self.assertEqual(caught.exception.code, "CAPABILITY_AUDIENCE_MISMATCH")

    def test_subject_must_match_the_new_owner(self):
        message = copy.deepcopy(self.message)
        capability = message["body"]["data"]["delegated_capability"]
        capability["subject"] = "agent://com.example.notes/a#1"
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, message)
        self.assertEqual(caught.exception.code, "CAPABILITY_SUBJECT_MISMATCH")

    def test_capability_must_be_bound_to_the_task(self):
        message = copy.deepcopy(self.message)
        message["body"]["data"]["delegated_capability"]["task_id"] = "task_other"
        with self.assertRaises(OsapError) as caught:
            self.board.handoff(self.record, message)
        self.assertEqual(caught.exception.code, "CAPABILITY_TASK_MISMATCH")

    def test_handoff_is_audited(self):
        self.board.handoff(self.record, self.message)
        entry = self.board.audit[-1]
        self.assertEqual(entry["action"], "task.handoff")
        self.assertEqual(entry["to"], CALENDAR)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def board(self) -> task.TaskBoard:
        return task.TaskBoard(store=JsonStore(self.path))

    def test_the_whole_tree_survives_reopen(self):
        first = self.board()
        root = first.add(parent_task())
        child = child_record("task_child", parent=root.task_id)
        child.consumed = {"wall_ms": 250, "tool_calls": 1}
        child.detached = True
        child.result_schema = "osap.child/v1"
        first.add(child)

        second = self.board()
        self.assertEqual(second.require(root.task_id).to_state(), root.to_state())
        restored = second.require("task_child")
        self.assertEqual(restored.to_state(), child.to_state())
        self.assertEqual(restored.parent_task_id, root.task_id)
        self.assertEqual(restored.consumed, {"wall_ms": 250, "tool_calls": 1})
        self.assertTrue(restored.detached)

    def test_a_restored_task_continues_transitioning(self):
        first = self.board()
        record = first.add(parent_task())
        first.transition(record, "accepted")
        first.transition(record, "running")

        second = self.board()
        resumed = second.require(record.task_id)
        second.transition(resumed, "succeeded")
        self.assertEqual(self.board().require(record.task_id).status, "succeeded")

    def test_delegation_survives_reopen(self):
        first = self.board()
        parent = first.add(parent_task())
        child = first.delegate(parent.task_id, load("delegate.json"))

        second = self.board()
        restored = second.require(child.task_id)
        self.assertEqual(restored.to_state(), child.to_state())
        self.assertEqual(restored.parent_task_id, parent.task_id)
        self.assertEqual(restored.authority["cap_id"], child.authority["cap_id"])

    def test_cancellation_survives_reopen(self):
        first = self.board()
        root = first.add(parent_task())
        child = first.add(child_record("task_child", parent=root.task_id))
        first.cancel(root.task_id)

        second = self.board()
        self.assertEqual(second.require(root.task_id).status, "cancelled")
        self.assertEqual(second.require(child.task_id).status, "cancelled")

    def test_a_detached_child_stays_running_across_reopen(self):
        first = self.board()
        root = first.add(parent_task())
        child = child_record("task_child", parent=root.task_id)
        child.detached = True
        first.add(child)
        first.cancel(root.task_id)

        second = self.board()
        self.assertTrue(second.require(child.task_id).detached)
        self.assertEqual(second.require(child.task_id).status, "running")
        self.assertEqual(second.require(root.task_id).status, "cancelled")

    def test_handoff_survives_reopen(self):
        first = self.board()
        record = first.add(parent_task())
        first.handoff(record, load("handoff.json"))

        second = self.board()
        restored = second.require(record.task_id)
        self.assertEqual(restored.owner, CALENDAR)
        self.assertEqual(restored.assignee, CALENDAR)
        self.assertEqual(restored.authority["cap_id"], "cap_01J9Z6Q3V8N2K4M7P1R5T0WXAF")

    def test_audit_is_not_persisted(self):
        first = self.board()
        record = first.add(parent_task())
        first.transition(record, "accepted")
        first.transition(record, "running")
        self.assertTrue(first.audit)

        self.assertEqual(self.board().audit, [])

    def test_another_section_of_the_shared_store_is_kept(self):
        store = JsonStore(self.path)
        store.put("other.section", {"kept": True})
        board = task.TaskBoard(store=store)
        board.add(parent_task())

        self.assertEqual(JsonStore(self.path).get("other.section"), {"kept": True})
        self.assertIn(
            parent_task().task_id,
            JsonStore(self.path).get(task.TASKS_SECTION),
        )

    def test_a_corrupt_section_is_rejected(self):
        store = JsonStore(self.path)
        store.put(task.TASKS_SECTION, [])
        with self.assertRaises(ValueError):
            task.TaskBoard(store=store)

    def test_a_record_with_an_unknown_status_is_rejected(self):
        store = JsonStore(self.path)
        state = {**parent_task().to_state(), "status": "sleeping"}
        store.put(task.TASKS_SECTION, {"task_x": state})
        with self.assertRaises(ValueError):
            task.TaskBoard(store=store)

    def test_a_record_under_the_wrong_key_is_rejected(self):
        store = JsonStore(self.path)
        store.put(task.TASKS_SECTION, {"task_other": parent_task().to_state()})
        with self.assertRaises(ValueError):
            task.TaskBoard(store=store)

    def test_a_record_without_a_budget_is_rejected(self):
        state = parent_task().to_state()
        del state["budget"]
        store = JsonStore(self.path)
        store.put(task.TASKS_SECTION, {state["task_id"]: state})
        with self.assertRaises(ValueError):
            task.TaskBoard(store=store)




def running_record(board: task.TaskBoard):
    """Add a task and move it to `running`, the state recovery must not leave."""

    record = board.add(parent_task())
    board.transition(record, "accepted")
    board.transition(record, "running")
    return record


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def board(self) -> task.TaskBoard:
        return task.TaskBoard(store=JsonStore(self.path))

    def test_a_running_task_becomes_failed_and_stays_failed(self):
        first = self.board()
        record = running_record(first)

        second = self.board()
        report = second.recover()

        self.assertEqual(
            report["recovered_tasks"],
            [{"task_id": record.task_id, "from": "running", "to": "failed"}],
        )
        self.assertEqual(report["task_statuses"][record.task_id], "failed")
        self.assertEqual(self.board().require(record.task_id).status, "failed")

    def test_a_created_task_is_also_recovered(self):
        first = self.board()
        record = first.add(parent_task())

        report = self.board().recover()

        self.assertEqual(report["recovered_tasks"][0]["from"], "created")
        self.assertEqual(report["task_statuses"][record.task_id], "failed")

    def test_terminal_tasks_are_not_touched(self):
        first = self.board()
        record = running_record(first)
        first.transition(record, "succeeded")

        report = self.board().recover()

        self.assertEqual(report["recovered_tasks"], [])
        self.assertEqual(report["audit"], [])
        self.assertEqual(self.board().require(record.task_id).status, "succeeded")

    def test_a_detached_running_task_is_recovered(self):
        first = self.board()
        record = running_record(first)
        record.detached = True
        first._persist()

        report = self.board().recover()

        self.assertEqual(report["recovered_tasks"][0]["task_id"], record.task_id)
        self.assertEqual(self.board().require(record.task_id).status, "failed")

    def test_recovery_overrides_the_normal_state_machine(self):
        board = task.TaskBoard()
        record = board.add(parent_task())

        with self.assertRaises(OsapError):
            board.transition(record, "failed")

        board.recover()

        self.assertEqual(record.status, "failed")

    def test_reschedule_returns_a_running_task_to_created(self):
        first = self.board()
        record = running_record(first)

        report = self.board().recover(policy="reschedule")

        self.assertEqual(
            report["recovered_tasks"],
            [{"task_id": record.task_id, "from": "running", "to": "created"}],
        )
        self.assertEqual(self.board().require(record.task_id).status, "created")

    def test_reschedule_leaves_a_created_task_untouched(self):
        first = self.board()
        record = first.add(parent_task())

        report = self.board().recover(policy="reschedule")

        self.assertEqual(report["recovered_tasks"], [])
        self.assertEqual(self.board().require(record.task_id).status, "created")

    def test_parent_and_child_are_recovered_together(self):
        first = self.board()
        root = running_record(first)
        child = child_record("task_child", parent=root.task_id)
        first.add(child)

        report = self.board().recover()

        self.assertEqual(
            {item["task_id"] for item in report["recovered_tasks"]},
            {root.task_id, child.task_id},
        )
        self.assertEqual(self.board().require("task_child").status, "failed")

    def test_a_second_recovery_is_a_no_op(self):
        first = self.board()
        running_record(first)
        first.recover()

        second = self.board()
        report = second.recover()

        self.assertEqual(report["recovered_tasks"], [])
        self.assertEqual(report["audit"], [])

    def test_recovery_events_fit_an_audit_ledger(self):
        first = self.board()
        record = running_record(first)

        report = self.board().recover()
        ledger = audit.AuditLedger(trace_id="trace_recovery")
        for event in report["audit"]:
            ledger.append(event)

        self.assertTrue(ledger.verify())
        event = ledger.events[0]
        self.assertEqual(event["action"], "task.failed")
        self.assertEqual(event["target"], record.task_id)
        self.assertEqual(event["decision"], "allow")
        self.assertEqual(event["extensions"]["reason"], "restart_recovery")

    def test_recovery_persists_one_atomic_snapshot(self):
        store = RecordingStore()
        board = task.TaskBoard(store=store)
        board.add(parent_task())
        store.puts.clear()

        board.recover()

        self.assertEqual(store.puts, [task.TASKS_SECTION, task.EFFECTS_SECTION])
        self.assertIn(parent_task().task_id, store.data[task.TASKS_SECTION])

    def test_a_no_op_recovery_does_not_write(self):
        store = RecordingStore()
        board = task.TaskBoard(store=store)
        record = board.add(parent_task())
        board.transition(record, "accepted")
        board.transition(record, "running")
        board.transition(record, "succeeded")
        store.puts.clear()

        board.recover()

        self.assertEqual(store.puts, [])

    def test_an_unknown_policy_is_rejected(self):
        for value in ("", "retry", None, 1):
            with self.assertRaises(ValueError):
                task.TaskBoard().recover(policy=value)


class EffectJournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def board(self) -> task.TaskBoard:
        return task.TaskBoard(store=JsonStore(self.path))

    def intent(self, board: task.TaskBoard, record=None, **overrides):
        record = record or board.add(parent_task())
        if record.status == "created":
            board.transition(record, "accepted")
            board.transition(record, "running")
        values = {
            "intent_ref": "intent_calendar_write",
            "target": "calendar:primary",
            "idempotency_key": "idem_calendar_write",
        }
        values.update(overrides)
        return board.record_effect_intent(record.task_id, **values)

    def test_an_intent_is_persisted_before_the_effect(self):
        first = self.board()
        record = self.intent(first)

        stored = JsonStore(self.path).get(task.EFFECTS_SECTION)
        self.assertEqual(stored[record["intent_ref"]], record)
        second = self.board()
        self.assertEqual(second.effects[record["intent_ref"]], record)

    def test_an_outcome_is_persisted(self):
        board = self.board()
        record = self.intent(board)
        board.record_effect_outcome(record["intent_ref"])

        self.assertEqual(
            self.board().effects[record["intent_ref"]]["status"], "executed"
        )

    def test_an_outcome_is_idempotent(self):
        board = self.board()
        record = self.intent(board)
        first = board.record_effect_outcome(record["intent_ref"])
        second = board.record_effect_outcome(record["intent_ref"])

        self.assertEqual(first, second)
        self.assertEqual(second["status"], "executed")

    def test_a_duplicate_intent_is_rejected(self):
        board = self.board()
        record = self.intent(board)

        with self.assertRaises(OsapError) as caught:
            self.intent(board, board.require(record["task_id"]))

        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_an_unknown_task_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.board().record_effect_intent(
                "task_missing", intent_ref="intent_x", target="calendar:primary"
            )

        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")

    def test_a_terminal_task_cannot_start_an_effect(self):
        board = self.board()
        record = board.add(parent_task())
        board.transition(record, "cancelled")

        with self.assertRaises(OsapError) as caught:
            board.record_effect_intent(
                record.task_id, intent_ref="intent_x", target="calendar:primary"
            )

        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_an_invalid_intent_is_rejected(self):
        board = self.board()
        record = board.add(parent_task())
        for values in (
            {"intent_ref": "", "target": "calendar:primary"},
            {"intent_ref": "intent_x", "target": ""},
            {"intent_ref": "intent_x", "target": "calendar:primary", "idempotency_key": ""},
        ):
            with self.assertRaises(ValueError):
                board.record_effect_intent(record.task_id, **values)

    def test_recovery_marks_an_intent_unknown(self):
        board = self.board()
        record = self.intent(board)

        report = board.recover()

        self.assertTrue(report["effects"]["requires_reconciliation"])
        self.assertEqual(report["effects"]["effect_state"], "unknown")
        self.assertEqual(report["effects"]["pending_intents"], [record["intent_ref"]])
        self.assertTrue(report["audit"])

    def test_unknown_effects_survive_a_reopen(self):
        first = self.board()
        record = self.intent(first)
        first.recover()

        second = self.board()
        report = second.recover()

        self.assertEqual(report["effects"]["pending_intents"], [record["intent_ref"]])
        self.assertEqual(report["audit"], [])
        self.assertEqual(second.effects[record["intent_ref"]]["status"], "unknown")

    def test_the_effect_alert_is_a_valid_audit_event(self):
        board = self.board()
        self.intent(board)

        report = board.recover()
        ledger = audit.AuditLedger(trace_id="trace_effect")
        for event in report["audit"]:
            ledger.append(event)

        self.assertTrue(ledger.verify())
        alert = [event for event in ledger.events if event["action"] == "error"][0]
        self.assertEqual(alert["decision"], "deny")
        self.assertEqual(alert["extensions"]["reason"], "effect_outcome_unknown")
        self.assertTrue(alert["extensions"]["requires_reconciliation"])

    def test_recovery_writes_the_tree_and_journal_together(self):
        store = RecordingStore()
        board = task.TaskBoard(store=store)
        self.intent(board)
        store.puts.clear()

        board.recover()

        self.assertEqual(store.puts, [task.TASKS_SECTION, task.EFFECTS_SECTION])

    def test_replay_is_blocked_for_a_pending_intent(self):
        board = self.board()
        record = self.intent(board)

        with self.assertRaises(OsapError) as caught:
            board.require_replay_allowed(record["intent_ref"])

        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertEqual(caught.exception.details["reason"], "reconciliation_required")

    def test_replay_is_blocked_for_an_unknown_effect(self):
        board = self.board()
        record = self.intent(board)
        board.recover()

        with self.assertRaises(OsapError) as caught:
            board.require_replay_allowed(record["intent_ref"])

        self.assertEqual(caught.exception.details["reason"], "reconciliation_required")

    def test_replay_is_allowed_for_an_executed_effect(self):
        board = self.board()
        record = self.intent(board)
        board.record_effect_outcome(record["intent_ref"])

        allowed = board.require_replay_allowed(record["intent_ref"])

        self.assertEqual(allowed["status"], "executed")

    def test_reconciliation_can_confirm_execution(self):
        board = self.board()
        record = self.intent(board)
        board.recover()
        reconciled = board.reconcile_effect(
            record["intent_ref"], outcome="executed"
        )

        self.assertEqual(reconciled["status"], "reconciled")
        self.assertEqual(reconciled["reconciled_outcome"], "executed")
        self.assertEqual(
            self.board().effects[record["intent_ref"]]["reconciled_outcome"],
            "executed",
        )
        with self.assertRaises(OsapError) as caught:
            board.require_replay_allowed(record["intent_ref"])
        self.assertEqual(caught.exception.details["reason"], "already_executed")

    def test_reconciliation_can_confirm_a_miss_and_allow_a_retry(self):
        board = self.board()
        record = self.intent(board)
        board.recover()
        board.reconcile_effect(record["intent_ref"], outcome="not_executed")

        allowed = board.require_replay_allowed(record["intent_ref"])

        self.assertEqual(allowed["reconciled_outcome"], "not_executed")

    def test_only_an_unknown_effect_can_be_reconciled(self):
        board = self.board()
        record = self.intent(board)
        with self.assertRaises(OsapError) as caught:
            board.reconcile_effect(record["intent_ref"], outcome="executed")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

        board.recover()
        with self.assertRaises(ValueError):
            board.reconcile_effect(record["intent_ref"], outcome="maybe")

    def test_a_late_outcome_must_be_reconciled(self):
        board = self.board()
        record = self.intent(board)
        board.recover()

        with self.assertRaises(OsapError) as caught:
            board.record_effect_outcome(record["intent_ref"])

        self.assertEqual(caught.exception.details["reason"], "reconciliation_required")

    def test_corrupt_effect_sections_are_rejected(self):
        cases = [
            [],
            {"intent_x": []},
            {"intent_x": {"intent_ref": "intent_other", "task_id": "task_x"}},
        ]
        for value in cases:
            with self.subTest(value=value):
                path = Path(self.directory.name) / f"corrupt_{len(str(value))}.json"
                store = JsonStore(path)
                store.put(task.EFFECTS_SECTION, value)
                with self.assertRaises(ValueError):
                    task.TaskBoard(store=store)

    def test_an_effect_with_a_bad_status_is_rejected(self):
        store = JsonStore(self.path)
        board = task.TaskBoard(store=store)
        record = self.intent(board)
        state = store.get(task.EFFECTS_SECTION)
        state[record["intent_ref"]]["status"] = "maybe"
        store.put(task.EFFECTS_SECTION, state)

        with self.assertRaises(ValueError):
            self.board()

    def test_an_effect_for_a_missing_task_is_rejected(self):
        store = JsonStore(self.path)
        board = task.TaskBoard(store=store)
        record = self.intent(board)
        state = store.get(task.EFFECTS_SECTION)
        state[record["intent_ref"]]["task_id"] = "task_missing"
        store.put(task.EFFECTS_SECTION, state)

        with self.assertRaises(ValueError):
            self.board()

    def test_a_reconciled_effect_needs_a_valid_outcome(self):
        store = JsonStore(self.path)
        board = task.TaskBoard(store=store)
        record = self.intent(board)
        state = store.get(task.EFFECTS_SECTION)
        state[record["intent_ref"]]["status"] = "reconciled"
        store.put(task.EFFECTS_SECTION, state)

        with self.assertRaises(ValueError):
            self.board()

    def test_an_unreconciled_effect_cannot_carry_an_outcome(self):
        store = JsonStore(self.path)
        board = task.TaskBoard(store=store)
        record = self.intent(board)
        state = store.get(task.EFFECTS_SECTION)
        state[record["intent_ref"]]["reconciled_outcome"] = "executed"
        store.put(task.EFFECTS_SECTION, state)

        with self.assertRaises(ValueError):
            self.board()

    def test_an_unknown_effect_ref_is_routing_not_found(self):
        with self.assertRaises(OsapError) as caught:
            self.board().require_replay_allowed("intent_missing")

        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")


class RecordingStore:
    """A tiny store that records one section name per write."""

    def __init__(self):
        self.data: dict = {}
        self.puts: list[str] = []

    def get(self, section, default=None):
        return copy.deepcopy(self.data.get(section, default))

    def put(self, section, value):
        self.puts.append(section)
        self.data[section] = copy.deepcopy(value)

    def put_many(self, sections):
        self.puts.extend(sections)
        self.data.update(copy.deepcopy(sections))


class WriteCountTests(unittest.TestCase):
    def setUp(self):
        self.store = RecordingStore()
        self.board = task.TaskBoard(store=self.store)

    def test_add_writes_once(self):
        self.board.add(parent_task())
        self.assertEqual(self.store.puts, [task.TASKS_SECTION])

    def test_a_no_op_transition_does_not_write(self):
        record = self.board.add(parent_task())
        self.store.puts.clear()
        self.board.transition(record, "created")
        self.assertEqual(self.store.puts, [])

    def test_delegate_writes_once_not_twice(self):
        parent = self.board.add(parent_task())
        self.store.puts.clear()
        self.board.delegate(parent.task_id, load("delegate.json"))
        self.assertEqual(self.store.puts, [task.TASKS_SECTION])

    def test_cancel_writes_once_for_the_whole_subtree(self):
        root = self.board.add(parent_task())
        self.board.add(child_record("task_child", parent=root.task_id))
        self.board.add(child_record("task_grandchild", parent="task_child"))
        self.store.puts.clear()
        self.board.cancel(root.task_id)
        self.assertEqual(self.store.puts, [task.TASKS_SECTION])

    def test_rejected_handoff_does_not_write(self):
        record = self.board.add(parent_task())
        self.store.puts.clear()
        self.board.handoff(record, load("handoff.json"), accepted=False)
        self.assertEqual(self.store.puts, [])

    def test_accepted_handoff_writes_once(self):
        record = self.board.add(parent_task())
        self.store.puts.clear()
        self.board.handoff(record, load("handoff.json"))
        self.assertEqual(self.store.puts, [task.TASKS_SECTION])


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.board = task.TaskBoard()
        self.record = self.board.add(parent_task())

    def test_owner_may_keep_sending(self):
        self.board.require_owner(self.record.task_id, ORCHESTRATOR)

    def test_former_owner_is_refused_after_handoff(self):
        self.board.handoff(self.record, load("handoff.json"))
        with self.assertRaises(OsapError) as caught:
            self.board.require_owner(self.record.task_id, ORCHESTRATOR)
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_new_owner_may_send(self):
        self.board.handoff(self.record, load("handoff.json"))
        self.board.require_owner(self.record.task_id, CALENDAR)

    def test_unknown_task_is_routing_not_found(self):
        with self.assertRaises(OsapError) as caught:
            self.board.require_owner("task_missing", ORCHESTRATOR)
        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")


class RecoveryLedgerTests(unittest.TestCase):
    """recover() puts the tree, the journal, and the audit chain together."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def board(self, **kwargs) -> task.TaskBoard:
        store = JsonStore(self.path)
        ledger = audit.AuditLedger(trace_id=TRACE, store=store, clock=clock)
        return task.TaskBoard(store=store, ledger=ledger, **kwargs)

    def test_recover_writes_one_transaction(self):
        board = self.board()
        record = running_record(board)
        board.record_effect_intent(record.task_id, intent_ref="intent_x", target="x")

        report = board.recover()

        self.assertEqual(report["ledger_trace_id"], TRACE)
        self.assertEqual(len(report["audit"]), 2)
        stored = JsonStore(self.path)
        self.assertEqual(
            sorted(stored.sections()),
            sorted(
                [
                    task.TASKS_SECTION,
                    task.EFFECTS_SECTION,
                    f"audit.chain.{TRACE}",
                ]
            ),
        )
        ledger = audit.AuditLedger(trace_id=TRACE, store=stored, clock=clock)
        self.assertEqual(len(ledger), 2)
        self.assertTrue(ledger.verify())
        actions = {event["action"] for event in ledger.events}
        self.assertEqual(
            actions, {"task.failed", "error"}
        )
        reopened = self.board()
        self.assertEqual(reopened.require(record.task_id).status, "failed")
        self.assertEqual(
            reopened.effects["intent_x"]["status"], "unknown"
        )
        self.assertTrue(reopened._ledger.verify())

    def test_recover_with_nothing_to_do_writes_no_audit(self):
        board = self.board()
        record = running_record(board)
        board.transition(record, "succeeded")
        sections_before = JsonStore(self.path).sections()

        report = board.recover()

        self.assertEqual(report["audit"], [])
        self.assertEqual(report["ledger_trace_id"], TRACE)
        self.assertEqual(JsonStore(self.path).sections(), sections_before)
        self.assertEqual(len(board._ledger), 0)

    def test_a_failed_write_rolls_back_the_recovery(self):
        store = JsonStore(self.path)
        ledger = audit.AuditLedger(trace_id=TRACE, store=store, clock=clock)
        board = task.TaskBoard(store=store, ledger=ledger)
        record = running_record(board)
        board.record_effect_intent(record.task_id, intent_ref="intent_x", target="x")

        audit_before = len(board.audit)
        store.put_many = lambda sections: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            board.recover()
        self.assertEqual(record.status, "running")
        self.assertEqual(board.effects["intent_x"]["status"], "pending")
        self.assertEqual(len(board.audit), audit_before)
        self.assertEqual(len(ledger), 0)

        del store.put_many
        board.recover()
        self.assertEqual(record.status, "failed")
        self.assertEqual(board.effects["intent_x"]["status"], "unknown")
        self.assertTrue(audit.AuditLedger(trace_id=TRACE, store=JsonStore(self.path)).verify())

    def test_the_ledger_must_share_the_board_store(self):
        store = JsonStore(self.path)
        ledger = audit.AuditLedger(trace_id=TRACE, store=store, clock=clock)
        self.assertIs(task.TaskBoard(store=store, ledger=ledger)._ledger, ledger)
        with self.assertRaises(ValueError):
            task.TaskBoard(
                store=JsonStore(self.path),
                ledger=audit.AuditLedger(trace_id=TRACE, store=JsonStore(self.path)),
            )
        with self.assertRaises(ValueError):
            task.TaskBoard(
                store=JsonStore(self.path),
                ledger=audit.AuditLedger(trace_id=TRACE, clock=clock),
            )
        with self.assertRaises(ValueError):
            task.TaskBoard(ledger=ledger)
        with self.assertRaises(ValueError):
            task.TaskBoard(store=store, ledger=object())

    def test_a_reschedule_recovery_is_also_audited(self):
        board = self.board()
        record = running_record(board)

        report = board.recover(policy="reschedule")

        self.assertEqual(report["task_statuses"][record.task_id], "created")
        ledger = audit.AuditLedger(trace_id=TRACE, store=JsonStore(self.path))
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.events[0]["action"], "task.created")
        self.assertTrue(ledger.verify())


class EffectArchiveTests(unittest.TestCase):
    """max_effects moves resolved effects aside; pending ones never leave."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def board(self, **kwargs) -> task.TaskBoard:
        return task.TaskBoard(store=JsonStore(self.path), **kwargs)

    def intent(self, board, intent_ref, resolve=None):
        record = board.add(parent_task())
        board.transition(record, "accepted")
        board.transition(record, "running")
        board.record_effect_intent(
            record.task_id, intent_ref=intent_ref, target="calendar:primary"
        )
        if resolve is not None:
            board.record_effect_outcome(intent_ref)
        return record

    def test_resolved_effects_move_to_the_archive(self):
        board = self.board(max_effects=2)
        self.intent(board, "intent_a", resolve="outcome")
        self.intent(board, "intent_b")
        self.intent(board, "intent_c")
        # Resolving `intent_a` made it the oldest movable effect, so the
        # third journal entry trims it out immediately.
        self.assertEqual(sorted(board.effects), ["intent_b", "intent_c"])
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])

        board.record_effect_outcome("intent_b")
        self.assertEqual(sorted(board.effects), ["intent_b", "intent_c"])
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])
        stored = JsonStore(self.path).get(task.EFFECT_ARCHIVE_SECTION)
        self.assertEqual(sorted(stored), ["intent_a"])
        self.assertEqual(stored["intent_a"]["status"], "executed")

    def test_pending_effects_are_never_archived(self):
        board = self.board(max_effects=1)
        self.intent(board, "intent_a")
        self.intent(board, "intent_b")
        self.intent(board, "intent_c")
        self.assertEqual(len(board.effects), 3)
        self.assertEqual(board.archived_effects(), {})

    def test_the_archive_survives_a_reopen(self):
        board = self.board(max_effects=1)
        self.intent(board, "intent_a", resolve="outcome")
        self.intent(board, "intent_b", resolve="outcome")
        self.assertEqual(sorted(board.effects), ["intent_b"])
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])

        reopened = self.board(max_effects=1)
        self.assertEqual(sorted(reopened.effects), ["intent_b"])
        self.assertEqual(sorted(reopened.archived_effects()), ["intent_a"])
        with self.assertRaises(OsapError) as caught:
            reopened.require_replay_allowed("intent_a")
        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")
        reopened.require_replay_allowed("intent_b")

    def test_a_failed_archive_write_rolls_back(self):
        store = JsonStore(self.path)
        board = task.TaskBoard(store=store, max_effects=1)
        self.intent(board, "intent_a", resolve="outcome")
        self.intent(board, "intent_b")
        # Recording `intent_b` already archived the resolved `intent_a`.
        self.assertEqual(sorted(board.effects), ["intent_b"])
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])

        store.put = lambda section, value: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            board.record_effect_outcome("intent_b")
        self.assertEqual(sorted(board.effects), ["intent_b"])
        self.assertEqual(board.effects["intent_b"]["status"], "pending")
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])
        del store.put
        board.record_effect_outcome("intent_b")
        self.assertEqual(board.effects["intent_b"]["status"], "executed")
        self.assertEqual(sorted(board.archived_effects()), ["intent_a"])

    def test_corrupt_archive_sections_are_rejected(self):
        board = self.board(max_effects=1)
        self.intent(board, "intent_a", resolve="outcome")
        self.intent(board, "intent_b")
        good = JsonStore(self.path).get(task.EFFECT_ARCHIVE_SECTION)
        for mutate in (
            lambda value: [],
            lambda value: {"intent_other": good["intent_a"]},
            lambda value: {"intent_a": {**good["intent_a"], "status": "weird"}},
            lambda value: {"intent_a": {**good["intent_a"], "task_id": "task_ghost"}},
        ):
            JsonStore(self.path).put(task.EFFECT_ARCHIVE_SECTION, mutate(good))
            with self.assertRaises(ValueError):
                self.board(max_effects=1)

    def test_invalid_limits_are_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                task.TaskBoard(max_effects=value)


if __name__ == "__main__":
    unittest.main()
