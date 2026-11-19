# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for capability tokens (standard.md §5.2–§5.6)."""

import copy
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from osap import OsapError, capability
from osap.store import JsonStore

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

PARENT_ID = "cap_01J9Z6Q3V8N2K4M7P1R5T0WXAA"
CHILD_ID = "cap_01J9Z6Q3V8N2K4M7P1R5T0WXAB"
ORCHESTRATOR = "agent://com.example.orchestrator/main#1a2b"
CALENDAR = "agent://com.example.calendar/agent#9c"
TASK = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAB"
# exp inside examples/capability.json is 2026-11-10T11:14:45Z.
VALID_AT = datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)


def token() -> dict:
    return json.loads((EXAMPLES / "capability.json").read_text(encoding="utf-8"))


def envelope() -> dict:
    return json.loads((EXAMPLES / "request.json").read_text(encoding="utf-8"))


def parent() -> dict:
    document = token()
    document["cap_id"] = PARENT_ID
    document["depth"] = 0
    return document


def child(**constraints) -> dict:
    document = token()
    if constraints:
        document["constraints"] = {**document["constraints"], **constraints}
    return document


class AttenuationTests(unittest.TestCase):
    def assert_rejected(self, requested: dict, dimension: str) -> None:
        with self.assertRaises(OsapError) as caught:
            capability.attenuate(parent(), requested)
        self.assertEqual(caught.exception.code, "CAPABILITY_ATTENUATION_INVALID")
        self.assertIn(dimension, caught.exception.details["violations"])

    def test_identity_child_is_accepted(self):
        self.assertEqual(capability.attenuate(parent(), child())["cap_id"], CHILD_ID)

    def test_narrowing_actions_is_accepted(self):
        requested = child()
        requested["actions"] = ["propose"]
        capability.attenuate(parent(), requested)

    def test_widening_actions_is_rejected(self):
        requested = child()
        requested["actions"] = ["propose", "create"]
        self.assert_rejected(requested, "actions")

    def test_widening_resources_is_rejected(self):
        requested = child()
        requested["resources"] = ["calendar:primary", "calendar:work"]
        self.assert_rejected(requested, "resources")

    def test_extending_exp_is_rejected(self):
        requested = child()
        requested["exp"] = parent()["exp"] + 1
        self.assert_rejected(requested, "exp")

    def test_shortening_exp_is_accepted(self):
        requested = child()
        requested["exp"] = parent()["exp"] - 1
        capability.attenuate(parent(), requested)

    def test_moving_nbf_earlier_is_rejected(self):
        requested = child()
        requested["nbf"] = parent()["nbf"] - 1
        self.assert_rejected(requested, "nbf")

    def test_raising_max_uses_is_rejected(self):
        self.assert_rejected(child(max_uses=6), "constraints.max_uses")

    def test_dropping_max_uses_is_rejected(self):
        requested = token()
        del requested["constraints"]["max_uses"]
        self.assert_rejected(requested, "constraints.max_uses")

    def test_lowering_max_uses_is_accepted(self):
        capability.attenuate(parent(), child(max_uses=1))

    def test_faster_rate_is_rejected(self):
        self.assert_rejected(child(rate="10/min"), "constraints.rate")

    def test_slower_rate_is_accepted(self):
        capability.attenuate(parent(), child(rate="1/min"))
        capability.attenuate(parent(), child(rate="6/hour"))

    def test_wider_budget_is_rejected(self):
        requested = child()
        requested["constraints"]["max_budget"] = {"wall_ms": 6000, "tool_calls": 2}
        self.assert_rejected(requested, "max_budget.wall_ms")

    def test_dropping_a_budget_dimension_is_rejected(self):
        requested = child()
        requested["constraints"]["max_budget"] = {"tool_calls": 2}
        self.assert_rejected(requested, "max_budget.wall_ms")

    def test_narrower_budget_is_accepted(self):
        requested = child()
        requested["constraints"]["max_budget"] = {"wall_ms": 1000, "tool_calls": 1}
        capability.attenuate(parent(), requested)

    def test_wrong_depth_is_rejected(self):
        requested = token()
        requested["depth"] = 3
        self.assert_rejected(requested, "depth")

    def test_depth_beyond_max_depth_is_rejected(self):
        ancestor = parent()
        ancestor["depth"] = 2
        requested = copy.deepcopy(ancestor)
        requested["cap_id"] = "cap_child"
        requested["depth"] = 3
        with self.assertRaises(OsapError) as caught:
            capability.attenuate(ancestor, requested)
        self.assertIn("constraints.max_depth", caught.exception.details["violations"])

    def test_delegation_must_be_allowed(self):
        ancestor = parent()
        ancestor["constraints"]["can_delegate"] = False
        with self.assertRaises(OsapError) as caught:
            capability.attenuate(ancestor, child())
        self.assertIn("constraints.can_delegate", caught.exception.details["violations"])

    def test_consent_receipt_must_survive(self):
        requested = child()
        requested["consent_receipt_id"] = "consent_other"
        self.assert_rejected(requested, "consent_receipt_id")

    def test_invalid_child_schema_is_rejected(self):
        requested = child()
        del requested["proof"]
        with self.assertRaises(OsapError) as caught:
            capability.attenuate(parent(), requested)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_rate_conversion(self):
        self.assertEqual(capability.rate_per_minute("5/min"), 5.0)
        self.assertEqual(capability.rate_per_minute("60/hour"), 1.0)
        self.assertEqual(capability.rate_per_minute("1/s"), 60.0)
        self.assertIsNone(capability.rate_per_minute("fast"))


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.authority = capability.CapabilityAuthority()

    def test_matching_binding_is_accepted(self):
        self.authority.check_binding(token(), envelope(), audience=CALENDAR)

    def test_audience_mismatch_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.authority.check_binding(
                token(), envelope(), audience="agent://com.example.notes/agent#77"
            )
        self.assertEqual(caught.exception.code, "CAPABILITY_AUDIENCE_MISMATCH")

    def test_task_mismatch_is_rejected(self):
        message = envelope()
        message["task"]["id"] = "task_other"
        with self.assertRaises(OsapError) as caught:
            self.authority.check_binding(token(), message, audience=CALENDAR)
        self.assertEqual(caught.exception.code, "CAPABILITY_TASK_MISMATCH")

    def test_subject_mismatch_is_rejected(self):
        message = envelope()
        message["from"] = "agent://com.example.notes/agent#77"
        with self.assertRaises(OsapError) as caught:
            self.authority.check_binding(token(), message, audience=CALENDAR)
        self.assertEqual(caught.exception.code, "CAPABILITY_SUBJECT_MISMATCH")

    def test_audience_is_checked_before_the_task(self):
        message = envelope()
        message["task"]["id"] = "task_other"
        with self.assertRaises(OsapError) as caught:
            self.authority.check_binding(
                token(), message, audience="agent://com.example.notes/agent#77"
            )
        self.assertEqual(caught.exception.code, "CAPABILITY_AUDIENCE_MISMATCH")


