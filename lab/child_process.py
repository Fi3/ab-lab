"""Keep nested CLI output alive when the program testing it shuts down.

The small supervisor inherits the caller's environment, stdin and OS sandbox.
It changes process ownership, not permissions or the requested model work.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import weakref

from .environment import clean_env

CALL_PREFIX = 'call-'
SUPERVISOR_STARTUP_SECONDS = 5


def codex_requires_usage(arguments):
    """Inspection commands need no model receipt; generation and unknown calls do."""
    inspection = {'agents', 'login', 'logout', 'mcp', 'plugin', 'remote-control',
                  'completion', 'update', 'doctor', 'sandbox', 'debug', 'apply', 'a',
                  'archive', 'delete', 'migrate-rollouts', 'unarchive', 'exec-server',
                  'features', 'help'}
    values = {'-c', '--config', '--enable', '--disable', '--remote', '--remote-auth-token-env',
              '-m', '--model', '--local-provider', '-p', '--profile', '-s', '--sandbox',
              '-C', '--cd', '--add-dir', '-a', '--ask-for-approval', '-i', '--image'}
    args = iter(arguments)
    command = None
    for arg in args:
        if arg == '--':
            break
        if arg in ('--help', '-h', '--version', '-V'):
            return False
        if command is None:
            if arg in values:
                next(args, None)
            elif not arg.startswith('-'):
                command = arg
    return command not in inspection


def supervisor_alive(folder):
    """A filesystem lease works even when the caller has a private PID namespace."""
    try:
        with (folder / 'supervisor.lock').open('rb') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
    except FileNotFoundError:
        return None


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


def supervise(folder, lock_fd=None):
    folder = Path(folder)
    lease = os.fdopen(lock_fd, 'rb') if lock_fd is not None else None
    process = None
    request = {}
    result = {'exit_code': None, 'timed_out': False, 'cancelled': False}
    try:
        request = json.loads((folder / 'request.json').read_text())
        def should_stop():
            result['timed_out'] = time.monotonic() >= request['deadline']
            result['cancelled'] = (folder.parent / 'cancel').exists()
            # A shared filesystem lease survives private PID namespaces and
            # releases on runner death, even when its PID is invisible here.
            with open(request['owner_lock'], 'rb') as owner:
                try:
                    fcntl.flock(owner, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    result['cancelled'] = True
            return result['timed_out'] or result['cancelled']
        if should_stop():
            return
        with (folder / 'stdout').open('ab', buffering=0) as out, (folder / 'stderr').open('ab', buffering=0) as err:
            process = subprocess.Popen(request['argv'], cwd=request['cwd'],
                stdin=sys.stdin.buffer, stdout=out, stderr=err, start_new_session=True,
                env={**clean_env(), **request.get('environment', {})})
            while process.poll() is None:
                if should_stop():
                    stop(process)
                    break
                time.sleep(0.05)
            result['exit_code'] = process.wait()
    except BaseException as exc:
        result['error'] = str(exc)
    finally:
        try:
            if process is not None:
                stop(process)
            if request.get('session_dir'):
                try:
                    from .nested import capture_call_receipts
                    capture_call_receipts(folder, request['harness'])
                except Exception as exc:
                    result['error'] = 'could not record final child usage boundary: ' + str(exc)
            result['finished_at_unix'] = time.time()
            write_result(folder, result)
        finally:
            if lease is not None:
                lease.close()


def launch(config, argv):
    """Relay saved output; killing this relay cannot close the real CLI's pipes."""
    root = Path(config['calls'])
    if (root / 'cancel').exists() or time.monotonic() >= config['deadline']:
        raise ValueError('nested harness launch rejected after benchmark shutdown/deadline')
    folder = Path(tempfile.mkdtemp(prefix=CALL_PREFIX, dir=root))
    request = {'argv': argv, 'cwd': str(Path.cwd()), 'deadline': config['deadline'],
               'owner_lock': config['owner_lock'], 'harness': config['harness'],
               'started_at_unix': time.time()}
    if config['harness'] == 'codex':
        from .nested import prepare_codex_call_state
        request['requires_usage'] = codex_requires_usage(argv[1:])
        home = prepare_codex_call_state(config, folder, argv[1:])
        request['environment'] = {'CODEX_HOME': str(home)}
        request['session_dir'] = str(folder / 'sessions')
        # Persistence supplies measurement receipts without changing the CLI's
        # stdout format or its choice of model, role, or requested work.
        args = iter(argv[1:])
        kept = []
        for arg in args:
            if arg == '--':
                kept.extend([arg, *args])
                break
            if arg != '--ephemeral':
                kept.append(arg)
        request['argv'] = [argv[0], *kept]
    if config['harness'] == 'pi':
        from .pi_sessions import prepare_pi_call
        arguments, sessions = prepare_pi_call(config, folder, argv[1:])
        request['argv'] = [argv[0], *arguments]
        request['session_dir'] = str(sessions)
    (folder / 'request.json').write_text(json.dumps(request))
    for name in ('stdout', 'stderr'):
        (folder / name).touch()
    code = ('import sys; sys.path.insert(0, '+repr(str(Path(__file__).resolve().parents[1]))+'); '
            'from lab.child_process import supervise; supervise(sys.argv[1], int(sys.argv[2]))')
    try:
        with (folder / 'supervisor.pending').open('xb') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            (folder / 'supervisor.pending').replace(folder / 'supervisor.lock')
            # Publish only an already-held lock. Inheriting its descriptor keeps
            # it held across startup and caller death, until the receipt exists.
            with (folder / 'supervisor.stderr').open('wb') as errors:
                worker = subprocess.Popen([sys.executable, '-c', code, str(folder), str(lease.fileno())],
                    stdin=sys.stdin.buffer, stdout=subprocess.DEVNULL, stderr=errors,
                    env=clean_env(), start_new_session=True, pass_fds=(lease.fileno(),))
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
        self.owner_lock = (self.folder / 'owner.lock').open('xb')
        self._release_owner = weakref.finalize(self, self.owner_lock.close)
        fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.finished = {}
        self.missing_since, self.abandoned = {}, {}

    def report(self):
        pending = []
        for folder in self.folder.iterdir():
            if not folder.name.startswith(CALL_PREFIX) or not folder.is_dir() or folder.name in self.finished:
                continue
            try:
                result = json.loads((folder / 'result.json').read_text())
            except (OSError, ValueError):
                alive = supervisor_alive(folder)
                if alive is False:
                    # The writer may have published between our first read and
                    # releasing its lock. Check again before declaring loss.
                    try:
                        result = json.loads((folder / 'result.json').read_text())
                    except (OSError, ValueError):
                        self.abandoned[folder.name] = 'supervisor exited without a valid completion receipt; output retained'
                        continue
                else:
                    started = self.missing_since.setdefault(folder.name, time.monotonic())
                    if alive is None and time.monotonic()-started >= SUPERVISOR_STARTUP_SECONDS:
                        self.abandoned[folder.name] = 'missing supervisor lock and completion receipt after startup grace; output retained'
                    else:
                        pending.append(folder.name)
                    continue
            self.finished[folder.name] = result
            self.abandoned.pop(folder.name, None)
            self.missing_since.pop(folder.name, None)
        errors = [name+': '+str(result) for name, result in self.finished.items()
                  if result.get('error') or result.get('timed_out') or result.get('cancelled')]
        errors.extend(name+': '+reason for name, reason in self.abandoned.items())
        return {'artifacts': str(self.folder), 'completed': dict(self.finished),
                'abandoned': dict(self.abandoned),
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
        self._release_owner()
