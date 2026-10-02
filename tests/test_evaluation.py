"""Benchmark-owned grading uses the ordinary workflow without model feedback."""
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from benchmarks.evaluators import ADAPTERS
from lab.config import FACTORS, load_benchmark
from lab.evaluation import BaseEvaluator, adapter_type
from lab.host import git
from lab.summary import evaluation_tables, records, render
from lab.workflow import run
from test_core import repo_at
from test_summary import result as summary_result
from test_workflow import FakeCodex


class NativeAuthor(FakeCodex):
    """Exercise actual file capture and public checks, without model calls."""

    def turn(self, thread, prompt, label, **options):
        self.calls.append((label, thread, prompt, options))
        name = label.removesuffix("-implement")
        (self.repo / (name + ".py")).write_text("value = 1\n")
        return "Implemented."

    def close(self):
        (self.artifacts.parent / "provider-closed").touch()


class BenchmarkEvaluationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = repo_at(self.root / "input")
        self.events = []
        self.verdict = {"status": "completed", "passed": True}
        self.evaluation_error = None
        self.before_evaluation = None
        self.published_evaluation = None
        self.config = {"name": "ordinary-project", "repo": str(self.repo), "revision": "HEAD",
                       "features": [{"id": "one", "request": "Create one.py."},
                                    {"id": "two", "request": "Create two.py."}],
                       "checks": ["test -f one.py && test -f two.py"],
                       "fixture_grader": {"target_value": 1}}
        owner = self

        class FixtureEvaluator(BaseEvaluator):
            config_key = "fixture_grader"

            @classmethod
            def expand(cls, data, path):
                owner.events.append(("expand", str(path)))
                return data

            def start(self, base, manifest, deadline):
                owner.events.append(("start", base))

            def checkpoint(self, checkout, checkpoint, quality_tool, deadline):
                owner.events.append(("checkpoint", checkpoint["feature"], checkpoint["head"]))

            def final(self, checkout):
                owner.events.append(("final", git(checkout, "rev-parse", "HEAD").decode().strip()))

            def evaluate(self):
                # The evaluator sees the retained submission only after all
                # model sessions close, including successful native captures.
                owner.assertTrue((self.output / "provider-closed").is_file())
                owner.before_evaluation = json.loads((self.output / "before-evaluation.json").read_text())
                owner.published_evaluation = json.loads((self.output / "result.json").read_text())
                owner.events.append(("evaluate",))
                report = self.output / "fixture-grading.json"
                report.write_text(json.dumps({"evidence": "HIDDEN_GRADER_EVIDENCE",
                    "commits": [item["head"] for item in self.result["checkpoints"]]}))
                if owner.evaluation_error:
                    raise owner.evaluation_error
                if not isinstance(owner.verdict, dict):
                    return owner.verdict
                return {"report_path": str(report), **owner.verdict}

        self.adapter = FixtureEvaluator
        module = ModuleType("test_fixture_grader_plugin")
        module.Evaluator = FixtureEvaluator
        self.enterContext(patch.dict(sys.modules, {module.__name__: module}))
        self.enterContext(patch.dict(ADAPTERS, {"fixture_grader": module.__name__}))

    def execute(self, *, backend=NativeAuthor, benchmark=None, name="run"):
        path = self.root / (name + "-benchmark.json")
        path.write_text(json.dumps(self.config if benchmark is None else benchmark))
        loaded = load_benchmark(path)
        result = run(loaded, dict.fromkeys(FACTORS, False), self.root / name,
                     30, 10_000, 30, backend=backend, max_review_loops=0,
                     loop_options={"enabled": False}, preset="native")
        self.assertEqual(json.loads((self.root / name / "result.json").read_text()), result)
        return result

    def test_registered_benchmark_runs_and_grades_after_provider_shutdown(self):
        result = self.execute()
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["evaluation"]["status"], "completed")
        self.assertIs(result["evaluation"]["passed"], True)
        self.assertEqual([event[0] for event in self.events],
                         ["expand", "start", "checkpoint", "checkpoint", "final", "evaluate"])
        self.assertEqual([event[1] for event in self.events if event[0] == "checkpoint"], ["one", "two"])
        checkpoint_heads = [checkpoint["head"] for checkpoint in result["checkpoints"]]
        self.assertEqual([event[2] for event in self.events if event[0] == "checkpoint"], checkpoint_heads)
        checkout = self.root / "run/checkout"
        self.assertEqual(result["final_submission"]["commit"], checkpoint_heads[-1])
        self.assertEqual(result["final_submission"]["tree"],
                         git(checkout, "rev-parse", "HEAD^{tree}").decode().strip())
        first_tree = git(checkout, "ls-tree", "-r", "--name-only", checkpoint_heads[0]).decode().splitlines()
        self.assertIn("one.py", first_tree)
        self.assertNotIn("two.py", first_tree)
        self.assertEqual(self.before_evaluation["checkpoints"], result["checkpoints"])
        self.assertEqual(self.before_evaluation["final_submission"], result["final_submission"])
        self.assertEqual(self.before_evaluation["status"], "passed")
        self.assertEqual(self.published_evaluation["status"], "failed")
        self.assertEqual(self.published_evaluation["evaluation"]["status"], "incomplete")
        self.assertEqual(self.published_evaluation["evaluation"]["workflow_status"], "passed")
        self.assertIsNone(self.published_evaluation["evaluation"]["passed"])
        self.assertIn("evaluation", self.published_evaluation["error"].lower())
        self.assertNotIn("error", result)
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertTrue(result["usage"]["measurement_complete"])
        self.assertEqual([call[2] for call in NativeAuthor.instances[-1].calls],
                         [feature["request"] for feature in self.config["features"]])
        self.assertIn("HIDDEN_GRADER_EVIDENCE", Path(result["evaluation"]["report_path"]).read_text())
        self.assertFalse((self.repo / "one.py").exists())

    def test_failed_or_unfinished_grading_cannot_report_run_success(self):
        for status, passed in (("completed", False), ("incomplete", None), ("error", None)):
            with self.subTest(status=status, passed=passed):
                self.verdict = {"status": status, "passed": passed}
                result = self.execute(name=status)
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["evaluation"]["status"], status)
                self.assertIs(result["evaluation"]["passed"], passed)
                self.assertEqual(len(result["checkpoints"]), 2)
                self.assertEqual(result["checks"][0]["exit_code"], 0)
                self.assertEqual(len(NativeAuthor.instances[-1].calls), 2)

    def test_malformed_grader_results_fail_closed(self):
        verdicts = [None, [], {"status": "completed", "passed": "true"},
                    {"status": "unknown", "passed": True},
                    {"status": "completed", "passed": True, "report_path": None},
                    {"status": "completed", "passed": True,
                     "report_path": str(self.root / "missing-grader-report.json")}]
        for index, verdict in enumerate(verdicts):
            with self.subTest(verdict=verdict):
                self.verdict = verdict
                result = self.execute(name=f"malformed-{index}")
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["failure"]["origin"], "evaluator")
                self.assertEqual(len(result["checkpoints"]), 2)
                self.assertEqual(result["checks"][0]["exit_code"], 0)

    def test_evaluator_crash_retains_model_submission_and_partial_report(self):
        self.evaluation_error = RuntimeError("fixture grader crashed after writing evidence")
        result = self.execute()
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["failure"]["origin"], "evaluator")
        self.assertIn("fixture grader crashed", result["error"])
        self.assertEqual(self.before_evaluation["status"], "passed")
        self.assertEqual(result["checkpoints"], self.before_evaluation["checkpoints"])
        self.assertEqual(result["usage"], self.before_evaluation["usage"])
        self.assertEqual(result["final_submission"], self.before_evaluation["final_submission"])
        self.assertTrue((self.root / "run/fixture-grading.json").is_file())
        self.assertEqual(len(NativeAuthor.instances[-1].calls), 2)

    def test_evaluator_system_exit_is_a_retained_evaluation_error(self):
        self.evaluation_error = SystemExit("grader exited before returning a verdict")
        result = self.execute()
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["failure"]["origin"], "evaluator")
        self.assertEqual(result["evaluation"]["status"], "error")
        self.assertIn("grader exited", result["error"])
        self.assertEqual(len(result["checkpoints"]), 2)
        self.assertTrue((self.root / "run/fixture-grading.json").is_file())

    def test_abrupt_termination_during_grading_never_leaves_a_success_report(self):
        class ProcessTerminated(BaseException):
            pass

        self.evaluation_error = ProcessTerminated("simulate process termination during grading")
        with self.assertRaises(ProcessTerminated):
            self.execute()
        published = json.loads((self.root / "run/result.json").read_text())
        self.assertEqual(published["status"], "failed")
        self.assertEqual(published["evaluation"]["status"], "incomplete")
        self.assertIsNone(published["evaluation"]["passed"])
        self.assertEqual(published["evaluation"]["workflow_status"], "passed")
        self.assertEqual(published["checkpoints"], self.before_evaluation["checkpoints"])
        self.assertEqual(self.before_evaluation["status"], "passed")

    def test_no_grading_when_provider_shutdown_is_incomplete(self):
        class BrokenClose(NativeAuthor):
            def close(self):
                raise RuntimeError("child sessions still alive")

        result = self.execute(backend=BrokenClose)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("child sessions still alive", result["shutdown_error"])
        self.assertNotIn(("evaluate",), self.events)
        self.assertFalse((self.root / "run/fixture-grading.json").exists())

    def test_no_grading_without_a_completed_checkpoint(self):
        class BrokenAuthor(NativeAuthor):
            def turn(self, *args, **options):
                raise RuntimeError("provider connection lost")

        result = self.execute(backend=BrokenAuthor)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["failure"]["origin"], "provider")
        self.assertEqual(result["checkpoints"], [])
        self.assertNotIn(("evaluate",), self.events)

    def test_operator_interruption_prevents_grading_even_with_an_earlier_checkpoint(self):
        class InterruptedAuthor(NativeAuthor):
            def turn(self, thread, prompt, label, **options):
                if label == "two-implement":
                    raise KeyboardInterrupt("operator requested cancellation")
                return super().turn(thread, prompt, label, **options)

        result = self.execute(backend=InterruptedAuthor)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["failure"]["origin"], "operator")
        self.assertEqual(len(result["checkpoints"]), 1)
        self.assertNotIn(("evaluate",), self.events)

    def test_evaluation_preserves_an_existing_public_check_failure(self):
        benchmark = {**self.config, "checks": ["false"]}
        for name, error in (("graded", None), ("crashed", RuntimeError("grader unavailable"))):
            with self.subTest(name=name):
                self.evaluation_error = error
                result = self.execute(benchmark=benchmark, name=name)
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["failure"]["origin"], "validation")
                self.assertIn("final check 1 failed", result["error"])
                self.assertEqual(result["evaluation"]["status"], "error" if error else "completed")
                self.assertEqual(len(NativeAuthor.instances[-1].calls), 2)

    def test_existing_benchmark_without_evaluator_keeps_public_checks(self):
        benchmark = {key: value for key, value in self.config.items() if key != "fixture_grader"}
        result = self.execute(benchmark=benchmark)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(self.events, [])
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["command"], benchmark["checks"][0])
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertEqual(len(result["checkpoints"]), 2)
        self.assertEqual([call[2] for call in NativeAuthor.instances[-1].calls],
                         [feature["request"] for feature in benchmark["features"]])

    def test_benchmark_extension_selects_its_own_adapter(self):
        self.assertIs(adapter_type(self.config), self.adapter)
        self.assertIs(adapter_type({}), BaseEvaluator)

    def test_ambiguous_evaluators_are_rejected_before_a_run(self):
        benchmark = {**self.config, "second_grader": {}}
        path = self.root / "ambiguous.json"
        path.write_text(json.dumps(benchmark))
        with patch.dict(ADAPTERS, {"second_grader": "test_fixture_grader_plugin"}):
            with self.assertRaisesRegex(ValueError, "only one evaluator"):
                load_benchmark(path)
            with self.assertRaisesRegex(ValueError, "only one evaluator"):
                adapter_type(benchmark)
        self.assertEqual(self.events, [])


