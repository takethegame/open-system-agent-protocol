# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""RFC 9180 A.1.1 test vectors and P1 application tests (opaque.py)."""

import json
import unittest

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from osap import crypto, opaque
from osap.errors import OsapError

# RFC 9180 Appendix A.1.1 — DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-128-GCM, base mode.
INFO = bytes.fromhex("4f6465206f6e2061204772656369616e2055726e")
IKM_E = bytes.fromhex("7268600d403fce431561aef583ee1613527cff655c1343f29812e66706df3234")
PK_EM = bytes.fromhex("37fda3567bdbd628e88668c3c8d7e97d1d1253b6d4ea6d44c150f741f1bf4431")
IKM_R = bytes.fromhex("6db9df30aa07dd42ee5e8181afdb977e538f5e1fec8a06223f33f7013e525037")
PK_RM = bytes.fromhex("3948cfe0ad1ddb695d780e59077195da6c56506b027329794ab02bca80815c4d")
SK_RM = bytes.fromhex("4612c550263fc8ad58375df3f557aac531d26850903e55a9f23f21d8534e8ac8")
ENC = bytes.fromhex("37fda3567bdbd628e88668c3c8d7e97d1d1253b6d4ea6d44c150f741f1bf4431")
SHARED_SECRET = bytes.fromhex("fe0e18c9f024ce43799ae393c7e8fe8fce9d218875e8227b0187c04e7d2ea1fc")
KEY = bytes.fromhex("4531685d41d65f03dc48f6b8302c05b0")
BASE_NONCE = bytes.fromhex("56d890e5accaaf011cff4b7d")
EXPORTER_SECRET = bytes.fromhex("45ff1c2e220db587171952c0592d5f5ebe103f1561a2614e38f2ffd47e99e3f8")

PT = bytes.fromhex("4265617574792069732074727574682c20747275746820626561757479")

ENCODINGS = [
    (0, bytes.fromhex("436f756e742d30"),
     bytes.fromhex("f938558b5d72f1a23810b4be2ab4f84331acc02fc97babc53a52ae8218a355a96d8770ac83d07bea87e13c512a")),
    (1, bytes.fromhex("436f756e742d31"),
     bytes.fromhex("af2d7e9ac9ae7e270f46ba1f975be53c09f8d875bdc8535458c2494e8a6eab251c03d0c22a56b8ca42c2063b84")),
    (2, bytes.fromhex("436f756e742d32"),
     bytes.fromhex("498dfcabd92e8acedc281e85af1cb4e3e31c7dc394a1ca20e173cb72516491588d96a19ad4a683518973dcc180")),
    (4, bytes.fromhex("436f756e742d34"),
     bytes.fromhex("583bd32bc67a5994bb8ceaca813d369bca7b2a42408cddef5e22f880b631215a09fc0012bc69fccaa251c0246d")),
    (255, bytes.fromhex("436f756e742d323535"),
     bytes.fromhex("7175db9717964058640a3a11fb9007941a5d1757fda1a6935c805c21af32505bf106deefec4a49ac38d71c9e0a")),
    (256, bytes.fromhex("436f756e742d323536"),
     bytes.fromhex("957f9800542b0b8891badb026d79cc54597cb2d225b54c00c5238c25d05c30e3fbeda97d2e0e1aba483a2df9f2")),
]

EXPORTS = [
    (b"", 32, bytes.fromhex("3853fe2b4035195a573ffc53856e77058e15d9ea064de3e59f4961d0095250ee")),
    (bytes.fromhex("00"), 32, bytes.fromhex("2e8f0b54673c7029649d4eb9d5e33bf1872cf76d623ff164ac185da9e88c21a5")),
    (bytes.fromhex("54657374436f6e74657874"), 32,
     bytes.fromhex("e9e43065102c3836401bed8c3c3c75ae46be1639869391d62c61f1ec7af54931")),
]