class ValidityTests(unittest.TestCase):
    def setUp(self):
        self.authority = capability.CapabilityAuthority()

    def test_token_is_valid_inside_its_window(self):
        self.authority.check_validity(token(), now=VALID_AT)

    def test_expired_token_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.authority.check_validity(token(), now=VALID_AT + timedelta(hours=2))
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_not_yet_valid_token_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.authority.check_validity(token(), now=VALID_AT - timedelta(seconds=1))
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_outside_time_window_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.authority.check_validity(token(), now=datetime(2026, 11, 18, tzinfo=timezone.utc))
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_revoked_token_is_rejected(self):
        self.authority.revoke(CHILD_ID)
        with self.assertRaises(OsapError) as caught:
            self.authority.check_validity(token(), now=VALID_AT)
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")


class RevocationTests(unittest.TestCase):
    def setUp(self):
        self.authority = capability.CapabilityAuthority()
        self.ancestor = parent()
        self.ancestor["cap_id"] = PARENT_ID
        self.middle = token()
        self.middle["cap_id"] = "cap_middle"
        self.middle["parent_cap_id"] = PARENT_ID
        self.leaf = token()
        self.leaf["cap_id"] = "cap_leaf"
        self.leaf["parent_cap_id"] = "cap_middle"
        for item in (self.ancestor, self.middle, self.leaf):
            self.authority.issue(item)

    def test_revoking_a_parent_cascades_to_descendants(self):
        self.assertEqual(self.authority.revoke(PARENT_ID), 3)
        for item in (self.ancestor, self.middle, self.leaf):
            self.assertTrue(self.authority.is_revoked(item))

    def test_revoking_a_leaf_leaves_ancestors_usable(self):
        self.authority.revoke("cap_leaf")
        self.assertFalse(self.authority.is_revoked(self.ancestor))
        self.assertFalse(self.authority.is_revoked(self.middle))
        self.assertTrue(self.authority.is_revoked(self.leaf))

    def test_unissued_revoked_parent_still_invalidates_child(self):
        # The receiving agent may only have the child token and a revocation list.
        authority = capability.CapabilityAuthority()
        authority.revoke(PARENT_ID)
        self.assertTrue(authority.is_revoked(token()))

    def test_revocation_is_audited(self):
        self.authority.revoke(PARENT_ID)
        targets = [entry["target"] for entry in self.authority.audit]
        self.assertEqual(targets, [PARENT_ID, "cap_middle", "cap_leaf"])

    def test_repeated_revocation_is_idempotent(self):
        self.assertEqual(self.authority.revoke(PARENT_ID), 3)
        self.assertEqual(self.authority.revoke(PARENT_ID), 0)
        self.assertEqual(len(self.authority.audit), 3)

    def test_revoking_middle_does_not_revoke_the_ancestor(self):
        self.assertEqual(self.authority.revoke("cap_middle"), 2)
        self.assertFalse(self.authority.is_revoked(self.ancestor))
        self.assertTrue(self.authority.is_revoked(self.middle))
        self.assertTrue(self.authority.is_revoked(self.leaf))

    def test_fan_out_tree_revokes_every_descendant_once(self):
        authority = capability.CapabilityAuthority()
        root = parent()
        root["cap_id"] = "cap_root"
        authority.issue(root)
        for index in range(6):
            branch = token()
            branch["cap_id"] = f"cap_branch_{index}"
            branch["parent_cap_id"] = "cap_root"
            authority.issue(branch)
            for leaf_index in range(4):
                leaf = token()
                leaf["cap_id"] = f"cap_leaf_{index}_{leaf_index}"
                leaf["parent_cap_id"] = branch["cap_id"]
                authority.issue(leaf)
        self.assertEqual(authority.revoke("cap_root"), 31)
        self.assertEqual(len(authority.revoked), 31)
        self.assertEqual(len(authority.audit), 31)

    def test_revoked_id_cannot_be_reissued(self):
        self.authority.revoke("cap_leaf")
        with self.assertRaises(OsapError) as caught:
            self.authority.issue(self.leaf)
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_child_of_revoked_parent_cannot_be_issued(self):
        self.authority.revoke(PARENT_ID)
        replacement = token()
        replacement["cap_id"] = "cap_after_revoke"
        replacement["parent_cap_id"] = PARENT_ID
        with self.assertRaises(OsapError) as caught:
            self.authority.issue(replacement)
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")
        self.assertEqual(
            caught.exception.details["parent_cap_id"], PARENT_ID
        )

    def test_reissuing_a_token_moves_it_to_the_new_parent(self):
        replacement = token()
        replacement["cap_id"] = "cap_leaf"
        replacement["parent_cap_id"] = PARENT_ID
        self.authority.issue(replacement)
        self.assertEqual(self.authority.revoke(PARENT_ID), 3)
        self.assertIn("cap_leaf", self.authority.revoked)


