# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""PCS consent-receipt signing and offline verification (standard.md §10.4).

A consent receipt MUST be signed by the user/OS consent authority and MUST be
verifiable offline; an Agent MUST NOT sign its own consent. The signature
covers the canonical JSON of the receipt with `proof` removed, so the proof
object (algorithm, key id, signature) is not itself signed. This matches the
manifest rule in `crypto.py`: key-sorted, separator-minimal UTF-8 JSON.

This module carries no key distribution. A verifier receives the PCS public
key out of band; `ConsentSigner` is the reference implementation's holder of
the signing key.
"""

from __future__ import annotations

from . import crypto
from .errors import OsapError

PROOF_FIELD = "proof"
ALGORITHM = "EdDSA"


def receipt_bytes(receipt: dict) -> bytes:
    """Return the canonical bytes a receipt signature covers."""

    return crypto.canonical_bytes(receipt, drop=(PROOF_FIELD,))


def sign_receipt(receipt: dict, private_b64: str, *, kid: str) -> dict:
    """Return a copy of `receipt` with a fresh Ed25519 `proof`."""

    signature = crypto.sign_bytes(receipt_bytes(receipt), private_b64)
    signed = dict(receipt)
    signed[PROOF_FIELD] = {"alg": ALGORITHM, "kid": kid, "sig": signature}
    return signed


def verify_receipt(receipt: dict, public_b64: str, *, kid: str | None = None) -> bool:
    """Verify a receipt proof; malformed or mismatched input returns False."""

    proof = receipt.get(PROOF_FIELD)
    if not isinstance(proof, dict):
        return False
    if proof.get("alg") != ALGORITHM:
        return False
    proof_kid = proof.get("kid")
    if not isinstance(proof_kid, str) or not proof_kid:
        return False
    if kid is not None and proof_kid != kid:
        return False
    signature = proof.get("sig")
    if not isinstance(signature, str) or not signature:
        return False
    return crypto.verify_bytes(receipt_bytes(receipt), signature, public_b64)


def require_verified_receipt(
    receipt: dict,
    public_b64: str | None,
    *,
    kid: str | None = None,
    what: str = "consent receipt",
) -> dict:
    """Raise `AUTH_DENIED` unless the receipt proof verifies (§7.7)."""

    if public_b64 is None:
        raise OsapError(
            "AUTH_DENIED",
            f"{what} cannot be verified without a PCS key",
            details={"reason": "receipt_key_unknown"},
        )
    if not verify_receipt(receipt, public_b64, kid=kid):
        raise OsapError(
            "AUTH_DENIED",
            f"{what} signature does not verify",
            details={"reason": "receipt_signature_invalid"},
        )
    return receipt


class ConsentSigner:
    """The PCS/user side: holds one Ed25519 key and signs receipts."""

    def __init__(self, private_b64: str, *, kid: str = "pcs-key-1") -> None:
        if not kid:
            raise ValueError("a consent signing key needs a kid")
        self._private_b64 = private_b64
        self.kid = kid
        self.public_key = crypto.public_from_private(private_b64)

    @classmethod
    def generate(cls, *, kid: str = "pcs-key-1") -> "ConsentSigner":
        private_b64, _public_b64 = crypto.generate_keypair()
        return cls(private_b64, kid=kid)

    def sign(self, receipt: dict) -> dict:
        return sign_receipt(receipt, self._private_b64, kid=self.kid)

    def verify(self, receipt: dict) -> bool:
        return verify_receipt(receipt, self.public_key, kid=self.kid)

    def require(self, receipt: dict) -> dict:
        return require_verified_receipt(receipt, self.public_key, kid=self.kid)

    def key_record(self) -> dict:
        """The public half a verifier needs; never include the private key."""

        return {"kid": self.kid, "public_key": self.public_key}

    def export_private(self) -> str:
        """Return the private key for a 0600 store; never send it over a Bus."""

        return self._private_b64
