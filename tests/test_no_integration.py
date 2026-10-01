"""Completion preserves the author submission and adds no model stage."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.config import FACTORS, settings
from lab.host import git
from lab.workflow import run
from test_scb import benchmark_at, checker_at, PHASES
from test_workflow import FakeCodex


class NoIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.benchmark = benchmark_at(self.root)

    def execute(self):
        return run(self.benchmark, settings({}), self.root / "run", 30, 10000, 30,
                   backend=FakeCodex, scb_check=checker_at(self.root))

    def test_last_author_source_and_commits_are_final_submission(self):
        result = self.execute()
        self.assertEqual(result["status"], "passed", result)
        checkout = self.root / "run/checkout"
        self.assertEqual(git(checkout, "rev-parse", "HEAD").decode().strip(),
                         result["checkpoints"][-1]["head"])
        self.assertEqual(len(result["final_commits"]), 3)
        self.assertFalse(any(label.startswith("integration-")
                             for label, *_ in FakeCodex.instances[-1].calls))
        self.assertFalse(FakeCodex.instances[-1].options["allow_delegation"])
        self.assertFalse((checkout / "README.md").exists())
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertEqual(set(result["scb_check"]["measurements"]), set(PHASES))
        self.assertEqual(result["scb_check"]["status"], "completed")
        self.assertNotIn("skip_linearization", result)

    def test_failed_final_check_is_reported_without_an_agent_repair(self):
        self.benchmark["checks"] = ["false"]
        result = self.execute()
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("final check 1 failed", result["error"])
        self.assertEqual(len(FakeCodex.instances[-1].calls), 6)

    def test_validation_cannot_silently_commit_a_changed_submission(self):
        self.benchmark["checks"] = [
            "printf 'changed\n' > one.py && git add one.py && git commit -qm changed"]
        result = self.execute()
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("final validation changed submitted source", result["error"])

    def test_native_author_receives_only_benchmark_request_with_delegation_enabled(self):
        class Native(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                self.assertion = not self.tool_handlers
                (self.repo / (label.removesuffix("-implement") + ".py")).write_text("value = 1\n")
                return "Done."

        factors = dict.fromkeys(FACTORS, False)
        result = run(self.benchmark, factors, self.root / "native", 30, 10000, 30,
                     backend=Native, max_review_loops=0, loop_options={"enabled": False}, preset="native")
        self.assertEqual(result["status"], "passed", result)
        backend = Native.instances[-1]
        self.assertTrue(backend.options["allow_delegation"])
        self.assertTrue(backend.assertion)
        self.assertEqual([prompt for _, _, prompt, _ in backend.calls],
                         [feature["request"] for feature in self.benchmark["features"]])
        self.assertTrue(all(options["writable"] for _, _, _, options in backend.calls))
        self.assertEqual(result["reviews"], [])
        self.assertEqual(result["preset"], "native")


class NativePresetCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "benchmark.json"
        self.path.write_text(json.dumps(benchmark_at(self.root)))

    def plan(self, *options):
        output = io.StringIO()
        with patch.object(sys, "argv", ["lab", "plan", str(self.path), *options]), \
                contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        return json.loads(output.getvalue())

    def test_native_disables_all_conditions_reviews_and_loop_detection(self):
        plan = self.plan("--preset", "native")
        self.assertEqual(plan["factors"], dict.fromkeys(FACTORS, False))
        self.assertEqual(plan["author_policy"], "")
        self.assertEqual(plan["max_review_loops"], 0)
        self.assertFalse(plan["loop_policy"]["enabled"])
        self.assertEqual(plan["preset"], "native")

    def test_explicit_conditions_and_limits_override_native_defaults(self):
        policy = self.root / "policy.json"
        policy.write_text('{"enabled": true, "repeat_limit": 4}')
        plan = self.plan("--preset", "native", "--on", "C17,C20",
                         "--max-review-loops", "2", "--loop-policy", str(policy))
        self.assertEqual({key for key, enabled in plan["factors"].items() if enabled},
                         {"C17", "C20"})
        self.assertEqual(plan["max_review_loops"], 2)
        self.assertTrue(plan["loop_policy"]["enabled"])
        self.assertEqual(plan["loop_policy"]["repeat_limit"], 4)

    def test_both_harnesses_and_batch_receive_native_effective_settings(self):
        for harness in ("codex", "pi"):
            for parallel in (1, 2):
                with self.subTest(harness=harness, parallel=parallel):
                    target = "run" if parallel == 1 else "run_batch"
                    arguments = ["lab", "run", str(self.path), "--preset", "native",
                        "--harness", harness, "--parallel", str(parallel),
                        "--out", str(self.root / "out"), "--seconds", "30",
                        "--max-raw", "10000", "--max-turns", "30"]
                    with patch("lab.__main__." + target, return_value={"status": "passed"}) as launch, \
                            patch.object(sys, "argv", arguments), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main(), 0)
                    self.assertEqual(launch.call_args.args[1], dict.fromkeys(FACTORS, False))
                    self.assertEqual(launch.call_args.kwargs["max_review_loops"], 0)
                    self.assertFalse(launch.call_args.kwargs["loop_options"]["enabled"])
                    self.assertEqual(launch.call_args.kwargs["preset"], "native")

    def test_removed_linearization_flag_is_rejected(self):
        with patch.object(sys, "argv", ["lab", "plan", str(self.path), "--skip-linearization"]), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main()
        self.assertEqual(raised.exception.code, 2)
