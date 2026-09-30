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
import unittest
from unittest.mock import patch

from benchmarks import swe_milestone as sm
from lab.config import load_benchmark


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
            loaded = load_benchmark(prepared / "benchmark.json")
            self.assertEqual(set(bench), {"name", "repo", "revision", "features", "checks"})
            self.assertEqual(loaded["features"], [{"id": "M01_2", "request": (self.workspace / "srs/M01.2/SRS.md").read_bytes().decode()}])
            self.assertEqual(imported["revision"], base)
            sm.prepare("example")  # Repeating setup reuses verified inputs.
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

    def test_final_assembly_regression_prevents_success_and_uses_recorded_commit(self):
        repo, bench, tasks, (base, _, _) = self.records()
        (repo / "source.py").write_text("value = 3\n")
        assembled = self.commit(repo)
        receipt = repo.parent / "scb-check/after_assembly/result.json"
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
        receipt = repo.parent / "scb-check/after_assembly/result.json"
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
