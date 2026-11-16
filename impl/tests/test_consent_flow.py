# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the consent flow (standard.md §10.2, §10.3)."""

import copy
import json
import unittest
from datetime import timedelta
from pathlib import Path

from osap import capability, consent, consent_flow, pcs
from osap.clock import parse_timestamp
from osap.errors import OsapError

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
BASE = parse_timestamp("2026-11-10T10:14:45Z")
USER = "user://local/example-user"
REQUEST_ID = "creq_01J9Z6Q3V8N2K4M7P1R5T0WX40"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def request_payload() -> dict:
    return copy.deepcopy(load("consent-request.json")["body"]["data"])


def token_for(receipt: dict) -> dict:
    token = copy.deepcopy(load("capability.json"))
    token.update(
        {
            "cap_id": receipt["cap_id"],
            "task_id": receipt["task_id"],
            "audience": receipt["audience"],
            "subject": receipt["agent"],
            "actions": list(receipt["actions"]),
            "resources": list(receipt["resources"]),
            "consent_receipt_id": receipt["receipt_id"],
        }
    )
    return token


class Clock:
    def __init__(self, moment=BASE):
        self.moment = moment

    def __call__(self):
        return self.moment

    def advance(self, **kwargs):
        self.moment += timedelta(**kwargs)


def flow_with(clock=None, *, authority=True):
    clock = clock or Clock()
    ca = capability.CapabilityAuthority(clock=clock) if authority else None
    return consent_flow.ConsentFlow(user=USER, authority=ca, clock=clock), ca, clock


def granted_flow():
    flow, ca, clock = flow_with()
    payload = request_payload()
    flow.request(payload)
    flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
    receipt = flow.grant(payload["request_id"], option="allow_once", receipt_id="receipt_flow")
    return flow, ca, clock, receipt


