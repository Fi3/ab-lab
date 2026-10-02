"""The dataset adapter must work with the existing runner contract unchanged."""
import contextlib
import csv
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from benchmarks import swe_milestone as sm
from benchmarks.swe_milestone_evaluator import Evaluator
from lab.config import FACTORS, load_benchmark
from lab.workflow import run as run_workflow
from test_evaluation import NativeAuthor


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "data" / "example"
        self.workspace.mkdir(parents=True)

    def dataset(self, ids=("a", "b", "c"), selected=None, edges=(), additions=(), nongraded=()):
        (self.workspace / "milestones.csv").write_text("id,title\n" + "".join(f"{mid},Title\n" for mid in ids))
        if selected is not None:
            (self.workspace / "selected_milestone_ids.txt").write_text("\n".join(selected))
        (self.workspace / "non-graded_milestone_ids.txt").write_text("\n".join(nongraded))
        for name, rows in (("dependencies.csv", edges), ("additional_dependencies.csv", additions)):
            with (self.workspace / name).open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["source_id", "target_id", "strength"])
                writer.writerow(["# Release comment"])
                writer.writerows(rows)
        for mid in ids:
            path = self.workspace / "srs" / mid / "SRS.md"
            path.parent.mkdir(parents=True)
            path.write_bytes(f"# {mid}\r\n\r\nUpstream task, café.\r\n".encode())

    def repo(self):
        repo = self.root / "run" / "checkout"
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        sm.git(repo, "config", "user.name", "Test")
        sm.git(repo, "config", "user.email", "test@localhost")
        (repo / "source.py").write_text("value = 0\n")
        return repo, self.commit(repo)

    def commit(self, repo):
        sm.git(repo, "add", "-A")
        sm.git(repo, "commit", "-qm", "fixture")
        return sm.git(repo, "rev-parse", "HEAD").decode().strip()

    def records(self):
        self.dataset(ids=("a", "b"))
        repo, base = self.repo()
        (repo / "source.py").write_text("value = 1\n")
        first = self.commit(repo)
        (repo / "source.py").write_text("value = 2\n")
        last = self.commit(repo)
        tasks = sm.milestones(self.workspace)
        benchmark = {"name": "example", "revision": base, "repo": str(repo), "checks": ["python source.py"],
                     "features": [{"id": t["id"], "request": t["request"]} for t in tasks]}
        sm.write_json(repo.parent / "manifest.json", {"benchmark": benchmark})
        sm.write_json(repo.parent / "result.json", {"benchmark": "example", "status": "failed"})
        for task, previous, head in zip(benchmark["features"], (base, first), (first, last)):
            sm.write_json(repo.parent / (task["id"] + "-result.json"),
                          {"feature": task["id"], "request": task["request"], "base": previous, "head": head})
        return repo, benchmark, tasks, (base, first, last)

    def test_curated_subset_additional_edges_and_verbatim_tasks(self):
        self.dataset(selected=("b", "a"), edges=(("a", "b", "Weak"),),
                     additions=(("b", "a", "Strong"), ("c", "a", "Strong")), nongraded=("b",))
        tasks = sm.milestones(self.workspace)
        self.assertEqual([t["id"] for t in tasks], ["b", "a"])
        self.assertEqual([t["graded"] for t in tasks], [False, True])
        self.assertEqual(tasks[0]["request"].encode(), (self.workspace / "srs/b/SRS.md").read_bytes())

    def test_absent_selection_means_all_release_milestones(self):
        self.dataset(edges=(("c", "a", "Strong"),))
        self.assertEqual([t["id"] for t in sm.milestones(self.workspace)], ["b", "c", "a"])

    def test_cycle_cannot_silently_drop_tasks(self):
        self.dataset(edges=(("a", "b", "Strong"), ("b", "a", "Strong")))
        with self.assertRaisesRegex(ValueError, "cycle"):
            sm.milestones(self.workspace)

    def test_id_mapping_preserves_original_evaluator_id(self):
        self.dataset(ids=("M01.2",))
        task = sm.milestones(self.workspace)[0]
        self.assertEqual((task["id"], task["milestone"]), ("M01_2", "M01.2"))

    def test_colliding_ids_are_rejected(self):
        self.dataset(ids=("M01.2", "M01_2"))
        with self.assertRaisesRegex(ValueError, "collide"):
            sm.milestones(self.workspace)

    def test_unknown_selected_task_is_rejected(self):
        self.dataset(selected=("missing",))
        with self.assertRaisesRegex(ValueError, "missing"):
            sm.milestones(self.workspace)

    def test_duplicate_selected_task_is_rejected(self):
        self.dataset(selected=("a", "a"))
        with self.assertRaisesRegex(ValueError, "unique"):
            sm.milestones(self.workspace)

    def test_checkpoints_use_recorded_heads_even_after_further_edits(self):
        repo, benchmark, _, (_, first, last) = self.records()
        (repo / "source.py").write_text("value = 'uncommitted'\n")
        self.assertEqual(sm.recorded_commits(repo.parent, benchmark), {"a": first, "b": last})
        (repo.parent / "b-result.json").unlink()
        self.assertEqual(sm.recorded_commits(repo.parent, benchmark), {"a": first})

    def test_different_specification_or_history_is_rejected(self):
        repo, benchmark, _, (base, _, _) = self.records()
        record_path = repo.parent / "b-result.json"
        record = json.loads(record_path.read_text())
        sm.write_json(record_path, {**record, "request": "another task"})
        with self.assertRaisesRegex(ValueError, "specification"):
            sm.recorded_commits(repo.parent, benchmark)
        sm.write_json(record_path, {**record, "base": base})
        with self.assertRaisesRegex(ValueError, "history"):
            sm.recorded_commits(repo.parent, benchmark)

    def test_prepare_produces_ordinary_runner_config_with_no_extra_prompt(self):
        self.dataset(ids=("M01.2",))
        repo, base = self.repo()
        config = self.workspace.parent / "config/example.yaml"
        config.parent.mkdir()
        config.write_text("repo_src_dirs: [src]\ntest_dirs: [tests]\n")
        upstream = self.root / "upstream"
        policy = upstream / "quarantine_configs/example.yaml"
        policy.parent.mkdir(parents=True)
        policy.write_text("ecosystem: cargo\n")

        def export(image, destination):
            subprocess.run(["git", "clone", "-q", str(repo), str(destination)], check=True)
            return base

        with patch.multiple(sm, CACHE=self.root / "cache", DATA=self.workspace.parent, UPSTREAM=upstream,
                            PROJECTS={"example": {"workspace": "example", "checks": ["cargo build"]}}), \
                patch.object(sm, "release"), patch.object(sm, "pull_image", return_value=("image@sha256:123", "f" * 64)), \
                patch.object(sm, "export_baseline", side_effect=export), contextlib.redirect_stdout(io.StringIO()):
            sm.prepare("example")
            prepared, imported, bench = sm.load_prepared("example")
            loaded = load_benchmark(prepared / "run-benchmark.json")
            self.assertEqual(set(bench), {"name", "repo", "revision", "features", "checks"})
            self.assertEqual(loaded["swe_milestone"], {"project": "example", "seconds": 3600})
            self.assertEqual(loaded["features"], [{"id": "M01_2", "request": (self.workspace / "srs/M01.2/SRS.md").read_bytes().decode()}])
            self.assertEqual(imported["revision"], base)
            frozen = (prepared / "benchmark.json").read_bytes(), (prepared / "import.json").read_bytes()
            sm.prepare("example")  # Repeating setup reuses verified inputs.
            self.assertEqual(frozen, ((prepared / "benchmark.json").read_bytes(),
                                      (prepared / "import.json").read_bytes()))
            with self.assertRaisesRegex(ValueError, "different checks"):
                sm.prepare("example", ["different check"])
            (prepared / "repo_config.yaml").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                sm.load_prepared("example")

    def test_grader_errors_never_count_as_acceptance(self):
        receipt = {"exit_code": 0, "timed_out": False}
        sm.write_json(self.root / "evaluation_result.json", {"resolved": True, "infrastructure_failure": "Docker failed"})
        self.assertEqual(sm.evaluation_result(self.root, receipt)["status"], "error")
        sm.write_json(self.root / "evaluation_result.json", {"resolved": True})
        for bad in ({"exit_code": 2, "timed_out": False}, {"exit_code": 0, "timed_out": True}):
            self.assertFalse(sm.evaluation_result(self.root, bad)["resolved"])
        (self.root / "evaluation_result.json").unlink()
        self.assertEqual(sm.evaluation_result(self.root, receipt)["status"], "error")

    def test_release_filtered_verdict_is_used(self):
        sm.write_json(self.root / "evaluation_result.json", {"resolved": False})
        sm.write_json(self.root / "evaluation_result_filtered.json", {"resolved": True})
        scored = sm.evaluation_result(self.root, {"exit_code": 1, "timed_out": False})
        self.assertEqual(scored["status"], "passed")
        self.assertTrue(scored["report"].endswith("evaluation_result_filtered.json"))

    def test_explicit_upstream_build_failure_is_graded_despite_exit_two(self):
        raw = {"resolved": False, "eval_status": "failed", "scored_failure_reason": "build-failure-with-zero-tests",
               "infra_invalid": False, "test_summary": {"total": 0, "fail_to_pass_required": 2}}
        sm.write_json(self.root / "evaluation_result.json", raw)
        sm.write_json(self.root / "evaluation_result_filtered.json", {"resolved": True})
        result = sm.evaluation_result(self.root, {"exit_code": 2, "timed_out": False})
        self.assertEqual(result["status"], "failed")
        self.assertIs(result["resolved"], False)
        self.assertEqual(result["scored_failure_reason"], raw["scored_failure_reason"])
        self.assertEqual(result["test_summary"], raw["test_summary"])
        self.assertEqual(result["report"], str(self.root / "evaluation_result.json"))
        for key, value in (("infrastructure_failure", "Docker unavailable"), ("scoring_blocked", "invalid environment"),
                           ("infra_invalid", True), ("infra_invalid_reason", "zero-tests-with-required-tests")):
            with self.subTest(key=key):
                sm.write_json(self.root / "evaluation_result.json", {**raw, key: value})
                self.assertEqual(sm.evaluation_result(self.root, {"exit_code": 2, "timed_out": False})["status"], "error")

    def test_unclassified_exit_two_and_malformed_outputs_are_not_scored_failures(self):
        for raw in ({"resolved": False}, {"resolved": False, "eval_status": "failed"},
                    {"resolved": False, "eval_status": "failed", "scored_failure_reason": "unknown"},
                    {"resolved": True, "eval_status": "failed", "scored_failure_reason": "build-failure-with-zero-tests"}):
            with self.subTest(raw=raw):
                sm.write_json(self.root / "evaluation_result.json", raw)
                self.assertEqual(sm.evaluation_result(self.root, {"exit_code": 2, "timed_out": False})["status"], "error")
        for malformed in ("not JSON", "[]"):
            (self.root / "evaluation_result.json").write_text(malformed)
            with self.assertRaises(ValueError):
                sm.evaluation_result(self.root, {"exit_code": 2, "timed_out": False})

    def test_partial_evaluation_keeps_full_denominator_and_cannot_be_solved(self):
        repo, bench, tasks, (_, first, _) = self.records()
        prepared = self.root / "prepared"
        prepared.mkdir()
        imported = {"milestones": tasks, "version": sm.VERSION}
        sm.write_json(prepared / "import.json", imported)
        output = self.root / "grading"
        with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                patch.object(sm, "load_prepared", return_value=(prepared, imported, bench)), \
                patch.object(sm, "grade", return_value={"status": "passed", "resolved": True}) as grader, \
                patch.object(sm, "quality", return_value={"status": "completed"}), \
                contextlib.redirect_stdout(io.StringIO()):
            status = sm.evaluate("example", repo.parent, output, ["a"], 60, "scb-check")
        self.assertEqual(status, 2)
        self.assertEqual(grader.call_args.args[1], first)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual((report["passed"], report["total"], report["solved"]), (1, 2, False))
        self.assertEqual(report["milestones"][1]["status"], "not_run")

    def test_final_evaluation_regression_prevents_success_and_uses_recorded_commit(self):
        repo, bench, tasks, (base, _, _) = self.records()
        (repo / "source.py").write_text("value = 3\n")
        assembled = self.commit(repo)
        receipt = repo.parent / "scb-check/after_implementation/result.json"
        receipt.parent.mkdir(parents=True)
        sm.write_json(receipt, {"status": "completed", "commit": assembled})
        (repo / "source.py").write_text("value = 4\n")
        self.commit(repo)  # Post-run activity must not change the graded tree.
        prepared = self.root / "prepared"
        prepared.mkdir()
        imported = {"milestones": tasks, "revision": base, "version": sm.VERSION}
        sm.write_json(prepared / "import.json", imported)
        calls = []

        def grade(repo, commit, imported, prepared, folder, seconds):
            calls.append((folder, commit))
            passed = not (folder.parent.name == "final" and folder.name == "a")
            return {"status": "passed" if passed else "failed", "resolved": passed}

        output = self.root / "grading"
        with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                patch.object(sm, "load_prepared", return_value=(prepared, imported, bench)), \
                patch.object(sm, "grade", side_effect=grade), \
                patch.object(sm, "quality", return_value={"status": "completed"}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sm.evaluate("example", repo.parent, output, None, 60, "scb-check"), 1)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["passed"], 2)
        self.assertFalse(report["solved"])
        self.assertEqual(report["final"]["passed"], 1)
        self.assertEqual([commit for folder, commit in calls if folder.parent.name == "final"], [assembled, assembled])

    def test_identical_final_commit_reuses_verdict_and_ungraded_tasks_stay_ungraded(self):
        repo, bench, tasks, (base, _, last) = self.records()
        tasks[0]["graded"] = False
        receipt = repo.parent / "scb-check/after_implementation/result.json"
        receipt.parent.mkdir(parents=True)
        sm.write_json(receipt, {"status": "completed", "commit": last})
        prepared = self.root / "prepared"
        prepared.mkdir()
        imported = {"milestones": tasks, "revision": base, "version": sm.VERSION}
        sm.write_json(prepared / "import.json", imported)
        output = self.root / "grading"
        with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                patch.object(sm, "load_prepared", return_value=(prepared, imported, bench)), \
                patch.object(sm, "grade", return_value={"status": "passed", "resolved": True}) as grader, \
                patch.object(sm, "quality", return_value={"status": "completed"}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sm.evaluate("example", repo.parent, output, None, 60, "scb-check"), 0)
        self.assertEqual(grader.call_count, 1)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["milestones"][0]["status"], "not_graded")
        self.assertEqual(report["final"]["commit"], last)

    def test_final_submission_works_without_quality_and_does_not_follow_live_head(self):
        repo, bench, tasks, (base, _, final) = self.records()
        record = {"benchmark": "example", "status": "passed", "final_submission": {
            "commit": final, "tree": sm.git(repo, "rev-parse", final + "^{tree}").decode().strip()}}
        sm.write_json(repo.parent / "result.json", record)
        (repo / "source.py").write_text("value = 999\n")
        self.commit(repo)
        prepared = self.root / "prepared"
        prepared.mkdir()
        imported = {"milestones": tasks, "revision": base, "version": sm.VERSION}
        sm.write_json(prepared / "import.json", imported)
        output = self.root / "grading"
        with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                patch.object(sm, "load_prepared", return_value=(prepared, imported, bench)), \
                patch.object(sm, "grade", return_value={"status": "passed", "resolved": True}) as grader, \
                patch.object(sm, "quality") as quality, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sm.evaluate("example", repo.parent, output, None, 60, None), 0)
        quality.assert_not_called()
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["final"]["commit"], final)
        self.assertTrue(report["solved"])
        self.assertTrue(all(row["quality"]["status"] == "not_requested" for row in report["milestones"]))
        self.assertEqual(grader.call_args.args[1], final)

    def test_final_submission_cannot_substitute_a_different_tree(self):
        repo, _, tasks, (base, _, final) = self.records()
        sm.write_json(repo.parent / "result.json", {"final_submission": {"commit": final, "tree": "0" * 40}})
        with self.assertRaisesRegex(ValueError, "tree differs"):
            sm.final_evaluation(repo.parent, {"revision": base}, self.root, self.root, None, 60, tasks)

    def test_automatic_evaluator_validates_declaration(self):
        with patch.object(sm, "PROJECTS", {"example": {}}):
            configured = Evaluator.expand({"swe_milestone": {"project": "example"}}, self.root / "input.json")
            self.assertEqual(configured["swe_milestone"], {"project": "example", "seconds": 3600})
            for config in ({"project": "missing"}, {"project": "example", "seconds": True},
                           {"project": "example", "seconds": 0}, {"project": "example", "extra": 1}):
                with self.subTest(config=config), self.assertRaises(ValueError):
                    Evaluator.expand({"swe_milestone": config}, self.root / "input.json")

    def automatic_fixture(self):
        repo, benchmark, tasks, (base, _, _) = self.records()
        prepared = self.root / "prepared"
        prepared.mkdir()
        subprocess.run(["git", "clone", "-q", str(repo), str(prepared / "repo")], check=True)
        sm.git(prepared / "repo", "checkout", "-q", "--detach", base)
        upstream = self.root / "upstream"
        upstream.mkdir()
        cache = self.root / "cache"
        python = cache / "swe-milestone-venv/bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        imported = {"project": "example", "workspace": "example", "version": sm.VERSION,
                    "revision": base, "milestones": [{k: v for k, v in task.items() if k != "request"} for task in tasks],
                    "baseline_image": "image@sha256:pinned", "baseline_image_id": "image-id"}
        sm.write_json(prepared / "import.json", imported)
        actual_git = sm.git

        def git(path, *args):
            if Path(path) in (upstream, self.workspace.parent):
                return (sm.PINS["harness" if Path(path) == upstream else "data"] + "\n").encode() if args[0] == "rev-parse" else b""
            return actual_git(path, *args)

        self.enterContext(patch.multiple(sm, UPSTREAM=upstream, DATA=self.workspace.parent, CACHE=cache,
                                        PROJECTS={"example": {"workspace": "example"}}))
        self.enterContext(patch.object(sm, "git", side_effect=git))
        self.enterContext(patch.object(sm, "load_prepared", return_value=(prepared, imported, benchmark)))
        benchmark = {**benchmark, "swe_milestone": {"project": "example", "seconds": 5}}
        result = {"status": "passed", "checkpoints": [], "scb_check": {"tool": {"executable": "/checker"}}}
        evaluator = Evaluator(benchmark, repo.parent, result)
        return evaluator, base, tasks

    def test_automatic_preflight_is_local_and_fails_before_grading_for_changed_tasks(self):
        evaluator, base, _ = self.automatic_fixture()
        evaluator.benchmark["features"] = [{"id": "unexpected", "request": "changed"}]
        with patch("benchmarks.swe_milestone_evaluator.execute_child") as child, \
                patch.object(sm, "release") as download, self.assertRaisesRegex(Exception, "prepared features"):
            evaluator.start(base, {}, time.monotonic() + 60)
        child.assert_not_called()
        download.assert_not_called()

    def test_automatic_evaluation_is_bounded_and_keeps_correctness_in_run_result(self):
        evaluator, base, tasks = self.automatic_fixture()
        calls = []

        def child(argv, cwd, stdin, stdout, stderr, seconds, env):
            calls.append((argv, seconds))
            Path(stdout).write_text(json.dumps({"python": "fixture", "docker": "fixture"}))
            Path(stderr).write_text("")
            if "evaluate" in argv:
                folder = evaluator.output / "swe-milestone"
                folder.mkdir()
                sm.write_json(folder / "result.json", {
                    "schema": "swe-milestone-lab-evaluation/v1", "project": "example", "pins": sm.PINS,
                    "status": "completed", "solved": False,
                    "milestones": [{**task, "status": "failed", "resolved": False,
                                    "quality": {"status": "completed"}} for task in tasks],
                    "final": {"milestones": [{"milestone": task["milestone"], "status": "failed", "resolved": False}
                                               for task in tasks]}})
            return {"exit_code": int("evaluate" in argv), "timed_out": False, "cancelled_signal": None}

        manifest = {}
        with patch("benchmarks.swe_milestone_evaluator.execute_child", side_effect=child), \
                patch.object(sm, "release") as download:
            evaluator.start(base, manifest, time.monotonic() + 60)
            verdict = evaluator.evaluate()
        self.assertEqual(verdict["status"], "completed")
        self.assertIs(verdict["passed"], False)
        self.assertTrue(Path(verdict["report_path"]).is_file())
        self.assertEqual(evaluator.result["swe_milestone"]["status"], "completed")
        self.assertEqual([row["feature"] for row in verdict["checkpoints"]], [task["id"] for task in tasks])
        self.assertEqual(verdict["final"], {"passed": False})
        self.assertIn("swe_milestone_runtime", manifest)
        self.assertIn("--scb-check", calls[1][0])
        self.assertEqual(calls[1][1], 2 * len(tasks) * 5 + 300 * len(tasks) + 60)
        download.assert_not_called()

    def test_automatic_evaluation_cannot_accept_a_crash_or_missing_report(self):
        evaluator, base, _ = self.automatic_fixture()

        def child(argv, cwd, stdin, stdout, stderr, seconds, env):
            Path(stdout).write_text("{}")
            Path(stderr).write_text("")
            return {"argv": argv, "exit_code": 0, "timed_out": False, "cancelled_signal": None}

        with patch("benchmarks.swe_milestone_evaluator.execute_child", side_effect=child):
            evaluator.start(base, {}, time.monotonic() + 60)
            evaluator.result.pop("scb_check")
            verdict = evaluator.evaluate()
        self.assertEqual(verdict["status"], "error")
        self.assertIsNone(verdict["passed"])
        self.assertIn("--no-quality", evaluator.result["swe_milestone"]["process"]["argv"])

    def test_normal_run_automatically_grades_all_saved_milestones_after_author_shutdown(self):
        evaluator, _, tasks = self.automatic_fixture()
        output = self.root / "automatic-run"
        graded = []

        def grade(repo, commit, imported, prepared, folder, seconds):
            self.assertTrue((output / "provider-closed").exists())
            self.assertEqual(sm.git(repo, "show", commit + ":" + folder.name + ".py"), b"value = 1\n")
            graded.append((folder.name, commit))
            return {"status": "passed", "resolved": True}

        def child(argv, cwd, stdin, stdout, stderr, seconds, env):
            Path(stdout).write_text("{}")
            Path(stderr).write_text("")
            code = 0
            if "evaluate" in argv:
                self.assertTrue((output / "provider-closed").exists())
                with patch.object(sm, "release"), patch.object(sm, "upstream_imports"), \
                        patch.object(sm, "grade", side_effect=grade):
                    code = sm.evaluate("example", output, None, None, 5, None)
            return {"argv": argv, "exit_code": code, "timed_out": False, "cancelled_signal": None}

        with patch("benchmarks.swe_milestone_evaluator.execute_child", side_effect=child), \
                contextlib.redirect_stdout(io.StringIO()):
            result = run_workflow(evaluator.benchmark, dict.fromkeys(FACTORS, False), output,
                                  30, 10000, 30, backend=NativeAuthor, max_review_loops=0,
                                  loop_options={"enabled": False}, preset="native")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["evaluation"]["status"], "completed")
        self.assertIs(result["evaluation"]["passed"], True)
        self.assertEqual(result["swe_milestone"]["passed"], len(tasks))
        heads = [row["head"] for row in result["checkpoints"]]
        self.assertEqual(graded[:2], [("a", heads[0]), ("b", heads[1])])
        self.assertEqual(graded[2:], [("a", result["final_submission"]["commit"])])
        self.assertEqual(len(NativeAuthor.instances[-1].calls), 2)

    @unittest.skipUnless((sm.UPSTREAM / "harness/utils/snapshot.py").exists()
                         and importlib.util.find_spec("pathspec") and importlib.util.find_spec("yaml"),
                         "requires the pinned upstream checkout and evaluator dependencies")
    def test_upstream_snapshot_filters_tests_and_preserves_manifest_changes(self):
        repo, _ = self.repo()
        for name, content in {"src/code.py": "value = 1\n", "src/tests/test_code.py": "hidden test\n",
                              "go.mod": "module example\n", "go.sum": "checksum\n",
                              "pom.xml": "original\n", "old/pom.xml": "deleted later\n"}.items():
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        base = self.commit(repo)
        (repo / "src/code.py").write_text("value = 2\n")
        (repo / "pom.xml").write_text("changed\n")
        (repo / "old/pom.xml").unlink()
        head = self.commit(repo)
        (repo / "src/code.py").write_text("uncommitted change must not be captured\n")
        sm.write_json(self.workspace / "metadata.json", {"repo_src_dirs": ["src"], "test_dirs": ["src/tests/**"]})
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "repo_config.yaml").write_text("repo_src_dirs: [src]\ntest_dirs: ['src/tests/**']\n")
        imported = {"workspace": "example", "revision": base, "baseline_image_id": "a" * 64,
                    "repo_config_sha256": "b" * 64, "runtime_policy_sha256": "c" * 64}
        folder = self.root / "M01"
        folder.mkdir()
        with patch.object(sm, "DATA", self.workspace.parent):
            archive = sm.snapshot(repo, head, imported, folder, prepared)
        with tarfile.open(archive) as tar:
            self.assertEqual(set(tar.getnames()), {"src/code.py", "go.mod", "go.sum", "pom.xml"})
            self.assertEqual(tar.extractfile("src/code.py").read(), b"value = 2\n")
            self.assertEqual(tar.extractfile("pom.xml").read(), b"changed\n")
        sidecar = json.loads(archive.with_suffix(".integrity.json").read_text())
        self.assertTrue(sidecar["ok"])
        self.assertEqual(sidecar["manifest_overlay"]["deletes"], ["old/pom.xml"])
        self.assertEqual(sidecar["go_manifest_projection"]["present"], ["go.mod", "go.sum"])
        self.assertEqual(sidecar["snapshot_sha256"], sm.digest(archive))
        self.assertEqual(sidecar["agent_tag_commit"], head)
        self.assertEqual(sidecar["repo_config_binding"]["sha256"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
