"""Replay the completed-but-unpriced compaction from the retained p012-2 run.

The fixture contains actual ordered transport events and numeric native records,
not a mock compaction that invents an increasing app-server counter. Its provenance
lists the source files/lines; benchmark prompts and generated code are excluded.
The resumed response is synthetic because the failed run never resumed.
"""
import copy
import json
from pathlib import Path
import unittest

import test_context_recovery as recovery

from lab.host import Fatal
from lab.native_usage import NativeUsage


FIXTURE = Path(__file__).with_name("fixtures") / "compaction-usage.json"


class CompactionTraceTests(unittest.TestCase):
    def replay_provider(self, *, continue_after=False, omit_numeric=False,
                        automatic=False, price_output=True, late_price=False,
                        omit_continuation_native=False,
                        delay_continuation_native_polls=0):
        fixture = json.loads(FIXTURE.read_text())
        transport = fixture["transport"]
        start = next(i for i, row in enumerate(transport)
                     if row["event"].get("method") == "thread/compact/start")
        events = [row["event"] for row in transport[start + 1:]
                  if row["direction"] == "receive"]
        stages = [("turn/start" if automatic else "thread/compact/start", "compact", events)]

        # Only the resumed response is synthetic. Keep the native/app-server
        # counters separate: the latter omitted previous compaction costs too.
        continuation = copy.deepcopy(fixture["native"][0])
        continuation.pop("source_line")
        continuation["ordinal"] = 766
        continuation["timestamp"] = "2026-09-26T18:41:37.000Z"
        payload = continuation["payload"]
        response_turn = "compact" if automatic else "continuation"
        payload.update(turn_id=response_turn, root_turn_id=response_turn,
                       response_id="response-continuation")
        payload["usage"] = payload["turn_token_usage"] = {
            "input_tokens": 31, "output_tokens": 7, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "reasoning_output_tokens": 0,
            "total_tokens": 38}
        payload["thread_token_usage"]["input_tokens"] += 31
        payload["thread_token_usage"]["output_tokens"] += 7
        payload["thread_token_usage"]["total_tokens"] += 38
        if continue_after or automatic:
            price = copy.deepcopy(transport[0]["event"])
            price["params"]["turnId"] = response_turn
            counts = price["params"]["tokenUsage"]["total"]
            counts["inputTokens"] += 31
            counts["outputTokens"] += 7
            counts["totalTokens"] += 38
            price["params"]["tokenUsage"]["last"] = {
                "totalTokens": 38, "inputTokens": 31, "outputTokens": 7}
            if automatic:
                terminal = events.pop()
                events.append(recovery.item("compact", "@standalone done"))
                if price_output and not late_price:
                    events.append(price)
                events.append(terminal)
                if price_output and late_price:
                    events.append(price)
            else:
                stages.append(("turn/start", "continuation", [
                    recovery.item("continuation", "@standalone done"),
                    price, recovery.completed("continuation")]))

        provider = recovery.ContextRecoveryTests.provider(self, stages)
        provider.max_raw = 15_000_000
        path = provider.artifacts / "native-session.jsonl"
        with path.open("w") as handle:
            handle.write(json.dumps({"type": "session_meta", "payload": {
                "id": "thread", "cwd": str(provider.repo)}}) + "\n")
            baseline = copy.deepcopy(fixture["native_before"])
            baseline.pop("source_line")
            handle.write(json.dumps(baseline) + "\n")

        provider.native_usage = {"thread": NativeUsage(path, "thread", provider.repo)}
        provider.usage.observe(transport[0]["event"]["params"])
        provider.refresh_native_usage(force=True)
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_before"])

        original_incoming = provider.incoming
        written = set()
        delayed = []
        provider.native_delay_polls = 0

        def incoming(timeout, private_id=None):
            event = original_incoming(timeout, private_id)
            if event is None and delayed:
                provider.native_delay_polls += 1
                if provider.native_delay_polls >= delay_continuation_native_polls:
                    with path.open("a") as handle:
                        for record in delayed:
                            handle.write(json.dumps(record) + "\n")
                    delayed.clear()
            if not event or event.get("method") != "thread/tokenUsage/updated":
                return event
            is_compaction = event["params"]["tokenUsage"]["last"]["inputTokens"] == 0
            kind = "compaction" if is_compaction else "continuation"
            if kind in written:
                return event
            written.add(kind)
            if omit_continuation_native and not is_compaction:
                return event
            if delay_continuation_native_polls and not is_compaction:
                delayed.append(continuation)
                return event
            records = fixture["native"] if is_compaction else [continuation]
            with path.open("a") as handle:
                for source in records:
                    record = copy.deepcopy(source)
                    record.pop("source_line", None)
                    if omit_numeric and is_compaction:
                        if record["type"] == "token_usage_record":
                            continue
                        record["payload"].pop("latest_token_usage_record")
                    handle.write(json.dumps(record) + "\n")
            return event

        provider.incoming = incoming
        return provider, fixture

    def test_real_completed_compaction_charges_native_usage_and_continues(self):
        provider, fixture = self.replay_provider(continue_after=True)
        before = provider.usage.raw

        provider.compact("thread", "trace")

        self.assertEqual(provider.usage.raw - before,
                         fixture["expected"]["compaction_raw_tokens"])
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertTrue(provider.turns[0]["usage_observed_after_last_message"])
        self.assertTrue(provider.report()["measurement_complete"])

        # The native usage appears twice: its own record and the compacted
        # checkpoint's latest_token_usage_record. Re-reading also costs zero.
        for _ in range(2):
            provider.refresh_native_usage(force=True)
            self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])

        self.assertEqual(provider.turn("thread", "Continue the pending task.", "trace"),
                         "@standalone done")
        self.assertEqual([method for method, _ in provider.requests],
                         ["thread/compact/start", "turn/start"])
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"] + 38)
        self.assertTrue(provider.report()["measurement_complete"])

    def test_real_compaction_cost_reaching_budget_blocks_continuation(self):
        provider, fixture = self.replay_provider(continue_after=True)
        provider.max_raw = fixture["expected"]["native_raw_after"]

        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit"):
            provider.compact("thread", "trace")

        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
        self.assertEqual([method for method, _ in provider.requests],
                         ["thread/compact/start"])

    def test_compaction_counts_toward_feature_budget_without_continuation(self):
        from lab.loops import WorkLimitReached
        provider, fixture = self.replay_provider(continue_after=True)
        provider.work_limits = [{"reason": "feature_token_limit", "metric": "observed_raw_tokens",
                                 "start": 0, "limit": fixture["expected"]["native_raw_after"]}]
        with self.assertRaises(WorkLimitReached):
            provider.compact("thread", "trace")
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual([method for method, _ in provider.requests], ["thread/compact/start"])

    def test_context_reduction_without_numeric_evidence_still_blocks(self):
        provider, _ = self.replay_provider(omit_numeric=True)

        with self.assertRaisesRegex(Fatal, "incomplete.*token measurement"):
            provider.compact("thread", "trace")

        self.assertEqual(provider.context_usage["thread"]["tokens"], 72185)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual([method for method, _ in provider.requests],
                         ["thread/compact/start"])

    def test_automatic_compaction_receipt_cannot_price_later_assistant_output(self):
        provider, fixture = self.replay_provider(automatic=True, price_output=False)

        with self.assertRaisesRegex(Fatal, "incomplete token measurement after compaction"):
            provider.turn("thread", "Continue.", "automatic")

        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
        self.assertTrue(provider.turns[0]["compaction_usage"]["covered"])
        self.assertFalse(provider.turns[0]["usage_observed_after_last_message"])
        self.assertFalse(provider.report()["measurement_complete"])

    def test_automatic_compaction_and_late_response_usage_are_both_counted(self):
        provider, fixture = self.replay_provider(automatic=True, late_price=True)

        self.assertEqual(provider.turn("thread", "Continue.", "automatic"),
                         "@standalone done")

        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"] + 38)
        self.assertEqual(provider.turns[0]["compaction_usage"]["response_ids"],
                         ["response-compact"])
        self.assertTrue(provider.report()["measurement_complete"])

    def test_stale_native_counters_cannot_hide_priced_continuation_cost(self):
        provider, fixture = self.replay_provider(continue_after=True,
                                                omit_continuation_native=True)
        provider.compact("thread", "trace")

        # App-server counters advance for an ordinary response while the
        # session-file receipt is absent. Its smaller cumulative counter must
        # not silently hide those 38 tokens beneath the native cumulative total.
        with self.assertRaisesRegex(Fatal, "incomplete.*token measurement"):
            provider.turn("thread", "Continue.", "trace")
        self.assertFalse(provider.report()["measurement_complete"])

    def test_delayed_native_response_receipt_is_drained_before_continuation_returns(self):
        provider, fixture = self.replay_provider(continue_after=True,
                                                delay_continuation_native_polls=25)
        provider.compact("thread", "trace")

        self.assertEqual(provider.turn("thread", "Continue.", "trace"),
                         "@standalone done")

        self.assertEqual(provider.native_delay_polls, 25)
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"] + 38)
        self.assertTrue(provider.report()["measurement_complete"])

    def test_newly_flushed_native_cost_is_checked_before_any_generation_request(self):
        for action in ("turn", "compact"):
            with self.subTest(action=action):
                provider, fixture = self.replay_provider()
                provider.max_raw = fixture["expected"]["native_raw_after"]
                # replay_provider just refreshed, so normal budget polling is
                # throttled. Simulate a receipt being flushed immediately after.
                with provider.native_usage["thread"].path.open("a") as handle:
                    for source in fixture["native"]:
                        record = copy.deepcopy(source)
                        record.pop("source_line")
                        handle.write(json.dumps(record) + "\n")
                self.assertEqual(provider.observed_raw(),
                                 fixture["expected"]["native_raw_before"],
                                 "ordinary refresh must still be throttled")

                with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit"):
                    if action == "turn":
                        provider.turn("thread", "Continue.", "budget-race")
                    else:
                        provider.compact("thread", "budget-race")

                self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
                self.assertFalse(provider.requests, "budget exhaustion must prevent the RPC")
                self.assertFalse(provider.turns, "budget exhaustion must precede turn creation")

    def test_owned_thread_without_rollout_path_is_rejected(self):
        provider = recovery.ContextRecoveryTests.provider(self, [])
        provider.native_usage = {}
        for thread in ({"id": "thread"}, {"id": "thread", "path": ""},
                       {"id": "thread", "path": None}, {"id": "thread", "path": 42}):
            with self.subTest(thread=thread):
                with self.assertRaisesRegex(Fatal, "owned rollout path"):
                    provider.register_native_thread(thread)
        self.assertFalse(provider.native_usage)
        self.assertFalse(provider.requests)


