"""Native capability requests must be confirmed before author generation."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from lab.__main__ import main
from lab.config import FACTORS, NATIVE_CAPABILITY_POLICY, NATIVE_DELEGATION_REQUEST
from lab.host import Fatal
from lab.provider import Codex
from lab.sandbox import CommandSandbox
from lab.workflow import run
from test_core import repo_at
from test_evaluation import NativeAuthor
from test_workflow import FakeCodex
import test_pi as pi_fixtures


class NativeCapabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def provider(self, requested_model='selected-model', requested_effort='xhigh', **response):
        provider = object.__new__(Codex)
        provider.repo = provider.artifacts = self.root
        provider.model, provider.effort = requested_model, requested_effort
        provider.native_capabilities, provider.delegation_disabled = True, False
        provider.identity = {'model': provider.model, 'effort': provider.effort}
        (self.root / 'provider.json').write_text(json.dumps(provider.identity))
        provider.sandbox = CommandSandbox(self.root, '/bin/true')
        provider.parent_threads = set()
        provider.register_native_thread = Mock()
        provider.rpc = Mock(return_value={'thread': {'id': 'author'},
            'model': provider.model, 'reasoningEffort': provider.effort,
            'multiAgentMode': 'explicitRequestOnly', **response})
        return provider

    def test_native_author_confirms_selected_model_and_effort_without_a_runner_allowlist(self):
        for model, effort in (('model-a', 'off'), ('model-b', 'xhigh'),
                              ('model-c', 'max'), ('model-d', 'future-name')):
            with self.subTest(model=model, effort=effort):
                provider = self.provider(model, effort)
                self.assertEqual(provider.start_thread(writable=True), 'author')
                method, params = provider.rpc.call_args.args
                self.assertEqual(method, 'thread/start')
                self.assertNotIn('multiAgentMode', params)
                self.assertEqual(params['model'], model)
                self.assertEqual(params['config']['model_reasoning_effort'], effort)
                for feature in ('multi_agent', 'multi_agent_v2'):
                    self.assertIs(params['config']['features.' + feature], True)
                self.assertEqual(provider.identity['delegation_mode'], 'task-requested')
                self.assertEqual(provider.identity['native_capability_verification'], 'thread/start:model-effort')
                self.assertEqual(json.loads((self.root / 'provider.json').read_text()), provider.identity)

    def test_native_author_rejects_fallback_and_changed_model_or_effort(self):
        for response in ({'model': 'other-model'}, {'reasoningEffort': None},
                         {'reasoningEffort': 'high'}, {'reasoningEffort': 'ultra'}):
            with self.subTest(response=response):
                provider = self.provider(**response)
                with self.assertRaises(Fatal):
                    provider.start_thread(writable=True)
                self.assertEqual(provider.rpc.call_count, 1)

    def test_constructor_preserves_native_xhigh_without_requiring_ultra(self):
        source = self.root / 'source'
        source.mkdir()
        config = {'forced_login_method': 'chatgpt', 'model_provider': 'openai',
                  'model_auto_compact_token_limit': 131072}
        with patch.dict(os.environ, {'CODEX_HOME': str(source), 'PI_CODING_AGENT_DIR': str(source),
                                     'PATH': '/usr/bin:/bin'}), \
             patch('lab.provider.subprocess.Popen') as launch, \
             patch('lab.provider.subprocess.check_output', return_value='codex fixture'), \
             patch.object(Codex, '_reader'), \
             patch.object(Codex, 'rpc', side_effect=[{}, {'account': {'type': 'chatgpt'}}, {'config': config}]):
            provider = Codex(self.root, self.root / 'provider', 'another-model', 'xhigh', 0, 1, 1,
                             executable='/bin/true', allow_delegation=True, native_capabilities=True)
            try:
                self.assertEqual((provider.model, provider.effort), ('another-model', 'xhigh'))
                self.assertIn('model_reasoning_effort="xhigh"', launch.call_args.args[0])
            finally:
                provider.close()

    def test_only_native_author_turns_receive_the_delegation_request(self):
        original = 'Complete the task. Preserve its limits.\n'
        for native, writable in ((True, True), (False, True), (True, False)):
            expected = original + '\n\n' + NATIVE_DELEGATION_REQUEST if native and writable else original
            with self.subTest(harness='codex', native=native, writable=writable):
                provider = self.provider()
                provider.native_capabilities = native
                provider.settle_children, provider.check_limits = Mock(), Mock()
                provider._turn_once = Mock(return_value='Done')
                provider.turn('author', original, 'implement', writable=writable)
                self.assertEqual(provider._turn_once.call_args.args[1], expected)
            with self.subTest(harness='pi', native=native, writable=writable):
                helper = pi_fixtures.PiProviderStreamTests()
                self.addCleanup(helper.doCleanups)
                provider = helper.fake_pi_provider([
                    {'type': 'message_end', 'message': {'role': 'assistant',
                     'content': [{'type': 'text', 'text': 'Done'}], 'usage': {'input': 10, 'output': 2}}},
                    {'type': 'agent_settled'}])
                provider.native_capabilities = native
                provider.turn('t1', original, 'implement', writable=writable)
                self.assertEqual(provider.sent_messages[0]['message'], expected)
                self.assertEqual((provider.artifacts / 'turn-0001/prompt.txt').read_text(), expected)

    def test_controlled_author_and_read_only_review_keep_their_settings(self):
        for native, writable in ((False, True), (True, False)):
            with self.subTest(native=native, writable=writable):
                provider = self.provider(multiAgentMode='explicitRequestOnly')
                provider.native_capabilities = native
                provider.effort = 'high'
                provider.start_thread(writable=writable)
                params = provider.rpc.call_args.args[1]
                self.assertNotIn('multiAgentMode', params)
                self.assertEqual(params['config']['model_reasoning_effort'], 'high')
                for feature in ('multi_agent', 'multi_agent_v2'):
                    if writable:
                        self.assertNotIn('features.' + feature, params['config'])
                    else:
                        self.assertIs(params['config']['features.' + feature], False)

    def plan(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        (self.root / 'package.json').write_text(json.dumps({'dependencies': {
            '@openai/codex': '0.159.3', '@earendil-works/pi-coding-agent': '1.0.0'}}))
        benchmark = {'name': 'capabilities', 'repo': str(self.root), 'revision': 'HEAD',
                     'features': [{'id': 'one', 'request': 'Complete the task.'}], 'checks': ['true']}
        with patch.object(sys, 'argv', ['lab', 'plan', 'unused.json',
                                      '--executor', str(self.root / 'default.json'), *arguments]), \
             patch('lab.__main__.load_benchmark', return_value=benchmark), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main()
        return code, json.loads(output.getvalue()) if code == 0 else errors.getvalue()

    def test_native_plan_keeps_explicit_model_effort_and_no_external_review(self):
        code, plan = self.plan('--preset', 'native', '--model', 'selected-model', '--effort', 'high')
        self.assertEqual(code, 0, plan)
        self.assertEqual((plan['model'], plan['effort']), ('selected-model', 'high'))
        self.assertEqual(plan['max_review_loops'], 0)
        self.assertFalse(plan['loop_policy']['enabled'])
        self.assertEqual(plan['native_capability_policy'], NATIVE_CAPABILITY_POLICY)
        self.assertEqual(NATIVE_CAPABILITY_POLICY, 'native-capabilities-v2')
        self.assertEqual((plan['harness'], plan['harness_version']), ('codex', '0.159.3'))
        self.assertEqual(plan['delegation_mode'], 'task-requested')
        self.assertEqual(plan['native_capability_verification'], 'pending')
        self.assertEqual(plan['native_delegation_request'], NATIVE_DELEGATION_REQUEST)
        self.assertNotIn('capability_conflict', plan)

    def test_plans_accept_harness_efforts_without_a_runner_allowlist(self):
        for harness in ('codex', 'pi'):
            for effort in ('off', 'max', 'future-name'):
                with self.subTest(harness=harness, effort=effort):
                    model = harness + '-selected-model'
                    code, plan = self.plan('--preset', 'native', '--harness', harness,
                                           '--model', model, '--effort', effort)
                    self.assertEqual(code, 0, plan)
                    self.assertEqual((plan['model'], plan['effort']), (model, effort))
                    self.assertEqual(plan['native_delegation_request'], NATIVE_DELEGATION_REQUEST)
                    self.assertNotIn('capability_conflict', plan)

    def test_pi_plan_reports_unsupported_delegation_and_keeps_vanilla(self):
        for arguments in ((), ('--pi-vanilla',)):
            code, plan = self.plan('--preset', 'native', '--harness', 'pi', *arguments)
            self.assertEqual(code, 0, plan)
            self.assertEqual((plan['harness'], plan['harness_version']), ('pi', '1.0.0'))
            self.assertEqual(plan['delegation_mode'], 'unsupported')
            self.assertEqual(plan['pi_vanilla'], bool(arguments))

    def test_native_plan_preserves_explicit_host_owned_tools(self):
        for harness in ('codex', 'pi'):
            code, plan = self.plan('--preset', 'native', '--harness', harness, '--on', 'C17,C20')
            self.assertEqual(code, 0, plan)
            self.assertEqual({key for key, enabled in plan['factors'].items() if enabled}, {'C17', 'C20'})
            self.assertEqual(plan['effort'], 'xhigh')
            self.assertNotIn('native_capability_policy', plan)
            self.assertNotIn('capability_conflict', plan)

    def test_c17_override_keeps_delegation_disabled_during_execution(self):
        benchmark = {'name': 'override', 'repo': str(repo_at(self.root / 'input')),
                     'revision': 'HEAD', 'features': [{'id': 'one', 'request': 'Create one.py.'}],
                     'checks': ['test -f one.py']}
        factors = {**dict.fromkeys(FACTORS, False), 'C17': True, 'C20': True}
        output = self.root / 'run'
        result = run(benchmark, factors, output, 30, 10000, 3,
                     backend=FakeCodex, preset='native', max_review_loops=0)
        self.assertEqual(result['status'], 'passed', result)
        self.assertFalse(FakeCodex.instances[-1].options['allow_delegation'])
        self.assertNotIn('native_capabilities', FakeCodex.instances[-1].options)
        for record in (result, json.loads((output / 'manifest.json').read_text())):
            self.assertNotIn('native_capability_policy', record)

    def test_policy_is_saved_only_for_native_without_changing_the_task_or_reviews(self):
        benchmark = {'name': 'capabilities', 'repo': str(repo_at(self.root / 'input')),
                     'revision': 'HEAD', 'features': [{'id': 'one', 'request': 'Create one.py.'}],
                     'checks': ['test -f one.py']}
        results = []
        for preset in ('native', 'all'):
            output = self.root / preset
            result = run(benchmark, dict.fromkeys(FACTORS, False), output, 30, 10000, 3,
                         backend=NativeAuthor, preset=preset, max_review_loops=0)
            self.assertEqual(result['status'], 'passed', result)
            provider = NativeAuthor.instances[-1]
            self.assertEqual(provider.options.get('native_capabilities', False), preset == 'native')
            self.assertEqual(provider.calls[0][2], 'Create one.py.')
            self.assertEqual(result['reviews'], [])
            self.assertTrue(result['usage']['measurement_complete'])
            for record in (result, json.loads((output / 'manifest.json').read_text())):
                self.assertEqual(record.get('native_capability_policy'),
                                 NATIVE_CAPABILITY_POLICY if preset == 'native' else None)
            results.append(result)
        self.assertNotEqual(results[0]['comparison_key'], results[1]['comparison_key'])


if __name__ == '__main__':
    unittest.main()
