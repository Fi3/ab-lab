"""Installed app-server role/tool compatibility without any model request."""
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from lab.nested import CommandEnvironment
from lab.review import REVIEW_TOOLS


@unittest.skipUnless(shutil.which('codex'), 'installed Codex required')
class CodexRoleLifecycleTests(unittest.TestCase):
    def test_profiles_are_retained_and_review_tools_accepted_without_generation(self):
        with tempfile.TemporaryDirectory(prefix='codex-role-probe-',
                dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo, state = root / 'checkout', root / 'codex-state'
            repo.mkdir()
            state.mkdir()
            executable = shutil.which('codex')
            with patch.dict(os.environ, {'CODEX_HOME': str(state)}):
                commands = CommandEnvironment(repo, root / 'commands', executable)
            env, sandbox = commands.env, commands.sandbox
            # command/exec resolves global profiles; thread/start additionally
            # receives the same definitions through its retained configuration.
            profile_config = sandbox.command(False, [])[2:-3]
            with (root / 'stderr').open('w') as stderr:
                process = subprocess.Popen([executable, '--disable', 'apps', '--disable', 'multi_agent',
                    '--disable', 'multi_agent_v2', *profile_config, *commands.config_arguments(),
                    'app-server', '--listen', 'stdio://'],
                    cwd=repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=stderr, text=True, bufsize=1, start_new_session=True)
                events = queue.Queue()
                def read():
                    for line in process.stdout:
                        events.put(json.loads(line))
                reader = threading.Thread(target=read, daemon=True)
                reader.start()
                requests, notifications = [], []
                def rpc(method, params):
                    # This allowlist prevents an accidental model-generating
                    # request from being added to an offline compatibility test.
                    self.assertIn(method, ('initialize', 'config/read', 'thread/start', 'thread/settings/update', 'thread/read', 'command/exec'))
                    request_id = len(requests) + 1
                    requests.append(method)
                    process.stdin.write(json.dumps({'id': request_id, 'method': method, 'params': params}) + '\n')
                    process.stdin.flush()
                    while True:
                        event = events.get(timeout=20)
                        if event.get('id') == request_id:
                            self.assertNotIn('error', event, event)
                            return event['result']
                        notifications.append(event)
                try:
                    rpc('initialize', {'clientInfo': {'name': 'agent_lab_role_probe', 'version': '1'},
                                       'capabilities': {'experimentalApi': True}})
                    process.stdin.write(json.dumps({'method': 'initialized', 'params': {}}) + '\n')
                    process.stdin.flush()
                    config = rpc('config/read', {'includeLayers': False})['config']
                    self.assertIs(config['features']['multi_agent'], False)
                    self.assertIs(config['features']['multi_agent_v2'], False)
                    (state / 'probe-state').write_text('private')
                    for writable in (False, True):
                        options = sandbox.thread_options(writable)
                        options['config'].update({'features.multi_agent': False, 'features.multi_agent_v2': False})
                        result = rpc('thread/start', {'cwd': str(repo), 'model': 'gpt-5.6-sol',
                            'modelProvider': 'openai', 'approvalPolicy': 'never', **options,
                            'experimentalRawEvents': False,
                            'dynamicTools': [{'type': 'function', **tool} for tool in REVIEW_TOOLS]})
                        self.assertEqual(result['activePermissionProfile']['id'], sandbox.profile(writable))
                        self.assertEqual(result['approvalPolicy'], 'never')
                        thread_id = result['thread']['id']
                        rpc('thread/settings/update', {'threadId': thread_id, **sandbox.turn_options(not writable)})
                        readback = rpc('thread/read', {'threadId': thread_id, 'includeTurns': False})
                        self.assertEqual(readback['thread']['id'], thread_id)
                        self.assertEqual(readback['thread']['turns'], [])
                        expires = time.monotonic() + 10
                        while True:
                            updates = [event['params']['threadSettings'] for event in notifications
                                if event.get('method') == 'thread/settings/updated' and event['params']['threadId'] == thread_id]
                            if updates:
                                break
                            remaining = expires - time.monotonic()
                            self.assertGreater(remaining, 0, 'missing settings update notification')
                            notifications.append(events.get(timeout=remaining))
                        self.assertEqual(updates[-1]['activePermissionProfile']['id'], sandbox.profile(not writable))
                        probe = '\n'.join([
                            'from pathlib import Path',
                            'import tempfile',
                            'with tempfile.TemporaryDirectory() as folder:',
                            '    Path(folder, "result").write_text("ok")',
                            f'try: Path({str(state / "probe-state")!r}).read_text()',
                            'except OSError: pass',
                            'else: raise AssertionError("harness state readable")',
                            'try: Path("probe-write").write_text("ok")',
                            f'except OSError: assert not {writable!r}',
                            f'else: assert {writable!r}',
                        ])
                        command = rpc('command/exec', {'cwd': str(repo), 'permissionProfile': sandbox.profile(writable),
                            'command': ['/bin/bash', '-c', 'python3 -c "$1"', 'role-probe', probe], 'timeoutMs': 10000})
                        self.assertEqual(command['exitCode'], 0, command)
                    self.assertFalse((state / 'auth.json').exists())
                    self.assertNotIn('turn/start', requests)
                finally:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    process.stdin.close()
                    reader.join(timeout=2)
                    process.stdout.close()


if __name__ == '__main__':
    unittest.main()