class DurationTests(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(consent_flow.parse_duration("PT10M"), timedelta(minutes=10))

    def test_days_and_hours(self):
        self.assertEqual(consent_flow.parse_duration("P1DT2H"), timedelta(days=1, hours=2))

    def test_seconds_may_be_fractional(self):
        self.assertEqual(consent_flow.parse_duration("PT1.5S"), timedelta(seconds=1.5))

    def test_empty_duration_is_invalid(self):
        for text in ("", "P", "PT", "10M", "P1W"):
            with self.assertRaises(OsapError):
                consent_flow.parse_duration(text)


class RequestTests(unittest.TestCase):
    def test_request_returns_the_spec_envelope(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        message = flow.request(payload, message_id="msg_consent")
        self.assertEqual(message["type"], "consent.request")
        self.assertEqual(message["from"], "agent://system/policy#0")
        self.assertEqual(message["to"], {"user": USER})
        self.assertEqual(message["body"]["schema"], "osap.consent.request/v1")
        self.assertEqual(message["body"]["data"], payload)

    def test_request_uses_the_preview_ttl(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        record = flow.requests[payload["request_id"]]
        self.assertEqual(record["expires_at"], BASE + timedelta(minutes=10))

    def test_request_without_ttl_gets_the_default(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        del payload["intent_preview"]["ttl"]
        flow.request(payload)
        record = flow.requests[payload["request_id"]]
        self.assertEqual(record["expires_at"], BASE + consent_flow.DEFAULT_TTL)

    def test_duplicate_request_is_refused(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        with self.assertRaises(OsapError) as caught:
            flow.request(payload)
        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_invalid_payload_is_schema_invalid(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        del payload["options"]
        with self.assertRaises(OsapError) as caught:
            flow.request(payload)
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")


class ReservationTests(unittest.TestCase):
    def test_reservation_is_inert(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        cap_id = flow.reserve_cap_id(payload["request_id"], cap_id="cap_reserved")
        self.assertEqual(cap_id, "cap_reserved")
        self.assertFalse(flow.usable(cap_id))

    def test_reservation_is_idempotent_for_one_request(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        first = flow.reserve_cap_id(payload["request_id"], cap_id="cap_reserved")
        second = flow.reserve_cap_id(payload["request_id"])
        self.assertEqual(first, second)

    def test_two_requests_cannot_share_a_cap_id(self):
        flow, _, _ = flow_with()
        first, second = request_payload(), request_payload()
        second["request_id"] = "creq_second"
        flow.request(first)
        flow.request(second)
        flow.reserve_cap_id(first["request_id"], cap_id="cap_shared")
        with self.assertRaises(OsapError) as caught:
            flow.reserve_cap_id(second["request_id"], cap_id="cap_shared")
        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_unknown_request_is_refused(self):
        flow, _, _ = flow_with()
        with self.assertRaises(OsapError) as caught:
            flow.reserve_cap_id("creq_missing")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_expired_request_cannot_be_reserved(self):
        clock = Clock()
        flow, _, _ = flow_with(clock)
        payload = request_payload()
        flow.request(payload)
        clock.advance(minutes=11)
        with self.assertRaises(OsapError) as caught:
            flow.reserve_cap_id(payload["request_id"])
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_EXPIRED")
        self.assertEqual(flow.requests[payload["request_id"]]["status"], "expired")


class GrantTests(unittest.TestCase):
    def test_grant_needs_a_reservation_first(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        with self.assertRaises(OsapError) as caught:
            flow.grant(payload["request_id"], option="allow_once")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertEqual(caught.exception.details["reason"], "missing_reservation")

    def test_receipt_binds_user_agent_task_audience_actions_and_risk(self):
        flow, _, _, receipt = granted_flow()
        payload = request_payload()
        self.assertEqual(receipt["user"], USER)
        self.assertEqual(receipt["agent"], payload["agent"])
        self.assertEqual(receipt["task_id"], payload["task_id"])
        self.assertEqual(receipt["audience"], payload["audience"])
        self.assertEqual(receipt["actions"], payload["actions"])
        self.assertEqual(receipt["risk"], payload["risk"])

    def test_receipt_covers_the_reserved_capability(self):
        flow, _, _, receipt = granted_flow()
        token = token_for(receipt)
        self.assertEqual(consent.validate(receipt, token, now=BASE), receipt)

    def test_allow_once_sets_one_use(self):
        _, _, _, receipt = granted_flow()
        self.assertEqual(receipt["constraints"]["max_uses"], 1)

    def test_allow_task_keeps_the_requested_max_uses(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        receipt = flow.grant(payload["request_id"], option="allow_task", max_uses=5)
        self.assertEqual(receipt["constraints"]["max_uses"], 5)

    def test_receipt_expiry_is_clamped_to_the_request(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        receipt = flow.grant(
            payload["request_id"],
            option="allow_task",
            expires_at="2026-11-11T00:00:00Z",
        )
        self.assertEqual(receipt["constraints"]["expires_at"], "2026-11-10T10:24:45Z")

    def test_receipt_may_end_before_the_request(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        receipt = flow.grant(
            payload["request_id"],
            option="allow_task",
            expires_at="2026-11-10T10:16:00Z",
        )
        self.assertEqual(receipt["constraints"]["expires_at"], "2026-11-10T10:16:00Z")

    def test_past_receipt_expiry_is_refused(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        with self.assertRaises(OsapError) as caught:
            flow.grant(
                payload["request_id"],
                option="allow_task",
                expires_at="2026-11-10T10:00:00Z",
            )
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_EXPIRED")

    def test_deny_option_must_use_deny(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        with self.assertRaises(OsapError) as caught:
            flow.grant(payload["request_id"], option="deny")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_unoffered_option_is_refused(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        payload["options"] = ["allow_once", "deny"]
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        with self.assertRaises(OsapError) as caught:
            flow.grant(payload["request_id"], option="allow_task")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_duplicate_receipt_id_is_refused(self):
        flow, _, _ = flow_with()
        first, second = request_payload(), request_payload()
        second["request_id"] = "creq_second"
        for payload in (first, second):
            flow.request(payload)
            flow.reserve_cap_id(payload["request_id"], cap_id=f"cap_{payload['request_id']}")
        flow.grant(first["request_id"], receipt_id="receipt_shared")
        with self.assertRaises(OsapError) as caught:
            flow.grant(second["request_id"], receipt_id="receipt_shared")
        self.assertEqual(caught.exception.code, "DUPLICATE")


class DenyTests(unittest.TestCase):
    def test_deny_records_reason_and_alternatives(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        decision = flow.deny(
            payload["request_id"],
            reason="user_declined",
            alternatives=["narrower_scope"],
        )
        self.assertEqual(decision["decision"], "deny")
        self.assertEqual(decision["reason"], "user_declined")
        self.assertEqual(decision["alternatives"], ["narrower_scope"])

    def test_deny_without_reason_is_refused(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        with self.assertRaises(OsapError) as caught:
            flow.deny(payload["request_id"], reason="")
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_deny_cancels_a_reserved_capability(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        flow.deny(payload["request_id"], reason="user_declined")
        self.assertFalse(flow.usable("cap_flow"))
        self.assertEqual(flow.reservations["cap_flow"]["status"], "cancelled")

    def test_grant_after_deny_is_refused(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        flow.deny(payload["request_id"], reason="user_declined")
        with self.assertRaises(OsapError) as caught:
            flow.grant(payload["request_id"])
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_deny_after_grant_is_refused(self):
        flow, _, _, _ = granted_flow()
        with self.assertRaises(OsapError) as caught:
            flow.deny(REQUEST_ID, reason="late")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")


class ActivationTests(unittest.TestCase):
    def test_activation_issues_the_capability(self):
        flow, ca, _, receipt = granted_flow()
        token = token_for(receipt)
        flow.activate(receipt["receipt_id"], token)
        self.assertTrue(flow.usable(receipt["cap_id"]))
        self.assertIn(receipt["cap_id"], ca.issued)

    def test_reserved_id_is_not_issued(self):
        flow, ca, _, receipt = granted_flow()
        self.assertNotIn(receipt["cap_id"], ca.issued)
        self.assertFalse(flow.usable(receipt["cap_id"]))

    def test_activation_rejects_a_different_cap_id(self):
        flow, _, _, receipt = granted_flow()
        token = token_for(receipt)
        token["cap_id"] = "cap_other"
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_SCOPE_MISMATCH")

    def test_activation_rejects_a_widened_action(self):
        flow, _, _, receipt = granted_flow()
        token = token_for(receipt)
        token["actions"] = ["create"]
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token)
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_SCOPE_MISMATCH")

    def test_activation_twice_is_a_duplicate(self):
        flow, _, _, receipt = granted_flow()
        token = token_for(receipt)
        flow.activate(receipt["receipt_id"], token)
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token)
        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_expired_receipt_cannot_activate(self):
        flow, _, clock, receipt = granted_flow()
        clock.advance(minutes=11)
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token_for(receipt))
        self.assertEqual(caught.exception.code, "POLICY_CONSENT_EXPIRED")

    def test_unknown_receipt_cannot_activate(self):
        flow, _, _ = flow_with()
        with self.assertRaises(OsapError) as caught:
            flow.activate("receipt_missing", {"cap_id": "cap_missing"})
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_cancelled_reservation_cannot_activate(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        flow.deny(payload["request_id"], reason="user_declined")
        flow.receipts["receipt_orphan"] = flow.signer.sign(
            {
                "receipt_id": "receipt_orphan",
                "cap_id": "cap_flow",
            }
        )
        with self.assertRaises(OsapError) as caught:
            flow.activate("receipt_orphan", {"cap_id": "cap_flow"})
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertIn("cancelled", caught.exception.message)


class RevocationTests(unittest.TestCase):
    def test_revocation_cascades_to_the_issued_capability(self):
        flow, ca, _, receipt = granted_flow()
        token = token_for(receipt)
        flow.activate(receipt["receipt_id"], token)
        revoked = flow.revoke(receipt["receipt_id"])
        self.assertEqual(revoked, 1)
        self.assertIn(receipt["cap_id"], ca.revoked)
        self.assertEqual(flow.reservations[receipt["cap_id"]]["status"], "revoked")

    def test_revocation_before_activation_blocks_activation(self):
        flow, _, _, receipt = granted_flow()
        flow.revoke(receipt["receipt_id"])
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token_for(receipt))
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_unknown_receipt_cannot_be_revoked(self):
        flow, _, _ = flow_with()
        with self.assertRaises(OsapError) as caught:
            flow.revoke("receipt_missing")
        self.assertEqual(caught.exception.code, "POLICY_DENIED")


class ReceiptProofTests(unittest.TestCase):
    def test_grant_signs_with_the_pcs_key(self):
        flow, _, _, receipt = granted_flow()
        self.assertEqual(receipt["proof"]["kid"], flow.signer.kid)
        self.assertTrue(
            pcs.verify_receipt(
                receipt,
                flow.pcs_key["public_key"],
                kid=flow.signer.kid,
            )
        )

    def test_an_injected_signer_is_used(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-injected")
        flow = consent_flow.ConsentFlow(user=USER, signer=signer)
        payload = request_payload()
        flow.request(payload)
        flow.reserve_cap_id(payload["request_id"], cap_id="cap_flow")
        receipt = flow.grant(payload["request_id"], receipt_id="receipt_flow")
        self.assertEqual(receipt["proof"]["kid"], "pcs-injected")
        self.assertTrue(signer.verify(receipt))

    def test_an_agent_self_signed_receipt_cannot_activate(self):
        flow, _, _, receipt = granted_flow()
        forged = pcs.ConsentSigner.generate(kid=flow.signer.kid).sign(
            {key: value for key, value in receipt.items() if key != "proof"}
        )
        flow.receipts[receipt["receipt_id"]] = forged
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token_for(forged))
        self.assertEqual(caught.exception.code, "AUTH_DENIED")
        self.assertEqual(caught.exception.details["reason"], "receipt_signature_invalid")
        self.assertFalse(flow.usable(receipt["cap_id"]))

    def test_a_tampered_receipt_cannot_activate(self):
        flow, _, _, receipt = granted_flow()
        flow.receipts[receipt["receipt_id"]]["actions"] = ["calendar.read"]
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token_for(receipt))
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_a_receipt_without_a_proof_cannot_activate(self):
        flow, _, _, receipt = granted_flow()
        del flow.receipts[receipt["receipt_id"]]["proof"]
        with self.assertRaises(OsapError) as caught:
            flow.activate(receipt["receipt_id"], token_for(receipt))
        self.assertEqual(caught.exception.code, "AUTH_DENIED")

    def test_pcs_key_is_public_only(self):
        flow, _, _ = flow_with()
        self.assertEqual(set(flow.pcs_key), {"kid", "public_key"})


class AuditTests(unittest.TestCase):
    def test_the_flow_records_request_grant_and_issue(self):
        flow, _, _, receipt = granted_flow()
        flow.activate(receipt["receipt_id"], token_for(receipt))
        actions = [event["action"] for event in flow.audit]
        self.assertEqual(
            actions,
            ["consent.requested", "consent.granted", "capability.issued"],
        )

    def test_denial_is_audited(self):
        flow, _, _ = flow_with()
        payload = request_payload()
        flow.request(payload)
        flow.deny(payload["request_id"], reason="user_declined")
        self.assertEqual(flow.audit[-1]["action"], "consent.denied")
        self.assertEqual(flow.audit[-1]["reason"], "user_declined")

    def test_revocation_is_audited(self):
        flow, _, _, receipt = granted_flow()
        flow.revoke(receipt["receipt_id"])
        self.assertEqual(flow.audit[-1]["action"], "capability.revoked")


if __name__ == "__main__":
    unittest.main()
