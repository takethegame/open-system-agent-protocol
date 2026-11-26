# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the registry subset (standard.md §6.2, §6.6, §6.10)."""

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from osap import OsapError, crypto, registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

NOW = datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def record(**overrides) -> dict:
    document = {
        "record_id": "cr_01J9Z6Q3V8N2K4M7P1R5T0WX03",
        "source": {
            "kind": "vendor_registry",
            "registry": "android.appfunctions",
            "native_id": "com.example.calendar.createEvent",
            "version": "1.0.0",
        },
        "app": "app://com.example.calendar",
        "agent": "agent://com.example.calendar/agent#9c",
        "capability": {
            "cap": "cap://os/calendar/events",
            "actions": ["read", "propose", "create"],
            "resources": ["calendar:primary"],
            "schemas": ["osap.calendar.propose/v1", "osap.calendar.proposal/v1"],
            "risk": "L2",
        },
        "policy": {"visibility": "discoverable", "consent": "first_use"},
        "provenance": {
            "trust": "system",
            "signature": "base64url-example",
            "attested_at": "2026-11-10T10:00:00Z",
        },
        "freshness": {
            "observed_at": "2026-11-10T10:00:00Z",
            "expires_at": "2026-11-11T10:00:00Z",
        },
    }
    document.update(overrides)
    return document