class InlineReviewCompactionTests(unittest.TestCase):
    """Replay the real reviewer whose inline compaction crossed its review cap."""

    def replay(self, *, receipt_only=False, omit_numeric=False,
               foreign_turn=False, unpriced_tail=None, omit_completion=False):
        fixture = json.loads(FIXTURE.with_name("inline-compaction-review.json").read_text())
        events = [copy.deepcopy(row["event"]) for row in fixture["transport"]
                  if row["direction"] == "receive"]
        native = copy.deepcopy(fixture["native"])
        baseline = fixture["native_before"]
        transport_before = fixture["transport_before"]["event"]
        if receipt_only:
            baseline = native[-3]
            transport_before = [event for event in events
                                if event["method"] == "thread/tokenUsage/updated"][-2]
            start = next(i for i, event in enumerate(events)
                         if event.get("params", {}).get("item", {}).get("type") == "contextCompaction")
            events = events[start:]
            native = native[-2:]
        if omit_numeric:
            native = [record for record in native if record["type"] == "compacted"
                      or record["payload"]["response_id"] != native[-2]["payload"]["response_id"]]
            native[-1]["payload"].pop("latest_token_usage_record")
            # No priced compaction means no token-cap interrupt. Complete the
            # turn so the missing receipt, rather than a foreign interrupt, fails.
            events[-1]["params"]["turn"]["status"] = "completed"
        if foreign_turn:
            for record in native[-2:]:
                payload = record["payload"]
                if record["type"] == "compacted":
                    payload = payload["latest_token_usage_record"]
                payload["turn_id"] = payload["root_turn_id"] = "foreign-turn"
        if omit_completion:
            events = [event for event in events if not (
                event["method"] == "item/completed" and
                event["params"].get("item", {}).get("type") == "contextCompaction")]
        if unpriced_tail == "completed":
            events.insert(-1, recovery.item("review", "Unpriced ordinary output."))
        elif unpriced_tail == "delta":
            events.insert(-1, {"method": "item/agentMessage/delta", "params": {
                "threadId": "thread", "turnId": "review", "itemId": "unpriced-tail",
                "delta": "Unpriced ordinary output."}})

        provider = recovery.ContextRecoveryTests.provider(self, [("turn/start", "review", events)])
        provider.max_raw = 15_000_000
        path = provider.artifacts / "native-session.jsonl"
        with path.open("w") as handle:
            handle.write(json.dumps({"type": "session_meta", "payload": {
                "id": "thread", "cwd": str(provider.repo)}}) + "\n")
            handle.write(json.dumps(baseline) + "\n")
        provider.native_usage = {"thread": NativeUsage(path, "thread", provider.repo)}
        provider.usage.observe(transport_before["params"])
        provider.refresh_native_usage(force=True)
        provider.work_limits = [{"reason": "review_token_threshold", "action": "conclude_review",
                                 "metric": "observed_raw_tokens", "start": provider.usage.raw,
                                 "limit": 100_000 if receipt_only else 500_000}]
        original_incoming = provider.incoming
        pending = iter(native)

        def incoming(timeout, private_id=None):
            event = original_incoming(timeout, private_id)
            if event and event.get("method") == "thread/tokenUsage/updated":
                records = list(pending) if event["params"]["tokenUsage"]["last"]["inputTokens"] == 0 else [next(pending)]
                with path.open("a") as handle:
                    for record in records:
                        handle.write(json.dumps(record) + "\n")
                # The real rollout flushed its receipt before the unchanged
                # transport counter; that receipt triggered the cap interrupt.
                provider.refresh_native_usage(force=True)
            return event

        provider.incoming = incoming
        return provider, fixture

    def test_live_review_cap_after_inline_compaction_keeps_complete_accounting(self):
        from lab.loops import ReviewConclusionRequested
        provider, fixture = self.replay()

        with self.assertRaises(ReviewConclusionRequested) as stopped:
            provider.turn("thread", "Review the current checkpoint.", "review")

        self.assertEqual(stopped.exception.signal["observed"], fixture["expected"]["review_raw_tokens"])
        self.assertEqual(provider.usage.raw, fixture["expected"]["native_raw_after"])
        self.assertEqual(provider.usage.native_totals["thread"], (1383604, 37380, 1143680))
        self.assertEqual(provider.usage.transport_totals["thread"], (1255998, 35507, 1079808))
        row = provider.turns[0]
        self.assertEqual(row["status"], "interrupted")
        self.assertEqual(row["interrupt_reason"], "budget")
        self.assertTrue(row["compaction_usage"]["covered"])
        self.assertTrue(row["usage_observed_after_last_message"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertFalse(provider.missing_turns)
        self.assertEqual([event["method"] for event in provider.sent], ["turn/interrupt"])

    def test_receipt_only_inline_compaction_is_priced_before_review_cap(self):
        from lab.loops import ReviewConclusionRequested
        provider, fixture = self.replay(receipt_only=True)
        with self.assertRaises(ReviewConclusionRequested) as stopped:
            provider.turn("thread", "Review.", "review")
        self.assertEqual(stopped.exception.signal["observed"], fixture["expected"]["compaction_raw_tokens"])
        self.assertTrue(provider.turns[0]["usage_observed_after_last_message"])
        self.assertTrue(provider.report()["measurement_complete"])

    def test_review_cap_compaction_does_not_price_ordinary_tail(self):
        from lab.loops import ReviewConclusionRequested
        for form in ("completed", "delta"):
            with self.subTest(form=form):
                provider, _ = self.replay(unpriced_tail=form)
                with self.assertRaises(ReviewConclusionRequested):
                    provider.turn("thread", "Review.", "review")
                self.assertTrue(provider.turns[0]["compaction_usage"]["covered"])
                self.assertFalse(provider.turns[0]["usage_observed_after_last_message"])
                self.assertFalse(provider.report()["measurement_complete"])

    def test_inline_compaction_requires_its_own_numeric_receipt(self):
        for variant in ({"omit_numeric": True}, {"foreign_turn": True}):
            with self.subTest(variant=variant):
                provider, _ = self.replay(**variant)
                with self.assertRaises(Fatal):
                    provider.turn("thread", "Review.", "review")
                self.assertFalse(provider.turns[0]["compaction_usage"]["covered"])
                self.assertFalse(provider.report()["measurement_complete"])

    def test_interrupted_inflight_compaction_is_incomplete(self):
        from lab.loops import ReviewConclusionRequested
        provider, _ = self.replay(omit_completion=True)
        with self.assertRaises(ReviewConclusionRequested):
            provider.turn("thread", "Review.", "review")
        self.assertFalse(provider.turns[0]["usage_observed_after_last_message"])
        self.assertFalse(provider.report()["measurement_complete"])


if __name__ == "__main__":
    unittest.main()
