"""A caller's shutdown must not destroy a launched verification's usage tail."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from lab.nested import CommandEnvironment
from lab.host import Fatal
from lab.child_process import supervise
from tests import test_provider as stream


class NestedShutdownTests(unittest.TestCase):
    def test_next_parent_response_waits_for_the_nested_completion(self):
        helper = stream.StreamTests()
        self.addCleanup(helper.doCleanups)
        provider = helper.provider([stream.message('done'), stream.price(), stream.completed()])
        children = Mock()
        children.settle.return_value = {'measurement_complete': True, 'pending': [], 'errors': []}
        provider.commands = Mock(children=children)
        original = provider.rpc
        def rpc(method, params):
            children.settle.assert_called()
            return original(method, params)
        provider.rpc = rpc
        provider.turn('t', 'request', 'author')

    def test_missing_child_usage_blocks_before_another_parent_response(self):
        helper = stream.StreamTests()
        self.addCleanup(helper.doCleanups)
        provider = helper.provider([stream.message('done'), stream.price(), stream.completed()])
        provider.commands = Mock()
        provider.commands.children.settle.return_value = {'measurement_complete': True, 'pending': [], 'errors': []}
        provider.child_report = Mock(return_value={'measurement_complete': False, 'errors': [],
            'incomplete': ['child: last turn not complete and priced'], 'observed_raw_tokens': 0})
        provider.rpc = Mock(side_effect=provider.rpc)
        with self.assertRaisesRegex(Fatal, 'nested.*incomplete|incomplete.*nested'):
            provider.turn('t', 'request', 'author')
        provider.rpc.assert_not_called()

    def guard(self, body, seconds=10):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        executable = root / 'fake-codex'
        executable.write_text('#!'+sys.executable+'\n'+body)
        executable.chmod(0o755)
        guard = CommandEnvironment(root, root / 'commands', 'gpt-5.5', 'xhigh', str(executable),
                                   deadline=time.monotonic()+seconds)
        self.addCleanup(guard.close)
        return root, guard

    def test_normal_completion_preserves_stdin_output_exit_and_model(self):
        root, guard = self.guard('import json, sys, os\n'
            'print(json.dumps({"argv":sys.argv[1:], "stdin":sys.stdin.read(), "cwd":os.getcwd(), '
            '"key":os.environ.get("OPENAI_API_KEY")}))\n'
            'print("error stream", file=sys.stderr)\nraise SystemExit(7)\n')
        result = subprocess.run([str(guard.bin/'codex'), 'exec', '--json', '-'],
            cwd=root, env=dict(guard.env, OPENAI_API_KEY='not-a-real-key'),
            input='original prompt\n', text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stderr, 'error stream\n')
        reply = json.loads(result.stdout)
        self.assertEqual(reply['stdin'], 'original prompt\n')
        self.assertEqual(reply['cwd'], str(root))
        self.assertIsNone(reply['key'])
        self.assertIn('model="gpt-5.5"', reply['argv'])
        self.assertIn('forced_login_method="chatgpt"', reply['argv'])
        self.assertEqual(len(guard.children.report()['completed']), 1)

    def test_deadline_stops_child_and_is_not_reported_complete(self):
        root, guard = self.guard('import time\ntime.sleep(30)\n', seconds=0.4)
        result = subprocess.run([str(guard.bin/'codex'), 'exec', '-'], cwd=root,
            env=guard.env, input='', text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        report = guard.children.report()
        self.assertFalse(report['measurement_complete'])
        self.assertTrue(next(iter(report['completed'].values()))['timed_out'])

    def test_closed_output_pipe_does_not_discard_saved_usage(self):
        root, guard = self.guard('import time\nprint("started", flush=True)\ntime.sleep(0.2)\n'
            'print(\'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}\', flush=True)\n')
        process = subprocess.Popen([str(guard.bin/'codex'), 'exec', '-'], cwd=root, env=guard.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.assertEqual(process.stdout.readline().strip(), b'started')
        process.stdout.close()
        process.wait(timeout=5)
        report = guard.children.settle()
        self.assertTrue(report['measurement_complete'])
        call = next(iter(report['completed']))
        self.assertIn('turn.completed', (guard.children.folder/call/'stdout').read_text())

    def test_owner_shutdown_cancels_children_and_rejects_later_launches(self):
        root, guard = self.guard('from pathlib import Path\nimport time\n'
            'Path("started").touch()\ntime.sleep(30)\n')
        process = subprocess.Popen([str(guard.bin/'codex'), 'exec', '-'], cwd=root, env=guard.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            end = time.monotonic()+5
            while not (root/'started').exists() and time.monotonic() < end:
                time.sleep(0.01)
            self.assertTrue((root/'started').exists())
            guard.close()
            process.wait(timeout=5)
            report = guard.children.report()
            self.assertFalse(report['measurement_complete'])
            self.assertTrue(next(iter(report['completed'].values()))['cancelled'])
            retry = subprocess.run([str(guard.bin/'codex'), 'exec', '-'], cwd=root, env=guard.env,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
            self.assertEqual(retry.returncode, 2)
            self.assertIn(b'after benchmark shutdown', retry.stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)

    def test_two_children_finish_independently_and_keep_separate_outputs(self):
        root, guard = self.guard('import sys, time\ntime.sleep(0.15)\nprint(sys.argv[-1])\n')
        processes = [subprocess.Popen([str(guard.bin/'codex'), 'exec', label], cwd=root, env=guard.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for label in ('first', 'second')]
        for process, label in zip(processes, ('first', 'second')):
            out, err = process.communicate(timeout=5)
            self.assertEqual((out.strip(), err, process.returncode), (label.encode(), b'', 0))
        report = guard.children.settle()
        self.assertTrue(report['measurement_complete'])
        self.assertEqual(len(report['completed']), 2)

    def test_record_without_terminal_receipt_stays_incomplete(self):
        root, guard = self.guard('pass\n', seconds=0)
        folder = guard.children.folder/'call-missing'
        folder.mkdir()
        self.assertFalse(guard.children.report()['measurement_complete'])
        self.assertEqual(guard.children.report()['pending'], ['call-missing'])
        folder.rmdir()

    def test_delayed_supervisor_does_not_launch_after_owner_cancellation(self):
        root, guard = self.guard('pass\n')
        folder = guard.children.folder/'call-delayed'
        folder.mkdir()
        (folder/'request.json').write_text(json.dumps({'argv': ['/bin/true'], 'cwd': str(root),
            'owner_pid': os.getpid(), 'deadline': time.monotonic()+10}))
        (guard.children.folder/'cancel').touch()
        with patch('lab.child_process.subprocess.Popen', side_effect=AssertionError('late launch')) as spawn:
            supervise(folder)
            spawn.assert_not_called()
        self.assertFalse(guard.children.report()['measurement_complete'])

    def test_killing_the_caller_keeps_the_child_alive_to_record_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'fake-codex'
            executable.write_text(
                '#!'+sys.executable+'\n'
                'from pathlib import Path\nimport time\n'
                'Path("started").write_text("yes")\n'
                'time.sleep(0.5)\n'
                'Path("completed").write_text("priced")\n'
                'print(\'{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\', flush=True)\n')
            executable.chmod(0o755)
            guard = CommandEnvironment(root, root / 'commands', 'gpt-5.5', 'xhigh', str(executable))
            caller = subprocess.Popen([str(guard.bin / 'codex'), 'exec', '--json', '-'],
                cwd=root, env=guard.env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                end = time.monotonic()+5
                while not (root / 'started').exists() and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertTrue((root / 'started').exists())
                os.killpg(caller.pid, signal.SIGKILL)
                caller.wait(timeout=3)
                end = time.monotonic()+3
                while not (root / 'completed').exists() and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertTrue((root / 'completed').exists(),
                                'caller shutdown killed the child before completion/usage')
            finally:
                if caller.poll() is None:
                    os.killpg(caller.pid, signal.SIGKILL)
                    caller.wait(timeout=3)
                caller.stdout.close()
                caller.stderr.close()
                if hasattr(guard, 'close'):
                    guard.close()


if __name__ == '__main__':
    unittest.main()
