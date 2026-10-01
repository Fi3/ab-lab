from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from lab.codex_children import NativeChildren
from lab.host import Fatal
from lab.nested import NestedUsage
from lab.provider import Codex, Usage
from lab.sandbox import CommandSandbox


def event(method, thread="child", turn_id="child-turn", **params):
    return {"method": method, "params": {"threadId": thread, "turnId": turn_id, **params}}


def spawn(parent="parent", child="child"):
    return event("item/started", parent, "parent-turn", item={
        "type": "subAgentActivity", "kind": "started", "agentThreadId": child})


def message(thread="child", turn="child-turn", text="Child result"):
    return event("item/completed", thread, turn, item={"type": "agentMessage", "text": text})


def price(thread="child", turn="child-turn", input_tokens=60, output_tokens=10):
    value = {"inputTokens": input_tokens, "outputTokens": output_tokens, "cachedInputTokens": 0}
    return event("thread/tokenUsage/updated", thread, turn, tokenUsage={"total": value, "last": value})


def completed(thread="child", turn="child-turn", status="completed"):
    return event("turn/completed", thread, turn, **{"turn": {"id": turn, "status": status}})


class NativeChildIntegrationTests(unittest.TestCase):
    """Drive real incoming/observation code using only an owned temporary rollout."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = 1000.0
        clock = patch("lab.provider.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.remaining = deque()
        p = self.provider = object.__new__(Codex)
        p.repo = p.artifacts = self.root
        p.model, p.effort = "test-model", "high"
        p.turns, p.missing_turns, p.pending = [], [], deque()
        p.parent_threads, p.native_usage = {"parent"}, {}
        p.native_children, p.usage = NativeChildren(), Usage()
        p.max_turns, p.max_raw, p.deadline = 10, 10000, self.now + 30
        p.counter, p.active = 0, None
        p.sandbox = CommandSandbox(p.repo, "codex")
        p.nested = NestedUsage(p.repo, p.model, p.effort, self.root / "sessions")
        p.sent, p.received = [], []
        p.send = p.sent.append
        p.record = lambda direction, value: p.received.append(value)
        p.rpc = lambda method, params: {"turn": {"id": "parent-turn"}}
        # Keep Codex.incoming intact so every notification reaches both readers.
        p.events = self

    def get(self, timeout):
        self.now += max(timeout, 0.01)
        if not self.remaining:
            raise queue.Empty()
        step = self.remaining.popleft()
        return step() if callable(step) else step

    def deliver(self, *events):
        self.remaining.extend(events)
        for _ in events:
            self.provider.incoming(0)

    def append(self, path, kind, payload):
        with path.open("a") as stream:
            stream.write(json.dumps({"type": kind, "payload": payload}) + "\n")

    def receipt(self, thread="child", turn="child-turn", response="child-response", total=60, usage=None):
        tokens = {"input_tokens": total, "output_tokens": 10, "cached_input_tokens": 0}
        return {"thread_id": thread, "session_id": "parent", "turn_id": turn,
                "response_id": response, "usage": tokens if usage is None else usage,
                "thread_token_usage": tokens}

    def history(self, child="child", **context):
        folder = self.root / "sessions" / datetime.now(timezone.utc).strftime("%Y/%m/%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (child + ".jsonl")
        self.append(path, "session_meta", {"id": child, "cwd": str(self.root),
            "parent_thread_id": "parent", "forked_from_id": "parent", "session_id": "parent",
            "subagent_history_start_ordinal": 4})
        self.append(path, "session_meta", {"id": "parent", "cwd": str(self.root)})
        self.append(path, "turn_context", {"turn_id": "inherited-turn", "cwd": str(self.root),
            "model": "inherited-model", "effort": "low"})
        self.append(path, "event_msg", {"type": "token_count", "rate_limits": {"plan_type": "api"}})
        self.append(path, "token_usage_record", self.receipt("parent", "inherited-turn", "inherited", 5000))
        self.context(path, "child-turn", **context)
        return path

    def context(self, path, turn, **values):
        self.append(path, "turn_context", {"turn_id": turn, "cwd": str(self.root),
            "model": self.provider.model, "effort": self.provider.effort, **values})
        self.append(path, "event_msg", {"type": "token_count", "rate_limits": {"plan_type": "pro"}})

    def admit(self):
        path = self.history()
        self.deliver(spawn(), event("turn/started"))
        self.provider.refresh_native_usage(force=True)
        return path

    def parent_tail(self):
        return [message("parent", "parent-turn", "Parent result"),
                price("parent", "parent-turn", 20, 10), completed("parent", "parent-turn")]

    def test_spawn_allows_host_call_and_parent_waits_for_child_completion_and_receipt(self):
        p = self.provider
        calls, checkpoints = [], []
        path = None

        def spawned():
            nonlocal path
            path = self.history()
            return spawn()

        def host(name, arguments, identity):
            calls.append(identity)
            report = p.report()
            self.assertFalse(report["measurement_complete"])
            self.assertTrue(report["native_children"]["active"])
            self.assertEqual(report["observed_raw_tokens"], 0)
            return {"success": True, "text": "Host operation completed"}

        def first_price_seen():
            report = p.report()
            self.assertEqual(report["observed_raw_tokens"], 70)
            self.assertTrue(report["native_children"]["active"])
            self.assertFalse(report["measurement_complete"])
            checkpoints.append("first price remains pending")
            return message("parent", "parent-turn", "Parent result")

        def drain_boundary():
            self.now += 1.1
            self.assertEqual(p.turns[0]["status"], "completed")
            self.assertFalse(p.report()["measurement_complete"])
            return event("thread/status/changed")

        def terminal():
            self.assertTrue(p.turns[0]["usage_observed_after_last_message"])
            checkpoints.append("child completes during settlement")
            return completed()

        def receipt_arrives():
            report = p.report()
            self.assertFalse(report["native_children"]["active"])
            self.assertFalse(report["measurement_complete"])
            for _ in range(2):
                self.append(path, "token_usage_record", self.receipt())
            checkpoints.append("receipt arrives after completion")
            return price()

        p.register_host_tools("parent", [{"name": "host_echo"}], host)
        self.remaining.extend([spawned, {"id": 55, "method": "item/tool/call", "params": {
            "threadId": "parent", "turnId": "parent-turn", "callId": "host-call",
            "tool": "host_echo", "arguments": {}}}, event("turn/started"), message(), price(),
            first_price_seen, *self.parent_tail()[1:], drain_boundary, terminal, receipt_arrives])

        self.assertEqual(p.turn("parent", "request", "author"), "Parent result")
        self.assertEqual(calls, ["parent:parent-turn:host-call"])
        self.assertEqual(len(checkpoints), 3)
        self.assertFalse(self.remaining)
        self.assertEqual(p.sent, [{"id": 55, "result": {"success": True,
            "contentItems": [{"type": "inputText", "text": "Host operation completed"}]}}])
        report = p.report()
        self.assertTrue(report["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 100)
        self.assertEqual(report["nested"]["observed_raw_tokens"], 0)
        reader = p.native_usage["child"]
        self.assertEqual(reader.plans, {"pro"})
        self.assertEqual(set(reader.turn_contexts), {"child-turn"})
        self.assertEqual(set(reader.responses), {"child-response"})
        self.assertEqual(len(reader.responses["child-response"]["sources"]), 2)

    def test_completed_child_without_receipt_fails_after_bounded_settlement(self):
        self.admit()
        self.deliver(message(), price(), completed())
        with self.assertRaisesRegex(Fatal, "incomplete native child token measurement"):
            self.provider.settle_children()
        self.assertLess(self.now, self.provider.deadline)
        self.assertFalse(self.provider.report()["measurement_complete"])

    def test_aborted_child_remains_incomplete_even_with_receipt(self):
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price(), completed(status="interrupted"))
        with self.assertRaisesRegex(Fatal, "native child accounting failure"):
            self.provider.settle_children()
        report = self.provider.report()
        self.assertFalse(report["native_children"]["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 70)

    def test_active_child_with_receipt_is_still_not_complete(self):
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price())
        self.provider.refresh_native_usage(force=True)
        report = self.provider.native_child_report()
        self.assertTrue(report["active"])
        self.assertFalse(report["measurement_complete"])
        self.deliver(completed())
        self.assertTrue(self.provider.native_child_report()["measurement_complete"])

    def test_child_usage_counts_once_against_global_token_budget(self):
        path = self.admit()
        for _ in range(2):
            self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price(), price(), completed())
        self.provider.refresh_native_usage(force=True)
        self.provider.max_raw = 60
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
            self.provider.settle_children()
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
            self.provider.check_limits()
        report = self.provider.report()
        self.assertEqual(report["observed_raw_tokens"], 70)
        self.assertEqual(report["app_server_thread_totals"]["child"], (60, 10, 0))
        self.assertEqual(report["native_thread_totals"]["child"], (60, 10, 0))

    def test_active_child_settlement_stops_at_global_wall_time_limit(self):
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price())
        self.provider.deadline = self.now + 0.3
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
            self.provider.settle_children()
        self.assertGreaterEqual(self.now, self.provider.deadline)
        self.assertLessEqual(self.now, self.provider.deadline + 0.11)
        report = self.provider.report()
        self.assertTrue(report["native_children"]["active"])
        self.assertFalse(report["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 70)

    def test_completed_priced_child_with_unadmitted_model_and_effort_fails(self):
        path = self.history(model="other-model", effort="low")
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(spawn(), event("turn/started"), message(), price(), completed())
        with self.assertRaisesRegex(Fatal, "child model/effort differs from admission"):
            self.provider.settle_children()
        report = self.provider.report()
        self.assertFalse(report["native_children"]["active"])
        self.assertFalse(report["native_children"]["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 70)

    def test_child_compaction_receipt_increases_native_cost_exactly_once(self):
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        compacted = self.receipt(response="child-compaction", total=80,
            usage={"input_tokens": 20, "output_tokens": 5, "cached_input_tokens": 0})
        compacted["thread_token_usage"]["output_tokens"] = 15
        self.append(path, "compacted", {"compaction_response_id": "child-compaction",
            "latest_token_usage_record": compacted})
        self.append(path, "token_usage_record", compacted)
        self.deliver(message(), price(), event("item/completed", item={
            "type": "contextCompaction", "id": "compaction-item"}), completed())
        self.provider.settle_children()
        report = self.provider.report()
        self.assertTrue(report["native_children"]["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 95)
        self.assertEqual(report["app_server_thread_totals"]["child"], (60, 10, 0))
        self.assertEqual(report["native_thread_totals"]["child"], (80, 15, 0))
        reader = self.provider.native_usage["child"]
        self.assertEqual(len(reader.completed_compactions("child-turn")), 1)
        self.assertEqual(len(reader.responses["child-compaction"]["sources"]), 2)

    def test_foreign_spawn_does_not_adopt_a_child(self):
        self.deliver(spawn(parent="foreign"), event("turn/started"))
        self.assertFalse(self.provider.native_children.threads)
        self.assertFalse(self.provider.native_usage)
        self.assertTrue(self.provider.native_child_report()["measurement_complete"])

    def test_fork_history_before_spawn_notification_does_not_recharge_parent(self):
        p = self.provider
        self.deliver(price("parent", "parent-turn", 140, 10))
        p.max_raw = 200
        p.turns.append({"thread_id": "parent", "turn_id": "parent-turn", "status": "completed",
                        "usage_observed_after_last_message": True})
        self.assertTrue(p.report()["measurement_complete"])
        path = self.history()
        self.remaining.extend([spawn(), event("turn/started")])
        # The filesystem can expose a fork before its spawn notification reaches
        # incoming(); inherited model, plan, and receipts still belong to parent.
        self.now += 2.1
        self.assertEqual(p.observed_raw(), 150)
        self.assertIsNone(p.budget_error())
        report = p.report()
        self.assertEqual(report["observed_raw_tokens"], 150)
        self.assertFalse(report["measurement_complete"])
        while self.remaining:
            p.incoming(0)
        self.append(path, "token_usage_record", self.receipt(total=20))
        self.deliver(message(), price(input_tokens=20), completed())
        p.settle_children()
        self.assertEqual(p.report()["observed_raw_tokens"], 180)
        self.assertTrue(p.report()["measurement_complete"])

    def test_child_report_defers_file_created_after_its_single_header_scan(self):
        p = self.provider
        original_scan, created = p.nested.scan, []

        def scan_then_fork(force=False):
            original_scan(force=force)
            if not created:
                created.append(self.history())

        with patch.object(p.nested, "scan", side_effect=scan_then_fork) as scan:
            first = p.child_report(force=True)
            scan.assert_called_once_with(force=True)
            self.assertNotIn(created[0], p.nested.files)
            self.assertNotIn("child", p.native_children.threads)
            self.assertEqual(first["observed_raw_tokens"], 0)
            self.assertFalse(first["errors"])

            second = p.child_report(force=True)
            self.assertEqual(scan.call_count, 2)
            self.assertIn(created[0], p.nested.files)
            self.assertIn("child", p.native_children.threads)
            self.assertNotIn("child", p.nested.threads)
            self.assertEqual(second["observed_raw_tokens"], 0)
            self.assertFalse(second["errors"])
            self.assertFalse(p.native_child_report()["measurement_complete"])

    def test_settlement_consumes_queued_resume_after_previously_completed_child(self):
        p = self.provider
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price(), completed())
        p.settle_children()
        self.context(path, "resumed-turn")
        consumed = []

        def resumed_completion():
            report = p.native_child_report()
            self.assertTrue(report["active"])
            self.assertFalse(report["measurement_complete"])
            receipt = self.receipt(turn="resumed-turn", response="resumed-response", total=80,
                usage={"input_tokens": 20, "output_tokens": 10, "cached_input_tokens": 0})
            receipt["thread_token_usage"]["output_tokens"] = 20
            self.append(path, "token_usage_record", receipt)
            consumed.append("resumed-turn")
            return completed(turn="resumed-turn")

        self.remaining.extend([event("turn/started", turn_id="resumed-turn"),
            message(turn="resumed-turn"), price(turn="resumed-turn", input_tokens=80, output_tokens=20),
            resumed_completion])
        p.settle_children()
        self.assertEqual(consumed, ["resumed-turn"])
        self.assertFalse(self.remaining)
        self.assertTrue(p.native_child_report()["measurement_complete"])
        self.assertEqual(p.usage.raw, 100)

    def test_second_child_turn_requires_its_own_completion_and_receipt(self):
        path = self.admit()
        self.append(path, "token_usage_record", self.receipt())
        self.deliver(message(), price(), completed())
        self.provider.settle_children()
        self.context(path, "resumed-turn")
        self.deliver(event("turn/started", turn_id="resumed-turn"), message(turn="resumed-turn"),
                     price(turn="resumed-turn", input_tokens=80, output_tokens=20))
        self.provider.refresh_native_usage(force=True)
        self.assertFalse(self.provider.native_child_report()["measurement_complete"])
        receipt = self.receipt(turn="resumed-turn", response="resumed-response", total=80,
            usage={"input_tokens": 20, "output_tokens": 10, "cached_input_tokens": 0})
        receipt["thread_token_usage"]["output_tokens"] = 20
        self.append(path, "token_usage_record", receipt)
        self.deliver(completed(turn="resumed-turn"))
        self.provider.settle_children()
        self.assertTrue(self.provider.native_child_report()["measurement_complete"])
        self.assertEqual(self.provider.usage.raw, 100)

    def test_parent_without_children_retains_normal_receipt_accounting(self):
        path = self.root / "parent.jsonl"
        self.append(path, "session_meta", {"id": "parent", "cwd": str(self.root)})
        self.append(path, "token_usage_record",
                    self.receipt("parent", "parent-turn", "parent-response", 20))
        self.provider.register_native_thread({"id": "parent", "path": str(path)})
        self.remaining.extend(self.parent_tail())
        self.assertEqual(self.provider.turn("parent", "request", "author"), "Parent result")
        report = self.provider.report()
        self.assertTrue(report["measurement_complete"])
        self.assertEqual(report["observed_raw_tokens"], 30)
        self.assertFalse(report["native_children"]["threads"])
        self.assertFalse(self.provider.sent)


if __name__ == "__main__":
    unittest.main()
