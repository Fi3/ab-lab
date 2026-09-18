"""Pi reports individual responses and session totals, not one counter stream."""
from collections import deque
import unittest

from lab.host import Fatal
import test_pi as fixtures


def usage(input, output, cacheRead=0, cacheWrite=0):
    return {'input': input, 'output': output, 'cacheRead': cacheRead, 'cacheWrite': cacheWrite}


class PiUsageTests(unittest.TestCase):
    fake_pi_provider = fixtures.PiProviderStreamTests.fake_pi_provider

    def play(self, provider, messages, totals, *, repeat_end=False, interrupt=False):
        events = deque([{'type': 'message_update', 'usage': usage(0, 0)}])
        for index, tokens in enumerate(messages):
            message = {'role': 'assistant', 'timestamp': index,
                       'content': [{'type': 'text', 'text': '@standalone done'}], 'usage': tokens}
            events.append({'type': 'message_end', 'message': message})
            if repeat_end:
                events.append({'type': 'message_end', 'message': message})
            events.append({'type': 'turn_end', 'message': message})
        events.append({'type': 'agent_settled'})
        thread = provider.threads['t1']
        thread.incoming = lambda timeout: events.popleft() if events else None
        thread.rpc = lambda message, timeout=5: {'success': True, 'data': {'tokens': totals}}
        return provider.turn('t1', 'test', 'author', host_request=True, interrupt=interrupt)

    def test_two_turns_ignore_stream_resets_and_add_smaller_second_response(self):
        p = self.fake_pi_provider([])
        self.play(p, [usage(100, 50, 10, 3)], usage(100, 50, 10, 3), interrupt=True)
        self.assertEqual(p.usage.raw, 163)
        self.play(p, [usage(120, 20, 30, 5)], usage(220, 70, 40, 8), interrupt=True)
        self.assertEqual(p.usage.raw, 338)
        self.assertEqual(p.usage.cached, 40)
        self.assertTrue(p.report()['measurement_complete'], p.report())
        self.assertEqual(sum(m.get('type') == 'abort' for m in p.sent_messages), 2)

    def test_multiple_responses_count_once_despite_duplicate_end_events(self):
        p = self.fake_pi_provider([])
        self.play(p, [usage(100, 10, 20), usage(200, 5, 30)], usage(300, 15, 50), repeat_end=True)
        self.assertEqual(p.usage.raw, 365)
        self.assertTrue(p.report()['measurement_complete'], p.report())

    def test_cache_read_and_write_are_input_but_reasoning_is_not_added_twice(self):
        p = self.fake_pi_provider([])
        tokens = {**usage(100, 20, 30, 5), 'reasoning': 15, 'totalTokens': 155}
        self.play(p, [tokens], {**usage(100, 20, 30, 5), 'total': 155})
        self.assertEqual(p.usage.totals['t1'], (135, 20, 30))

    def test_session_only_usage_includes_other_internal_calls(self):
        p = self.fake_pi_provider([])
        self.play(p, [usage(10, 2)], usage(100, 20, 30))
        self.assertEqual(p.usage.raw, 150)

    def test_missing_session_stats_is_not_silently_marked_complete(self):
        p = self.fake_pi_provider([])
        with self.assertRaisesRegex(Fatal, 'session.*usage|usage.*session'):
            self.play(p, [usage(100, 10)], None)
        self.assertFalse(p.report()['measurement_complete'])

    def test_real_counter_regression_still_fails_closed(self):
        p = self.fake_pi_provider([])
        with self.assertRaisesRegex(Fatal, 'session.*usage|usage.*session'):
            self.play(p, [usage(100, 10)], usage(99, 10))
        self.assertFalse(p.report()['measurement_complete'])
        self.assertEqual(p.usage.raw, 110)

    def test_unchanged_session_total_does_not_cover_a_new_unpriced_response(self):
        p = self.fake_pi_provider([])
        self.play(p, [usage(100, 10)], usage(100, 10))
        with self.assertRaisesRegex(Fatal, 'session.*usage|usage.*session'):
            self.play(p, [{}], usage(100, 10))
        self.assertFalse(p.report()['measurement_complete'])

    def test_malformed_and_inconsistent_usage_are_rejected(self):
        for tokens in (usage(-1, 10), usage(True, 10), {'input': 1},
                       {**usage(100, 20), 'total': 99}):
            with self.subTest(tokens=tokens):
                p = self.fake_pi_provider([])
                with self.assertRaises(Fatal):
                    self.play(p, [usage(100, 20)], tokens)
                self.assertFalse(p.report()['measurement_complete'])


if __name__ == '__main__':
    unittest.main()
