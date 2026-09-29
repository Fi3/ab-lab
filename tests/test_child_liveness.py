"""Lost child supervisors must fail promptly without inventing completion."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.child_process import Children
from lab.nested import CommandEnvironment


class ChildLivenessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.children = Children(self.root / 'children', time.monotonic()+21600)
        self.addCleanup(self.children.close)

    def call(self, name='call-lost'):
        folder = self.children.folder / name
        folder.mkdir()
        return folder

    def bounded_settle(self, children=None):
        checks = 0
        def check():
            nonlocal checks
            checks += 1
            if checks > 4:
                raise AssertionError('dead supervisor still waits for the six-hour deadline')
        return (children or self.children).settle(check)

    def test_unrelated_directories_never_enter_child_accounting(self):
        for name in ('.git', '.agents', '.codex', 'metadata'):
            self.call(name)
        for now in (0, 60):
            with self.subTest(now=now), patch('lab.child_process.time.monotonic', return_value=now):
                report = self.children.report()
                self.assertEqual(report['pending'], [])
                self.assertEqual(report['abandoned'], {})
                self.assertEqual(report['errors'], [])
                self.assertTrue(report['measurement_complete'])
        self.assertEqual(self.children.missing_since, {})
        self.assertTrue(self.bounded_settle()['measurement_complete'])

    def test_unrelated_receipt_is_not_a_completed_child(self):
        folder = self.call('metadata')
        (folder / 'result.json').write_text(json.dumps({'exit_code': 0}))
        report = self.children.report()
        self.assertEqual(report['completed'], {})
        self.assertTrue(report['measurement_complete'])

    def test_missing_real_call_still_fails_among_unrelated_directories(self):
        for name in ('.git', '.agents', '.codex', 'metadata'):
            self.call(name)
        folder = self.call()
        with patch('lab.child_process.time.monotonic', return_value=0):
            self.assertEqual(self.children.report()['pending'], [folder.name])
        with patch('lab.child_process.time.monotonic', return_value=60):
            report = self.children.report()
        self.assertEqual(report['pending'], [])
        self.assertEqual(list(report['abandoned']), [folder.name])
        self.assertEqual(len(report['errors']), 1)
        self.assertFalse(report['measurement_complete'])

    def test_released_supervisor_lock_fails_without_a_fake_receipt(self):
        folder = self.call()
        (folder / 'supervisor.lock').touch()
        report = self.bounded_settle()
        self.assertFalse(report['measurement_complete'])
        self.assertEqual(report['pending'], [])
        self.assertEqual(report['completed'], {})
        self.assertIn('supervisor exited', '; '.join(report['errors']))
        self.assertFalse((folder / 'result.json').exists())

    def test_live_lock_waits_and_real_completion_takes_precedence(self):
        folder = self.call()
        with (folder / 'supervisor.lock').open('wb') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.children.report()['pending'], [folder.name])
            self.assertEqual(self.children.report()['errors'], [])
            (folder / 'result.json').write_text(json.dumps({'exit_code': 0}))
            report = self.bounded_settle()
        self.assertTrue(report['measurement_complete'])
        self.assertEqual(report['completed'][folder.name]['exit_code'], 0)

    def test_receipt_published_between_first_read_and_lock_release_is_not_lost(self):
        folder = self.call()
        (folder / 'supervisor.lock').touch()
        (folder / 'result.json').write_text(json.dumps({'exit_code': 0}))
        original = Path.read_text
        reads = 0
        def raced(path, *args, **kwargs):
            nonlocal reads
            if path == folder / 'result.json':
                reads += 1
                if reads == 1:
                    raise FileNotFoundError('receipt not published yet')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', raced):
            report = self.children.report()
        self.assertTrue(report['measurement_complete'], report)

    def test_missing_lock_has_a_bounded_startup_grace(self):
        folder = self.call()
        with patch('lab.child_process.time.monotonic', return_value=0):
            self.assertEqual(self.children.report()['pending'], [folder.name])
        with patch('lab.child_process.time.monotonic', return_value=60):
            report = self.children.report()
        self.assertFalse(report['measurement_complete'])
        self.assertEqual(report['pending'], [])
        self.assertIn('supervisor', '; '.join(report['errors']))

    def test_actual_supervisor_sigkill_does_not_leave_runner_waiting(self):
        executable = self.root / 'fake-codex'
        executable.write_text('#!'+sys.executable+'\nimport os, signal\n'
            'print("partial child output", flush=True)\n'
            'os.kill(os.getppid(), signal.SIGKILL)\n')
        executable.chmod(0o755)
        commands = CommandEnvironment(self.root, self.root / 'commands', 'test', 'test',
            str(executable), deadline=time.monotonic()+21600)
        self.addCleanup(commands.close)
        result = subprocess.run([str(commands.bin / 'codex'), 'exec', '-'],
            cwd=self.root, env=commands.env, input='', capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        report = self.bounded_settle(commands.children)
        self.assertFalse(report['measurement_complete'])
        self.assertEqual(report['pending'], [])
        self.assertIn('supervisor exited', '; '.join(report['errors']))
        folder = next(p for p in commands.children.folder.iterdir() if p.is_dir())
        self.assertEqual((folder / 'stdout').read_text(), 'partial child output\n')
        self.assertFalse((folder / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
