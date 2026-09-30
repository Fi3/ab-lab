"""Reviews can build tests without accepting source or Git mutations."""
from pathlib import Path
import tempfile
import unittest

from lab.config import settings
from lab.host import git
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class ReviewPermissionTests(unittest.TestCase):
    def workflow(self, root, backend):
        repo = repo_at(root / "input")
        benchmark = {"name": "review-checks", "repo": str(repo), "revision": "HEAD",
            "features": [{"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
            "checks": ["true"]}
        return run(benchmark, settings({}), root / "run", 30, 10000, 30, backend=backend)

    def test_review_can_write_build_outputs_but_author_inspection_stays_read_only(self):
        class Builds(FakeCodex):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                (self.repo / ".git/info/exclude").write_text("build/\n")

            def turn(self, thread, prompt, label, **options):
                if "-review-" in label:
                    if not options.get("writable"):
                        raise RuntimeError("review cannot write build output")
                    folder = self.repo / "build"
                    folder.mkdir(exist_ok=True)
                    (folder / "test-output").write_text("built and tested\n")
                elif label.endswith("-implement") and options.get("writable"):
                    raise RuntimeError("mediated author unexpectedly gained native write access")
                return super().turn(thread, prompt, label, **options)

        with tempfile.TemporaryDirectory() as directory:
            result = self.workflow(Path(directory), Builds)
            self.assertEqual(result["status"], "passed", result)

    def test_review_source_index_and_history_changes_are_still_rejected(self):
        for mutation in ("source", "index", "history", "untracked"):
            class Mutates(FakeCodex):
                def turn(self, thread, prompt, label, **options):
                    if "-review-" in label:
                        if mutation == "history":
                            git(self.repo, "commit", "--allow-empty", "-qm", "unauthorized review commit")
                        elif mutation == "untracked":
                            (self.repo / "unexpected.py").write_text("bad\n")
                        else:
                            (self.repo / "source.py").write_text("unauthorized review edit\n")
                            if mutation == "index":
                                git(self.repo, "add", "source.py")
                        return "NO_FINDINGS"
                    return super().turn(thread, prompt, label, **options)

            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                result = self.workflow(Path(directory), Mutates)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"], "reviewer changed source, index or history")


if __name__ == "__main__":
    unittest.main()
