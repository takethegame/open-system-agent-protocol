# Changelog

All notable changes to this repository are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Entries are written in English to match commit messages; the Chinese text in
`docs/standard.md` remains the normative source.

## [Unreleased]

### Added

- `drafts/`: two IETF xml2rfc v3 individual-draft skeletons, `draft-osap-capability-tokens-00` (token format, attenuation, binding, revocation, consent linkage) and `draft-osap-consent-receipts-00` (consent request, receipt, reservation ordering, audit, informative ISO/IEC 27560 mapping).
- `drafts/README.md`: section-by-section mapping back to `docs/standard.md`, build commands, publication prerequisites, and known boundaries.
- `tools/check_drafts.py` and `requirements-drafts.txt`: static checks for XML, v3 front matter, anchors/xrefs, references, JSON examples, placeholders, local references, and ASCII; `--compile` runs `xml2rfc` and emits text/HTML.
- `bindings/linux/`: the Linux binding profile (Chinese and English) with D-Bus names, object paths, method signatures, peer authentication, error mapping, `xdg-desktop-portal` mapping, `systemd --user` units, and three sequence diagrams; example socket/service units and D-Bus activation files.
- `decisions/0001-*.md` through `0014-*.md`: ADRs for the fourteen open issues in `docs/standard.md` Section 15, each with a provisional decision, consequences, alternatives, and a re-review trigger.
- `GOVERNANCE.md` Section 9.1 (and the English parallel): the actual liaison status as of 2026-11-19, explicitly distinguishing individual drafts from IETF adoption.
- `.github/workflows/ci.yml`: a `drafts` job that installs `requirements-drafts.txt` and runs `tools/check_drafts.py --compile`.
- `conformance/`: machine-readable cases for C0 (7), C1 (6), C2 (6), C3 (12), C4 (11), C5 (11), C6 (8), and C7 (7), plus `case.schema.json`, `suite.schema.json`, `report.schema.json`, and `README.md`.
- `examples/context-handle.json`, `examples/blackboard.json`, and `examples/audit-chain.json`: context-fabric and audit-chain fixtures.
- `impl/`: reference implementation for M2.1 — envelope validation, the error model, stream and message framing, handshake, idempotency, and monotonic-clock deadlines.
- `impl/osap/crypto.py`, `identity.py`, and `registry.py` (M2.2): Ed25519 manifest signatures, agent registration with reserved-namespace and public-key binding checks, capability-record indexing with TTL, and discovery candidates that carry a static `consent_hint` only.
- `impl/osap/capability.py` (M2.3): capability-token validation, the ten attenuation rules of §5.3, stateless audience/task/subject binding, revocation with cascade, and the L3/L4 consent prerequisite.
- `impl/osap/consent.py` (M2.4): consent-receipt validation ordered as decision, expiry, scope binding, then action/resource subsets.
- `impl/osap/consent_flow.py` (M2.4b): the §10.2–§10.3 consent flow — request validation with preview TTL, `cap_id` reservation that stays inert, grant/deny restricted to offered options, receipt issuance with expiry clamped to the request, activation through `consent.validate` and `CapabilityAuthority.issue`, and revocation that cascades to the issued capability.
- `impl/osap/registry.py`: `capability_descriptor()` and `risk_of()` so an envelope route can be resolved to the receiving agent and its declared risk class.
- `impl/osap/task.py` (M2.5a): task tree, the §8.10 state machine, delegation budget and depth checks, cancellation that skips detached subtrees, result-contract validation, and handoff with ownership transfer.
- `impl/osap/context.py` (M2.5b): handle resolution with `resolve`/`memory.read` grants, OS-permission and audience checks, non-renewing expiry, information-flow labels, egress consent, blackboard archival, tombstoning deletes, cache-TTL clamping, storage-duty declarations, and the memory-promotion boundary.
- `impl/osap/federation.py` (M2.5c): read-only projection of Android/Apple/Windows, MCP, A2A, D-Bus, and OpenAPI descriptors into capability records, preserving native identity, mapping namespaces deterministically, and capping external trust at `unverified`.
- `impl/osap/audit.py` (M2.6): audit-chain verification with schema, trace, and hash-linkage checks; salted-commitment redacted export; idempotent replay; intent-only recovery marked `unknown`; cross-user authorization; and the 0.1 compromised-Bus declaration.
- `impl/osap/transport.py` (M2.1b): an authenticated `AF_UNIX` stream server/client with length framing and one `Bus` per connection, a datagram message pair that preserves native boundaries without a prefix, and a fail-closed `PeerPolicy` over kernel-attested uid/gid/pid/executable (Linux `SO_PEERCRED`, macOS `getpeereid`/`LOCAL_PEERPID`).
- `impl/osap/store.py`: a sectioned JSON document store with atomic `os.replace`, `fsync`, mode 0600, rollback on a failed serialization, and `put_many` for a multi-section atomic flush; one instance per path is shared by subsystems and each writes its own section.
- `impl/osap/idempotency.py` and `impl/osap/capability.py`: the idempotency cache and the capability issuance/revocation state can be persisted through `JsonStore`; a reopened `CapabilityAuthority` rebuilds the `parent_cap_id → children` index, and a reopened `Bus` replays a duplicate `id` instead of re-executing its side effect.
- `impl/osap/consent_flow.py`: with a `JsonStore`, consent requests, receipts, reservations, and a generated PCS signing key survive a restart; request timestamps are restored as datetimes, terminal states stay terminal, and an injected signer is never written. An optional `KeyRegistry` lets `activate` resolve `proof.kid` and verify without the PCS private key; `publish_pcs_key()` registers the flow's own key, and flows without a registry keep verifying against their signer. `key_store=` moves `consent.pcs_key` into a dedicated store, and `ConsentFlow.verifier()` builds a registry-backed verifier whose ephemeral signer is never persisted.
- `impl/osap/task.py`: `TaskBoard(store=...)` persists the whole tree in one `task.tasks` section; `Task.to_state()` records every field the board needs, including `consumed` and `detached`, and `from_state()` rejects corrupt records instead of restoring a partial tree.
- `impl/osap/task.py`: a durable `task.effects` journal with `record_effect_intent`, `record_effect_outcome`, `reconcile_effect`, and `require_replay_allowed`; `recover(policy=...)` fails every non-terminal task (or returns it to `created`), marks every intent-only effect `unknown`, writes both sections through one `put_many`, and returns audit-ready recovery events. A pending or unknown effect cannot be replayed until reconciliation, and a reconciled execution cannot be replayed again.
- `impl/osap/context.py`: `ContextFabric(store=...)` writes every `context.resolve` allow/deny to one `context.events` section, validates each stored event on reopen, and optionally keeps only the newest `limit` events so the in-memory list and the file cannot drift; the in-memory default is unchanged.
- `impl/osap/context.py`: the same fabric also persists the handle registry (`context.handles`), task blackboards (`context.blackboards`), and object metadata plus tombstones (`context.objects`). A string handle resolves through the registry and an unknown identifier fails closed with `CONTEXT_NOT_FOUND`; a registered handle still passes the audience, `allowed_agents`, OS-permission, grant, expiry, and egress checks. Blackboards keep their optional version, TTL, and timestamps, are cleared when closed, stay `promoted_to_memory=false`, and reopen validation rejects a closed board with entries or promotion. Object records enforce reference counts, hard-delete only at zero references, tombstone a referenced delete, and reject `deleted` together with `tombstoned` or a non-zero count. Each mutation rewrites one section atomically; the in-memory default is unchanged.
- `impl/osap/audit.py`: `AuditLedger` records one trace, fills `audit_id`, `ts`, `prev_hash`, and `hash`, writes one `audit.chain.<trace_id>` section per append, and rechecks every body hash on reopen; a broken link, a foreign trace, or a tampered body fails closed with `AUDIT_CHAIN_INVALID`. `max_events=` trims the oldest events into `audit.archive.<trace_id>` with one atomic `put_many`, keeps the live chain's first `prev_hash` pointing at the archived tail, verifies the archive from genesis on reopen, and exposes the whole history through `history()`.
- `impl/osap/keystore.py`: a `KeyStore` contract (`load`, `save`, optional `delete`) for the one PCS signing record, with `JsonKeyStore` over a `JsonStore` section, `MemoryKeyStore` for ephemeral verifiers, and `KeyringKeyStore` over the macOS `security` CLI or Linux `secret-tool`. `signer_of` validates shape, `kid`, the Ed25519 private key, and a matching public key in one place, and `as_key_store` wraps a bare `JsonStore` so existing call sites keep the 0600 JSON layout.
- `impl/osap/pcs.py`: Ed25519 consent-receipt signing over the canonical receipt body with `proof` removed, offline verification, and `ConsentSigner` key handling; `KeyRegistry` keeps public PCS keys by `kid` with `active`/`retired`/`revoked` lifecycle state, `not_before`/`not_after` windows, rotation with a retirement grace window, terminal revocation, and receipt verification that resolves `proof.kid`. A persisted `pcs.keys` section is revalidated on reopen, and failures use `AUTH_DENIED` with distinct reasons.
- `impl/osap/flowcontrol.py`: per-identity `Quota`, `AdmissionController`, and `Admission` leases — connection, in-flight, bounded FIFO queue, and token-bucket rate limits on a monotonic clock; rejections use `RATE_LIMIT` with `reason`, `retry_after_ms`, queue depth, and the effective quota.
- `impl/osap/audit.py`: `AuditJournal` partitions audit chains by `user://` identity under `audit.user.<user>.chain.<trace>` and keeps one contiguous cross-trace order index in `audit.order.<user>`. Each append writes the chain, an optional archive migration, and the next order entry in one atomic `put_many`; `AuditLedger.append` takes an internal companion callback and rolls its in-memory chain back when the write fails. A reopen cross-checks the order against every chain history and rejects gaps, duplicates, timestamp mismatches, orphaned entries, and unordered events with `AUDIT_CHAIN_INVALID`.
- `impl/osap/keystore.py`: a Windows keyring backend over PowerShell and the Windows `PasswordVault` (Credential Manager) with the secret piped on stdin, `KeyringError` carrying a diagnosable `reason` (`backend_missing`, `lookup_failed`, `store_failed`) plus the backend name and CLI `returncode`/`stderr`, and `migrate_key_store(source, target)` which validates the record first, refuses to overwrite a different target key, makes an identical target idempotent, verifies after writing, and deletes the source only then; `tools/migrate_pcs_key.py` wraps the migration as a CLI with JSON reports.
- `impl/tests/`: 720 unit tests covering framing, validation order, idempotency, deadlines, signatures, registration rejections, registry freshness, attenuation per dimension, revocation cascade, binding, receipt ordering, consent request TTLs and options, inert reservations, denial and revocation terminal states, receipt-expiry clamping, task state transitions, cancellation, delegation budgets, result contracts, handoff rejections, the context fabric's grant, expiry, label, egress, blackboard, delete, cache, storage, and memory rules, federated native-identity projection with external-trust normalization, real UDS stream and datagram round trips with connection isolation and peer authentication, audit-chain verification, redaction, replay, recovery, and cross-user rules, durable store round-trips, restart replay, revocation survival, receipt signing, tampering, wrong-key, and self-signed-activation rejection, consent-flow reopen with signer reuse and terminal-state persistence, quota validation, token refill, per-Agent isolation, queue grant/full/timeout, connection limits, wire-level `RATE_LIMIT`, concurrent serving with an idle peer and a same-Agent cross-connection queue, task-tree reopen with budget, consumed, detached, parent links, cancellation, delegation, handoff, and one write per mutation, audit-ledger append, linkage, body-hash recomputation, per-trace isolation, and corrupt-section rejection, PCS key registration, validity windows, rotation with and without grace, revocation idempotence, verification failure reasons, detached records, reopen, and corrupt-section rejection, consent-flow key publication, cross-signer registry activation, fallback without a registry, revoked-key and grace-window verification, tampered-receipt rejection, registry reopen, split key/receipt stores, verifier construction, and no-key verifier reopen, key-record validation, JSON and in-memory key stores, platform backend selection, keyring command construction with missing entries, stdin versus argv secrets, backend failures, flow-level key reuse with a clean receipt store, context-event round trips and ordering, restore validation of every event field, retention limits on append and reopen, custom sections, the in-memory default, audit trimming into an archive, linkage across the live/archive boundary, reopen with and without a limit, duplicate ids across the boundary, tampered, truncated, or re-rooted archives, task recovery under `fail` and `reschedule`, detached and nested tasks, idempotent recovery, one atomic recovery write, effect-intent persistence and restore validation, outcome idempotence, unknown-effect reconciliation, replay gating, recovery audit-event shape, context handle and blackboard reopen with conflict rejection, object reference counts, tombstones, hard-delete refusal, corrupt-record rejection, per-user audit partitions, cross-trace ordering, atomic chain/order writes, order/chain mismatch rejection, Windows PasswordVault command construction with stdin secrets, missing-entry and failure reasons, backend-missing construction, and key migration across backends with occupied-target and idempotent paths.
- `demo/run_demo.py` and `demo/README.md` (M2.7): a three-agent end-to-end demo that registers signed manifests, discovers a capability record, runs the L3 consent flow from request through activation, delegates to notes and calendar across two boundaries, resolves a memory context handle, and verifies plus redacts a 16-event audit chain with asserted trace completeness and side-effect-free recovery.
- `spec/formal/`: TLA+ models for capability attenuation/revocation, task budgets/cancellation, consent request ordering, and §8.11 crash reconciliation; a bounded-closure `check.sh`; and two negative-control configurations that must each produce a counterexample.
- `tools/benchmark_revocation.py`: a local, CI-excluded revocation-propagation benchmark over a configurable tree; it measures from `revoke(root)` to every descendant reporting `is_revoked()` and enforces a p95 below 100 ms.
- `tools/conformance_run.py`: loads and validates cases, applies JSON Pointer mutations, runs an implementation adapter, and emits text, JSON, or Markdown reports.
- `docs/roadmap.md`: milestone plan from 0.1 to 0.2 (M0–M5, decision gates, risk register).
- `SECURITY.md` / `SECURITY.en.md`: disclosure channel, timelines, security review triggers.
- `.github/workflows/ci.yml`: schema meta-validation, example validation, and documentation checks on Python 3.11 and 3.12.
- `tools/check_schemas.py`: validates every schema against the 2020-12 metaschema, enforces unique `urn:osap:schema:` `$id`s, and rejects unsupported `$ref` targets.
- `tools/check_docs.py`: checks JSON code blocks, fence balance, relative links, Chinese/English structural parity, and personal-identifier leakage.
- `.gitignore`, `requirements.txt`, and `CHANGELOG.md`.

