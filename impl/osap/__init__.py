# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Reference implementation of an OSAP 0.1 Bus subset.

Covered so far:

- M2.1: envelope, error model, stream and message framing, handshake,
  idempotency, and monotonic-clock deadlines (standard.md §7.1–§7.10);
- M2.1b: authenticated local transport bindings — an `AF_UNIX` stream server
  and client with length framing, plus a datagram message pair (§7.9, §7.10);
- M2.2: Ed25519 manifest signatures, agent registration, reserved namespaces,
  and the registry subset (§4, §6);
- M2.3: capability tokens, attenuation, binding, revocation (§5.1-§5.6);
- M2.4: consent receipts and capability linkage (§5.8); consent request,
  reservation, grant/deny, activation, and revocation flow (§10.2, §10.3);
- PCS: Ed25519 consent-receipt signing and offline proof verification
  (§10.4), so an Agent cannot self-sign its own consent; a `KeyStore` holds
  the private consent key in a JSON section, in memory, or in the OS keyring;
- M2.5: task tree, budgets, cancellation, results, handoff (§8); context
  fabric handles, labels, blackboard, objects (§9); federation adapters
  projecting native descriptors into capability records (§6.7, §6.8);
- M2.6: audit-chain verification, redacted export, replay, and recovery
  (§10.5–§10.7, §8.11);
- persistence: a sectioned, atomic `JsonStore` that backs the idempotency
  index, capability issuance/revocation state, consent flow, task tree, and
  audit ledger so a restart replays instead of re-executing and a corrupt
  audit chain fails closed (§7.8, §5.5, §10.5);
- flow control: per-Agent connection, in-flight, queue, and token-bucket rate
  limits with explicit `RATE_LIMIT` backpressure (§7.11, §11.7).
"""

from . import (
    audit,
    capability,
    consent,
    consent_flow,
    context,
    crypto,
    federation,
    flowcontrol,
    identity,
    keystore,
    pcs,
    registry,
    schema,
    store,
    task,
    transport,
)
from .audit import AuditLedger
from .bus import Bus, sender_identity
from .clock import Deadline
from .envelope import KNOWN_TYPES, SUPPORTED_MAJOR, validate
from .errors import STANDARD_CODES, OsapError
from .flowcontrol import Admission, AdmissionController, DEFAULT_QUOTA, Quota
from .framing import MAX_FRAME_BYTES, Binding
from .idempotency import IdempotencyIndex
from .keystore import JsonKeyStore, KeyringKeyStore, KeyStore, MemoryKeyStore
from .pcs import ConsentSigner, KeyRegistry
from .store import JsonStore

__all__ = [
    "Admission",
    "AdmissionController",
    "AuditLedger",
    "Binding",
    "Bus",
    "ConsentSigner",
    "DEFAULT_QUOTA",
    "Deadline",
    "IdempotencyIndex",
    "JsonKeyStore",
    "JsonStore",
    "KeyRegistry",
    "KeyStore",
    "KeyringKeyStore",
    "MemoryKeyStore",
    "KNOWN_TYPES",
    "MAX_FRAME_BYTES",
    "OsapError",
    "Quota",
    "STANDARD_CODES",
    "SUPPORTED_MAJOR",
    "audit",
    "capability",
    "consent",
    "consent_flow",
    "context",
    "crypto",
    "federation",
    "flowcontrol",
    "identity",
    "keystore",
    "pcs",
    "registry",
    "schema",
    "sender_identity",
    "store",
    "task",
    "transport",
    "validate",
]
