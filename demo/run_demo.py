#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Three-agent OSAP 0.1 demo: notes + calendar behind one supervisor.

The demo runs in process, but every step goes through the reference modules:
signed manifests and registration, capability-record discovery, a consent
receipt, two delegated tasks with attenuated budgets, a context handle, and an
audit chain with a redacted export. The task crosses two delegation
boundaries, so it covers the C7-01 precondition ("three Apps, at least two
delegation or handoff boundaries") and can be replayed by hand.

Section 7 makes the runtime durable: the task tree, effect journal, audit
chain, context fabric, and idempotency index share one 0600 JSON store, a
simulated crash drops every in-memory object, and the restart shows the
§3.7/§8.11 guarantees — intent-only effects refuse replay until reconciled,
duplicate message ids replay instead of re-executing, and task blackboards
are cleared on close and never promoted to memory.

Run from anywhere:

    python3 demo/run_demo.py
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))

from osap import (  # noqa: E402
    audit,
    capability,
    consent_flow,
    context,
    crypto,
    identity,
    idempotency,
    pcs,
    registry,
    task,
)
from osap.clock import parse_timestamp  # noqa: E402
from osap.errors import OsapError  # noqa: E402
from osap.store import JsonStore  # noqa: E402

EXAMPLES = REPO / "examples"
NOW_TEXT = "2026-11-10T10:14:45Z"
NOW = parse_timestamp(NOW_TEXT)
TRACE = "trace_demo_01J9Z6Q3V8N2K4M7P1R5T0W"

SUPERVISOR = "agent://com.example.orchestrator/main#1a2b"
CALENDAR = "agent://com.example.calendar/agent#9c"
NOTES = "agent://com.example.notes/assistant#7f3a"
BUS = "agent://system/bus#0"
REGISTRY = "agent://system/registry#0"
USER = "user://local/example-user"

PARENT_TASK_ID = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAB"
NOTES_TASK_ID = "task_01J9Z6Q3V8N2K4M7P1R5T0WXA1"
CALENDAR_TASK_ID = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAE"
ROOT_TASK_ID = "task_01J9Z6Q3V8N2K4M7P1R5T0WXAA"

CAP_ID = "cap_demo_calendar_propose"
RECEIPT_ID = "consent_demo_calendar_propose"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def section(title: str) -> None:
    print()
    print(f"== {title} ==")


def require(condition: bool, message: str) -> None:
    """Fail the demo when a printed claim would be false."""

    if not condition:
        raise SystemExit(f"demo assertion failed: {message}")


def descriptor(uri: str, actions: list, resources: list, schemas: list, risk: str) -> dict:
    return {
        "cap": uri,
        "actions": actions,
        "resources": resources,
        "schemas": schemas,
        "risk": risk,
        "consent": "per_task" if risk in {"L3", "L4"} else "first_use",
    }


def build_manifest(app: str, agent: str, display: str, capabilities: list) -> tuple[dict, str]:
    private, public = crypto.generate_keypair()
    document = {
        "osap_manifest": "0.1",
        "app": app,
        "version": "1.0.0",
        "signature": "",
        "agents": [
            {
                "agent": agent,
                "display_name": display,
                "public_key": public,
                "capabilities": capabilities,
            }
        ],
    }
    return crypto.sign_document(document, private), public


def build_hello(agent: str, app: str, public: str, nonce: str) -> dict:
    return {
        "osap": "0.1",
        "id": f"msg_demo_hello_{nonce}",
        "type": "hello",
        "from": agent,
        "to": {"agent": BUS},
        "body": {
            "schema": "osap.hello/v1",
            "data": {
                "app": app,
                "agent": agent,
                "display_name": agent.rsplit("/", 1)[-1].split("#", 1)[0],
                "manifest_version": "1.0.0",
                "features": ["discover", "delegate", "consent", "context"],
                "encodings": ["json"],
                "public_key": public,
            },
        },
        "ts": NOW_TEXT,
    }


