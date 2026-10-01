"""Installed local harness/tool probes; never send prompts or model requests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.nested import CommandEnvironment
from lab.pi_sandbox import PiSandbox


@unittest.skipUnless(shutil.which('codex') and shutil.which('pi') and shutil.which('node'),
                     'installed Codex/Pi/Node required')
class DelegationSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delegation-tools-',
            dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        self.state = self.root / 'codex-state'
        self.pi_state = self.root / 'pi-state'
        for path in (self.state, self.pi_state):
            path.mkdir()
            (path / 'auth.json').write_text('{}')
        # No real credentials enter the probe. Real installed CLIs and SDK are
        # used, with exactly the CommandEnvironment policy used by the runner.
        with patch.dict(os.environ, {'CODEX_HOME': str(self.state),
                                    'PI_CODING_AGENT_DIR': str(self.pi_state)}):
            self.commands = CommandEnvironment(self.repo, self.root / 'commands',
                                               shutil.which('codex'), pi_executable=shutil.which('pi'))
        self.env = dict(self.commands.env)

    def command(self, argv, writable=True, **kwargs):
        return subprocess.run(self.commands.sandbox.command(writable, argv), cwd=self.repo,
            env=self.env, text=True, capture_output=True, timeout=20, **kwargs)

    def test_absolute_cli_launchers_and_auth_reads_are_denied_for_both_roles(self):
        probe = '''import json, pathlib, subprocess, sys
for command in json.loads(sys.argv[1]):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except PermissionError:
        pass
    else:
        assert result.returncode != 0, command
for filename in json.loads(sys.argv[2]):
    try:
        with open(filename, 'rb'):
            pass
    except PermissionError:
        pass
    else:
        raise AssertionError('credential path readable: '+filename)
print('DENIED')
'''
        launchers = [[str(Path(shutil.which(name)).resolve()), '--version'] for name in ('codex', 'pi')]
        launchers += [['node', str(Path(shutil.which(name)).resolve()), '--version'] for name in ('codex', 'pi')]
        credentials = [str(path / 'auth.json') for path in (self.state, self.pi_state)]
        for writable in (False, True):
            with self.subTest(writable=writable):
                result = self.command([sys.executable, '-c', probe, json.dumps(launchers),
                                       json.dumps(credentials)], writable)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'DENIED')

    def test_pi_sdk_native_reads_and_writes_survive_the_full_delegation_policy(self):
        sandbox = PiSandbox(self.repo, self.commands.executable, shutil.which('pi'),
                            execution=self.commands.sandbox)
        env = {**self.env, 'AGENT_LAB_PI_MODULE': sandbox.module}
        (self.repo / 'source.txt').write_text('before\n')
        for writable, request, expected in (
            (False, {'name': 'read', 'id': 'read', 'params': {'path': 'source.txt'}}, 'result'),
            (False, {'name': 'write', 'id': 'forbidden', 'params': {'path': 'source.txt', 'content': 'bad'}}, 'error'),
            (True, {'name': 'edit', 'id': 'edit', 'params': {'path': 'source.txt', 'edits': [{'oldText': 'before', 'newText': 'after'}]}}, 'result'),
            (True, {'name': 'write', 'id': 'write', 'params': {'path': 'added.txt', 'content': 'new'}}, 'result')):
            with self.subTest(request=request['id']):
                result = subprocess.run(sandbox.command(writable), cwd=self.repo, env=env,
                    input=json.dumps(request), capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(response['type'], expected, response)
        self.assertEqual((self.repo / 'source.txt').read_text(), 'after\n')
        self.assertEqual((self.repo / 'added.txt').read_text(), 'new')

    def test_codex_native_apply_patch_helper_can_write_without_exposing_auth(self):
        entry = Path(self.commands.executable).resolve()
        helper = entry
        for parent in entry.parents:
            package = parent / 'package.json'
            if package.is_file() and json.loads(package.read_text()).get('name') == '@openai/codex':
                helper = next(parent.glob('**/vendor/*/bin/codex'))
                break
        change = '*** Begin Patch\n*** Add File: native.txt\n+native patch works\n*** End Patch\n'
        result = self.command([str(helper), '--codex-run-as-apply-patch', change])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / 'native.txt').read_text(), 'native patch works\n')


if __name__ == '__main__':
    unittest.main()
