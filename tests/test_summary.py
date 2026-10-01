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

    def test_slopcodebench_appends_correctness_without_changing_existing_report(self):
        row = result()
        original = self.render(row)
        row['slopcodebench'] = None
        self.assertEqual(self.render(row), original)
        row['slopcodebench'] = {
            'problem': 'code_search', 'status': 'completed', 'solved': False,
            'checkpoints': [
                {'feature': 'checkpoint_1', 'status': 'passed', 'strict_pass': True,
                 'isolated_pass': True, 'core_pass': True, 'tests': {'passed': 8, 'total': 8}},
                {'feature': 'checkpoint_2', 'status': 'failed', 'strict_pass': False,
                 'isolated_pass': True, 'core_pass': False, 'tests': {'passed': 9, 'total': 12}}],
            'final': {'status': 'passed', 'strict_pass': True, 'isolated_pass': True,
                      'core_pass': True, 'tests': {'passed': 12, 'total': 12}}}
        rendered = self.render(row)
        self.assertTrue(rendered.startswith(original+'\n'))
        section = rendered.split('SlopCodeBench correctness:', 1)[1]
        summary = next(line for line in section.splitlines() if 'code_search' in line)
        self.assertEqual([value.strip() for value in summary.split('|')[1:-1]],
                         ['run-001', 'code_search', 'completed', '1/2', 'pass', 'no'])
        checkpoint = next(line for line in section.splitlines() if 'checkpoint_2' in line)
        self.assertEqual([value.strip() for value in checkpoint.split('|')[1:-1]],
                         ['run-001', 'checkpoint_2', 'failed', 'fail', 'pass', 'fail', '9/12'])
        self.assertIn('Final assembly', section)
        self.assertNotIn('Verbosity', section)

    def test_slopcodebench_incomplete_results_keep_unknowns_and_optional_quality(self):
        row = result(status='failed')
        row['slopcodebench'] = {
            'problem': 'partial', 'status': 'incomplete', 'solved': None,
            'checkpoints': [
                {'feature': 'checkpoint_1', 'status': 'passed', 'strict_pass': True,
                 'quality': {'status': 'completed', 'report': {'verbosity': 0.25, 'erosion': 0.125}}},
                {'feature': 'checkpoint_2', 'status': 'error', 'strict_pass': None,
                 'quality': {'status': 'error', 'report': {'verbosity': 0.0}}}],
            'final': None}
        legacy = result('legacy')
        section = self.render([row, legacy]).split('SlopCodeBench correctness:', 1)[1]
        self.assertNotIn('legacy', section)
        summary = next(line for line in section.splitlines() if 'partial' in line)
        self.assertEqual([value.strip() for value in summary.split('|')[1:-1]],
                         ['run-001', 'partial', 'incomplete', '1/2', '—', '—'])
        checkpoint = next(line for line in section.splitlines() if 'checkpoint_2' in line)
        self.assertEqual([value.strip() for value in checkpoint.split('|')[1:-1]],
                         ['run-001', 'checkpoint_2', 'error', '—', '—', '—', '—', '—', '—'])
        self.assertIn('25.00%', section)
        self.assertIn('12.50%', section)
        self.assertNotIn('0.00%', section)
        self.assertNotIn('0/0', section)

    def test_slopcodebench_missing_checkpoint_records_are_not_zero_scores(self):
        row = result(status='failed')
        row['slopcodebench'] = {'problem': 'unavailable', 'status': 'error', 'solved': None}
        section = self.render(row).split('SlopCodeBench correctness:', 1)[1]
        summary = next(line for line in section.splitlines() if 'unavailable' in line)
        self.assertEqual([value.strip() for value in summary.split('|')[1:-1]],
                         ['run-001', 'unavailable', 'error', '—', '—', '—'])

    def test_completed_benchmark_retains_attention_and_only_counts_actual_approvals(self):
        row = result(status='needs_attention')
        row['execution_status'] = 'completed'
        row['feature_count'] = 3
        row['checkpoints'] = [
            {'feature': 'checkpoint_1', 'status': 'approved', 'review_approved': True},
            {'feature': 'checkpoint_2', 'status': 'needs_attention', 'review_approved': False},
            {'feature': 'checkpoint_3', 'status': 'needs_attention', 'review_approved': None}]
        row['slopcodebench'] = {
            'problem': 'code_search', 'status': 'completed', 'solved': False, 'all_tests_passed': True,
            'checkpoints': [dict(feature=f'checkpoint_{i}', status='passed', strict_pass=True,
                                 isolated_pass=True, core_pass=True, tests={'passed': 8, 'total': 8})
                            for i in range(1, 4)],
            'final': {'status': 'passed', 'strict_pass': True}}
        rendered = self.render(row)
        main = next(line for line in rendered.splitlines() if line.startswith('| run-001'))
        columns = [value.strip() for value in main.split('|')[1:-1]]
        self.assertEqual(columns[:3], ['run-001', 'needs_attention', 'completed'])
        self.assertEqual(columns[-2:], ['1/3', '1/2'])
        self.assertNotIn('Mean raw tokens:', rendered)
        section = rendered.split('SlopCodeBench correctness:', 1)[1]
        summary = next(line for line in section.splitlines() if 'code_search' in line)
        self.assertEqual([value.strip() for value in summary.split('|')[1:-1]],
                         ['run-001', 'code_search', 'completed', '3/3', 'pass', 'pass', 'no'])
        for feature, expected in [('checkpoint_1', 'approved'), ('checkpoint_2', 'rejected'),
                                  ('checkpoint_3', 'incomplete')]:
            checkpoint = next(line for line in section.splitlines() if feature in line)
            self.assertEqual([value.strip() for value in checkpoint.split('|')[1:-1]][2:4],
                             ['passed', expected])

    def test_skipped_and_exhausted_reviews_do_not_count_as_approvals(self):
        row = result()
        row['execution_status'] = 'completed'
        row['checkpoints'] = [
            {'feature': 'one', 'status': 'review_skipped', 'review_approved': None},
            {'feature': 'two', 'status': 'review_limit_reached', 'review_approved': None}]
        row['slopcodebench'] = {
            'problem': 'code_search', 'status': 'completed', 'solved': True,
            'all_tests_passed': True,
            'checkpoints': [
                {'feature': 'one', 'status': 'passed', 'strict_pass': True},
                {'feature': 'two', 'status': 'passed', 'strict_pass': True,
                 'attempt_status': 'review_limit_reached', 'review_approved': None}],
            'final': {'status': 'passed', 'strict_pass': True}}
        rendered = self.render(row)
        main = next(line for line in rendered.splitlines() if line.startswith('| run-001'))
        self.assertEqual([value.strip() for value in main.split('|')[1:-1]][-2], '0/2')
        section = rendered.split('SlopCodeBench correctness:', 1)[1]
        for feature, expected in [('one', 'skipped'), ('two', 'limit reached (unreviewed)')]:
            checkpoint = next(line for line in section.splitlines()
                              if feature in [value.strip() for value in line.split('|')])
            self.assertEqual([value.strip() for value in checkpoint.split('|')[1:-1]][2:4],
                             ['passed', expected])

    def test_mixed_legacy_and_attention_reports_keep_unknown_execution_and_review(self):
        legacy = result('legacy')
        row = result(status='needs_attention')
        row['execution_status'] = 'incomplete'
        row['checkpoints'] = [{'feature': 'one', 'status': 'needs_attention'}]
        row['slopcodebench'] = {
            'problem': 'partial', 'status': 'incomplete', 'solved': False, 'all_tests_passed': None,
            'checkpoints': [{'feature': 'one', 'status': 'not_run', 'review_approved': None}],
            'final': None}
        rendered = self.render([legacy, row])
        legacy_line = next(line for line in rendered.splitlines() if line.startswith('| legacy'))
        self.assertEqual([value.strip() for value in legacy_line.split('|')[1:-1]][2], '—')
        self.assertEqual([value.strip() for value in legacy_line.split('|')[1:-1]][-2], '1/2')
        current_line = next(line for line in rendered.splitlines() if line.startswith('| run-001'))
        self.assertEqual([value.strip() for value in current_line.split('|')[1:-1]][-2], '0/2')
        section = rendered.split('SlopCodeBench correctness:', 1)[1]
        summary = next(line for line in section.splitlines() if 'partial' in line)
        self.assertEqual([value.strip() for value in summary.split('|')[1:-1]][-2:], ['—', 'no'])


if __name__ == '__main__':
    unittest.main()
