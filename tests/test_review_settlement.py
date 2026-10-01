"""Reproduce checkpoint 5's timed-out, unpriced first review-conclusion response.

The retained turn 0137 had owned reasoning item notifications but no visible
agent message. At cancellation its tokenUsage repeated turn 0136's totals.
Only item types/ownership and numeric receipts are needed to replay that failure;
no private reasoning content or benchmark solution text belongs in this fixture.
"""
from collections import deque
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab.host import Fatal
from lab.loops import FeatureProgress, POLICY_VERSION, WorkLimitReached, loop_policy
from lab.native_usage import NativeUsage
from lab.provider import Codex, Usage
from lab.sandbox import CommandSandbox


THREAD = "review-thread"
TURN = "review"
# Exact prior cumulative counters replayed when real turn 0137 was cancelled.
BEFORE = (529817, 4429, 465408)
AFTER = (603817, 8429, 525408)


def started(kind="reasoning", *, turn=TURN, thread=THREAD, item_id="active-response"):
    return {"method": "item/started", "params": {"threadId": thread, "turnId": turn,
            "item": {"id": item_id, "type": kind}}}


def price(values=AFTER, *, turn=TURN, thread=THREAD):
    return {"method": "thread/tokenUsage/updated", "params": {
        "threadId": thread, "turnId": turn,
        "tokenUsage": {"total": dict(zip(("inputTokens", "outputTokens", "cachedInputTokens"), values)),
                       "last": {"totalTokens": 78000}, "modelContextWindow": 258400}}}


def completed(status="completed"):
    return {"method": "turn/completed", "params": {
        "threadId": THREAD, "turn": {"id": TURN, "status": status, "error": None}}}


def message(text="NO_FINDINGS"):
    return {"method": "item/completed", "params": {"threadId": THREAD, "turnId": TURN,
            "item": {"id": "verdict", "type": "agentMessage", "phase": "final_answer", "text": text}}}


