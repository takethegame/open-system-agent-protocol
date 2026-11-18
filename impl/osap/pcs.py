# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""PCS consent-receipt signing and offline verification (standard.md §10.4).

A consent receipt MUST be signed by the user/OS consent authority and MUST be
verifiable offline; an Agent MUST NOT sign its own consent. The signature
covers the canonical JSON of the receipt with `proof` removed, so the proof
object (algorithm, key id, signature) is not itself signed. This matches the
manifest rule in `crypto.py`: key-sorted, separator-minimal UTF-8 JSON.

`ConsentSigner` is the reference implementation's holder of the signing key.
`KeyRegistry` is the distribution half: it stores only public keys, keyed by
`kid`, and supports registration, rotation with a grace window, expiry, and
revocation. When backed by a `JsonStore`, the registry survives a restart, so
a verifier can resolve a receipt's `kid` without an out-of-band copy (§4.5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import crypto
from .clock import parse_timestamp
from .errors import OsapError
from .store import JsonStore

PROOF_FIELD = "proof"
ALGORITHM = "EdDSA"

#: Lifecycle states a registered key can be in.
ACTIVE = "active"
RETIRED = "retired"
REVOKED = "revoked"
STATUSES = (ACTIVE, RETIRED, REVOKED)

#: Section a persisted registry writes.
KEYS_SECTION = "pcs.keys"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


