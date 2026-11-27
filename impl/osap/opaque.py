# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""HPKE base mode for the P1 Opaque Bus profile (RFC 9180; §3.6).

This is a deliberately small subset of RFC 9180: **base mode only**, with
the fixed ciphersuite DHKEM(X25519, HKDF-SHA256) + HKDF-SHA256 +
AES-128-GCM (kem_id 0x0020, kdf_id 0x0001, aead_id 0x0001). Correctness is
pinned by the RFC 9180 Appendix A.1.1 test vectors in
`impl/tests/test_opaque.py`.

Two layers live here:

* the RFC 9180 primitives (`encap`, `decap`, `key_schedule`, `seal_bytes`,
  `open_bytes`, `export_bytes`) — vector-verified building blocks; and
* the OSAP P1 application layer (`P1KeyPair`, `seal_p1`, `open_p1`) that
  implements the `docs/p1-opaque-bus.md` §4.2 decision: the **inner**
  payload (`auth`, `body`, `refs`, `consent`, `extensions`) is encrypted,
  and the **outer routing metadata** is bound as AAD so the Bus cannot
  tamper with or reorder it without breaking decryption.

Base-mode HPKE gives **no** forward secrecy against the recipient static
key alone; the P1 profile obtains rotation-window forward secrecy by key
rotation and destruction (R=24h, G=1h per the design proposal). This
module does not manage rotation; it provides the per-message primitive.

Non-normative: §3.6 says 0.1 implementations MUST NOT claim P1 support;
this module is the 0.2 draft and stays behind the same gate until the
profile is normative.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .errors import OsapError

# --- ciphersuite identifiers (RFC 9180 §7) ---------------------------------

KEM_ID = 0x0020        # DHKEM(X25519, HKDF-SHA256)
KDF_ID = 0x0001        # HKDF-SHA256
AEAD_ID = 0x0001       # AES-128-GCM
MODE_BASE = 0x00

NK = 16                # AES-128-GCM key length
NN = 12                # nonce length
NH = 32                # SHA-256 output length
NSECRET = 32           # X25519 KEM shared-secret length

P1_INFO = b"osap-p1-v0.2"

_I2OSP = int.to_bytes


def _i2osp(n: int, width: int) -> bytes:
    return n.to_bytes(width, "big")


# --- RFC 5869 Extract/Expand (SHA-256) --------------------------------------


def _extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract: PRK = HMAC-Hash(salt, ikm)."""

    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand."""

    if length > 255 * NH:
        raise ValueError("HKDF output length too large")
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


# --- RFC 9180 labeled KDF (§4) ----------------------------------------------


