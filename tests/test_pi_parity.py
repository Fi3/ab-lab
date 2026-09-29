"""Pi must use the same permission, model and child-accounting controls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

from lab.__main__ import main
from lab.host import Fatal
from lab.provider import Pi
import test_pi as fixtures


class PiParityTests(unittest.TestCase):
    fake_pi_provider = fixtures.PiProviderStreamTests.fake_pi_provider

    def children(self, provider, *, complete=True, errors=None):
        provider.parent_threads = set()
        provider.nested = MagicMock()
        provider.nested.report.return_value = {
            'observed_raw_tokens': 70, 'cached_input_tokens': 30,
            'measurement_complete': complete, 'errors': errors or [],
            'incomplete': [] if complete else ['child not complete and priced'],
        }

    def test_child_usage_is_included_once_in_total_and_budget(self):
        p = self.fake_pi_provider([])
        p.usage.observe_tokens('t1', 100, 20, 50)
        p.turns.append({'status': 'completed'})
        self.children(p)
        self.assertEqual(p.observed_raw(), 190)
        for _ in range(2):
            report = p.report()
            self.assertEqual(report['observed_raw_tokens'], 190)
            self.assertEqual(report['cached_input_tokens'], 80)
            self.assertEqual(report['parent_observed_raw_tokens'], 120)

    def test_unfinished_child_cannot_claim_complete_measurement(self):
        p = self.fake_pi_provider([])
        p.turns.append({'status': 'completed'})
        self.children(p, complete=False)
        self.assertFalse(p.report()['measurement_complete'])

    def test_wrong_child_model_prevents_generation(self):
        p = self.fake_pi_provider([])
        self.children(p, errors=['nested model differs from benchmark'])
        with self.assertRaisesRegex(Fatal, 'nested'):
            p.turn('t1', 'do not generate', 'test')
        self.assertEqual(p.sent_messages, [])

    def test_pending_child_is_settled_before_next_prompt(self):
        p = self.fake_pi_provider([])
        p.settle_children = MagicMock(side_effect=Fatal('pending child'))
        with self.assertRaisesRegex(Fatal, 'pending child'):
            p.turn('t1', 'do not generate', 'test')
        self.assertEqual(p.sent_messages, [])

    def test_primary_model_provider_and_effort_are_verified(self):
        p = self.fake_pi_provider([])
        good = {'success': True, 'data': {
            'model': {'provider': 'openai-codex', 'id': 'test-model'}, 'thinkingLevel': 'xhigh'}}
        p.validate_state(good)
        for data in ({'model': {'provider': 'other', 'id': 'test-model'}, 'thinkingLevel': 'xhigh'},
                     {'model': {'provider': 'openai-codex', 'id': 'wrong'}, 'thinkingLevel': 'xhigh'},
                     {'model': {'provider': 'openai-codex', 'id': 'test-model'}, 'thinkingLevel': 'low'}, {}):
            with self.subTest(data=data), self.assertRaises(Fatal):
                p.validate_state({'success': True, 'data': data})

    def test_pi_and_codex_plan_default_to_same_model(self):
        outputs = []
        for harness in ('pi', 'codex'):
            out = io.StringIO()
            with patch.object(sys, 'argv', ['lab', 'plan', 'benchmarks/work-leaf.json', '--harness', harness]), contextlib.redirect_stdout(out):
                self.assertEqual(main(), 0)
            outputs.append(json.loads(out.getvalue()))
        self.assertEqual(outputs[0]['model'], outputs[1]['model'])
        self.assertEqual(outputs[0]['effort'], outputs[1]['effort'])

    def test_primary_launch_pins_subscription_and_disables_other_extensions(self):
        p = self.fake_pi_provider([])
        p.executable = '/bin/pi'
        argv = p.launch_arguments()
        self.assertIn('--no-extensions', argv)
        for key, value in (('--provider', 'openai-codex'), ('--model', 'test-model'), ('--thinking', 'xhigh')):
            self.assertEqual(argv[argv.index(key) + 1], value)


if __name__ == '__main__':
    unittest.main()
