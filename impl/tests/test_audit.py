# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the audit chain, export, replay, and recovery (§10)."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from osap import JsonStore, audit
from osap.errors import OsapError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TRACE = "trace_01J9Z6Q3V8N2K4M7P1R5T0WX00"
MOMENT = datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)


def clock() -> datetime:
    return MOMENT


def event(**overrides) -> dict:
    document = {
        "actor": "agent://com.example.orchestrator/main#1a2b",
        "action": "task.created",
        "target": "task_01J9Z6Q3V8N2K4M7P1R5T0WXAB",
        "decision": "allow",
    }
    document.update(overrides)
    return document


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def chain() -> dict:
    return load("audit-chain.json")


def executed_pair() -> list:
    intent = chain()["events"][2]
    executed = copy.deepcopy(intent)
    executed["audit_id"] = "audit_after_intent"
    executed["action"] = "effect.executed"
    executed["phase"] = "outcome"
    executed["intent_ref"] = intent["audit_id"]
    executed["prev_hash"] = intent["hash"]
    executed["hash"] = "sha256:after"
    return [intent, executed]


class VerifyTests(unittest.TestCase):
    def test_example_chain_is_valid(self):
        self.assertTrue(audit.verify_chain(chain()))

    def test_tampered_prev_hash_is_rejected(self):
        document = chain()
        document["events"][1]["prev_hash"] = "sha256:tampered0000"
        with self.assertRaises(OsapError) as caught:
            audit.verify_chain(document)
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)
        self.assertEqual(caught.exception.details["index"], 1)

    def test_foreign_trace_is_rejected(self):
        document = chain()
        document["events"][1]["trace_id"] = "trace_other"
        with self.assertRaises(OsapError) as caught:
            audit.verify_chain(document)
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)

    def test_duplicate_audit_id_is_rejected(self):
        document = chain()
        document["events"][1]["audit_id"] = document["events"][0]["audit_id"]
        with self.assertRaises(OsapError) as caught:
            audit.verify_chain(document)
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)

    def test_invalid_event_shape_is_schema_invalid(self):
        document = chain()
        del document["events"][0]["target"]
        with self.assertRaises(OsapError) as caught:
            audit.verify_chain(document)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_effect_intent_without_intent_phase_is_schema_invalid(self):
        document = chain()
        document["events"][2]["phase"] = "outcome"
        with self.assertRaises(OsapError) as caught:
            audit.verify_chain(document)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_audit_chain_invalid_is_a_domain_extension(self):
        error = OsapError(audit.CHAIN_INVALID)
        self.assertFalse(error.standard)


