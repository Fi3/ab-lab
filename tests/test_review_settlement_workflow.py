"""A priced, stopped review must remain unapproved through SCB assembly.

Provider timing/receipts are scripted here; transport receipt ownership is
covered by test_review_settlement. Host operations, Git commits, final checks,
snapshot capture, and the existing subprocess evaluator fixture all run.
"""
import json
from pathlib import Path
import shlex
import sys
import time
import unittest

from lab.host import git, save_json
from lab.loops import ReviewConclusionRequested, WorkLimitReached, work_limit_error
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
            # Advance this review's timer only. Keep it expired after raising:
            # a stale limit would stop the next stage's real workflow precheck.
            now = time.monotonic()
            limit = next(item for item in backend.work_limits
                         if item["reason"] == "review_wrapup_time_limit")
            limit["start"] = now - limit["limit"] - 0.125
            stopped = work_limit_error(backend.work_limits, backend.raw, now=now)
            self.assertIsInstance(stopped, WorkLimitReached)
            self.assertNotIsInstance(stopped, ReviewConclusionRequested)
            self.assertEqual(stopped.signal["reason"], "review_wrapup_time_limit")
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
                "label": stopped_feature + "-review-1-conclude",
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
                "@standalone run -- " + check_command({feature: value}, feature + " checked"),
                "@standalone done",
            ]
            Backend.script[feature + "-review-1"] = ["NO_FINDINGS"]
        Backend.script[stopped_feature + "-review-1"] = [
            ("Review exploration reached its threshold without a verdict.", 100)]
        Backend.script[stopped_feature + "-review-1-conclude"] = [(settle, 0)]
        benchmark = self.benchmark()
        benchmark["checks"] = [check_command({"one": 2, "two": 1}, "assembly checked")]
        before_evaluation = len(self.evaluated())
        result = self.workflow(benchmark=benchmark, name=name, backend=Backend,
                               skip_linearization=preserve,
                               loop_options={"max_feature_raw": 4000, "max_review_raw": 100,
                                             "max_review_wrapup_raw": 500})
        return result, Backend.instances[-1], self.evaluated()[before_evaluation:]

    def assert_completed_unapproved(self, result, backend, evaluated, stopped_feature):
        self.assertEqual(result["status"], "needs_attention", result.get("error"))
        self.assertEqual(result["execution_status"], "completed", result.get("error"))
        self.assertEqual(result["attention_features"], [stopped_feature])
        self.assertEqual(result["blocked_features"], [])
        self.assertTrue(result["usage"]["measurement_complete"])
        self.assertEqual(result["usage"]["unpriced_or_incomplete_turns"], [])
        self.assertEqual(backend.raw_after_settlement - backend.raw_before_settlement, 73)
        self.assertEqual(sum(item["observed_raw_tokens"] for item in result["checkpoints"]),
                         result["usage"]["observed_raw_tokens"])
        checkpoints = {item["feature"]: item for item in result["checkpoints"]}
        stopped = checkpoints[stopped_feature]
        self.assertEqual(stopped["status"], "needs_attention")
        self.assertIsNone(stopped["review_approved"])
        self.assertIsNone(stopped["reviewed_head"])
        self.assertEqual(stopped["stop_reason"], "review_wrapup_time_limit")
        self.assertFalse(any(item["feature"] == stopped_feature for item in result["reviews"]))
        flag, = result["loop_flags"]
        self.assertEqual(flag["reason"], "review_wrapup_time_limit")
        self.assertEqual(flag["limit"], 90)
        self.assertEqual(flag["observed"], 90.125)
        self.assertEqual(flag["review"]["status"], "stopped")
        self.assertIsNone(flag["review_approved"])
        self.assertEqual(flag["continuation"]["status"], "continued")
        self.assertEqual(flag["continuation"]["commit"], stopped["head"])
        self.assertEqual(json.loads(Path(flag["artifact"]).read_text()), flag)
        wrapup, = result["review_wrapups"]
        self.assertEqual(wrapup["status"], "stopped")
        self.assertFalse(wrapup["used_completed_verdict"])
        self.assertEqual(wrapup["stop"], backend.settled_turn["work_limit"])
        self.assertEqual(wrapup["raw_tokens_after_conclusion"], backend.raw_after_settlement)
        wrapup_path = Path(result["output"]) / (stopped_feature + "-review-1-wrapup.json")
        self.assertEqual(json.loads(wrapup_path.read_text()), wrapup)

        labels = [label for label, *_ in backend.calls]
        self.assertEqual(labels.count(stopped_feature + "-review-1-conclude"), 1)
        self.assertFalse(any("-fix-" in label for label in labels))
        self.assertEqual(labels[-2:], ["integration-plan", "integration-accept"])
        threads = {label: thread for label, thread, *_ in backend.calls}
        self.assertEqual(threads[stopped_feature + "-review-1"],
                         threads[stopped_feature + "-review-1-conclude"])
        self.assertEqual(threads["integration-plan"], threads["integration-accept"])
        self.assertIsNotNone(work_limit_error(backend.expired_limits, backend.raw))
        self.assertEqual(backend.work_limits, [])
        self.assertTrue(all(not limits for label, limits in backend.limits_by_call
                            if label.startswith("integration-")))
        for label, _, prompt, _ in backend.calls:
            self.assertNotIn("EVALUATOR_SECRET", prompt)
            if label.startswith("integration-"):
                self.assertIn("Do not restart those stopped review/repair loops", prompt)

        report = result["slopcodebench"]
        self.assertEqual(report["status"], "completed", report)
        self.assertTrue(report["all_tests_passed"])
        self.assertFalse(report["solved"])
        self.assertEqual([item["checkpoint"] for item in evaluated], ["one", "two", "two"])
        for item in [*report["checkpoints"], report["final"]]:
            self.assertEqual(item["status"], "passed", item)
            saved = Path(item["snapshot"])
            self.assertEqual((saved / "one.py").read_text(), "value = 2\n")
            if item["feature"] != "one":
                self.assertEqual((saved / "two.py").read_text(), "value = 1\n")
            if item["feature"] == stopped_feature:
                self.assertIsNone(item["review_approved"])
                self.assertEqual(item["attempt_status"], "needs_attention")
                self.assertEqual(item["commit"], stopped["head"])
        self.assertEqual(len(result["final_commits"]), 2)
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertEqual((Path(result["output"]) / "check-01/stdout.txt").read_text(),
                         "assembly checked\n")
        for feature in ("one", "two"):
            receipts = list((Path(result["output"]) / (feature + "-host")).glob("operation-*/receipt.json"))
            self.assertEqual(len(receipts), 2, "real host edit and check must both execute")
        self.assertEqual(json.loads((Path(result["output"]) / "result.json").read_text()), result)

    def test_final_checkpoint_timed_conclusion_is_graded_and_assembled_without_approval(self):
        for preserve in (False, True):
            with self.subTest(preserve_history=preserve):
                result, backend, evaluated = self.execute(preserve=preserve, name=f"final-{preserve}")
                self.assert_completed_unapproved(result, backend, evaluated, "two")
                self.assertEqual(Path(backend.settled_turn["reply_file"]).read_text(), "NO_FINDINGS")

    def test_priced_interrupted_review_continues_with_next_feature_and_fresh_limits(self):
        result, backend, evaluated = self.execute("one", verdict="")
        self.assert_completed_unapproved(result, backend, evaluated, "one")
        limits = next(limits for label, limits in backend.limits_by_call if label == "two-implement")
        self.assertEqual(limits[0]["start"], backend.raw_after_settlement)
        later = next(prompt for label, _, prompt, _ in backend.calls if label == "two-implement")
        self.assertIn("review_wrapup_time_limit", later)
        self.assertIn("they were not approved", later)

    def test_missing_settlement_receipt_blocks_final_capture_and_integration(self):
        result, backend, evaluated = self.execute(complete=False, verdict="")
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("incomplete token measurement", result["error"])
        self.assertFalse(result["usage"]["measurement_complete"])
        self.assertEqual(backend.raw_after_settlement, backend.raw_before_settlement)
        self.assertEqual(len(result["usage"]["unpriced_or_incomplete_turns"]), 1)
        self.assertEqual([item["feature"] for item in result["checkpoints"]], ["one"])
        self.assertEqual(result["review_wrapups"][0]["status"], "stopped")
        self.assertNotIn("continuation", result["loop_flags"][0])
        self.assertEqual(result["slopcodebench"]["status"], "incomplete")
        self.assertIsNone(result["slopcodebench"]["final"])
        self.assertEqual([item["checkpoint"] for item in evaluated], ["one"])
        self.assertFalse(any(label.startswith("integration-") for label, *_ in backend.calls))
        self.assertEqual(result["checks"], [])
        self.assertEqual((backend.repo / "two.py").read_text(), "value = 1\n")
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")
