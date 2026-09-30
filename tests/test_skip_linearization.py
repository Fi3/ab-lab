"""Optional history cleanup must not weaken reviews or final validation."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.batch import run_batch, worker
from lab.config import settings
from lab.host import git
from lab.workflow import run
from test_batch import worker_at
from test_scb import benchmark_at, checker_at, PHASES
from test_workflow import FakeCodex


class PreserveCommits(FakeCodex):
    def turn(self, thread, prompt, label, **kwargs):
        if label == "integration-accept":
            self.calls.append((label, thread, prompt, kwargs))
            (self.repo / "README.md").write_text("Both features are documented.\n")
            git(self.repo, "add", "README.md")
            git(self.repo, "commit", "-qm", "ADD required feature documentation")
            return "Documentation and checks complete; reviewed commits preserved."
        return super().turn(thread, prompt, label, **kwargs)


class SkipLinearizationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.benchmark = benchmark_at(self.root)

    def run_workflow(self, name="run", backend=PreserveCommits, skip=True):
        return run(self.benchmark, settings({}), self.root / name, 30, 10000, 30,
                   backend=backend, skip_linearization=skip,
                   scb_check=checker_at(self.root))

    def test_preserves_reviewed_commits_and_keeps_docs_checks_and_measurements(self):
        result = self.run_workflow()
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["skip_linearization"])
        checkout = self.root / "run/checkout"
        reviewed = result["checkpoints"][-1]["reviewed_head"]
        git(checkout, "merge-base", "--is-ancestor", reviewed, "HEAD")
        self.assertEqual(len(result["final_commits"]), 4)  # two edits, review repair, docs
        self.assertTrue((checkout / "README.md").exists())
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertTrue(all(result["scb_check"]["measurements"][p]["status"] == "completed"
                            for p in PHASES))
        manifest = json.loads((self.root / "run/manifest.json").read_text())
        self.assertTrue(manifest["skip_linearization"])
        for label, _, prompt, _ in PreserveCommits.instances[-1].calls:
            if label.startswith("integration-"):
                self.assertIn("Do not reorder, squash, amend, rebase or replace", prompt)
                self.assertNotIn("exactly 2 final commits", prompt)

    def test_rewriting_reviewed_history_still_fails(self):
        result = self.run_workflow(backend=FakeCodex)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("preserve reviewed commits", result["error"])

    def test_failed_final_checks_still_fail(self):
        self.benchmark["checks"] = ["false"]
        result = self.run_workflow()
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("final check 1 failed", result["error"])

    def test_already_satisfied_features_need_no_empty_commits(self):
        class AlreadySatisfied(FakeCodex):
            def turn(self, thread, prompt, label, **kwargs):
                if label.endswith("-implement"):
                    return "Finished."
                if "-review-" in label:
                    return "NO_FINDINGS"
                return "No documentation or repairs needed."

        self.benchmark["checks"] = ["true"]
        result = self.run_workflow(backend=AlreadySatisfied)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["final_commits"], [])
        self.assertTrue(all(c["already_satisfied"] for c in result["checkpoints"]))


    def test_default_still_linearizes_and_has_distinct_comparison_key(self):
        normal = self.run_workflow("normal", backend=FakeCodex, skip=False)
        skipped = self.run_workflow("skipped")
        self.assertEqual(normal["status"], "passed", normal)
        self.assertEqual(len(normal["final_commits"]), 2)
        self.assertFalse(normal["skip_linearization"])
        self.assertNotEqual(normal["comparison_key"], skipped["comparison_key"])

    def test_cli_supports_plan_single_and_parallel_with_either_harness(self):
        path = self.root / "benchmark.json"
        path.write_text(json.dumps(self.benchmark))
        common = [str(path), "--skip-linearization", "--off", "C08,C16,C17"]
        output = io.StringIO()
        with patch.object(sys, "argv", ["lab", "plan", *common]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertTrue(json.loads(output.getvalue())["skip_linearization"])
        for harness in ("codex", "pi"):
            for parallel in (1, 3):
                with self.subTest(harness=harness, parallel=parallel):
                    target = "run" if parallel == 1 else "run_batch"
                    args = ["lab", "run", *common, "--harness", harness,
                            "--parallel", str(parallel), "--out", str(self.root / "out"),
                            "--seconds", "30", "--max-raw", "10000", "--max-turns", "30"]
                    with patch("lab.__main__." + target, return_value={"status": "passed"}) as launch:
                        with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(main(), 0)
                    self.assertTrue(launch.call_args.kwargs["skip_linearization"])
                    self.assertEqual({k for k, v in launch.call_args.args[1].items() if v},
                                     {"C13", "C14", "C15", "C20", "C38"})

    def test_batch_persists_and_worker_forwards_option(self):
        result = run_batch(self.benchmark, settings({}), self.root / "batch", 2, 2,
            seconds=30, max_raw=10000, max_turns=30, skip_linearization=True,
            _worker_command=worker_at(self.root))
        self.assertTrue(result["skip_linearization"])
        config_path = self.root / "batch/batch-input.json"
        config = json.loads(config_path.read_text())
        self.assertTrue(config["options"]["skip_linearization"])
        with patch("lab.batch.run", return_value={"status": "passed"}) as launch:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(worker(config_path, self.root / "worker"), 0)
        self.assertTrue(launch.call_args.kwargs["skip_linearization"])


if __name__ == "__main__":
    unittest.main()
