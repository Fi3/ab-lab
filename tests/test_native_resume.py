"""Explicit recovery must retain costs and reject unsafe saved boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from lab.config import settings
from lab.host import git
from lab.provider import Codex, Usage
from test_core import repo_at


class NativeResumeTests(unittest.TestCase):
    def test_only_proven_redundant_trust_additions_can_match_original_config(self):
        from lab.continuation import configuration_matches
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {'model': 'gpt-5.5', 'projects': {'/owned': {'trust_level': 'trusted'}}}
            digest = lambda x: hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()
            expected = {'auth': 'chatgpt', 'model': 'gpt-5.5', 'effective_config_sha256': digest(original)}
            current = copy.deepcopy(original)
            current['projects']['/owned/child'] = {'trust_level': 'trusted'}
            provider = Mock()
            provider.artifacts = root
            provider.identity = dict(expected, effective_config_sha256=digest(current))
            provider.rpc.return_value = {'config': current}
            self.assertFalse(configuration_matches(provider, expected))
            self.assertTrue(configuration_matches(provider, expected, ['/owned/child']))
            current['model'] = 'different'
            self.assertFalse(configuration_matches(provider, expected, ['/owned/child']))
            current['model'] = 'gpt-5.5'
            current['projects']['/outside'] = {'trust_level': 'trusted'}
            provider.identity['effective_config_sha256'] = digest(current)
            self.assertFalse(configuration_matches(provider, expected, ['/owned/child', '/outside']))

    def fixture(self, root):
        previous = root / 'previous'
        previous.mkdir()
        repo = repo_at(previous / 'checkout')
        head = git(repo, 'rev-parse', 'HEAD').decode().strip()
        provider = previous / 'provider'
        turn = provider / 'turn-0001'
        turn.mkdir(parents=True)
        (turn / 'reply.txt').write_text('Verified.\n@standalone done\n')
        (provider / 'provider.json').write_text(json.dumps({'auth': 'chatgpt'}))
        manifest = {'base_commit': head, 'created_at_unix': 1,
            'benchmark': {'name': 'resume', 'repo': str(repo), 'revision': head,
                'features': [{'id': 'one', 'request': 'verify existing'}],
                'checks': ['test -f source.py'], 'instructions': '', 'defer_documentation': True},
            'factors': settings({k: False for k in settings({})}),
            'limits': {'seconds': 300, 'observed_raw_tokens': 10000, 'turns': 10},
            'model': 'gpt-5.5', 'effort': 'xhigh'}
        result = {'status': 'failed', 'error': 'native author did not supply the stage-completion marker',
            'stages': [{'stage': 'one-implement', 'thread_id': 'author'}],
            'checkpoints': [], 'duration_seconds': 20,
            'factors': manifest['factors'], 'usage': {'measurement_complete': True,
                'observed_raw_tokens': 110, 'thread_totals': {'author': [100, 10, 50]},
                'turns': [{'thread_id': 'author', 'status': 'completed',
                    'usage_observed_after_last_message': True}],
                'unpriced_or_incomplete_turns': [], 'uncertainties': [],
                'nested': {'observed_raw_tokens': 0, 'threads': {}, 'thread_totals': {}}}}
        for name, data in (('manifest.json', manifest), ('result.json', result)):
            (previous / name).write_text(json.dumps(data))
        return previous, head, manifest, result

    def test_saved_boundary_requires_marker_complete_cost_and_exact_clean_source(self):
        from lab.continuation import inspect_boundary
        with tempfile.TemporaryDirectory() as directory:
            previous, head, manifest, result = self.fixture(Path(directory))
            record = inspect_boundary(previous, head)
            self.assertEqual(record['remaining_seconds'], 280)
            self.assertEqual(record['author'], 'author')
            for altered in (dict(result, error='other failure'),
                            dict(result, status='passed'),
                            dict(result, checkpoints=[{}]),
                            dict(result, usage=dict(result['usage'], measurement_complete=False))):
                (previous / 'result.json').write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    inspect_boundary(previous, head)
            (previous / 'result.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                inspect_boundary(previous, '0'*40)
            (previous / 'checkout' / 'untracked').write_text('unexpected')
            with self.assertRaises(ValueError):
                inspect_boundary(previous, head)

    def test_resume_restores_parent_counters_and_does_not_reinject_prompt(self):
        from lab.continuation import restore_provider
        with tempfile.TemporaryDirectory() as directory:
            previous, head, manifest, result = self.fixture(Path(directory))
            provider = object.__new__(Codex)
            provider.repo = previous / 'checkout'
            provider.model, provider.effort = 'gpt-5.5', 'xhigh'
            provider.usage, provider.turns, provider.parent_threads = Usage(), [], set()
            provider.native_usage = {}
            provider.nested = Mock()
            provider.nested.started = 99
            rollout = previous / 'owned-rollout.jsonl'
            provider.rpc = Mock(return_value={'thread': {'id': 'author', 'path': str(rollout)}})
            prior = copy.deepcopy(result['usage'])
            restore_provider(provider, manifest, prior, 'author')
            self.assertEqual(provider.usage.raw, 110)
            self.assertEqual(provider.turns, prior['turns'])
            self.assertEqual(provider.nested.started, 1)
            self.assertEqual(provider.parent_threads, {'author'})
            self.assertEqual(provider.native_usage['author'].path, rollout)
            method, params = provider.rpc.call_args.args
            self.assertEqual(method, 'thread/resume')
            self.assertEqual(params['threadId'], 'author')
            self.assertEqual(params['model'], 'gpt-5.5')
            self.assertNotIn('input', params)
            provider.usage.observe({'threadId': 'author', 'tokenUsage': {'total': {
                'inputTokens': 150, 'outputTokens': 20, 'cachedInputTokens': 60}}})
            self.assertEqual(provider.usage.raw, 170)
            self.assertEqual(prior, result['usage'])

    def test_live_monitor_includes_saved_cost_before_a_resumed_price_arrives(self):
        from unittest.mock import patch
        from lab.monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, head, manifest, result = self.fixture(root)
            output = root/'continued'
            output.mkdir()
            manifest = dict(manifest, continuation={'previous': str(previous),
                'original_created_at': manifest['created_at_unix']})
            (output/'manifest.json').write_text(json.dumps(manifest))
            observer = Mock()
            observer.report.return_value = {'observed_raw_tokens': 0, 'errors': [], 'incomplete': []}
            with patch('lab.monitor.NestedUsage', return_value=observer):
                row = sample([output], {})['runs'][0]
            self.assertEqual(row['observed_raw'], 110)
            self.assertEqual(row['completed_turns'], 1)

    def test_resume_keeps_native_and_transport_baselines_and_original_workspace(self):
        from lab.continuation import restore_provider
        with tempfile.TemporaryDirectory() as directory:
            previous, _, manifest, result = self.fixture(Path(directory))
            provider = object.__new__(Codex)
            provider.repo = Path(directory) / 'continued' / 'checkout'
            provider.model, provider.effort = 'gpt-5.5', 'xhigh'
            provider.usage, provider.turns, provider.parent_threads = Usage(), [], set()
            provider.nested = Mock()
            metadata = {'id': 'author', 'path': '/owned/native.jsonl', 'cwd': str(provider.repo)}
            provider.rpc = Mock(return_value={'thread': metadata})
            provider.register_native_thread = Mock()
            prior = copy.deepcopy(result['usage'])
            prior.update(thread_totals={'author': [200, 20, 100]},
                         app_server_thread_totals={'author': [100, 10, 50]},
                         native_thread_totals={'author': [200, 20, 100]},
                         native_usage={'author': {'cwd': str(previous / 'checkout'),
                                                  'path': '/owned/native.jsonl'}})
            before = copy.deepcopy(prior)
            restore_provider(provider, manifest, prior, 'author')
            provider.register_native_thread.assert_called_once_with(
                metadata, cwd=str(previous / 'checkout'))
            self.assertEqual(provider.usage.transport_totals['author'], (100, 10, 50))
            self.assertEqual(provider.usage.native_totals['author'], (200, 20, 100))
            self.assertEqual(provider.usage.raw, 220)
            provider.usage.observe_tokens('author', 110, 12, 55)
            provider.usage.observe_native('author', 210, 22, 105)
            self.assertEqual(provider.usage.raw, 232)
            self.assertEqual(provider.usage.uncertain, [])
            self.assertEqual(prior, before)

    def test_resumed_monitor_restores_both_counter_sources(self):
        from unittest.mock import patch
        from lab.monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, _, manifest, result = self.fixture(root)
            result['usage'].update(thread_totals={'author': [200, 20, 100]},
                app_server_thread_totals={'author': [100, 10, 50]},
                native_thread_totals={'author': [200, 20, 100]})
            (previous/'result.json').write_text(json.dumps(result))
            output = root/'continued'
            (output/'provider').mkdir(parents=True)
            manifest = dict(manifest, continuation={'previous': str(previous),
                'original_created_at': manifest['created_at_unix']})
            (output/'manifest.json').write_text(json.dumps(manifest))
            (output/'provider/transport.jsonl').write_text(json.dumps({'event': {
                'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'author',
                    'tokenUsage': {'total': {'inputTokens': 110, 'outputTokens': 12,
                                            'cachedInputTokens': 55}}}}})+'\n')
            (output/'provider/native-usage.json').write_text(json.dumps({'author': {
                'thread_id': 'author', 'validated': True, 'thread_totals': [210, 22, 105],
                'errors': [], 'missing_compactions': []}}))
            observer = Mock()
            observer.report.return_value = {'observed_raw_tokens': 0, 'errors': [], 'incomplete': []}
            with patch('lab.monitor.NestedUsage', return_value=observer):
                row = sample([output], {})['runs'][0]
            self.assertEqual(row['observed_raw'], 232)
            self.assertEqual(row['counter_flags'], [])

    def test_continuation_starts_at_review_without_replaying_implementation(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from lab.continuation import continue_native
        from test_workflow import FakeCodex

        class Continued(FakeCodex):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.identity = {'auth': 'chatgpt'}
                self.model, self.effort = 'gpt-5.5', 'xhigh'
                self.usage, self.turns = Usage(), []
                self.parent_threads, self.nested = set(), SimpleNamespace(started=99)
                self.rpc = Mock(return_value={'thread': {'id': 'author'}})

            def report(self):
                return {'measurement_complete': True, 'observed_raw_tokens': self.usage.raw,
                        'thread_totals': self.usage.totals, 'turns': self.turns}

            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                self.assertion = not label.endswith('-implement')
                if not self.assertion:
                    raise AssertionError('completed implementation was regenerated')
                previous = self.usage.totals.get(thread, (0, 0, 0))
                self.usage.observe({'threadId': thread, 'tokenUsage': {'total': {
                    'inputTokens': previous[0]+10, 'outputTokens': previous[1]+1,
                    'cachedInputTokens': 0}}})
                self.turns.append({'thread_id': thread, 'status': 'completed'})
                if label.endswith('-review-1'):
                    return 'NO_FINDINGS'
                if label == 'integration-accept':
                    git(self.repo, 'commit', '--allow-empty', '-qm',
                        'UPDATE Verify the independently reviewed existing feature')
                return 'Finished'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, head, manifest, result = self.fixture(root)
            original = (previous/'result.json').read_bytes()
            with patch('lab.continuation.archive_boundary'):
                continued = continue_native(previous, root/'continued', head, backend=Continued)
            self.assertEqual(continued['status'], 'passed', continued)
            self.assertEqual(continued['usage']['observed_raw_tokens'], 143)
            self.assertEqual((previous/'result.json').read_bytes(), original)
            self.assertEqual([row[0] for row in Continued.instances[-1].calls],
                ['one-review-1', 'integration-plan', 'integration-accept'])
            self.assertEqual(continued['stages'][0], result['stages'][0])
            self.assertGreaterEqual(continued['duration_seconds'], result['duration_seconds'])


if __name__ == '__main__':
    unittest.main()