### Changed

- Repository renamed from `open-system-agent-protocal` to `open-system-agent-protocol`; the GitHub URL, local directory, `origin` remote, and CI badge links were updated accordingly.
- `CONTRIBUTING.md` / `CONTRIBUTING.en.md`: state that the Chinese text is the normative original and `*.en.md` files are parallel translations.
- `schemas/envelope.schema.json`: require `session_id` when `task.mode` is `peer`, matching standard §8.4.
- `tools/conformance_run.py`: JSON output is now validated against `report.schema.json`; CI runs the same check.
- CI now runs the reference implementation unit tests and the conformance suite against `impl/adapter.py`.

### Changed

- `conformance/cases/C3-authorization.json`: C3-04…C3-07 now name the pristine capability fixture as `context`, so the parent token is derived from it rather than from the mutated child. Expected outcomes and error codes are unchanged.
- `conformance/cases/C0-transport.json`: C0-01 and C0-06 are now automated against real `AF_UNIX` sockets (stream handshake rejection and prefix-free message delivery); `conformance/case.schema.json` accepts the new `transport` operation.
- `conformance/cases/C4-collaboration.json`: C4-08 and C4-09 are now automated. C4-08 reopens a persisted board, recovers a running task to `failed`, and verifies the persisted audit chain; C4-09 records `effect.intent`, crashes before the outcome, recovers the effect to `unknown`, and asserts replay is blocked with `reconciliation_required`.
- `tools/conformance_run.py --stub`: now also checks case-ID coverage against `docs/conformance.md` and materialises every `input.ref`, `context`, and mutation, so a missing fixture or a bad JSON Pointer fails CI instead of being skipped.
- `impl/osap/capability.py`: `CapabilityAuthority` now indexes `parent_cap_id → children` on issuance, so revocation walks each descendant once instead of rescanning every issued token per level; a repeated revocation returns 0 and writes no duplicate audit event. `issue` now rejects a revoked `cap_id` or a revoked `parent_cap_id` with `CAPABILITY_REVOKED`, a gap found by the TLA+ model.
- `IdempotencyIndex` and `CapabilityAuthority` accept an optional `JsonStore`; `Bus` accepts either an explicit index or a store path/instance and rejects passing both. State remains memory-only when no store is supplied.
- `ConsentFlow` now signs every granted receipt with a `ConsentSigner` and verifies the proof in `activate` before checking reservation state; the signer is injectable and `pcs_key` exposes only the public half. `ConsentFlow` also accepts a `JsonStore`, persisting requests, receipts, reservations, and a generated signing key across restarts.
- `Bus` now admits every envelope through an `AdmissionController` by default, with `admission_wait` controlling whether a caller waits for an in-flight slot or receives `RATE_LIMIT` immediately. A shared controller enforces one message quota per Agent across connections.
- `UnixStreamServer` enforces a connection quota keyed by kernel-attested executable, pid, or uid, returns a `RATE_LIMIT` error frame before closing a rejected connection, and passes its controller to the default per-connection `Bus`.
- `UnixStreamServer.serve_forever(concurrency=N)` serves up to N connections in parallel through a bounded thread pool; an idle peer no longer blocks another peer's handshake, same-Agent connections share in-flight and queue limits through the server controller, and `close()` shuts down sessions so blocked workers exit.
- `TaskBoard` accepts a `JsonStore` and writes one atomic `task.tasks` section after `add`, `transition`, `cancel`, `delegate`, or an accepted `handoff`; a no-op transition and a rejected handoff do not write, cancellation flushes once for the whole subtree, and the audit list stays in memory.
- CI now runs `python3 demo/run_demo.py` after the unit tests and the conformance suite.
- `tools/check_docs.py` now also checks structural parity for the Linux binding profile (`bindings/linux/profile.md` and `profile.en.md`).
- `docs/roadmap.md` marks the M4 packaging tasks complete and records that the drafts are local individual submissions, not IETF submissions; `docs/progress.md` adds Section 17 with the deliverables, evidence, and boundaries; both READMEs now list `drafts/`, `bindings/`, `decisions/`, and `requirements-drafts.txt`.

