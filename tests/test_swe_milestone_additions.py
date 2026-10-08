"""Repository treatments preserve the upstream files, tasks, and grading base."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import swe_milestone as sm
from benchmarks.swe_milestone_evaluator import Evaluator
from lab.config import FACTORS
from lab.workflow import run as run_workflow
from test_evaluation import NativeAuthor
import test_swe_milestone as fixtures


class RepositoryAdditionTests(unittest.TestCase):
    setUp = fixtures.MilestoneTests.setUp
    dataset = fixtures.MilestoneTests.dataset
    repo = fixtures.MilestoneTests.repo
    commit = fixtures.MilestoneTests.commit
    records = fixtures.MilestoneTests.records
    automatic_fixture = fixtures.MilestoneTests.automatic_fixture

    def variant(self, change=None):
        repo, baseline = self.repo()
        skill = repo / ".agents/skills/speckit-plan/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("Installed skill\n")
        constitution = repo / ".specify/memory/constitution.md"
        constitution.parent.mkdir(parents=True)
        constitution.write_text("Existing project rules\n")
        if change:
            change(repo)
        revision = self.commit(repo)
        expected = {"revision": baseline, "features": [{"id": "a", "request": "Unchanged request"}]}
        benchmark = {**expected, "repo": str(repo), "revision": revision,
                     "swe_milestone": {"project": "scikit-learn", "repository_additions": [".agents", ".specify"]}}
        return repo, baseline, expected, benchmark

    def test_additions_retain_the_original_grading_revision_and_frozen_metadata(self):
        repo, baseline, expected, benchmark = self.variant()
        imported = {"revision": baseline, "milestones": [{"id": "a"}], "pins": sm.PINS}
        original = copy.deepcopy(imported)
        scope = sm.benchmark_scope(imported, expected, benchmark)
        self.assertEqual(imported, original)
        self.assertEqual(scope["revision"], baseline)
        receipt = scope["repository_additions"]
        self.assertTrue(receipt["existing_files_unchanged"])
        self.assertEqual(receipt["baseline_revision"], baseline)
        self.assertEqual(len(receipt["files"]), 2)
        self.assertEqual(sm.git(repo, "show", benchmark["revision"] + ":source.py"), b"value = 0\n")

    def test_changed_revision_still_requires_an_explicit_additions_declaration(self):
        _, _, expected, benchmark = self.variant()
        benchmark["swe_milestone"].pop("repository_additions")
        with self.assertRaisesRegex(ValueError, "prepared revision"):
            sm.benchmark_scope({"milestones": []}, expected, benchmark)

    def test_declared_new_root_instruction_file_is_admitted_with_the_kit(self):
        repo, baseline, expected, benchmark = self.variant(
            lambda repo: (repo / "AGENTS.md").write_text("Run the installed workflow\n"))
        benchmark["swe_milestone"]["repository_additions"].append("AGENTS.md")
        scope = sm.benchmark_scope({"revision": baseline, "milestones": []}, expected, benchmark)
        self.assertEqual(scope["revision"], baseline)
        files = scope["repository_additions"]["files"]
        self.assertEqual(len(files), 3)
        self.assertEqual(next(item for item in files if item["path"] == "AGENTS.md")["mode"], "100644")
        self.assertEqual(sm.git(repo, "diff", baseline, benchmark["revision"], "--", "source.py"), b"")

    def test_existing_root_instruction_file_cannot_be_declared_as_an_addition(self):
        repo, _ = self.repo()
        (repo / "AGENTS.md").write_text("Original instructions\n")
        baseline = self.commit(repo)
        (repo / ".specify").mkdir()
        (repo / ".specify/install.json").write_text("{}\n")
        benchmark = {"repo": str(repo), "revision": self.commit(repo),
            "swe_milestone": {"repository_additions": ["AGENTS.md", ".specify"]}}
        with self.assertRaisesRegex(ValueError, "already exists"):
            sm.verify_repository_additions(benchmark, baseline)

    def test_workflow_instructions_cannot_admit_changes_to_committed_tests(self):
        repo, _ = self.repo()
        (repo / "test_existing.py").write_text("def test_existing():\n    assert True\n")
        baseline = self.commit(repo)
        (repo / "AGENTS.md").write_text("Run the installed workflow\n")
        (repo / "test_existing.py").write_text("def test_existing():\n    pass\n")
        benchmark = {"repo": str(repo), "revision": self.commit(repo),
            "swe_milestone": {"repository_additions": ["AGENTS.md"]}}
        with self.assertRaisesRegex(ValueError, "existing or undeclared"):
            sm.verify_repository_additions(benchmark, baseline)

    def test_rejects_source_changes_deletions_modes_renames_and_undeclared_files(self):
        changes = {
            "modified": lambda repo: (repo / "source.py").write_text("solved = True\n"),
            "deleted": lambda repo: (repo / "source.py").unlink(),
            "mode": lambda repo: (repo / "source.py").chmod(0o755),
            "renamed": lambda repo: (repo / "source.py").rename(repo / ".specify/source.py"),
            "undeclared": lambda repo: (repo / "extra.py").write_text("extra = True\n"),
        }
        for name, change in changes.items():
            with self.subTest(change=name), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder)
                _, _, expected, benchmark = self.variant(change)
                with self.assertRaisesRegex(ValueError, "existing or undeclared"):
                    sm.benchmark_scope({"milestones": []}, expected, benchmark)

    def test_rejects_symlinks_and_existing_addition_directories(self):
        _, _, expected, benchmark = self.variant(lambda repo: (repo / ".specify/link").symlink_to("../source.py"))
        with self.assertRaisesRegex(ValueError, "regular files"):
            sm.benchmark_scope({"milestones": []}, expected, benchmark)
        repo = Path(benchmark["repo"])
        (repo / ".specify/link").unlink()
        baseline = self.commit(repo)
        (repo / ".specify/new.md").write_text("Additional file\n")
        benchmark["revision"] = self.commit(repo)
        expected["revision"] = baseline
        with self.assertRaisesRegex(ValueError, "already exists"):
            sm.benchmark_scope({"milestones": []}, expected, benchmark)

    def test_rejects_intermediate_history_even_if_its_final_source_matches(self):
        repo, baseline, expected, benchmark = self.variant()
        (repo / "source.py").write_text("solved = True\n")
        self.commit(repo)
        (repo / "source.py").write_text("value = 0\n")
        benchmark["revision"] = self.commit(repo)
        self.assertEqual(sm.git(repo, "diff", baseline, benchmark["revision"], "--", "source.py"), b"")
        with self.assertRaisesRegex(ValueError, "direct child"):
            sm.benchmark_scope({"milestones": []}, expected, benchmark)

    def test_declaration_rejects_unsafe_or_ambiguous_paths(self):
        for paths in (None, [], ".specify", [""], ["/tmp"], ["."], ["../x"], [".git"],
                      ["x/.git/y"], [".specify/"], [".agents", ".agents"],
                      [".agents", ".agents/skills"]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                Evaluator.expand({"swe_milestone": {"project": "scikit-learn", "repository_additions": paths}}, self.root)

    def test_additions_cannot_change_tasks_or_accept_a_different_runtime_base(self):
        evaluator, baseline, _ = self.automatic_fixture()
        source = Path(evaluator.benchmark["repo"])
        sm.git(source, "checkout", "-q", "--detach", baseline)
        (source / ".specify").mkdir()
        (source / ".specify/install.json").write_text("{}\n")
        revision = self.commit(source)
        evaluator.benchmark = {**evaluator.benchmark, "revision": revision,
            "swe_milestone": {**evaluator.benchmark["swe_milestone"], "repository_additions": [".specify"]}}
        with patch("benchmarks.swe_milestone_evaluator.execute_child") as child:
            with self.assertRaisesRegex(Exception, "starting repository changed"):
                evaluator.start(baseline, {}, float("inf"))
            evaluator.benchmark["features"] = [{"id": "a", "request": "Changed request"}]
            with self.assertRaisesRegex(ValueError, "unchanged prefix"):
                evaluator.start(revision, {}, float("inf"))
        child.assert_not_called()

    def test_native_workflow_and_grader_use_identical_requests_and_original_base(self):
        evaluator, baseline, tasks = self.automatic_fixture()
        source = Path(evaluator.benchmark["repo"])
        sm.git(source, "checkout", "-q", "--detach", baseline)
        (source / ".specify").mkdir()
        (source / ".specify/install.json").write_text("{}\n")
        revision = self.commit(source)
        benchmark = {**evaluator.benchmark, "revision": revision,
            "swe_milestone": {**evaluator.benchmark["swe_milestone"], "repository_additions": [".specify"]}}
        output = self.root / "addition-run"
        graded = []

        def grade(repo, commit, imported, prepared, folder, seconds):
            self.assertEqual(imported["revision"], baseline)
            self.assertEqual(sm.git(repo, "show", commit + ":.specify/install.json"), b"{}\n")
            graded.append(folder.name)
            return {"status": "passed", "resolved": True}

        def child(argv, cwd, stdin, stdout, stderr, seconds, env):
            Path(stdout).write_text("{}")
            Path(stderr).write_text("")
            code = 0
            if "evaluate" in argv:
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
        self.assertEqual([c["request"] for c in result["checkpoints"]], [task["request"] for task in tasks])
        self.assertEqual(result["checkpoints"][0]["base"], revision)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["swe_milestone_repository_additions"]["baseline_revision"], baseline)
        self.assertEqual(json.loads((output / "swe-milestone/import.json").read_text())["revision"], baseline)
        self.assertEqual(len(graded), 3)


if __name__ == "__main__":
    unittest.main()
