"""Tests for Pi harness support in agent-behavior-lab."""
from collections import deque
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from lab.__main__ import main
from lab.config import settings
from lab.host import Fatal
from lab.provider import Pi, Usage
from lab.workflow import run
from test_scb import benchmark_at
from test_workflow import review_arguments, verdict


class FakePi:
    instances = []
    transport = "pi-rpc-stdio"

    def __init__(self, repo, folder, model, effort, deadline, max_raw, max_turns, executable="pi", *, require_git_write=False, allow_delegation=False):
        FakePi.instances.append(self)
        self.repo = Path(repo)
        self.artifacts = Path(folder)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.identity = {
            "pi_version": "0.85.1",
            "harness": "pi",
            "auth": "antigravity",
            "model": model or "gemini-3.8-flash",
            "effort": effort,
            "effective_config_sha256": "fake_pi_hash"
        }
        self.calls, self.authors, self.fixes = [], {}, {}
        self.model = model
        self.effort = effort
        self.deadline = deadline
        self.max_raw = max_raw
        self.max_turns = max_turns
        self.require_git_write = require_git_write
        self.threads = 0
        self.handlers = {}

    def start_thread(self, writable=False, tools=None, tool_handler=None):
        self.threads += 1
        thread = f"fake-pi-thread-{self.threads}"
        if tools:
            self.handlers[thread] = tool_handler
        return thread

    def report(self):
        return {
            "observed_raw_tokens": 150,
            "cached_input_tokens": 15,
            "measurement_complete": True,
            "thread_totals": {"fake-pi-thread-1": (100, 50, 15)},
            "turns": [{"label": c[0], "status": "completed"} for c in self.calls],
            "unpriced_or_incomplete_turns": [],
            "nested": {"observed_raw_tokens": 0, "cached_input_tokens": 0, "measurement_complete": True, "errors": [], "incomplete": []}
        }

    def close(self):
        pass

    def turn(self, thread, prompt, label, **kwargs):
        self.calls.append((label, thread, prompt, kwargs))
        folder = self.artifacts / f"turn-{len(self.calls):04d}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt.txt").write_text(prompt)
        if label.endswith("-implement"):
            name = label.removesuffix("-implement")
            result = self.handlers[thread]("host_edit", {
                "reason": f"implement {name}",
                "patch": f"*** Begin Patch\n*** Add File: {name}.py\n+value = 1\n*** End Patch\n",
            }, f"{thread}:{label}:edit")
            assert result["success"], result
            reply = "Implemented."
        elif "-review-" in label:
            value = verdict("Change one.py value to 2") if label == "one-review-1" else verdict()
            self.handlers[thread]("submit_review", review_arguments(prompt, value), f"{thread}:{label}:verdict")
            reply = "Review submitted."
        elif "-fix-" in label:
            result = self.handlers[thread]("host_edit", {
                "reason": "resolve review",
                "patch": "*** Begin Patch\n*** Update File: one.py\n@@\n-value = 1\n+value = 2\n*** End Patch\n",
            }, f"{thread}:{label}:edit")
            assert result["success"], result
            reply = "Fixed."
        else:
            reply = "OK"
        (folder / "reply.txt").write_text(reply)
        save_result = {"label": label, "thread_id": thread, "status": "completed", "reply": reply}
        (folder / "result.json").write_text(json.dumps(save_result))
        return reply