class KeyRegistry:
    """Public PCS keys by `kid`, with rotation, expiry, and revocation (§4.5).

    The registry stores only public keys. A key is registered once and can
    then move from `active` to `retired` (on rotation, with an optional grace
    window) or to `revoked` (terminal). `state_of` reports that stored
    lifecycle state; `usable` adds the time checks (`not_before`, `not_after`,
    and the retirement grace window).

    With a `JsonStore` every mutation rewrites the single `pcs.keys` section,
    so a verifier resolves the same keys after a restart. A corrupt or
    misshapen section raises `ValueError` instead of restoring partial state.
    """

    def __init__(self, *, store: JsonStore | None = None, clock=None) -> None:
        self._store = store
        self._clock = clock or _now
        self._keys: dict[str, dict] = {}
        if store is not None:
            self._restore()

    # --- persistence -------------------------------------------------------

    def _restore(self) -> None:
        loaded = self._store.get(KEYS_SECTION)
        if loaded is None:
            return
        if not isinstance(loaded, dict):
            raise ValueError(f"{KEYS_SECTION!r} must be a JSON object")
        restored: dict[str, dict] = {}
        for kid, stored in loaded.items():
            if not isinstance(stored, dict):
                raise ValueError(f"PCS key {kid!r} must be a JSON object")
            if stored.get("kid") != kid:
                raise ValueError(f"PCS key {kid!r} carries a different kid")
            public_key = stored.get("public_key")
            if not isinstance(public_key, str) or not crypto.valid_public_key(public_key):
                raise ValueError(f"PCS key {kid!r} has an invalid public key")
            status = stored.get("status")
            if status not in STATUSES:
                raise ValueError(f"PCS key {kid!r} has an unknown status {status!r}")
            try:
                created_at = parse_timestamp(stored["created_at"])
            except (KeyError, TypeError, OsapError) as error:
                raise ValueError(f"PCS key {kid!r} needs a created_at timestamp") from error
            restored[kid] = {
                "kid": kid,
                "public_key": public_key,
                "status": status,
                "created_at": created_at,
                "not_before": self._restore_time(stored, "not_before", kid),
                "not_after": self._restore_time(stored, "not_after", kid),
                "retired_at": self._restore_time(stored, "retired_at", kid),
                "grace_until": self._restore_time(stored, "grace_until", kid),
                "revoked_at": self._restore_time(stored, "revoked_at", kid),
            }
            record = restored[kid]
            if (
                record["not_before"] is not None
                and record["not_after"] is not None
                and record["not_before"] > record["not_after"]
            ):
                raise ValueError(f"PCS key {kid!r} has an inverted validity window")
        self._keys = restored

    @staticmethod
    def _restore_time(stored: dict, field: str, kid: str) -> datetime | None:
        value = stored.get(field)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError(f"PCS key {kid!r} has a malformed {field}")
        try:
            return parse_timestamp(value)
        except OsapError:
            raise ValueError(f"PCS key {kid!r} has a malformed {field}") from None

    def _persist(self) -> None:
        if self._store is None:
            return
        self._store.put(
            KEYS_SECTION,
            {kid: self._stored(record) for kid, record in self._keys.items()},
        )

    @staticmethod
    def _stored(record: dict) -> dict:
        stored = {}
        for field, value in record.items():
            stored[field] = _stamp(value) if isinstance(value, datetime) else value
        return stored

    # --- registration ------------------------------------------------------

    def register(
        self,
        kid: str,
        public_key: str,
        *,
        not_before: datetime | None = None,
        not_after: datetime | None = None,
    ) -> dict:
        """Register a new active key; a known `kid` cannot be reused."""

        if not isinstance(kid, str) or not kid:
            raise ValueError("a PCS key needs a non-empty kid")
        if kid in self._keys:
            raise ValueError(f"PCS key {kid!r} is already registered")
        if not isinstance(public_key, str) or not crypto.valid_public_key(public_key):
            raise ValueError(f"PCS key {kid!r} is not a valid Ed25519 public key")
        self._check_window(not_before, not_after)
        record = {
            "kid": kid,
            "public_key": public_key,
            "status": ACTIVE,
            "created_at": self._clock(),
            "not_before": not_before,
            "not_after": not_after,
            "retired_at": None,
            "grace_until": None,
            "revoked_at": None,
        }
        self._keys[kid] = record
        self._persist()
        return self._public(record)

    def rotate(
        self,
        kid: str,
        new_public_key: str,
        *,
        new_kid: str,
        grace_seconds: float = 0,
        not_before: datetime | None = None,
        not_after: datetime | None = None,
    ) -> dict:
        """Retire `kid`, add an active `new_kid`, and return the new record.

        The retired key stays usable through `grace_seconds` so receipts that
        were signed just before the rotation still verify. A revoked or
        already retired key cannot be rotated again.
        """

        current = self._keys.get(kid)
        if current is None:
            raise ValueError(f"PCS key {kid!r} is not registered")
        if current["status"] == REVOKED:
            raise ValueError(f"PCS key {kid!r} is revoked")
        if current["status"] == RETIRED:
            raise ValueError(f"PCS key {kid!r} is already retired")
        if not isinstance(new_kid, str) or not new_kid:
            raise ValueError("a PCS key needs a non-empty kid")
        if new_kid == kid:
            raise ValueError("a rotation needs a new kid")
        if new_kid in self._keys:
            raise ValueError(f"PCS key {new_kid!r} is already registered")
        if not isinstance(new_public_key, str) or not crypto.valid_public_key(new_public_key):
            raise ValueError(f"PCS key {new_kid!r} is not a valid Ed25519 public key")
        if not isinstance(grace_seconds, (int, float)) or grace_seconds < 0:
            raise ValueError("grace_seconds must be a non-negative number")
        self._check_window(not_before, not_after)

        moment = self._clock()
        retired = dict(current)
        retired["status"] = RETIRED
        retired["retired_at"] = moment
        retired["grace_until"] = moment + timedelta(seconds=grace_seconds)
        replacement = {
            "kid": new_kid,
            "public_key": new_public_key,
            "status": ACTIVE,
            "created_at": moment,
            "not_before": not_before,
            "not_after": not_after,
            "retired_at": None,
            "grace_until": None,
            "revoked_at": None,
        }
        self._keys[kid] = retired
        self._keys[new_kid] = replacement
        self._persist()
        return self._public(replacement)

    def revoke(self, kid: str, *, at: datetime | None = None) -> bool:
        """Revoke `kid`; return False when it was already revoked."""

        record = self._keys.get(kid)
        if record is None:
            raise ValueError(f"PCS key {kid!r} is not registered")
        if record["status"] == REVOKED:
            return False
        revoked = dict(record)
        revoked["status"] = REVOKED
        revoked["revoked_at"] = at or self._clock()
        self._keys[kid] = revoked
        self._persist()
        return True

    # --- lookup ------------------------------------------------------------

    def state_of(self, kid: str) -> str | None:
        """Return the stored lifecycle state, or None for an unknown key."""

        record = self._keys.get(kid)
        return None if record is None else record["status"]

    def usable(self, kid: str, *, at: datetime | None = None) -> bool:
        """True when `kid` may verify a receipt at `at` (§4.5)."""

        record = self._keys.get(kid)
        if record is None or record["status"] == REVOKED:
            return False
        moment = at or self._clock()
        if record["not_before"] is not None and moment < record["not_before"]:
            return False
        if record["not_after"] is not None and moment > record["not_after"]:
            return False
        if record["status"] == RETIRED:
            grace_until = record["grace_until"]
            return grace_until is not None and moment <= grace_until
        return True

    def key(self, kid: str) -> dict | None:
        """Return a detached public record, or None when it is absent."""

        record = self._keys.get(kid)
        return None if record is None else self._public(record)

    def keys(self) -> list[dict]:
        """Return every public record, ordered by `kid`."""

        return [self._public(self._keys[kid]) for kid in sorted(self._keys)]

    @staticmethod
    def _public(record: dict) -> dict:
        return KeyRegistry._stored(record)

    @staticmethod
    def _check_window(not_before: datetime | None, not_after: datetime | None) -> None:
        for name, value in (("not_before", not_before), ("not_after", not_after)):
            if value is not None and not isinstance(value, datetime):
                raise ValueError(f"{name} must be a datetime")
        if not_before is not None and not_after is not None and not_before > not_after:
            raise ValueError("not_before must not be after not_after")

    # --- verification ------------------------------------------------------

    def verify_receipt(self, receipt: dict, *, at: datetime | None = None) -> bool:
        """Resolve the receipt's `kid` and verify its proof; never raises."""

        proof = receipt.get(PROOF_FIELD)
        if not isinstance(proof, dict):
            return False
        kid = proof.get("kid")
        if not isinstance(kid, str) or not kid:
            return False
        record = self._keys.get(kid)
        if record is None or not self.usable(kid, at=at):
            return False
        return verify_receipt(receipt, record["public_key"], kid=kid)

    def require_receipt(self, receipt: dict, *, at: datetime | None = None) -> dict:
        """Raise `AUTH_DENIED` unless `kid` is usable and the proof verifies."""

        proof = receipt.get(PROOF_FIELD)
        kid = proof.get("kid") if isinstance(proof, dict) else None
        record = self._keys.get(kid) if isinstance(kid, str) and kid else None
        if record is None:
            raise OsapError(
                "AUTH_DENIED",
                "consent receipt names an unknown PCS key",
                details={"reason": "receipt_key_unknown", "kid": kid},
            )
        moment = at or self._clock()
        if record["status"] == REVOKED:
            raise OsapError(
                "AUTH_DENIED",
                "consent receipt was signed by a revoked PCS key",
                details={"reason": "receipt_key_revoked", "kid": kid},
            )
        if record["not_before"] is not None and moment < record["not_before"]:
            raise OsapError(
                "AUTH_DENIED",
                "consent receipt key is not valid yet",
                details={"reason": "receipt_key_not_yet_valid", "kid": kid},
            )
        if not self.usable(kid, at=moment):
            raise OsapError(
                "AUTH_DENIED",
                "consent receipt key is outside its validity window",
                details={"reason": "receipt_key_expired", "kid": kid},
            )
        if not verify_receipt(receipt, record["public_key"], kid=kid):
            raise OsapError(
                "AUTH_DENIED",
                "consent receipt signature does not verify",
                details={"reason": "receipt_signature_invalid", "kid": kid},
            )
        return receipt
