"""Regression tests for the two failures retained in the third full attempt."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Host, git
from lab.host_tools import HostTools
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class NoChangeTests(unittest.TestCase):
    def test_existing_feature_is_reviewed_without_an_empty_commit(self):
        class Existing(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                if label.endswith('-implement'):
                    return 'The requested behavior is already implemented.'
                if '-review-' in label:
                    self.assertion = 'requested behavior is already satisfied' in prompt
                    return self.submit_review(thread, prompt, label)
                return 'Verified'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'existing', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'existing', 'request': 'source.py already contains middle'}],
                'checks': ['test -f source.py']}
            for mediated in (True, False):
                result = run(benchmark, settings({'C17': mediated, 'C08': mediated}),
                    root / str(mediated), 30, 10000, 10, backend=Existing)
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(Existing.instances[-1].assertion)
                self.assertTrue(result['checkpoints'][0]['already_satisfied'])
                self.assertEqual(result['checkpoints'][0]['review_rounds'], 1)
                self.assertEqual(result['final_commits'], [])

    def test_empty_initial_diff_does_not_skip_findings_and_repair(self):
        class Rejected(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                if label == 'one-implement':
                    self.calls.append((label, thread, prompt, options))
                    return 'The requested behavior is already implemented.'
                if label == 'one-fix-1':
                    self.calls.append((label, thread, prompt, options))
                    self.tool_call(thread, "host_edit", {"patch": "*** Begin Patch\n*** Add File: one.py\n+value = 2\n*** End Patch\n"}, label)
                    return "Resolved missing behavior."
                return super().turn(thread, prompt, label, **options)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'input')
            benchmark = {'name': 'repair', 'repo': str(repo), 'revision': 'HEAD',
                'features': [{'id': 'one', 'request': 'create one'}, {'id': 'two', 'request': 'create two'}],
                'checks': ['test -f one.py']}
            result = run(benchmark, settings({}), root / 'run', 30, 10000, 20, backend=Rejected)
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(result['checkpoints'][0]['review_rounds'], 2)
            self.assertFalse(result['checkpoints'][0]['already_satisfied'])


class NestedTests(unittest.TestCase):
    def test_header_scan_allows_excluding_forks_before_any_history_is_parsed(self):
        from datetime import datetime, timezone
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = NestedUsage(root / 'repo', 'gpt-5.5', 'xhigh', root / 'sessions')
            folder = observer.sessions / datetime.now(timezone.utc).strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            paths = {}
            for thread, parent in (('cli', None), ('native-child', 'owned-parent')):
                path = folder / (thread + '.jsonl')
                paths[thread] = path
                meta = {'id': thread, 'cwd': str(observer.repo), 'parent_thread_id': parent}
                rows = [{'type': 'session_meta', 'payload': meta},
                        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': thread + '-turn'}}]
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with patch.object(observer, 'observe', wraps=observer.observe) as observe:
                self.assertTrue(observer.scan(force=True))
                self.assertEqual(set(observer.files), set(paths.values()))
                observe.assert_not_called()
                child = observer.files[paths['native-child']]
                self.assertEqual(child['parent_thread_id'], 'owned-parent')
                self.assertEqual(child['session_meta']['id'], 'native-child')
                inherited_offset = child['offset']
                observer.refresh(parents={'native-child'})
                self.assertEqual(observe.call_count, 1)
                self.assertEqual(observe.call_args.args[0], 'cli')
                self.assertEqual(child['offset'], inherited_offset)
                self.assertEqual(set(observer.threads), {'cli'})
                self.assertFalse(observer.scan())
                observer.refresh(parents={'native-child'})
                self.assertEqual(observe.call_count, 1)

    def test_refresh_discovers_every_header_before_observing_and_preserves_resume(self):
        from datetime import datetime, timezone
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = NestedUsage(root, 'gpt-5.5', 'xhigh', root / 'sessions')
            folder = observer.sessions / datetime.now(timezone.utc).strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            paths = [folder / (thread + '.jsonl') for thread in ('one', 'two')]
            for path in paths:
                rows = [{'type': 'session_meta', 'payload': {'id': path.stem, 'cwd': str(root)}},
                        {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'first'}}]
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            original_observe = observer.observe
            def observe(thread, row):
                self.assertEqual(set(observer.files), set(paths))
                original_observe(thread, row)
            with patch.object(observer, 'observe', side_effect=observe) as seen:
                observer.refresh(force=True)
                self.assertEqual(seen.call_count, 2)
                with paths[0].open('a') as stream:
                    stream.write(json.dumps({'type': 'event_msg', 'payload': {
                        'type': 'task_started', 'turn_id': 'resumed'}}) + '\n')
                observer.refresh(force=True)
                self.assertEqual(seen.call_count, 3)
                self.assertEqual(set(observer.threads['one']['turns']), {'first', 'resumed'})

    def test_consume_uses_scanned_files_without_discovering_a_new_child(self):
        from datetime import datetime, timezone
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = NestedUsage(root, 'gpt-5.5', 'xhigh', root / 'sessions')
            folder = observer.sessions / datetime.now(timezone.utc).strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            self.assertTrue(observer.scan(force=True))
            path = folder / 'new-child.jsonl'
            rows = [{'type': 'session_meta', 'payload': {
                        'id': 'new-child', 'cwd': str(root), 'parent_thread_id': 'parent'}},
                    {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}}]
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            observer.consume()
            self.assertNotIn(path, observer.files)
            self.assertNotIn('new-child', observer.threads)
            observer.refresh(force=True)
            self.assertEqual(observer.files[path]['parent_thread_id'], 'parent')
            self.assertIn('new-child', observer.threads)

    def test_header_scan_keeps_mtime_workspace_and_partial_header_admission(self):
        from datetime import datetime, timezone
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = NestedUsage(root / 'repo', 'gpt-5.5', 'xhigh', root / 'sessions')
            folder = observer.sessions / datetime.now(timezone.utc).strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            for thread, cwd in (('old', observer.repo), ('foreign', root / 'elsewhere'), ('partial', observer.repo)):
                path = folder / (thread + '.jsonl')
                row = {'type': 'session_meta', 'payload': {'id': thread, 'cwd': str(cwd)}}
                path.write_text(json.dumps(row) + ('' if thread == 'partial' else '\n'))
                if thread == 'old':
                    os.utime(path, (observer.started - 10, observer.started - 10))
            self.assertTrue(observer.scan(force=True))
            self.assertIsNone(observer.files[folder / 'old.jsonl'])
            self.assertIsNone(observer.files[folder / 'foreign.jsonl'])
            self.assertNotIn(folder / 'partial.jsonl', observer.files)
            with (folder / 'partial.jsonl').open('a') as stream:
                stream.write('\n')
            self.assertTrue(observer.scan(force=True))
            self.assertEqual(observer.files[folder / 'partial.jsonl']['thread'], 'partial')
            self.assertFalse(observer.threads)

    def test_native_assistant_item_after_price_is_an_unpriced_tail(self):
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            observer = NestedUsage(Path(directory), 'gpt-5.5', 'xhigh', Path(directory)/'sessions')
            rows = [
                {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'u'}},
                {'type': 'turn_context', 'payload': {'model': 'gpt-5.5', 'effort': 'xhigh'}},
                {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 50, 'output_tokens': 5}}, 'rate_limits': {'plan_type': 'pro'}}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'unpriced final'}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'u'}}]
            for row in rows:
                observer.observe('child', row)
            self.assertFalse(observer.report()['measurement_complete'])

    def test_non_subscription_plan_is_rejected(self):
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            observer = NestedUsage(Path(directory), 'gpt-5.5', 'xhigh', Path(directory)/'sessions')
            observer.observe('child', {'type': 'event_msg', 'payload': {'type': 'token_count',
                'info': {'total_token_usage': {'input_tokens': 50, 'output_tokens': 5}},
                'rate_limits': {'plan_type': 'api'}}})
            self.assertTrue(observer.report()['errors'])

    def test_native_child_count_enters_provider_total_and_budget(self):
        from lab.provider import Codex, Usage
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = object.__new__(Codex)
            provider.usage = Usage()
            provider.usage.observe({'threadId': 'parent', 'tokenUsage': {'total': {'inputTokens': 100, 'outputTokens': 10}}})
            provider.parent_threads = {'parent'}
            provider.nested = NestedUsage(root, 'gpt-5.5', 'xhigh', root / 'sessions')
            provider.turns, provider.missing_turns = [{'status': 'completed'}], []
            events = [
                {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'u'}},
                {'type': 'turn_context', 'payload': {'model': 'gpt-5.5', 'effort': 'xhigh'}},
                {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 50, 'output_tokens': 5}}, 'rate_limits': {'plan_type': 'pro'}}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'u'}}]
            for event in events:
                provider.nested.observe('child', event)
            self.assertEqual(provider.observed_raw(), 165)
            self.assertEqual(provider.report()['observed_raw_tokens'], 165)
            self.assertTrue(provider.report()['measurement_complete'])

    def test_host_commands_do_not_inherit_api_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / 'repo')
            host = Host(repo, root / 'host', 'f', 'author', time.monotonic()+30, settings({}))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'not-a-real-key', 'CODEX_API_KEY': 'not-a-real-key'}):
                reply = HostTools(host).execute("host_run", {"command": "test -z \"$OPENAI_API_KEY$CODEX_API_KEY\""}, "credentials")
            self.assertTrue(reply['success'], reply)

    def test_codex_and_pi_launchers_deny_before_running_any_model(self):
        from lab.nested import CommandEnvironment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / '@openai/codex/bin/codex.js'
            executable.parent.mkdir(parents=True)
            (executable.parent.parent / 'package.json').write_text('{"name":"@openai/codex"}')
            executable.write_text('#!/bin/sh\ntouch ' + str(root / 'started') + '\n')
            executable.chmod(0o755)
            guard = CommandEnvironment(root, root / 'commands', str(executable))
            for harness in ('codex', 'pi'):
                for arguments in ([], ['exec', '-'], ['review'], ['--version']):
                    with self.subTest(harness=harness, arguments=arguments):
                        result = subprocess.run([str(guard.bin / harness), *arguments],
                            cwd=root, env=guard.env, input='request', text=True, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 126)
                        self.assertIn('Agent-created model sessions are disabled', result.stderr)
                        self.assertEqual(result.stdout, '')
            self.assertFalse((root / 'started').exists())

    def test_delegation_paths_protect_auth_and_real_cli_without_hiding_pi_sdk(self):
        from lab.nested import delegation_paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / '@openai/codex'
            (codex / 'bin').mkdir(parents=True)
            (codex / 'package.json').write_text('{"name":"@openai/codex"}')
            (codex / 'bin/codex.js').write_text('#!/usr/bin/env node\n')
            platform = root / '@openai/codex-linux-x64'
            platform.mkdir()
            pi = root / 'pi/dist/bundle/cli.js'
            pi.parent.mkdir(parents=True)
            pi.write_text('#!/usr/bin/env node\n')
            (root / 'pi/package.json').write_text('{"name":"@earendil-works/pi-coding-agent","main":"dist/index.js"}')
            for path in (codex / 'bin/codex.js', pi):
                path.chmod(0o755)
            link = root / 'codex'
            link.symlink_to(codex / 'bin/codex.js')
            with patch.dict(os.environ, {'CODEX_HOME': str(root / 'codex-state'),
                                        'PI_CODING_AGENT_DIR': str(root / 'pi-state')}):
                blocked = set(delegation_paths(str(link), str(pi)))
            self.assertTrue({str(codex / 'bin'), str(pi.parent), str(root / 'codex-state'),
                             str(root / 'pi-state')} <= blocked)
            self.assertNotIn(str(codex), blocked)
            self.assertNotIn(str(platform), blocked)
            self.assertNotIn(str(pi.parent.parent), blocked)

    def test_login_shell_still_resolves_run_local_wrapper(self):
        from lab.nested import CommandEnvironment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = CommandEnvironment(root, root / 'commands', '/bin/true')
            reply = subprocess.check_output(['/bin/bash', '-lc', 'command -v codex'], env=guard.env, text=True)
            self.assertEqual(reply.strip(), str(guard.bin / 'codex'))

    def test_native_usage_counts_resumes_once_and_excludes_parents(self):
        from lab.nested import NestedUsage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = NestedUsage(root / 'repo', 'gpt-5.5', 'xhigh', root / 'sessions')
            def event(kind, **payload):
                observer.observe('child', {'type': kind, 'payload': payload})
            event('event_msg', type='task_started', turn_id='a')
            event('turn_context', turn_id='a', model='gpt-5.5', effort='xhigh')
            event('event_msg', type='token_count', info={'total_token_usage': {
                'input_tokens': 100, 'output_tokens': 10, 'cached_input_tokens': 50}}, rate_limits={'plan_type': 'pro'})
            event('event_msg', type='task_complete', turn_id='a')
            event('event_msg', type='task_started', turn_id='b')
            event('turn_context', turn_id='b', model='gpt-5.5', effort='xhigh')
            event('event_msg', type='token_count', info={'total_token_usage': {
                'input_tokens': 250, 'output_tokens': 20, 'cached_input_tokens': 80}}, rate_limits={'plan_type': 'pro'})
            event('event_msg', type='task_complete', turn_id='b')
            self.assertEqual(observer.report(set())['observed_raw_tokens'], 270)
            self.assertTrue(observer.report(set())['measurement_complete'])
            self.assertEqual(observer.report({'child'})['observed_raw_tokens'], 0)
            event('event_msg', type='task_started', turn_id='c')
            event('turn_context', turn_id='c', model='wrong', effort='xhigh')
            event('event_msg', type='task_complete', turn_id='c')
            report = observer.report(set())
            self.assertFalse(report['measurement_complete'])
            self.assertTrue(report['errors'])

    def test_shell_startup_cannot_restore_api_keys_before_nested_execution(self):
        from lab.nested import CommandEnvironment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / 'prior-hook.sh'
            previous.write_text('export OPENAI_API_KEY=not-a-real-key\n')
            with patch.dict(os.environ, {'BASH_ENV': str(previous)}):
                guard = CommandEnvironment(root, root / 'commands', '/bin/true')
            result = subprocess.run(['/bin/bash', '-c', 'test -z "$OPENAI_API_KEY$CODEX_API_KEY"'], env=guard.env)
            self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
