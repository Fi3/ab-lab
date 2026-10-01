"""Exercise Pi's real native tools without making model calls."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(shutil.which('pi') and shutil.which('codex') and shutil.which('node'), 'local Pi/Codex required')
class PiSandboxTests(unittest.TestCase):
    def setUp(self):
        from lab.pi_sandbox import PiSandbox
        # Outside /tmp: workspace-write intentionally permits /tmp in Codex.
        self.tmp = tempfile.TemporaryDirectory(prefix='pi-sandbox-test-', dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / 'source.txt').write_text('before\n')
        self.sandbox = PiSandbox(self.repo, shutil.which('codex'), shutil.which('pi'))

    def tool(self, name, args, writable=False):
        request = {'name': name, 'id': 'test', 'params': args}
        env = {**os.environ, 'AGENT_LAB_PI_MODULE': self.sandbox.module}
        result = subprocess.run(self.sandbox.command(writable), cwd=self.repo, env=env,
                                input=json.dumps(request), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_extension_bridge_returns_native_tool_result(self):
        script = """import {readFileSync} from 'node:fs';
import {execute} from './lab/pi_sandbox.mjs';
const {policy, request, cwd} = JSON.parse(readFileSync(0, 'utf8'));
process.chdir(cwd);
console.log(JSON.stringify(await execute(policy, request)));
"""
        env = {**os.environ, 'AGENT_LAB_PI_MODULE': self.sandbox.module}
        result = subprocess.run(['node', '--input-type=module', '-e', script],
            cwd=Path(__file__).resolve().parents[1], env=env, input=json.dumps({
                'cwd': str(self.repo), 'policy': self.sandbox.policy(False),
                'request': {'name': 'read', 'id': 'test', 'params': {'path': 'source.txt'}}}),
            text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['content'][0]['text'], 'before\n')

    def test_read_only_native_read_works_but_write_edit_and_shell_write_fail(self):
        self.assertEqual(self.tool('read', {'path': 'source.txt'})['type'], 'result')
        for name, args in (('write', {'path': 'source.txt', 'content': 'bad'}),
                           ('edit', {'path': 'source.txt', 'edits': [{'oldText': 'before', 'newText': 'bad'}]}),
                           ('bash', {'command': 'echo bad > source.txt'})):
            with self.subTest(name=name):
                self.assertEqual(self.tool(name, args)['type'], 'error')
                self.assertEqual((self.repo / 'source.txt').read_text(), 'before\n')

    def test_workspace_write_allows_source_and_git_but_not_sibling_files(self):
        self.assertEqual(self.tool('write', {'path': 'source.txt', 'content': 'after'}, True)['type'], 'result')
        self.assertEqual(self.tool('bash', {'command': 'git add source.txt'}, True)['type'], 'result')
        self.assertEqual(self.tool('write', {'path': '../outside.txt', 'content': 'bad'}, True)['type'], 'error')
        (self.repo / 'link').symlink_to(self.root / 'outside.txt')
        self.assertEqual(self.tool('write', {'path': 'link', 'content': 'bad'}, True)['type'], 'error')
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_network_is_enabled_for_both_roles(self):
        command = "python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0)); s.listen(); c=socket.create_connection(s.getsockname()); a,_=s.accept(); a.sendall(b\"ok\"); assert c.recv(2)==b\"ok\"'"
        for writable in (False, True):
            with self.subTest(writable=writable):
                result = self.tool('bash', {'command': command}, writable)
                self.assertEqual(result['type'], 'result', result)

    def test_read_only_tools_can_build_in_scratch_without_editing_submission(self):
        command = """python3 - <<'PY'
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory, 'build')
    output.mkdir()
    (output / 'result').write_text('ok')
try:
    Path('source.txt').write_text('bad')
except OSError:
    pass
else:
    raise AssertionError('submission changed')
