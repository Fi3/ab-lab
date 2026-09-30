"""A benchmark checkout must not contain solutions after its pinned starting point."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from lab.config import settings
from lab.host import git
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class CheckoutIsolationTests(unittest.TestCase):
    def test_only_starting_commit_and_ancestors_are_copied(self):
        class NoGeneration(FakeCodex):
            def turn(self, *args, **kwargs):
                raise RuntimeError("stop before generation")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = repo_at(root / "source")
            ancestor = git(source, "rev-parse", "HEAD").decode().strip()
            git(source, "commit", "--allow-empty", "-qm", "benchmark starting point")
            base = git(source, "rev-parse", "HEAD").decode().strip()
            (source / "answer.py").write_text("future solution\n")
            git(source, "add", "answer.py")
            git(source, "commit", "-qm", "future solution")
            future = git(source, "rev-parse", "HEAD").decode().strip()
            blob = git(source, "rev-parse", "HEAD:answer.py").decode().strip()
            git(source, "tag", "solution", future)
            git(source, "branch", "later-solution", future)
            git(source, "gc", "--quiet")
            original_refs = git(source, "show-ref")
            benchmark = {"name": "isolated", "repo": str(source), "revision": base,
                "features": [{"id": "feature", "request": "implement a feature"}],
                "checks": ["true"]}

            result = run(benchmark, settings({}), root / "run", 30, 100, 1, backend=NoGeneration)
            self.assertEqual(result["error"], "stop before generation")
            checkout = root / "run" / "checkout"
            self.assertEqual(git(checkout, "rev-parse", "HEAD").decode().strip(), base)
            self.assertEqual(git(checkout, "rev-parse", "HEAD^{tree}"), git(source, "rev-parse", base+"^{tree}"))
            self.assertEqual(git(checkout, "rev-list", "HEAD").decode().splitlines(), [base, ancestor])
            for value in (future, blob, "refs/tags/solution", "refs/remotes/origin/HEAD"):
                with self.subTest(object=value):
                    probe = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", value],
                                           capture_output=True)
                    self.assertNotEqual(probe.returncode, 0, "future solution is accessible")
            self.assertEqual(git(checkout, "remote"), b"")
            self.assertEqual(git(checkout, "for-each-ref", "--format=%(refname)"), b"")
            self.assertFalse((checkout / ".git/objects/info/alternates").exists())
            self.assertFalse((checkout / "answer.py").exists())
            self.assertEqual(git(source, "show-ref"), original_refs)
            self.assertEqual(git(source, "rev-parse", "HEAD").decode().strip(), future)


if __name__ == "__main__":
    unittest.main()
