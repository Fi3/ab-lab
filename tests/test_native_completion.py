"""Natural author completion and runner source capture need no markers."""
from pathlib import Path
import tempfile
import unittest

from lab.config import settings
from lab.host import git
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class NativeCompletionTests(unittest.TestCase):
    def test_natural_summary_reaches_independent_review(self):
        class Native(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                if label == 'present-implement':
                    return 'Verified the existing behavior and tests.'
                if label == 'present-review-1':
                    return self.submit_review(thread, prompt, label)
                return 'Finished'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'completion', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'present', 'request': 'verify source.py'}],
                'checks': ['test -f source.py']}
            factors = settings({key: False for key in settings({})})
            result = run(benchmark, factors, root / 'run', 30, 10000, 10, backend=Native)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual([row[0] for row in Native.instances[-1].calls],
                ['present-implement', 'present-review-1'])
            self.assertTrue(result['checkpoints'][0]['already_satisfied'])

    def test_native_changes_are_captured_without_an_agent_commit(self):
        class Native(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                if label == "new-implement":
                    (self.repo / "new.py").write_text("value = 1\n")
                if "-review-" in label:
                    return self.submit_review(thread, prompt, label)
                return "Finished."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            benchmark = {"name": "natural", "repo": str(repo), "revision": "HEAD",
                "features": [{"id": "new", "request": "Create new.py"}], "checks": ["test -f new.py"]}
            result = run(benchmark, settings({key: False for key in settings({})}), root / "run",
                         30, 10000, 10, backend=Native)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(len(result["final_commits"]), 1)
            self.assertTrue((root / "run/new-implement-source.json").exists())


if __name__ == '__main__':
    unittest.main()
