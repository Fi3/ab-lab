from collections import deque
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.provider import Codex, Usage
from lab.host import Fatal
from lab.loops import WorkLimitReached
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

    def test_natural_completion_returns_last_assistant_message(self):
        p = self.provider([message("Progress update"), message("Completed implementation."), price(), completed()])
        self.assertEqual(p.turn("t", "request", "author"), "Completed implementation.")
        self.assertFalse(p.sent)
        self.assertEqual(p.usage.raw, 110)

    def test_foreign_and_partial_messages_do_not_replace_owned_final_answer(self):
        p = self.provider([message("Foreign or partial explanation", thread="foreign"),
                          {"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "u", "delta": "Foreign or partial explanation"}},
                          message("Final answer"), price(), completed()])
        self.assertEqual(p.turn("t", "request", "author"), "Final answer")
        self.assertFalse(p.sent)

    def test_unpriced_tail_remains_missing(self):
        p = self.provider([price(), message("Finished"), completed()])
        with self.assertRaisesRegex(Fatal, "incomplete native token measurement"):
            p.turn("t", "request", "author")
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
        p = self.provider([message("Implementation in progress."), price(40),
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

    def test_review_limit_retains_reply_as_evidence_without_returning_a_verdict(self):
        for status, threshold in (("completed", 100), ("interrupted", 50)):
            with self.subTest(status=status):
                p = self.provider([message("NO_FINDINGS"), price(40), completed(status), price(100)])
                p.work_limits = [{"reason": "review_token_limit", "metric": "observed_raw_tokens",
                                  "start": 0, "limit": threshold}]
                with self.assertRaises(WorkLimitReached) as stopped:
                    p.turn("t", "review", "review-1")
                self.assertFalse(hasattr(stopped.exception, "completed_reply"))
                self.assertEqual((p.artifacts / "turn-0001/reply.txt").read_text(), "NO_FINDINGS")
                self.assertEqual(p.usage.raw, 110)
                self.assertTrue(p.report()["measurement_complete"])
                self.assertEqual(p.turns[0]["work_limit"]["kind"], "budget_exhausted")

    def test_time_and_token_limits_interrupt_and_retain_priced_partial_turn(self):
        for limit in ("time", "tokens"):
            with self.subTest(limit=limit):
                directive = "Partial author response"
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

                # Partial output is retained as evidence; complete accounting does
                # not turn a cancelled response into a successful return.
                with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
                    p.turn("t", "request", "author")

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
