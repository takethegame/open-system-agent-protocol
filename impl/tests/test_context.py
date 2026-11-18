# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the context fabric (standard.md §9)."""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from osap import JsonStore, OsapError, context
from osap.clock import parse_timestamp

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

ORCHESTRATOR = "agent://com.example.orchestrator/main#1a2b"
NOTES = "agent://com.example.notes/assistant#7f3a"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def handle(**overrides) -> dict:
    document = load("context-handle.json")
    document.update(overrides)
    return document


def now_of(document: dict):
    return parse_timestamp(document["created_at"])


def resolve(document: dict, **kwargs):
    fabric = context.ContextFabric()
    kwargs.setdefault("agent", document.get("audience"))
    kwargs.setdefault("granted_actions", ["resolve"])
    kwargs.setdefault("now", now_of(document))
    result = fabric.resolve(document, **kwargs)
    return fabric, result


class LabelTests(unittest.TestCase):
    def test_labels_are_ordered_from_public_to_secret(self):
        ranks = [context.label_rank(label) for label in context.LABELS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(context.LABELS, ("public", "personal", "sensitive", "secret"))

    def test_unknown_label_is_schema_invalid(self):
        with self.assertRaises(OsapError) as caught:
            context.label_rank("top_secret")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_stricter_label_picks_the_highest_rank(self):
        self.assertEqual(context.stricter_label("public", "sensitive", None), "sensitive")
        self.assertEqual(context.stricter_label("secret", "personal"), "secret")

    def test_stricter_label_of_nothing_is_none(self):
        self.assertIsNone(context.stricter_label(None, None))

    def test_lowered_label_is_reported(self):
        sources = {"obj://sha256:9f2c7b1a": "sensitive"}
        report = context.label_violation(handle(label="public"), sources)
        self.assertTrue(report["lowered"])
        self.assertFalse(report["conforming"])
        self.assertEqual(report["effective_label"], "sensitive")

    def test_raised_label_is_conforming(self):
        sources = {"obj://sha256:9f2c7b1a": "personal"}
        report = context.label_violation(handle(label="secret"), sources)
        self.assertFalse(report["lowered"])
        self.assertTrue(report["conforming"])
        self.assertEqual(report["effective_label"], "secret")

    def test_equal_label_is_conforming(self):
        sources = {"obj://sha256:9f2c7b1a": "personal"}
        report = context.label_violation(handle(label="personal"), sources)
        self.assertFalse(report["lowered"])
        self.assertEqual(report["effective_label"], "personal")

    def test_unknown_source_is_ignored(self):
        report = context.label_violation(handle(label="public"), {"obj://sha256:other": "secret"})
        self.assertFalse(report["lowered"])
        self.assertIsNone(report["inherited_label"])


class ExpiryTests(unittest.TestCase):
    def test_expires_at_wins_over_ttl(self):
        document = handle(expires_at="2026-11-10T10:20:00Z")
        self.assertEqual(context.expiry_of(document), parse_timestamp("2026-11-10T10:20:00Z"))

    def test_ttl_is_measured_from_created_at(self):
        document = handle(expires_at="", ttl=600)
        expected = parse_timestamp(document["created_at"]) + timedelta(seconds=600)
        self.assertEqual(context.expiry_of(document), expected)

    def test_no_expiry_returns_none(self):
        self.assertIsNone(context.expiry_of({"handle": "ctx://user/profile"}))


class ResolveTests(unittest.TestCase):
    def test_resolve_grant_is_accepted(self):
        document = handle()
        fabric, result = resolve(document)
        self.assertEqual(result["handle"], "ctx://user/profile#display_name")
        self.assertEqual(result["label"], "personal")
        self.assertEqual(fabric.audit[-1]["decision"], "allow")

    def test_read_grant_alone_is_not_enough(self):
        document = handle()
        with self.assertRaises(OsapError) as caught:
            resolve(document, granted_actions=["read"])
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(caught.exception.details["required_action"], "resolve")

    def test_denial_is_audited(self):
        document = handle()
        fabric = context.ContextFabric()
        with self.assertRaises(OsapError):
            fabric.resolve(
                document,
                agent=document["audience"],
                granted_actions=["read"],
                now=now_of(document),
            )
        self.assertEqual(fabric.audit[-1]["decision"], "deny")
        self.assertEqual(fabric.audit[-1]["action"], "context.resolve")
        self.assertEqual(fabric.audit[-1]["handle"], document["handle"])
        self.assertEqual(fabric.audit[-1]["agent"], document["audience"])

    def test_expired_handle_is_rejected(self):
        document = handle(expires_at="2026-11-10T09:00:00Z")
        with self.assertRaises(OsapError) as caught:
            resolve(document)
        self.assertEqual(caught.exception.code, "CONTEXT_EXPIRED")

    def test_expiry_is_not_renewed_by_resolving(self):
        document = handle()
        expired = now_of(document) + timedelta(seconds=600)
        with self.assertRaises(OsapError) as caught:
            resolve(document, now=expired)
        self.assertEqual(caught.exception.code, "CONTEXT_EXPIRED")
        self.assertNotIn("renewed", str(caught.exception.details))

    def test_audience_mismatch_is_denied(self):
        with self.assertRaises(OsapError) as caught:
            resolve(handle(), agent=NOTES)
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(caught.exception.details["reason"], "audience")

    def test_non_audience_does_not_learn_the_expiry_state(self):
        document = handle(expires_at="2026-11-10T09:00:00Z")
        with self.assertRaises(OsapError) as caught:
            resolve(document, agent=NOTES)
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(caught.exception.details["reason"], "audience")

    def test_agent_outside_allowed_agents_is_denied(self):
        document = handle(constraints={"allowed_agents": [NOTES]})
        with self.assertRaises(OsapError) as caught:
            resolve(document)
        self.assertEqual(caught.exception.details["reason"], "agent_not_allowed")

    def test_allowed_agents_are_enforced_with_the_audience(self):
        document = handle(constraints={"allowed_agents": [ORCHESTRATOR]})
        result = resolve(document)[1]
        self.assertEqual(result["label"], "personal")

    def test_os_permission_denial_wins(self):
        document = handle()
        with self.assertRaises(OsapError) as caught:
            resolve(document, os_permission="denied")
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(caught.exception.details["reason"], "os_permission")

    def test_task_grant_does_not_read_long_term_memory(self):
        document = handle(handle="ctx://user/memory/preferences", scope="user")
        with self.assertRaises(OsapError) as caught:
            resolve(document, granted_actions=["task.read"])
        self.assertEqual(caught.exception.details["required_action"], context.MEMORY_ACTION)

    def test_memory_read_grant_resolves_a_memory_handle(self):
        document = handle(handle="ctx://user/memory/preferences", scope="user")
        result = resolve(document, granted_actions=["memory.read"])[1]
        self.assertEqual(result["scope"], "user")

    def test_user_scope_alone_is_not_memory(self):
        document = handle(scope="user")
        self.assertFalse(context.is_memory_handle(document))
        self.assertEqual(context.required_action(document), "resolve")


class EgressTests(unittest.TestCase):
    def test_secret_egress_without_approval_is_denied(self):
        with self.assertRaises(OsapError) as caught:
            resolve(handle(label="secret"), egress=True, user_approval=False)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_sensitive_egress_without_approval_is_denied(self):
        with self.assertRaises(OsapError) as caught:
            resolve(handle(label="sensitive"), egress=True)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_secret_egress_with_approval_is_accepted(self):
        result = resolve(handle(label="secret"), egress=True, user_approval=True)[1]
        self.assertEqual(result["label"], "secret")

    def test_personal_egress_needs_no_approval(self):
        result = resolve(handle(), egress=True)[1]
        self.assertEqual(result["label"], "personal")


class BlackboardTests(unittest.TestCase):
    def test_task_end_archives_without_promotion(self):
        report = context.close_blackboard(load("blackboard.json"), task_ended=True)
        self.assertTrue(report["cleared_or_archived"])
        self.assertFalse(report["promoted_to_memory"])
        self.assertEqual(report["entries_archived"], 2)

    def test_running_task_keeps_the_count(self):
        report = context.close_blackboard(load("blackboard.json"), task_ended=False)
        self.assertFalse(report["task_ended"])
        self.assertTrue(report["cleared_or_archived"])


class DeleteTests(unittest.TestCase):
    def test_referenced_object_is_tombstoned_not_deleted(self):
        report = context.delete_object(
            "obj://sha256:9f2c7b1a", reference_count=2, hard_delete=False
        )
        self.assertFalse(report["deleted"])
        self.assertTrue(report["tombstoned"])
        self.assertTrue(report["references_checked"])
        self.assertTrue(report["audit_written"])
        self.assertTrue(report["conforming"])

    def test_hard_deleting_a_referenced_object_is_non_conforming(self):
        report = context.delete_object(
            "obj://sha256:9f2c7b1a", reference_count=2, hard_delete=True
        )
        self.assertFalse(report["deleted"])
        self.assertFalse(report["conforming"])
        self.assertEqual(report["reference_count"], 2)

    def test_unreferenced_object_is_deleted(self):
        report = context.delete_object(
            "obj://sha256:9f2c7b1a", reference_count=0, hard_delete=False
        )
        self.assertTrue(report["deleted"])
        self.assertFalse(report["tombstoned"])
        self.assertTrue(report["conforming"])


class CacheTests(unittest.TestCase):
    def test_cache_ttl_is_clamped_to_the_handle_ttl(self):
        report = context.cache_window(handle(), requested_ttl=900, elapsed_seconds=700)
        self.assertTrue(report["clamped"])
        self.assertEqual(report["effective_ttl"], 600)
        self.assertFalse(report["cache_hit"])

    def test_entry_inside_the_window_is_a_hit(self):
        report = context.cache_window(handle(), requested_ttl=60, elapsed_seconds=30)
        self.assertFalse(report["clamped"])
        self.assertEqual(report["effective_ttl"], 60)
        self.assertTrue(report["cache_hit"])

    def test_handle_without_ttl_keeps_the_requested_ttl(self):
        report = context.cache_window(
            {"handle": "ctx://user/profile"}, requested_ttl=900, elapsed_seconds=0
        )
        self.assertFalse(report["clamped"])
        self.assertEqual(report["effective_ttl"], 900)


class StorageTests(unittest.TestCase):
    def test_managed_store_missing_duties_is_non_conforming(self):
        report = context.storage_declaration(
            "managed_store", {"quota": False, "garbage_collection": False}
        )
        self.assertFalse(report["conforming"])
        self.assertIn("quota", report["missing"])
        self.assertIn("garbage_collection", report["missing"])

    def test_complete_managed_store_is_conforming(self):
        declares = {duty: True for duty in context.STORAGE_DUTIES}
        report = context.storage_declaration("managed_store", declares)
        self.assertTrue(report["conforming"])
        self.assertEqual(report["missing"], [])

    def test_os_native_mode_owes_no_storage_duties(self):
        report = context.storage_declaration("os_native", {})
        self.assertFalse(report["declares_managed_store"])
        self.assertTrue(report["conforming"])


class MemoryTests(unittest.TestCase):
    def test_bus_state_is_not_memory(self):
        report = context.memory_promotions(["idempotency_index", "audit_log", "task_tree"])
        self.assertFalse(report["conforming"])
        self.assertEqual(
            report["promoted_to_memory"], ["idempotency_index", "audit_log", "task_tree"]
        )

    def test_blackboard_and_metadata_are_not_memory(self):
        report = context.memory_promotions(["blackboard", "object_metadata"])
        self.assertEqual(len(report["promoted_to_memory"]), 2)

    def test_explicit_memory_source_is_conforming(self):
        report = context.memory_promotions(["memory_entries", "contacts"])
        self.assertTrue(report["conforming"])
        self.assertEqual(report["promoted_to_memory"], [])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "context.json"

    def fabric(self, **kwargs):
        return context.ContextFabric(store=JsonStore(self.path), **kwargs)

    @staticmethod
    def allow(fabric, document):
        return fabric.resolve(
            document,
            agent=document["audience"],
            granted_actions=["resolve"],
            now=now_of(document),
        )

    @staticmethod
    def deny(fabric, document):
        return fabric.resolve(
            document,
            agent=document["audience"],
            granted_actions=["read"],
            now=now_of(document),
        )

    @staticmethod
    def event(**overrides):
        event = {
            "action": "context.resolve",
            "handle": "ctx://user/profile#display_name",
            "agent": NOTES,
            "label": "personal",
            "decision": "allow",
            "reason": "resolved",
        }
        event.update(overrides)
        return event

    def seed(self, value):
        JsonStore(self.path).put(context.EVENTS_SECTION, value)

    def test_a_resolution_writes_one_event(self):
        document = handle()
        self.allow(self.fabric(), document)
        stored = JsonStore(self.path).get(context.EVENTS_SECTION)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["decision"], "allow")
        self.assertEqual(stored[0]["handle"], document["handle"])
        self.assertEqual(stored[0]["action"], "context.resolve")

    def test_a_reopen_restores_allowed_and_denied_events(self):
        document = handle()
        first = self.fabric()
        self.allow(first, document)
        with self.assertRaises(OsapError):
            self.deny(first, document)
        second = self.fabric()
        self.assertEqual([item["decision"] for item in second.audit], ["allow", "deny"])
        self.assertEqual(second.audit[1]["reason"], "missing_grant")
        self.assertEqual(second.audit, first.audit)

    def test_an_empty_store_starts_without_events(self):
        self.assertEqual(self.fabric().audit, [])

    def test_a_non_list_section_is_rejected(self):
        self.seed({"action": "context.resolve"})
        with self.assertRaises(ValueError):
            context.ContextFabric(store=JsonStore(self.path))

    def test_a_non_object_event_is_rejected(self):
        self.seed([["not", "an", "event"]])
        with self.assertRaises(ValueError):
            context.ContextFabric(store=JsonStore(self.path))

    def test_an_unknown_action_is_rejected(self):
        self.seed([self.event(action="context.open")])
        with self.assertRaises(ValueError):
            context.ContextFabric(store=JsonStore(self.path))

    def test_an_unknown_decision_is_rejected(self):
        self.seed([self.event(decision="maybe")])
        with self.assertRaises(ValueError):
            context.ContextFabric(store=JsonStore(self.path))

    def test_a_missing_or_empty_handle_is_rejected(self):
        for value in (None, ""):
            seeded = self.event()
            if value is None:
                del seeded["handle"]
            else:
                seeded["handle"] = value
            self.seed([seeded])
            with self.assertRaises(ValueError):
                context.ContextFabric(store=JsonStore(self.path))

    def test_a_missing_reason_is_rejected(self):
        seeded = self.event()
        del seeded["reason"]
        self.seed([seeded])
        with self.assertRaises(ValueError):
            context.ContextFabric(store=JsonStore(self.path))

    def test_a_non_string_agent_or_label_is_rejected(self):
        for field in ("agent", "label"):
            self.seed([self.event(**{field: 7})])
            with self.assertRaises(ValueError):
                context.ContextFabric(store=JsonStore(self.path))

    def test_a_null_agent_and_label_are_accepted(self):
        self.seed([self.event(agent=None, label=None)])
        fabric = context.ContextFabric(store=JsonStore(self.path))
        self.assertIsNone(fabric.audit[0]["agent"])
        self.assertIsNone(fabric.audit[0]["label"])

    def test_unknown_fields_are_dropped_on_restore(self):
        self.seed([self.event(extra="ignored")])
        fabric = context.ContextFabric(store=JsonStore(self.path))
        self.assertNotIn("extra", fabric.audit[0])

    def test_a_limit_keeps_only_the_newest_events(self):
        document = handle()
        fabric = self.fabric(limit=2)
        for _ in range(4):
            self.allow(fabric, document)
        self.assertEqual(len(fabric.audit), 2)
        self.assertEqual(len(JsonStore(self.path).get(context.EVENTS_SECTION)), 2)

    def test_a_zero_limit_keeps_nothing(self):
        document = handle()
        fabric = self.fabric(limit=0)
        self.allow(fabric, document)
        self.assertEqual(fabric.audit, [])
        self.assertEqual(JsonStore(self.path).get(context.EVENTS_SECTION), [])

    def test_a_limit_clamps_events_restored_from_disk(self):
        self.seed([self.event(reason=f"r{index}") for index in range(5)])
        fabric = context.ContextFabric(store=JsonStore(self.path), limit=2)
        self.assertEqual([item["reason"] for item in fabric.audit], ["r3", "r4"])

    def test_an_invalid_limit_is_rejected(self):
        for value in (-1, "3", True, 1.5):
            with self.assertRaises(ValueError):
                context.ContextFabric(limit=value)

    def test_a_custom_section_is_used(self):
        document = handle()
        fabric = context.ContextFabric(store=JsonStore(self.path), section="ctx.user.a")
        self.allow(fabric, document)
        self.assertEqual(len(JsonStore(self.path).get("ctx.user.a")), 1)
        self.assertIsNone(JsonStore(self.path).get(context.EVENTS_SECTION))

    def test_an_event_without_a_handle_identifier_is_rejected(self):
        fabric = self.fabric()
        with self.assertRaises(ValueError):
            fabric.resolve(
                {"scheme": "ctx"},
                agent=NOTES,
                granted_actions=["resolve"],
                now=now_of(handle()),
            )
        self.assertEqual(fabric.audit, [])
        self.assertIsNone(JsonStore(self.path).get(context.EVENTS_SECTION))

    def test_an_in_memory_fabric_still_works(self):
        document = handle()
        fabric = context.ContextFabric()
        self.allow(fabric, document)
        self.assertEqual(len(fabric.audit), 1)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
