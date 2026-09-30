"""Pinned external tasks and grading preserve the existing agent workflow."""
import copy
import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.batch import run_batch
from lab.config import load_benchmark, settings
from lab.host import Fatal, git
from lab.slopcodebench import ENVIRONMENT, SEED_IGNORE, grade_one, pending, setup
from lab.workflow import run
from test_batch import worker_at
from test_scb import checker_at
from test_workflow import FakeCodex


BRIDGE_STUB = '''import json, os, pathlib, signal, sys, time
assert sys.argv[1] == '-I'
action, config = sys.argv[3], json.loads(sys.argv[4])
problem = config['problem']
if action == 'describe':
    print(json.dumps({'features': [{'id': 'one', 'request': 'FIRST_SPEC create one'},
        {'id': 'two', 'request': 'SECOND_SPEC create two'}],
        'prompt_provenance': {'format': 'upstream-scb-prompts-v1',
        'template': 'configs/prompts/just-solve.jinja', 'template_sha256': 'template-hash',
        'checkpoints': [{'feature': 'one'}, {'feature': 'two'}]}}))
elif action == 'check':
    if problem == 'unavailable':
        print('Docker unavailable', file=sys.stderr); sys.exit(2)
    print(json.dumps({'status': 'ready', 'evaluator': 'test-v1'}))
elif action == 'cleanup':
    if problem == 'cancel_cleanup':
        os.kill(os.getppid(), signal.SIGINT); time.sleep(30)
    print(json.dumps({'status': 'completed'}))
elif action == 'evaluate':
    snapshot = pathlib.Path(sys.argv[5])
    assert (snapshot.parents[2] / 'provider-closed').exists(), 'grading before provider shutdown'
    with (pathlib.Path(config['runner']) / '.venv/evaluated.jsonl').open('a') as stream:
        stream.write(json.dumps({'snapshot': str(snapshot), 'checkpoint': sys.argv[7]}) + '\\n')
    if problem == 'timeout':
        time.sleep(30)
    if problem == 'cancel':
        os.kill(os.getppid(), signal.SIGINT); time.sleep(30)
    if problem == 'crash':
        print('grader crashed', file=sys.stderr); sys.exit(2)
    if problem == 'malformed':
        print('not json'); sys.exit(0)
    if problem == 'infrastructure':
        print(json.dumps({'status': 'error', 'error': 'container failed to start'})); sys.exit(0)
    one = (snapshot / 'one.py').read_text() == 'value = 2\\n'
    two = sys.argv[7] == 'one' or (snapshot / 'two.py').read_text() == (
        'value = 2\\n' if problem == 'needs_final_repair' else 'value = 1\\n')
    passed = one and two
    print(json.dumps({'status': 'passed' if passed else 'failed', 'strict_pass': passed,
        'isolated_pass': two, 'core_pass': one, 'tests': {'passed': int(one)+int(two), 'total': 2},
        'evidence': 'EVALUATOR_SECRET'}))
else:
    raise AssertionError(action)
'''


def repository(path, files):
    path.mkdir()
    git(path, 'init', '--quiet')
    git(path, 'config', 'user.name', 'Test')
    git(path, 'config', 'user.email', 'test@example.invalid')
    git(path, 'config', 'commit.gpgSign', 'false')
    for name, content in files.items():
        destination = path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    git(path, 'add', '.')
    git(path, 'commit', '-qm', 'Initialize fixture')
    return git(path, 'rev-parse', 'HEAD').decode().strip()


class ClosingCodex(FakeCodex):
    def close(self):
        (self.artifacts.parent / 'provider-closed').touch()


class NativeCodex(ClosingCodex):
    def turn(self, thread, prompt, label, **kwargs):
        if label.endswith('-implement') or '-fix-' in label:
            self.calls.append((label, thread, prompt, kwargs))
            name = label.split('-')[0]
            (self.repo / (name + '.py')).write_text('value = 2\n' if '-fix-' in label else 'value = 1\n')
            git(self.repo, 'add', name + '.py')
            git(self.repo, 'commit', '-qm', 'Implement ' + name)
            return 'Implemented.'
        return super().turn(thread, prompt, label, **kwargs)


class SlopCodeBenchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.seed = self.root / 'seed'
        self.dataset = self.root / 'dataset'
        self.runner = self.root / 'runner'
        repository(self.seed, {'.gitignore': SEED_IGNORE})
        dataset_revision = repository(self.dataset, {'README.md': 'Private evaluator fixtures.\n'})
        runner_revision = repository(self.runner, {'.gitignore': '.venv/\n', ENVIRONMENT: 'type: docker\n'})
        self.python = self.runner / '.venv/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.write_text('#!' + sys.executable + '\n' + BRIDGE_STUB)
        self.python.chmod(0o755)
        self.raw = {'name': 'fixture-scb', 'repo': 'seed', 'revision': 'HEAD',
                    'checks': ['test -f one.py && test -f two.py'],
                    'slopcodebench': {'dataset': 'dataset', 'revision': dataset_revision,
                        'problem': 'fixture', 'runner': 'runner', 'runner_revision': runner_revision,
                        'environment': ENVIRONMENT, 'seconds': 2}}
        self.path = self.root / 'benchmark.json'

    def benchmark(self, problem='fixture'):
        self.raw['slopcodebench']['problem'] = problem
        self.path.write_text(json.dumps(self.raw))
        return load_benchmark(self.path)

    def workflow(self, benchmark=None, name='run', backend=ClosingCodex, factors=None, **options):
        return run(benchmark or self.benchmark(), factors or settings({}), self.root / name,
                   30, 10000, 30, backend=backend, **options)

    def evaluated(self):
        path = self.runner / '.venv/evaluated.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_shutdown_failure_retains_result_and_does_not_expose_evaluation(self):
        class BadShutdown(ClosingCodex):
            def close(self):
                raise RuntimeError("provider failed to shut down")
        result = self.workflow(backend=BadShutdown)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["origin"], "provider")
        self.assertFalse(result["usage"]["measurement_complete"])
        self.assertEqual(self.evaluated(), [])
        self.assertTrue((self.root / "run/result.json").exists())

    def test_load_reveals_cumulative_specs_and_preserves_generic_definition(self):
        benchmark = self.benchmark()
        self.assertEqual(benchmark['features'][0]['request'], 'FIRST_SPEC create one')
        self.assertEqual(benchmark['features'][1]['request'],
                         'FIRST_SPEC create one\n\nSECOND_SPEC create two')
        self.assertNotIn('instructions', benchmark)
        provenance = pending(benchmark)['prompt_provenance']
        self.assertEqual(provenance, benchmark['prompt_provenance'])
        self.assertEqual(provenance['template_sha256'], 'template-hash')
        self.assertEqual(provenance['runner_revision'], self.raw['slopcodebench']['runner_revision'])
        self.assertEqual(len(provenance['cumulative_requests']), 2)
        self.assertNotIn('defer_documentation', benchmark)
        self.assertEqual(benchmark['slopcodebench']['dataset'], str(self.dataset))
        self.assertEqual(benchmark['slopcodebench']['runner'], str(self.runner))
        generic = {key: value for key, value in self.raw.items() if key != 'slopcodebench'}
        generic['features'] = [{'id': 'one', 'request': 'Generic request'}]
        self.path.write_text(json.dumps(generic))
        loaded = load_benchmark(self.path)
        self.assertEqual(loaded['features'], generic['features'])
        self.assertNotIn('defer_documentation', loaded)
        self.assertNotIn('slopcodebench', loaded)

    def test_local_instructions_cannot_override_the_upstream_prompt(self):
        self.raw['instructions'] = 'Write our preferred kind of tests.'
        with self.assertRaisesRegex(ValueError, 'unknown benchmark fields'):
            self.benchmark()

    def test_load_rejects_unpinned_dirty_and_conflicting_configuration(self):
        cases = [({'revision': 'HEAD'}, 'full Git'), ({'problem': '../private'}, 'directory name'),
                 ({'seconds': 0}, 'positive integer'), ({'environment': '../outside'}, 'relative')]
        original = copy.deepcopy(self.raw)
        for overrides, error in cases:
            with self.subTest(overrides=overrides):
                self.raw = copy.deepcopy(original)
                self.raw['slopcodebench'].update(overrides)
                self.path.write_text(json.dumps(self.raw))
                with self.assertRaisesRegex(ValueError, error):
                    load_benchmark(self.path)
        self.raw = original
        self.raw['features'] = [{'id': 'extra', 'request': 'unexpected'}]
        with self.assertRaisesRegex(ValueError, 'own checkpoint'):
            self.benchmark()
        del self.raw['features']
        (self.dataset / 'README.md').write_text('edited\n')
        with self.assertRaisesRegex(ValueError, 'local changes'):
            self.benchmark()

    def test_checkpoint_limit_selects_only_the_requested_prefix(self):
        full = self.benchmark()
        self.assertEqual([feature['id'] for feature in full['features']], ['one', 'two'])
        self.assertNotIn('checkpoint_limit', full['slopcodebench'])
        self.assertNotIn('checkpoint_limit', pending(full))
        for limit in (1, 2):
            with self.subTest(limit=limit):
                self.raw['slopcodebench']['checkpoint_limit'] = limit
                benchmark = self.benchmark()
                self.assertEqual(benchmark['features'], full['features'][:limit])
                self.assertEqual(benchmark['slopcodebench']['checkpoint_limit'], limit)
                report = pending(benchmark)
                self.assertEqual(report['checkpoint_limit'], limit)
                self.assertEqual(len(report['prompt_provenance']['checkpoints']), limit)
                self.assertEqual(len(report['prompt_provenance']['cumulative_requests']), limit)
                self.assertEqual(report['checkpoints'], [
                    {'feature': feature['id'], 'status': 'not_run'}
                    for feature in full['features'][:limit]])

    def test_checkpoint_limit_rejects_invalid_or_unavailable_counts(self):
        for limit in (True, False, '1', 1.0, None, 0, -1, 3):
            with self.subTest(limit=limit):
                self.raw['slopcodebench']['checkpoint_limit'] = limit
                with self.assertRaisesRegex(ValueError, 'checkpoint_limit'):
                    self.benchmark()

    def test_one_checkpoint_completes_reviews_repairs_assembly_and_external_grading(self):
        class SingleCheckpointCodex(ClosingCodex):
            def turn(self, thread, prompt, label, **kwargs):
                if label == 'integration-accept':
                    self.calls.append((label, thread, prompt, kwargs))
                    base = git(self.repo, 'rev-list', '--max-parents=0', 'HEAD').decode().strip()
                    git(self.repo, 'reset', '--soft', base)
                    git(self.repo, 'commit', '-qm', 'ADD one')
                    return 'Finished'
                return super().turn(thread, prompt, label, **kwargs)

        self.raw['slopcodebench']['checkpoint_limit'] = 1
        self.raw['checks'] = ['test -f one.py && test ! -f two.py']
        result = self.workflow(backend=SingleCheckpointCodex, scb_check=checker_at(self.root))
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['factors'], settings({}))
        self.assertEqual([item['review_rounds'] for item in result['checkpoints']], [2])
        self.assertEqual(len(result['final_commits']), 1)
        self.assertEqual(result['checks'][0]['exit_code'], 0)
        self.assertTrue(result['usage']['measurement_complete'])
        calls = SingleCheckpointCodex.instances[-1].calls
        self.assertEqual(list(dict.fromkeys(label for label, _, _, _ in calls)), [
            'one-implement', 'one-review-1', 'one-fix-1', 'one-review-2',
            'integration-plan', 'integration-accept'])
        threads = {label: thread for label, thread, _, _ in calls}
        self.assertEqual(threads['one-implement'], threads['one-fix-1'])
        self.assertEqual(threads['one-review-1'], threads['one-review-2'])
        self.assertEqual(threads['integration-plan'], threads['integration-accept'])
        self.assertNotEqual(threads['one-implement'], threads['one-review-1'])
        for _, _, prompt, _ in calls:
            self.assertNotIn('SECOND_SPEC', prompt)
            self.assertNotIn('EVALUATOR_SECRET', prompt)
        report = result['slopcodebench']
        self.assertEqual(report['checkpoint_limit'], 1)
        self.assertTrue(report['solved'])
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['workflow_status'], 'passed')
        self.assertEqual([item['feature'] for item in report['checkpoints']], ['one'])
        self.assertEqual(report['checkpoints'][0]['status'], 'passed')
        self.assertEqual(report['checkpoints'][0]['quality']['status'], 'completed')
        self.assertEqual(report['final']['status'], 'passed')
        self.assertEqual([item['checkpoint'] for item in self.evaluated()], ['one', 'one'])
        for item in [*report['checkpoints'], report['final']]:
            self.assertEqual((Path(item['snapshot']) / 'one.py').read_text(), 'value = 2\n')
            self.assertFalse((Path(item['snapshot']) / 'two.py').exists())
        measurements = result['scb_check']['measurements']
        self.assertEqual(measurements['before_changes']['status'], 'not_applicable')
        self.assertEqual(measurements['after_implementation']['status'], 'completed')
        self.assertEqual(measurements['after_assembly']['status'], 'completed')
        self.assertEqual(result['scb_check']['status'], 'completed')
        self.assertEqual(result, json.loads((self.root / 'run/result.json').read_text()))

    def test_mediated_and_native_workflows_keep_reviews_repairs_and_no_grader_feedback(self):
        for name, backend, factors in (
            ('mediated', ClosingCodex, settings({})),
            ('native', NativeCodex, settings(dict.fromkeys(settings({}), False))),
        ):
            with self.subTest(name=name):
                result = self.workflow(name=name, backend=backend, factors=factors)
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(result['slopcodebench']['solved'])
                self.assertEqual(result['slopcodebench']['workflow_status'], 'passed')
                self.assertEqual([item['review_rounds'] for item in result['checkpoints']], [2, 1])
                self.assertEqual(len(result['final_commits']), 2)
                self.assertEqual(result['checks'][0]['exit_code'], 0)
                self.assertEqual(result['usage']['observed_raw_tokens'], 100)
                calls = backend.instances[-1].calls
                threads = {label: thread for label, thread, _, _ in calls}
                self.assertEqual(threads['one-implement'], threads['one-fix-1'])
                self.assertEqual(threads['one-review-1'], threads['one-review-2'])
                self.assertEqual(threads['integration-plan'], threads['integration-accept'])
                for _, _, prompt, _ in calls:
                    self.assertNotIn('EVALUATOR_SECRET', prompt)
                    self.assertNotIn('strict_pass', prompt)
                    self.assertNotIn(str(self.runner), prompt)
                items = result['slopcodebench']['checkpoints']
                self.assertFalse((Path(items[0]['snapshot']) / 'two.py').exists())
                self.assertEqual((Path(items[0]['snapshot']) / 'one.py').read_text(), 'value = 2\n')
                self.assertTrue(all(item['status'] == 'passed' for item in items))
                self.assertEqual(result, json.loads((self.root / name / 'result.json').read_text()))
        self.assertEqual(len(self.evaluated()), 6)
        self.assertFalse((self.seed / 'one.py').exists())

    def test_reviewed_failure_remains_visible_when_final_assembly_repairs_it(self):
        class FinalRepair(ClosingCodex):
            def turn(self, thread, prompt, label, **kwargs):
                if label == 'integration-accept':
                    (self.repo / 'two.py').write_text('value = 2\n')
                return super().turn(thread, prompt, label, **kwargs)

        result = self.workflow(self.benchmark('needs_final_repair'), backend=FinalRepair)
        report = result['slopcodebench']
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(report['workflow_status'], 'passed')
        self.assertEqual(report['status'], 'completed')
        self.assertFalse(report['solved'])
        self.assertEqual([item['status'] for item in report['checkpoints']], ['passed', 'failed'])
        self.assertEqual(report['final']['status'], 'passed')
        self.assertNotEqual(report['checkpoints'][1]['tree'], report['final']['tree'])

    def test_partial_author_failure_retains_reviewed_grade_and_complete_usage(self):
        class StopsAtSecond(ClosingCodex):
            def turn(self, thread, prompt, label, **kwargs):
                if label == 'two-implement':
                    raise RuntimeError('author stopped')
                return super().turn(thread, prompt, label, **kwargs)

        result = self.workflow(backend=StopsAtSecond)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('author stopped', result['error'])
        self.assertTrue(result['usage']['measurement_complete'])
        self.assertEqual(result['usage']['observed_raw_tokens'], 100)
        report = result['slopcodebench']
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual([item['status'] for item in report['checkpoints']], ['passed', 'not_run'])
        self.assertIsNone(report['final'])
        self.assertEqual(len(self.evaluated()), 1)

    def test_budget_stop_preserves_accepted_work_in_unfinished_checkpoint(self):
        for stopped_feature in ('one', 'two'):
            with self.subTest(stopped_feature=stopped_feature):
                class BudgetStop(ClosingCodex):
                    def turn(self, thread, prompt, label, **kwargs):
                        reply = super().turn(thread, prompt, label, **kwargs)
                        if label == stopped_feature + '-implement':
                            raise Fatal('workflow wall-time/observed-token limit reached')
                        return reply

                before = len(self.evaluated())
                output = self.root / ('budget-' + stopped_feature)
                result = self.workflow(name=output.name, backend=BudgetStop)
                self.assertEqual(result['status'], 'failed')
                self.assertIn('limit reached', result['error'])
                self.assertTrue(result['usage']['measurement_complete'])
                self.assertEqual((output / 'checkout' / (stopped_feature + '.py')).read_text(), 'value = 1\n')
                self.assertFalse(git(output / 'checkout', 'status', '--porcelain'))
                self.assertTrue((output / 'provider-closed').exists())
                report = result['slopcodebench']
                self.assertEqual(report['status'], 'incomplete')
                self.assertIsNone(report['final'])
                reviewed = int(stopped_feature == 'two')
                self.assertEqual(len(result['checkpoints']), reviewed)
                self.assertEqual(len(self.evaluated()) - before, reviewed)
                self.assertEqual([item['status'] for item in report['checkpoints']],
                                 ['passed', 'not_run'] if reviewed else ['not_run', 'not_run'])
                self.assertFalse(any(label.startswith('integration-')
                                     for label, _, _, _ in BudgetStop.instances[-1].calls))
                if reviewed:
                    saved = Path(report['checkpoints'][0]['snapshot'])
                    self.assertEqual((saved / 'one.py').read_text(), 'value = 2\n')
                    self.assertFalse((saved / 'two.py').exists())
                self.assertEqual(result, json.loads((output / 'result.json').read_text()))

    def test_quality_has_empty_baseline_and_every_reviewed_checkpoint(self):
        result = self.workflow(scb_check=checker_at(self.root))
        self.assertEqual(result['status'], 'passed', result)
        measurements = result['scb_check']['measurements']
        self.assertEqual(measurements['before_changes']['status'], 'not_applicable')
        self.assertNotIn('report', measurements['before_changes'])
        self.assertEqual(measurements['after_implementation']['status'], 'completed')
        self.assertEqual(measurements['after_assembly']['status'], 'completed')
        self.assertEqual(result['scb_check']['status'], 'completed')
        for item in result['slopcodebench']['checkpoints']:
            self.assertEqual(item['quality']['status'], 'completed')
            self.assertEqual(item['quality']['commit'], item['commit'])

    def test_missing_evaluator_or_runtime_stops_before_provider_creation(self):
        benchmark = self.benchmark()
        before = len(ClosingCodex.instances)
        self.python.unlink()
        result = self.workflow(benchmark)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('not installed', result['error'])
        self.assertEqual(len(ClosingCodex.instances), before)
        self.python.write_text('#!' + sys.executable + '\n' + BRIDGE_STUB)
        self.python.chmod(0o755)
        result = self.workflow(self.benchmark('unavailable'), name='runtime-failure')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('runtime unavailable', result['error'])
        self.assertEqual(len(ClosingCodex.instances), before)

    def test_failed_and_malformed_evaluators_never_produce_passing_grades(self):
        for problem in ('crash', 'malformed', 'infrastructure'):
            with self.subTest(problem=problem):
                result = self.workflow(self.benchmark(problem), name=problem)
                report = result['slopcodebench']
                self.assertEqual(result['status'], 'failed', result)
                self.assertEqual(report['workflow_status'], 'passed')
                self.assertEqual(report['status'], 'error')
                self.assertIsNot(report['solved'], True)
                self.assertTrue(all(item['status'] == 'error' for item in report['checkpoints']))
                self.assertEqual(report['final']['status'], 'error')

    def test_timeout_is_bounded_and_saved_as_infrastructure_error(self):
        benchmark = self.benchmark('timeout')
        benchmark['slopcodebench']['seconds'] = 0.1
        output = self.root / 'timeout'
        snapshot = output / 'slopcodebench/snapshots/one'
        snapshot.mkdir(parents=True)
        (output / 'provider-closed').touch()
        started = time.monotonic()
        record = grade_one(benchmark['slopcodebench'], {'feature': 'one', 'snapshot': str(snapshot)}, output, 'one')
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(record['status'], 'error')
        self.assertTrue(record['timed_out'])
        self.assertNotIn('strict_pass', record)
        self.assertEqual(record, json.loads((output / 'slopcodebench/evaluation/one/result.json').read_text()))

    def test_comparison_keys_are_stable_and_include_dataset_version(self):
        benchmark = self.benchmark()
        first = self.workflow(benchmark, name='first')
        second = self.workflow(benchmark, name='second', factors=settings({'C13': False}))
        self.assertEqual(first['status'], 'passed', first)
        self.assertEqual(second['status'], 'passed', second)
        self.assertEqual(first['comparison_key'], second['comparison_key'])
        git(self.dataset, 'commit', '--allow-empty', '-qm', 'Updated dataset revision')
        benchmark['slopcodebench']['revision'] = git(self.dataset, 'rev-parse', 'HEAD').decode().strip()
        changed = self.workflow(benchmark, name='changed')
        self.assertEqual(changed['status'], 'passed', changed)
        self.assertNotEqual(first['comparison_key'], changed['comparison_key'])

    def test_batch_admission_preserves_pinned_task_and_all_execution_options(self):
        benchmark = self.benchmark()
        result = run_batch(benchmark, settings({}), self.root / 'batch', 2, 2,
            seconds=30, max_raw=10000, max_turns=30, harness='pi', skip_linearization=True,
            _worker_command=worker_at(self.root))
        self.assertEqual(result['status'], 'passed', result)
        config = json.loads((self.root / 'batch/batch-input.json').read_text())
        self.assertEqual(config['benchmark'], benchmark)
        self.assertEqual(config['options']['harness'], 'pi')
        self.assertTrue(config['options']['skip_linearization'])
        self.assertEqual({row['base_commit'] for row in result['results']}, {config['base_commit']})

    def test_cancellation_stops_remaining_evaluator_calls(self):
        for problem in ('cancel', 'cancel_cleanup'):
            with self.subTest(problem=problem):
                before = len(self.evaluated())
                result = self.workflow(self.benchmark(problem), name=problem)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(len(self.evaluated()) - before, 1)
                report = result['slopcodebench']
                self.assertEqual(report['checkpoints'][0]['cancelled_signal'], signal.SIGINT)
                self.assertEqual(report['checkpoints'][1]['status'], 'not_run')
                self.assertEqual(report['final']['status'], 'not_run')

    def test_repeated_setup_keeps_one_empty_seed_commit(self):
        installed = self.root / 'installed'
        installed.mkdir()
        dataset_revision = repository(installed / 'scb-problems', {'README.md': 'Pinned tasks.\n'})
        runner_revision = repository(installed / 'slop-code-bench', {ENVIRONMENT: 'type: docker\n'})
        run_child = subprocess.run

        def installed_dependencies(argv, **kwargs):
            if argv[0] == 'uv' or (len(argv) > 3 and argv[3] == 'prepare'):
                return subprocess.CompletedProcess(argv, 0)
            return run_child(argv, **kwargs)

        with patch.multiple('lab.slopcodebench', DATASET_REVISION=dataset_revision, RUNNER_REVISION=runner_revision):
            with patch('lab.slopcodebench.subprocess.run', side_effect=installed_dependencies):
                with contextlib.redirect_stdout(io.StringIO()):
                    setup(installed)
                    seed = installed / 'scb-empty'
                    original = git(seed, 'rev-parse', 'HEAD')
                    setup(installed)
        self.assertEqual(git(seed, 'rev-parse', 'HEAD'), original)
        self.assertEqual(git(seed, 'rev-list', '--count', 'HEAD').strip(), b'1')
        self.assertEqual(git(seed, 'ls-tree', '-r', '--name-only', 'HEAD').strip(), b'.gitignore')
        self.assertEqual(git(seed, 'status', '--porcelain'), b'')
        self.assertEqual((seed / '.gitignore').read_text(), SEED_IGNORE)


if __name__ == '__main__':
    unittest.main()
