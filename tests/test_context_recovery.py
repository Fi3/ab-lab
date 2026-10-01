"""Exercise context recovery with separately scheduled app-server turns."""
from collections import deque
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab.host import Fatal
from lab.provider import Codex, RECOVERY_PROMPT, Usage
from lab.sandbox import CommandSandbox


def item(turn, text="Finished", kind="agentMessage"):
    return {"method": "item/completed", "params": {
        "threadId": "thread", "turnId": turn,
        "item": {"id": turn + "-item", "type": kind, "text": text}}}


def completed(turn, error=None):
    value = {"id": turn, "status": "failed" if error else "completed"}
    if error:
        value["error"] = {"message": "provider failure: contextWindowExceeded",
                          "codexErrorInfo": error}
    return {"method": "turn/completed", "params": {
        "threadId": "thread", "turn": value}}


def price(turn, input_tokens, context=20, window=258400):
    return {"method": "thread/tokenUsage/updated", "params": {
        "threadId": "thread", "turnId": turn,
        "tokenUsage": {"total": {"inputTokens": input_tokens, "outputTokens": 10},
                       "last": {"totalTokens": context},
                       "modelContextWindow": window}}}


def failure(turn="failed", tokens=100, error="contextWindowExceeded"):
    return ("turn/start", turn, [item(turn, "Partial answer before failure"),
                                 completed(turn, error), price(turn, tokens)])


def compaction(tokens=200):
    return ("thread/compact/start", "compact", [
        item("compact", kind="contextCompaction"), completed("compact"),
        price("compact", tokens)])


def success(turn="retry", tokens=300):
    return ("turn/start", turn, [item(turn, "Recovered final answer"),
                                 price(turn, tokens), completed(turn)])


