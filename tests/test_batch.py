"""Repeated workflows are separate processes, not concurrent feature agents."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.config import settings
from lab.host import git
from test_scb import benchmark_at, checker_at

ROOT = Path(__file__).resolve().parents[1]


def worker_at(root):
    path = root/'worker.py'
    path.write_text('''import json, pathlib, sys, time
config = json.loads(pathlib.Path(sys.argv[1]).read_text())
out = pathlib.Path(sys.argv[2])
out.mkdir()
index = int(out.name.split('-')[-1])
start = time.time()
(out/'started').touch()
time.sleep(10 if config['benchmark']['name'] == 'slow' else (0.3 if index == 1 else 0.15))
if config['benchmark']['name'] == 'crash-middle' and index == 2:
    sys.exit(7)
failed = config['benchmark']['name'] == 'fail-middle' and index == 2
result = {'status': 'failed' if failed else 'passed', 'output': str(out),
          'factors': config['factors'], 'usage': {'observed_raw_tokens': index*100,
          'measurement_complete': True}, 'start': start, 'finish': time.time(),
          'base_commit': config['base_commit']}
(out/'result.json').write_text(json.dumps(result))
sys.exit(1 if failed else 0)
''')
    return [sys.executable, str(path)]


class BatchTests(unittest.TestCase):
    def setup_batch(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        return root, benchmark_at(root), worker_at(root)

    def execute(self, benchmark, output, command, repeat=5, parallel=2):
        from lab.batch import run_batch
        return run_batch(benchmark, settings({}), output, repeat, parallel,
            seconds=30, max_raw=10000, max_turns=30, model='test', harness='codex',
            _worker_command=command)

    def test_repetitions_obey_parallel_limit_and_keep_ordered_separate_results(self):
        root, bench, command = self.setup_batch()
        result = self.execute(bench, root/'batch', command)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(len(result['results']), 5)
        self.assertEqual([Path(r['output']).name for r in result['results']],
                         [f'run-{n:03d}' for n in range(1, 6)])
        events = sorted([(r['start'], 1) for r in result['results']]+
                        [(r['finish'], -1) for r in result['results']])
        live = peak = 0
        for _, delta in events:
            live += delta
            peak = max(peak, live)
        self.assertEqual(peak, 2)
        for row in result['results']:
            self.assertEqual(row['base_commit'], result['base_commit'])
            self.assertTrue((Path(row['output'])/'result.json').exists())
        self.assertEqual(json.loads((root/'batch/result.json').read_text()), result)

    def test_failed_workflows_are_retained_without_replacement_or_lost_siblings(self):
        root, bench, command = self.setup_batch()
        bench['name'] = 'fail-middle'
        result = self.execute(bench, root/'batch', command, repeat=3, parallel=3)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual([r['status'] for r in result['results']], ['passed', 'failed', 'passed'])
        self.assertEqual(result['results'][1]['usage']['observed_raw_tokens'], 200)
        self.assertEqual(len(list((root/'batch').glob('run-*'))), 3)

    def test_crash_without_result_is_reported_as_unknown_usage_not_zero(self):
        root, bench, command = self.setup_batch()
        bench['name'] = 'crash-middle'
        result = self.execute(bench, root/'batch', command, repeat=3, parallel=2)
        row = result['results'][1]
        self.assertEqual(row['status'], 'failed')
        self.assertIsNone(row['usage']['observed_raw_tokens'])
        self.assertFalse(row['usage']['measurement_complete'])
        self.assertIn('7', row['error'])
        self.assertEqual(result['results'][2]['status'], 'passed')

    def test_existing_output_and_invalid_counts_never_launch_workers(self):
        root, bench, command = self.setup_batch()
        with patch('lab.batch.subprocess.Popen') as spawn:
            with self.assertRaises(FileExistsError):
                self.execute(bench, root, command)
            for repeat, parallel in ((0, 1), (2, 0), (-1, 1)):
                with self.assertRaises(ValueError):
                    self.execute(bench, root/'invalid', command, repeat, parallel)
            spawn.assert_not_called()

    def test_three_actual_workflow_loops_keep_clones_checks_and_start_commit_isolated(self):
        root, bench, _ = self.setup_batch()
        before = git(bench['repo'], 'rev-parse', 'HEAD').decode().strip()
        worker = root/'workflow-worker.py'
        worker.write_text('import json, pathlib, subprocess, sys, time\n'
            +f'sys.path.insert(0, {str(ROOT/"tests")!r})\n'
            +'from test_workflow import FakeCodex\nfrom lab.workflow import run\n'
            +'config=json.loads(pathlib.Path(sys.argv[1]).read_text())\nout=pathlib.Path(sys.argv[2])\n'
            +'if out.name == "run-001":\n'
            +'    subprocess.run(["git", "-C", config["benchmark"]["repo"], "commit", "--allow-empty", "-qm", "advance input"], check=True)\n'
            +'time.sleep(0.1)\n'
            +'result=run(config["benchmark"], config["factors"], out, backend=FakeCodex, '
            +'_base_commit=config["base_commit"], **config["options"])\n'
            +'raise SystemExit(result["status"] != "passed")\n')
        from lab.batch import run_batch
        result = run_batch(bench, settings({}), root/'batch', 3, 3,
            seconds=30, max_raw=10000, max_turns=30, scb_check=checker_at(root),
            _worker_command=[sys.executable, str(worker)])
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['base_commit'], before)
        self.assertNotEqual(git(bench['repo'], 'rev-parse', 'HEAD').decode().strip(), before)
        for row in result['results']:
            out = Path(row['output'])
            manifest = json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['base_commit'], before)
            self.assertEqual(manifest['benchmark']['revision'], 'HEAD')
            self.assertEqual(len(row['checkpoints']), 2)
            self.assertEqual(row['feature_count'], 2)
            self.assertEqual(row['check_count'], 1)
            self.assertEqual(row['scb_check']['status'], 'completed')
            self.assertEqual((out/'checkout/one.py').read_text(), 'value = 2\n')
        self.assertEqual(len({r['comparison_key'] for r in result['results']}), 1)

    def test_interrupt_stops_active_jobs_and_records_unstarted_repetitions(self):
        root, bench, command = self.setup_batch()
        bench['name'] = 'slow'
        program = root/'controller.py'
        program.write_text('from pathlib import Path\nfrom lab.batch import run_batch\n'
            +f'run_batch({bench!r}, {settings({})!r}, Path({str(root/"batch")!r}), 3, 1, '
            +f'seconds=30, max_raw=10000, max_turns=30, _worker_command={command!r})\n')
        process = subprocess.Popen([sys.executable, str(program)],
            env=dict(os.environ, PYTHONPATH=str(ROOT)), start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while not (root/'batch/run-001/started').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((root/'batch/run-001/started').exists())
            process.send_signal(signal.SIGTERM)
            _, err = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, err)
            result = json.loads((root/'batch/result.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['interrupted'])
            self.assertEqual([r['status'] for r in result['results']], ['failed', 'not_run', 'not_run'])
            self.assertFalse((root/'batch/run-002/started').exists())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=3)
            process.stdout.close()
            process.stderr.close()


class BatchCliTests(unittest.TestCase):
    def test_real_cli_retains_three_pre_generation_failures_and_emits_one_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'benchmark.json'
            path.write_text(json.dumps(benchmark_at(root)))
            command = [sys.executable, '-m', 'lab', 'run', str(path), '--out', str(root/'batch'),
                '--seconds', '30', '--max-raw', '10000', '--max-turns', '20',
                '--parallel', '3', '--harness', 'codex', '--scb-check', str(root/'missing-checker')]
            process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 1, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(len(result['results']), 3)
            for row in result['results']:
                self.assertEqual(row['status'], 'failed')
                self.assertIn('scb-check executable not found', row['error'])
                self.assertIsNone(row['usage']['observed_raw_tokens'])
                self.assertFalse((Path(row['output'])/'provider').exists())
            summary = subprocess.run([sys.executable, str(ROOT/'summarize.py')],
                input=process.stdout, text=True, capture_output=True)
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn('failed: 3', summary.stdout)

    def test_report_accepts_batch_json_and_keeps_table_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.json'
            row = {'status': 'passed', 'output': '/runs/one', 'factors': {},
                'usage': {'observed_raw_tokens': 100, 'measurement_complete': True},
                'duration_seconds': 30, 'feature_count': 2}
            path.write_text(json.dumps({'results': [row, dict(row, output='/runs/two')]}))
            output = io.StringIO()
            with patch.object(sys, 'argv', ['lab', 'report', str(path)]), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            rows = json.loads(output.getvalue())
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['duration_seconds'], 30)

    def test_parallel_implies_three_repetitions_and_forwards_all_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'benchmark.json'
            path.write_text(json.dumps(benchmark_at(root)))
            arguments = ['lab', 'run', str(path), '--out', str(root/'batch'),
                '--seconds', '100', '--max-raw', '10000', '--max-turns', '20',
                '--parallel', '3', '--harness', 'pi', '--pi', 'custom-pi',
                '--model', 'unchanged-model', '--effort', 'high', '--off', 'C08,C20',
                '--scb-check', '/checker', '--scb-seconds', '10']
            with patch('lab.__main__.run_batch', return_value={'status': 'passed'}) as batch:
                with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                call = batch.call_args
                self.assertEqual(call.args[3:5], (3, 3))
                self.assertEqual(call.kwargs['model'], 'unchanged-model')
                self.assertEqual(call.kwargs['harness'], 'pi')
                self.assertEqual(call.kwargs['executable'], 'custom-pi')
                self.assertEqual(call.kwargs['scb_check'], '/checker')
                self.assertFalse(call.args[1]['C08'])
                self.assertFalse(call.args[1]['C20'])
                with patch.object(sys, 'argv', arguments+['--repeat', '9']), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                self.assertEqual(batch.call_args.args[3:5], (9, 3))


if __name__ == '__main__':
    unittest.main()
