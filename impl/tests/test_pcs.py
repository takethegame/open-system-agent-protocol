# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for PCS consent-receipt signing (standard.md §10.4)."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from osap import JsonStore, crypto, pcs
from osap.errors import OsapError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
MOMENT = datetime(2026, 11, 10, 10, 14, 45, tzinfo=timezone.utc)


def clock() -> datetime:
    return MOMENT


def registry() -> pcs.KeyRegistry:
    return pcs.KeyRegistry(clock=clock)


def receipt() -> dict:
    document = json.loads((EXAMPLES / "consent-receipt.json").read_text(encoding="utf-8"))
    return {key: value for key, value in document.items() if key != "proof"}


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.signer = pcs.ConsentSigner.generate(kid="pcs-test-1")

    def test_sign_adds_a_verifiable_proof(self):
        signed = self.signer.sign(receipt())
        self.assertEqual(signed["proof"]["alg"], "EdDSA")
        self.assertEqual(signed["proof"]["kid"], "pcs-test-1")
        self.assertTrue(signed["proof"]["sig"])
        self.assertTrue(self.signer.verify(signed))

    def test_signing_is_deterministic(self):
        first = self.signer.sign(receipt())
        second = self.signer.sign(receipt())
        self.assertEqual(first["proof"]["sig"], second["proof"]["sig"])

    def test_tampering_with_a_signed_field_fails(self):
        for field, value in (
            ("task_id", "task_other"),
            ("cap_id", "cap_other"),
            ("actions", ["calendar.read"]),
            ("decision", "deny"),
        ):
            with self.subTest(field=field):
                signed = self.signer.sign(receipt())
                signed[field] = value
                self.assertFalse(self.signer.verify(signed))

    def test_proof_metadata_is_outside_the_signature(self):
        signed = self.signer.sign(receipt())
        changed = copy.deepcopy(signed)
        changed["proof"]["kid"] = "another-kid"
        self.assertTrue(pcs.verify_receipt(changed, self.signer.public_key))
        self.assertFalse(self.signer.verify(changed))

    def test_a_different_key_does_not_verify(self):
        other = pcs.ConsentSigner.generate(kid="pcs-test-1")
        signed = self.signer.sign(receipt())
        self.assertFalse(other.verify(signed))
        self.assertFalse(pcs.verify_receipt(signed, other.public_key))

    def test_malformed_proofs_are_rejected(self):
        signed = self.signer.sign(receipt())
        cases = {
            "missing": None,
            "not-an-object": "signature",
            "wrong-alg": {**signed["proof"], "alg": "RS256"},
            "empty-kid": {**signed["proof"], "kid": ""},
            "empty-sig": {**signed["proof"], "sig": ""},
        }
        for name, proof in cases.items():
            with self.subTest(name=name):
                document = copy.deepcopy(signed)
                if proof is None:
                    del document["proof"]
                else:
                    document["proof"] = proof
                self.assertFalse(pcs.verify_receipt(document, self.signer.public_key))

    def test_require_returns_the_receipt(self):
        signed = self.signer.sign(receipt())
        self.assertIs(self.signer.require(signed), signed)

    def test_require_rejects_a_bad_signature(self):
        signed = self.signer.sign(receipt())
        signed["actions"] = ["calendar.read"]
        with self.assertRaises(OsapError) as caught:
            self.signer.require(signed)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")
        self.assertEqual(caught.exception.details["reason"], "receipt_signature_invalid")

    def test_require_rejects_an_unknown_key(self):
        signed = self.signer.sign(receipt())
        with self.assertRaises(OsapError) as caught:
            pcs.require_verified_receipt(signed, None)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")
        self.assertEqual(caught.exception.details["reason"], "receipt_key_unknown")

    def test_key_record_carries_only_the_public_half(self):
        private_b64, public_b64 = crypto.generate_keypair()
        signer = pcs.ConsentSigner(private_b64, kid="known-key")
        self.assertEqual(
            signer.key_record(),
            {"kid": "known-key", "public_key": public_b64},
        )

    def test_generated_signers_use_distinct_keys(self):
        other = pcs.ConsentSigner.generate(kid="pcs-test-1")
        self.assertNotEqual(self.signer.public_key, other.public_key)


class KeyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.signer = pcs.ConsentSigner.generate(kid="pcs-registry-1")
        self.registry = registry()
        self.registry.register(self.signer.kid, self.signer.public_key)

    def test_a_registered_key_is_active(self):
        record = self.registry.key("pcs-registry-1")
        self.assertEqual(record["kid"], "pcs-registry-1")
        self.assertEqual(record["public_key"], self.signer.public_key)
        self.assertEqual(record["status"], pcs.ACTIVE)
        self.assertEqual(record["created_at"], "2026-11-10T10:14:45Z")
        self.assertIsNone(record["not_before"])
        self.assertIsNone(record["not_after"])
        self.assertIsNone(record["retired_at"])
        self.assertIsNone(record["grace_until"])
        self.assertIsNone(record["revoked_at"])
        self.assertEqual(self.registry.state_of("pcs-registry-1"), pcs.ACTIVE)
        self.assertTrue(self.registry.usable("pcs-registry-1"))

    def test_an_unknown_key_has_no_state(self):
        self.assertIsNone(self.registry.state_of("missing"))
        self.assertIsNone(self.registry.key("missing"))
        self.assertFalse(self.registry.usable("missing"))

    def test_a_duplicate_kid_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.register("pcs-registry-1", self.signer.public_key)
        self.assertEqual(len(self.registry.keys()), 1)

    def test_a_malformed_key_is_rejected(self):
        for kid, public_key in (
            ("", self.signer.public_key),
            (None, self.signer.public_key),
            ("bad-key", "not-base64"),
            ("short-key", crypto.b64encode(b"too-short")),
            ("none-key", None),
        ):
            with self.subTest(kid=kid):
                with self.assertRaises(ValueError):
                    self.registry.register(kid, public_key)

    def test_an_inverted_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.register(
                "window-key",
                self.signer.public_key,
                not_before=MOMENT + timedelta(seconds=1),
                not_after=MOMENT,
            )

    def test_a_non_datetime_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.register(
                "window-key", self.signer.public_key, not_before="2026-11-10T10:14:45Z"
            )

    def test_not_before_delays_usability(self):
        self.registry.register(
            "future-key",
            self.signer.public_key,
            not_before=MOMENT + timedelta(minutes=1),
        )
        self.assertFalse(self.registry.usable("future-key"))
        self.assertTrue(
            self.registry.usable("future-key", at=MOMENT + timedelta(minutes=2))
        )

    def test_not_after_ends_usability(self):
        self.registry.register(
            "expiring-key",
            self.signer.public_key,
            not_after=MOMENT + timedelta(minutes=1),
        )
        self.assertTrue(
            self.registry.usable("expiring-key", at=MOMENT + timedelta(seconds=30))
        )
        self.assertFalse(
            self.registry.usable("expiring-key", at=MOMENT + timedelta(minutes=2))
        )

    def test_revocation_is_terminal_and_idempotent(self):
        self.assertTrue(self.registry.revoke("pcs-registry-1"))
        self.assertFalse(self.registry.revoke("pcs-registry-1"))
        self.assertEqual(self.registry.state_of("pcs-registry-1"), pcs.REVOKED)
        self.assertFalse(self.registry.usable("pcs-registry-1"))
        self.assertEqual(
            self.registry.key("pcs-registry-1")["revoked_at"],
            "2026-11-10T10:14:45Z",
        )

    def test_revoking_an_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.revoke("missing")

    def test_rotation_retires_the_old_key_with_grace(self):
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        record = self.registry.rotate(
            "pcs-registry-1",
            replacement.public_key,
            new_kid="pcs-registry-2",
            grace_seconds=30,
        )

        self.assertEqual(record["kid"], "pcs-registry-2")
        self.assertEqual(record["status"], pcs.ACTIVE)
        self.assertEqual(self.registry.state_of("pcs-registry-1"), pcs.RETIRED)
        retired = self.registry.key("pcs-registry-1")
        self.assertEqual(retired["retired_at"], "2026-11-10T10:14:45Z")
        self.assertEqual(retired["grace_until"], "2026-11-10T10:15:15Z")
        self.assertTrue(
            self.registry.usable("pcs-registry-1", at=MOMENT + timedelta(seconds=10))
        )
        self.assertFalse(
            self.registry.usable("pcs-registry-1", at=MOMENT + timedelta(seconds=31))
        )
        self.assertTrue(self.registry.usable("pcs-registry-2"))

    def test_rotation_without_grace_retires_immediately(self):
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        self.registry.rotate(
            "pcs-registry-1",
            replacement.public_key,
            new_kid="pcs-registry-2",
        )
        self.assertTrue(self.registry.usable("pcs-registry-1"))
        self.assertFalse(
            self.registry.usable("pcs-registry-1", at=MOMENT + timedelta(seconds=1))
        )

    def test_rotation_rejections_leave_the_registry_unchanged(self):
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        other = pcs.ConsentSigner.generate(kid="pcs-registry-3")
        self.registry.register("pcs-registry-3", other.public_key)

        cases = {
            "unknown": ("missing", replacement.public_key, "pcs-registry-2"),
            "same-kid": ("pcs-registry-1", replacement.public_key, "pcs-registry-1"),
            "existing-kid": ("pcs-registry-1", replacement.public_key, "pcs-registry-3"),
            "bad-key": ("pcs-registry-1", "not-base64", "pcs-registry-4"),
            "negative-grace": ("pcs-registry-1", replacement.public_key, "pcs-registry-5"),
        }
        for name, (kid, public_key, new_kid) in cases.items():
            with self.subTest(name=name):
                grace = -1 if name == "negative-grace" else 0
                with self.assertRaises(ValueError):
                    self.registry.rotate(
                        kid, public_key, new_kid=new_kid, grace_seconds=grace
                    )
        self.assertEqual(self.registry.state_of("pcs-registry-1"), pcs.ACTIVE)
        self.assertIsNone(self.registry.key("pcs-registry-4"))

    def test_a_revoked_key_cannot_be_rotated(self):
        self.registry.revoke("pcs-registry-1")
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        with self.assertRaises(ValueError):
            self.registry.rotate(
                "pcs-registry-1", replacement.public_key, new_kid="pcs-registry-2"
            )

    def test_a_retired_key_cannot_be_rotated_again(self):
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        self.registry.rotate(
            "pcs-registry-1", replacement.public_key, new_kid="pcs-registry-2"
        )
        with self.assertRaises(ValueError):
            self.registry.rotate(
                "pcs-registry-1", replacement.public_key, new_kid="pcs-registry-3"
            )

    def test_returned_records_are_detached(self):
        record = self.registry.key("pcs-registry-1")
        record["status"] = pcs.REVOKED
        record["public_key"] = "tampered"
        self.assertEqual(self.registry.state_of("pcs-registry-1"), pcs.ACTIVE)
        self.assertEqual(
            self.registry.key("pcs-registry-1")["public_key"], self.signer.public_key
        )

    def test_keys_are_ordered_by_kid(self):
        second = pcs.ConsentSigner.generate(kid="aaa-key")
        self.registry.register("aaa-key", second.public_key)
        self.assertEqual(
            [record["kid"] for record in self.registry.keys()],
            ["aaa-key", "pcs-registry-1"],
        )

    def test_verify_receipt_resolves_the_kid(self):
        signed = self.signer.sign(receipt())
        self.assertTrue(self.registry.verify_receipt(signed))
        self.assertIs(self.registry.require_receipt(signed), signed)

    def test_verify_receipt_rejects_a_tampered_body(self):
        signed = self.signer.sign(receipt())
        signed["actions"] = ["calendar.read"]
        self.assertFalse(self.registry.verify_receipt(signed))
        with self.assertRaises(OsapError) as caught:
            self.registry.require_receipt(signed)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")
        self.assertEqual(caught.exception.details["reason"], "receipt_signature_invalid")

    def test_verify_receipt_rejects_an_unknown_kid(self):
        signed = self.signer.sign(receipt())
        signed["proof"]["kid"] = "missing"
        self.assertFalse(self.registry.verify_receipt(signed))
        with self.assertRaises(OsapError) as caught:
            self.registry.require_receipt(signed)
        self.assertEqual(caught.exception.details["reason"], "receipt_key_unknown")

    def test_verify_receipt_rejects_a_malformed_proof(self):
        signed = self.signer.sign(receipt())
        for proof in (None, "signature", {"kid": ""}, {"kid": 5}, {}):
            with self.subTest(proof=proof):
                document = copy.deepcopy(signed)
                if proof is None:
                    document.pop("proof")
                else:
                    document["proof"] = proof
                self.assertFalse(self.registry.verify_receipt(document))
                with self.assertRaises(OsapError) as caught:
                    self.registry.require_receipt(document)
                self.assertEqual(
                    caught.exception.details["reason"], "receipt_key_unknown"
                )

    def test_verify_receipt_rejects_a_revoked_key(self):
        signed = self.signer.sign(receipt())
        self.registry.revoke(self.signer.kid)
        self.assertFalse(self.registry.verify_receipt(signed))
        with self.assertRaises(OsapError) as caught:
            self.registry.require_receipt(signed)
        self.assertEqual(caught.exception.details["reason"], "receipt_key_revoked")

    def test_verify_receipt_rejects_an_expired_key(self):
        self.registry.register(
            "expiring-key",
            self.signer.public_key,
            not_after=MOMENT,
        )
        signed = self.signer.sign(receipt())
        signed["proof"]["kid"] = "expiring-key"
        later = MOMENT + timedelta(seconds=1)
        self.assertFalse(self.registry.verify_receipt(signed, at=later))
        with self.assertRaises(OsapError) as caught:
            self.registry.require_receipt(signed, at=later)
        self.assertEqual(caught.exception.details["reason"], "receipt_key_expired")

    def test_verify_receipt_rejects_a_future_key(self):
        self.registry.register(
            "future-key",
            self.signer.public_key,
            not_before=MOMENT + timedelta(minutes=1),
        )
        signed = self.signer.sign(receipt())
        signed["proof"]["kid"] = "future-key"
        self.assertFalse(self.registry.verify_receipt(signed))
        with self.assertRaises(OsapError) as caught:
            self.registry.require_receipt(signed)
        self.assertEqual(
            caught.exception.details["reason"], "receipt_key_not_yet_valid"
        )

    def test_a_retired_key_still_verifies_inside_the_grace_window(self):
        replacement = pcs.ConsentSigner.generate(kid="pcs-registry-2")
        signed = self.signer.sign(receipt())
        self.registry.rotate(
            self.signer.kid,
            replacement.public_key,
            new_kid="pcs-registry-2",
            grace_seconds=60,
        )
        inside = MOMENT + timedelta(seconds=30)
        after = MOMENT + timedelta(seconds=61)
        self.assertTrue(self.registry.verify_receipt(signed, at=inside))
        self.assertFalse(self.registry.verify_receipt(signed, at=after))


class PersistedKeyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "pcs.json"

    def registry(self) -> pcs.KeyRegistry:
        return pcs.KeyRegistry(store=JsonStore(self.path), clock=clock)

    def test_keys_survive_reopen(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-persisted-1")
        first = self.registry()
        first.register(signer.kid, signer.public_key)

        second = self.registry()
        self.assertEqual(second.keys(), first.keys())
        self.assertTrue(second.usable("pcs-persisted-1"))
        signed = signer.sign(receipt())
        self.assertTrue(second.verify_receipt(signed))

    def test_rotation_and_revocation_survive_reopen(self):
        old = pcs.ConsentSigner.generate(kid="pcs-old")
        new = pcs.ConsentSigner.generate(kid="pcs-new")
        first = self.registry()
        first.register(old.kid, old.public_key)
        first.register("pcs-doomed", old.public_key)
        first.rotate(old.kid, new.public_key, new_kid=new.kid, grace_seconds=30)
        first.revoke("pcs-doomed")

        second = self.registry()
        self.assertEqual(second.state_of("pcs-old"), pcs.RETIRED)
        self.assertEqual(second.state_of("pcs-new"), pcs.ACTIVE)
        self.assertEqual(second.state_of("pcs-doomed"), pcs.REVOKED)
        self.assertEqual(second.key("pcs-old")["grace_until"], "2026-11-10T10:15:15Z")
        self.assertTrue(
            second.usable("pcs-old", at=MOMENT + timedelta(seconds=10))
        )
        self.assertFalse(second.usable("pcs-doomed"))

    def test_windows_and_timestamps_round_trip(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-window")
        first = self.registry()
        first.register(
            signer.kid,
            signer.public_key,
            not_before=MOMENT - timedelta(minutes=5),
            not_after=MOMENT + timedelta(minutes=5),
        )
        reopened = self.registry().key(signer.kid)
        self.assertEqual(reopened["not_before"], "2026-11-10T10:09:45Z")
        self.assertEqual(reopened["not_after"], "2026-11-10T10:19:45Z")
        self.assertEqual(reopened["created_at"], "2026-11-10T10:14:45Z")

    def test_every_mutation_rewrites_only_the_keys_section(self):
        store = JsonStore(self.path)
        store.put("other.section", {"kept": True})
        signer = pcs.ConsentSigner.generate(kid="pcs-section")
        registry = pcs.KeyRegistry(store=store, clock=clock)
        registry.register(signer.kid, signer.public_key)
        registry.revoke(signer.kid)

        reopened = JsonStore(self.path)
        self.assertEqual(reopened.sections(), ["other.section", pcs.KEYS_SECTION])
        self.assertEqual(reopened.get("other.section"), {"kept": True})
        self.assertEqual(reopened.get(pcs.KEYS_SECTION)["pcs-section"]["status"], pcs.REVOKED)

    def test_an_empty_registry_writes_nothing(self):
        self.registry()
        self.assertIsNone(JsonStore(self.path).get(pcs.KEYS_SECTION))

    def test_a_non_object_section_is_rejected(self):
        JsonStore(self.path).put(pcs.KEYS_SECTION, [])
        with self.assertRaises(ValueError):
            self.registry()

    def test_a_non_object_record_is_rejected(self):
        JsonStore(self.path).put(pcs.KEYS_SECTION, {"kid": "not-an-object"})
        with self.assertRaises(ValueError):
            self.registry()

    def test_a_mismatched_kid_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-b",
                    "public_key": crypto.generate_keypair()[1],
                    "status": pcs.ACTIVE,
                    "created_at": "2026-11-10T10:14:45Z",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_an_invalid_public_key_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": "not-base64",
                    "status": pcs.ACTIVE,
                    "created_at": "2026-11-10T10:14:45Z",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_an_unknown_status_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": crypto.generate_keypair()[1],
                    "status": "expired",
                    "created_at": "2026-11-10T10:14:45Z",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_a_missing_created_at_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": crypto.generate_keypair()[1],
                    "status": pcs.ACTIVE,
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_a_malformed_optional_timestamp_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": crypto.generate_keypair()[1],
                    "status": pcs.ACTIVE,
                    "created_at": "2026-11-10T10:14:45Z",
                    "not_after": 17,
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_a_malformed_created_at_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": crypto.generate_keypair()[1],
                    "status": pcs.ACTIVE,
                    "created_at": "not-a-timestamp",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()

    def test_an_inverted_stored_window_is_rejected(self):
        JsonStore(self.path).put(
            pcs.KEYS_SECTION,
            {
                "kid-a": {
                    "kid": "kid-a",
                    "public_key": crypto.generate_keypair()[1],
                    "status": pcs.ACTIVE,
                    "created_at": "2026-11-10T10:14:45Z",
                    "not_before": "2026-11-10T11:00:00Z",
                    "not_after": "2026-11-10T10:00:00Z",
                }
            },
        )
        with self.assertRaises(ValueError):
            self.registry()


if __name__ == "__main__":
    unittest.main()
