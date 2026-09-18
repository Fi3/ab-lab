"""Completion markers describe a line, not the entire native final reply."""
from pathlib import Path
import tempfile
import unittest

from lab.config import settings
from lab.host import git
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class NativeCompletionTests(unittest.TestCase):
    def test_summary_before_marker_reaches_independent_review(self):
        class Native(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                if label == 'present-implement':
                    return 'Verified the existing behavior and tests.\n\n@standalone done'
                if label == 'present-review-1':
                    return 'NO_FINDINGS'
                if label == 'integration-accept':
                    git(self.repo, 'commit', '--allow-empty', '-qm',
                        'UPDATE Verify the existing feature meets its request')
                return 'Finished'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'completion', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'present', 'request': 'verify source.py'}],
                'checks': ['test -f source.py'], 'instructions': '', 'defer_documentation': True}
            factors = settings({key: False for key in settings({})})
            result = run(benchmark, factors, root / 'run', 30, 10000, 10, backend=Native)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual([row[0] for row in Native.instances[-1].calls],
                ['present-implement', 'present-review-1', 'integration-plan', 'integration-accept'])
            self.assertTrue(result['checkpoints'][0]['already_satisfied'])

    def test_marker_must_be_unique_unquoted_and_final(self):
        from lab.workflow import native_done
        for reply in ('@standalone done', 'Summary\n\n@standalone done\n'):
            self.assertTrue(native_done(reply), reply)
        for reply in ('Done', 'Say @standalone done', '@standalone done soon',
                      '> @standalone done', '```\n@standalone done\n```',
                      '@standalone done\n@standalone done',
                      '@standalone done\nBut there is more work',
                      '```text\n@standalone done'):
            self.assertFalse(native_done(reply), reply)


if __name__ == '__main__':
    unittest.main()