### Planned

- Storage for context handles, blackboards, and object metadata, per-user audit partitioning with a cross-trace order, cross-subsystem atomic recovery audit, and replacing the remaining in-memory registry state.
- A Windows Credential Manager backend for `KeyringKeyStore`, a migration helper from a JSON key store into the keyring, and distinguishable keyring error reasons.
- Platform-native bindings (XPC, Binder, named pipe) and localhost mTLS with code-signature or package-identity peer checks.

## [0.1.0] - 2026-11-10

First public discussion draft. No reference implementation.

### Added

- `docs/standard.md`: OSAP 0.1 Draft — architecture, identity, capability model, registry federation, message protocol, task model, context fabric, consent and audit, security considerations, conformance, versioning, and open issues.
- `docs/conformance.md`: conformance levels C0–C7 and 68 test cases.
- `docs/design-draft.md`: non-normative design background and trade-offs.
- `docs/prior-art.md`: prior work survey, comparison matrix, and falsifiable novelty claims.
- `schemas/`: 12 JSON Schemas, including 5 payload schemas.
- `examples/`: 13 example documents.
- `tools/validate_examples.py`: schema and cross-document validation (`OK: 20 checks passed`).
- `GOVERNANCE.md`: versioning, change process, roles, security disclosure, external liaison, license and trademark terms.
- `CONTRIBUTING.md`: proposal process, DCO 1.1, content rules.
- `LICENSE` (Apache-2.0) and `NOTICE`.
- `README.md`: project overview and document index.

### Notes

- New `handoff` message type; `handoff` is a one-shot ownership transfer, not a task mode.
- Two-stage validation: the Bus performs stateless envelope/signature/binding checks; the receiver performs revocation, policy, consent, risk, and business checks.
- Consent issuance order: the CA reserves `cap_id`, the receipt references it, and the CA issues the capability after the grant.
- Trust profiles: only P0 Trusted Bus is claimable in 0.1; P1 Opaque Bus (HPKE) is deferred to 0.2.

## [0.1.1-docs] - 2026-11-11

Editorial pass on the 0.1 draft, no protocol changes.

### Added

- English parallel versions: `README.en.md`, `GOVERNANCE.en.md`, `CONTRIBUTING.en.md`, `docs/standard.en.md`, `docs/conformance.en.md`, `docs/design-draft.en.md`, `docs/prior-art.en.md`.
- Cross-links between Chinese originals and English translations.

### Changed

- Tightened `handoff` semantics, consent binding, audience/task binding, and conformance wording.
- Replaced Chinese human-readable strings inside English code blocks with English equivalents.
- Removed personal identifiers and local paths from documentation and examples.