class Rfc9180VectorTests(unittest.TestCase):
    """Every value below is byte-exact from RFC 9180 Appendix A.1.1."""

    def setUp(self):
        # The vector ikmE/ikmR are DeriveKeyPair seeds (§7.1.3).
        sk_e = opaque._derive_key_pair(IKM_E)
        sk_r = opaque._derive_key_pair(IKM_R)
        self.pk_em = opaque._raw_public(X25519PrivateKey.from_private_bytes(sk_e).public_key())
        self.schedule = opaque._key_schedule(
            opaque._extract_and_expand(opaque._x25519(sk_e, PK_RM), ENC + PK_RM),
            INFO,
        )

    def test_kem_shared_secret(self):
        sk_e = opaque._derive_key_pair(IKM_E)
        shared, enc = opaque._encap_with(sk_e, PK_RM)
        self.assertEqual(enc, self.pk_em)
        self.assertEqual(shared, SHARED_SECRET)
        self.assertEqual(enc, ENC)

    def test_key_schedule(self):
        self.assertEqual(self.schedule["key"], KEY)
        self.assertEqual(self.schedule["base_nonce"], BASE_NONCE)
        self.assertEqual(self.schedule["exporter_secret"], EXPORTER_SECRET)

    def test_seal_open_sequence(self):
        shared, enc = opaque._encap_with(opaque._derive_key_pair(IKM_E), PK_RM)
        schedule = opaque._key_schedule(shared, INFO)
        self.assertEqual(enc, self.pk_em)
        for seq, aad, expected_ct in ENCODINGS:
            nonce = opaque._compute_nonce(schedule["base_nonce"], seq)
            ct = opaque._aead_seal(schedule["key"], nonce, aad, PT)
            self.assertEqual(ct, expected_ct, f"seq {seq}")
            self.assertEqual(opaque._aead_open(schedule["key"], nonce, aad, ct), PT)

    def test_exported_values(self):
        enc = self.pk_em
        exported = opaque.export_bytes(
            opaque._derive_key_pair(IKM_R), ENC, INFO, b"", 32,
        )
        self.assertEqual(enc, ENC)
        self.assertEqual(exported, EXPORTS[0][2])
        for context, length, expected in EXPORTS[1:]:
            exported = opaque.export_bytes(
                opaque._derive_key_pair(IKM_R), ENC, INFO, context, length,
            )
            self.assertEqual(exported, expected)


class P1LayerTests(unittest.TestCase):
    """The OSAP P1 application layer on top of the verified primitives."""

    OUTER = {
        "osap": "0.2", "id": "msg_01", "type": "request",
        "trace_id": "trace_01", "from": "agent://com.example.notes/assistant#7f3a",
        "to": {"agent": "agent://com.example.calendar/agent#9c"},
        "task": {"id": "task_01", "mode": "supervisor"}, "ts": "2026-11-10T10:14:45Z",
    }
    INNER = {
        "auth": {"cap_id": "cap_01", "token": {"osap_cap": "0.1"}},
        "body": {"schema": "osap.calendar.propose/v1", "data": {"window": "09:00/12:00"}},
        "refs": ["obj://sha256:9f2c7b1a"],
    }

    def setUp(self):
        self.receiver = opaque.P1KeyPair.generate()
        self.sender = opaque.P1KeyPair.generate()

    def body(self, outer=None, inner=None):
        return opaque.seal_p1(outer or self.OUTER, inner or self.INNER, pk_r=self.receiver.public_key)

    def test_seal_open_round_trip(self):
        body = self.body()
        self.assertTrue(body["p1_kid"].startswith("p1_"))
        self.assertIn("enc", body)
        self.assertIn("ciphertext", body)
        inner = opaque.open_p1(self.OUTER, body, sk_r=self.receiver.private_key)
        self.assertEqual(inner, self.INNER)

    def test_tampering_with_outer_metadata_breaks_decryption(self):
        body = self.body()
        tampered = dict(self.OUTER, task={"id": "task_other", "mode": "supervisor"})
        with self.assertRaises(OsapError) as caught:
            opaque.open_p1(tampered, body, sk_r=self.receiver.private_key)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_a_wrong_receiver_key_is_rejected(self):
        other = opaque.P1KeyPair.generate()
        with self.assertRaises(OsapError) as caught:
            opaque.open_p1(self.OUTER, self.body(), sk_r=other.private_key)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_a_rotated_kid_is_reported(self):
        body = self.body()
        stale_pair = opaque.P1KeyPair.generate()
        body["p1_kid"] = stale_pair.kid
        with self.assertRaises(OsapError) as caught:
            opaque.open_p1(self.OUTER, body, sk_r=self.receiver.private_key)
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_kid_is_derived_from_the_public_key(self):
        self.assertEqual(
            self.receiver.kid,
            "p1_" + __import__("hashlib").sha256(self.receiver.public_key).hexdigest()[:16],
        )

    def test_the_inner_payload_is_not_plaintext_anywhere(self):
        body = self.body()
        self.assertNotIn(b"propose", body["ciphertext"].encode("ascii"))
        self.assertNotIn(b"cap_01", body["ciphertext"].encode("ascii"))
        self.assertNotIn(b"calendar", body["enc"].encode("ascii"))

    def test_aad_is_the_canonical_outer_serialization(self):
        body = self.body()
        # Recompute with the documented AAD rule: canonical outer fields.
        enc = __import__("base64").urlsafe_b64decode(body["enc"] + "==")
        ct = __import__("base64").urlsafe_b64decode(body["ciphertext"] + "==")
        aad = crypto.canonical_bytes(self.OUTER, drop=())
        pt = opaque.open_bytes(enc, self.receiver.private_key, opaque.P1_INFO, aad, ct)
        self.assertEqual(json.loads(pt.decode()), self.INNER)


if __name__ == "__main__":
    unittest.main()