class ReviewSettlementTests(unittest.TestCase):
    def provider(self, scheduled, *, review_seconds=90):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = 1000.0
        clock = patch("lab.provider.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        provider = object.__new__(Codex)
        provider.artifacts = provider.repo = Path(directory.name)
        provider.turns, provider.missing_turns, provider.pending = [], [], deque()
        provider.max_turns, provider.max_raw, provider.deadline = 10, 15000000, 11000.0
        provider.counter, provider.active, provider.usage = 0, None, Usage()
        provider.model, provider.effort = "gpt-5.6-sol", "xhigh"
        provider.context_usage = {}
        provider.sandbox = CommandSandbox(provider.repo, "codex")
        provider.sent, provider.requests = [], []
        provider.usage.observe_tokens(THREAD, *BEFORE)
        path = provider.artifacts / "owned-rollout.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": THREAD, "cwd": str(provider.repo)}}) + "\n")
        provider.native_usage = {THREAD: NativeUsage(path, THREAD, provider.repo)}
        self.receipt_values, self.receipt_count = (0, 0, 0), 0

        def receipt(total, turn=TURN):
            self.receipt_count += 1
            def usage(values):
                return {"input_tokens": values[0], "output_tokens": values[1],
                        "cached_input_tokens": values[2], "total_tokens": sum(values[:2])}
            delta = tuple(a-b for a,b in zip(total,self.receipt_values))
            self.receipt_values = total
            value = {"type": "token_usage_record", "payload": {
                "thread_id": THREAD, "session_id": THREAD, "turn_id": turn,
                "response_id": "response-"+str(self.receipt_count),
                "usage": usage(delta), "thread_token_usage": usage(total)}}
            with path.open("a") as stream:
                stream.write(json.dumps(value)+"\n")
        self.append_receipt = receipt
        receipt(BEFORE, "previous-review")
        provider.refresh_native_usage(force=True)
        self.events = deque((1000.0+at, copy.deepcopy(event), native)
                            for at,event,native in scheduled)
        progress = FeatureProgress({"id": "checkpoint_5"}, loop_policy({
            "max_feature_raw": 3_000_000, "max_review_raw": 500_000,
            "max_review_seconds": review_seconds}), 0)
        provider.work_limits = progress.limits(sum(BEFORE[:2]), reviewing=True)
        self.start = self.now

        def rpc(method, params):
            provider.requests.append((method, params))
            self.assertEqual(method, "turn/start")
            self.assertEqual(len(provider.requests), 1, "a timed-out review must not generate again")
            return {"turn": {"id": TURN}}

        def send(event):
            provider.sent.append((self.now-self.start, event))
            self.assertEqual(event["method"], "turn/interrupt")
            # Cancellation discards this response's future scheduled completion.
            # The real provider repeated its previous cumulative counters.
            previous = provider.usage.transport_totals[THREAD]
            self.events = deque([(self.now+0.001, price(previous), None),
                                 (self.now+0.002, completed("interrupted"), None)])

        def incoming(timeout, private_id=None):
            end = self.now + max(0.001, timeout)
            if not self.events or self.events[0][0] > end:
                self.now = end
                return None
            at, event, native = self.events.popleft()
            self.now = max(self.now, at)
            if native is not None:
                if isinstance(native, dict):
                    receipt(native["compaction"])
                    with path.open("a") as stream:
                        stream.write(json.dumps({"type": "compacted", "payload": {
                            "compaction_response_id": "response-"+str(self.receipt_count)}})+"\n")
                else:
                    receipt(native)
            if event and event.get("method") == "thread/tokenUsage/updated":
                event["_fresh_usage"] = provider.usage.observe(event["params"])
                provider.remember_context(event["params"])
            return event
        provider.rpc, provider.send, provider.incoming = rpc, send, incoming
        return provider

    def stop(self, provider, expected=WorkLimitReached):
        with self.assertRaises(expected) as stopped:
            provider.turn(THREAD, "Review the assigned requirements.",
                          "checkpoint_5-review-1", writable=True)
        self.assertEqual(len(provider.requests), 1)
        self.assertFalse(provider.turns[0].get("recovery_eligible", False))
        self.assertFalse((provider.artifacts/"turn-0001/host-operation.txt").exists())
        return stopped.exception

    def assert_first_expiry(self, provider, limit=90, outcome="priced_boundary"):
        row = provider.turns[0]
        self.assertGreaterEqual(row["work_limit"]["observed"], limit)
        self.assertLess(row["work_limit"]["observed"], limit+0.2)
        settlement = row["work_limit_settlement"]
        self.assertEqual(settlement["trigger"], row["work_limit"])
        self.assertEqual(settlement["settle_seconds"], 600)
        self.assertEqual(settlement["outcome"], outcome)

    def test_policy_versions_elapsed_review_settlement_explicitly(self):
        policy = loop_policy()
        self.assertEqual(POLICY_VERSION, "bounded-review-loops-v6")
        self.assertEqual(policy["max_review_settle_seconds"], 600)
        progress = FeatureProgress({"id": "checkpoint_5"}, policy, 0)
        self.assertEqual(progress.limits(0, reviewing=True), [])
        progress = FeatureProgress({"id": "checkpoint_5"}, loop_policy({
            "max_feature_raw": 3_000_000, "max_review_raw": 500_000,
            "max_review_seconds": 300}), 0)
        limits = progress.limits(0, reviewing=True)
        self.assertEqual(limits[-1]["settle_seconds"], 600)
        self.assertNotIn("settle_seconds", limits[0])
        self.assertNotIn("settle_seconds", limits[-2])
        self.assertFalse(any("action" in item for item in limits))

    def test_default_review_finishes_beyond_previous_time_and_token_caps(self):
        total = tuple(a+b for a, b in zip(BEFORE, (600000, 5000, 550000)))
        provider = self.provider([(1, started(), None), (399.9, message(), None),
                                  (400, price(total), total), (400.01, completed(), None)])
        progress = FeatureProgress({"id": "checkpoint_5"}, loop_policy(), 0)
        provider.work_limits = progress.limits(sum(BEFORE[:2]), reviewing=True)

        reply = provider.turn(THREAD, "Review the assigned requirements.",
                              "checkpoint_5-review-1", writable=True)

        self.assertEqual(reply, "NO_FINDINGS")
        self.assertEqual(provider.usage.raw - sum(BEFORE[:2]), 605000)
        self.assertGreaterEqual(self.now - self.start, 400)
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertFalse(provider.sent)

    def test_silent_first_response_waits_for_owned_receipt_after_ninety_seconds(self):
        provider = self.provider([(1, started(), None), (130, price(), AFTER)])
        error = self.stop(provider)
        self.assertEqual(error.signal["reason"], "review_time_limit")
        self.assertEqual(len(provider.sent), 1)
        self.assertGreaterEqual(provider.sent[0][0], 130)
        self.assertLess(provider.sent[0][0], 131)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, sum(AFTER[:2]))
        self.assertEqual((provider.artifacts/"turn-0001/reply.txt").read_text(), "")
        self.assertEqual(json.loads((provider.artifacts/"turn-0001/messages.json").read_text()), [])
        self.assert_first_expiry(provider)

    def test_natural_priced_verdict_is_retained_but_not_delivered_or_approved(self):
        provider = self.provider([(1, started(), None), (129.9, message(), None),
                                  (130, completed(), None), (130.01, price(), AFTER)])
        error = self.stop(provider)
        self.assertFalse(hasattr(error, "completed_reply"))
        self.assertFalse(provider.sent)
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual((provider.artifacts/"turn-0001/reply.txt").read_text(), "NO_FINDINGS")
        self.assert_first_expiry(provider, outcome="turn_completed")

    def test_previous_response_receipt_is_invalidated_by_next_owned_reasoning(self):
        earlier = (539817, 4439, 470408)
        provider = self.provider([(1, started(item_id="response-a"), None),
                                  (10, price(earlier), earlier),
                                  (80, started(item_id="response-b"), None),
                                  (95, price(earlier), None), (130, price(), AFTER)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 130)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assert_first_expiry(provider)

    def test_agent_message_start_without_any_delta_also_invalidates_prior_receipt(self):
        earlier = (539817, 4439, 470408)
        provider = self.provider([(1, started(), None), (10, price(earlier), earlier),
                                  (80, started("agentMessage"), None), (130, price(), AFTER)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 130)
        self.assertTrue(provider.report()["measurement_complete"])

    def test_foreign_turn_counter_and_repeated_prior_counter_do_not_settle(self):
        foreign = (529818, 4429, 465408)
        provider = self.provider([(1, started(), None), (95, price(BEFORE), None),
                                  (100, price(foreign, turn="other-turn"), None),
                                  (130, price(), AFTER)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 130)
        self.assertTrue(provider.report()["measurement_complete"])

    def test_transport_receipt_waits_for_owned_native_cost_to_be_flushed(self):
        provider = self.provider([(1, started(), None), (130, price(), None),
                                  (135, None, AFTER)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 135)
        self.assertLess(provider.sent[0][0], 136)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assert_first_expiry(provider)

    def test_missing_first_response_receipt_stops_after_bounded_settlement(self):
        provider = self.provider([(1, started(), None), (95, price(BEFORE), None)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 690)
        self.assertLess(provider.sent[0][0], 691)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, sum(BEFORE[:2]))
        self.assertEqual(len(provider.missing_turns), 1)
        self.assert_first_expiry(provider, outcome="timeout")

    def test_global_deadline_preempts_review_receipt_settlement(self):
        provider = self.provider([(1, started(), None)])
        provider.deadline = self.start+100
        error = self.stop(provider, Fatal)
        self.assertNotIsInstance(error, WorkLimitReached)
        self.assertIn("workflow wall-time/observed-token", str(error))
        self.assertGreaterEqual(provider.sent[0][0], 100)
        self.assertLess(provider.sent[0][0], 100.2)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.turns[0]["work_limit_settlement"]["outcome"], "hard_limit")

    def test_global_feature_and_review_token_caps_preempt_elapsed_settlement(self):
        for kind in ("global", "feature", "review"):
            with self.subTest(kind=kind):
                provider = self.provider([(1, started(), None), (100, price(), AFTER)])
                if kind == "global":
                    provider.max_raw = sum(BEFORE[:2])+1
                elif kind == "feature":
                    provider.work_limits[0]["limit"] = sum(BEFORE[:2])+1
                else:
                    provider.work_limits[-2]["limit"] = 1
                error = self.stop(provider, Fatal)
                if kind == "global":
                    self.assertNotIsInstance(error, WorkLimitReached)
                else:
                    self.assertEqual(error.signal["reason"],
                                     "feature_token_limit" if kind=="feature" else "review_token_limit")
                self.assertGreaterEqual(provider.sent[0][0], 100)
                self.assertLess(provider.sent[0][0], 100.2)
                self.assertTrue(provider.report()["measurement_complete"])
                self.assertEqual(provider.turns[0]["work_limit_settlement"]["outcome"], "hard_limit")

    def test_foreign_activity_does_not_invalidate_an_owned_priced_boundary(self):
        for field in ("thread", "turn"):
            with self.subTest(field=field):
                event = started(**{field: "unrelated"})
                provider = self.provider([(1, started(), None), (10, price(), AFTER),
                                          (80, event, None)])
                self.stop(provider)
                self.assertGreaterEqual(provider.sent[0][0], 90)
                self.assertLess(provider.sent[0][0], 90.2)
                self.assertTrue(provider.report()["measurement_complete"])
                self.assert_first_expiry(provider)

    def test_terminal_provider_error_preempts_settlement_without_retry(self):
        error = {"method": "error", "params": {"threadId": THREAD, "turnId": TURN,
                 "willRetry": False, "error": {"message": "request rejected by provider",
                                                "codexErrorInfo": "other"}}}
        provider = self.provider([(1, started(), None), (100, error, None)])
        stopped = self.stop(provider, Fatal)
        self.assertNotIsInstance(stopped, WorkLimitReached)
        self.assertIn("agent turn ended unexpectedly", str(stopped))
        self.assertGreaterEqual(provider.sent[0][0], 100)
        self.assertLess(provider.sent[0][0], 100.2)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.turns[0]["work_limit_settlement"]["outcome"], "provider_error")

    def test_buffered_new_reasoning_is_processed_before_using_previous_receipt(self):
        earlier = (539817, 4439, 470408)
        provider = self.provider([(1, started(item_id="response-a"), None),
                                  (90.1, price(earlier), earlier),
                                  (90.1005, started(item_id="response-b"), None),
                                  (130, price(), AFTER)])
        incoming = provider.incoming
        def flushed(timeout, private_id=None):
            event = incoming(timeout, private_id)
            if event and event.get("method") == "thread/tokenUsage/updated":
                provider.refresh_native_usage(force=True)
            return event
        provider.incoming = flushed
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0], 130)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assert_first_expiry(provider)

    def test_compaction_receipt_cannot_cover_subsequent_silent_reasoning(self):
        compacted = tuple(a+b for a,b in zip(BEFORE,(100,20,0)))
        total_after = tuple(a+b for a,b in zip(AFTER,(100,20,0)))
        finished = {"method": "item/completed", "params": {"threadId": THREAD, "turnId": TURN,
                    "item": {"id": "automatic-compact", "type": "contextCompaction"}}}
        provider = self.provider([(1, started("contextCompaction",item_id="automatic-compact"),None),
                                  (2, finished, {"compaction":compacted}),
                                  (80, started(),None), (130,price(),total_after)])
        self.stop(provider)
        self.assertGreaterEqual(provider.sent[0][0],130)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw,sum(total_after[:2]))
        self.assertEqual(provider.turns[0]["compaction_usage"]["response_ids"],["response-2"])
        self.assert_first_expiry(provider)

    def test_hard_streaming_ceiling_during_review_settlement_quarantines_late_verdict(self):
        delta = {"method":"item/agentMessage/delta", "params": {"threadId":THREAD,
                 "turnId":TURN,"itemId":"verdict","delta":"NO_FINDINGS"}}
        provider = self.provider([(1,delta,None)],review_seconds=300)
        send = provider.send
        def natural_race(event):
            send(event)
            self.events = deque([(self.now+0.001,message(),None),
                                 (self.now+0.002,completed(),None),
                                 (self.now+0.003,price(),AFTER)])
        provider.send = natural_race
        error = self.stop(provider,WorkLimitReached)
        self.assertGreaterEqual(provider.sent[0][0],601)
        self.assertLess(provider.sent[0][0],602)
        self.assertEqual(provider.turns[0]["status"],"completed")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertFalse(hasattr(error, "completed_reply"),
                         "a hard stop cannot become an approved review verdict")
        self.assert_first_expiry(provider,limit=300,outcome="hard_limit")

    def test_exploration_time_threshold_uses_same_bounded_receipt_boundary(self):
        provider = self.provider([(1, started(), None), (330, price(), AFTER)], review_seconds=300)
        error = self.stop(provider, WorkLimitReached)
        self.assertEqual(error.signal["reason"], "review_time_limit")
        self.assertFalse(hasattr(error, "completed_reply"))
        self.assertGreaterEqual(provider.sent[0][0], 330)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assert_first_expiry(provider, limit=300)


if __name__ == "__main__":
    unittest.main()