class ConsentRequirementTests(unittest.TestCase):
    def setUp(self):
        self.authority = capability.CapabilityAuthority()

    def test_l2_does_not_require_a_receipt(self):
        self.authority.require_consent(token(), risk="L2")

    def test_l3_requires_a_receipt(self):
        document = token()
        del document["consent_receipt_id"]
        with self.assertRaises(OsapError) as caught:
            self.authority.require_consent(document, risk="L3")
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_l4_requires_a_receipt(self):
        document = token()
        del document["consent_receipt_id"]
        with self.assertRaises(OsapError) as caught:
            self.authority.require_consent(document, risk="L4")
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_l3_with_a_receipt_is_accepted(self):
        self.authority.require_consent(token(), risk="L3")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"

    def authority(self) -> capability.CapabilityAuthority:
        return capability.CapabilityAuthority(store=JsonStore(self.path))

    def chain(self) -> tuple[dict, dict, dict]:
        root = parent()
        middle = token()
        middle["cap_id"] = "cap_middle"
        middle["parent_cap_id"] = PARENT_ID
        leaf = token()
        leaf["cap_id"] = "cap_leaf"
        leaf["parent_cap_id"] = "cap_middle"
        return root, middle, leaf

    def test_issued_tokens_survive_reopen(self):
        first = self.authority()
        first.issue(token())
        second = self.authority()
        self.assertIn(CHILD_ID, second.issued)
        self.assertEqual(second.issued[CHILD_ID], token())

    def test_revocation_survives_reopen(self):
        first = self.authority()
        first.issue(token())
        first.revoke(CHILD_ID)

        second = self.authority()
        self.assertTrue(second.is_revoked(token()))
        with self.assertRaises(OsapError) as caught:
            second.check_validity(token(), now=VALID_AT)
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_cascade_index_is_rebuilt_on_load(self):
        first = self.authority()
        for item in self.chain():
            first.issue(item)

        second = self.authority()
        self.assertEqual(second.revoke(PARENT_ID), 3)
        for item in self.chain():
            self.assertTrue(second.is_revoked(item))

    def test_revoked_parent_blocks_new_children_after_reopen(self):
        self.authority().issue(parent())
        self.authority().revoke(PARENT_ID)

        second = self.authority()
        with self.assertRaises(OsapError) as caught:
            second.issue(token())
        self.assertEqual(caught.exception.code, "CAPABILITY_REVOKED")

    def test_unissued_revocation_survives_reopen(self):
        self.authority().revoke(PARENT_ID)
        self.assertTrue(self.authority().is_revoked(token()))

    def test_revoked_section_is_sorted(self):
        authority = self.authority()
        for item in self.chain():
            authority.issue(item)
        authority.revoke(PARENT_ID)
        self.assertEqual(
            JsonStore(self.path).get(capability.REVOKED_SECTION),
            [PARENT_ID, "cap_leaf", "cap_middle"],
        )

    def test_audit_is_not_persisted(self):
        first = self.authority()
        first.issue(token())
        first.revoke(CHILD_ID)
        self.assertEqual(self.authority().audit, [])


