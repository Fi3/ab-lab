"""Every test route uses the provider's command sandbox, including final checks."""
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

from lab.config import settings
from lab.workflow import run
from lab.host import Host, git
from lab.host_tools import HostTools
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
    def test_host_commands_write_source_and_build_but_cannot_modify_git(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = repo_at(root / 'checkout')
            sandbox = CommandSandbox(repo, shutil.which('codex'))
            probe = '\n'.join([
                'import errno,pathlib,subprocess,tempfile',
                'index_before = pathlib.Path(".git/index").read_bytes()',
                'config_before = pathlib.Path(".git/config").read_bytes()',
                'pathlib.Path("source.py").write_text("changed\\n")',
                'pathlib.Path("build").mkdir()',
                'pathlib.Path("build/result").write_text("ok")',
                'assert subprocess.run(["git", "diff", "--quiet"]).returncode == 1',
                'for command in (["git","add","source.py"],',
                '                ["git","config","user.name","unauthorized"],',
                '                ["git","update-ref","refs/heads/unauthorized","HEAD"]):',
                '    assert subprocess.run(command, capture_output=True).returncode != 0, command',
                'for path in (".git/config", "../outside"):',
                '    try: pathlib.Path(path).write_text("bad")',
                '    except OSError as e: assert e.errno in (errno.EACCES, errno.EPERM, errno.EROFS)',
                '    else: raise AssertionError("forbidden write allowed: "+path)',
                'for action in (lambda: pathlib.Path(".git/config").unlink(),',
                '               lambda: pathlib.Path(".git/config").rename(".git/config.backup"),',
                '               lambda: pathlib.Path(".git").rename("moved-git")):',
                '    try: action()',
                '    except OSError: pass',
                '    else: raise AssertionError("Git unlink or rename allowed")',
                'assert pathlib.Path(".git/index").read_bytes() == index_before',
                'assert pathlib.Path(".git/config").read_bytes() == config_before',
                'with tempfile.TemporaryDirectory() as scratch:',
                '    pathlib.Path(scratch, "result").write_text("ok")',
            ])
            config = (repo / '.git/config').read_bytes()
            host = Host(repo, root / 'host', 'probe', 'author', time.monotonic()+20, settings({}),
                command_argv=lambda argv: sandbox.command(True, argv, protect_git=True))
            reply = HostTools(host).execute('host_run', {'command': shlex.join([sys.executable, '-c', probe])}, 'sandbox-check')
            self.assertTrue(reply['success'], reply)
            folder = next((root / 'host/tools').glob('call-*'))
            receipt = json.loads((folder / 'receipt.json').read_text())
            self.assertEqual(receipt['exit_code'], 0, (folder / 'stderr.txt').read_text())
            # The command cannot stage, but the trusted host subsequently
            # publishes its actual source changes through its own commit.
            self.assertEqual(receipt['commit'], git(repo, 'rev-parse', 'HEAD').decode().strip())
            self.assertEqual(git(repo, 'show', 'HEAD:source.py'), b'changed\n')
            self.assertEqual((repo / '.git/config').read_bytes(), config)
            self.assertFalse((repo / '.git/refs/heads/unauthorized').exists())
            self.assertEqual((repo / 'build/result').read_text(), 'ok')
            self.assertFalse((root / 'outside').exists())

    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_read_only_checkout_inside_tmp_cannot_be_edited_but_scratch_copy_can_build(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory() as directory:
            repo = repo_at(Path(directory) / 'checkout')
            (repo / 'program.py').write_text('answer = 42\n')
            sandbox = CommandSandbox(repo, shutil.which('codex'))
            probe = '\n'.join([
                'import pathlib,py_compile,shutil,subprocess,tempfile',
                'for path in ("source.py", "new-source.py", ".git/config"):',
                '    try: pathlib.Path(path).write_text("bad")',
                '    except OSError: pass',
                '    else: raise AssertionError("submission write allowed: "+path)',
                'assert subprocess.run(["git","add","source.py"], capture_output=True).returncode != 0',
                'with tempfile.TemporaryDirectory() as scratch:',
                '    copy = pathlib.Path(scratch, "copy")',
                '    shutil.copytree(pathlib.Path.cwd(), copy, ignore=shutil.ignore_patterns(".git"))',
                '    py_compile.compile(str(copy / "program.py"), doraise=True)',
                '    (copy / "build").mkdir()',
                '    (copy / "build/result").write_text("ok")',
            ])
            result = subprocess.run(sandbox.command(False, [sys.executable, '-c', probe]),
                cwd=repo, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repo / 'source.py').read_text(), 'first\nmiddle\nlast\n')
            self.assertFalse((repo / 'new-source.py').exists())
            self.assertFalse((repo / '__pycache__').exists())

    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_denied_paths_are_unreadable_in_every_role_and_through_symlinks(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = repo_at(root / 'checkout')
            private = root / 'agent-state'
            private.mkdir()
            (private / 'auth.json').write_text('test secret')
            (repo / 'linked-state').symlink_to(private, target_is_directory=True)
            sandbox = CommandSandbox(repo, shutil.which('codex'), blocked_paths=[private])
            probe = '\n'.join([
                'import pathlib',
                f'for path in ({str(private / "auth.json")!r}, "linked-state/auth.json"):',
                '    try: pathlib.Path(path).read_text()',
                '    except OSError: pass',
                '    else: raise AssertionError("agent credential read allowed")',
            ])
            for writable, protect_git in ((False, False), (True, True), (True, False)):
                with self.subTest(writable=writable, protect_git=protect_git):
                    result = subprocess.run(sandbox.command(writable, [sys.executable, '-c', probe],
                        protect_git=protect_git), cwd=repo, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('codex'), 'local Codex sandbox required')
    def test_review_copy_can_build_without_writing_original_under_tmp(self):
        from lab.sandbox import CommandSandbox
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = repo_at(root / 'original')
            copy = repo_at(root / 'copy')
            sandbox = CommandSandbox(copy, shutil.which('codex'), read_only_paths=[original])
            probe = '\n'.join([
                'import pathlib,subprocess',
                'pathlib.Path("build").mkdir()',
                'pathlib.Path("build/result").write_text("ok")',
                f'original = pathlib.Path({str(original)!r})',
                'for path in (original / "source.py", original / "new.py", original / ".git/config"):',
                '    try: path.write_text("bad")',
                '    except OSError: pass',
                '    else: raise AssertionError("original submission write allowed")',
                'assert subprocess.run(["git","-C",str(original),"config","user.name","bad"], capture_output=True).returncode != 0',
                'assert subprocess.run(["git","config","user.name","bad"], capture_output=True).returncode != 0',
            ])
            result = subprocess.run(sandbox.command(True, [sys.executable, '-c', probe], protect_git=True),
                cwd=copy, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((copy / 'build/result').read_text(), 'ok')
            self.assertEqual((original / 'source.py').read_text(), 'first\nmiddle\nlast\n')
            self.assertFalse((original / 'new.py').exists())

    def test_host_and_final_checks_use_the_same_provider_wrapper(self):
        class Wrapped(FakeCodex):
            wrapped = []

            def command_argv(self, argv):
                self.wrapped.append(argv)
                return [sys.executable, '-c',
                        'import os,sys; os.environ["LAB_WRAPPED_TEST"]="yes"; os.execvp(sys.argv[1],sys.argv[1:])',
                        *argv]

            def turn(self, thread, prompt, label, **options):
                if label == 'one-implement':
                    self.tool_call(thread, 'host_run', {'command': 'test "$LAB_WRAPPED_TEST" = yes'}, 'wrapper-check')
                return super().turn(thread, prompt, label, **options)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'permissions', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'one', 'request': 'create one'}, {'id': 'two', 'request': 'create two'}],
                'checks': ['test "$LAB_WRAPPED_TEST" = yes']}
            result = run(benchmark, settings({}), root / 'run', 30, 10000, 30, backend=Wrapped)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(Wrapped.wrapped, [['/bin/sh', '-c', benchmark['checks'][0]]] * 2)
            receipts = list((root / 'run/one-host').glob('tools/call-*/receipt.json'))
            commands = [json.loads(path.read_text()) for path in receipts if 'exit_code' in json.loads(path.read_text())]
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0]['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