class LedgerTests(unittest.TestCase):
    def ledger(self) -> audit.AuditLedger:
        return audit.AuditLedger(trace_id=TRACE, clock=clock)

    def test_append_fills_identity_time_and_links(self):
        ledger = self.ledger()
        first = ledger.append(event())
        second = ledger.append(event(action="capability.exercised", target="calendar:primary"))

        self.assertEqual(first["trace_id"], TRACE)
        self.assertTrue(first["audit_id"].startswith("audit_"))
        self.assertEqual(first["ts"], "2026-11-10T10:14:45Z")
        self.assertEqual(first["prev_hash"], audit.GENESIS_HASH)
        self.assertEqual(second["prev_hash"], first["hash"])
        self.assertEqual(ledger.head, second["hash"])
        self.assertTrue(audit.verify_chain(ledger.chain()))

    def test_explicit_audit_id_and_timestamp_are_kept(self):
        record = self.ledger().append(
            event(audit_id="audit_explicit", ts="2026-11-10T10:00:00Z")
        )
        self.assertEqual(record["audit_id"], "audit_explicit")
        self.assertEqual(record["ts"], "2026-11-10T10:00:00Z")

    def test_duplicate_audit_id_is_rejected(self):
        ledger = self.ledger()
        ledger.append(event(audit_id="audit_same"))
        with self.assertRaises(OsapError) as caught:
            ledger.append(event(audit_id="audit_same"))
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)
        self.assertEqual(len(ledger), 1)

    def test_a_foreign_trace_is_rejected(self):
        ledger = self.ledger()
        with self.assertRaises(OsapError) as caught:
            ledger.append(event(trace_id="trace_other"))
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)
        self.assertEqual(len(ledger), 0)

    def test_an_invalid_event_is_not_appended(self):
        ledger = self.ledger()
        payload = event()
        del payload["decision"]
        with self.assertRaises(OsapError) as caught:
            ledger.append(payload)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")
        self.assertEqual(len(ledger), 0)

    def test_the_returned_event_is_detached(self):
        ledger = self.ledger()
        record = ledger.append(event())
        record["target"] = "tampered"
        self.assertNotEqual(ledger.events[0]["target"], "tampered")

    def test_verify_recomputes_the_body_hash(self):
        ledger = self.ledger()
        ledger.append(event())
        ledger.events[0]["target"] = "calendar:other"
        with self.assertRaises(OsapError) as caught:
            ledger.verify()
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)
        self.assertEqual(caught.exception.details["index"], 0)

    def test_the_ledger_chain_can_be_redacted(self):
        ledger = self.ledger()
        ledger.append(
            event(
                action="capability.exercised",
                target="calendar:primary",
                policy="calendar_first_use",
                consent_receipt_id="consent_01J",
                context_refs=["obj://sha256:9f2c7b1a"],
            )
        )
        report = audit.redact_chain(ledger.chain(), salt="export-salt")
        self.assertTrue(report["chain_verified"])
        self.assertTrue(
            report["chain"]["events"][0]["target"].startswith("sha256:")
        )


class PersistedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "audit.json"

    def ledger(self, trace_id: str = TRACE) -> audit.AuditLedger:
        return audit.AuditLedger(
            trace_id=trace_id,
            store=JsonStore(self.path),
            clock=clock,
        )

    def section(self, trace_id: str = TRACE) -> str:
        return f"{audit.LEDGER_SECTION_PREFIX}{trace_id}"

    def test_events_survive_reopen(self):
        first = self.ledger()
        first.append(event())
        first.append(
            event(
                action="effect.intent",
                phase="intent",
                target="calendar:primary",
                policy="calendar_first_use",
            )
        )

        second = self.ledger()
        self.assertEqual(len(second), 2)
        self.assertEqual(second.head, first.head)
        self.assertEqual(second.chain(), first.chain())
        self.assertTrue(second.verify())

    def test_each_trace_gets_its_own_section(self):
        store = JsonStore(self.path)
        alpha = audit.AuditLedger(
            trace_id="trace_alpha", store=store, clock=clock
        )
        beta = audit.AuditLedger(trace_id="trace_beta", store=store, clock=clock)
        alpha.append(event())
        beta.append(event(action="capability.revoked", target="cap_01J"))

        reopened_alpha = self.ledger("trace_alpha")
        reopened_beta = self.ledger("trace_beta")
        self.assertEqual(len(reopened_alpha), 1)
        self.assertEqual(len(reopened_beta), 1)
        self.assertEqual(reopened_beta.events[0]["action"], "capability.revoked")
        self.assertEqual(
            sorted(store.sections()),
            [self.section("trace_alpha"), self.section("trace_beta")],
        )

    def test_a_tampered_body_is_rejected_on_reopen(self):
        self.ledger().append(event())
        store = JsonStore(self.path)
        stored = store.get(self.section())
        stored["events"][0]["target"] = "calendar:other"
        store.put(self.section(), stored)

        with self.assertRaises(OsapError) as caught:
            self.ledger()
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)

    def test_a_broken_link_is_rejected_on_reopen(self):
        ledger = self.ledger()
        ledger.append(event())
        ledger.append(event(action="capability.exercised", target="calendar:primary"))
        store = JsonStore(self.path)
        stored = store.get(self.section())
        stored["events"][1]["prev_hash"] = "sha256:tampered0000"
        store.put(self.section(), stored)

        with self.assertRaises(OsapError) as caught:
            self.ledger()
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)

    def test_a_wrong_trace_id_in_the_section_is_rejected(self):
        store = JsonStore(self.path)
        store.put(
            self.section(),
            {
                "chain_id": "audit_chain_other",
                "trace_id": "trace_other",
                "created_at": "2026-11-10T10:14:45Z",
                "events": [],
            },
        )
        with self.assertRaises(ValueError):
            self.ledger()

    def test_a_non_object_section_is_rejected(self):
        store = JsonStore(self.path)
        store.put(self.section(), [])
        with self.assertRaises(ValueError):
            self.ledger()

    def test_a_non_array_events_field_is_rejected(self):
        store = JsonStore(self.path)
        store.put(
            self.section(),
            {
                "chain_id": "audit_chain_x",
                "trace_id": TRACE,
                "created_at": "2026-11-10T10:14:45Z",
                "events": {},
            },
        )
        with self.assertRaises(ValueError):
            self.ledger()

    def test_a_corrupt_event_shape_is_chain_invalid(self):
        store = JsonStore(self.path)
        store.put(
            self.section(),
            {
                "chain_id": "audit_chain_x",
                "trace_id": TRACE,
                "created_at": "2026-11-10T10:14:45Z",
                "events": [{"audit_id": "audit_only"}],
            },
        )
        with self.assertRaises(OsapError) as caught:
            self.ledger()
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)

    def test_an_empty_ledger_writes_nothing(self):
        self.ledger()
        self.assertIsNone(JsonStore(self.path).get(self.section()))


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.document = chain()
        self.report = audit.redact_chain(self.document, salt="export-salt")

    def test_report_keeps_integrity_and_hides_plaintext(self):
        self.assertTrue(self.report["redacted"])
        self.assertTrue(self.report["chain_verified"])
        self.assertFalse(self.report["plaintext_recoverable"])

    def test_commitments_replace_sensitive_fields(self):
        first = self.report["chain"]["events"][1]
        self.assertTrue(first["target"].startswith("sha256:"))
        self.assertTrue(first["consent_receipt_id"].startswith("sha256:"))
        self.assertTrue(first["policy"].startswith("sha256:"))

    def test_context_references_are_committed_individually(self):
        intent = self.report["chain"]["events"][2]
        self.assertEqual(len(intent["context_refs"]), 1)
        self.assertTrue(intent["context_refs"][0].startswith("sha256:"))

    def test_hashes_are_preserved_for_verification(self):
        self.assertTrue(audit.verify_chain(self.report["chain"]))
        self.assertEqual(
            self.report["chain"]["events"][1]["hash"],
            self.document["events"][1]["hash"],
        )

    def test_redaction_does_not_mutate_the_source(self):
        self.assertEqual(self.document["events"][1]["target"], "calendar:primary")

    def test_different_salts_produce_different_commitments(self):
        other = audit.redact_chain(chain(), salt="another-salt")
        self.assertNotEqual(
            self.report["chain"]["events"][1]["target"],
            other["chain"]["events"][1]["target"],
        )

    def test_default_salt_is_unique_per_export(self):
        first = audit.redact_chain(chain())
        second = audit.redact_chain(chain())
        self.assertNotEqual(first["export_salt"], second["export_salt"])

    def test_tampered_chain_is_refused_before_redaction(self):
        document = chain()
        document["events"][1]["prev_hash"] = "sha256:tampered0000"
        with self.assertRaises(OsapError) as caught:
            audit.redact_chain(document)
        self.assertEqual(caught.exception.code, audit.CHAIN_INVALID)


