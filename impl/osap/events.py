# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Topic event subscriptions and delivery (standard.md §7.4).

An event topic is an `event://<namespace>/<topic>` URI. Agents subscribe
with a topic filter (exact topic, or a trailing `/*` that matches every
topic under that namespace), publish with an `event` message, and read
what was delivered from their inbox. §7.4 fixes five properties, and each
has a direct counterpart here:

- **Authorization**: subscribing requires the
  `cap://os/events/subscribe` capability. The broker never checks tokens
  itself — that is the PCS/registry's job — so it takes an `authorize`
  callback and fails closed with `POLICY_DENIED` when the callback
  refuses.
- **Delivery is at-most-once**: an event id that already reached a
  subscriber's inbox is never delivered again to that subscriber.
- **Origin and minimal payload**: a published event MUST carry an
  `origin`; sensitive content travels through `refs`, not the payload.
- **User visibility**: subscriptions can be listed per agent.
- **User revocability**: any subscription can be revoked by id,
  idempotently, after which nothing further is delivered.

Delivery happens into per-subscriber inboxes. There is no cross-process
fan-out and no durability: the broker is runtime state, consistent with
"Bus state is not memory" (§3.7).
"""

from __future__ import annotations

import copy
import secrets
from datetime import datetime, timezone

from .errors import OsapError

SUBSCRIBE_CAPABILITY = "cap://os/events/subscribe"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _matches(filter_topic: str, topic: str) -> bool:
    if filter_topic == topic:
        return True
    return filter_topic.endswith("/*") and topic.startswith(filter_topic[:-1])


class EventBroker:
    """Subscriptions, at-most-once delivery, and per-agent inboxes (§7.4)."""

    def __init__(self, *, authorize=None) -> None:
        if authorize is not None and not callable(authorize):
            raise ValueError("authorize must be callable")
        self._authorize = authorize
        self._subscriptions: dict[str, dict] = {}
        self._inboxes: dict[str, list[dict]] = {}
        self._seen: dict[str, set[str]] = {}
        self._events: dict[str, dict] = {}

    # --- subscriptions -----------------------------------------------------

    def subscribe(self, agent: str, *, topics: list[str]) -> dict:
        """Register one subscription for `agent` over `topics` (§7.4)."""

        if not isinstance(agent, str) or not agent:
            raise ValueError("agent must be a non-empty string")
        if not isinstance(topics, list) or not topics:
            raise ValueError("topics must be a non-empty list")
        for topic in topics:
            if not isinstance(topic, str) or not topic.startswith("event://"):
                raise ValueError(
                    f"topic must be an event:// URI: {topic!r}"
                )
        if self._authorize is not None:
            verdict = self._authorize(agent=agent, topics=topics)
            if verdict is not True:
                raise OsapError(
                    "POLICY_DENIED",
                    "subscribing requires the events.subscribe capability",
                    details={
                        "capability": SUBSCRIBE_CAPABILITY,
                        "agent": agent,
                        "topics": topics,
                    },
                )
        subscription_id = f"sub_{secrets.token_hex(8)}"
        record = {
            "subscription_id": subscription_id,
            "agent": agent,
            "topics": list(topics),
            "status": "active",
            "created_at": _now(),
        }
        self._subscriptions[subscription_id] = record
        self._inboxes.setdefault(agent, [])
        self._seen.setdefault(agent, set())
        return dict(record)

    def unsubscribe(self, subscription_id: str) -> bool:
        """Revoke one subscription; revoking twice reports False (§7.4)."""

        record = self._subscriptions.get(subscription_id)
        if record is None or record["status"] != "active":
            return False
        record["status"] = "revoked"
        return True

    def subscriptions(self, agent: str | None = None) -> list[dict]:
        """List subscriptions — the §7.4 user-visibility requirement."""

        records = [
            record
            for record in self._subscriptions.values()
            if record["status"] == "active"
            and (agent is None or record["agent"] == agent)
        ]
        return [dict(record) for record in records]

    # --- delivery ----------------------------------------------------------

    def publish(self, topic: str, *, event: dict, sender: str | None = None) -> dict:
        """Deliver one event to every matching active subscriber (§7.4)."""

        if not isinstance(topic, str) or not topic.startswith("event://"):
            raise ValueError(f"topic must be an event:// URI: {topic!r}")
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        if "origin" not in event:
            raise OsapError(
                "SCHEMA_INVALID",
                "a published event must carry origin (§7.4)",
                details={"topic": topic},
            )
        event_id = event.get("id") or f"evt_{secrets.token_hex(8)}"
        if event_id in self._events:
            # The same event id is the same publication; never deliver twice.
            return {**self._events[event_id], "delivered": []}
        record = {
            "event_id": event_id,
            "topic": topic,
            "payload": copy_of(event),
            "sender": sender,
            "published_at": _now(),
        }
        self._events[event_id] = record
        delivered = []
        for subscription in self._subscriptions.values():
            if subscription["status"] != "active":
                continue
            if not any(_matches(topic_filter, topic) for topic_filter in subscription["topics"]):
                continue
            agent = subscription["agent"]
            seen = self._seen.setdefault(agent, set())
            if event_id in seen:
                continue  # at-most-once per subscriber
            seen.add(event_id)
            self._inboxes.setdefault(agent, []).append(
                {
                    "event_id": event_id,
                    "topic": topic,
                    "origin": event.get("origin"),
                    "payload": copy_of(event.get("payload") or {}),
                    "refs": list(event.get("refs") or []),
                    "sender": sender,
                    "subscription_id": subscription["subscription_id"],
                    "delivered_at": _now(),
                }
            )
            delivered.append(agent)
        return {
            "event_id": event_id,
            "topic": topic,
            "delivered": delivered,
            "published_at": record["published_at"],
        }

    def inbox(self, agent: str) -> list[dict]:
        """Events delivered to one agent, oldest first (§7.4)."""

        if not isinstance(agent, str) or not agent:
            raise ValueError("agent must be a non-empty string")
        return copy.deepcopy(self._inboxes.get(agent) or [])


def copy_of(value):
    """Detach a JSON value."""

    return copy.deepcopy(value)
