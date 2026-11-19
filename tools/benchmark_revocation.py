# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Measure revocation-propagation latency (M2 exit criterion).

The standard requires a revoked capability to stop authorising within the
declared propagation bound. The reference implementation has no out-of-process
notification path, so this benchmark measures the observable in-process bound:
from `CapabilityAuthority.revoke(root)` returning until every token in the tree
reports `is_revoked()`.

Run it locally before releasing; it is deliberately not part of CI because
timing thresholds are machine-dependent:

    python3 tools/benchmark_revocation.py
    python3 tools/benchmark_revocation.py --samples 500 --width 8 --depth 4
    python3 tools/benchmark_revocation.py --cross-process --samples 20
"""

from __future__ import annotations

import argparse
import copy
import json
import multiprocessing
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))

from osap import capability  # noqa: E402
from osap.store import JsonStore  # noqa: E402

EXAMPLES = REPO / "examples"
DEFAULT_THRESHOLD_MS = 100.0


def template() -> dict:
    return json.loads((EXAMPLES / "capability.json").read_text(encoding="utf-8"))


def build_tree(width: int, depth: int, prefix: str = "cap_tree") -> list[dict]:
    """Return a parent-before-child list with `width ** depth` leaves."""

    tokens = []
    base = template()
    base.pop("parent_cap_id", None)
    base["depth"] = 0
    base["cap_id"] = f"{prefix}_0"
    base["constraints"]["max_depth"] = depth
    tokens.append(base)

    frontier = [f"{prefix}_0"]
    for level in range(1, depth + 1):
        next_frontier = []
        for parent in frontier:
            for index in range(width):
                cap_id = f"{prefix}_{len(tokens)}"
                child = copy.deepcopy(template())
                child["cap_id"] = cap_id
                child["parent_cap_id"] = parent
                child["depth"] = level
                child["constraints"]["max_depth"] = depth
                tokens.append(child)
                next_frontier.append(cap_id)
        frontier = next_frontier
    return tokens


def percentiles(durations: list[float], *points: float) -> dict[float, float]:
    ordered = sorted(durations)
    result = {}
    for point in points:
        rank = max(0, min(len(ordered) - 1, round(point / 100 * len(ordered)) - 1))
        result[point] = ordered[rank] * 1000
    return result


def run(width: int, depth: int, samples: int) -> list[float]:
    tokens = build_tree(width, depth)
    durations = []
    for _ in range(samples):
        authority = capability.CapabilityAuthority()
        for token in tokens:
            authority.issue(token)
        started = time.perf_counter()
        revoked = authority.revoke("cap_tree_0")
        if revoked != len(tokens):
            raise SystemExit(f"revoked {revoked} of {len(tokens)} tokens")
        for token in tokens:
            if not authority.is_revoked(token):
                raise SystemExit(f"token {token['cap_id']} still usable")
        durations.append(time.perf_counter() - started)
    return durations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=6, help="children per node")
    parser.add_argument("--depth", type=int, default=4, help="tree depth")
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--threshold-ms", type=float, default=DEFAULT_THRESHOLD_MS)
    parser.add_argument(
        "--cross-process",
        action="store_true",
        help="measure revoke -> a replica process reporting is_revoked()",
    )
    parser.add_argument(
        "--chain-length",
        type=int,
        default=10,
        help="tokens per independent chain in cross-process mode",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="revoke a full width/depth tree per sample in cross-process mode",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.005,
        help="replica poll interval in seconds (cross-process mode)",
    )
    parser.add_argument(
        "--cross-threshold-ms",
        type=float,
        default=250.0,
        help="p95 bound for cross-process propagation",
    )
    args = parser.parse_args()

    if args.cross_process:
        return run_cross_process(args)
    durations = run(args.width, args.depth, args.samples)
    stats = percentiles(durations, 50, 95, 99)
    tokens = sum(args.width**level for level in range(args.depth + 1))

    print(
        f"tree: width={args.width} depth={args.depth} tokens={tokens} "
        f"samples={args.samples}"
    )
    print(
        f"p50={stats[50]:.3f} ms  p95={stats[95]:.3f} ms  "
        f"p99={stats[99]:.3f} ms  max={max(durations) * 1000:.3f} ms  "
        f"mean={statistics.fmean(durations) * 1000:.3f} ms"
    )
    if stats[95] >= args.threshold_ms:
        print(
            f"FAIL: p95 {stats[95]:.3f} ms is not below "
            f"{args.threshold_ms:.3f} ms"
        )
        return 1
    print(f"PASS: p95 is below {args.threshold_ms:.3f} ms")
    return 0


# --- cross-process propagation -----------------------------------------------

#: The source label the watcher/replica subscribes to.
_SOURCE = "issuer"


def _cross_worker(
    source_path: str,
    replica_path: str,
    interval: float,
    progress,
    stop,
) -> None:
    """Apply the source journal until the parent signals stop.

    `progress` receives `(source_seq, monotonic)` for every batch the replica
    applies, so the parent can measure `revoke -> is_revoked()` end to end.
    """

    replica = capability.CapabilityAuthority(store=JsonStore(replica_path))
    while not stop.is_set():
        journal = JsonStore(source_path).get("capability.revocations") or []
        if journal:
            try:
                report = replica.apply_revocations(journal, source=_SOURCE)
            except Exception:
                time.sleep(interval)
                continue
            progress.put((report["cursor"], time.monotonic()))
        time.sleep(interval)
    progress.close()


def run_cross_process(args) -> int:
    """Measure `revoke` in one process to `is_revoked()` in another.

    The parent owns the issuing authority and its store file; the child owns
    a replica store and polls the source journal on `--interval`. The
    measured span is from `revoke()` returning until the child reports the
    sample's last journal sequence applied, which includes the poll wait,
    file read, validation, and the replica-side cascade.
    """

    if args.samples < 1:
        raise SystemExit("--samples must be positive")
    context = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory() as directory:
        source_path = str(Path(directory) / "source.json")
        replica_path = str(Path(directory) / "replica.json")
        source = capability.CapabilityAuthority(store=JsonStore(source_path))
        roots = []
        tokens_per_chain = args.chain_length + 1
        if args.tree:
            tokens_per_chain = sum(args.width**level for level in range(args.depth + 1))
        for index in range(args.samples):
            if args.tree:
                prefix = f"cap_x_{index}"
                tokens = build_tree(args.width, args.depth, prefix=prefix)
                for token in tokens:
                    source.issue(token)
                roots.append(f"{prefix}_0")
                continue
            root_cap = f"cap_x_{index}_0"
            token = template()
            token.pop("parent_cap_id", None)
            token["cap_id"] = root_cap
            token["depth"] = 0
            source.issue(token)
            parent_id = root_cap
            for position in range(1, args.chain_length):
                child = copy.deepcopy(template())
                child["cap_id"] = f"cap_x_{index}_{position}"
                child["parent_cap_id"] = parent_id
                child["depth"] = position
                source.issue(child)
                parent_id = child["cap_id"]
            roots.append(root_cap)

        progress = context.Queue()
        stop = context.Event()
        worker = context.Process(
            target=_cross_worker,
            args=(source_path, replica_path, args.interval, progress, stop),
            daemon=True,
        )
        worker.start()
        durations = []
        try:
            for index, root in enumerate(roots):
                started = time.monotonic()
                source.revoke(root)
                end_seq = source.last_seq
                observed = None
                deadline = started + 10.0
                while observed is None:
                    if time.monotonic() > deadline:
                        raise SystemExit(
                            f"sample {index}: replica never applied seq {end_seq}"
                        )
                    seq, moment = progress.get(timeout=1.0)
                    if seq >= end_seq:
                        observed = moment
                durations.append(observed - started)
        finally:
            stop.set()
            worker.join(2)
            if worker.is_alive():
                worker.terminate()
        stats = percentiles(durations, 50, 95, 99)
        print(
            f"cross-process: chains={args.samples} "
            f"tokens_per_chain={tokens_per_chain} "
            f"interval={args.interval * 1000:.1f} ms"
        )
        print(
            f"p50={stats[50]:.3f} ms  p95={stats[95]:.3f} ms  "
            f"p99={stats[99]:.3f} ms  max={max(durations) * 1000:.3f} ms  "
            f"mean={statistics.fmean(durations) * 1000:.3f} ms"
        )
        print("(spans one poll interval; not comparable to the in-process p95)")
        if stats[95] >= args.cross_threshold_ms:
            print(
                f"FAIL: p95 {stats[95]:.3f} ms is not below "
                f"{args.cross_threshold_ms:.3f} ms"
            )
            return 1
        print(f"PASS: p95 is below {args.cross_threshold_ms:.3f} ms")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
