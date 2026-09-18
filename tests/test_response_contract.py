"""Whitespace and empty-message regressions from the real parallel run."""
import json
import unittest

from lab.host import Fatal, Rejected, parse_operations
from lab.summary import render
import test_provider as stream
import test_pi as pi_stream


class ResponseContractTests(unittest.TestCase):
    provider = stream.StreamTests.provider
    fake_pi_provider = pi_stream.PiProviderStreamTests.fake_pi_provider

    def test_done_accepts_trailing_spaces_tabs_and_crlf(self):
        for ending in (' ', '\t', ' \t\r\n'):
            with self.subTest(ending=ending):
                self.assertEqual(parse_operations('@standalone done'+ending), [('done',)])

    def test_end_accepts_whitespace_without_stripping_patch_content(self):
        body = '*** Begin Patch\n*** Add File: demo.txt\n+  keep spaces  \n*** End Patch'
        text = '@standalone edit example\n'+body+'\n@standalone end \t\n'
        self.assertEqual(parse_operations(text), [('edit', 'example', body)])
        self.assertEqual(parse_operations('@standalone run -- printf "x"\\ '),
                         [('run', [], 'printf "x"\\ ')])

    def test_quoted_fenced_partial_or_suffixed_markers_still_rejected(self):
        for text in ('> @standalone done ', '```\n@standalone done \n```',
                     'Example: @standalone done ', '@standalone done later',
                     '@standalone edit reason\nbody\n@standalone end later'):
            with self.subTest(text=text), self.assertRaises(Rejected):
                parse_operations(text)

    def test_actual_failure_messages_reach_done_and_keep_usage(self):
        messages = ['@standalone done \n', '']
        p = self.provider([*(stream.message(text) for text in messages), stream.price(), stream.completed()])
        reply = p.turn('t', 'request', 'author', host_request=True)
        self.assertEqual(parse_operations(reply), [('done',)])
        self.assertTrue(p.report()['measurement_complete'])
        self.assertEqual(json.loads((p.artifacts/'turn-0001/messages.json').read_text()), messages)

    def test_empty_trailing_messages_do_not_erase_latest_reply_or_review(self):
        for late in (False, True):
            with self.subTest(late=late):
                events = [stream.message('NO_FINDINGS'), stream.message('FINDINGS\nFix the test.')]
                if late:
                    events += [stream.completed(), stream.message(' \t'), stream.price()]
                else:
                    events += [stream.message(''), stream.price(), stream.completed()]
                p = self.provider(events)
                self.assertEqual(p.turn('t', 'review', 'reviewer'), 'FINDINGS\nFix the test.')
                self.assertTrue(p.report()['measurement_complete'])

    def test_empty_priced_reply_fails_protocol_without_inventing_missing_usage(self):
        for text in ('', ' \t\n'):
            with self.subTest(text=text):
                p = self.provider([stream.message(text), stream.price(), stream.completed()])
                with self.assertRaisesRegex(Fatal, 'no executable request or final reply'):
                    p.turn('t', 'request', 'author')
                self.assertIn('no executable', p.turns[-1]['error'])
                self.assertTrue(p.report()['measurement_complete'])
                self.assertEqual(p.usage.raw, 110)

    def test_failed_generation_is_still_incomplete_even_with_a_counter(self):
        p = self.provider([stream.message('Partial'), stream.price(), stream.completed('failed')])
        with self.assertRaises(Fatal):
            p.turn('t', 'request', 'author')
        self.assertFalse(p.report()['measurement_complete'])

    def test_pi_ignores_whitespace_tail_and_separates_protocol_from_usage(self):
        def event(text):
            return {'type': 'message_end', 'message': {'role': 'assistant',
                'content': [{'type': 'text', 'text': text}]}}
        p = self.fake_pi_provider([event('NO_FINDINGS'), event(' \t'), {'type': 'agent_settled'}])
        self.assertEqual(p.turn('t1', 'review', 'reviewer'), 'NO_FINDINGS')
        self.assertTrue(p.report()['measurement_complete'])
        p = self.fake_pi_provider([event(''), {'type': 'agent_settled'}])
        with self.assertRaises(Fatal):
            p.turn('t1', 'request', 'author')
        self.assertTrue(p.report()['measurement_complete'])

    def test_table_calls_review_checkpoints_reviews_not_verified_features(self):
        text = render([{'status': 'passed', 'usage': {}, 'checkpoints': [{}], 'feature_count': 3}])
        self.assertIn('Reviewed features', text)
        self.assertIn('not independent feature acceptance tests', text)


if __name__ == '__main__':
    unittest.main()
