# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for event subscriptions and delivery (standard.md §7.4)."""

import unittest

from osap import EventBroker
from osap.errors import OsapError

TOPIC = "event://app.com.example.calendar/event_changed"
OTHER = "event://os/user/activity"


class SubscribeTests(unittest.TestCase):
    def setUp(self):
        self.broker = EventBroker()

    def test_a_subscription_is_created_and_listed(self):
        record = self.broker.subscribe(
            "agent://com.example.notes/assistant#7f3a", topics=[TOPIC]
        )
        self.assertTrue(record["subscription_id"].startswith("sub_"))
        self.assertEqual(record["status"], "active")
        self.assertEqual(
            [item["subscription_id"] for item in self.broker.subscriptions()],
            [record["subscription_id"]],
        )
        self.assertEqual(
            [item["agent"] for item in self.broker.subscriptions()],
            ["agent://com.example.notes/assistant#7f3a"],
        )

    def test_topics_must_be_event_uris(self):
        for topics in ([], ["calendar"], [42], "event://x"):
            with self.assertRaises(ValueError):
                self.broker.subscribe("agent://com.example.notes/assistant#7f3a", topics=topics)

    def test_the_authorizer_can_deny_a_subscription(self):
        broker = EventBroker(authorize=lambda agent, topics: False)
        with self.assertRaises(OsapError) as caught:
            broker.subscribe("agent://com.example.notes/assistant#7f3a", topics=[TOPIC])
        self.assertEqual(caught.exception.code, "POLICY_DENIED")
        self.assertEqual(caught.exception.details["capability"], "cap://os/events/subscribe")
        self.assertEqual(broker.subscriptions(), [])

    def test_unsubscribe_revokes_and_is_idempotent(self):
        record = self.broker.subscribe("agent://com.example.notes/assistant#7f3a", topics=[TOPIC])
        self.assertTrue(self.broker.unsubscribe(record["subscription_id"]))
        self.assertFalse(self.broker.unsubscribe(record["subscription_id"]))
        self.assertEqual(self.broker.subscriptions(), [])
        self.assertEqual(self.broker.inbox("agent://com.example.notes/assistant#7f3a"), [])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.broker = EventBroker()
        self.sub = self.broker.subscribe(
            "agent://com.example.notes/assistant#7f3a", topics=[TOPIC]
        )
        self.other = self.broker.subscribe(
            "agent://com.example.calendar/agent#9c", topics=[OTHER]
        )

    def event(self, event_id="evt_1", topic=TOPIC, origin="app://com.example.calendar"):
        return {"id": event_id, "origin": origin, "payload": {"changed": True}}

    def test_publish_delivers_to_matching_subscribers_only(self):
        report = self.broker.publish(TOPIC, event=self.event(), sender=TOPIC and "app://com.example.calendar")
        self.assertEqual(report["delivered"], ["agent://com.example.notes/assistant#7f3a"])
        inbox = self.broker.inbox("agent://com.example.notes/assistant#7f3a")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["topic"], TOPIC)
        self.assertEqual(inbox[0]["origin"], "app://com.example.calendar")
        self.assertEqual(self.broker.inbox("agent://com.example.calendar/agent#9c"), [])

    def test_at_most_once_per_subscriber(self):
        self.broker.publish(TOPIC, event=self.event())
        report = self.broker.publish(TOPIC, event=self.event())  # same id again
        self.assertEqual(report["delivered"], [])
        self.assertEqual(len(self.broker.inbox("agent://com.example.notes/assistant#7f3a")), 1)

    def test_wildcard_filters_match_subtopics(self):
        self.broker.unsubscribe(self.sub["subscription_id"])
        self.broker.subscribe(
            "agent://com.example.notes/assistant#7f3a", topics=["event://app.com.example.calendar/*"]
        )
        self.broker.publish(OTHER, event=self.event("evt_other", topic=OTHER))
        self.assertEqual(self.broker.inbox("agent://com.example.notes/assistant#7f3a"), [])
        self.broker.publish(TOPIC, event=self.event("evt_changed"))
        self.assertEqual(len(self.broker.inbox("agent://com.example.notes/assistant#7f3a")), 1)

    def test_revoked_subscriptions_receive_nothing(self):
        self.broker.unsubscribe(self.sub["subscription_id"])
        report = self.broker.publish(TOPIC, event=self.event())
        self.assertEqual(report["delivered"], [])

    def test_an_event_without_origin_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.broker.publish(TOPIC, event={"id": "evt_bad", "payload": {}})
        self.assertEqual(caught.exception.code, "SCHEMA_INVALID")

    def test_inbox_is_chronological_and_detached(self):
        self.broker.publish(TOPIC, event=self.event("evt_a"))
        self.broker.publish(TOPIC, event=self.event("evt_b"))
        inbox = self.broker.inbox("agent://com.example.notes/assistant#7f3a")
        self.assertEqual([item["event_id"] for item in inbox], ["evt_a", "evt_b"])
        inbox[0]["payload"]["changed"] = "tampered"
        self.assertEqual(self.broker.inbox("agent://com.example.notes/assistant#7f3a")[0]["payload"]["changed"], True)


if __name__ == "__main__":
    unittest.main()
