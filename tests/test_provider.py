from collections import deque
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.provider import Codex, Usage


def message(text, thread="t", turn="u"):
    return {"method": "item/completed", "params": {"threadId": thread, "turnId": turn,
            "item": {"type": "agentMessage", "text": text}}}


def price(raw=100):
    return {"method": "thread/tokenUsage/updated", "params": {"threadId": "t", "turnId": "u", "tokenUsage": {
        "total": {"inputTokens": raw, "outputTokens": 10}, "last": {"inputTokens": raw, "outputTokens": 10}}}}


def completed(status="completed"):
    return {"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "u", "status": status}}}


class StreamTests(unittest.TestCase):
    def provider(self, events):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = object.__new__(Codex)
        p.artifacts = Path(tmp.name)
        p.turns, p.missing_turns, p.pending = [], [], deque()
        p.max_turns, p.max_raw, p.deadline = 10, 100000, time.monotonic()+30
        p.counter, p.active, p.usage = 0, None, Usage()
        p.model, p.effort, p.repo = "test", "test", p.artifacts
        p.sent, p.remaining = [], deque(events)
        p.send = lambda value: p.sent.append(value)
        p.rpc = lambda method, params: {"turn": {"id": "u"}}

        def incoming(timeout, private_id=None):
            if not p.remaining:
                time.sleep(min(timeout, 0.01))
                return None
            event = p.remaining.popleft()
            if event.get("method") == "thread/tokenUsage/updated":
                event["_fresh_usage"] = p.usage.observe(event["params"])
            return event
        p.incoming = incoming
        return p

    def test_interrupt_runs_after_exact_owned_message_and_counts_late_usage(self):
        p = self.provider([message("@standalone run -- true"),
                          price(40),
                          {"method": "item/started", "params": {"threadId": "t", "turnId": "u", "item": {"type": "reasoning"}}},
                          completed("interrupted"), price()])
        text = p.turn("t", "request", "author", interrupt=True, host_request=True)
        self.assertEqual(text, "@standalone run -- true")
        self.assertEqual([v["method"] for v in p.sent], ["turn/interrupt"])
        self.assertEqual(p.usage.raw, 110)
        self.assertEqual(p.missing_turns, [])

    def test_disabled_waits_for_natural_finish_keeps_first_request(self):
        p = self.provider([message("@standalone run -- true"), message("Late explanation"), price(), completed()])
        self.assertEqual(p.turn("t", "request", "author", host_request=True), "@standalone run -- true")
        self.assertFalse(p.sent)
        self.assertEqual(p.usage.raw, 110)

    def test_foreign_and_partial_messages_never_authorize_operations(self):
        p = self.provider([message("@standalone run -- false", thread="foreign"),
                          {"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "u", "delta": "@standalone run -- false"}},
                          message("Not a directive"), price(), completed()])
        self.assertEqual(p.turn("t", "request", "author", interrupt=True, host_request=True), "Not a directive")
        self.assertFalse(p.sent)

    def test_unpriced_tail_remains_missing(self):
        p = self.provider([price(), message("@standalone done"), completed()])
        p.turn("t", "request", "author", host_request=True)
        self.assertEqual(len(p.missing_turns), 1)
        self.assertFalse(p.report()["measurement_complete"])

    def test_operator_cancel_drains_usage_instead_of_dropping_the_tail(self):
        p = self.provider([price(), completed("interrupted")])
        original = p.incoming
        first = True

        def cancelled(timeout, private_id=None):
            nonlocal first
            if first:
                first = False
                raise KeyboardInterrupt()
            return original(timeout, private_id)
        p.incoming = cancelled
        with self.assertRaises(KeyboardInterrupt):
            p.turn("t", "request", "author")
        self.assertEqual(p.usage.raw, 110)
        self.assertEqual([v["method"] for v in p.sent], ["turn/interrupt"])


if __name__ == "__main__":
    unittest.main()
