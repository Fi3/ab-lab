"""Delegation is denied before generation, regardless of selected model."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from lab.codex_children import NativeChildren
from lab.host import Fatal
from lab.nested import DELEGATION_POLICY, NestedUsage
from lab.provider import Codex, Usage
from lab.sandbox import CommandSandbox


class DelegationTests(unittest.TestCase):
    def test_codex_startup_pins_and_verifies_both_collaboration_runtimes(self):
        for model in ('gpt-5.5', 'gpt-5.6-sol'):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = {'forced_login_method': 'chatgpt', 'model_provider': 'openai',
                          'features': {'multi_agent': False, 'multi_agent_v2': False}}
                with patch('lab.provider.subprocess.Popen') as launch, \
                     patch('lab.provider.subprocess.check_output', return_value='codex test'), \
                     patch.object(Codex, '_reader'), \
                     patch.object(Codex, 'rpc', side_effect=[{}, {'account': {'type': 'chatgpt'}},
                                                           {'config': config}]) as rpc:
                    provider = Codex(root, root / 'provider', model, 'high', time.monotonic()+10, 1000, 10,
                                     executable='/bin/true')
                    try:
                        argv = launch.call_args.args[0]
                        self.assertIn(['--disable', 'multi_agent'], [argv[i:i+2] for i in range(len(argv)-1)])
                        self.assertIn(['--disable', 'multi_agent_v2'], [argv[i:i+2] for i in range(len(argv)-1)])
                        self.assertEqual(provider.identity['delegation_policy'], DELEGATION_POLICY)
                        self.assertEqual([call.args[0] for call in rpc.call_args_list],
                                         ['initialize', 'account/read', 'config/read'])
                    finally:
                        provider.close()

    def test_missing_or_enabled_effective_feature_fails_before_starting_a_thread(self):
        for features in ({}, {'multi_agent': False},
                         {'multi_agent': True, 'multi_agent_v2': False},
                         {'multi_agent': False, 'multi_agent_v2': True}):
            with self.subTest(features=features), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch('lab.provider.subprocess.Popen'), patch.object(Codex, '_reader'), \
                     patch.object(Codex, 'rpc', side_effect=[{}, {'account': {'type': 'chatgpt'}},
                                                           {'config': {'features': features}}]) as rpc:
                    with self.assertRaisesRegex(Fatal, 'must disable multi_agent'):
                        Codex(root, root / 'provider', 'any-model', 'high', time.monotonic()+10, 1000, 10,
                              executable='/bin/true')
                    self.assertNotIn('thread/start', [call.args[0] for call in rpc.call_args_list])

    def test_each_thread_pins_disabled_collaboration_in_retained_config(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = object.__new__(Codex)
            provider.repo, provider.artifacts = Path(directory), Path(directory)
            provider.model, provider.effort = 'any-model', 'high'
            provider.sandbox = CommandSandbox(provider.repo, '/bin/true')
            provider.parent_threads = set()
            provider.register_native_thread = Mock()
            provider.rpc = Mock(return_value={'thread': {'id': 'author'}})
            for writable in (False, True):
                provider.start_thread(writable=writable)
                params = provider.rpc.call_args.args[1]
                self.assertIs(params['config']['features.multi_agent'], False)
                self.assertIs(params['config']['features.multi_agent_v2'], False)

    def test_unexpected_native_child_is_reported_as_policy_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = object.__new__(Codex)
            provider.repo = provider.artifacts = Path(directory)
            provider.usage = Usage()
            provider.native_usage = {}
            provider.native_children = NativeChildren()
            provider.native_children.discover('unexpected-child', 'author')
            provider.delegation_disabled = True
            with self.assertRaisesRegex(Fatal, 'native subagent observed despite disabled'):
                provider.observed_raw()

    def test_unexpected_shell_session_cannot_be_accepted_as_a_valid_nested_run(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = object.__new__(Codex)
            provider.repo = provider.artifacts = Path(directory)
            provider.model, provider.effort = 'any-model', 'high'
            provider.usage, provider.native_usage = Usage(), {}
            provider.native_children = NativeChildren()
            provider.parent_threads = {'author'}
            provider.delegation_disabled = True
            provider.nested = NestedUsage(provider.repo, provider.model, provider.effort,
                                           provider.repo / 'sessions')
            provider.nested.observe('unexpected-session', {'type': 'turn_context', 'payload': {
                'model': provider.model, 'effort': provider.effort}})
            with self.assertRaisesRegex(Fatal, 'agent-created model session observed'):
                provider.observed_raw()


if __name__ == '__main__':
    unittest.main()
