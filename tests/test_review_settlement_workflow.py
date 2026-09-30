"""A priced, stopped review retains its evidence and blocks dependent work.

Provider timing/receipts are scripted here; transport receipt ownership is
covered by test_review_settlement. Host operations, Git commits, snapshot
capture, and the existing subprocess evaluator fixture all run.
"""
import json
from pathlib import Path
import shlex
import sys
import time
import unittest

from lab.host import git, save_json
from lab.loops import WorkLimitReached, work_limit_error
import test_scb_attention as attention
import test_slopcodebench as fixtures


def check_command(names, marker):
    code = "import runpy; " + "; ".join(
        f"assert runpy.run_path({name + '.py'!r})['value'] == {value}"
        for name, value in names.items()) + f"; print({marker!r})"
    return shlex.join([sys.executable, "-c", code])


class ReviewSettlementWorkflowTests(unittest.TestCase):
    # Reuse disposable repositories and the external evaluator without
    # inheriting unrelated test methods or replacing any workflow checks.
    setUp = fixtures.SlopCodeBenchTests.setUp
    benchmark = fixtures.SlopCodeBenchTests.benchmark
    workflow = fixtures.SlopCodeBenchTests.workflow
    evaluated = fixtures.SlopCodeBenchTests.evaluated

    def execute(self, stopped_feature="two", *, complete=True, verdict="NO_FINDINGS",
                preserve=True, name="run"):
        class Backend(attention.ScenarioBackend):
            def report(self):
                report = super().report()
                if hasattr(self, "settled_turn"):
                    report["turns"] = [self.settled_turn]
                    if not self.complete:
                        report["unpriced_or_incomplete_turns"] = [self.settled_turn]
                return report

        def settle(backend):
            # Keep the explicit timer expired while accounting settles. Neither
            # a priced interruption nor a late verdict authorizes a new stage.
            now = time.monotonic()
            limit = next(item for item in backend.work_limits
                         if item["reason"] == "review_time_limit")
            limit["start"] = now - limit["limit"] - 0.125
            stopped = work_limit_error(backend.work_limits, backend.raw, now=now)
            self.assertIsInstance(stopped, WorkLimitReached)
            self.assertEqual(stopped.signal["reason"], "review_time_limit")
            self.assertEqual(stopped.settle_seconds, 600)
            backend.expired_limits = [dict(item) for item in backend.work_limits]
            backend.raw_before_settlement = backend.raw
            if complete:
                backend.raw += 73  # Explicit fixture receipt, never estimated cost.
            backend.complete = complete
            backend.raw_after_settlement = backend.raw
            folder = backend.artifacts / "scripted-review-settlement"
            folder.mkdir()
            (folder / "reply.txt").write_text(verdict)
            backend.settled_turn = {
                "fixture": "scripted-provider-receipt",
                "label": stopped_feature + "-review-1",
                "reply_file": str(folder / "reply.txt"),
                "status": "completed" if verdict else "interrupted",
                "measurement_complete": complete,
                "observed_raw_tokens": 73 if complete else None,
                "work_limit": dict(stopped.signal),
                "work_limit_settlement": {
                    "trigger": dict(stopped.signal), "settle_seconds": 600,
                    "outcome": ("turn_completed" if verdict else "priced_boundary")
                    if complete else "timeout",
                    "elapsed_seconds": 40 if complete else 600,
                },
            }
            save_json(folder / "result.json", backend.settled_turn)
            raise stopped

        Backend.preserve_history = preserve
        Backend.script = {}
        for feature, value in (("one", 2), ("two", 1)):
            Backend.script[feature + "-implement"] = [
                attention.edit(feature, value),
                {"name": "host_run", "arguments": {"command": check_command({feature: value}, feature + " checked")}},
                "Finished.",
            ]
            Backend.script[feature + "-review-1"] = ["NO_FINDINGS"]
        Backend.script[stopped_feature + "-review-1"] = [(settle, 0)]
        benchmark = self.benchmark()
        benchmark["checks"] = [check_command({"one": 2, "two": 1}, "assembly checked")]
        before_evaluation = len(self.evaluated())
        result = self.workflow(benchmark=benchmark, name=name, backend=Backend,
                               skip_linearization=preserve,
                               loop_options={"max_feature_raw": 4000, "max_review_raw": 500,
                                             "max_review_seconds": 300})
        return result, Backend.instances[-1], self.evaluated()[before_evaluation:]

    def assert_stopped_unapproved(self, result, backend, evaluated, stopped_feature):
        attempted = ["one"] if stopped_feature == "one" else ["one", "two"]
        self.assertEqual(result["status"], "needs_attention", result.get("error"))
        self.assertEqual(result["execution_status"], "incomplete", result.get("error"))
        self.assertEqual(result["blocked_features"], ["two"] if stopped_feature == "one" else [])
        self.assertTrue(result["usage"]["measurement_complete"])
        self.assertEqual(result["usage"]["unpriced_or_incomplete_turns"], [])
        self.assertEqual(backend.raw_after_settlement - backend.raw_before_settlement, 73)
        self.assertEqual(sum(item["observed_raw_tokens"] for item in result["checkpoints"]),
                         result["usage"]["observed_raw_tokens"])
        checkpoints = {item["feature"]: item for item in result["checkpoints"]}
        self.assertEqual(list(checkpoints), attempted)
        stopped = checkpoints[stopped_feature]
        self.assertEqual(stopped["status"], "needs_attention")
        self.assertIsNone(stopped["review_approved"])
        self.assertIsNone(stopped["reviewed_head"])
        self.assertEqual(stopped["stop_reason"], "review_time_limit")
        self.assertFalse(any(item["feature"] == stopped_feature for item in result["reviews"]))
        flag, = result["loop_flags"]
        self.assertEqual(flag["reason"], "review_time_limit")
        self.assertEqual(flag["limit"], 300)
        self.assertEqual(flag["observed"], 300.125)
        self.assertEqual(flag["review"]["status"], "stopped")
        self.assertIsNone(flag["review_approved"])
        self.assertNotIn("continuation", flag)
        self.assertEqual(flag["retention"]["commit"], stopped["head"])
        self.assertEqual(json.loads(Path(flag["artifact"]).read_text()), flag)
        labels = [label for label, *_ in backend.calls]
        self.assertEqual(labels.count(stopped_feature + "-review-1"), 1)
        self.assertEqual(labels[-1], stopped_feature + "-review-1")
        self.assertFalse(any("-fix-" in label or label.startswith("integration-") for label in labels))
        self.assertIsNotNone(work_limit_error(backend.expired_limits, backend.raw))
        self.assertEqual(backend.work_limits, [])
        for _, _, prompt, _ in backend.calls:
            self.assertNotIn("EVALUATOR_SECRET", prompt)

        report = result["slopcodebench"]
        self.assertEqual(report["status"], "incomplete", report)
        self.assertIsNone(report["all_tests_passed"])
        self.assertFalse(report["solved"])
        self.assertIsNone(report["final"])
        self.assertEqual([item["checkpoint"] for item in evaluated], attempted)
        for item in report["checkpoints"]:
            if item["feature"] not in attempted:
                self.assertEqual(item, {"feature": "two", "status": "not_run"})
                continue
            self.assertEqual(item["status"], "passed", item)
            saved = Path(item["snapshot"])
            self.assertEqual((saved / "one.py").read_text(), "value = 2\n")
            if item["feature"] != "one":
                self.assertEqual((saved / "two.py").read_text(), "value = 1\n")
            if item["feature"] == stopped_feature:
                self.assertIsNone(item["review_approved"])
                self.assertEqual(item["attempt_status"], "needs_attention")
                self.assertEqual(item["commit"], stopped["head"])
        self.assertNotIn("final_commits", result)
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")
        self.assertEqual(result["checks"], [])
        self.assertFalse((Path(result["output"]) / "check-01").exists())
        for feature in attempted:
            receipts = list((Path(result["output"]) / (feature + "-host")).glob("tools/call-*/result.json"))
            self.assertEqual(len(receipts), 2, "real host edit and check must both execute")
        self.assertEqual(json.loads((Path(result["output"]) / "result.json").read_text()), result)

    def test_final_checkpoint_timed_review_is_graded_but_blocks_assembly(self):
        for preserve in (False, True):
            with self.subTest(preserve_history=preserve):
                result, backend, evaluated = self.execute(preserve=preserve, name=f"final-{preserve}")
                self.assert_stopped_unapproved(result, backend, evaluated, "two")
                self.assertEqual(Path(backend.settled_turn["reply_file"]).read_text(), "NO_FINDINGS")

    def test_priced_interrupted_review_blocks_next_feature(self):
        result, backend, evaluated = self.execute("one", verdict="")
        self.assert_stopped_unapproved(result, backend, evaluated, "one")
        self.assertFalse(any(label.startswith("two-") for label, *_ in backend.calls))
        self.assertFalse((backend.repo / "two.py").exists())

    def test_missing_settlement_receipt_blocks_final_capture_and_integration(self):
        result, backend, evaluated = self.execute(complete=False, verdict="")
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("incomplete token measurement", result["error"])
        self.assertFalse(result["usage"]["measurement_complete"])
        self.assertEqual(backend.raw_after_settlement, backend.raw_before_settlement)
        self.assertEqual(len(result["usage"]["unpriced_or_incomplete_turns"]), 1)
        self.assertEqual([item["feature"] for item in result["checkpoints"]], ["one"])
        self.assertNotIn("retention", result["loop_flags"][0])
        self.assertEqual(result["slopcodebench"]["status"], "incomplete")
        self.assertIsNone(result["slopcodebench"]["final"])
        self.assertEqual([item["checkpoint"] for item in evaluated], ["one"])
        self.assertFalse(any(label.startswith("integration-") for label, *_ in backend.calls))
        self.assertEqual(result["checks"], [])
        self.assertEqual((backend.repo / "two.py").read_text(), "value = 1\n")
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")
