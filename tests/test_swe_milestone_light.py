"""Reduced SWE-Milestone definitions preserve the selected prefix end to end."""
import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmarks import swe_milestone as sm
from lab.config import FACTORS, load_benchmark
from lab.workflow import run as run_workflow
from test_evaluation import NativeAuthor
import test_swe_milestone as fixtures


class LightMilestoneTests(unittest.TestCase):
    setUp = fixtures.MilestoneTests.setUp
    dataset = fixtures.MilestoneTests.dataset
    repo = fixtures.MilestoneTests.repo
    commit = fixtures.MilestoneTests.commit
    records = fixtures.MilestoneTests.records
    automatic_fixture = fixtures.MilestoneTests.automatic_fixture

    def test_committed_light_definition_changes_only_name_and_feature_prefix(self):
        folder = sm.ROOT / "benchmarks"
        full = json.loads((folder / "swe-milestone-scikit-learn.json").read_text())
        light = json.loads((folder / "swe-milestone-scikit-learn-light.json").read_text())
        expected = {**full, "name": "swe-milestone-scikit-learn-light-" + sm.VERSION,
                    "features": full["features"][:3]}
        self.assertEqual(light, expected)
        self.assertEqual([row["id"] for row in light["features"]], ["M06", "M11", "M12_1"])
        light["repo"] = str(self.root)
        path = self.root / "light.json"
        sm.write_json(path, light)
        loaded = load_benchmark(path)
        self.assertEqual(loaded["features"], expected["features"])
        self.assertEqual(loaded["swe_milestone"], full["swe_milestone"])

    def test_scope_accepts_full_and_prefix_without_changing_prepared_metadata(self):
        self.dataset()
        tasks = sm.milestones(self.workspace)
        imported = {"milestones": tasks, "revision": "base", "pins": sm.PINS}
        expected = {"name": "full", "revision": "base",
                    "features": [{"id": task["id"], "request": task["request"]} for task in tasks]}
        original = copy.deepcopy(imported)
        for count in (1, 2, 3):
            with self.subTest(count=count):
                light = {**expected, "name": "light", "features": expected["features"][:count]}
                scoped = sm.benchmark_scope(imported, expected, light)
                self.assertEqual(scoped["milestones"], tasks[:count])
                self.assertEqual(scoped["revision"], imported["revision"])
                self.assertEqual(scoped["pins"], imported["pins"])
                self.assertIsNot(scoped, imported)
        self.assertEqual(imported, original)

    def test_scope_rejects_changed_or_nonprefix_tasks(self):
        self.dataset()
        tasks = sm.milestones(self.workspace)
        features = [{"id": task["id"], "request": task["request"]} for task in tasks]
        imported = {"milestones": tasks, "revision": "base"}
        expected = {"name": "full", "revision": "base", "features": features}
        cases = {
            "empty": [],
            "skipped_first": features[1:],
            "skipped_middle": [features[0], features[2]],
            "reordered": [features[1], features[0]],
            "duplicated": [features[0], features[0]],
            "modified_request": [{**features[0], "request": features[0]["request"] + "extra"}],
            "modified_id": [{**features[0], "id": "other"}],
            "too_long": features + [features[0]],
        }
        for name, selected in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                sm.benchmark_scope(imported, expected, {**expected, "features": selected})
        with self.assertRaises(ValueError):
            sm.benchmark_scope(imported, expected, {**expected, "revision": "different"})

    def test_light_workflow_grades_only_selected_checkpoint_and_final(self):
        evaluator, _, tasks = self.automatic_fixture()
        benchmark = {**evaluator.benchmark, "name": "example-light",
                     "features": evaluator.benchmark["features"][:1]}
        output = self.root / "light-run"
        prepared_import = self.root / "prepared" / "import.json"
        original_import = prepared_import.read_bytes()
        graded = []

        def grade(repo, commit, imported, prepared, folder, seconds):
            self.assertTrue((output / "provider-closed").exists())
            self.assertEqual([task["id"] for task in imported["milestones"]], ["a"])
            self.assertEqual(folder.name, "a")
            self.assertEqual(sm.git(repo, "show", commit + ":a.py"), b"value = 1\n")
            graded.append(commit)
            return {"status": "passed", "resolved": True}

        def child(argv, cwd, stdin, stdout, stderr, seconds, env):
            Path(stdout).write_text("{}")
            Path(stderr).write_text("")
            code = 0
            if "evaluate" in argv:
                self.assertEqual(seconds, 2 * 5 + 60)
                with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                        patch.object(sm, "grade", side_effect=grade):
                    code = sm.evaluate("example", output, None, None, 5, None)
            return {"argv": argv, "exit_code": code, "timed_out": False, "cancelled_signal": None}

        with patch("benchmarks.swe_milestone_evaluator.execute_child", side_effect=child), \
                contextlib.redirect_stdout(io.StringIO()):
            result = run_workflow(benchmark, dict.fromkeys(FACTORS, False), output,
                                  30, 10000, 30, backend=NativeAuthor, max_review_loops=0,
                                  loop_options={"enabled": False}, preset="native")
        self.assertEqual(result["status"], "passed", result)
        report = result["swe_milestone"]
        self.assertEqual((report["status"], report["passed"], report["total"], report["solved"]),
                         ("completed", 1, 1, True))
        self.assertEqual((report["final"]["passed"], report["final"]["total"]), (1, 1))
        self.assertEqual([row["id"] for row in report["milestones"]], ["a"])
        self.assertEqual([row["milestone"] for row in report["final"]["milestones"]], ["a"])
        self.assertEqual(graded, [result["checkpoints"][0]["head"]])
        self.assertEqual(len(NativeAuthor.instances[-1].calls), 1)
        scoped = json.loads((output / "swe-milestone" / "import.json").read_text())
        self.assertEqual([row["id"] for row in scoped["milestones"]], ["a"])
        self.assertEqual(prepared_import.read_bytes(), original_import)
        self.assertEqual([task["id"] for task in tasks], ["a", "b"])

    def test_unreached_selected_checkpoint_remains_in_light_denominator(self):
        repo, full, tasks, (base, first, _) = self.records()
        extra = {"id": "c", "milestone": "c", "request": "Additional task", "graded": True}
        full = {**full, "features": full["features"] + [{"id": "c", "request": extra["request"]}]}
        imported = {"milestones": tasks + [extra], "revision": base, "version": sm.VERSION}
        light = {**full, "name": "example-light", "features": full["features"][:2]}
        sm.write_json(repo.parent / "manifest.json", {"benchmark": light})
        sm.write_json(repo.parent / "result.json", {"benchmark": light["name"], "status": "failed"})
        (repo.parent / "b-result.json").unlink()
        prepared = self.root / "prepared"
        prepared.mkdir()
        sm.write_json(prepared / "import.json", imported)
        original_import = (prepared / "import.json").read_bytes()
        output = self.root / "grading"
        with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                patch.object(sm, "load_prepared", return_value=(prepared, imported, full)), \
                patch.object(sm, "grade", return_value={"status": "passed", "resolved": True}) as grader, \
                contextlib.redirect_stdout(io.StringIO()):
            status = sm.evaluate("example", repo.parent, output, None, 60, None)
        self.assertEqual(status, 2)
        self.assertEqual(grader.call_args.args[1], first)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual((report["passed"], report["total"], report["solved"]), (1, 2, False))
        self.assertEqual([row["id"] for row in report["milestones"]], ["a", "b"])
        self.assertEqual(report["milestones"][1]["status"], "not_run")
        self.assertEqual(report["final"]["total"], 2)
        self.assertEqual((prepared / "import.json").read_bytes(), original_import)
        scoped = json.loads((output / "import.json").read_text())
        self.assertEqual([row["id"] for row in scoped["milestones"]], ["a", "b"])
