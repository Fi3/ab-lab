"""Native harness capabilities stay available inside owned runtime boundaries."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from lab.codex_children import NativeChildren
from lab.nested import (CommandEnvironment, NativeState, PiNestedUsage, NestedUsage,
                        prepare_codex_call_state, capture_call_receipts)
from lab.provider import Codex, Pi
from lab.sandbox import CommandSandbox


class NativeDelegationTests(unittest.TestCase):
    def test_native_codex_does_not_disable_apps_or_collaboration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source-state'
            source.mkdir()
            config = {'forced_login_method': 'chatgpt', 'model_provider': 'openai',
                      'features': {'multi_agent': True, 'multi_agent_v2': True, 'apps': True},
                      'model_auto_compact_token_limit': 300000}
            with patch.dict(os.environ, {'CODEX_HOME': str(source), 'PI_CODING_AGENT_DIR': str(source)}), \
                 patch('lab.provider.subprocess.Popen') as launch, \
                 patch('lab.provider.subprocess.check_output', return_value='codex test'), \
                 patch.object(Codex, '_reader'), \
                 patch.object(Codex, 'rpc', side_effect=[{}, {'account': {'type': 'chatgpt'}}, {'config': config}]):
                provider = Codex(root, root / 'provider', 'parent-model', 'high', time.monotonic()+10,
                    1000, 10, executable='/bin/true', allow_delegation=True)
                try:
                    argv = launch.call_args.args[0]
                    self.assertNotIn('--disable', argv)
                    self.assertEqual(provider.identity['context_policy'], {'mode': 'harness-native'})
                    self.assertFalse(provider.delegation_disabled)
                finally:
                    provider.close()

    def test_native_author_preserves_features_but_reviewer_stays_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            p = object.__new__(Codex)
            p.repo = p.artifacts = Path(directory)
            p.model, p.effort, p.delegation_disabled = 'parent-model', 'high', False
            p.sandbox = CommandSandbox(p.repo, '/bin/true')
            p.parent_threads = set()
            p.register_native_thread = Mock()
            p.rpc = Mock(return_value={'thread': {'id': 'author'}})
            p.start_thread(writable=True)
            config = p.rpc.call_args.args[1]['config']
            self.assertNotIn('features.multi_agent', config)
            self.assertNotIn('features.multi_agent_v2', config)
            self.assertNotIn('model_auto_compact_token_limit', config)
            p.start_thread(writable=False)
            config = p.rpc.call_args.args[1]['config']
            self.assertIs(config['features.multi_agent'], False)
            self.assertIs(config['features.multi_agent_v2'], False)

    def test_private_native_state_preserves_configuration_without_shared_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, artifacts = root / 'source', root / 'artifacts'
            source.mkdir(); artifacts.mkdir()
            for filename in ('auth.json', 'config.toml', 'reviewer.config.toml', 'AGENTS.md', 'SYSTEM.md', 'APPEND_SYSTEM.md'):
                (source / filename).write_text(filename)
            (source / 'extensions').mkdir()
            (source / 'extensions' / 'agent.ts').write_text('export default function () {}')
            with patch.dict(os.environ, {'CODEX_HOME': str(source), 'PI_CODING_AGENT_DIR': str(source)}):
                commands = CommandEnvironment(root / 'checkout', artifacts / 'commands', '/bin/true',
                    allow_delegation=True, deadline=time.monotonic()+10)
            state = commands.native_state
            try:
                for variable in ('CODEX_HOME', 'PI_CODING_AGENT_DIR'):
                    private = Path(commands.env[variable])
                    self.assertNotEqual(private, source)
                    self.assertEqual((private / 'AGENTS.md').read_text(), 'AGENTS.md')
                    if variable == 'CODEX_HOME':
                        self.assertEqual((private / 'reviewer.config.toml').read_text(), 'reviewer.config.toml')
                    (private / 'auth.json').write_text('refreshed')
                    self.assertEqual((source / 'auth.json').read_text(), 'auth.json')
                self.assertEqual((Path(commands.env['PI_CODING_AGENT_DIR']) / 'SYSTEM.md').read_text(), 'SYSTEM.md')
                self.assertTrue((Path(commands.env['PI_CODING_AGENT_DIR']) / 'extensions').is_symlink())
                self.assertNotIn(str(source), commands.sandbox.roots)
                self.assertNotIn('auth.json', state.fingerprints['codex'])
                self.assertEqual(state.fingerprints['pi']['extensions']['hashed_files'], 1)
                self.assertNotEqual(commands.sandbox.filesystem(False)[str(state.root)], 'write')
            finally:
                commands.close()
            self.assertFalse(state.root.exists())
            self.assertTrue(state.sessions['codex'].exists())

    def test_native_pi_retains_default_tools_and_extension_discovery(self):
        p = object.__new__(Pi)
        p.executable, p.model, p.effort = 'pi', 'parent-model', 'high'
        native = p.launch_arguments(native=True)
        self.assertNotIn('--no-extensions', native)
        self.assertNotIn('--tools', native)
        self.assertIn('--extension', native)
        self.assertIn('--no-extensions', p.launch_arguments())

    def test_native_children_may_use_configured_models_and_efforts(self):
        children = NativeChildren()
        children.discover('child', 'parent')
        reader = Mock(validated=True, errors=[], turn_contexts={'turn': {'model': 'other', 'effort': 'low'}},
                      responses={}, plans={'pro'}, missing_compactions=[])
        native = children.report({'child': reader}, 'parent', 'high', allow_model_variation=True)
        self.assertEqual(native['errors'], [])
        controlled = children.report({'child': reader}, 'parent', 'high')
        self.assertTrue(any('model/effort' in error for error in controlled['errors']))


class PiDelegatedUsageTests(unittest.TestCase):
    def test_responses_and_compaction_count_once_and_missing_usage_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            call = root / 'call-owned'
            (call / 'sessions').mkdir(parents=True)
            (call / 'request.json').write_text(json.dumps({'harness': 'pi'}))
            usage = PiNestedUsage(root, root)
            self.assertFalse(usage.report(force=True)['measurement_complete'])
            rows = [{'type': 'session', 'id': 'child', 'cwd': str(root)},
                {'type': 'message', 'id': 'response', 'message': {'role': 'assistant', 'provider': 'openai-codex',
                 'model': 'child-model', 'stopReason': 'stop', 'usage': {'input': 20, 'output': 5, 'cacheRead': 10}}},
                {'type': 'compaction', 'id': 'compact', 'usage': {'input': 4, 'output': 2, 'cacheRead': 1}}]
            path = call / 'sessions' / 'child.jsonl'
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            for _ in range(2):
                result = usage.report(force=True)
                self.assertEqual(result['observed_raw_tokens'], 42)
                self.assertEqual(result['cached_input_tokens'], 11)
                self.assertTrue(result['measurement_complete'])
            rows.append({'type': 'compaction', 'id': 'missing'})
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            result = usage.report(force=True)
            self.assertFalse(result['measurement_complete'])
            self.assertIn('missing', result['errors'][0])


class CodexDelegatedReceiptTests(unittest.TestCase):
    def fixture(self, root):
        observer = NestedUsage(root, 'parent', 'high', root / 'sessions', allow_model_variation=True)
        directory = root / 'sessions' / datetime.now(timezone.utc).strftime('%Y/%m/%d')
        directory.mkdir(parents=True)
        path = directory / 'cli.jsonl'
        self.write(path, 'session_meta', {'id': 'cli', 'cwd': str(root)})
        self.write(path, 'turn_context', {'turn_id': 'first', 'model': 'configured-child', 'effort': 'low'})
        self.write(path, 'event_msg', {'type': 'task_started', 'turn_id': 'first'})
        return observer, path

    @staticmethod
    def write(path, kind, payload):
        with path.open('a') as stream:
            stream.write(json.dumps({'type': kind, 'payload': payload}) + '\n')

    def price(self, path, turn, response, usage, total):
        def values(counts):
            return dict(zip(('input_tokens', 'output_tokens', 'cached_input_tokens'), counts))
        self.write(path, 'token_usage_record', {'thread_id': 'cli', 'turn_id': turn,
            'response_id': response, 'usage': values(usage), 'thread_token_usage': values(total)})

    def counter(self, path, tokens):
        self.write(path, 'event_msg', {'type': 'token_count', 'rate_limits': {'plan_type': 'pro'},
            'info': {'total_token_usage': dict(zip(('input_tokens', 'output_tokens', 'cached_input_tokens'), tokens))}})

    def test_compaction_is_priced_without_corrupting_following_transport_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            observer, path = self.fixture(Path(directory))
            self.price(path, 'first', 'ordinary', (10, 2, 5), (10, 2, 5))
            self.counter(path, (10, 2, 5))
            self.price(path, 'first', 'compaction', (100, 5, 50), (110, 7, 55))
            self.write(path, 'compacted', {'compaction_response_id': 'compaction'})
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            observer.refresh(force=True)
            self.assertEqual(observer.report()['observed_raw_tokens'], 117)
            self.write(path, 'event_msg', {'type': 'task_started', 'turn_id': 'next'})
            self.write(path, 'turn_context', {'turn_id': 'next', 'model': 'configured-child', 'effort': 'low'})
            self.price(path, 'next', 'next-response', (15, 3, 5), (125, 10, 60))
            self.counter(path, (25, 5, 10))
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'next'})
            observer.refresh(force=True)
            report = observer.report()
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['observed_raw_tokens'], 135)
            self.assertTrue(report['measurement_complete'], report)

    def test_one_receipt_cannot_cover_a_later_unpriced_assistant_message(self):
        with tempfile.TemporaryDirectory() as directory:
            observer, path = self.fixture(Path(directory))
            self.price(path, 'first', 'ordinary', (10, 2, 5), (10, 2, 5))
            self.counter(path, (10, 2, 5))
            self.write(path, 'response_item', {'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'unpriced tail'}]})
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            observer.refresh(force=True)
            self.assertFalse(observer.report()['measurement_complete'])

    def test_each_cli_generation_requires_its_own_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer, path = self.fixture(root)
            observer.calls = root / 'calls'
            for name in ('call-priced', 'call-missing'):
                folder = observer.calls / name
                folder.mkdir(parents=True)
                (folder / 'request.json').write_text(json.dumps({'harness': 'codex', 'requires_usage': True}))
            owned = observer.calls / 'call-priced' / 'sessions'
            owned.mkdir()
            target = owned / 'history.jsonl'
            path.rename(target)
            self.price(target, 'first', 'ordinary', (10, 2, 5), (10, 2, 5))
            self.counter(target, (10, 2, 5))
            self.write(target, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            observer.refresh(force=True)
            report = observer.report()
            self.assertEqual(report['observed_raw_tokens'], 12)
            self.assertFalse(report['measurement_complete'])
            self.assertEqual(report['incomplete'], ['call-missing: no owned Codex response usage receipts'])

    def test_owned_resume_reuses_home_and_canonical_receipts_without_borrowing_future_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'home'
            source.mkdir()
            calls = root / 'calls'
            calls.mkdir()
            config = {'codex_home': str(source), 'runtime_root': str(root / 'runtime'),
                      'calls': str(calls), 'repo': str(root)}
            first = calls / 'call-first'
            first.mkdir()
            home = prepare_codex_call_state(config, first, ['exec', 'task'])
            def request(folder, selected):
                (folder / 'request.json').write_text(json.dumps({'harness': 'codex', 'requires_usage': True,
                    'environment': {'CODEX_HOME': str(selected)}, 'session_dir': str(folder / 'sessions')}))
            request(first, home)
            path = first / 'sessions' / 'cli.jsonl'
            self.write(path, 'session_meta', {'id': 'cli', 'cwd': str(root)})
            self.write(path, 'turn_context', {'turn_id': 'first', 'model': 'child', 'effort': 'high'})
            self.write(path, 'event_msg', {'type': 'task_started', 'turn_id': 'first'})
            self.price(path, 'first', 'original', (10, 2, 5), (10, 2, 5))
            self.counter(path, (10, 2, 5))
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            capture_call_receipts(first, 'codex')
            (first / 'result.json').write_text('{}')

            failed = calls / 'call-failed-resume'
            failed.mkdir()
            self.assertEqual(prepare_codex_call_state(config, failed, ['exec', 'resume', 'cli', 'more']), home)
            self.assertEqual((failed / 'sessions').resolve(), (first / 'sessions').resolve())
            request(failed, home)
            capture_call_receipts(failed, 'codex')
            (failed / 'result.json').write_text('{}')

            fork = calls / 'call-fork-selection'
            fork.mkdir()
            with patch.object(Path, 'cwd', return_value=root):
                self.assertEqual(prepare_codex_call_state(config, fork, ['fork', '--last']), home)
            self.assertEqual(json.loads((fork / 'response-baseline.json').read_text())['operation'], 'fork')

            resumed = calls / 'call-resumed'
            resumed.mkdir()
            self.assertEqual(prepare_codex_call_state(config, resumed, ['exec', 'resume', 'cli', 'more']), home)
            request(resumed, home)
            self.write(path, 'event_msg', {'type': 'task_started', 'turn_id': 'next'})
            self.write(path, 'turn_context', {'turn_id': 'next', 'model': 'child', 'effort': 'high'})
            self.price(path, 'next', 'new', (5, 1, 2), (15, 3, 7))
            self.counter(path, (15, 3, 7))
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'next'})
            capture_call_receipts(resumed, 'codex')
            (resumed / 'result.json').write_text('{}')
            observer = NestedUsage(root, 'parent', 'high', root / 'sessions',
                allow_model_variation=True, calls=calls)
            observer.refresh(force=True)
            report = observer.report()
            self.assertEqual(len(observer.files), 1)
            self.assertEqual(report['observed_raw_tokens'], 18)
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['incomplete'], ['call-failed-resume: no owned Codex response usage receipts'])

    def test_resumed_primary_thread_is_validated_without_counting_it_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer, path = self.fixture(root)
            self.price(path, 'first', 'response', (10, 2, 5), (10, 2, 5))
            self.counter(path, (10, 2, 5))
            self.write(path, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            observer.refresh(force=True)
            reader = observer.native_readers['cli']
            calls = root / 'calls'
            call = calls / 'call-resume'
            call.mkdir(parents=True)
            (call / 'sessions').symlink_to(path.parent, target_is_directory=True)
            (call / 'request.json').write_text(json.dumps({'harness': 'codex', 'requires_usage': True}))
            observer.calls = calls
            observer.refresh(parents={'cli'}, force=True)
            report = observer.report(parents={'cli'}, external_readers={'cli': reader})
            self.assertEqual(report['observed_raw_tokens'], 0)
            self.assertTrue(report['measurement_complete'], report)

    def test_paginated_cli_fork_subtracts_only_verified_parent_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer, parent = self.fixture(root)
            self.price(parent, 'first', 'parent-response', (100, 20, 50), (100, 20, 50))
            self.counter(parent, (100, 20, 50))
            self.write(parent, 'event_msg', {'type': 'task_complete', 'turn_id': 'first'})
            child = parent.with_name('fork.jsonl')
            self.write(child, 'session_meta', {'id': 'fork', 'session_id': 'fork', 'cwd': str(root),
                'forked_from_id': 'cli', 'history_mode': 'paginated',
                'history_base': {'thread_id': 'cli', 'end_byte_offset': parent.stat().st_size}})
            self.write(child, 'turn_context', {'turn_id': 'fork-turn', 'model': 'child', 'effort': 'high'})
            self.write(child, 'event_msg', {'type': 'task_started', 'turn_id': 'fork-turn'})
            self.write(child, 'token_usage_record', {'thread_id': 'fork', 'turn_id': 'fork-turn',
                'response_id': 'fork-response', 'usage': {'input_tokens': 10, 'output_tokens': 2, 'cached_input_tokens': 5},
                'thread_token_usage': {'input_tokens': 110, 'output_tokens': 22, 'cached_input_tokens': 55}})
            self.counter(child, (110, 22, 55))
            self.write(child, 'event_msg', {'type': 'task_complete', 'turn_id': 'fork-turn'})
            observer.refresh(force=True)
            report = observer.report()
            self.assertTrue(report['measurement_complete'], report)
            self.assertEqual(report['thread_totals'], {'cli': [100, 20, 50], 'fork': [10, 2, 5]})
            self.assertEqual(report['observed_raw_tokens'], 132)
            unknown = NestedUsage(root, 'parent', 'high', root / 'sessions', allow_model_variation=True)
            parent.unlink()
            unknown.refresh(force=True)
            report = unknown.report()
            self.assertFalse(report['measurement_complete'])
            self.assertEqual(report['observed_raw_tokens'], 12)
            self.assertIn('no owned parent history', report['incomplete'][0])
