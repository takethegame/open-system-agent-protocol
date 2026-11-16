# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Consent flow: request, reserve, grant or deny, then activate (§10.2, §10.3).

The receipt validators in `consent.py` answer "does this receipt cover this
capability?". This module adds the other side: the PCS records a request, the
CA reserves a `cap_id` before the user decides, the user grants or denies, and
only a validated grant activates the capability (§10.3 issuance ordering).

Reservations are deliberately inert. A reserved `cap_id` is not issued, so it
fails routing and validity checks until `activate()` succeeds; a denied,
revoked, or expired request can never promote it. Every grant is signed by the
PCS `ConsentSigner` and `activate()` verifies that proof before issuing, so an
Agent cannot self-sign its own consent.

With a `JsonStore`, the requests, receipts, reservations, and a generated
signing key survive a restart; the audit list stays in memory. The clock is
injectable, matching the rest of the reference implementation.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from . import consent, schema
from .capability import CapabilityAuthority
from .clock import parse_timestamp
from .errors import OsapError
from .pcs import ConsentSigner
from .store import JsonStore

REQUEST_SCHEMA = "consent-request.schema.json"
GRANT_OPTIONS = frozenset({"allow_once", "allow_task", "allow_ttl"})
DENY_OPTION = "deny"

REQUESTS_SECTION = "consent.requests"
RECEIPTS_SECTION = "consent.receipts"
RESERVATIONS_SECTION = "consent.reservations"
SIGNING_KEY_SECTION = "consent.pcs_key"

#: Default request lifetime when `intent_preview.ttl` is absent.
DEFAULT_TTL = timedelta(minutes=10)

_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_duration(text: str) -> timedelta:
    """Parse the small ISO 8601 subset the consent preview uses (`PT10M`)."""

    match = _DURATION.match(text or "")
    if not match or not any(match.groupdict().values()):
        raise OsapError("SCHEMA_INVALID", f"not an ISO 8601 duration: {text!r}")
    if not text.startswith("P") or text in {"P", "PT"}:
        raise OsapError("SCHEMA_INVALID", f"not an ISO 8601 duration: {text!r}")
    return timedelta(
        days=int(match["days"] or 0),
        hours=int(match["hours"] or 0),
        minutes=int(match["minutes"] or 0),
        seconds=float(match["seconds"] or 0),
    )