class RecoveryTests(unittest.TestCase):
    def test_intent_without_outcome_is_unknown(self):
        report = audit.recover_effects(chain()["events"])
        self.assertEqual(report["effect_state"], "unknown")
        self.assertTrue(report["alerted"])
        self.assertTrue(report["requires_reconciliation"])

    def test_intent_and_outcome_is_complete(self):
        report = audit.recover_effects(executed_pair())
        self.assertEqual(report["effect_state"], "complete")
        self.assertFalse(report["alerted"])
        self.assertEqual(report["pending_intents"], [])

    def test_multiple_pending_intents_are_all_reported(self):
        extra = copy.deepcopy(chain()["events"][2])
        extra["audit_id"] = "audit_second_intent"
        report = audit.recover_effects([chain()["events"][2], extra])
        self.assertEqual(len(report["pending_intents"]), 2)


class TraceTests(unittest.TestCase):
    def test_single_trace_with_causation_is_complete(self):
        messages = [
            {"id": "msg_1", "trace_id": "trace_1"},
            {"id": "msg_2", "trace_id": "trace_1", "causation_id": "msg_1"},
        ]
        report = audit.trace_complete(messages)
        self.assertTrue(report["complete"])
        self.assertEqual(report["trace_ids"], ["trace_1"])

    def test_missing_causation_breaks_the_trace(self):
        messages = [
            {"id": "msg_1", "trace_id": "trace_1"},
            {"id": "msg_2", "trace_id": "trace_1"},
        ]
        report = audit.trace_complete(messages)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_causation"], ["msg_2"])

    def test_two_trace_ids_are_not_a_single_intent(self):
        messages = [
            {"id": "msg_1", "trace_id": "trace_1"},
            {"id": "msg_2", "trace_id": "trace_2", "causation_id": "msg_1"},
        ]
        report = audit.trace_complete(messages)
        self.assertFalse(report["single_trace"])


class CrossUserTests(unittest.TestCase):
    def test_same_user_is_not_cross_user(self):
        report = audit.authorize_cross_user(
            "user://local/example-user", "user://local/example-user", enabled=False
        )
        self.assertFalse(report["cross_user"])
        self.assertTrue(report["allowed"])

    def test_disabled_cross_user_traffic_is_denied(self):
        with self.assertRaises(OsapError) as caught:
            audit.authorize_cross_user(
                "user://local/example-user", "user://local/other-user", enabled=False
            )
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_enabled_without_both_consents_needs_consent(self):
        with self.assertRaises(OsapError) as caught:
            audit.authorize_cross_user(
                "user://local/example-user", "user://local/other-user", enabled=True
            )
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_REQUIRED")

    def test_enabled_with_both_consents_is_allowed(self):
        report = audit.authorize_cross_user(
            "user://local/example-user",
            "user://local/other-user",
            enabled=True,
            sender_consented=True,
            receiver_consented=True,
        )
        self.assertTrue(report["allowed"])


class ReplayTests(unittest.TestCase):
    def test_replay_runs_the_side_effect_once(self):
        report = audit.replay_effect("key", repeat=2, replay=True)
        self.assertEqual(report["side_effects"], 1)
        self.assertTrue(report["idempotent_replay"])
        self.assertEqual(report["replays"], 1)

    def test_many_replays_still_run_once(self):
        report = audit.replay_effect("key", repeat=5, replay=True)
        self.assertEqual(report["side_effects"], 1)
        self.assertEqual(report["replays"], 4)

    def test_without_replay_every_call_executes(self):
        report = audit.replay_effect("key", repeat=2, replay=False)
        self.assertEqual(report["side_effects"], 2)
        self.assertFalse(report["idempotent_replay"])


class CompromisedBusTests(unittest.TestCase):
    def test_claiming_p0_protection_is_non_conforming(self):
        report = audit.compromised_bus_declaration(
            bus_compromised=True, claims_p0_protection=True
        )
        self.assertFalse(report["conforming"])
        self.assertFalse(report["p0_protection"])
        self.assertTrue(report["p1_required"])

    def test_not_claiming_protection_is_conforming(self):
        report = audit.compromised_bus_declaration(
            bus_compromised=True, claims_p0_protection=False
        )
        self.assertTrue(report["conforming"])


if __name__ == "__main__":
    unittest.main()
