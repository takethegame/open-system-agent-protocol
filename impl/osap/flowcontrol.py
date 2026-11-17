# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Admission control and explicit backpressure (standard.md §7.11, §11.7).

The Bus core owns connection/session accounting and backpressure. This module
keeps that policy in one place:

- per-identity connection, in-flight, queue, and rate limits;
- a token bucket measured on a monotonic clock, so a wall-clock jump cannot
  grant extra capacity;
- a bounded FIFO wait queue per identity, so a busy Agent cannot consume
  another Agent's slots;
- `RATE_LIMIT` as the only rejection code, with machine-readable details.

Queues are per identity rather than global. A slow or rate-limited sender can
therefore fill its own queue without blocking a different sender's admission.
The queue is FIFO and has no priority scheduling: the standard treats
`priority` as a hint that a sender may drop when necessary, and FIFO is the
simplest way to satisfy its "no starvation" requirement. Weighted fair
queueing remains a SHOULD and is not implemented here.

An `AdmissionController` is safe to share between the UDS listener and every
`Bus` it creates. Connection leases are keyed by kernel-attested peer
attributes; message leases are keyed by the envelope `from` Agent URI.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .errors import OsapError


@dataclass(frozen=True)
class Quota:
    """Limits for one identity. `None` means "not limited"."""

    max_connections: int | None = None
    max_in_flight: int | None = None
    max_queued: int = 0
    rate: int | None = None
    window: float = 1.0

    def __post_init__(self) -> None:
        for name in ("max_connections", "max_in_flight", "max_queued", "rate"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an int or None")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if isinstance(self.window, bool) or not isinstance(self.window, (int, float)):
            raise ValueError("window must be a number")
        if not math.isfinite(self.window) or self.window <= 0:
            raise ValueError("window must be a positive, finite number")

    def to_dict(self) -> dict:
        return {
            "max_connections": self.max_connections,
            "max_in_flight": self.max_in_flight,
            "max_queued": self.max_queued,
            "rate": self.rate,
            "window": self.window,
        }


#: Defaults for a local single-user Bus. They are deliberately generous; the
#: point is to bound an accidental flood, not to throttle normal traffic.
DEFAULT_QUOTA = Quota(
    max_connections=32,
    max_in_flight=16,
    max_queued=32,
    rate=200,
    window=1.0,
)


@dataclass
class _Waiter:
    granted: bool = False


@dataclass
class _State:
    tokens: float = 0.0
    last_refill: float = 0.0
    connections: int = 0
    in_flight: int = 0
    waiters: deque = field(default_factory=deque)
    rejected: int = 0
    last_reject: str | None = None
    condition: threading.Condition | None = None


class Admission:
    """A held connection or message slot. Release it when the work is done."""

    def __init__(self, controller: "AdmissionController", identity: str, kind: str) -> None:
        self._controller = controller
        self.identity = identity
        self.kind = kind
        self.released = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self._controller._release(self)

    def __enter__(self) -> "Admission":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class AdmissionController:
    """Per-identity quotas plus a bounded FIFO wait queue.

    `clock` defaults to `time.monotonic`; tests inject a deterministic clock.
    `quotas` overrides `default` for individual identities.
    """

    def __init__(
        self,
        default: Quota | None = None,
        *,
        quotas: dict[str, Quota] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.default = default or DEFAULT_QUOTA
        self._quotas = dict(quotas or {})
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._states: dict[str, _State] = {}

    # --- inspection -------------------------------------------------------

    def quota_for(self, identity: str) -> Quota:
        return self._quotas.get(_identity(identity), self.default)

    def snapshot(self, identity: str | None = None) -> dict:
        """Return counters and queue depth, for a `status` reply or tests."""

        with self._lock:
            now = self._clock()
            if identity is not None:
                key = _identity(identity)
                state = self._states.get(key)
                quota = self.quota_for(key)
                if state is not None:
                    _refill(state, quota, now)
                return _snapshot(key, state, quota)
            snapshots = {}
            for key, state in sorted(self._states.items()):
                quota = self.quota_for(key)
                _refill(state, quota, now)
                snapshots[key] = _snapshot(key, state, quota)
            return snapshots

    # --- admission --------------------------------------------------------

    def open_connection(self, identity: str, *, timeout: float = 0.0) -> Admission:
        """Reserve one connection slot for `identity`.

        Connections are never queued: a listener rejects the accept and closes
        the socket rather than holding an unauthenticated peer open.
        """

        if timeout != 0:
            raise ValueError("connection admission does not queue")
        key = _identity(identity)
        with self._lock:
            state = self._state(key)
            quota = self.quota_for(key)
            if (
                quota.max_connections is not None
                and state.connections >= quota.max_connections
            ):
                _reject(
                    state,
                    "connection_limit",
                    key,
                    quota,
                    limit=quota.max_connections,
                )
            state.connections += 1
            return Admission(self, key, "connection")

    def admit(
        self,
        identity: str,
        *,
        cost: int = 1,
        timeout: float = 0.0,
    ) -> Admission:
        """Reserve one message slot, waiting up to `timeout` seconds.

        The rate check happens before any wait: waiting for an in-flight slot
        cannot create tokens, so a rate-limited sender is rejected immediately.
        A waiting sender that times out is removed from its own queue and gets
        its token back.
        """

        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
            raise ValueError("cost must be a positive int")
        if timeout < 0:
            raise ValueError("timeout must not be negative")

        key = _identity(identity)
        with self._lock:
            state = self._state(key)
            quota = self.quota_for(key)
            now = self._clock()
            _refill(state, quota, now)

            needs_wait = (
                quota.max_in_flight is not None
                and state.in_flight >= quota.max_in_flight
            )
            if not needs_wait:
                _take_token(state, quota, key, cost)
                state.in_flight += 1
                return Admission(self, key, "message")

            if quota.max_queued <= 0 or len(state.waiters) >= quota.max_queued:
                _reject(
                    state,
                    "queue_full" if quota.max_queued > 0 else "in_flight_limit",
                    key,
                    quota,
                    limit=quota.max_in_flight,
                )
            if timeout <= 0:
                _reject(
                    state,
                    "in_flight_limit",
                    key,
                    quota,
                    limit=quota.max_in_flight,
                )

            _take_token(state, quota, key, cost)
            waiter = _Waiter()
            state.waiters.append(waiter)
            deadline = now + timeout
            try:
                while not waiter.granted:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        break
                    state.condition.wait(remaining)
            except BaseException:
                if waiter.granted:
                    if state.in_flight > 0:
                        state.in_flight -= 1
                    _grant_next(state)
                else:
                    try:
                        state.waiters.remove(waiter)
                    except ValueError:
                        pass
                    _refund(state, quota, cost)
                raise

            if not waiter.granted:
                try:
                    state.waiters.remove(waiter)
                except ValueError:
                    # A release granted the slot between the timeout and the
                    # removal; accept it rather than leaking the slot.
                    pass
                if not waiter.granted:
                    _refund(state, quota, cost)
                    _reject(
                        state,
                        "queue_timeout",
                        key,
                        quota,
                        limit=quota.max_in_flight,
                    )
            return Admission(self, key, "message")

    # --- internals --------------------------------------------------------

    def _state(self, identity: str) -> _State:
        state = self._states.get(identity)
        if state is None:
            quota = self.quota_for(identity)
            state = _State(
                tokens=float(quota.rate or 0),
                last_refill=self._clock(),
                condition=threading.Condition(self._lock),
            )
            self._states[identity] = state
        return state

    def _release(self, admission: Admission) -> None:
        with self._lock:
            state = self._states.get(admission.identity)
            if state is None:
                return
            if admission.kind == "connection":
                if state.connections > 0:
                    state.connections -= 1
                return
            if state.in_flight > 0:
                state.in_flight -= 1
            _grant_next(state)


def _grant_next(state: _State) -> None:
    if not state.waiters:
        return
    waiter = state.waiters.popleft()
    waiter.granted = True
    state.in_flight += 1
    state.condition.notify_all()


def _identity(identity: object) -> str:
    if isinstance(identity, str) and identity:
        return identity
    return "unknown"


def _refill(state: _State, quota: Quota, now: float) -> None:
    if quota.rate is None:
        return
    if quota.rate == 0:
        state.tokens = 0.0
        state.last_refill = now
        return
    elapsed = max(0.0, now - state.last_refill)
    state.tokens = min(
        float(quota.rate),
        state.tokens + elapsed * quota.rate / quota.window,
    )
    state.last_refill = now


def _take_token(state: _State, quota: Quota, identity: str, cost: int) -> None:
    if quota.rate is None:
        return
    if state.tokens + 1e-12 < cost:
        retry_after_ms = None
        if quota.rate > 0:
            missing = cost - state.tokens
            retry_after_ms = math.ceil(missing * quota.window / quota.rate * 1000)
        _reject(
            state,
            "rate_limited",
            identity,
            quota,
            limit=quota.rate,
            retry_after_ms=retry_after_ms,
        )
    state.tokens -= cost


def _refund(state: _State, quota: Quota, cost: int) -> None:
    if quota.rate is None or quota.rate == 0:
        return
    state.tokens = min(float(quota.rate), state.tokens + cost)


def _reject(
    state: _State,
    reason: str,
    identity: str,
    quota: Quota,
    *,
    limit: int | None,
    retry_after_ms: int | None = None,
) -> None:
    state.rejected += 1
    state.last_reject = reason
    details = {
        "reason": reason,
        "identity": identity,
        "limit": limit,
        "in_flight": state.in_flight,
        "queued": len(state.waiters),
        "connections": state.connections,
        "quota": quota.to_dict(),
    }
    if retry_after_ms is not None:
        details["retry_after_ms"] = retry_after_ms
    raise OsapError("RATE_LIMIT", f"admission denied: {reason}", details=details)


def _snapshot(identity: str, state: _State | None, quota: Quota) -> dict:
    if state is None:
        return {
            "connections": 0,
            "in_flight": 0,
            "queued": 0,
            "tokens": float(quota.rate or 0),
            "rejected": 0,
            "last_reject": None,
            "quota": quota.to_dict(),
        }
    return {
        "connections": state.connections,
        "in_flight": state.in_flight,
        "queued": len(state.waiters),
        "tokens": round(state.tokens, 3),
        "rejected": state.rejected,
        "last_reject": state.last_reject,
        "quota": quota.to_dict(),
    }
