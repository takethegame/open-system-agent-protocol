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
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))

from osap import capability  # noqa: E402

EXAMPLES = REPO / "examples"
DEFAULT_THRESHOLD_MS = 100.0


def template() -> dict:
    return json.loads((EXAMPLES / "capability.json").read_text(encoding="utf-8"))


def build_tree(width: int, depth: int) -> list[dict]:
    """Return a parent-before-child list with `width ** depth` leaves."""

    tokens = []
    base = template()
    base.pop("parent_cap_id", None)
    base["depth"] = 0
    base["cap_id"] = "cap_tree_0"
    base["constraints"]["max_depth"] = depth
    tokens.append(base)

    frontier = ["cap_tree_0"]
    for level in range(1, depth + 1):
        next_frontier = []
        for parent in frontier:
            for index in range(width):
                cap_id = f"cap_tree_{len(tokens)}"
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
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
