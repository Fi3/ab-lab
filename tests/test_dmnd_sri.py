"""Check source capture, independent grading, and failure propagation."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import dmnd_sri as sri
from lab.config import FACTORS, load_benchmark
from lab.host import git
from lab.setup import ensure_benchmark
from lab.workflow import run
from test_core import repo_at
from test_evaluation import NativeAuthor


class SriLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = repo_at(self.root / "repo")
        self.base = git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.enterContext(patch.object(sri, "BASE", self.base))
        self.config = {"name": "sri-fixture", "repo": str(self.repo), "revision": self.base,
                       "features": [{"id": "new-sri", "request": "Create new-sri.py."}],
                       "checks": ["test -f new-sri.py"], "dmnd_sri": {}}
        self.path = self.root / "benchmark.json"
        self.path.write_text(json.dumps(self.config))

    def execute(self, verdict):
        output = self.root / "run"

        def grade(item, folder, config, references):
            self.assertTrue((output / "provider-closed").exists())
            self.assertEqual(git(item["repo"], "rev-parse", "HEAD").decode().strip(), item["commit"])
            self.assertEqual(git(item["repo"], "remote"), b"")
            self.assertEqual(git(item["repo"], "show", item["commit"] + ":new-sri.py"), b"value = 1\n")
            return {"schema": sri.VERSION, "submission": item, "errors": [], **verdict}

        with patch.object(sri, "load_references", return_value={}), \
                patch.object(sri, "runtime_identity", return_value={"Version": "fixture"}), \
                patch.object(sri, "grade_submission", side_effect=grade) as grader:
            result = run(load_benchmark(self.path), dict.fromkeys(FACTORS, False), output,
                         30, 10_000, 30, backend=NativeAuthor, max_review_loops=0,
                         loop_options={"enabled": False}, preset="native")
        self.assertEqual(grader.call_count, 1, "Identical checkpoint and final commits share one grade")
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertEqual(json.loads((output / "result.json").read_text()), result)
        return result

    def test_verified_submission_passes_after_provider_shutdown(self):
        result = self.execute({"status": "completed", "passed": True})
        self.assertEqual(result["status"], "passed", result)
        self.assertIs(result["evaluation"]["passed"], True)

    def test_green_public_check_does_not_override_runtime_failure(self):
        result = self.execute({"status": "completed", "passed": False})
        self.assertEqual(result["status"], "failed", result)
        self.assertIs(result["evaluation"]["passed"], False)

    def test_grader_error_cannot_claim_a_verdict(self):
        result = self.execute({"status": "error", "passed": None})
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["evaluation"]["status"], "error")
        self.assertIsNone(result["evaluation"]["passed"])

    def test_stopped_checkpoint_does_not_claim_complete_success(self):
        output = self.root / "stopped"
        output.mkdir()
        result = {"dmnd_sri": {"checkpoints": [{"feature": "new-sri", "commit": self.base}],
                               "final": None}}
        evaluator = sri.Evaluator(self.config, output, result)
        evaluator.references = {}
        with patch.object(sri, "grade_submission", return_value={"status": "completed", "passed": True}):
            verdict = evaluator.evaluate()
        self.assertEqual(verdict["status"], "incomplete")
        self.assertIsNone(verdict["passed"])

    def test_setup_uses_the_definition_repository(self):
        with patch("benchmarks.dmnd_sri_prepare.prepare") as prepare:
            ensure_benchmark(self.path)
        prepare.assert_called_once_with(repo=self.repo)

    def test_relative_prepared_path_is_resolved_before_git_reads(self):
        relative = Path(".benchmarks/dmnd-new-sri/repo")
        with patch.object(sri, "dependency_sources", return_value={}) as sources, \
                patch.object(sri, "load_setup", return_value={"references": {}}) as load:
            self.assertEqual(sri.load_references(relative), {})
        sources.assert_called_once_with(relative.resolve())
        load.assert_called_once_with(relative.resolve().parent / "setup.json", {})

    def test_invalid_setup_does_not_download_sources(self):
        self.path.write_text(json.dumps({**self.config, "revision": "HEAD"}))
        with patch("benchmarks.dmnd_sri_prepare.prepare") as prepare, self.assertRaises(ValueError):
            ensure_benchmark(self.path)
        prepare.assert_not_called()

    def test_invalid_base_feature_or_time_budget_is_rejected(self):
        for changes in ({"revision": "HEAD"}, {"features": []},
                        {"dmnd_sri": {"run_seconds": 0}}, {"dmnd_sri": {"build_seconds": True}},
                        {"dmnd_sri": {"unknown": 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sri.Evaluator.expand({**self.config, **changes}, self.path)


class SriDockerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.item = {"repo": str(self.root / "repo"), "commit": "a" * 40, "tree": "b" * 40}
        self.config = {"build_seconds": 60, "run_seconds": 60}

    def receipt(self, code=0, timeout=False):
        return {"exit_code": code, "timed_out": timeout, "cancelled_signal": None}

    def test_metadata_instrumentation_preserves_commands_and_valid_continuation(self):
        path = self.root / "Dockerfile"
        original = "FROM rust AS builder\nRUN true \\\n    && strip /out/mining-e2e /out/dmnd-client\nFROM debian\nENTRYPOINT [\"mining-e2e\"]\n"
        path.write_text(original)
        sri.instrument_metadata(path)
        changed = path.read_text()
        self.assertNotIn("\n+", changed)
        self.assertIn("/out/cargo-metadata.json " + chr(92) + "\n    && cargo metadata", changed)
        self.assertIn("--features mining-e2e > /out/cargo-mining-metadata.json", changed)
        self.assertIn('ENTRYPOINT ["mining-e2e"]', changed)
        self.assertEqual(changed.count("cargo metadata"), 2)

    def test_build_cache_is_separate_for_each_source_tree(self):
        path = self.root / "Dockerfile"
        path.write_text("RUN --mount=type=cache,target=/workspace/target,sharing=locked true "
                        + chr(92) + "\n    && strip /out/mining-e2e /out/dmnd-client\n")
        sri.instrument_metadata(path, "a" * 40)
        self.assertIn("id=dmnd-sri-" + "a" * 40 + ",target=/workspace/target", path.read_text())

    def test_build_failure_stops_before_container_run(self):
        with patch.object(sri, "source_context", return_value={}), \
                patch.object(sri, "checked_process", return_value=self.receipt(1)), \
                patch.object(sri, "run_mining") as mining, \
                patch.object(sri, "cleanup_container"):
            report = sri.grade_submission(self.item, self.root / "evaluation", self.config, {})
        mining.assert_not_called()
        self.assertEqual(report["status"], "completed")
        self.assertIs(report["passed"], False)

    def test_timeout_does_not_report_a_completed_test_failure(self):
        with patch.object(sri, "source_context", return_value={}), \
                patch.object(sri, "checked_process", return_value=self.receipt(137, True)), \
                patch.object(sri, "cleanup_container"):
            report = sri.grade_submission(self.item, self.root / "evaluation", self.config, {})
        self.assertEqual(report["status"], "error")
        self.assertIsNone(report["passed"])

    def test_changed_tests_fail_before_docker_build(self):
        with patch.object(sri, "source_context", side_effect=ValueError("The pinned mining tests changed")), \
                patch.object(sri, "checked_process") as process, \
                patch.object(sri, "cleanup_container"):
            report = sri.grade_submission(self.item, self.root / "evaluation", self.config, {})
        process.assert_not_called()
        self.assertIs(report["passed"], False)
        self.assertEqual(json.loads((self.root / "evaluation/result.json").read_text()), report)

    def test_successful_exit_with_runtime_error_is_rejected(self):
        folder = self.root / "evaluation"

        def process(argv, cwd, output, name, seconds):
            if name in ("metadata", "mining-metadata"):
                (output / (name + ".stdout.txt")).write_text("{}")
            return self.receipt()

        with patch.object(sri, "source_context", return_value={}), patch.object(sri, "checked_process", side_effect=process), \
                patch.object(sri, "audit_dependencies", return_value={"passed": True, "errors": []}), \
                patch.object(sri, "run_performance", return_value=(self.receipt(), {"passed": True, "errors": []})), \
                patch.object(sri, "run_mining", return_value=(self.receipt(), {
                    "passed": False, "errors": ["worker panicked"]})), \
                patch.object(sri, "cleanup_container"):
            report = sri.grade_submission(self.item, folder, self.config, {})
        self.assertIs(report["passed"], False)
        self.assertIn("worker panicked", report["errors"])

    def test_test_feature_cannot_hide_an_old_production_dependency(self):
        good = {"passed": True, "errors": []}
        bad = {"passed": False, "errors": ["old SRI enabled by mining-e2e"]}
        with patch.object(sri, "source_context", return_value={}), \
                patch.object(sri, "checked_process", return_value=self.receipt()), \
                patch.object(sri, "check_dependencies", side_effect=[good, bad]) as audit, \
                patch.object(sri, "run_mining", return_value=(self.receipt(), good)), \
                patch.object(sri, "run_performance", return_value=(self.receipt(), good)), \
                patch.object(sri, "cleanup_container"):
            report = sri.grade_submission(self.item, self.root / "evaluation", self.config, {})
        self.assertEqual(audit.call_count, 2)
        self.assertTrue(audit.call_args.kwargs["mining"])
        self.assertIs(report["passed"], False)
        self.assertIn("old SRI enabled by mining-e2e", report["errors"])

    def test_cleanup_attempts_all_owned_resources_after_one_error(self):
        with patch.object(sri, "cleanup_container", side_effect=[RuntimeError("probe failed"), None]) as containers, \
                patch.object(sri, "checked_process", return_value=self.receipt()) as image:
            errors = sri.cleanup_evaluation("owned", "owned:tag", True, self.root)
        self.assertEqual(containers.call_count, 2)
        image.assert_called_once()
        self.assertEqual(errors, ["probe failed"])

    def test_standalone_preparation_error_returns_two_and_saves_failure(self):
        output = self.root / "run"
        with patch.object(sri, "load_references", side_effect=ValueError("invalid preparation")), \
                patch.object(sri, "capture") as capture, contextlib.redirect_stdout(io.StringIO()):
            code = sri.main([str(self.root), "HEAD", "--out", str(output)])
        capture.assert_not_called()
        self.assertEqual(code, 2)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["status"], "error")
        self.assertIsNone(report["passed"])


if __name__ == "__main__":
    unittest.main()