PY"""
        event = self.bridge_tool('bash', {'command': command})
        self.assertEqual(event['type'], 'result', event)
        self.assertEqual((self.repo / 'source.txt').read_text(), 'before\n')

    def bridge_tool(self, name, args, writable=False, deadline=None):
        script = """import {readFileSync} from 'node:fs';
import {execute} from './lab/pi_sandbox.mjs';
const {policy, request, cwd} = JSON.parse(readFileSync(0, 'utf8'));
process.chdir(cwd);
try { console.log(JSON.stringify({type: 'result', value: await execute(policy, request)})); }
catch (error) { console.log(JSON.stringify({type: 'error', value: error.message})); }
"""
        policy = self.sandbox.policy(writable)
        if deadline is not None:
            policy['deadline'] = deadline
        result = subprocess.run(['node', '--input-type=module', '-e', script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'AGENT_LAB_PI_MODULE': self.sandbox.module},
            input=json.dumps({'cwd': str(self.repo), 'policy': policy,
                             'request': {'name': name, 'id': 'test', 'params': args}}),
            text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_read_only_large_shell_output_is_saved_and_readable(self):
        for content in ('line\n' * 3000, 'x' * 70000 + '\n'):
            with self.subTest(size=len(content)):
                (self.repo / 'large.txt').write_text(content)
                event = self.bridge_tool('bash', {'command': 'cat large.txt'})
                self.assertEqual(event['type'], 'result', event)
                details = event['value']['details']
                self.assertTrue(details['truncation']['truncated'])
                output = Path(details['fullOutputPath'])
                self.addCleanup(output.unlink, missing_ok=True)
                self.assertEqual(output.read_text(), content)
                self.assertEqual(self.bridge_tool('read', {'path': str(output), 'limit': 1})['type'], 'result')

    def test_shell_output_bridge_preserves_read_only_and_allows_network(self):
        denied = self.bridge_tool('bash', {'command': 'echo bad > source.txt'})
        self.assertEqual(denied['type'], 'error', denied)
        self.assertEqual((self.repo / 'source.txt').read_text(), 'before\n')
        for writable in (False, True):
            with self.subTest(writable=writable):
                allowed = self.bridge_tool('bash', {'command': "python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0))'"}, writable)
                self.assertEqual(allowed['type'], 'result', allowed)

    def test_shell_output_bridge_keeps_writable_scope(self):
        allowed = self.bridge_tool('bash', {'command': 'echo after > source.txt && git add source.txt'}, True)
        self.assertEqual(allowed['type'], 'result', allowed)
        self.assertEqual((self.repo / 'source.txt').read_text(), 'after\n')
        denied = self.bridge_tool('bash', {'command': 'echo bad > ../outside.txt'}, True)
        self.assertEqual(denied['type'], 'error', denied)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_shell_output_bridge_quotes_commands_without_outer_shell_expansion(self):
        literal = "'quoted' $(echo bad > source.txt) `echo bad > source.txt`\n$PATH"
        event = self.bridge_tool('bash', {'command': "printf '%s' " + shlex.quote(literal)})
        self.assertEqual(event['type'], 'result', event)
        self.assertEqual(event['value']['content'][0]['text'], literal)
        self.assertEqual((self.repo / 'source.txt').read_text(), 'before\n')

    def test_shell_output_bridge_honors_deadline_and_native_timeout(self):
        expired = self.bridge_tool('bash', {'command': 'echo unexpected'}, deadline=time.time()-1)
        self.assertEqual(expired['type'], 'error', expired)
        self.assertIn('deadline', expired['value'])
        stopped = self.bridge_tool('bash', {'command': 'sleep 10'}, deadline=time.time()+2)
        self.assertEqual(stopped['type'], 'error', stopped)
        self.assertTrue('aborted' in stopped['value'].lower() or 'deadline' in stopped['value'], stopped)
        timed = self.bridge_tool('bash', {'command': 'sleep 10', 'timeout': 0.1})
        self.assertEqual(timed['type'], 'error', timed)
        self.assertIn('timed out', timed['value'])


if __name__ == '__main__':
    unittest.main()
