"""Explicit repetitions of the unchanged workflow in isolated worker processes."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .environment import clean_env
from .context import AUTO_COMPACT_TOKENS, validate_compaction_tokens
from .host import git, save_json
from .review import DEFAULT_MAX_REVIEW_LOOPS, DEFAULT_PRIORITIES, normalize_priorities, normalize_review_loops
from .loops import loop_policy
from .workflow import run, source_hashes

ROOT = Path(__file__).resolve().parents[1]
SHUTDOWN_SECONDS = 20


def failure(config, output, error, *, status='failed', duration=None):
    benchmark = config['benchmark']
    return {'schema': 'agent-behavior-lab/v1', 'status': status, 'output': str(output),
        'benchmark': benchmark['name'], 'factors': config['factors'], 'preset': config['options'].get('preset'),
        'review_priorities': list(config['options'].get('review_priorities', DEFAULT_PRIORITIES)),
        'max_review_loops': config['options'].get('max_review_loops', DEFAULT_MAX_REVIEW_LOOPS),
        'compaction_tokens': config['options']['compaction_tokens'],
        'loop_policy': loop_policy(config['options'].get('loop_options')),
        'feature_count': len(benchmark['features']), 'check_count': len(benchmark['checks']),
        'checkpoints': [], 'checks': [], 'duration_seconds': duration, 'error': error,
        'usage': {'observed_raw_tokens': None, 'measurement_complete': False}}


def collect(config, output, exit_code, duration):
    path = output/'result.json'
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get('status') not in ('passed', 'failed', 'needs_attention') or not isinstance(value.get('usage'), dict):
            raise ValueError('invalid workflow result')
        if exit_code != 0 and value['status'] == 'passed':
            value.update(status='failed', error=f'worker exited with code {exit_code} despite a passed report')
    except (OSError, ValueError) as exc:
        value = failure(config, output,
            f'worker exited with code {exit_code} without a valid result: {exc}; inspect batch logs', duration=duration)
        if not path.exists():
            output.mkdir(exist_ok=True)
            save_json(path, value)
    value['worker_exit_code'] = exit_code
    return value


def run_batch(benchmark, factors, output, repeat, parallel, *, seconds, max_raw, max_turns,
              model='gpt-5.5', effort='xhigh', executable='codex', harness=None,
              scb_check=None, scb_seconds=300, child_codex='codex',
              review_priorities=DEFAULT_PRIORITIES, max_review_loops=DEFAULT_MAX_REVIEW_LOOPS,
              loop_options=None, preset=None, compaction_tokens=AUTO_COMPACT_TOKENS,
              _worker_command=None):
    review_priorities = normalize_priorities(review_priorities)
    max_review_loops = normalize_review_loops(max_review_loops)
    compaction_tokens = validate_compaction_tokens(compaction_tokens)
    if harness not in (None, 'codex', 'pi'):
        raise ValueError(f"harness {harness!r} does not support setting compaction tokens")
    progress_policy = loop_policy(loop_options)
    for name, value in (('repeat', repeat), ('parallel', parallel), ('seconds', seconds),
                        ('max_raw', max_raw), ('max_turns', max_turns)):
        if type(value) is not int or value <= 0:
            raise ValueError(name+' must be a positive integer')
    if not math.isfinite(scb_seconds) or scb_seconds <= 0:
        raise ValueError('scb-check needs a positive finite time limit')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(str(output))
    # Resolve a moving branch only once, before any repetition can start.
    base = git(benchmark['repo'], 'rev-parse', '--verify', benchmark['revision']+'^{commit}').decode().strip()
    output.mkdir(parents=True, exist_ok=False)
    logs = output/'logs'
    logs.mkdir()
    config = {'benchmark': benchmark, 'base_commit': base, 'factors': factors,
        'source_sha256': source_hashes(), 'repeat': repeat, 'parallel': parallel,
        'options': {'seconds': seconds, 'max_raw': max_raw, 'max_turns': max_turns,
            'model': model, 'effort': effort, 'executable': executable, 'harness': harness, 'child_codex': child_codex,
            'scb_check': str(scb_check) if scb_check is not None else None, 'scb_seconds': scb_seconds,
            'review_priorities': list(review_priorities),
            'max_review_loops': max_review_loops,
            'compaction_tokens': compaction_tokens,
            'loop_options': progress_policy, 'preset': preset}}
    config_path = output/'batch-input.json'
    save_json(config_path, config)
    prefix = _worker_command or [sys.executable, '-m', 'lab.batch']
    env = clean_env()
    env['PYTHONPATH'] = str(ROOT)+os.pathsep+env.get('PYTHONPATH', '')
    started = time.monotonic()
    results, active, next_index = [None]*repeat, {}, 0
    interrupted, controller_error = None, None

    def interrupt(signum, _frame):
        nonlocal interrupted
        interrupted = interrupted or signum

    previous = {kind: signal.getsignal(kind) for kind in (signal.SIGINT, signal.SIGTERM)}
    for kind in previous:
        signal.signal(kind, interrupt)

    def stop_active():
        for job in active.values():
            process = job['process']
            if process.poll() is None:
                if 'stop_at' not in job:
                    job['stop_at'] = time.monotonic()
                    try:
                        # The workflow handles SIGINT and closes its own providers
                        # and command groups before saving its partial result.
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass
                elif time.monotonic()-job['stop_at'] >= SHUTDOWN_SECONDS:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def reap():
        for index, job in list(active.items()):
            code = job['process'].poll()
            if code is not None:
                results[index] = collect(config, job['output'], code, time.monotonic()-job['started'])
                del active[index]

    try:
        while active or (next_index < repeat and not interrupted):
            while not interrupted and next_index < repeat and len(active) < parallel:
                index = next_index
                next_index += 1
                name = f'run-{index+1:03d}'
                destination = output/name
                try:
                    with (logs/(name+'.stdout.json')).open('xb') as out, (logs/(name+'.stderr.txt')).open('xb') as err:
                        process = subprocess.Popen([*prefix, str(config_path), str(destination)],
                            stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                            env=env, start_new_session=True)
                    active[index] = {'process': process, 'output': destination, 'started': time.monotonic()}
                except OSError as exc:
                    results[index] = failure(config, destination, 'worker could not start: '+str(exc))
                    destination.mkdir(exist_ok=True)
                    save_json(destination/'result.json', results[index])
            if interrupted:
                stop_active()
            reap()
            if active:
                time.sleep(0.05)
    except (Exception, KeyboardInterrupt) as exc:
        controller_error = str(exc) or 'operator interruption'
    finally:
        try:
            while active:
                stop_active()
                reap()
                if active:
                    time.sleep(0.05)
            for index, value in enumerate(results):
                if value is None:
                    destination = output/f'run-{index+1:03d}'
                    results[index] = failure(config, destination,
                        controller_error or 'batch interrupted before this repetition started', status='not_run')
                    destination.mkdir(exist_ok=True)
                    save_json(destination/'result.json', results[index])
            result = {'schema': 'agent-behavior-lab/batch-v1',
                'status': 'passed' if not interrupted and not controller_error and all(r['status'] == 'passed' for r in results) else 'failed',
                'output': str(output), 'benchmark': benchmark['name'], 'base_commit': base,
                'factors': factors, 'preset': preset, 'repeat': repeat, 'parallel': parallel,
                'review_priorities': list(review_priorities),
                'max_review_loops': max_review_loops,
                'compaction_tokens': compaction_tokens,
                'loop_policy': progress_policy,
                'interrupted': bool(interrupted), 'cancelled_signal': interrupted,
                'duration_seconds': time.monotonic()-started, 'results': results}
            if controller_error:
                result['error'] = controller_error
            save_json(output/'result.json', result)
        finally:
            for kind, handler in previous.items():
                signal.signal(kind, handler)
    return result


def worker(config_path, output):
    config = json.loads(Path(config_path).read_text())
    if config['source_sha256'] != source_hashes():
        raise ValueError('runner source changed since batch admission; no agent started')
    result = run(config['benchmark'], config['factors'], Path(output),
                 _base_commit=config['base_commit'], **config['options'])
    print(json.dumps(result, indent=2))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ValueError('internal batch worker requires its saved input and output directory')
        code = worker(*sys.argv[1:])
    except (OSError, ValueError, RuntimeError) as exc:
        print('batch worker: '+str(exc), file=sys.stderr)
        code = 2
    raise SystemExit(code)
