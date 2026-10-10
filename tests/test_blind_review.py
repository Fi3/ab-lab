"""Blind review preserves source trees while hiding author history and artifacts."""
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

from lab.config import settings
from lab.environment import clean_env
from lab.host import git, snapshot
from lab.pi_sandbox import PiSandbox
from lab.provider import ChildAccounting
from lab.review import BLIND_REVIEW_POLICY, BlindReview, ReviewTools
from lab.sandbox import CommandSandbox
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class BlindReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = repo_at(self.root / "author")
        self.base = git(self.source, "rev-parse", "HEAD").decode().strip()
        (self.source / "source.py").write_text("changed\n")
        (self.source / "binary").write_bytes(b"\x00\xff")
        (self.source / "executable").write_text("#!/bin/sh\n")
        (self.source / "executable").chmod(0o755)
        (self.source / "link").symlink_to("source.py")
        (self.source / ".gitattributes").write_text("binary export-ignore\n")
        git(self.source, "add", "--all")
        git(self.source, "commit", "-qm", "PRIVATE_AUTHOR_REASON: repair the issue")
        self.head = git(self.source, "rev-parse", "HEAD").decode().strip()
        self.before = snapshot(self.source)
        self.view = BlindReview(self.source, self.base, self.root / "review")
        self.view.update(self.head)

    def test_exact_trees_and_diff_without_original_commits_or_metadata(self):
        for original, neutral in ((self.base, self.view.base), (self.head, self.view.head)):
            self.assertEqual(git(self.source, "rev-parse", original + "^{tree}"),
                             git(self.view.repo, "rev-parse", neutral + "^{tree}"))
            result = subprocess.run(["git", "-C", str(self.view.repo), "cat-file", "-e", original], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git(self.source, "diff", "--binary", self.base, self.head),
                         git(self.view.repo, "diff", "--binary", self.view.base, self.view.head))
        self.assertEqual(git(self.view.repo, "log", "--format=%s").decode().splitlines(), ["Submission", "Baseline"])
        self.assertNotIn(b"PRIVATE_AUTHOR_REASON", git(self.view.repo, "log", "--format=fuller"))
        self.assertEqual((self.view.repo / "binary").read_bytes(), b"\x00\xff")
        self.assertTrue((self.view.repo / "executable").stat().st_mode & 0o111)
        self.assertEqual((self.view.repo / "link").readlink(), Path("source.py"))
        self.assertEqual(git(self.view.repo, "remote"), b"")
        self.assertFalse((self.view.repo / ".git/objects/info/alternates").exists())
        self.assertEqual(snapshot(self.source), self.before)

    def test_repairs_keep_the_feature_base_and_never_import_author_commits(self):
        base = self.view.base
        (self.source / "source.py").write_text("repaired\n")
        git(self.source, "add", "source.py")
        git(self.source, "commit", "-qm", "PRIVATE_REPAIR_REASON")
        repaired = git(self.source, "rev-parse", "HEAD").decode().strip()
        self.view.update(repaired)
        self.assertEqual(self.view.base, base)
        self.assertEqual(git(self.view.repo, "rev-list", "HEAD").decode().splitlines(), [self.view.head, base])
        self.assertEqual(git(self.source, "diff", "--binary", self.base, repaired),
                         git(self.view.repo, "diff", "--binary", base, self.view.head))
        result = subprocess.run(["git", "-C", str(self.view.repo), "cat-file", "-e", repaired], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_empty_diff_has_only_a_neutral_baseline(self):
        self.view.update(self.base)
        self.assertEqual(self.view.head, self.view.base)
        self.assertEqual(git(self.view.repo, "log", "--format=%s"), b"Baseline\n")
        self.assertEqual(git(self.view.repo, "diff", self.view.base, "HEAD"), b"")

    def test_provider_settings_and_accounting_are_restored_after_errors(self):
        execution = CommandSandbox(self.source, "codex")
        pi = object.__new__(PiSandbox)
        pi.repo, pi.execution = self.source, execution
        for sandbox in (execution, pi):
            with self.subTest(sandbox=type(sandbox).__name__):
                provider = SimpleNamespace(repo=self.source, sandbox=sandbox, command_env={"BASH_ENV": "/private/startup"},
                                           usage=object(), max_raw=123, max_turns=4, deadline=5)
                original_env, usage = provider.command_env, provider.usage
                with self.assertRaisesRegex(RuntimeError, "test failure"):
                    with self.view.activate(provider, [self.source]):
                        isolated = provider.sandbox.execution if isinstance(provider.sandbox, PiSandbox) else provider.sandbox
                        self.assertEqual(provider.repo, self.view.repo)
                        self.assertEqual(isolated.filesystem(False)[str(self.source)], "none")
                        self.assertEqual(provider.command_env["BASH_ENV"], "/dev/null")
                        self.assertIs(provider.usage, usage)
                        raise RuntimeError("test failure")
                self.assertEqual(provider.repo, self.source)
                self.assertIs(provider.sandbox, sandbox)
                self.assertIs(provider.command_env, original_env)
                self.assertEqual((provider.max_raw, provider.max_turns, provider.deadline), (123, 4, 5))

    @unittest.skipUnless(shutil.which("codex"), "installed Codex sandbox required; no model calls")
    def test_native_tools_and_review_run_cannot_read_original_data(self):
        artifacts = self.root / "private"
        artifacts.mkdir()
        secret = artifacts / "issue.txt"
        secret.write_text("PRIVATE_ISSUE_DESCRIPTION")
        provider = ChildAccounting()
        provider.repo = self.source
        provider.sandbox = CommandSandbox(self.source, shutil.which("codex"))
        provider.command_env = clean_env()
        protected = [str(self.source / ".git/COMMIT_EDITMSG"), str(secret)]
        script = "\n".join([
            "from pathlib import Path",
            f"for filename in {protected!r}:",
            "    try: Path(filename).read_bytes()",
            "    except OSError: pass",
            "    else: raise AssertionError('private data readable')",
        ])
        with self.view.activate(provider, [self.source, artifacts]):
            result = subprocess.run(provider.sandbox.command(False, ["python3", "-c", script]),
                                    cwd=self.view.repo, env=provider.command_env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            tools = ReviewTools(self.root / "receipts", repo=self.view.repo, deadline=time.monotonic() + 20,
                                command_env=provider.command_env, command_argv=provider.review_command_argv)
            tools.begin("review-1", self.view.head)
            command = "python3 -c " + shlex.quote(script) + " && git log --format=%s && mkdir build"
            response = tools.execute("review_run", {"command": command}, "verification")
            self.assertTrue(response["success"], response)
            self.assertIn("Submission", response["text"])
            self.assertNotIn("PRIVATE_AUTHOR_REASON", response["text"])
            self.assertEqual(snapshot(self.source), self.before)


class BlindReviewWorkflowTests(unittest.TestCase):
    def test_blind_and_legacy_review_routes_preserve_the_author_submission(self):
        class Inspects(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                if "-review-" in label:
                    messages = git(self.repo, "log", "--format=%s").decode().splitlines()
                    if "Original request: create one" in prompt:
                        assert self.repo.name == "checkout" and any(message.startswith("UPDATE one:") for message in messages)
                    else:
                        assert messages == ["Submission", "Baseline"]
                        assert "Review target: review-" in prompt
                return super().turn(thread, prompt, label, **options)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = repo_at(root / "input")
            benchmark = {"name": "routing", "repo": str(source), "revision": "HEAD",
                         "features": [{"id": "one", "request": "Original request: create one"}], "checks": ["test -f one.py"]}
            for informed in (False, True):
                output = root / str(informed)
                result = run(benchmark, settings({}), output, 30, 10000, 30, backend=Inspects, review_issue_description=informed)
                self.assertEqual(result["status"], "passed", result)
                self.assertEqual(len(result["final_commits"]), 2)
                self.assertEqual((output / "checkout/one.py").read_text(), "value = 2\n")
                manifest = json.loads((output / "manifest.json").read_text())
                self.assertEqual(manifest.get("blind_review_policy"), None if informed else BLIND_REVIEW_POLICY)
                self.assertEqual(result.get("blind_review_policy"), None if informed else BLIND_REVIEW_POLICY)
                self.assertTrue(all(("blind_head" in review) is not informed for review in result["reviews"]))


if __name__ == "__main__":
    unittest.main()
