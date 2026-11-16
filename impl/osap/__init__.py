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
- M2.5: task tree, budgets, cancellation, results, handoff (§8); context
  fabric handles, labels, blackboard, objects (§9); federation adapters
  projecting native descriptors into capability records (§6.7, §6.8);
- M2.6: audit-chain verification, redacted export, replay, and recovery
  (§10.5–§10.7, §8.11);
- persistence: a sectioned, atomic `JsonStore` that backs the idempotency
  index and capability issuance/revocation state so a restart replays instead
  of re-executing (§7.8, §5.5).
"""

from . import (
    audit,
    capability,
    consent,
    consent_flow,
    context,
    crypto,
    federation,
    identity,
    registry,
    schema,
    store,
    task,
    transport,
)
from .bus import Bus
from .clock import Deadline
from .envelope import KNOWN_TYPES, SUPPORTED_MAJOR, validate
from .errors import STANDARD_CODES, OsapError
from .framing import MAX_FRAME_BYTES, Binding
from .idempotency import IdempotencyIndex
from .store import JsonStore

__all__ = [
    "Binding",
    "Bus",
    "Deadline",
    "IdempotencyIndex",
    "JsonStore",
    "KNOWN_TYPES",
    "MAX_FRAME_BYTES",
    "OsapError",
    "STANDARD_CODES",
    "SUPPORTED_MAJOR",
    "audit",
    "capability",
    "consent",
    "consent_flow",
    "context",
    "crypto",
    "federation",
    "identity",
    "registry",
    "schema",
    "store",
    "task",
    "transport",
    "validate",
]
