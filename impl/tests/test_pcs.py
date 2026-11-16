# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for PCS consent-receipt signing (standard.md §10.4)."""

import copy
import json
import unittest
from pathlib import Path

from osap import crypto, pcs
from osap.errors import OsapError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


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


if __name__ == "__main__":
    unittest.main()