class ContextRecoveryTests(unittest.TestCase):
    def provider(self, stages):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        now = [1000.0]

        def monotonic():
            now[0] += 0.001
            return now[0]

        clock = patch("lab.provider.time.monotonic", side_effect=monotonic)
        clock.start()
        self.addCleanup(clock.stop)
        provider = object.__new__(Codex)
        provider.artifacts = provider.repo = Path(directory.name)
        provider.turns, provider.missing_turns, provider.pending = [], [], deque()
        provider.max_turns, provider.max_raw, provider.deadline = 10, 1000000, 2000.0
        provider.counter, provider.active, provider.usage = 0, None, Usage()
        provider.model, provider.effort = "test", "test"
        provider.sandbox = CommandSandbox(provider.repo, "codex")
        provider.context_usage = {}
        provider.sent, provider.requests = [], []
        provider.send = provider.sent.append
        planned, events = deque(stages), deque()

        def observe(event):
            if event.get("method") == "thread/tokenUsage/updated":
                event["_fresh_usage"] = provider.usage.observe(event["params"])
                provider.remember_context(event["params"])
            return event

        def rpc(method, params):
            provider.requests.append((method, params))
            self.assertTrue(planned, "unexpected extra generation request")
            expected, turn, incoming, *buffered = planned.popleft()
            self.assertEqual(method, expected)
            self.assertFalse(events, "previous turn must drain before another request")
            if buffered:
                # Real rpc() observes and defers notifications received before
                # the response carrying the request's turn ID arrives.
                provider.pending.extend(observe(event) for event in incoming)
            else:
                events.extend(incoming)
            return {"turn": {"id": turn}} if method == "turn/start" else {}

        def incoming(timeout, private_id=None):
            # Advance virtual time so usage drains need no wall-clock sleeps.
            now[0] += max(0.01, timeout)
            return observe(events.popleft()) if events else None

        provider.rpc, provider.incoming = rpc, incoming
        return provider

    def methods(self, provider):
        return [method for method, _ in provider.requests]

    def test_priced_failure_drains_compacts_and_continues_same_thread_once(self):
        provider = self.provider([failure(), compaction(), success()])
        original = "Implement the requested feature without replaying side effects."
        reply = provider.turn("thread", original, "author", writable=True)

        self.assertEqual(reply, "Recovered final answer")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start", "turn/start"])
        self.assertEqual([params["threadId"] for _, params in provider.requests], ["thread"] * 3)
        starts = [params for method, params in provider.requests if method == "turn/start"]
        self.assertEqual([value["input"][0]["text"] for value in starts], [original, RECOVERY_PROMPT])
        self.assertEqual(starts[0]["permissions"], starts[1]["permissions"])
        self.assertIn("do not replay completed commands or accepted edits", RECOVERY_PROMPT)
        self.assertEqual(provider.usage.raw, 310)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual([row["status"] for row in provider.turns], ["failed", "completed", "completed"])
        self.assertEqual(provider.turns[1]["kind"], "compaction")
        self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(),
                         "Partial answer before failure")
        coverage = [json.loads(line) for line in
                    (provider.artifacts / "coverage.jsonl").read_text().splitlines()]
        self.assertEqual(len(coverage), 3)
        self.assertTrue(all(row["usage_observed_after_last_message"] for row in coverage))
        self.assertIsNone(provider.active)

    def test_message_text_alone_does_not_make_unrelated_failure_recoverable(self):
        provider = self.provider([failure(error="other")])
        with self.assertRaisesRegex(Fatal, "agent turn ended unexpectedly"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])

    def test_unpriced_failed_response_blocks_compaction_and_retry(self):
        provider = self.provider([("turn/start", "failed", [
            price("failed", 100), item("failed", "Partial answer before failure"),
            completed("failed", "contextWindowExceeded")])])
        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertEqual(provider.usage.raw, 110)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.missing_turns[0]["turn_id"], "failed")

    def test_second_context_failure_exhausts_recovery_without_third_attempt(self):
        provider = self.provider([failure(), compaction(), failure("retry", 300)])
        with self.assertRaisesRegex(Fatal, "recovery exhausted after one retry"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start", "turn/start"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 310)

    def test_compaction_failure_is_terminal_even_for_context_error(self):
        provider = self.provider([failure(), ("thread/compact/start", "compact", [
            item("compact", kind="contextCompaction"),
            completed("compact", "contextWindowExceeded"), price("compact", 200)])])
        with self.assertRaisesRegex(Fatal, "agent turn ended unexpectedly"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertFalse(provider.turns[1]["recovery_eligible"])

    def test_compaction_consumes_original_turn_and_token_budgets(self):
        for limit, expected in (("turns", "workflow turn limit"),
                                ("tokens", "workflow wall-time/observed-token limit")):
            with self.subTest(limit=limit):
                provider = self.provider([failure(), compaction()])
                if limit == "turns":
                    provider.max_turns = 2
                else:
                    provider.max_raw = 200
                with self.assertRaisesRegex(Fatal, expected):
                    provider.turn("thread", "original", "author")
                self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start"])
                self.assertEqual(len(provider.turns), 2)
                self.assertEqual(provider.usage.raw, 210)
                self.assertTrue(provider.report()["measurement_complete"])

    def test_proactive_compaction_accounts_for_upcoming_utf8_prompt(self):
        provider = self.provider([compaction(), success("initial")])
        provider.context_usage["thread"] = {"tokens": 580, "window": 1000}
        prompt = "é" * 10  # 20 UTF-8 bytes reach the 600-token threshold.
        provider.turn("thread", prompt, "author")
        self.assertEqual(self.methods(provider), ["thread/compact/start", "turn/start"])
        self.assertEqual(provider.requests[1][1]["input"][0]["text"], prompt)
        self.assertEqual(provider.usage.raw, 310)

    def test_large_cumulative_cost_does_not_trigger_proactive_compaction(self):
        provider = self.provider([success("initial", 100000)])
        provider.usage.observe_tokens("thread", 90000, 10)
        provider.context_usage["thread"] = {"tokens": 20, "window": 1000}
        provider.turn("thread", "small next request", "author")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertEqual(provider.usage.raw, 100010)

    def test_unpriced_compaction_blocks_further_generation(self):
        provider = self.provider([failure(), ("thread/compact/start", "compact", [
            item("compact", kind="contextCompaction"), completed("compact")])])
        with self.assertRaisesRegex(Fatal, "incomplete token measurement after compaction"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.missing_turns[0]["turn_id"], "compact")
        self.assertEqual(provider.usage.raw, 110)

    def test_terminal_notification_without_compaction_item_cannot_authorize_retry(self):
        provider = self.provider([failure(), ("thread/compact/start", "compact", [
            {"method": "turn/started", "params": {"threadId": "thread", "turn": {"id": "compact"}}},
            completed("compact"), price("compact", 200)])])
        with self.assertRaisesRegex(Fatal, "without a contextCompaction item"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start"])
        self.assertTrue(provider.report()["measurement_complete"])

    def test_usage_buffered_after_completion_before_rpc_response_is_drained(self):
        foreign = item("foreign", " " * 9000)
        foreign["params"]["threadId"] = "foreign-thread"
        provider = self.provider([("turn/start", "initial", [
            item("initial"), completed("initial"), foreign, price("initial", 100)], True)])
        self.assertEqual(provider.turn("thread", "original", "author"), "Finished")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 110)
        self.assertEqual(list(provider.pending), [foreign])
        self.assertFalse(provider.sent)

    def test_compaction_can_finish_before_its_rpc_response(self):
        provider = self.provider([failure(), (*compaction(), True), success()])
        reply = provider.turn("thread", "original", "author")
        self.assertEqual(reply, "Recovered final answer")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 310)
        self.assertEqual(provider.turns[1]["turn_id"], "compact")
        self.assertFalse(provider.pending)

    def test_late_runaway_output_after_terminal_rejects_unreliable_response(self):
        for form in ("completed", "delta"):
            with self.subTest(form=form):
                garbage = (item("initial", " " * 9000) if form == "completed" else
                           {"method": "item/agentMessage/delta", "params": {
                               "threadId": "thread", "turnId": "initial",
                               "itemId": "late", "delta": " " * 9000}})
                provider = self.provider([("turn/start", "initial", [
                    item("initial", "Partial answer before failure"),
                    price("initial", 100), completed("initial"), garbage,
                    price("initial", 150)]), compaction(), success()])
                reply = provider.turn("thread", "original", "author")
                self.assertEqual(reply, "Recovered final answer")
                self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start", "turn/start"])
                self.assertEqual(provider.turns[0]["error"], "trailing_whitespace")
                self.assertTrue(provider.report()["measurement_complete"])
                self.assertFalse(provider.sent, "the first turn was already terminal")

    def test_unpriced_late_runaway_output_stops_without_generation(self):
        provider = self.provider([("turn/start", "initial", [
            item("initial", "Partial answer before failure"), price("initial", 100),
            completed("initial"), item("initial", " " * 9000)])])
        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 110)

    def test_streaming_runaway_waits_for_price_without_waiting_for_message_completion(self):
        stopped = completed("initial")
        stopped["params"]["turn"]["status"] = "interrupted"
        delta = {"method": "item/agentMessage/delta", "params": {
            "threadId": "thread", "turnId": "initial", "itemId": "stream",
            "delta": "\ufffd\n" * 128}}
        provider = self.provider([("turn/start", "initial", [delta, price("initial", 100), stopped]),
                                  compaction(), success()])
        reply = provider.turn("thread", "original", "author")
        self.assertEqual(reply, "Recovered final answer")
        self.assertEqual(provider.sent, [{"id": 1, "method": "turn/interrupt",
            "params": {"threadId": "thread", "turnId": "initial"}}])
        self.assertEqual(provider.turns[0]["interrupt_reason"], "runaway_output")
        self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(), "")
        self.assertTrue(provider.report()["measurement_complete"])

    def test_long_stream_has_a_time_limit_even_when_text_is_not_malformed(self):
        stopped = completed("initial")
        stopped["params"]["turn"]["status"] = "interrupted"
        delta = {"method": "item/agentMessage/delta", "params": {
            "threadId": "thread", "turnId": "initial", "itemId": "stream", "delta": "ordinary text"}}
        provider = self.provider([("turn/start", "initial", [delta, price("initial", 80),
                                  stopped, price("initial", 100)]), compaction(), success()])
        with patch("lab.provider.MESSAGE_SECONDS", 0.05):
            provider.turn("thread", "original", "author")
        self.assertEqual(provider.turns[0]["error"], "agent message exceeded streaming time limit")
        self.assertEqual(provider.sent[0]["method"], "turn/interrupt")
        self.assertTrue(provider.report()["measurement_complete"])

    def test_late_usage_over_budget_prevents_successful_response_return(self):
        provider = self.provider([("turn/start", "initial", [item("initial"),
                                  price("initial", 20), completed("initial"), price("initial", 100)])])
        provider.max_raw = 100
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit"):
            provider.turn("thread", "original", "author")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertEqual(provider.usage.raw, 110)
        self.assertTrue(provider.report()["measurement_complete"])



if __name__ == "__main__":
    unittest.main()
