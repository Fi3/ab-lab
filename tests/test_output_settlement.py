"""Runaway responses must reach a priced boundary before recovery cancels them.

The retained GPT-5.6 failure began a host command in streamed chunks, then emitted
newline chunks until the whitespace guard cancelled an unfinished response. Its
only subsequent usage notification repeated the previous response's counters.
These tests preserve that event shape while varying the terminal usage evidence.
"""
import json
import time
import unittest
from unittest.mock import patch

from lab.host import Fatal
from lab.loops import ReviewConclusionRequested, WorkLimitReached
from lab.native_usage import NativeUsage
import test_context_recovery as recovery


def delta(text, turn="initial", item_id="command"):
    return {"method": "item/agentMessage/delta", "params": {
        "threadId": "thread", "turnId": turn, "itemId": item_id, "delta": text}}


def runaway(text="\n" * 8192):
    # The real failed stream started '@', 'stand', 'alone', ' run', ' --'.
    return [delta(chunk) for chunk in ("@", "stand", "alone", " run", " --", " true", text)]


class OutputSettlementTests(unittest.TestCase):
    provider = recovery.ContextRecoveryTests.provider
    methods = recovery.ContextRecoveryTests.methods

    def acknowledge_interrupt(self, provider):
        """The server closes only after the host actually sends interruption."""
        original = provider.send
        observations = []

        def send(event):
            observations.append({"time": time.monotonic(), "raw": provider.usage.raw})
            original(event)
            terminal = recovery.completed(event["params"]["turnId"])
            terminal["params"]["turn"]["status"] = "interrupted"
            provider.pending.append(terminal)

        provider.send = send
        return observations

    def test_soft_stream_guard_waits_for_numeric_usage_then_recovers_same_thread(self):
        for text, reason in (("\n" * 8192, "trailing_whitespace"),
                             ("\ufffd\n" * 128, "replacement_character_flood")):
            with self.subTest(reason=reason):
                rejected = runaway(text)
                provider = self.provider([
                    ("turn/start", "initial", [*rejected, recovery.price("initial", 100)]),
                    recovery.compaction(), recovery.success()])
                sent = self.acknowledge_interrupt(provider)

                reply = provider.turn("thread", "Implement the next step.", "author",
                                      host_request=True, writable=True)

                self.assertEqual(reply, "@standalone run -- fresh-proposal")
                self.assertEqual([row["raw"] for row in sent], [110])
                self.assertEqual(self.methods(provider),
                                 ["turn/start", "thread/compact/start", "turn/start"])
                self.assertEqual(provider.turns[0]["error"], reason)
                self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "priced_boundary")
                self.assertTrue(provider.report()["measurement_complete"])
                self.assertEqual(provider.usage.raw, 310)
                journal = provider.artifacts / "turn-0001/agent-message-deltas.jsonl"
                saved = [json.loads(line) for line in journal.read_text().splitlines()]
                self.assertEqual(saved, [{"item_id": "command", "delta": e["params"]["delta"]}
                                         for e in rejected])
                self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(), "")

    def test_natural_completion_after_violation_needs_no_interrupt(self):
        provider = self.provider([
            ("turn/start", "initial", [*runaway(), recovery.completed("initial"),
                                       recovery.price("initial", 100)]),
            recovery.compaction(), recovery.success()])

        self.assertEqual(provider.turn("thread", "Continue.", "reviewer"),
                         "@standalone run -- fresh-proposal")

        self.assertFalse(provider.sent)
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertEqual(provider.turns[0]["error"], "trailing_whitespace")
        self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "turn_completed")
        self.assertTrue(provider.report()["measurement_complete"])

    def test_genuine_usage_after_120_seconds_still_recovers_without_early_cancellation(self):
        provider = self.provider([("turn/start", "initial", runaway()),
                                  recovery.compaction(), recovery.success()])
        sent = self.acknowledge_interrupt(provider)
        original = provider.incoming
        detected, price_delivered = [], []

        def incoming(timeout, private_id=None):
            event = original(timeout, private_id)
            if event and event.get("params", {}).get("delta") == "\n" * 8192:
                detected.append(time.monotonic())
            if (event is None and detected and not price_delivered
                    and time.monotonic() - detected[0] >= 130):
                event = recovery.price("initial", 100)
                event["_fresh_usage"] = provider.usage.observe(event["params"])
                provider.remember_context(event["params"])
                price_delivered.append(time.monotonic())
            return event

        provider.incoming = incoming
        self.assertEqual(provider.turn("thread", "Continue.", "author", host_request=True),
                         "@standalone run -- fresh-proposal")

        self.assertEqual([row["raw"] for row in sent], [110])
        self.assertGreaterEqual(sent[0]["time"], price_delivered[0])
        self.assertGreaterEqual(sent[0]["time"] - detected[0], 130)
        self.assertLess(sent[0]["time"] - detected[0], 600)
        self.assertEqual(provider.turns[0]["output_guard"]["settle_seconds"], 600)
        self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "priced_boundary")
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start", "turn/start"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 310)

    def test_completed_only_violation_without_usage_is_bounded_from_guard_detection(self):
        rejected = recovery.item("initial", "NO_FINDINGS" + " " * 8192)
        provider = self.provider([("turn/start", "initial", [rejected, recovery.price("initial", 100)])])
        provider.usage.observe_tokens("thread", 100, 10)
        sent = self.acknowledge_interrupt(provider)
        original = provider.incoming
        detected = []

        def incoming(timeout, private_id=None):
            event = original(timeout, private_id)
            if event is rejected:
                detected.append(time.monotonic())
            return event

        provider.incoming = incoming
        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
            provider.turn("thread", "Review the implementation.", "reviewer")

        self.assertEqual(len(sent), 1)
        self.assertGreaterEqual(sent[0]["time"] - detected[0], 600)
        self.assertLess(sent[0]["time"] - detected[0], 601)
        self.assertEqual(provider.turns[0]["output_guard"]["settle_seconds"], 600)
        self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "timeout")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])

    def test_natural_terminal_without_fresh_usage_still_blocks_recovery(self):
        provider = self.provider([("turn/start", "initial", [*runaway(),
            recovery.completed("initial"), recovery.price("initial", 100)])])
        provider.usage.observe_tokens("thread", 100, 10)

        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
            provider.turn("thread", "Continue.", "author")

        self.assertFalse(provider.sent)
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 110)

    def test_rejected_completed_verdict_is_not_attached_to_review_conclusion_request(self):
        rejected = "NO_FINDINGS" + " " * 8192
        provider = self.provider([("turn/start", "initial", [recovery.item("initial", rejected),
            recovery.completed("initial"), recovery.price("initial", 100)])])
        provider.work_limits = [{"reason": "review_token_threshold", "action": "conclude_review",
                                "metric": "observed_raw_tokens", "start": 0, "limit": 100}]

        with self.assertRaises(ReviewConclusionRequested) as stopped:
            provider.turn("thread", "Review the implementation.", "reviewer")

        self.assertIsNone(stopped.exception.completed_reply,
                          "a verdict rejected by the output guard cannot bypass conclusion")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertEqual(provider.turns[0]["output_guard"]["reason"], "trailing_whitespace")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.sent)
        self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(), rejected)

    def test_streaming_timeout_verdict_is_not_attached_to_review_conclusion_request(self):
        verdict = recovery.item("initial", "NO_FINDINGS")
        verdict["params"]["item"]["id"] = "command"
        provider = self.provider([("turn/start", "initial", [delta("NO_FINDINGS"),
            recovery.price("initial", 100), verdict, recovery.completed("initial"),
            recovery.price("initial", 200)])])
        provider.usage.observe_tokens("thread", 100, 10)
        provider.work_limits = [{"reason": "review_token_threshold", "action": "conclude_review",
                                "metric": "observed_raw_tokens", "start": 110, "limit": 100}]

        with patch("lab.provider.MESSAGE_SECONDS", 0.05):
            with self.assertRaises(ReviewConclusionRequested) as stopped:
                provider.turn("thread", "Review the implementation.", "reviewer")

        self.assertIsNone(stopped.exception.completed_reply,
                          "a time-rejected response remains rejected when its terminal price arrives")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertEqual(provider.turns[0]["interrupt_reason"], "runaway_output")
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertEqual([message["method"] for message in provider.sent], ["turn/interrupt"])
        self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(), "NO_FINDINGS")

    def test_late_rejected_output_preserves_known_context_error_recoverability(self):
        for form in ("delta", "completed"):
            with self.subTest(form=form):
                malformed = (delta("\n" * 8192) if form == "delta" else
                             recovery.item("initial", "\n" * 8192))
                provider = self.provider([("turn/start", "initial", [
                    recovery.completed("initial", "contextWindowExceeded"), malformed,
                    recovery.price("initial", 100)]), recovery.compaction(), recovery.success()])

                self.assertEqual(provider.turn("thread", "Continue.", "author", host_request=True),
                                 "@standalone run -- fresh-proposal")

                self.assertTrue(provider.turns[0]["recovery_eligible"])
                self.assertEqual(provider.turns[0]["output_guard"]["reason"], "trailing_whitespace")
                self.assertEqual(self.methods(provider),
                                 ["turn/start", "thread/compact/start", "turn/start"])
                self.assertTrue(provider.report()["measurement_complete"])
                self.assertEqual(provider.usage.raw, 310)
                self.assertFalse(provider.sent)

    def test_noncovering_counter_waits_until_hard_stream_deadline_then_fails_without_retry(self):
        for kind in ("repeated", "empty", "different_turn", "different_thread"):
            with self.subTest(kind=kind):
                notification = recovery.price("initial", 100 if kind == "repeated" else 200)
                if kind == "empty":
                    notification["params"]["tokenUsage"]["total"] = {}
                elif kind == "different_turn":
                    notification["params"]["turnId"] = "previous"
                elif kind == "different_thread":
                    notification["params"]["threadId"] = "other-thread"
                provider = self.provider([
                    ("turn/start", "initial", [*runaway(), notification])])
                provider.usage.observe_tokens("thread", 100, 10)
                sent = self.acknowledge_interrupt(provider)
                original = provider.incoming
                started = []

                def incoming(timeout, private_id=None):
                    event = original(timeout, private_id)
                    if event and event.get("params", {}).get("delta") == "@":
                        started.append(time.monotonic())
                    return event

                provider.incoming = incoming
                with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
                    provider.turn("thread", "Continue.", "author", host_request=True)

                self.assertEqual(len(sent), 1)
                self.assertGreaterEqual(sent[0]["time"] - started[0], 600)
                self.assertLess(sent[0]["time"] - started[0], 601)
                self.assertEqual(self.methods(provider), ["turn/start"])
                self.assertEqual(provider.turns[0]["output_guard"]["settle_seconds"], 600)
                self.assertEqual(provider.turns[0]["interrupt_reason"], "runaway_output")
                self.assertFalse(provider.report()["measurement_complete"])
                self.assertEqual(provider.missing_turns[0]["turn_id"], "initial")

    def test_later_stream_chunk_invalidates_earlier_settlement_usage(self):
        for fresh_tail in (False, True):
            with self.subTest(fresh_tail=fresh_tail):
                events = [*runaway(), recovery.completed("initial"),
                          recovery.price("initial", 100), delta("\n" * 16)]
                if fresh_tail:
                    events.append(recovery.price("initial", 150))
                stages = [("turn/start", "initial", events)]
                if fresh_tail:
                    stages += [recovery.compaction(), recovery.success()]
                provider = self.provider(stages)

                if fresh_tail:
                    self.assertEqual(provider.turn("thread", "Continue.", "author"),
                                     "@standalone run -- fresh-proposal")
                    self.assertTrue(provider.report()["measurement_complete"])
                else:
                    with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
                        provider.turn("thread", "Continue.", "author")
                    self.assertEqual(self.methods(provider), ["turn/start"])
                    self.assertFalse(provider.report()["measurement_complete"])
                self.assertFalse(provider.sent)

    def test_deadline_and_work_limits_preempt_soft_settlement(self):
        for kind in ("global", "feature", "review"):
            with self.subTest(kind=kind):
                provider = self.provider([("turn/start", "initial", runaway())])
                sent = self.acknowledge_interrupt(provider)
                original = provider.incoming
                detected = []

                def incoming(timeout, private_id=None):
                    event = original(timeout, private_id)
                    if event and event.get("params", {}).get("delta") == "\n" * 8192:
                        now = time.monotonic()
                        detected.append(now)
                        if kind == "global":
                            provider.deadline = now + 0.3
                        else:
                            provider.work_limits = [{"reason": kind + "_time_limit",
                                "metric": "seconds", "start": now, "limit": 0.3,
                                **({"action": "conclude_review"} if kind == "review" else {})}]
                    return event

                provider.incoming = incoming
                expected = (Fatal if kind == "global" else WorkLimitReached
                            if kind == "feature" else ReviewConclusionRequested)
                with patch("lab.provider.OUTPUT_SETTLE_SECONDS", 600.0, create=True):
                    with self.assertRaises(expected):
                        provider.turn("thread", "Continue.", "author")

                self.assertEqual(len(sent), 1)
                self.assertLess(sent[0]["time"] - detected[0], 1.0)
                self.assertEqual(provider.turns[0]["interrupt_reason"], "budget")
                self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "budget")
                self.assertFalse(provider.turns[0]["recovery_eligible"])
                self.assertEqual(self.methods(provider), ["turn/start"])
                self.assertFalse(provider.report()["measurement_complete"])

    def test_hard_byte_ceiling_preempts_already_latched_soft_guard(self):
        huge = delta("x" * (4 * 1024 * 1024))
        provider = self.provider([("turn/start", "initial", [*runaway(), huge])])
        sent = self.acknowledge_interrupt(provider)
        original = provider.incoming
        seen_hard_limit = []

        def incoming(timeout, private_id=None):
            event = original(timeout, private_id)
            if event is huge:
                seen_hard_limit.append(time.monotonic())
            return event

        provider.incoming = incoming
        with patch("lab.provider.OUTPUT_SETTLE_SECONDS", 600.0, create=True):
            with self.assertRaises(Fatal):
                provider.turn("thread", "Continue.", "author")

        self.assertEqual(len(seen_hard_limit), 1)
        self.assertEqual(len(sent), 1)
        self.assertLess(sent[0]["time"] - seen_hard_limit[0], 1.0)
        self.assertGreaterEqual(sent[0]["time"], seen_hard_limit[0])
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "hard_limit")
        self.assertEqual(provider.turns[0]["output_guard"]["hard_limit"], "agent_message_bytes")
        self.assertFalse(provider.report()["measurement_complete"])

    def test_unrelated_terminal_error_never_retries_after_soft_violation(self):
        provider = self.provider([("turn/start", "initial", [*runaway(),
            recovery.completed("initial", "other"), recovery.price("initial", 100)])])

        with self.assertRaisesRegex(Fatal, "agent turn ended unexpectedly"):
            provider.turn("thread", "Continue.", "author")

        self.assertFalse(provider.sent)
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.turns[0]["recovery_eligible"])
        self.assertFalse(provider.report()["measurement_complete"])

    def test_terminal_error_notification_preempts_settlement_and_context_recovery(self):
        policy_error = {"method": "error", "params": {
            "threadId": "thread", "turnId": "initial", "willRetry": False,
            "error": {"message": "terminal policy rejection", "codexErrorInfo": "policyViolation"}}}
        later_context_error = {"method": "error", "params": {
            "threadId": "thread", "turnId": "initial", "willRetry": False,
            "error": {"message": "context exceeded", "codexErrorInfo": "contextWindowExceeded"}}}
        provider = self.provider([("turn/start", "initial", [*runaway(), policy_error,
            later_context_error, recovery.price("initial", 100)])])
        sent = self.acknowledge_interrupt(provider)

        with self.assertRaisesRegex(Fatal, "terminal policy rejection"):
            provider.turn("thread", "Continue.", "author")

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["raw"], 0, "a terminal provider error must not await usage")
        self.assertEqual(provider.turns[0]["interrupt_reason"], "provider_error")
        self.assertFalse(provider.turns[0]["recovery_eligible"])
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])

    def test_empty_terminal_error_preserves_context_error_but_policy_error_overrides_it(self):
        for policy_override in (False, True):
            with self.subTest(policy_override=policy_override):
                context_error = {"method": "error", "params": {
                    "threadId": "thread", "turnId": "initial", "willRetry": False,
                    "error": {"message": "context exceeded", "codexErrorInfo": "contextWindowExceeded"}}}
                terminal = recovery.completed("initial")
                terminal["params"]["turn"].update(status="failed", error=(
                    {"message": "terminal policy rejection", "codexErrorInfo": "policyViolation"}
                    if policy_override else None))
                stages = [("turn/start", "initial", [context_error, terminal,
                                                     recovery.price("initial", 100)])]
                if not policy_override:
                    stages += [recovery.compaction(), recovery.success()]
                provider = self.provider(stages)

                if policy_override:
                    with self.assertRaisesRegex(Fatal, "terminal policy rejection"):
                        provider.turn("thread", "Continue.", "author")
                    self.assertEqual(self.methods(provider), ["turn/start"])
                    self.assertFalse(provider.turns[0]["recovery_eligible"])
                    self.assertFalse(provider.report()["measurement_complete"])
                else:
                    self.assertEqual(provider.turn("thread", "Continue.", "author"),
                                     "@standalone run -- fresh-proposal")
                    self.assertEqual(self.methods(provider),
                                     ["turn/start", "thread/compact/start", "turn/start"])
                    self.assertTrue(provider.turns[0]["recovery_eligible"])
                    self.assertIn("contextWindowExceeded", provider.turns[0]["error"])
                    self.assertTrue(provider.report()["measurement_complete"])
                    self.assertEqual(provider.usage.raw, 310)
                self.assertEqual([message["method"] for message in provider.sent], ["turn/interrupt"])
                self.assertEqual(provider.turns[0]["interrupt_reason"], "provider_error")

    def test_terminal_status_cannot_hide_a_policy_error(self):
        for status in ("completed", "interrupted"):
            with self.subTest(status=status):
                terminal = recovery.completed("initial")
                terminal["params"]["turn"].update(status=status, error={
                    "message": "terminal policy rejection", "codexErrorInfo": "policyViolation"})
                provider = self.provider([("turn/start", "initial", [*runaway(), terminal,
                                                                        recovery.price("initial", 100)])])

                with self.assertRaisesRegex(Fatal, "terminal policy rejection"):
                    provider.turn("thread", "Continue.", "author")

                self.assertFalse(provider.sent)
                self.assertEqual(self.methods(provider), ["turn/start"])
                self.assertFalse(provider.turns[0]["recovery_eligible"])
                self.assertFalse(provider.report()["measurement_complete"])

    def test_transient_and_foreign_error_notifications_do_not_block_priced_recovery(self):
        for kind in ("retrying", "foreign_turn", "foreign_thread"):
            for after_terminal in (False, True):
                with self.subTest(kind=kind, after_terminal=after_terminal):
                    notification = {"method": "error", "params": {
                        "threadId": "thread", "turnId": "initial", "willRetry": kind == "retrying",
                        "error": {"message": "transient or unrelated failure", "codexErrorInfo": "other"}}}
                    if kind == "foreign_turn":
                        notification["params"]["turnId"] = "other-turn"
                    elif kind == "foreign_thread":
                        notification["params"]["threadId"] = "other-thread"
                    events = runaway()
                    if after_terminal:
                        events.append(recovery.completed("initial"))
                    events += [notification, recovery.price("initial", 100)]
                    provider = self.provider([("turn/start", "initial", events),
                                              recovery.compaction(), recovery.success()])
                    sent = self.acknowledge_interrupt(provider)

                    self.assertEqual(provider.turn("thread", "Continue.", "author"),
                                     "@standalone run -- fresh-proposal")

                    self.assertEqual([row["raw"] for row in sent], [] if after_terminal else [110])
                    self.assertEqual(self.methods(provider),
                                     ["turn/start", "thread/compact/start", "turn/start"])
                    self.assertTrue(provider.report()["measurement_complete"])
                    self.assertEqual(provider.usage.raw, 310)

    def test_native_receipt_must_cover_transport_price_before_settlement(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                stages = [("turn/start", "initial", [*runaway(), recovery.price("initial", 100)])]
                if not missing:
                    # Real manual compaction costs appear in native receipts
                    # while the app-server's ordinary-response total is static.
                    stages += [recovery.compaction(tokens=100), recovery.success(tokens=200)]
                provider = self.provider(stages)
                path = provider.artifacts / "native-session.jsonl"
                path.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": "thread", "cwd": str(provider.repo)}}) + "\n")
                reader = NativeUsage(path, "thread", provider.repo)
                provider.native_usage = {"thread": reader}
                sent = self.acknowledge_interrupt(provider)
                original = provider.incoming
                idle_polls, receipt_count = [0], [0]

                def append_receipt(turn):
                    receipt_count[0] += 1
                    count = receipt_count[0]
                    usage = {"input_tokens": 100, "output_tokens": 10,
                             "cached_input_tokens": 0, "total_tokens": 110}
                    payload = {"thread_id": "thread", "session_id": "thread", "turn_id": turn,
                        "response_id": "response-" + turn, "usage": usage,
                        "thread_token_usage": {key: value * count for key, value in usage.items()}}
                    record = {"type": "token_usage_record", "payload": payload}
                    if turn == "compact":
                        record = {"type": "compacted", "payload": {
                            "compaction_response_id": payload["response_id"],
                            "latest_token_usage_record": payload}}
                    with path.open("a") as handle:
                        handle.write(json.dumps(record) + "\n")

                def incoming(timeout, private_id=None):
                    event = original(timeout, private_id)
                    if event is None and not receipt_count[0]:
                        idle_polls[0] += 1
                        if not missing and idle_polls[0] == 3:
                            append_receipt("initial")
                    elif event and event.get("method") == "thread/tokenUsage/updated":
                        turn = event["params"]["turnId"]
                        if turn != "initial":
                            append_receipt(turn)
                    return event

                provider.incoming = incoming
                if missing:
                    with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
                        provider.turn("thread", "Continue.", "author")
                    self.assertEqual(self.methods(provider), ["turn/start"])
                    self.assertEqual(provider.turns[0]["output_guard"]["settle_seconds"], 600)
                    self.assertEqual(provider.turns[0]["interrupt_reason"], "runaway_output")
                    self.assertFalse(provider.report()["measurement_complete"])
                else:
                    self.assertEqual(provider.turn("thread", "Continue.", "author"),
                                     "@standalone run -- fresh-proposal")
                    self.assertEqual(idle_polls[0], 3)
                    self.assertEqual(provider.turns[0]["output_guard"]["settlement"], "priced_boundary")
                    self.assertTrue(provider.report()["measurement_complete"])
                    self.assertEqual(provider.usage.raw, 330)
                    self.assertEqual(len(reader.responses), 3)
                self.assertEqual([row["raw"] for row in sent], [110])


if __name__ == "__main__":
    unittest.main()
