from collections import deque
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.provider import Codex, Usage
from lab.host import Fatal
from lab.loops import ReviewConclusionRequested, WorkLimitReached
from lab.sandbox import CommandSandbox


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
        p.sandbox = CommandSandbox(p.repo, 'codex')
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

    def test_feature_budget_interrupts_a_native_turn_and_retains_late_usage(self):
        p = self.provider([message("@standalone run -- never_execute"), price(40),
                           completed("interrupted"), price(100)])
        p.work_limits = [{"reason": "feature_token_limit", "metric": "observed_raw_tokens", "start": 0, "limit": 50}]
        with self.assertRaises(WorkLimitReached) as stopped:
            p.turn("t", "request", "author", writable=True)
        self.assertEqual(stopped.exception.signal["reason"], "feature_token_limit")
        self.assertEqual([v["method"] for v in p.sent], ["turn/interrupt"])
        self.assertEqual(p.usage.raw, 110)
        self.assertTrue(p.report()["measurement_complete"])
        self.assertEqual(p.turns[0]["work_limit"]["observed"], 110)
        self.assertFalse(p.turns[0]["recovery_eligible"])

    def test_review_time_limit_interrupts_without_masking_global_limit(self):
        p = self.provider([message("FINDINGS\n- [P2] defect"), price(40), completed("interrupted"), price(100)])
        p.work_limits = [{"reason": "review_time_limit", "metric": "seconds", "start": time.monotonic(), "limit": 300}]
        incoming = p.incoming

        def expire(timeout, private_id=None):
            event = incoming(timeout, private_id)
            if event and event.get("method") == "thread/tokenUsage/updated":
                p.work_limits[0]["start"] = time.monotonic()-301
            return event

        p.incoming = expire
        with self.assertRaisesRegex(WorkLimitReached, "review_time_limit"):
            p.turn("t", "review", "review-1")
        self.assertTrue(p.report()["measurement_complete"])
        p.max_raw = 100
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token") as stopped:
            p.check_limits()
        self.assertNotIsInstance(stopped.exception, WorkLimitReached)

    def test_review_threshold_preserves_completed_verdict_but_not_interrupted_text(self):
        for status, threshold in (("completed", 100), ("interrupted", 50)):
            with self.subTest(status=status):
                p = self.provider([message("NO_FINDINGS"), price(40), completed(status), price(100)])
                p.work_limits = [{"reason": "review_token_threshold", "metric": "observed_raw_tokens",
                                  "start": 0, "limit": threshold, "action": "conclude_review"}]
                with self.assertRaises(ReviewConclusionRequested) as stopped:
                    p.turn("t", "review", "review-1")
                self.assertEqual(stopped.exception.completed_reply, "NO_FINDINGS" if status == "completed" else None)
                self.assertEqual(p.usage.raw, 110)
                self.assertTrue(p.report()["measurement_complete"])
                self.assertEqual(p.turns[0]["work_limit"]["kind"], "review_wrapup")

    def test_time_and_token_limits_interrupt_and_retain_priced_partial_turn(self):
        for limit in ("time", "tokens"):
            with self.subTest(limit=limit):
                directive = "@standalone run -- should_not_run"
                p = self.provider([message(directive), price(40),
                                   completed("interrupted"), price(100)])
                if limit == "tokens":
                    p.max_raw = 50
                else:
                    incoming = p.incoming

                    def expire_after_usage(timeout, private_id=None):
                        event = incoming(timeout, private_id)
                        if event and event.get("method") == "thread/tokenUsage/updated":
                            p.deadline = time.monotonic()-1
                        return event

                    p.incoming = expire_after_usage

                # A directive delivered before exhaustion must not reach the
                # host after the budget cancellation, even with complete usage.
                with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
                    p.turn("t", "request", "author", host_request=True)

                self.assertEqual(p.sent, [{"id": 1, "method": "turn/interrupt",
                    "params": {"threadId": "t", "turnId": "u"}}])
                self.assertEqual(p.usage.raw, 110)
                self.assertTrue(p.report()["measurement_complete"])
                self.assertEqual(p.missing_turns, [])
                self.assertIsNone(p.active)
                folder = p.artifacts / "turn-0001"
                row = json.loads((folder / "result.json").read_text())
                self.assertEqual(row["status"], "interrupted")
                self.assertEqual(row["interrupt_reason"], "budget")
                self.assertEqual(row["error"], "workflow wall-time/observed-token limit reached")
                self.assertTrue(row["usage_observed_after_last_message"])
                self.assertEqual((folder / "reply.txt").read_text(), directive)
                coverage = json.loads((p.artifacts / "coverage.jsonl").read_text())
                self.assertEqual(coverage["status"], "interrupted")
                self.assertTrue(coverage["usage_observed_after_last_message"])


if __name__ == "__main__":
    unittest.main()