class ConsentFlow:
    """In-memory PCS/CA handshake with the §10.3 ordering."""

    def __init__(
        self,
        *,
        user: str,
        authority: CapabilityAuthority | None = None,
        policy_agent: str = "agent://system/policy#0",
        clock=None,
        signer: ConsentSigner | None = None,
        store: JsonStore | None = None,
    ) -> None:
        self.user = user
        self.authority = authority
        self.policy_agent = policy_agent
        self._clock = clock or _now
        self._store = store
        self.requests: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}
        self.reservations: dict[str, dict] = {}
        self.audit: list[dict] = []
        if store is not None:
            self._restore()
        self.signer = self._restore_signer(signer)

    @property
    def pcs_key(self) -> dict:
        """The public half a verifier needs to check this flow's receipts."""

        return self.signer.key_record()

    # --- persistence ------------------------------------------------------

    def _restore_signer(self, injected: ConsentSigner | None) -> ConsentSigner:
        if injected is not None:
            return injected
        if self._store is None:
            return ConsentSigner.generate()
        stored = self._store.get(SIGNING_KEY_SECTION)
        if stored is None:
            generated = ConsentSigner.generate()
            self._store.put(
                SIGNING_KEY_SECTION,
                {
                    "kid": generated.kid,
                    "private_key": generated.export_private(),
                    "public_key": generated.public_key,
                },
            )
            return generated
        if not isinstance(stored, dict):
            raise ValueError(f"{SIGNING_KEY_SECTION!r} must be a JSON object")
        private = stored.get("private_key")
        kid = stored.get("kid")
        if not isinstance(private, str) or not isinstance(kid, str):
            raise ValueError(f"{SIGNING_KEY_SECTION!r} needs a private_key and a kid")
        restored = ConsentSigner(private, kid=kid)
        if stored.get("public_key") not in (None, restored.public_key):
            raise ValueError(f"{SIGNING_KEY_SECTION!r} public_key does not match")
        return restored

    def _restore(self) -> None:
        requests = self._read_section(REQUESTS_SECTION)
        receipts = self._read_section(RECEIPTS_SECTION)
        reservations = self._read_section(RESERVATIONS_SECTION)
        for request_id, record in requests.items():
            if not isinstance(record, dict):
                raise ValueError(f"consent request {request_id!r} must be a JSON object")
            try:
                record["requested_at"] = parse_timestamp(record["requested_at"])
                record["expires_at"] = parse_timestamp(record["expires_at"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"consent request {request_id!r} has bad timestamps") from error
        self.requests = requests
        self.receipts = receipts
        self.reservations = reservations

    def _read_section(self, section: str) -> dict:
        loaded = self._store.get(section)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{section!r} must be a JSON object")
        return loaded

    def _persist(self) -> None:
        if self._store is None:
            return
        self._store.put_many(
            {
                REQUESTS_SECTION: {
                    request_id: self._stored_request(record)
                    for request_id, record in self.requests.items()
                },
                RECEIPTS_SECTION: self.receipts,
                RESERVATIONS_SECTION: self.reservations,
            }
        )

    @staticmethod
    def _stored_request(record: dict) -> dict:
        stored = dict(record)
        stored["requested_at"] = _stamp(record["requested_at"])
        stored["expires_at"] = _stamp(record["expires_at"])
        return stored

    # --- request ----------------------------------------------------------

    def request(self, payload: dict, *, message_id: str | None = None) -> dict:
        """Validate and record a consent request; return the §10.2 envelope."""

        schema.validate(REQUEST_SCHEMA, payload)
        request_id = payload["request_id"]
        if request_id in self.requests:
            raise OsapError("DUPLICATE", f"consent request already exists: {request_id}")

        moment = self._clock()
        ttl = payload.get("intent_preview", {}).get("ttl")
        lifetime = parse_duration(ttl) if ttl else DEFAULT_TTL
        expires_at = moment + lifetime

        self.requests[request_id] = {
            "payload": payload,
            "status": "pending",
            "requested_at": moment,
            "expires_at": expires_at,
            "message_id": message_id or f"msg_{request_id}",
            "cap_id": None,
            "receipt_id": None,
        }
        self.audit.append(
            {
                "action": "consent.requested",
                "request_id": request_id,
                "risk": payload["risk"],
                "agent": payload["agent"],
            }
        )
        self._persist()
        return {
            "osap": "0.1",
            "type": "consent.request",
            "id": self.requests[request_id]["message_id"],
            "from": self.policy_agent,
            "to": {"user": self.user},
            "body": {"schema": "osap.consent.request/v1", "data": payload},
            "ts": _stamp(moment),
        }

    def _require_pending(self, request_id: str) -> dict:
        record = self.requests.get(request_id)
        if record is None:
            raise OsapError(
                "POLICY_DENIED",
                "unknown consent request",
                details={"request_id": request_id, "reason": "unknown_request"},
            )
        if record["status"] != "pending":
            raise OsapError(
                "POLICY_DENIED",
                f"consent request is {record['status']}",
                details={"request_id": request_id, "reason": record["status"]},
            )
        if record["expires_at"] <= self._clock():
            record["status"] = "expired"
            self._persist()
            raise OsapError(
                "POLICY_CONSENT_EXPIRED",
                "consent request has expired",
                details={"request_id": request_id, "expires_at": _stamp(record["expires_at"])},
            )
        return record

    # --- CA reservation ---------------------------------------------------

    def reserve_cap_id(self, request_id: str, *, cap_id: str | None = None) -> str:
        """Reserve a `cap_id` before the user decides; it is not yet usable."""

        record = self._require_pending(request_id)
        if record["cap_id"] is not None:
            return record["cap_id"]
        reserved = cap_id or f"cap_{secrets.token_hex(8).upper()}"
        if reserved in self.reservations:
            raise OsapError("DUPLICATE", f"cap_id already reserved: {reserved}")

        record["cap_id"] = reserved
        self.reservations[reserved] = {
            "request_id": request_id,
            "status": "reserved",
            "receipt_id": None,
        }
        self._persist()
        return reserved

    # --- user decision ----------------------------------------------------

    def grant(
        self,
        request_id: str,
        *,
        option: str = "allow_once",
        receipt_id: str | None = None,
        expires_at: str | None = None,
        max_uses: int | None = None,
    ) -> dict:
        """Record a grant and return a receipt that still needs activation."""

        if option == DENY_OPTION:
            raise OsapError(
                "POLICY_DENIED",
                "the deny option must be recorded with deny()",
                details={"reason": "deny_option"},
            )
        if option not in GRANT_OPTIONS:
            raise OsapError(
                "SCHEMA_INVALID",
                f"unknown consent option: {option!r}",
                details={"allowed": sorted(GRANT_OPTIONS)},
            )

        record = self._require_pending(request_id)
        payload = record["payload"]
        if option not in payload["options"]:
            raise OsapError(
                "SCHEMA_INVALID",
                f"option {option!r} is not offered by the request",
                details={"offered": list(payload["options"])},
            )

        cap_id = record["cap_id"]
        if cap_id is None:
            raise OsapError(
                "POLICY_DENIED",
                "grant is out of order: reserve a cap_id first",
                details={"request_id": request_id, "reason": "missing_reservation"},
            )

        moment = self._clock()
        receipt_expiry = self._receipt_expiry(record, expires_at, moment)
        receipt_id = receipt_id or f"consent_{secrets.token_hex(8).upper()}"
        if receipt_id in self.receipts:
            raise OsapError("DUPLICATE", f"receipt already exists: {receipt_id}")

        constraints: dict = {"expires_at": _stamp(receipt_expiry)}
        if option == "allow_once":
            constraints["max_uses"] = 1
        elif max_uses is not None:
            constraints["max_uses"] = int(max_uses)

        receipt = {
            "osap_receipt": "0.1",
            "receipt_id": receipt_id,
            "user": self.user,
            "agent": payload["agent"],
            "task_id": payload["task_id"],
            "cap_id": cap_id,
            "audience": payload["audience"],
            "actions": list(payload["actions"]),
            "resources": list(payload["resources"]),
            "risk": payload["risk"],
            "decision": "grant",
            "constraints": constraints,
            "issued_at": _stamp(moment),
        }
        receipt = self.signer.sign(receipt)
        schema.validate("consent-receipt.schema.json", receipt)

        self.receipts[receipt_id] = receipt
        record["status"] = "granted"
        record["receipt_id"] = receipt_id
        self.reservations[cap_id]["receipt_id"] = receipt_id
        self.audit.append(
            {
                "action": "consent.granted",
                "request_id": request_id,
                "receipt_id": receipt_id,
                "cap_id": cap_id,
            }
        )
        self._persist()
        return receipt

    def deny(
        self,
        request_id: str,
        *,
        reason: str,
        alternatives: list | None = None,
    ) -> dict:
        """Record a denial and ensure a reserved `cap_id` can never activate."""

        if not reason:
            raise OsapError("SCHEMA_INVALID", "a denial needs a reason code")
        record = self._require_pending(request_id)
        cap_id = record["cap_id"]
        if cap_id is not None:
            self.reservations[cap_id]["status"] = "cancelled"
        record["status"] = "denied"
        self.audit.append(
            {
                "action": "consent.denied",
                "request_id": request_id,
                "reason": reason,
                "cap_id": cap_id,
            }
        )
        self._persist()
        return {
            "request_id": request_id,
            "decision": "deny",
            "reason": reason,
            "alternatives": list(alternatives or []),
        }

    def _receipt_expiry(self, record: dict, requested: str | None, moment: datetime) -> datetime:
        request_expiry = record["expires_at"]
        if requested is None:
            return request_expiry
        expiry = parse_timestamp(requested)
        if expiry <= moment:
            raise OsapError(
                "POLICY_CONSENT_EXPIRED",
                "the requested receipt expiry is already in the past",
                details={"expires_at": requested},
            )
        # Consent may not outlive the request that asked for it.
        return min(expiry, request_expiry)

    # --- activation -------------------------------------------------------

    def activate(self, receipt_id: str, token: dict) -> dict:
        """Validate a receipt, then issue the capability (§10.3 step 4)."""

        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise OsapError("POLICY_DENIED", f"unknown receipt: {receipt_id}")
        # Verify the user/OS proof before looking at reservation state, so a
        # forged or tampered receipt cannot learn whether a cap_id is active.
        self.signer.require(receipt)
        reservation = self.reservations.get(receipt["cap_id"])
        if reservation is None:
            raise OsapError("POLICY_DENIED", "capability has no reservation")
        if reservation["status"] == "cancelled":
            raise OsapError(
                "POLICY_DENIED",
                "reserved cap_id was cancelled by a denial",
                details={"cap_id": receipt["cap_id"]},
            )
        if reservation["status"] == "revoked":
            raise OsapError(
                "POLICY_DENIED",
                "reserved cap_id was revoked",
                details={"cap_id": receipt["cap_id"]},
            )
        if reservation["status"] == "active":
            raise OsapError(
                "DUPLICATE",
                "capability is already active",
                details={"cap_id": receipt["cap_id"]},
            )

        if token["cap_id"] != receipt["cap_id"]:
            raise OsapError(
                "POLICY_CONSENT_SCOPE_MISMATCH",
                "token cap_id is not the reserved cap_id",
                details={"token": token["cap_id"], "reserved": receipt["cap_id"]},
            )

        consent.validate(receipt, token, now=self._clock())
        if self.authority is not None:
            self.authority.issue(token)

        reservation["status"] = "active"
        self.audit.append(
            {
                "action": "capability.issued",
                "request_id": reservation["request_id"],
                "receipt_id": receipt_id,
                "cap_id": token["cap_id"],
            }
        )
        self._persist()
        return token

    def usable(self, cap_id: str) -> bool:
        """True only after activation; reserved or denied ids stay inert."""

        reservation = self.reservations.get(cap_id)
        return bool(reservation and reservation["status"] == "active")

    # --- revocation -------------------------------------------------------

    def revoke(self, receipt_id: str) -> int:
        """Revoke a receipt and cascade to the capability it activated."""

        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise OsapError("POLICY_DENIED", f"unknown receipt: {receipt_id}")
        cap_id = receipt["cap_id"]
        reservation = self.reservations.get(cap_id)
        if reservation is not None:
            reservation["status"] = "revoked"
        revoked = 0
        if self.authority is not None and cap_id in self.authority.issued:
            revoked = self.authority.revoke(cap_id)
        self.audit.append(
            {"action": "capability.revoked", "receipt_id": receipt_id, "cap_id": cap_id}
        )
        self._persist()
        return revoked
