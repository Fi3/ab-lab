"""Keep nested CLI output alive when the program testing it shuts down.

The small supervisor inherits the caller's environment, stdin and OS sandbox.
It changes process ownership, not permissions or the requested model work.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from .environment import clean_env


def write_result(folder, result):
    temporary = folder / 'result.pending'
    temporary.write_text(json.dumps(result))
    temporary.replace(folder / 'result.json')


def stop(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


def supervise(folder):
    folder = Path(folder)
    process = None
    result = {'exit_code': None, 'timed_out': False, 'cancelled': False}
    try:
        request = json.loads((folder / 'request.json').read_text())
        def should_stop():
            result['timed_out'] = time.monotonic() >= request['deadline']
            result['cancelled'] = (folder.parent / 'cancel').exists()
            try:
                os.kill(request['owner_pid'], 0)
            except ProcessLookupError:
                result['cancelled'] = True
            return result['timed_out'] or result['cancelled']
        if should_stop():
            return
        with (folder / 'stdout').open('ab', buffering=0) as out, (folder / 'stderr').open('ab', buffering=0) as err:
            process = subprocess.Popen(request['argv'], cwd=request['cwd'],
                stdin=sys.stdin.buffer, stdout=out, stderr=err, start_new_session=True)
            while process.poll() is None:
                if should_stop():
                    stop(process)
                    break
                time.sleep(0.05)
            result['exit_code'] = process.wait()
    except BaseException as exc:
        result['error'] = str(exc)
    finally:
        if process is not None:
            stop(process)
        result['finished_at_unix'] = time.time()
        write_result(folder, result)


def launch(config, argv):
    """Relay saved output; killing this relay cannot close the real CLI's pipes."""
    root = Path(config['calls'])
    if (root / 'cancel').exists() or time.monotonic() >= config['deadline']:
        raise ValueError('nested Codex launch rejected after benchmark shutdown/deadline')
    folder = Path(tempfile.mkdtemp(prefix='call-', dir=root))
    request = {'argv': argv, 'cwd': str(Path.cwd()), 'deadline': config['deadline'],
               'owner_pid': config['owner_pid'], 'started_at_unix': time.time()}
    (folder / 'request.json').write_text(json.dumps(request))
    for name in ('stdout', 'stderr'):
        (folder / name).touch()
    code = ('import sys; sys.path.insert(0, '+repr(str(Path(__file__).resolve().parents[1]))+'); '
            'from lab.child_process import supervise; supervise(sys.argv[1])')
    try:
        with (folder / 'supervisor.stderr').open('wb') as errors:
            worker = subprocess.Popen([sys.executable, '-c', code, str(folder)],
                stdin=sys.stdin.buffer, stdout=subprocess.DEVNULL, stderr=errors,
                env=clean_env(), start_new_session=True)
    except BaseException as exc:
        write_result(folder, {'exit_code': None, 'error': str(exc)})
        raise
    with (folder / 'stdout').open('rb') as out, (folder / 'stderr').open('rb') as err:
        destinations = [sys.stdout.buffer, sys.stderr.buffer]
        while True:
            finished = worker.poll() is not None
            for index, source in enumerate((out, err)):
                while data := source.read(65536):
                    if destinations[index] is not None:
                        try:
                            destinations[index].write(data)
                            destinations[index].flush()
                        except (BrokenPipeError, OSError):
                            destinations[index] = None
            if finished:
                break
            time.sleep(0.02)
    try:
        result = json.loads((folder / 'result.json').read_text())
    except (OSError, ValueError):
        return 1
    return result.get('exit_code') if result.get('exit_code') is not None else 1


class Children:
    def __init__(self, folder, deadline):
        self.folder, self.deadline = Path(folder), deadline
        self.folder.mkdir()
        self.finished = {}

    def report(self):
        pending = []
        for folder in self.folder.iterdir():
            if not folder.is_dir() or folder.name in self.finished:
                continue
            try:
                self.finished[folder.name] = json.loads((folder / 'result.json').read_text())
            except (OSError, ValueError):
                pending.append(folder.name)
        errors = [name+': '+str(result) for name, result in self.finished.items()
                  if result.get('error') or result.get('timed_out') or result.get('cancelled')]
        return {'artifacts': str(self.folder), 'completed': dict(self.finished),
                'pending': pending, 'errors': errors,
                'measurement_complete': not pending and not errors}

    def settle(self, check=None):
        while self.report()['pending']:
            if check is not None:
                check()
            if time.monotonic() >= self.deadline:
                self.close()
                break
            time.sleep(0.05)
        return self.report()

    def close(self):
        (self.folder / 'cancel').touch(exist_ok=True)
        end = time.monotonic()+4
        while self.report()['pending'] and time.monotonic() < end:
            time.sleep(0.05)
