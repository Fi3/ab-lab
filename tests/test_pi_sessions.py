"""Pi's ordinary selectors can reuse owned histories without replaying usage."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lab.nested import capture_call_receipts
from lab.pi_sessions import prepare_pi_call


class PiSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        self.calls = self.root / 'calls'
        self.calls.mkdir()
        self.config = {'calls': str(self.calls), 'repo': str(self.repo)}
        self.serial = 0

    def folder(self):
        self.serial += 1
        folder = self.calls / f'call-{self.serial:03d}'
        folder.mkdir()
        return folder

    def session(self, identity='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', cwd=None):
        folder = self.folder()
        sessions = folder / 'sessions'
        sessions.mkdir()
        path = sessions / ('2026-10-01T10-00-00-000Z_' + identity + '.jsonl')
        rows = [{'type': 'session', 'version': 3, 'id': identity,
                 'cwd': str(cwd or self.repo), 'timestamp': '2026-10-01T10:00:00.000Z'},
                self.response('old-' + identity)]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        (folder / 'request.json').write_text(json.dumps({'harness': 'pi',
            'cwd': str(cwd or self.repo), 'session_dir': str(sessions)}))
        return path

    @staticmethod
    def response(identity):
        return {'type': 'message', 'id': identity, 'parentId': None,
            'timestamp': '2026-10-01T10:00:01.000Z', 'message': {'role': 'assistant',
            'provider': 'openai-codex', 'model': 'test-model', 'stopReason': 'stop',
            'content': [{'type': 'text', 'text': 'done'}],
            'usage': {'input': 2, 'output': 1, 'cacheRead': 0, 'cacheWrite': 0, 'totalTokens': 3}}}

    def prepare(self, arguments):
        folder = self.folder()
        argv, sessions = prepare_pi_call(self.config, folder, arguments)
        (folder / 'request.json').write_text(json.dumps({'harness': 'pi',
            'cwd': str(self.repo), 'session_dir': str(sessions)}))
        return folder, argv, sessions

    def test_continue_and_resume_preserve_selectors_and_expose_owned_history(self):
        old = self.session()
        for selector in ('--continue', '-c', '--resume', '-r'):
            with self.subTest(selector=selector):
                arguments = [selector, '--model', 'chosen-model', '--print', 'continue work']
                folder, argv, sessions = self.prepare(arguments)
                self.assertEqual(argv, ['--session-dir', str(sessions), *arguments])
                self.assertEqual({path.resolve() for path in sessions.glob('*.jsonl')}, {old})
                baseline = json.loads((folder / 'response-baseline.json').read_text())
                self.assertEqual(baseline['operation'], 'resume')
                self.assertEqual(list(baseline['responses'].values()), [['old-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee']])

    def test_explicit_id_path_and_session_id_reuse_existing_file(self):
        identity = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        old = self.session(identity)
        for option, value in (('--session', identity), ('--session', str(old)),
                              ('--session-id', identity), ('--session', identity[:8])):
            with self.subTest(option=option, value=value):
                folder, argv, sessions = self.prepare([option, value, '-p', 'next'])
                self.assertEqual(argv[-4:], [option, value, '-p', 'next'])
                self.assertEqual({path.resolve() for path in sessions.glob('*.jsonl')}, {old})
                self.assertIn(identity, json.loads((folder / 'response-baseline.json').read_text())['responses'])

    def test_external_history_is_rejected_even_with_a_matching_checkout_header(self):
        old = self.session()
        external = self.root / 'unowned.jsonl'
        external.write_bytes(old.read_bytes())
        with self.assertRaisesRegex(ValueError, 'not owned'):
            self.prepare(['--session', str(external)])
        foreign = self.session('11111111-bbbb-4ccc-8ddd-eeeeeeeeeeee', cwd=self.root / 'other')
        _, _, sessions = self.prepare(['--resume'])
        self.assertEqual({path.resolve() for path in sessions.glob('*.jsonl')}, {old})
        self.assertNotIn(foreign, {path.resolve() for path in sessions.glob('*.jsonl')})

    def test_fork_keeps_selector_and_records_inherited_receipts(self):
        old = self.session()
        folder, argv, sessions = self.prepare(['--fork', str(old), '-p', 'branch'])
        self.assertEqual(argv[-4:], ['--fork', str(old), '-p', 'branch'])
        baseline = json.loads((folder / 'response-baseline.json').read_text())
        self.assertEqual(baseline['operation'], 'fork')
        self.assertEqual(set(baseline['responses']), {baseline['target_thread_id']})

    def test_new_calls_stay_new_and_prompt_values_are_not_session_flags(self):
        self.session()
        arguments = ['--no-session', '--session-dir', '/ignored', '--system-prompt',
                     '--session', '--model', 'chosen-model', '--', '--continue']
        folder, argv, sessions = self.prepare(arguments)
        self.assertEqual(argv, ['--session-dir', str(sessions), '--system-prompt',
                               '--session', '--model', 'chosen-model', '--', '--continue'])
        self.assertEqual(list(sessions.iterdir()), [])
        self.assertEqual(json.loads((folder / 'response-baseline.json').read_text()),
                         {'operation': 'new', 'responses': {}})

    def test_final_receipt_boundary_does_not_change_on_later_resume(self):
        old = self.session()
        folder, _, sessions = self.prepare(['--continue'])
        before = json.loads((folder / 'response-baseline.json').read_text())['responses']
        with old.open('a') as stream:
            stream.write(json.dumps(self.response('first-resume')) + '\n')
        capture_call_receipts(folder, 'pi')
        final = (folder / 'response-final.json').read_text()
        with old.open('a') as stream:
            stream.write(json.dumps(self.response('later-resume')) + '\n')
        self.assertEqual((folder / 'response-final.json').read_text(), final)
        new_ids = set(next(iter(json.loads(final)['responses'].values()))) - set(next(iter(before.values())))
        self.assertEqual(new_ids, {'first-resume'})

    @unittest.skipUnless(shutil.which('pi') and shutil.which('node'), 'installed Pi SDK required; no model calls')
    def test_installed_pi_session_manager_finds_continue_id_and_picker_entries(self):
        first_id = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        second_id = '11111111-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        first, second = self.session(first_id), self.session(second_id)
        os.utime(first, (20, 20))
        os.utime(second, (10, 10))
        _, _, sessions = self.prepare(['--continue'])
        module = Path(shutil.which('pi')).resolve().parents[1] / 'core/session-manager.js'
        script = '''
const {SessionManager} = await import(process.argv[1]);
const [cwd, dir, id] = process.argv.slice(2);
const recent = SessionManager.continueRecent(cwd, dir);
const exact = SessionManager.findById(cwd, id, dir);
const entries = await SessionManager.list(cwd, dir);
console.log(JSON.stringify({recent: recent.getSessionFile(), exact, ids: entries.map(x => x.id)}));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script,
            module.as_uri(), str(self.repo), str(sessions), second_id],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads(result.stdout)
        self.assertEqual(Path(selected['recent']).resolve(), first)
        self.assertEqual(Path(selected['exact']).resolve(), second)
        self.assertEqual(set(selected['ids']), {first_id, second_id})