class RevocationJournalTests(unittest.TestCase):
    """The durable journal that lets another process apply revocations."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"

    def authority(self) -> capability.CapabilityAuthority:
        return capability.CapabilityAuthority(store=JsonStore(self.path))

    def chain(self) -> tuple[dict, dict, dict]:
        root = parent()
        middle = token()
        middle["cap_id"] = "cap_middle"
        middle["parent_cap_id"] = PARENT_ID
        leaf = token()
        leaf["cap_id"] = "cap_leaf"
        leaf["parent_cap_id"] = "cap_middle"
        return root, middle, leaf

    def test_each_revoke_appends_contiguous_entries(self):
        authority = self.authority()
        for item in self.chain():
            authority.issue(item)
        self.assertEqual(authority.revoke(PARENT_ID), 3)
        entries = authority.revocations
        self.assertEqual([entry["seq"] for entry in entries], [1, 2, 3])
        self.assertEqual(
            [entry["cap_id"] for entry in entries],
            [PARENT_ID, "cap_middle", "cap_leaf"],
        )
        self.assertEqual(len({entry["ts"] for entry in entries}), 1)
        self.assertEqual(authority.last_seq, 3)
        self.assertEqual(authority.applied_sources(), {})

    def test_the_journal_and_the_revoked_set_persist_together(self):
        authority = self.authority()
        for item in self.chain():
            authority.issue(item)
        authority.revoke(PARENT_ID)
        reopened = self.authority()
        self.assertEqual(reopened.revocations, authority.revocations)
        self.assertEqual(reopened.last_seq, 3)
        self.assertEqual(
            reopened.revocations[0]["cap_id"], PARENT_ID
        )

    def test_repeated_revocation_writes_no_entries(self):
        authority = self.authority()
        authority.issue(parent())
        self.assertEqual(authority.revoke(PARENT_ID), 1)
        self.assertEqual(authority.revoke(PARENT_ID), 0)
        self.assertEqual(len(authority.revocations), 1)

    def test_an_in_memory_authority_journals_without_persisting(self):
        authority = capability.CapabilityAuthority()
        authority.issue(parent())
        authority.revoke(PARENT_ID)
        self.assertEqual(len(authority.revocations), 1)
        self.assertFalse(self.path.exists())

    def test_a_failed_write_rolls_back_the_journal(self):
        store = JsonStore(self.path)
        authority = capability.CapabilityAuthority(store=store)
        authority.issue(parent())
        store.put_many = lambda sections: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            authority.revoke(PARENT_ID)
        self.assertEqual(authority.revocations, [])
        self.assertEqual(authority.revoked, set())
        self.assertEqual(authority.audit, [])
        del store.put_many
        self.assertEqual(authority.revoke(PARENT_ID), 1)
        self.assertEqual(authority.last_seq, 1)

    def test_corrupt_journal_sections_are_rejected(self):
        authority = self.authority()
        authority.issue(parent())
        authority.revoke(PARENT_ID)
        good = JsonStore(self.path).get(capability.REVOCATIONS_SECTION)
        for mutate in (
            lambda value: value[0].pop("seq"),
            lambda value: [{**value[0], "seq": 0}],
            lambda value: [{**value[0], "seq": True}],
            lambda value: [{**value[0], "cap_id": ""}],
            lambda value: [{**value[0], "ts": "not-a-time"}],
            lambda value: [{**value[0], "origin": "agent://ops"}],
            lambda value: [{**value[0], "origin": "", "source_seq": 1}],
            lambda value: [{**value[0], "origin": "agent://ops", "source_seq": 0}],
            lambda value: value + [dict(value[0], seq=2)],
        ):
            JsonStore(self.path).put(capability.REVOCATIONS_SECTION, mutate(good))
            with self.assertRaises(ValueError):
                self.authority()

    def test_a_journal_entry_outside_the_revoked_set_is_rejected(self):
        authority = self.authority()
        authority.issue(parent())
        authority.revoke(PARENT_ID)
        JsonStore(self.path).put(
            capability.REVOCATIONS_SECTION,
            [{"seq": 1, "cap_id": "cap_ghost", "ts": "2026-11-10T10:14:45Z"}],
        )
        with self.assertRaises(ValueError):
            self.authority()

    def test_a_journal_sequence_gap_is_rejected_on_reopen(self):
        authority = self.authority()
        authority.issue(parent())
        authority.revoke(PARENT_ID)
        second = capability.CapabilityAuthority(store=JsonStore(self.path))
        self.assertEqual(second.revoke("cap_unissued"), 1)
        entries = JsonStore(self.path).get(capability.REVOCATIONS_SECTION)
        self.assertEqual([entry["seq"] for entry in entries], [1, 2])
        entries[1]["seq"] = 5
        JsonStore(self.path).put(capability.REVOCATIONS_SECTION, entries)
        with self.assertRaises(OsapError) as caught:
            self.authority()
        self.assertEqual(caught.exception.code, capability.REVOCATION_GAP)


class RevocationApplyTests(unittest.TestCase):
    """A replica in another process applies a source's journal batch."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "source.json"
        self.replica_path = Path(self.directory.name) / "replica.json"
        self.source = capability.CapabilityAuthority(store=JsonStore(self.source_path))
        self.replica = capability.CapabilityAuthority(store=JsonStore(self.replica_path))

    def chain(self) -> tuple[dict, dict, dict]:
        root = parent()
        middle = token()
        middle["cap_id"] = "cap_middle"
        middle["parent_cap_id"] = PARENT_ID
        leaf = token()
        leaf["cap_id"] = "cap_leaf"
        leaf["parent_cap_id"] = "cap_middle"
        return root, middle, leaf

    def journal_from_source(self) -> list[dict]:
        return JsonStore(self.source_path).get(capability.REVOCATIONS_SECTION)

    def test_a_batch_cascades_on_the_replica(self):
        for item in self.chain():
            self.source.issue(item)
        self.assertEqual(self.source.revoke(PARENT_ID), 3)
        report = self.replica.apply_revocations(
            self.journal_from_source(), source="issuer"
        )
        self.assertEqual(report["applied"], 3)
        self.assertEqual(report["revoked_now"], 3)
        self.assertEqual(report["skipped"], 0)
        self.assertEqual(report["last_seq"], 3)
        self.assertEqual(report["cursor"], 3)
        self.assertEqual(self.replica.revoked, self.source.revoked)
        self.assertTrue(self.replica.is_revoked(token()))
        self.assertTrue(self.replica.is_revoked({"cap_id": PARENT_ID}))
        self.assertEqual(self.replica.applied_sources(), {"issuer": 3})

    def test_applying_is_idempotent_and_tracks_the_sequence(self):
        for item in self.chain():
            self.source.issue(item)
        self.source.revoke(PARENT_ID)
        batch = self.journal_from_source()
        first = self.replica.apply_revocations(batch, source="issuer")
        second = self.replica.apply_revocations(batch, source="issuer")
        self.assertEqual(first["applied"], 3)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(second["skipped"], 3)
        self.assertEqual(second["last_seq"], 3)
        self.assertEqual(self.replica.revocations, self.source_journal_shape())

    def source_journal_shape(self) -> list[dict]:
        return [
            {
                "seq": index + 1,
                "cap_id": entry["cap_id"],
                "ts": entry["ts"],
                "origin": "issuer",
                "source_seq": entry["seq"],
            }
            for index, entry in enumerate(self.journal_from_source())
        ]

    def test_a_partial_batch_applies_in_order_and_a_gap_fails_closed(self):
        for item in self.chain():
            self.source.issue(item)
        self.source.revoke(PARENT_ID)
        batch = self.journal_from_source()
        first = self.replica.apply_revocations(batch[:1], source="issuer")
        self.assertEqual(first["applied"], 1)
        with self.assertRaises(OsapError) as caught:
            self.replica.apply_revocations(batch[2:], source="issuer")
        self.assertEqual(caught.exception.code, capability.REVOCATION_GAP)
        self.assertEqual(caught.exception.details["expected"], 2)
        # Fetching the missing entry makes the retry succeed unchanged.
        report = self.replica.apply_revocations(batch, source="issuer")
        self.assertEqual(report["applied"], 2)
        self.assertEqual(self.replica.last_seq, 3)

    def test_a_first_batch_must_start_at_one(self):
        # A fresh replica pulls from the source journal's genesis; a batch
        # that starts later hides earlier revocations and is refused without
        # any side effect.
        self.source.issue(parent())
        self.source.revoke(PARENT_ID)
        batch = self.journal_from_source()
        with self.assertRaises(OsapError) as caught:
            self.replica.apply_revocations([{**batch[0], "seq": 2}], source="issuer")
        self.assertEqual(caught.exception.code, capability.REVOCATION_GAP)
        self.assertEqual(self.replica.revoked, set())
        self.assertEqual(self.replica.audit, [])
        self.assertEqual(self.replica.revocations, [])
        self.assertEqual(self.replica.applied_sources(), {})
        report = self.replica.apply_revocations(batch, source="issuer")
        self.assertEqual(report["applied"], 1)
        self.assertEqual(report["cursor"], 1)

    def test_two_sources_keep_independent_cursors(self):
        self.source.issue(parent())
        self.source.revoke(PARENT_ID)
        other = capability.CapabilityAuthority()
        other.revoke("cap_unrelated")
        first = self.replica.apply_revocations(
            self.journal_from_source(), source="issuer"
        )
        second = self.replica.apply_revocations(
            [{"seq": 1, "cap_id": "cap_unrelated", "ts": "2026-11-10T10:14:45Z"}],
            source="relay",
        )
        self.assertEqual(first["cursor"], 1)
        self.assertEqual(second["cursor"], 1)
        self.assertEqual(
            self.replica.applied_sources(), {"issuer": 1, "relay": 1}
        )
        self.assertEqual(self.replica.last_seq, 2)

    def test_a_mixed_origin_batch_is_rejected(self):
        self.source.issue(parent())
        self.source.revoke(PARENT_ID)
        batch = self.journal_from_source()
        tainted = [dict(batch[0], origin="other")]
        with self.assertRaises(ValueError):
            self.replica.apply_revocations(tainted, source="issuer")
        self.assertEqual(self.replica.revocations, [])

    def test_a_corrupt_batch_is_rejected_without_side_effects(self):
        self.source.issue(parent())
        self.source.revoke(PARENT_ID)
        batch = self.journal_from_source()
        for mutate in (
            lambda value: "not a list",
            lambda value: value + [{"seq": 2}],
            lambda value: value + [dict(value[0], seq=2, ts="not-a-time")],
        ):
            with self.assertRaises(ValueError):
                self.replica.apply_revocations(mutate(list(batch)), source="issuer")
        self.assertEqual(self.replica.revoked, set())
        self.assertEqual(self.replica.last_seq, 0)
        self.assertEqual(self.replica.applied_sources(), {})

    def test_an_already_revoked_entry_does_not_recascade(self):
        self.source.issue(parent())
        self.replica.issue(parent())
        self.assertEqual(self.replica.revoke(PARENT_ID), 1)
        self.assertEqual(self.source.revoke(PARENT_ID), 1)
        report = self.replica.apply_revocations(
            self.journal_from_source(), source="issuer"
        )
        self.assertEqual(report["applied"], 1)
        self.assertEqual(report["revoked_now"], 0)
        self.assertEqual(len(self.replica.revocations), 2)
        self.assertEqual(
            self.replica.revocations[0],
            {
                "seq": 1,
                "cap_id": PARENT_ID,
                "ts": self.replica.revocations[0]["ts"],
            },
        )
        self.assertEqual(
            self.replica.revocations[1]["origin"], "issuer"
        )

    def test_a_failed_write_rolls_back_the_replica(self):
        for item in self.chain():
            self.source.issue(item)
        self.source.revoke(PARENT_ID)
        store = JsonStore(self.replica_path)
        replica = capability.CapabilityAuthority(store=store)
        store.put_many = lambda sections: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            replica.apply_revocations(self.journal_from_source(), source="issuer")
        self.assertEqual(replica.revoked, set())
        self.assertEqual(replica.revocations, [])
        self.assertEqual(replica.applied_sources(), {})
        del store.put_many
        report = replica.apply_revocations(self.journal_from_source(), source="issuer")
        self.assertEqual(report["applied"], 3)
        self.assertEqual(replica.last_seq, 3)
        self.assertEqual(replica.applied_sources(), {"issuer": 3})


class RevocationWatcherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source_path = Path(self.directory.name) / "source.json"
        self.replica_path = Path(self.directory.name) / "replica.json"
        self.source = capability.CapabilityAuthority(store=JsonStore(self.source_path))
        self.replica = capability.CapabilityAuthority(store=JsonStore(self.replica_path))

    def watcher(self, **kwargs) -> capability.RevocationWatcher:
        kwargs.setdefault("source", "issuer")
        return capability.RevocationWatcher(self.source_path, self.replica, **kwargs)

    def wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.001)
        raise AssertionError("condition was not reached before the timeout")

    def test_the_watcher_applies_revocations_automatically(self):
        watcher = self.watcher(interval=0.005)
        watcher.start()
        try:
            self.source.issue(parent())
            self.assertEqual(self.source.revoke(PARENT_ID), 1)
            self.wait_for(
                lambda: self.replica.applied_sources().get("issuer") == 1
            )
            self.assertTrue(self.replica.is_revoked({"cap_id": PARENT_ID}))
            # A later revocation is picked up by the same watcher.
            self.assertEqual(self.source.revoke("cap_second"), 1)
            self.wait_for(
                lambda: self.replica.applied_sources().get("issuer") == 2
            )
            self.assertTrue(self.replica.is_revoked({"cap_id": "cap_second"}))
        finally:
            self.assertTrue(watcher.stop())
            self.assertFalse(watcher.stop())
        # A manual poll after the watcher stops still reports the cursor.
        report = watcher.poll_once()
        self.assertEqual(report["applied"], 0)
        self.assertEqual(report["cursor"], 2)

    def test_start_twice_is_rejected(self):
        watcher = self.watcher(interval=0.05)
        with self.assertRaises(RuntimeError):
            watcher.start()
            watcher.start()
        watcher.stop()

    def test_invalid_arguments_are_rejected(self):
        for kwargs in (
            {"source": ""},
            {"interval": 0},
            {"interval": -1},
            {"interval": True},
        ):
            with self.assertRaises(ValueError):
                self.watcher(**kwargs)
        with self.assertRaises(ValueError):
            capability.RevocationWatcher(self.source_path, object())

    def test_a_failed_apply_is_retried_on_the_next_tick(self):
        watcher = self.watcher(interval=0.005)
        self.source.issue(parent())
        self.source.revoke(PARENT_ID)
        # A gap fails closed; the watcher keeps the replica empty and retries.
        journal = JsonStore(self.source_path).get(capability.REVOCATIONS_SECTION)
        poisoned = [{**journal[0], "seq": 2}]
        JsonStore(self.source_path).put(capability.REVOCATIONS_SECTION, poisoned)
        with self.assertRaises(OsapError):
            watcher.poll_once()
        self.assertEqual(self.replica.revoked, set())
        # Restoring the real journal lets the next poll succeed.
        JsonStore(self.source_path).put(capability.REVOCATIONS_SECTION, journal)
        report = watcher.poll_once()
        self.assertEqual(report["applied"], 1)
        self.assertTrue(self.replica.is_revoked({"cap_id": PARENT_ID}))


if __name__ == "__main__":
    unittest.main()