class PiCliTests(unittest.TestCase):
    def test_run_requires_harness_argument(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "bench.json"
            path.write_text(json.dumps(benchmark_at(root)))
            argv = ["lab", "run", str(path), "--out", str(root / "run"),
                    "--seconds", "30", "--max-raw", "1000", "--max-turns", "10"]
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 2)

    def test_run_with_harness_codex_selects_codex_backend(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "bench.json"
            path.write_text(json.dumps(benchmark_at(root)))
            with patch("lab.__main__.run", return_value={"status": "passed"}) as runner:
                argv = ["lab", "run", str(path), "--out", str(root / "run"),
                        "--seconds", "30", "--max-raw", "1000", "--max-turns", "10",
                        "--harness", "codex", "--codex", "custom-codex"]
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                from lab.provider import Codex
                self.assertIs(runner.call_args.kwargs["backend"], Codex)
                self.assertEqual(runner.call_args.args[8], "custom-codex")

    def test_run_with_harness_pi_selects_pi_backend(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "bench.json"
            path.write_text(json.dumps(benchmark_at(root)))
            with patch("lab.__main__.run", return_value={"status": "passed"}) as runner:
                argv = ["lab", "run", str(path), "--out", str(root / "run"),
                        "--seconds", "30", "--max-raw", "1000", "--max-turns", "10",
                        "--harness", "pi", "--pi", "custom-pi"]
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                from lab.provider import Pi
                self.assertIs(runner.call_args.kwargs["backend"], Pi)
                self.assertEqual(runner.call_args.args[8], "custom-pi")

    def test_plan_with_harness_pi(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "bench.json"
            path.write_text(json.dumps(benchmark_at(root)))
            output = io.StringIO()
            with patch.object(sys, "argv", ["lab", "plan", str(path), "--harness", "pi"]), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            plan_data = json.loads(output.getvalue())
            self.assertEqual(plan_data["model"], "gpt-5.5")

    def test_doctor_with_harness_pi(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            output = io.StringIO()
            argv = ["lab", "doctor", "--repo", str(root), "--out", str(root / "doc"), "--harness", "pi"]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            doc_data = json.loads(output.getvalue())
            self.assertEqual(doc_data["harness"], "pi")
            self.assertIn("pi_version", doc_data)
            self.assertEqual(doc_data["generation"], "none")


class PiUsageTests(unittest.TestCase):
    def test_observe_tokens_increments(self):
        u = Usage()
        self.assertTrue(u.observe_tokens("t1", 100, 20, 5))
        self.assertEqual(u.raw, 120)
        self.assertEqual(u.cached, 5)
        self.assertEqual(u.uncertain, [])

        # same counts: returns False
        self.assertFalse(u.observe_tokens("t1", 100, 20, 5))

        # increased counts
        self.assertTrue(u.observe_tokens("t1", 150, 40, 10))
        self.assertEqual(u.raw, 190)
        self.assertEqual(u.cached, 10)

    def test_observe_tokens_decreased_marks_uncertain(self):
        u = Usage()
        u.observe_tokens("t1", 100, 50, 0)
        self.assertFalse(u.observe_tokens("t1", 90, 50, 0))
        self.assertIn("provider counters decreased for t1; no negative charge inferred", u.uncertain)

    def test_observe_tokens_invalid_marks_uncertain(self):
        u = Usage()
        self.assertFalse(u.observe_tokens("t1", -1, 50, 0))
        self.assertIn("invalid usage notification", u.uncertain)


class PiWorkflowIntegrationTests(unittest.TestCase):
    def test_workflow_runs_with_pi_backend(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b = benchmark_at(root)
            out = root / "run-pi"
            result = run(b, settings({}), out, 30, 10000, 30, backend=FakePi, harness="pi")
            self.assertEqual(result["status"], "passed")
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["transport"], "pi-rpc-stdio")
            self.assertEqual(result["usage"]["observed_raw_tokens"], 150)
            self.assertTrue(result["usage"]["measurement_complete"])


class PiProviderStreamTests(unittest.TestCase):
    def test_review_limit_never_returns_an_approval_after_exhaustion(self):
        from lab.loops import WorkLimitReached
        for threshold in (100, 50):
            with self.subTest(threshold=threshold):
                p = self.fake_pi_provider([
                    {"type": "message_end", "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "NO_FINDINGS"}],
                        "usage": {"input": 40, "output": 10, "cacheRead": 0}}},
                    {"type": "agent_settled"},
                ])
                p.work_limits = [{"reason": "review_token_limit", "metric": "observed_raw_tokens",
                                  "start": 0, "limit": threshold}]
                with self.assertRaises(WorkLimitReached) as stopped:
                    p.turn("t1", "review", "review-1")
                self.assertFalse(hasattr(stopped.exception, "completed_reply"))
                self.assertEqual(p.usage.raw, 125)
                self.assertTrue(p.report()["measurement_complete"])

    def test_feature_budget_interrupts_inside_native_turn_and_retains_session_usage(self):
        from lab.loops import WorkLimitReached
        p = self.fake_pi_provider([
            {"type": "message_end", "message": {"role": "assistant",
                "content": [{"type": "text", "text": "Implementation in progress."}],
                "usage": {"input": 40, "output": 10, "cacheRead": 0}}},
            {"type": "agent_settled"},
        ])
        p.work_limits = [{"reason": "feature_token_limit", "metric": "observed_raw_tokens", "start": 0, "limit": 50}]
        with self.assertRaises(WorkLimitReached):
            p.turn("t1", "implement", "author", writable=True)
        self.assertEqual([m["type"] for m in p.sent_messages], ["prompt", "abort"])
        self.assertEqual(p.usage.raw, 125)
        self.assertTrue(p.report()["measurement_complete"])
        self.assertEqual(p.turns[0]["work_limit"]["observed"], 125)

    def fake_pi_provider(self, events):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = object.__new__(Pi)
        p.artifacts = Path(tmp.name)
        p.turns, p.missing_turns = [], []
        p.max_turns, p.max_raw, p.deadline = 10, 100000, time.monotonic() + 30
        p.usage = Usage()
        p.prepare_turn = MagicMock()
        p.model, p.effort, p.repo = "test-model", "xhigh", p.artifacts
        p.log = (p.artifacts / "transport.jsonl").open("w")
        self.addCleanup(p.log.close)

        # Mock thread
        th = MagicMock()
        th.thread_id = "t1"
        th.policy = p.artifacts / "t1-sandbox.json"
        th.policy.write_text("{}")
        sent_messages = []
        th.send = lambda msg: sent_messages.append(msg)
        th_events = deque(events)

        def incoming(timeout):
            if not th_events:
                return None
            return th_events.popleft()

        def rpc(msg, timeout=30):
            return {"type": "response", "success": True, "data": {"tokens": {"input": 100, "output": 20, "cacheRead": 5}}}

        th.incoming = incoming
        th.rpc = rpc
        p.threads = {"t1": th}
        p.sent_messages = sent_messages
        return p

    def test_normal_turn_flow(self):
        events = [
            {"id": "turn-0001", "type": "response", "command": "prompt", "success": True},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_start", "message": {"role": "assistant"}},
            {"type": "message_update", "usage": {"input": 50, "output": 10, "cacheRead": 0}},
            {"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello world!"}],
                "usage": {"input": 50, "output": 10, "cacheRead": 0}
            }},
            {"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello world!"}]}},
            {"type": "agent_end"},
            {"type": "agent_settled"}
        ]
        p = self.fake_pi_provider(events)
        reply = p.turn("t1", "hi", "test-label")
        self.assertEqual(reply, "Hello world!")
        self.assertEqual(p.turns[0]["status"], "completed")
        self.assertTrue(p.turns[0]["usage_observed_after_last_message"])
        self.assertEqual(p.missing_turns, [])
        rep = p.report()
        self.assertTrue(rep["measurement_complete"])
        self.assertEqual(rep["observed_raw_tokens"], 125)

    def test_turn_limit_reached_raises_fatal(self):
        p = self.fake_pi_provider([])
        p.turns = [{}] * 10
        with self.assertRaisesRegex(Fatal, "workflow turn limit reached"):
            p.turn("t1", "hi", "test")

    def test_budget_exceeded_raises_fatal(self):
        p = self.fake_pi_provider([])
        p.max_raw = 50
        p.usage.observe_tokens("t1", 100, 10)
        with self.assertRaisesRegex(Fatal, "workflow wall-time/observed-token limit reached"):
            p.turn("t1", "hi", "test")


if __name__ == "__main__":
    unittest.main()