def main() -> int:
    print("OSAP 0.1 reference demo: notes + calendar behind one supervisor")
    print(f"simulated now: {NOW_TEXT}")
    state_dir = tempfile.mkdtemp(prefix="osap-demo-")
    state_path = os.path.join(state_dir, "bus_state.json")
    store = JsonStore(state_path)
    print(f"bus state: {state_path} (0600 JSON, one store, five sections)")

    # --- 1. signed manifests, trust, registration -------------------------
    section("1. manifests and registration (§4.1–§4.5, §7.1)")
    registry_instance = registry.Registry()

    setup = [
        (
            "app://com.example.orchestrator",
            SUPERVISOR,
            "Orchestrator",
            [
                descriptor(
                    "cap://os/tasks/orchestrate",
                    ["delegate", "cancel"],
                    ["task:*"],
                    ["osap.task/v1"],
                    "L1",
                )
            ],
        ),
        (
            "app://com.example.calendar",
            CALENDAR,
            "Calendar Agent",
            [
                descriptor(
                    "cap://os/calendar/events",
                    ["read", "propose", "create"],
                    ["calendar:primary"],
                    ["osap.calendar.event/v1", "osap.calendar.proposal/v1"],
                    "L3",
                )
            ],
        ),
        (
            "app://com.example.notes",
            NOTES,
            "Notes Assistant",
            [
                descriptor(
                    "cap://os/notes/documents",
                    ["read", "write"],
                    ["notes:local"],
                    ["osap.notes.document/v1", "osap.notes.summary/v1"],
                    "L2",
                )
            ],
        ),
    ]

    registrar = identity.Registrar(registry_instance)
    sessions = {}
    for index, (app, agent, display, capabilities) in enumerate(setup, start=1):
        manifest, public = build_manifest(app, agent, display, capabilities)
        registry_instance.trust(app, public)
        registry_instance.index_manifest(manifest)
        welcome = registrar.register(build_hello(agent, app, public, str(index)))
        sessions[agent] = welcome["session_id"]
        print(f"registered {agent} in {welcome['session_id']}")

    require(len(sessions) == 3, "all three agents must register")

    # --- 2. discovery ------------------------------------------------------
    section("2. capability discovery (§6.5, §6.6)")
    record = copy.deepcopy(load("capability-record.json"))
    record["agent"] = CALENDAR
    record["capability"]["actions"] = ["read", "propose", "create"]
    record["capability"]["schemas"] = [
        "osap.calendar.proposal/v1",
        "osap.calendar.event/v1",
    ]
    record["capability"]["risk"] = "L3"
    registry_instance.index_record(record, now=NOW)

    query = {
        "requires": ["calendar.propose"],
        "schemas": ["osap.calendar.proposal/v1"],
        "risk_max": "L3",
        "sources": ["vendor_registry"],
        "limit": 5,
    }
    candidates = registry_instance.discover(query, now=NOW)
    require(bool(candidates), "discovery must return the calendar record")
    candidate = candidates[0]
    print(f"found {candidate['agent']} via {candidate['source']['registry']}")
    print(f"match={candidate['match']} risk={candidate['risk']} hint={candidate['consent_hint']}")

    discover_message = {
        "id": "msg_demo_discover",
        "trace_id": TRACE,
        "type": "discover",
        "from": SUPERVISOR,
        "to": {"agent": REGISTRY},
    }

    # --- 3. consent request, reservation, grant, activation ----------------
    section("3. user consent flow and attenuated capability (§5.2–§5.8, §10.2–§10.3)")
    authority = capability.CapabilityAuthority(clock=lambda: NOW)
    flow = consent_flow.ConsentFlow(user=USER, authority=authority, clock=lambda: NOW)

    consent_payload = copy.deepcopy(load("consent-request.json")["body"]["data"])
    consent_payload["task_id"] = CALENDAR_TASK_ID
    consent_payload["agent"] = SUPERVISOR
    consent_payload["audience"] = CALENDAR
    consent_payload["actions"] = ["propose"]
    consent_payload["resources"] = ["calendar:primary"]
    consent_payload["risk"] = "L3"
    consent_message = flow.request(consent_payload, message_id="msg_demo_consent")

    reserved = flow.reserve_cap_id(consent_payload["request_id"], cap_id=CAP_ID)
    require(not flow.usable(reserved), "a reserved cap_id must stay inert")

    receipt = flow.grant(
        consent_payload["request_id"],
        option="allow_once",
        receipt_id=RECEIPT_ID,
    )
    require(not flow.usable(CAP_ID), "a grant must not activate before the CA issues")
    require(
        pcs.verify_receipt(receipt, flow.pcs_key["public_key"], kid=flow.signer.kid),
        "the receipt must verify against the PCS public key",
    )

    token = copy.deepcopy(load("capability.json"))
    token["cap_id"] = CAP_ID
    token["task_id"] = CALENDAR_TASK_ID
    token["root_task_id"] = ROOT_TASK_ID
    token["audience"] = CALENDAR
    token["subject"] = SUPERVISOR
    token["actions"] = ["propose"]
    token["constraints"]["max_depth"] = 2
    token["constraints"]["can_delegate"] = False
    token["iat"] = int(NOW.timestamp())
    token["nbf"] = int(NOW.timestamp())
    token["exp"] = int(NOW.timestamp()) + 3600
    token["consent_receipt_id"] = RECEIPT_ID

    flow.activate(RECEIPT_ID, token)
    require(flow.usable(CAP_ID), "activation must make the capability usable")
    authority.check_validity(token, now=NOW)
    authority.require_consent(token, risk="L3")
    print(
        f"{consent_message['type']} {consent_payload['request_id']} "
        f"-> {receipt['decision']} max_uses={receipt['constraints']['max_uses']}"
    )
    print(f"receipt {RECEIPT_ID} activated {CAP_ID} for {CALENDAR}")
    print("receipt proof verified against the PCS public key")
    print("L3 consent prerequisite satisfied; capability is valid at the simulated now")

    # --- 4. two delegations, two results ----------------------------------
    section("4. delegated tasks and results (§8.3–§8.8)")
    board = task.TaskBoard(store=store)
    parent = board.add(task.Task.from_document(load("task.json")))
    print(f"parent {parent.task_id} budget wall_ms={parent.budget['wall_ms']}")

    notes_delegate = copy.deepcopy(load("delegate.json"))
    notes_delegate["id"] = "msg_demo_delegate_notes"
    notes_delegate["trace_id"] = TRACE
    notes_delegate["causation_id"] = discover_message["id"]
    notes_delegate["to"] = {"agent": NOTES}
    notes_delegate["task"] = {
        "id": NOTES_TASK_ID,
        "parent": PARENT_TASK_ID,
        "root": ROOT_TASK_ID,
        "mode": "supervisor",
    }
    notes_delegate["auth"]["cap_id"] = "cap_demo_notes_summary"
    notes_delegate["body"]["data"].update(
        {
            "goal": "从本地笔记中提取会议背景与参会人",
            "budget": {"wall_ms": 3000, "tool_calls": 1, "depth": 2},
            "result_schema": "osap.notes.summary/v1",
        }
    )
    notes_cap = notes_delegate["body"]["data"]["delegated_capability"]
    notes_cap.update(
        {
            "cap_id": "cap_demo_notes_summary",
            "subject": NOTES,
            "audience": NOTES,
            "task_id": NOTES_TASK_ID,
            "root_task_id": ROOT_TASK_ID,
            "actions": ["read"],
            "resources": ["notes:local"],
            "parent_cap_id": "cap_demo_supervisor",
            "depth": 2,
        }
    )
    notes_cap["constraints"].update(
        {"max_budget": {"wall_ms": 3000, "tool_calls": 1}, "can_delegate": False}
    )

    notes_child = board.delegate(parent.task_id, notes_delegate)
    board.transition(notes_child, "accepted")
    board.transition(notes_child, "running")
    print(f"notes  {notes_child.task_id} budget wall_ms={notes_child.budget['wall_ms']}")

    progress = board.report_progress(
        notes_child.task_id,
        consumed={"wall_ms": 1200, "tool_calls": 1},
        sender=NOTES,
    )
    print(
        f"notes  status consumed tool_calls={progress['consumed']['tool_calls']}/1 "
        f"wall_ms={progress['consumed']['wall_ms']}/3000 "
        f"remaining wall_ms={progress['remaining']['wall_ms']}"
    )

    notes_result = {
        "osap": "0.1",
        "id": "msg_demo_result_notes",
        "type": "result",
        "trace_id": TRACE,
        "causation_id": notes_delegate["id"],
        "session_id": sessions[SUPERVISOR],
        "from": NOTES,
        "to": {"agent": SUPERVISOR},
        "task": {"id": NOTES_TASK_ID, "status": "succeeded"},
        "body": {
            "schema": "osap.notes.summary/v1",
            "data": {
                "summary": "下周三上午只有 10:00-11:00 全员空闲",
                "context_ref": "obj://sha256:9f2c7b1a",
            },
        },
        "ts": NOW_TEXT,
    }
    board.accept_result(notes_result)
    print(f"notes  status={notes_child.status} schema={notes_result['body']['schema']}")

    calendar_delegate = copy.deepcopy(load("delegate.json"))
    calendar_delegate["id"] = "msg_demo_delegate_calendar"
    calendar_delegate["trace_id"] = TRACE
    calendar_delegate["causation_id"] = notes_result["id"]
    calendar_delegate["task"]["id"] = CALENDAR_TASK_ID
    calendar_delegate["task"]["parent"] = PARENT_TASK_ID
    calendar_delegate["task"]["root"] = ROOT_TASK_ID
    calendar_delegate["auth"]["cap_id"] = CAP_ID
    calendar_delegate["body"]["data"]["budget"] = {
        "wall_ms": 5000,
        "tool_calls": 2,
        "depth": 2,
    }

    calendar_child = board.delegate(parent.task_id, calendar_delegate)
    board.transition(calendar_child, "accepted")
    board.transition(calendar_child, "running")
    print(f"calendar {calendar_child.task_id} budget wall_ms={calendar_child.budget['wall_ms']}")

    calendar_result = copy.deepcopy(load("result.json"))
    calendar_result["id"] = "msg_demo_result_calendar"
    calendar_result["trace_id"] = TRACE
    calendar_result["causation_id"] = calendar_delegate["id"]
    calendar_result["task"]["id"] = calendar_child.task_id
    board.accept_result(calendar_result)
    print(
        f"calendar status={calendar_child.status} "
        f"slots={len(calendar_result['body']['data']['slots'])}"
    )

    board.transition(parent, "accepted")
    board.transition(parent, "running")
    board.transition(parent, "succeeded")
    print(f"parent {parent.task_id} status={parent.status}")
    require(len(board.children(parent.task_id)) == 2, "the task must cross two delegations")
    require(parent.status == "succeeded", "the parent task must succeed")

    trace_messages = [
        discover_message,
        notes_delegate,
        notes_result,
        calendar_delegate,
        calendar_result,
    ]

    # --- 5. context fabric -------------------------------------------------
    section("5. context resolution (§9.2–§9.4)")
    handle_document = copy.deepcopy(load("context-handle.json"))
    handle_document["handle"] = "ctx://user/memory/meeting_preferences"
    handle_document["scope"] = "user"
    handle_document["audience"] = CALENDAR
    handle_document["constraints"]["allowed_agents"] = [CALENDAR]
    fabric = context.ContextFabric()
    resolved = fabric.resolve(
        handle_document,
        agent=CALENDAR,
        granted_actions=["resolve", "memory.read"],
        now=NOW,
    )
    print(f"resolved {resolved['handle']} label={resolved['label']} scope={resolved['scope']}")
    print(f"audit decision={fabric.audit[-1]['decision']} action={fabric.audit[-1]['action']}")

    # --- 6. audit chain, redaction, recovery ------------------------------
    section("6. audit chain and redacted export (§10.5–§10.6, §8.11)")
    events = [
        {"actor": BUS, "action": "agent.registered", "target": SUPERVISOR},
        {"actor": BUS, "action": "agent.registered", "target": CALENDAR},
        {"actor": BUS, "action": "agent.registered", "target": NOTES},
        {"actor": SUPERVISOR, "action": "discovery.query", "target": REGISTRY},
        {
            "actor": flow.policy_agent,
            "action": "consent.requested",
            "target": USER,
        },
        {
            "actor": USER,
            "action": "consent.granted",
            "target": CALENDAR,
            "consent_receipt_id": RECEIPT_ID,
        },
        {
            "actor": SUPERVISOR,
            "action": "task.created",
            "target": parent.task_id,
            "task_id": parent.task_id,
        },
        {
            "actor": SUPERVISOR,
            "action": "task.delegated",
            "target": notes_child.task_id,
            "task_id": notes_child.task_id,
            "session_id": sessions[SUPERVISOR],
        },
        {
            "actor": NOTES,
            "action": "task.completed",
            "target": notes_child.task_id,
            "task_id": notes_child.task_id,
        },
        {
            "actor": SUPERVISOR,
            "action": "task.delegated",
            "target": calendar_child.task_id,
            "task_id": calendar_child.task_id,
            "session_id": sessions[SUPERVISOR],
        },
        {
            "actor": CALENDAR,
            "action": "capability.exercised",
            "target": "calendar:primary",
            "policy": "calendar_per_task",
            "consent_receipt_id": RECEIPT_ID,
        },
        {
            "actor": CALENDAR,
            "action": "context.resolve",
            "target": resolved["handle"],
            "context_refs": ["obj://sha256:9f2c7b1a"],
        },
    ]

    ledger = audit.AuditLedger(trace_id=TRACE, store=store, clock=lambda: NOW)
    for event in events:
        # The ledger owns audit_id/ts/prev_hash/hash; the demo only supplies
        # the semantic fields, exactly as a Bus service would.
        ledger.append({**event, "decision": event.get("decision", "allow")})

    # The effect pair keeps its §8.11 linkage: the outcome's `intent_ref` is
    # the intent event's ledger-assigned audit_id.
    intent_record = ledger.append(
        {
            "actor": CALENDAR,
            "action": "effect.intent",
            "target": "calendar:primary",
            "decision": "allow",
            "phase": "intent",
            "policy": "calendar_per_task",
            "consent_receipt_id": RECEIPT_ID,
        }
    )
    ledger.append(
        {
            "actor": CALENDAR,
            "action": "effect.executed",
            "target": "calendar:primary",
            "decision": "allow",
            "phase": "outcome",
            "policy": "calendar_per_task",
            "consent_receipt_id": RECEIPT_ID,
            "intent_ref": intent_record["audit_id"],
        }
    )
    ledger.append(
        {
            "actor": CALENDAR,
            "action": "task.completed",
            "target": calendar_child.task_id,
            "decision": "allow",
            "task_id": calendar_child.task_id,
        }
    )
    ledger.append(
        {
            "actor": SUPERVISOR,
            "action": "task.completed",
            "target": parent.task_id,
            "decision": "allow",
            "task_id": parent.task_id,
        }
    )
    chain = ledger.history()
    audit.verify_chain(chain)
    require(ledger.verify(), "the ledger must verify its own chain")
    print(f"recorded {len(chain['events'])} events under {chain['trace_id']} via AuditLedger")

    redacted = audit.redact_chain(chain, salt="demo-export-salt")
    require(redacted["chain_verified"], "the redacted export must stay verifiable")
    require(not redacted["plaintext_recoverable"], "redaction must not leave plaintext")
    print(
        "redacted export: "
        f"chain_verified={redacted['chain_verified']} "
        f"plaintext_recoverable={redacted['plaintext_recoverable']} "
        f"fields={redacted['redacted_fields']}"
    )

    recovery = audit.recover_effects(chain["events"])
    require(recovery["effect_state"] == "complete", "intent and outcome must reconcile")
    print(f"recovery: effect_state={recovery['effect_state']} alerted={recovery['alerted']}")

    trace = audit.trace_complete(trace_messages)
    require(trace["single_trace"], "every hop must share one trace_id")
    require(trace["complete"], "every hop after the first must carry causation_id")
    print(
        f"trace: single_trace={trace['single_trace']} "
        f"missing_causation={trace['missing_causation']} complete={trace['complete']}"
    )

    # --- 7. crash and restart ---------------------------------------------
    section("7. crash and restart (§3.7, §8.11)")

    recovery_doc = copy.deepcopy(load("task.json"))
    recovery_doc["task_id"] = "task_demo_recovery"
    recovery_doc["session_id"] = sessions[SUPERVISOR]
    recovery_task = board.add(task.Task.from_document(recovery_doc))
    board.transition(recovery_task, "accepted")
    board.transition(recovery_task, "running")

    intent_ref = "intent_recovery_write"
    board.record_effect_intent(
        recovery_task.task_id, intent_ref=intent_ref, target="calendar:primary"
    )
    print(f"effect intent {intent_ref} persisted before the side effect (§8.11)")

    fabric = context.ContextFabric(store=store)
    fabric.open_blackboard(
        recovery_task.task_id,
        entries=[{"key": "proposal", "value": {"slot": "10:00-11:00"}}],
    )

    index = idempotency.IdempotencyIndex(store=store)

    def write_calendar():
        print("  side effect executes (calendar:primary)")
        return {"written": True}

    _, replayed = index.execute_once("msg_demo_recovery_write", write_calendar)
    require(not replayed, "the first delivery must execute the side effect")

    print("crash: dropping every in-memory object, reopening the store")
    store = JsonStore(state_path)
    board = task.TaskBoard(store=store)
    ledger = audit.AuditLedger(trace_id=TRACE, store=store, clock=lambda: NOW)
    fabric = context.ContextFabric(store=store)
    index = idempotency.IdempotencyIndex(store=store)
    require(ledger.verify(), "the audit chain must verify after the restart")
    require(
        len(fabric.blackboard(recovery_task.task_id)["entries"]) == 1,
        "an open blackboard survives the restart with its entries",
    )
    print("reopened: task tree, effects, audit chain, blackboard, idempotency index")

    try:
        board.require_replay_allowed(intent_ref)
        raise AssertionError("the replay gate must refuse an unknown effect")
    except OsapError as error:
        require(error.code == "POLICY_DENIED", "unknown effects fail closed")
        print(f"replay blocked: {error.details['reason']} (§8.11)")

    recovered = board.recover()
    require(
        recovered["effects"]["effect_state"] == "unknown",
        "intent-only effects must be marked unknown",
    )
    require(
        board.require(recovery_task.task_id).status == "failed",
        "the running task must be recovered to failed",
    )
    print(
        f"recovered {len(recovered['recovered_tasks'])} task to failed; "
        "effect intent marked unknown"
    )

    _, replayed = index.execute_once("msg_demo_recovery_write", write_calendar)
    require(
        replayed,
        "the restarted Bus must replay the cached result, not re-execute",
    )
    print("duplicate delivery replayed from the idempotency index (§7.3)")

    board.reconcile_effect(intent_ref, outcome="not_executed")
    board.require_replay_allowed(intent_ref)
    print(
        "reconciled: outcome=not_executed; an explicit retry is now an "
        "operator decision, not a silent replay"
    )

    report = fabric.close_blackboard(recovery_task.task_id)
    require(report["promoted_to_memory"] is False, "blackboards are never promoted")
    require(
        fabric.blackboard(recovery_task.task_id)["entries"] == [],
        "closing the blackboard clears its entries",
    )
    reopened_fabric = context.ContextFabric(store=JsonStore(state_path))
    require(
        reopened_fabric.blackboard(recovery_task.task_id)["promoted_to_memory"]
        is False,
        "a closed blackboard is not promoted across restarts either",
    )
    print("blackboard: entries cleared on close and never promoted (§9.5)")

    section("demo complete")
    print("registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified")
    print("trace=complete redaction=verified recovery=complete")
    print(
        "crash=recovered replay=blocked reconcile=not_executed "
        "idempotent=across_restart blackboard=dies_with_task"
    )
    shutil.rmtree(state_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
