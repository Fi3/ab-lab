"""Every test route uses the provider's command sandbox, including final checks."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.workflow import run
from lab.host import Host, git
from lab.nested import CommandEnvironment
from test_core import repo_at
from test_workflow import FakeCodex


class ExecutionPermissionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_retained_read_only_config_works_without_typed_profile_override(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = repo_at(root / 'checkout')
            state = root / 'codex-state'
            state.mkdir()
            probe = '\n'.join([
                'import errno,pathlib,socket',
                'assert pathlib.Path("source.py").read_text()=="first\\nmiddle\\nlast\\n"',
                's=socket.socket(); s.bind(("127.0.0.1",0)); s.listen()',
                'c=socket.create_connection(s.getsockname()); a,_=s.accept()',
                'a.sendall(b"ok"); assert c.recv(2)==b"ok"',
                'try: pathlib.Path("forbidden").write_text("bad")',
                'except OSError as e: assert e.errno in (errno.EACCES, errno.EPERM, errno.EROFS)',
                'else: raise AssertionError("read-only checkout write allowed")',
            ])
            sandbox = CommandSandbox(repo, shutil.which('codex'))
            argv = sandbox.command(False, [sys.executable, '-c', probe])
            # App-server reloads retained config before model requests without
            # the typed permissions override from thread/start. Replay only
            # that config; supplying --permission-profile hides a missing selector.
            selector = argv.index('--permission-profile')
            del argv[selector:selector+2]
            result = subprocess.run(argv, cwd=repo,
                env={**os.environ, 'CODEX_HOME': str(state)},
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((repo / 'forbidden').exists())

    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_child_supervisor_can_observe_owner_across_sandbox_pid_namespace(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            repo = repo_at(root / 'checkout')
            fake = root / 'fake-codex'
            fake.write_text('#!' + sys.executable + '\nprint("CHILD_OK")\n')
            fake.chmod(0o755)
            commands = CommandEnvironment(repo, root / 'commands', 'test', 'test', str(fake))
            cleanup.callback(commands.close)
            sandbox = CommandSandbox(repo, shutil.which('codex'), [commands.children.folder])
            result = subprocess.run(sandbox.command(True, [str(commands.bin / 'codex'), 'exec', '-']),
                cwd=repo, env=commands.env, input='', text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, commands.children.report())
            self.assertEqual(result.stdout.strip(), 'CHILD_OK')
            self.assertTrue(commands.children.settle()['measurement_complete'])
            # Simulate loss of the runner without a graceful cancel file.
            commands.children.owner_lock.close()
            stopped = subprocess.run(sandbox.command(True, [str(commands.bin / 'codex'), 'exec', '-']),
                cwd=repo, env=commands.env, input='', text=True, capture_output=True, timeout=10)
            self.assertNotEqual(stopped.returncode, 0)
            self.assertNotIn('CHILD_OK', stopped.stdout)
            self.assertTrue(any(r.get('cancelled') for r in commands.children.report()['completed'].values()))

    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_host_checks_allow_network_build_and_child_state_but_not_sibling_writes(self):
        # Outside /tmp, which is an intentional writable scratch root.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory, ExitStack() as cleanup:
            root = Path(directory)
            repo = repo_at(root / 'checkout')
            (repo / '.gitignore').write_text('build/\n')
            git(repo, 'add', '.gitignore')
            git(repo, 'commit', '-qm', 'ignore build output')
            state = root / 'codex-state'
            state.mkdir()
            with patch.dict(os.environ, {'CODEX_HOME': str(state)}):
                commands = CommandEnvironment(repo, root / 'commands', 'test', 'test', 'codex')
            cleanup.callback(commands.close)
            probe = '\n'.join([
                'import errno,pathlib,socket',
                's=socket.socket(); s.bind(("127.0.0.1",0)); s.listen()',
                'c=socket.create_connection(s.getsockname()); a,_=s.accept()',
                'a.sendall(b"ok"); assert c.recv(2)==b"ok"',
                'pathlib.Path("build").mkdir(exist_ok=True)',
                'pathlib.Path("build/result").write_text("ok")',
                f'pathlib.Path({str(state / "runtime")!r}).write_text("ok")',
                f'pathlib.Path({str(commands.children.folder / "probe")!r}).write_text("ok")',
                'try: pathlib.Path("../outside").write_text("bad")',
                'except OSError as e: assert e.errno in (errno.EACCES, errno.EPERM, errno.EROFS)',
                'else: raise AssertionError("sibling write allowed")',
            ])
            host = Host(repo, root / 'host', 'probe', 'author', time.monotonic()+20, settings({}),
                command_env=commands.env, command_argv=lambda argv: commands.sandbox.command(True, argv))
            host.command([], shlex.join([sys.executable, '-c', probe]))
            receipt = json.loads((root / 'host/operation-0001/receipt.json').read_text())
            self.assertEqual(receipt['exit_code'], 0, (root / 'host/operation-0001/stderr.txt').read_text())
            self.assertEqual((repo / 'build/result').read_text(), 'ok')
            self.assertFalse((root / 'outside').exists())
            denied = subprocess.run(commands.sandbox.command(False, [sys.executable, '-c',
                f'from pathlib import Path; Path({str(state / "runtime")!r}).write_text("bad")']),
                cwd=repo, env=commands.env, capture_output=True, timeout=10)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual((state / 'runtime').read_text(), 'ok')

    def test_host_and_final_checks_use_the_same_provider_wrapper(self):
        class Wrapped(FakeCodex):
            wrapped = []

            def command_argv(self, argv):
                self.wrapped.append(argv)
                return [sys.executable, '-c',
                        'import os,sys; os.environ["LAB_WRAPPED_TEST"]="yes"; os.execvp(sys.argv[1],sys.argv[1:])',
                        *argv]

            def turn(self, thread, prompt, label, **options):
                if label == 'one-implement' and self.authors.get(label) == 1:
                    self.authors[label] += 1
                    return '@standalone run -- test "$LAB_WRAPPED_TEST" = yes'
                return super().turn(thread, prompt, label, **options)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'permissions', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'one', 'request': 'create one'}, {'id': 'two', 'request': 'create two'}],
                'checks': ['test "$LAB_WRAPPED_TEST" = yes'], 'instructions': '', 'defer_documentation': True}
            result = run(benchmark, settings({}), root / 'run', 30, 10000, 30, backend=Wrapped)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(Wrapped.wrapped, [['/bin/sh', '-c', benchmark['checks'][0]]] * 2)
            receipts = list((root / 'run/one-host').glob('operation-*/receipt.json'))
            commands = [json.loads(path.read_text()) for path in receipts if 'exit_code' in json.loads(path.read_text())]
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0]['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