class EvaluationSummaryTests(unittest.TestCase):
    @staticmethod
    def cells(line):
        return [value.strip() for value in line.split("|")[1:-1]]

    def test_completed_failed_and_incomplete_verdicts_remain_distinct(self):
        rows = []
        for name, status, passed in (("success", "completed", True),
                                     ("failure", "completed", False),
                                     ("partial", "incomplete", None)):
            row = summary_result(name, status="passed" if passed else "failed")
            row["execution_status"] = "completed"
            row["evaluation"] = {"evaluator": "fixture_grader", "status": status,
                                 "passed": passed, "report_path": f"/runs/{name}/grading.json"}
            rows.append(row)
        rows.append(summary_result("legacy"))
        rendered = render(records(rows))
        self.assertIn("Execution", rendered)
        section = rendered.split("Benchmark evaluation:", 1)[1]
        self.assertNotIn("legacy", section)
        grading_rows = [self.cells(line) for line in section.splitlines() if "fixture_grader" in line]
        self.assertEqual(grading_rows, [
            ["success", "fixture_grader", "completed", "pass", "/runs/success/grading.json"],
            ["failure", "fixture_grader", "completed", "fail", "/runs/failure/grading.json"],
            ["partial", "fixture_grader", "incomplete", "—", "/runs/partial/grading.json"]])

    def test_per_milestone_quality_is_reported_only_for_valid_completed_measurements(self):
        row = {"evaluation": {"evaluator": "fixture_grader", "status": "completed", "passed": False,
            "checkpoints": [
                {"feature": "one", "status": "completed", "passed": True,
                 "quality": {"status": "completed", "report": {
                     "verbosity": 0.25, "erosion": 0.125, "cog_erosion": 0.2}}},
                {"feature": "two", "status": "incomplete", "passed": None,
                 "quality": {"status": "error", "report": {
                     "verbosity": 0, "erosion": 0, "cog_erosion": 0}}},
                {"feature": "three", "status": "completed", "passed": False,
                 "quality": {"status": "completed", "report": {
                     "verbosity": True, "erosion": 1.2, "cog_erosion": float("nan")}}}],
            "final": {"passed": False}}}
        section = "\n".join(evaluation_tables(["example"], [row]))
        checkpoint_rows = [self.cells(line) for line in section.splitlines()
                           if line.startswith("| example") and "fixture_grader" not in line]
        self.assertEqual(checkpoint_rows, [
            ["example", "one", "completed", "pass", "25.00%", "12.50%", "20.00%"],
            ["example", "two", "incomplete", "—", "—", "—", "—"],
            ["example", "three", "completed", "fail", "—", "—", "—"],
            ["example", "Final evaluation", "—", "fail", "—", "—", "—"]])
        self.assertNotIn("nan", section)

    def test_existing_results_without_evaluation_keep_their_summary(self):
        row = summary_result()
        previous = render(records(row))
        self.assertEqual(evaluation_tables(["legacy"], [row]), [])
        self.assertNotIn("Benchmark evaluation:", previous)
        row["evaluation"] = None
        self.assertEqual(render(records(row)), previous)


if __name__ == "__main__":
    unittest.main()
