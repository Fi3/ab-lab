import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def result(name='run-001', status='passed', raw=1000, complete=True):
    return {'schema': 'agent-behavior-lab/v1', 'status': status, 'output': '/runs/'+name,
        'factors': {'C08': True, 'C25': False}, 'comparison_key': 'same',
        'usage': {'observed_raw_tokens': raw, 'cached_input_tokens': 500,
                  'measurement_complete': complete}, 'duration_seconds': 65,
        'checkpoints': [{'feature': 'one'}], 'feature_count': 2, 'check_count': 2,
        'checks': [{'exit_code': 0, 'timed_out': False, 'cancelled_signal': None}]}


class SummaryTests(unittest.TestCase):
    def render(self, value):
        from lab.summary import render, records
        return render(records(value))

    def test_single_run_reports_status_usage_time_features_and_checks(self):
        table = self.render(result())
        for expected in ('run-001', 'passed', '1,000', '500', 'complete', '1m 05s', '1/2', 'C08'):
            self.assertIn(expected, table)
        self.assertIn('| Run ', table)

    def test_batch_includes_failures_unknown_costs_and_honest_average(self):
        rows = [result(raw=1000), result('run-002', status='failed', raw=50, complete=False),
                result('run-003', status='not_run', raw=None, complete=False)]
        rows[1]['error'] = 'missing usage | still unknown\nnext line'
        table = self.render({'schema': 'agent-behavior-lab/batch-v1', 'results': rows})
        for expected in ('run-001', 'run-002', 'run-003', 'failed', 'not_run', 'incomplete', '1,050'):
            self.assertIn(expected, table)
        self.assertIn('Mean raw tokens: 1,000', table)
        self.assertIn('1 passed, fully measured run', table)
        self.assertIn('missing usage', table)
        self.assertNotIn('350', table)

    def test_different_settings_or_unknown_comparability_do_not_get_a_pooled_mean(self):
        a, b = result(), result('run-002')
        b['factors']['C25'] = True
        self.assertNotIn('Mean raw tokens:', self.render([a, b]))
        b = result('run-002')
        b.pop('comparison_key')
        self.assertNotIn('Mean raw tokens:', self.render([a, b]))

    def test_all_three_code_quality_checkpoints_and_missing_measurements_are_visible(self):
        row = result()
        row['scb_check'] = {'measurements': {
            'before_changes': {'status': 'completed', 'report': {'verbosity': 0.1, 'erosion': 0.2, 'cog_erosion': 0.3}},
            'after_implementation': {'status': 'completed', 'report': {'verbosity': 0.05, 'erosion': 0.1, 'cog_erosion': 0.2}},
            'after_assembly': {'status': 'not_run'}}}
        table = self.render(row)
        for expected in ('Before edits', 'After implementation', 'After assembly', '10.00%', '5.00%', 'not_run'):
            self.assertIn(expected, table)

    def test_old_report_array_with_missing_optional_fields_remains_readable(self):
        table = self.render([{'path': 'old/result.json', 'status': 'failed', 'factors': {},
            'usage': {'observed_raw_tokens': 123, 'measurement_complete': False}, 'error': 'old failure'}])
        self.assertIn('123', table)
        self.assertIn('old failure', table)
        self.assertNotIn('Mean raw tokens:', table)

    def test_root_script_accepts_stdin_multiple_files_and_rejects_bad_json(self):
        command = [sys.executable, str(ROOT/'summarize.py')]
        process = subprocess.run(command, input=json.dumps(result()), text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('run-001', process.stdout)
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)/f'{i}.json' for i in (1, 2)]
            for i, path in enumerate(paths, 1):
                path.write_text(json.dumps(result(f'run-{i:03d}')))
            process = subprocess.run([*command, *map(str, paths)], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn('run-002', process.stdout)
        invalid = subprocess.run(command, input='not json', text=True, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertNotIn('Traceback', invalid.stderr)

    def test_unknown_json_and_empty_batches_are_not_a_successful_summary(self):
        for value in ({'hello': 'world'}, [], {'results': []}):
            with self.assertRaises(ValueError):
                self.render(value)

    def test_the_same_run_is_not_double_counted_when_batch_and_leaf_are_supplied(self):
        row = result()
        with self.assertRaisesRegex(ValueError, 'duplicate run'):
            self.render([{'results': [row]}, row])


if __name__ == '__main__':
    unittest.main()
