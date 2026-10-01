"""Native harness context handling must not acquire extra runner generations."""
import unittest
from unittest.mock import Mock, patch

from lab.host import Fatal
import test_context_recovery as context
import test_provider as stream


class NativeContextTests(unittest.TestCase):
    def context_provider(self, stages):
        helper = context.ContextRecoveryTests()
        self.addCleanup(helper.doCleanups)
        provider = helper.provider(stages)
        provider.delegation_disabled = False
        return provider

    def test_large_context_does_not_trigger_runner_compaction(self):
        provider = self.context_provider([context.success()])
        provider.context_usage['thread'] = {'tokens': 200000, 'window': 258400}
        provider.turn('thread', 'Original benchmark request', 'author', writable=True)
        self.assertEqual([method for method, _ in provider.requests], ['turn/start'])
        self.assertEqual(provider.requests[0][1]['input'][0]['text'], 'Original benchmark request')

    def test_context_failure_does_not_receive_a_synthetic_retry(self):
        provider = self.context_provider([context.failure()])
        with self.assertRaises(Fatal):
            provider.turn('thread', 'Original benchmark request', 'author', writable=True)
        self.assertEqual([method for method, _ in provider.requests], ['turn/start'])
        self.assertFalse(provider.turns[0]['recovery_eligible'])

    def test_native_output_is_not_rejected_by_custom_repetition_guard(self):
        helper = stream.StreamTests()
        self.addCleanup(helper.doCleanups)
        output = 'a' * 2048
        provider = helper.provider([stream.message(output), stream.price(), stream.completed()])
        provider.delegation_disabled = False
        with patch('lab.provider.OutputGuard', side_effect=AssertionError('runner guard used')):
            self.assertEqual(provider.turn('t', 'request', 'author', writable=True), output)
        self.assertFalse(provider.sent)

    def test_native_thread_preserves_configured_context_limit_and_collaboration(self):
        provider = self.context_provider([])
        provider.parent_threads = set()
        provider.register_native_thread = Mock()
        provider.rpc = Mock(return_value={'thread': {'id': 'native'}})
        provider.start_thread(writable=True)
        params = provider.rpc.call_args.args[1]
        self.assertNotIn('model_auto_compact_token_limit', params['config'])
        self.assertNotIn('features.multi_agent', params['config'])
        self.assertNotIn('features.multi_agent_v2', params['config'])

    def test_native_stream_ignores_runner_message_timer_but_respects_global_budget(self):
        helper = stream.StreamTests()
        self.addCleanup(helper.doCleanups)
        delta = {'method': 'item/agentMessage/delta', 'params': {
            'threadId': 't', 'turnId': 'u', 'delta': 'progress'}}
        provider = helper.provider([delta, stream.message('done'), stream.price(), stream.completed()])
        provider.delegation_disabled = False
        with patch('lab.provider.MESSAGE_SECONDS', 0):
            self.assertEqual(provider.turn('t', 'request', 'author', writable=True), 'done')
        self.assertFalse(provider.sent)
        provider.max_raw = 50
        with self.assertRaises(Fatal):
            provider.turn('t', 'next request', 'next', writable=True)
        self.assertEqual(len(provider.turns), 1)


if __name__ == '__main__':
    unittest.main()
