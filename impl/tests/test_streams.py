# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for receiver-side stream state (standard.md §7.5)."""

import unittest

from osap import StreamRegistry
from osap.errors import OsapError


class StreamRegistryTests(unittest.TestCase):
    def setUp(self):
        self.streams = StreamRegistry()
        self.streams.open("stream_01", schema="osap.report/v1", total_estimate=3)

    def test_open_declares_the_stream(self):
        view = self.streams.view("stream_01")
        self.assertEqual(view["schema"], "osap.report/v1")
        self.assertEqual(view["total_estimate"], 3)
        self.assertEqual(view["status"], "open")
        self.assertEqual(view["chunks"], [])
        self.assertEqual(view["missing"], [])

    def test_a_second_open_is_rejected(self):
        with self.assertRaises(OsapError) as caught:
            self.streams.open("stream_01")
        self.assertEqual(caught.exception.code, "DUPLICATE")

    def test_chunks_arrive_out_of_order_and_are_sorted(self):
        for seq in (3, 1, 2):
            self.streams.chunk("stream_01", seq=seq, data={"part": seq})
        view = self.streams.view("stream_01")
        self.assertEqual([chunk["seq"] for chunk in view["chunks"]], [1, 2, 3])
        self.assertEqual(view["missing"], [])

    def test_missing_sequences_are_reported(self):
        self.streams.chunk("stream_01", seq=1, data={"part": 1})
        self.streams.chunk("stream_01", seq=3, data={"part": 3})
        view = self.streams.view("stream_01")
        self.assertEqual(view["missing"], [2])

    def test_a_redelivered_seq_never_overwrites(self):
        self.streams.chunk("stream_01", seq=2, data={"part": "first"})
        self.streams.chunk("stream_01", seq=2, data={"part": "retransmitted"})
        view = self.streams.view("stream_01")
        self.assertEqual(view["chunks"][0]["data"], {"part": "first"})
        self.assertEqual(view["received"], 1)

    def test_a_chunk_carries_exactly_one_of_data_or_ref(self):
        with self.assertRaises(ValueError):
            self.streams.chunk("stream_01", seq=1)
        with self.assertRaises(ValueError):
            self.streams.chunk("stream_01", seq=1, data={"a": 1}, ref="obj://x")
        self.streams.chunk("stream_01", seq=1, ref="obj://sha256:9f2c7b1a")
        self.assertEqual(self.streams.view("stream_01")["chunks"][0]["ref"], "obj://sha256:9f2c7b1a")

    def test_close_freezes_and_rejects_further_chunks(self):
        self.streams.chunk("stream_01", seq=1, data={"part": 1})
        view = self.streams.close("stream_01", status="complete", summary="done")
        self.assertEqual(view["status"], "complete")
        self.assertEqual(view["summary"], "done")
        with self.assertRaises(OsapError) as caught:
            self.streams.chunk("stream_01", seq=2, data={"part": 2})
        self.assertEqual(caught.exception.code, "POLICY_DENIED")

    def test_cancelling_frees_the_chunks_but_completing_keeps_them(self):
        self.streams.chunk("stream_01", seq=1, data={"part": 1})
        self.streams.close("stream_01", status="cancelled")
        self.assertEqual(self.streams.view("stream_01")["chunks"], [])
        # A fresh stream that completes keeps its chunks — that is the result.
        self.streams.open("stream_02", schema="osap.report/v1")
        self.streams.chunk("stream_02", seq=1, data={"part": 2})
        self.streams.close("stream_02", status="complete")
        self.assertEqual(
            [chunk["seq"] for chunk in self.streams.view("stream_02")["chunks"]], [1]
        )

    def test_close_cannot_be_repeated(self):
        self.streams.close("stream_01", status="cancelled")
        with self.assertRaises(OsapError):
            self.streams.close("stream_01", status="complete")

    def test_an_unknown_stream_is_not_found(self):
        with self.assertRaises(OsapError) as caught:
            self.streams.chunk("stream_missing", seq=1, data={})
        self.assertEqual(caught.exception.code, "ROUTING_NOT_FOUND")

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            self.streams.open("")
        with self.assertRaises(ValueError):
            self.streams.open("stream_x", total_estimate=-1)
        with self.assertRaises(ValueError):
            self.streams.chunk("stream_01", seq=0, data={})
        with self.assertRaises(ValueError):
            self.streams.close("stream_01", status="maybe")

    def test_views_are_detached(self):
        self.streams.chunk("stream_01", seq=1, data={"part": 1})
        view = self.streams.view("stream_01")
        view["chunks"][0]["data"] = "tampered"
        self.assertEqual(
            self.streams.view("stream_01")["chunks"][0]["data"], {"part": 1}
        )


if __name__ == "__main__":
    unittest.main()
