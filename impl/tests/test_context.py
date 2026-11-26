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


class DurableFabricTests(unittest.TestCase):
    """Shared fixture: one JSON file, reopened by constructing a new fabric."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "context.json"

    def fabric(self, **kwargs):
        return context.ContextFabric(store=JsonStore(self.path), **kwargs)

    def reopened(self, **kwargs):
        return context.ContextFabric(store=JsonStore(self.path), **kwargs)

    def seed(self, section, value):
        JsonStore(self.path).put(section, value)

    def stored(self, section):
        return JsonStore(self.path).get(section)


class HandleRegistryTests(DurableFabricTests):
    def test_a_registered_handle_survives_a_reopen(self):
        document = handle()
        self.fabric().register_handle(document)
        self.assertEqual(self.reopened().handle(document["handle"]), document)
        self.assertEqual(self.stored(context.HANDLES_SECTION)[document["handle"]], document)

    def test_registration_is_idempotent(self):
        document = handle()
        fabric = self.fabric()
        first = fabric.register_handle(document)
        second = fabric.register_handle(document)
        self.assertEqual(first, second)
        self.assertEqual(len(self.stored(context.HANDLES_SECTION)), 1)

    def test_a_conflicting_registration_is_rejected(self):
        document = handle()
        fabric = self.fabric()
        fabric.register_handle(document)
        with self.assertRaises(ValueError):
            fabric.register_handle(handle(label="public"))
        self.assertEqual(fabric.handle(document["handle"])["label"], "personal")

    def test_a_returned_handle_is_a_copy(self):
        document = handle()
        fabric = self.fabric()
        registered = fabric.register_handle(document)
        registered["label"] = "public"
        registered["constraints"]["allow_egress"] = True
        self.assertEqual(fabric.handle(document["handle"])["label"], "personal")
        self.assertFalse(fabric.handle(document["handle"])["constraints"]["allow_egress"])

    def test_a_string_resolves_through_the_registry(self):
        document = handle()
        fabric = self.fabric()
        fabric.register_handle(document)
        result = fabric.resolve(
            document["handle"],
            agent=document["audience"],
            granted_actions=["resolve"],
            now=now_of(document),
        )
        self.assertEqual(result["handle"], document["handle"])
        self.assertEqual(result["label"], "personal")
        self.assertEqual(result["expires_at"], document["expires_at"])

    def test_a_registered_handle_still_checks_expiry(self):
        document = handle()
        fabric = self.fabric()
        fabric.register_handle(document)
        later = parse_timestamp("2026-11-10T11:00:00Z")
        with self.assertRaises(OsapError) as caught:
            fabric.resolve(
                document["handle"],
                agent=document["audience"],
                granted_actions=["resolve"],
                now=later,
            )
        self.assertEqual(caught.exception.code, "CONTEXT_EXPIRED")
        self.assertEqual(fabric.audit[-1]["reason"], "expired")

    def test_a_registered_handle_still_checks_the_audience(self):
        document = handle()
        fabric = self.fabric()
        fabric.register_handle(document)
        with self.assertRaises(OsapError) as caught:
            fabric.resolve(
                document["handle"],
                agent=NOTES,
                granted_actions=["resolve"],
                now=now_of(document),
            )
        self.assertEqual(caught.exception.code, "CONTEXT_DENIED")
        self.assertEqual(fabric.audit[-1]["reason"], "audience")

    def test_an_unknown_identifier_is_audited_and_not_found(self):
        fabric = self.fabric()
        with self.assertRaises(OsapError) as caught:
            fabric.resolve(
                "ctx://user/profile#unknown",
                agent=NOTES,
                granted_actions=["resolve"],
                now=now_of(handle()),
            )
        self.assertEqual(caught.exception.code, "CONTEXT_NOT_FOUND")
        self.assertEqual(fabric.audit[-1]["decision"], "deny")
        self.assertEqual(fabric.audit[-1]["reason"], "not_found")
        self.assertEqual(self.stored(context.EVENTS_SECTION)[-1]["reason"], "not_found")

    def test_an_empty_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            self.fabric().resolve(
                "",
                agent=NOTES,
                granted_actions=["resolve"],
                now=now_of(handle()),
            )

    def test_drop_handle_is_persisted(self):
        document = handle()
        fabric = self.fabric()
        fabric.register_handle(document)
        self.assertTrue(fabric.drop_handle(document["handle"]))
        self.assertFalse(fabric.drop_handle(document["handle"]))
        self.assertIsNone(self.reopened().handle(document["handle"]))

    def test_an_unknown_handle_is_none(self):
        self.assertIsNone(self.fabric().handle("ctx://user/profile#unknown"))

    def test_invalid_handle_records_are_rejected(self):
        for record in (
            {"scheme": "ctx"},
            {"handle": ""},
            handle(scope=7),
            handle(ttl=-1),
            handle(ttl=True),
            handle(label="restricted"),
            handle(created_at="not-a-time"),
            handle(expires_at=""),
            handle(derived_from="obj://sha256:9f2c7b1a"),
            handle(constraints=[]),
        ):
            with self.assertRaises(ValueError):
                self.fabric().register_handle(record)

    def test_a_non_object_handle_section_is_rejected(self):
        self.seed(context.HANDLES_SECTION, [])
        with self.assertRaises(ValueError):
            self.reopened()

    def test_a_handle_key_must_match_its_record(self):
        self.seed(
            context.HANDLES_SECTION,
            {"ctx://user/profile#other": handle()},
        )
        with self.assertRaises(ValueError):
            self.reopened()

    def test_a_corrupt_handle_record_is_rejected(self):
        document = handle()
        self.seed(
            context.HANDLES_SECTION,
            {document["handle"]: {"handle": document["handle"], "ttl": -1}},
        )
        with self.assertRaises(ValueError):
            self.reopened()

    def test_handle_registration_keeps_other_sections(self):
        document = handle()
        fabric = self.fabric()
        fabric.resolve(
            document,
            agent=document["audience"],
            granted_actions=["resolve"],
            now=now_of(document),
        )
        fabric.register_handle(document)
        restored = self.reopened()
        self.assertEqual(len(restored.audit), 1)
        self.assertEqual(restored.handle(document["handle"]), document)

    def test_an_in_memory_fabric_registers_without_writing(self):
        document = handle()
        fabric = context.ContextFabric()
        fabric.register_handle(document)
        self.assertEqual(fabric.handle(document["handle"]), document)
        self.assertFalse(self.path.exists())


class BlackboardPersistenceTests(DurableFabricTests):
    TASK = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAB"

    def test_an_open_blackboard_survives_a_reopen(self):
        board = load("blackboard.json")
        self.fabric().open_blackboard(board["task_id"], board=board)
        restored = self.reopened().blackboard(board["task_id"])
        self.assertEqual(restored["blackboard"], board["blackboard"])
        self.assertEqual(restored["entries"], board["entries"])
        self.assertEqual(restored["version"], board["version"])
        self.assertEqual(restored["ttl"], board["ttl"])
        self.assertEqual(restored["created_at"], board["created_at"])
        self.assertEqual(restored["updated_at"], board["updated_at"])
        self.assertFalse(restored["closed"])
        self.assertFalse(restored["promoted_to_memory"])

    def test_open_is_idempotent_and_rejects_conflicts(self):
        fabric = self.fabric()
        first = fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}])
        self.assertEqual(
            fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}]),
            first,
        )
        with self.assertRaises(ValueError):
            fabric.open_blackboard(self.TASK, entries=[{"key": "other"}])

    def test_a_board_must_match_its_task_id(self):
        fabric = self.fabric()
        with self.assertRaises(ValueError):
            fabric.open_blackboard("task_other", board=load("blackboard.json"))

    def test_board_and_entries_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            self.fabric().open_blackboard(
                self.TASK,
                board=load("blackboard.json"),
                entries=[],
            )

    def test_entries_are_persisted_by_write(self):
        fabric = self.fabric()
        fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}])
        fabric.write_blackboard(
            self.TASK,
            [{"key": "plan"}, {"key": "draft", "value_ref": "obj://x"}],
        )
        restored = self.reopened().blackboard(self.TASK)
        self.assertEqual([entry["key"] for entry in restored["entries"]], ["plan", "draft"])

    def test_an_unknown_blackboard_is_not_found(self):
        fabric = self.fabric()
        for call in (
            lambda: fabric.write_blackboard(self.TASK, []),
            lambda: fabric.close_blackboard(self.TASK),
        ):
            with self.assertRaises(OsapError) as caught:
                call()
            self.assertEqual(caught.exception.code, "CONTEXT_NOT_FOUND")

    def test_closing_clears_entries_and_never_promotes(self):
        fabric = self.fabric()
        fabric.open_blackboard(
            self.TASK,
            entries=[{"key": "plan"}, {"key": "draft"}],
        )
        report = fabric.close_blackboard(self.TASK)
        self.assertTrue(report["closed"])
        self.assertTrue(report["cleared_or_archived"])
        self.assertEqual(report["entries_archived"], 2)
        self.assertFalse(report["promoted_to_memory"])
        restored = self.reopened().blackboard(self.TASK)
        self.assertTrue(restored["closed"])
        self.assertEqual(restored["entries"], [])
        self.assertEqual(restored["entries_archived"], 2)
        self.assertFalse(restored["promoted_to_memory"])

    def test_closing_is_idempotent(self):
        fabric = self.fabric()
        fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}])
        first = fabric.close_blackboard(self.TASK)
        second = fabric.close_blackboard(self.TASK)
        self.assertEqual(first, second)
        self.assertEqual(self.reopened().blackboard(self.TASK)["entries_archived"], 1)

    def test_a_closed_blackboard_cannot_be_reopened_or_written(self):
        fabric = self.fabric()
        fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}])
        fabric.close_blackboard(self.TASK)
        with self.assertRaises(ValueError):
            fabric.open_blackboard(self.TASK, entries=[])
        with self.assertRaises(ValueError):
            fabric.write_blackboard(self.TASK, [{"key": "plan"}])

    def test_an_invalid_task_id_is_rejected(self):
        for task_id in ("", None, 7):
            with self.assertRaises(ValueError):
                self.fabric().open_blackboard(task_id)

    def test_corrupt_blackboard_records_are_rejected(self):
        base = {
            "task_id": self.TASK,
            "blackboard": self.TASK,
            "entries": [],
            "closed": False,
            "entries_archived": 0,
            "promoted_to_memory": False,
        }
        corrupt = [
            [("entries", "not-a-list")],
            [("entries", [["not", "an", "object"]])],
            [("closed", "yes")],
            [("entries_archived", -1)],
            [("promoted_to_memory", "no")],
            [("version", -1)],
            [("ttl", True)],
            [("created_at", "not-a-time")],
            [("closed", True), ("entries", [{"key": "plan"}])],
            [("closed", True), ("promoted_to_memory", True)],
        ]
        for overrides in corrupt:
            record = dict(base)
            record.update(overrides)
            self.seed(context.BLACKBOARDS_SECTION, {self.TASK: record})
            with self.assertRaises(ValueError):
                self.reopened()

    def test_a_non_object_blackboard_section_is_rejected(self):
        self.seed(context.BLACKBOARDS_SECTION, [])
        with self.assertRaises(ValueError):
            self.reopened()

    def test_a_blackboard_key_must_match_its_record(self):
        self.seed(
            context.BLACKBOARDS_SECTION,
            {
                "task_other": {
                    "task_id": self.TASK,
                    "blackboard": self.TASK,
                    "entries": [],
                }
            },
        )
        with self.assertRaises(ValueError):
            self.reopened()

    def test_an_in_memory_fabric_keeps_a_blackboard_without_writing(self):
        fabric = context.ContextFabric()
        fabric.open_blackboard(self.TASK, entries=[{"key": "plan"}])
        self.assertEqual(fabric.blackboard(self.TASK)["entries"], [{"key": "plan"}])
        self.assertFalse(self.path.exists())


class ObjectMetadataTests(DurableFabricTests):
    URI = "obj://sha256:9f2c7b1a"

    def test_object_metadata_survives_a_reopen(self):
        self.fabric().register_object(
            self.URI,
            label="personal",
            metadata={"size": 12, "media_type": "text/plain"},
        )
        restored = self.reopened().object_state(self.URI)
        self.assertEqual(restored["uri"], self.URI)
        self.assertEqual(restored["reference_count"], 0)
        self.assertFalse(restored["deleted"])
        self.assertFalse(restored["tombstoned"])
        self.assertEqual(restored["label"], "personal")
        self.assertEqual(restored["metadata"], {"size": 12, "media_type": "text/plain"})

    def test_registration_is_idempotent_and_rejects_conflicts(self):
        fabric = self.fabric()
        first = fabric.register_object(self.URI, label="public")
        self.assertEqual(fabric.register_object(self.URI, label="public"), first)
        with self.assertRaises(ValueError):
            fabric.register_object(self.URI, label="personal")
        self.assertEqual(fabric.object_state(self.URI)["label"], "public")

    def test_retain_and_release_persist(self):
        fabric = self.fabric()
        fabric.register_object(self.URI)
        self.assertEqual(fabric.retain_object(self.URI)["reference_count"], 1)
        self.assertEqual(fabric.retain_object(self.URI)["reference_count"], 2)
        self.assertEqual(fabric.release_object(self.URI)["reference_count"], 1)
        self.assertEqual(self.reopened().object_state(self.URI)["reference_count"], 1)

    def test_release_never_goes_below_zero(self):
        fabric = self.fabric()
        fabric.register_object(self.URI)
        self.assertEqual(fabric.release_object(self.URI)["reference_count"], 0)
        self.assertEqual(fabric.release_object(self.URI)["reference_count"], 0)

    def test_delete_of_an_unreferenced_object_is_a_hard_delete(self):
        fabric = self.fabric()
        fabric.register_object(self.URI)
        report = fabric.delete_object(self.URI)
        self.assertTrue(report["deleted"])
        self.assertFalse(report["tombstoned"])
        restored = self.reopened().object_state(self.URI)
        self.assertTrue(restored["deleted"])
        self.assertFalse(restored["tombstoned"])

    def test_delete_of_a_referenced_object_tombstones(self):
        fabric = self.fabric()
        fabric.register_object(self.URI, reference_count=1)
        report = fabric.delete_object(self.URI)
        self.assertFalse(report["deleted"])
        self.assertTrue(report["tombstoned"])
        self.assertTrue(report["conforming"])
        restored = self.reopened().object_state(self.URI)
        self.assertFalse(restored["deleted"])
        self.assertTrue(restored["tombstoned"])

    def test_hard_delete_of_a_referenced_object_is_refused(self):
        fabric = self.fabric()
        fabric.register_object(self.URI, reference_count=2)
        report = fabric.delete_object(self.URI, hard_delete=True)
        self.assertFalse(report["conforming"])
        self.assertFalse(report["deleted"])
        self.assertFalse(report["tombstoned"])
        self.assertEqual(report["reason"], "referenced objects must be tombstoned, not hard-deleted")
        restored = self.reopened().object_state(self.URI)
        self.assertEqual(restored["reference_count"], 2)
        self.assertFalse(restored["deleted"])
        self.assertFalse(restored["tombstoned"])

    def test_a_deleted_object_cannot_be_retained_released_or_deleted_again(self):
        fabric = self.fabric()
        fabric.register_object(self.URI)
        fabric.delete_object(self.URI)
        for call in (
            lambda: fabric.retain_object(self.URI),
            lambda: fabric.release_object(self.URI),
            lambda: fabric.delete_object(self.URI),
        ):
            with self.assertRaises(OsapError) as caught:
                call()
            self.assertEqual(caught.exception.code, "CONTEXT_NOT_FOUND")

    def test_an_unknown_object_is_not_found(self):
        fabric = self.fabric()
        for call in (
            lambda: fabric.retain_object(self.URI),
            lambda: fabric.release_object(self.URI),
            lambda: fabric.delete_object(self.URI),
        ):
            with self.assertRaises(OsapError) as caught:
                call()
            self.assertEqual(caught.exception.code, "CONTEXT_NOT_FOUND")
        self.assertIsNone(fabric.object_state(self.URI))

    def test_invalid_object_records_are_rejected(self):
        for kwargs in (
            {"reference_count": -1},
            {"reference_count": True},
            {"label": "restricted"},
            {"metadata": []},
        ):
            with self.assertRaises(ValueError):
                self.fabric().register_object(self.URI, **kwargs)
        with self.assertRaises(ValueError):
            self.fabric().register_object("")

    def test_a_returned_object_state_is_a_copy(self):
        fabric = self.fabric()
        fabric.register_object(self.URI, metadata={"size": 1})
        state = fabric.object_state(self.URI)
        state["metadata"]["size"] = 99
        state["reference_count"] = 5
        self.assertEqual(fabric.object_state(self.URI)["metadata"]["size"], 1)
        self.assertEqual(fabric.object_state(self.URI)["reference_count"], 0)

    def test_corrupt_object_records_are_rejected(self):
        base = {
            "uri": self.URI,
            "reference_count": 0,
            "deleted": False,
            "tombstoned": False,
        }
        corrupt = [
            [("reference_count", -1)],
            [("reference_count", True)],
            [("deleted", "yes")],
            [("tombstoned", "no")],
            [("deleted", True), ("tombstoned", True)],
            [("deleted", True), ("reference_count", 1)],
            [("label", "restricted")],
            [("metadata", [])],
        ]
        for overrides in corrupt:
            record = dict(base)
            record.update(overrides)
            self.seed(context.OBJECTS_SECTION, {self.URI: record})
            with self.assertRaises(ValueError):
                self.reopened()

    def test_a_non_object_object_section_is_rejected(self):
        self.seed(context.OBJECTS_SECTION, [])
        with self.assertRaises(ValueError):
            self.reopened()

    def test_an_object_key_must_match_its_record(self):
        self.seed(
            context.OBJECTS_SECTION,
            {
                "obj://sha256:other": {
                    "uri": self.URI,
                    "reference_count": 0,
                }
            },
        )
        with self.assertRaises(ValueError):
            self.reopened()

    def test_an_in_memory_fabric_tracks_objects_without_writing(self):
        fabric = context.ContextFabric()
        fabric.register_object(self.URI, reference_count=1)
        fabric.retain_object(self.URI)
        self.assertEqual(fabric.object_state(self.URI)["reference_count"], 2)
        self.assertFalse(self.path.exists())


class AuthorizeRefsTests(unittest.TestCase):
    """§7.1: the sender must be able to pass every handle in refs."""

    def setUp(self):
        self.fabric = context.ContextFabric()
        self.handle_doc = handle()
        self.fabric.register_handle(self.handle_doc)
        self.sender = self.handle_doc["audience"]

    def refs(self, fabric, refs, *, agent=None, **kwargs):
        agent = agent or self.sender
        kwargs.setdefault("now", now_of(handle()))
        kwargs.setdefault("granted_actions", ["resolve"])
        return fabric.authorize_refs(agent=agent, refs=refs, **kwargs)

    def test_a_registered_handle_the_sender_holds_is_allowed(self):
        verdicts = self.refs(self.fabric, [self.handle_doc["handle"]])
        self.assertEqual(verdicts[self.handle_doc["handle"]]["decision"], "allow")
        self.assertEqual(len(self.fabric.audit), 1)
        self.assertEqual(self.fabric.audit[-1]["reason"], "refs_check")

    def test_an_unregistered_ref_is_unmodeled_and_passes(self):
        verdicts = self.refs(self.fabric, ["obj://sha256:9f2c7b1a"])
        self.assertEqual(verdicts["obj://sha256:9f2c7b1a"]["decision"], "unmodeled")
        self.assertEqual(self.fabric.audit, [])

    def test_a_denied_handle_is_audited(self):
        verdicts = self.refs(self.fabric, [self.handle_doc["handle"]], agent=NOTES)
        self.assertEqual(verdicts[self.handle_doc["handle"]]["decision"], "deny")
        self.assertEqual(verdicts[self.handle_doc["handle"]]["reason"], "audience")
        self.assertEqual(self.fabric.audit[-1]["decision"], "deny")

    def test_an_expired_handle_is_denied(self):
        late = parse_timestamp("2026-11-10T11:00:00Z")
        verdicts = self.refs(
            self.fabric, [self.handle_doc["handle"]], now=late
        )
        self.assertEqual(verdicts[self.handle_doc["handle"]]["reason"], "expired")

    def test_a_missing_grant_is_denied(self):
        verdicts = self.refs(
            self.fabric, [self.handle_doc["handle"]], granted_actions=[]
        )
        self.assertEqual(verdicts[self.handle_doc["handle"]]["reason"], "missing_grant")

    def test_empty_and_invalid_refs(self):
        self.assertEqual(self.refs(self.fabric, []), {})
        with self.assertRaises(ValueError):
            self.refs(self.fabric, [""])


if __name__ == "__main__":
    unittest.main()