class RecordIndexTests(unittest.TestCase):
    def test_fresh_record_is_indexed(self):
        instance = registry.Registry()
        indexed = instance.index_record(
            record(), now=datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        )
        self.assertTrue(indexed)

    def test_expired_record_is_not_indexed(self):
        instance = registry.Registry()
        indexed = instance.index_record(record(), now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertFalse(indexed)
        self.assertEqual(instance.records(), [])

    def test_missing_provenance_is_schema_invalid(self):
        document = record()
        del document["provenance"]
        with self.assertRaises(OsapError) as caught:
            registry.Registry().index_record(document)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_unsigned_manifest_is_denied(self):
        manifest = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
        with self.assertRaises(OsapError) as caught:
            registry.Registry().index_manifest(manifest)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_manifest_without_signature_is_schema_invalid(self):
        manifest = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
        del manifest["signature"]
        with self.assertRaises(OsapError) as caught:
            registry.Registry().index_manifest(manifest)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_trusted_signed_manifest_is_indexed(self):
        private, public = crypto.generate_keypair()
        manifest = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
        instance = registry.Registry()
        instance.trust(manifest["app"], public)
        instance.index_manifest(crypto.sign_document(manifest, private))
        self.assertIsNotNone(instance.manifest_for(manifest["app"]))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.instance = registry.Registry()
        now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        self.instance.index_record(record(), now=now)
        self.now = now

    def test_candidate_carries_consent_hint_not_verdict(self):
        candidates = self.instance.discover(
            {"requires": ["calendar.propose"], "schemas": ["osap.calendar.propose/v1"]},
            now=self.now,
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["consent_hint"], "first_use")
        self.assertNotIn("policy_verdict", candidate)
        self.assertFalse(registry.leaks_payload(candidates))
        self.assertFalse(registry.has_live_verdict(candidates))

    def test_risk_ceiling_filters_candidates(self):
        candidates = self.instance.discover({"risk_max": "L1"}, now=self.now)
        self.assertEqual(candidates, [])

    def test_hidden_records_are_not_discovered(self):
        document = record(record_id="cr_hidden")
        document["policy"]["visibility"] = "hidden"
        self.instance.index_record(document, now=self.now)
        candidates = self.instance.discover({"requires": ["calendar.read"]}, now=self.now)
        self.assertEqual(
            [item["record_id"] for item in candidates],
            ["cr_01J9Z6Q3V8N2K4M7P1R5T0WX03"],
        )

    def test_expired_records_drop_out_of_discovery(self):
        later = self.now + timedelta(days=2)
        self.assertEqual(self.instance.discover({"requires": ["calendar.read"]}, now=later), [])

    def test_payload_leak_is_detected(self):
        self.assertTrue(registry.leaks_payload([{"record_id": "cr_1", "data": {"secret": 1}}]))
        self.assertTrue(registry.has_live_verdict([{"policy_verdict": "allow"}]))


class DescriptorLookupTests(unittest.TestCase):
    def test_manifest_descriptor_is_resolved_to_an_agent(self):
        instance = registry.Registry()
        self.assertIsNone(instance.capability_descriptor("cap://os/calendar/events"))

        private, public = crypto.generate_keypair()
        manifest = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
        instance.trust(manifest["app"], public)
        instance.index_manifest(crypto.sign_document(manifest, private))

        descriptor, agent = instance.capability_descriptor("cap://os/calendar/events")
        self.assertEqual(descriptor["cap"], "cap://os/calendar/events")
        self.assertEqual(agent, manifest["agents"][0]["agent"])
        self.assertEqual(instance.risk_of("cap://os/calendar/events"), descriptor["risk"])

    def test_record_descriptor_is_resolved(self):
        instance = registry.Registry()
        instance.index_record(record(), now=datetime(2026, 11, 10, 12, tzinfo=timezone.utc))
        descriptor, agent = instance.capability_descriptor("cap://os/calendar/events")
        self.assertEqual(agent, "agent://com.example.calendar/agent#9c")
        self.assertEqual(instance.risk_of("cap://os/calendar/events"), "L2")

    def test_unknown_capability_has_no_risk(self):
        self.assertIsNone(registry.Registry().risk_of("cap://os/unknown"))


class DescribeTests(unittest.TestCase):
    """§7.2: describe is the idempotent detail lookup behind discover."""

    def setUp(self):
        self.registry = registry.Registry()
        record = copy.deepcopy(load("capability-record.json"))
        record["agent"] = "agent://com.example.calendar/agent#9c"
        record["record_id"] = "rec_calendar"
        self.registry.index_record(record, now=NOW)
        second = copy.deepcopy(record)
        second["record_id"] = "rec_calendar_tasks"
        second["capability"]["cap"] = "cap://os/tasks/orchestrate"
        second["policy"]["visibility"] = "restricted"
        self.registry.index_record(second, now=NOW)
        self.record_id = "rec_calendar"

    def describe(self, target):
        return self.registry.describe(target, now=NOW)

    def test_describe_by_agent_returns_full_records(self):
        records = self.describe({"agent": "agent://com.example.calendar/agent#9c"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_id"], self.record_id)
        self.assertEqual(records[0]["capability"]["risk"], "L2")
        self.assertIn("policy", records[0])

    def test_describe_by_capability_uri(self):
        records = self.describe({"capability": "cap://os/calendar/events"})
        self.assertEqual([item["record_id"] for item in records], [self.record_id])

    def test_describe_by_record_id(self):
        records = self.describe({"record_id": self.record_id})
        self.assertEqual(len(records), 1)

    def test_describe_bare_string_is_an_agent_selector(self):
        self.assertEqual(len(self.describe("agent://com.example.calendar/agent#9c")), 1)

    def test_restricted_records_are_not_describable(self):
        self.assertEqual(self.describe({"record_id": "rec_calendar_tasks"}), [])
        self.assertEqual(
            self.describe({"capability": "cap://os/tasks/orchestrate"}), []
        )

    def test_unknown_targets_return_empty(self):
        self.assertEqual(self.describe({"agent": "agent://com.example.other/agent#1"}), [])
        self.assertEqual(self.describe({"record_id": "rec_missing"}), [])

    def test_stale_records_are_excluded(self):
        stale = copy.deepcopy(load("capability-record.json"))
        stale["agent"] = "agent://com.example.stale/agent#1"
        stale["record_id"] = "rec_stale"
        stale["freshness"]["expires_at"] = "2026-11-10T00:00:00Z"
        self.registry.index_record(stale, now=NOW)
        self.assertEqual(self.describe({"agent": "agent://com.example.stale/agent#1"}), [])

    def test_invalid_selectors_are_rejected(self):
        for target in ({}, {"record_id": ""}, {"agent": 7}, {"agent": "x", "extra": 1}, "not a dict" if False else None):
            with self.assertRaises(ValueError):
                self.describe(target)

    def test_returns_detached_copies(self):
        records = self.describe({"agent": "agent://com.example.calendar/agent#9c"})
        records[0]["capability"]["risk"] = "L0"
        self.assertEqual(
            self.describe({"record_id": self.record_id})[0]["capability"]["risk"], "L2"
        )


if __name__ == "__main__":
    unittest.main()
