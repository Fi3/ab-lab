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
    def test_existing_feature_is_reviewed_and_gets_verification_commit(self):
        class Existing(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                self.calls.append((label, thread, prompt, options))
                if label.endswith('-implement'):
                    return 'The requested behavior is already implemented.'
                if '-review-' in label:
                    self.assertion = 'requested behavior is already satisfied' in prompt
                    return 'NO_FINDINGS'
                if label == 'integration-accept':
                    git(self.repo, 'commit', '--allow-empty', '-qm', 'UPDATE Verify the existing feature meets its request')
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

    def test_wrapper_pins_subscription_and_model_and_rejects_overrides(self):
        from lab.nested import pinned_arguments
        config = {'executable': '/usr/bin/codex', 'model': 'gpt-5.5', 'effort': 'xhigh', 'repo': '/tmp/owned'}
        args = pinned_arguments(config, ['exec', 'resume', '--json', 'thread', '-'])
        self.assertIn('forced_login_method="chatgpt"', args)
        self.assertIn('model="gpt-5.5"', args)
        self.assertIn('model_reasoning_effort="xhigh"', args)
        self.assertEqual(args[-5:], ['exec', 'resume', '--json', 'thread', '-'])
        for override in (['--model', 'wrong'], ['-c', 'model_provider="other"'],
                         ['-cmodel_reasoning_effort="low"'], ['--profile', 'other'], ['--oss']):
            with self.assertRaises(ValueError):
                pinned_arguments(config, override+['exec', '-'])

    def test_login_shell_still_resolves_run_local_wrapper(self):
        from lab.nested import CommandEnvironment
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = CommandEnvironment(root, root / 'commands', 'gpt-5.5', 'xhigh', '/bin/true')
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
                guard = CommandEnvironment(root, root / 'commands', 'gpt-5.5', 'xhigh', '/bin/true')
            result = subprocess.run(['/bin/bash', '-c', 'test -z "$OPENAI_API_KEY$CODEX_API_KEY"'], env=guard.env)
            self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