def _labeled_extract(suite_id: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    labeled_ikm = b"HPKE-v1" + suite_id + label + ikm
    return _extract(salt, labeled_ikm)


def _labeled_expand(suite_id: bytes, prk: bytes, label: bytes, info: bytes, length: int) -> bytes:
    labeled_info = _i2osp(length, 2) + b"HPKE-v1" + suite_id + label + info
    return _expand(prk, labeled_info, length)


# --- DHKEM(X25519, HKDF-SHA256) (RFC 9180 §4.1) ------------------------------

_KEM_SUITE = b"KEM" + _i2osp(KEM_ID, 2)


def _x25519(sk_bytes: bytes, pk_bytes: bytes) -> bytes:
    sk = X25519PrivateKey.from_private_bytes(sk_bytes)
    pk = X25519PublicKey.from_public_bytes(pk_bytes)
    return sk.exchange(pk)


def _extract_and_expand(dh: bytes, kem_context: bytes) -> bytes:
    eae_prk = _labeled_extract(_KEM_SUITE, b"", b"eae_prk", dh)
    return _labeled_expand(_KEM_SUITE, eae_prk, b"shared_secret", kem_context, NSECRET)


def _derive_key_pair(ikm: bytes) -> bytes:
    """RFC 9180 §7.1.3 DeriveKeyPair for X25519: a KDF over the seed."""

    dkp_prk = _labeled_extract(_KEM_SUITE, b"", b"dkp_prk", ikm)
    return _labeled_expand(_KEM_SUITE, dkp_prk, b"sk", b"", NSECRET)


def _encap_with(sk_e_bytes: bytes, pk_r: bytes) -> tuple[bytes, bytes]:
    """Encap with a caller-supplied ephemeral (testability per §6 of the
    design doc); production `encap` generates a fresh key pair."""

    sk_e = X25519PrivateKey.from_private_bytes(sk_e_bytes)
    enc = _raw_public(sk_e.public_key())
    dh = sk_e.exchange(X25519PublicKey.from_public_bytes(pk_r))
    shared_secret = _extract_and_expand(dh, enc + pk_r)
    return shared_secret, enc


def _decap(enc: bytes, sk_r_bytes: bytes) -> bytes:
    sk_r = X25519PrivateKey.from_private_bytes(sk_r_bytes)
    dh = sk_r.exchange(X25519PublicKey.from_public_bytes(enc))
    return _extract_and_expand(dh, enc + _raw_public(sk_r.public_key()))


def export_bytes(sk_r_bytes: bytes, enc: bytes, info: bytes, exporter_context: bytes, length: int) -> bytes:
    """RFC 9180 §6.2 receiver-side secret export; returns the exported value."""

    shared_secret = _decap(enc, sk_r_bytes)
    schedule = _key_schedule(shared_secret, info)
    return _labeled_expand(_HPKE_SUITE, schedule["exporter_secret"], b"sec", exporter_context, length)


# --- Key schedule (RFC 9180 §5.1, base mode) ---------------------------------

_HPKE_SUITE = b"HPKE" + _i2osp(KEM_ID, 2) + _i2osp(KDF_ID, 2) + _i2osp(AEAD_ID, 2)


def _key_schedule(shared_secret: bytes, info: bytes) -> dict:
    mode = _i2osp(MODE_BASE, 1)
    psk_id_hash = _labeled_extract(_HPKE_SUITE, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(_HPKE_SUITE, b"", b"info_hash", info)
    key_schedule_context = mode + psk_id_hash + info_hash
    secret = _labeled_extract(_HPKE_SUITE, shared_secret, b"secret", b"")
    return {
        "key": _labeled_expand(_HPKE_SUITE, secret, b"key", key_schedule_context, NK),
        "base_nonce": _labeled_expand(_HPKE_SUITE, secret, b"base_nonce", key_schedule_context, NN),
        "exporter_secret": _labeled_expand(_HPKE_SUITE, secret, b"exp", key_schedule_context, NH),
    }


def _compute_nonce(base_nonce: bytes, seq: int) -> bytes:
    return bytes(a ^ b for a, b in zip(base_nonce, _i2osp(seq, NN)))


def _aead_seal(key: bytes, nonce: bytes, aad: bytes, pt: bytes) -> bytes:
    return AESGCM(key).encrypt(nonce, pt, aad)


def _aead_open(key: bytes, nonce: bytes, aad: bytes, ct: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ct, aad)
    except Exception as error:  # AEAD authentication failure → fail closed
        raise OsapError("AUTH_DENIED", "HPKE decryption failed") from error


# --- single-shot primitives (RFC 9180 §6.1) -----------------------------------


def seal_bytes(pk_r: bytes, info: bytes, aad: bytes, pt: bytes, *, sk_e: bytes | None = None) -> tuple[bytes, bytes]:
    """Base-mode single-shot encryption; returns `(enc, ciphertext)`."""

    sk_e_bytes = sk_e if sk_e is not None else secrets.token_bytes(32)
    shared_secret, enc = _encap_with(sk_e_bytes, pk_r)
    schedule = _key_schedule(shared_secret, info)
    ct = _aead_seal(schedule["key"], _compute_nonce(schedule["base_nonce"], 0), aad, pt)
    return enc, ct


def open_bytes(enc: bytes, sk_r: bytes, info: bytes, aad: bytes, ct: bytes) -> bytes:
    """Base-mode single-shot decryption; raises `AUTH_DENIED` on failure."""

    shared_secret = _decap(enc, sk_r)
    schedule = _key_schedule(shared_secret, info)
    return _aead_open(schedule["key"], _compute_nonce(schedule["base_nonce"], 0), aad, ct)


# --- OSAP P1 application layer (docs/p1-opaque-bus.md §4) ----------------------


class P1KeyPair:
    """One agent's HPKE static key pair for the P1 profile."""

    def __init__(self, *, kid: str, public_key: bytes, private_key: bytes) -> None:
        self.kid = kid
        self.public_key = public_key
        self.private_key = private_key

    @classmethod
    def generate(cls) -> "P1KeyPair":
        private_key = secrets.token_bytes(32)
        public_key = _raw_public(X25519PrivateKey.from_private_bytes(private_key).public_key())
        return cls(kid=_kid_of(public_key), public_key=public_key, private_key=private_key)

    @classmethod
    def from_private_bytes(cls, private_key: bytes) -> "P1KeyPair":
        public_key = _raw_public(X25519PrivateKey.from_private_bytes(private_key).public_key())
        return cls(kid=_kid_of(public_key), public_key=public_key, private_key=private_key)


def _raw_public(key) -> bytes:
    """Raw X25519 public-key bytes across cryptography versions."""

    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _kid_of(public_key: bytes) -> str:
    return "p1_" + hashlib.sha256(public_key).hexdigest()[:16]


def seal_p1(
    outer_fields: dict,
    inner: dict,
    *,
    pk_r: bytes,
    info: bytes = P1_INFO,
    sk_e: bytes | None = None,
) -> dict:
    """Encrypt the P1 inner payload under the routing metadata (§4.2).

    `outer_fields` is the dict of visible envelope members; it is
    canonically serialized (same JCS profile as capability tokens) and
    bound as AEAD AAD, so the Bus cannot tamper with or reorder routing
    metadata without breaking decryption. Returns the `osap.opaque/v1`
    body data: `{p1_kid, enc, ciphertext}`.
    """

    from . import crypto

    aad = crypto.canonical_bytes(outer_fields, drop=())
    plaintext = crypto.canonical_bytes(inner, drop=())
    enc, ct = seal_bytes(pk_r, info, aad, plaintext, sk_e=sk_e)
    return {
        "p1_kid": _kid_of(pk_r),
        "enc": base64.urlsafe_b64encode(enc).rstrip(b"=").decode("ascii"),
        "ciphertext": base64.urlsafe_b64encode(ct).rstrip(b"=").decode("ascii"),
    }


def open_p1(
    outer_fields: dict,
    opaque_data: dict,
    *,
    sk_r: bytes,
    info: bytes = P1_INFO,
) -> dict:
    """Decrypt an `osap.opaque/v1` body; raises `AUTH_DENIED` on failure."""

    from . import crypto

    kid = opaque_data.get("p1_kid")
    if kid != _kid_of(sk_r_bytes_public(sk_r)):
        raise OsapError(
            "AUTH_DENIED",
            "opaque body carries an unknown or rotated p1_kid",
            details={"p1_kid": kid},
        )
    aad = crypto.canonical_bytes(outer_fields, drop=())
    try:
        enc = base64.urlsafe_b64decode(opaque_data["enc"] + "=" * (-len(opaque_data["enc"]) % 4))
        ct = base64.urlsafe_b64decode(
            opaque_data["ciphertext"] + "=" * (-len(opaque_data["ciphertext"]) % 4)
        )
    except (KeyError, binascii.Error, ValueError) as error:
        raise OsapError("AUTH_DENIED", "opaque body is malformed") from error
    plaintext = open_bytes(enc, sk_r, info, aad, ct)
    return json_loads(plaintext)


def sk_r_bytes_public(sk_r: bytes) -> bytes:
    return _raw_public(X25519PrivateKey.from_private_bytes(sk_r).public_key())


def json_loads(data: bytes) -> dict:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise OsapError("AUTH_DENIED", "opaque payload must be a JSON object")
    return value
