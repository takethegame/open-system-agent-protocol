# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Receiver-side stream state (standard.md §7.5).

A stream moves one long result in ordered chunks. `stream.open` declares
the stream with an optional `total_estimate`; every `stream.chunk` carries
a `stream_id`, a 1-based `seq`, and either inline `data` or a `ref`
handle; `stream.close` ends it with a `status` (`complete`, `cancelled`,
or `error`) and an optional `summary`.

The receiver MUST deduplicate by `seq`, MUST be able to order what it has,
and MUST be able to see which sequence numbers are missing so it can ask
for a retransmission. This registry is that receiver-side state: chunks are
stored by their first arrival (a re-delivered `seq` never overwrites),
`view()` returns the ordered payload plus the gap list, and `close()`
freezes the stream with its final status. Cancel linkage is the caller's
job — a cancelled task closes its streams with `status="cancelled"` (§7.5).

Streams are runtime state, not Bus memory: an open stream that never
receives a `close` simply dies with the process, and the registry is
therefore not persisted.
"""

from __future__ import annotations

import copy

from .errors import OsapError

#: Final statuses accepted by `stream.close` (§7.5).
CLOSE_STATUSES = ("complete", "cancelled", "error")


class StreamRegistry:
    """Ordered, deduplicated chunk state for open streams (§7.5)."""

    def __init__(self) -> None:
        self._streams: dict[str, dict] = {}

    # --- lifecycle ---------------------------------------------------------

    def open(self, stream_id: str, *, schema: str | None = None,
             total_estimate: int | None = None) -> dict:
        """Declare a stream; a second open for the same id is rejected."""

        if not isinstance(stream_id, str) or not stream_id:
            raise ValueError("stream_id must be a non-empty string")
        if stream_id in self._streams:
            raise OsapError(
                "DUPLICATE",
                f"stream already open: {stream_id}",
                details={"stream_id": stream_id},
            )
        record = {
            "stream_id": stream_id,
            "schema": schema,
            "total_estimate": total_estimate,
            "chunks": {},
            "status": "open",
            "summary": None,
        }
        if schema is not None and (not isinstance(schema, str) or not schema):
            raise ValueError("schema must be a non-empty string when present")
        if total_estimate is not None and (
            not isinstance(total_estimate, int)
            or isinstance(total_estimate, bool)
            or total_estimate < 0
        ):
            raise ValueError("total_estimate must be a non-negative integer")
        self._streams[stream_id] = record
        return self._view(record)

    def chunk(self, stream_id: str, *, seq: int, data=None, ref: str | None = None) -> dict:
        """Accept one chunk; the first delivery of a `seq` wins (§7.5)."""

        record = self._live(stream_id)
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise ValueError("seq must be a positive integer")
        if (data is None) == (ref is None):
            raise ValueError("a chunk carries exactly one of data or ref")
        existing = record["chunks"].get(seq)
        if existing is not None:
            # MUST deduplicate by seq: the retransmitted copy is dropped.
            return self._view(record)
        if ref is not None and (not isinstance(ref, str) or not ref):
            raise ValueError("ref must be a non-empty handle")
        record["chunks"][seq] = {
            "seq": seq,
            "data": copy.deepcopy(data),
            "ref": ref,
        }
        return self._view(record)

    def close(self, stream_id: str, *, status: str, summary: str | None = None) -> dict:
        """Freeze the stream with a final status and release ordering."""

        record = self._live(stream_id)
        if status not in CLOSE_STATUSES:
            raise ValueError(f"close status must be one of {CLOSE_STATUSES}")
        if summary is not None and (not isinstance(summary, str) or not summary):
            raise ValueError("summary must be a non-empty string when present")
        record["status"] = status
        record["summary"] = summary
        view = self._view(record)
        if status != "complete":
            # §7.5: cancelling frees the resources; a complete stream keeps
            # its chunks because the assembled result is the whole point.
            record["chunks"] = {}
        return view

    # --- inspection --------------------------------------------------------

    def _live(self, stream_id: str) -> dict:
        if not isinstance(stream_id, str) or not stream_id:
            raise ValueError("stream_id must be a non-empty string")
        record = self._streams.get(stream_id)
        if record is None:
            raise OsapError(
                "ROUTING_NOT_FOUND",
                f"unknown stream: {stream_id}",
                details={"stream_id": stream_id},
            )
        if record["status"] != "open":
            raise OsapError(
                "POLICY_DENIED",
                f"stream {stream_id} is already closed",
                details={"stream_id": stream_id, "status": record["status"]},
            )
        return record

    def view(self, stream_id: str) -> dict | None:
        """Ordered chunks, the missing-sequence list, and the close state."""

        record = self._streams.get(stream_id)
        if record is None:
            return None
        return self._view(record)

    def _view(self, record: dict) -> dict:
        seqs = sorted(record["chunks"])
        missing = (
            []
            if not seqs
            else [seq for seq in range(seqs[0], seqs[-1] + 1) if seq not in record["chunks"]]
        )
        return {
            "stream_id": record["stream_id"],
            "schema": record["schema"],
            "total_estimate": record["total_estimate"],
            "status": record["status"],
            "summary": record["summary"],
            "received": len(record["chunks"]),
            "chunks": copy.deepcopy([record["chunks"][seq] for seq in seqs]),
            "missing": missing,
        }
