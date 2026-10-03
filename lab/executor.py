"""Build the public executor recipe and run workflows in it; grading stays outside.

The workflow, providers and all their descendants share one container. This
avoids substituting mediated tools for native tools in experimental conditions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from multiprocessing.connection import Client, Listener
from multiprocessing import get_context

from .environment import clean_env

SCHEMA = 'agent-behavior-lab/executor-build-v1'
BACKEND_VERSION = 'whole-workflow-host-grading-v1'
PRIVATE_ENV = 'AGENT_LAB_EXECUTOR_PRIVATE'
RECEIPT_ENV = 'AGENT_LAB_EXECUTOR_RECEIPT'
MAX_MESSAGE = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / 'executors' / 'default.json'
BUILD_FILES = ('.dockerignore', 'Dockerfile', 'default.json', 'package.json', 'package-lock.json', 'requirements.lock')


def write_json(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def docker(*args, **options):
    return subprocess.run(['docker', *map(str, args)], check=True, **options)


def load_lock(path):
    """Build once per recipe identity; reuse the local Docker cache thereafter."""
    path = Path(path).resolve()
    lock = json.loads(path.read_text())
    if lock.get('schema') != SCHEMA:
        raise ValueError('unsupported executor build definition')
    if 'image' in lock:
        raise ValueError('executor requires a public build recipe, not a local image ID')
    if lock['platform'] != 'linux/amd64':
        raise ValueError('executor supports linux/amd64')
    inputs = {name: hashlib.sha256((path.parent / name).read_bytes()).hexdigest()
              for name in BUILD_FILES}
    inputs['profile'] = fingerprint(lock)
    build_hash = fingerprint(inputs)
    tag = 'agent-lab/executor:' + build_hash
    try:
        probe = docker('image', 'inspect', tag, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        # Build context contains only the public recipe, never the checkout,
        # credentials, host installations or benchmark data.
        docker('build', '--platform', lock['platform'], '--label',
               'agent-lab.recipe=' + build_hash, '-t', tag, path.parent,
               stdout=sys.stderr)
        probe = docker('image', 'inspect', tag, capture_output=True, text=True)
    identity = json.loads(probe.stdout)[0]
    platform = identity['Os'] + '/' + identity['Architecture']
    if platform != lock['platform'] or identity['Config']['Labels'].get('agent-lab.recipe') != build_hash:
        raise ValueError('executor image differs from its build definition')
    return {**lock, 'image': identity['Id'], 'build_sha256': build_hash,
            'uid': os.getuid(), 'gid': os.getgid()}


def execution_record():
    """No historical evidence is rewritten or inferred from the current host."""
    path = os.environ.get(RECEIPT_ENV)
    if path:
        return json.loads(Path(path).read_text())
    return {'mode': 'host-v1', 'environment_identity': None}


def normalize_runtime(value):
    """Private socket/auth paths vary per run, but do not define a condition."""
    private = os.environ.get(PRIVATE_ENV)
    if not private:
        return value
    return json.loads(json.dumps(value).replace(private, '<EXECUTOR_PRIVATE>'))


def container_argv(lock, name, mounts, command, private=None):
    argv = ['docker', 'run', '--name', name, '--init', '--network', 'host',
            '--cap-drop', 'ALL', '--security-opt', 'seccomp=unconfined',
            '--security-opt', 'systempaths=unconfined',
            '--user', f"{lock['uid']}:{lock['gid']}", '--workdir', lock['runner_root']]
    for source, destination, writable in mounts:
        # Docker's --mount syntax cannot represent commas in bind paths.
        if ',' in str(source) or ',' in str(destination):
            raise ValueError('executor mount paths cannot contain commas')
        argv += ['--mount', f'type=bind,src={source},dst={destination}' + ('' if writable else ',readonly')]
    for key, value in lock['environment'].items():
        argv += ['--env', f'{key}={value}']
    if private:
        argv += ['--env', f'{PRIVATE_ENV}={private}',
                 '--env', f'{RECEIPT_ENV}={private}/execution.json',
                 '--env', f'CODEX_HOME={private}/auth/codex',
                 '--env', f'PI_CODING_AGENT_DIR={private}/auth/pi']
    # No host Docker socket, home, /tmp, caches or benchmark datasets are mounted.
    return [*argv, lock['image'], *command]


def runner_mounts(lock, verification=False):
    """Runner revisions remain independent of the pinned project toolchain."""
    directories = ('lab', 'benchmarks', 'tests', 'examples') if verification else ('lab', 'benchmarks')
    return [(ROOT / name, Path(lock['runner_root']) / name, False) for name in directories]


def quality_proxy(lock, folder, output):
    """Let the separate grader use the recipe's checker without host installs."""
    path = folder / 'scb-check'
    prefix = ['docker', 'run', '--rm', '--network', 'none', '--user',
              f"{lock['uid']}:{lock['gid']}", '--workdir', '/work',
              '--mount', f'type=bind,src={output},dst={output},readonly']
    path.write_text(f'#!{sys.executable}\nimport os, subprocess, sys\n'
        f'argv = {prefix!r} + ["--mount", "type=bind,src=" + os.getcwd() + ",dst=/work,readonly",'
        f' {lock["image"]!r}, {lock["quality"]!r}] + sys.argv[1:]\n'
        'sys.exit(subprocess.run(argv).returncode)\n')
    path.chmod(0o700)
    return {'executable': str(path),
            'executable_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class GradingBridge:
    """Expose only the admitted evaluator lifecycle, never a host shell."""
    def __init__(self, folder, benchmark, output, checker=None):
        self.folder, self.benchmark, self.output = Path(folder), benchmark, Path(output)
        self.key = secrets.token_bytes(32)
        (self.folder / 'bridge.key').write_bytes(self.key)
        self.listener = Listener(str(self.folder / 'bridge.sock'), family='AF_UNIX', authkey=self.key)
        self.adapter = None
        self.finished = False
        self.error = None
        self.checker = checker
        # Evaluators use signal handlers and must run in a process main thread.
        self.process = get_context('fork').Process(target=self.serve, daemon=True)
        self.process.start()

    def dispatch(self, request):
        from .evaluation import adapter_type
        if request.get('benchmark') != self.benchmark or request.get('output') != str(self.output):
            raise ValueError('grading request differs from admitted workflow')
        method = request['method']
        if method not in ('start', 'baseline_measurement', 'checkpoint', 'final', 'evaluate'):
            raise ValueError('unknown evaluator lifecycle operation')
        if self.finished or (method == 'start') != (self.adapter is None):
            raise ValueError('invalid evaluator lifecycle order')
        result = request['result']
        if not isinstance(result, dict):
            raise ValueError('invalid evaluator state')
        if self.adapter is None:
            self.adapter = adapter_type(self.benchmark)(self.benchmark, self.output, result)
        else:
            self.adapter.result.clear()
            self.adapter.result.update(result)
        args = request['args']
        if method in ('checkpoint', 'final') and args[0] != str(self.output / 'checkout'):
            raise ValueError('evaluator checkout differs from admitted workflow')
        if method == 'evaluate':
            self.finished = True
        if method in ('checkpoint', 'final'):
            args[0] = Path(args[0])
        quality = self.adapter.result.get('scb_check', {})
        original = quality.get('tool')
        checkpoint_tool = args[2] if method == 'checkpoint' else None
        if self.checker:
            if original:
                quality['tool'] = {**original, **self.checker}
            if checkpoint_tool:
                args[2] = {**checkpoint_tool, **self.checker}
        try:
            value = getattr(self.adapter, method)(*args)
        finally:
            if self.checker and original:
                quality['tool'] = original
            if method == 'checkpoint':
                args[2] = checkpoint_tool
        if method in ('checkpoint', 'final'):
            args[0] = str(args[0])
        return {'value': value, 'result': self.adapter.result, 'args': args}

    def serve(self):
        # Source capture must not execute callbacks from agent-owned Git
        # configuration on the host. These overrides also reach grader children.
        os.environ.update(GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='core.fsmonitor',
                          GIT_CONFIG_VALUE_0='false', GIT_CONFIG_KEY_1='core.hooksPath',
                          GIT_CONFIG_VALUE_1='/dev/null')
        while True:
            try:
                connection = self.listener.accept()
            except (OSError, EOFError):
                return
            try:
                request = json.loads(connection.recv_bytes(MAX_MESSAGE))
                if request == {'method': 'close'}:
                    return
                try:
                    response = self.dispatch(request)
                except (Exception, KeyboardInterrupt) as exc:
                    response = {'error': str(exc) or type(exc).__name__}
                connection.send_bytes(json.dumps(response).encode())
            except (OSError, EOFError, ValueError) as exc:
                self.error = str(exc)
            finally:
                connection.close()

    def close(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=2)
        self.listener.close()


class RemoteEvaluator:
    def __init__(self, benchmark, output, result, adapter):
        self.benchmark, self.output, self.result = benchmark, Path(output), result
        self.config_key = adapter.config_key
        self.retain_stopped_attempts = adapter.retain_stopped_attempts

    def invoke(self, method, *args):
        folder = Path(os.environ[PRIVATE_ENV])
        request = {'method': method, 'benchmark': self.benchmark, 'output': str(self.output),
                   'result': self.result, 'args': [str(v) if isinstance(v, Path) else v for v in args]}
        with Client(str(folder / 'bridge.sock'), family='AF_UNIX',
                    authkey=(folder / 'bridge.key').read_bytes()) as connection:
            connection.send_bytes(json.dumps(request).encode())
            response = json.loads(connection.recv_bytes(MAX_MESSAGE))
        if 'error' in response:
            raise RuntimeError('host evaluator: ' + response['error'])
        merge_state(self.result, response['result'])
        return response

    def start(self, base, manifest, deadline):
        response = self.invoke('start', base, manifest, deadline)
        manifest.clear()
        manifest.update(response['args'][1])

    def baseline_measurement(self, base):
        return self.invoke('baseline_measurement', base)['value']

    def checkpoint(self, checkout, checkpoint, quality_tool, deadline):
        return self.invoke('checkpoint', checkout, checkpoint, quality_tool, deadline)['value']

    def final(self, checkout):
        return self.invoke('final', checkout)['value']

    def evaluate(self):
        return self.invoke('evaluate')['value']


def merge_state(target, source):
    """Preserve workflow references to nested measurement/state dictionaries."""
    for key in list(target):
        if key not in source:
            del target[key]
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_state(target[key], value)
        else:
            target[key] = value


def copy_auth(folder):
    """Runtime credentials are private mounts, never part of the frozen image."""
    from .nested import NativeState
    sources = {
        'codex': (Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')),
                  (*NativeState.codex_files,)),
        'pi': (Path(os.environ.get('PI_CODING_AGENT_DIR', Path.home() / '.pi/agent')),
               ('auth.json', 'settings.json', 'models.json', 'models-store.json', 'AGENTS.md',
                'AGENTS.override.md', 'SYSTEM.md', 'APPEND_SYSTEM.md')),
    }
    for name, (source, names) in sources.items():
        destination = folder / 'auth' / name
        destination.mkdir(parents=True, mode=0o700)
        # Only runtime auth comes from the host. Provider settings/resources
        # come from the public recipe, never the operator's personal files.
        for filename in names:
            origin = source / filename if filename == 'auth.json' else None
            frozen = folder / 'frozen-auth' / name / filename
            origin = origin if origin is not None else frozen
            if origin.is_file():
                shutil.copyfile(origin, destination / filename)
                (destination / filename).chmod(0o600)
        for resource in (NativeState.codex_resources if name == 'codex' else
                         ('extensions', 'skills', 'prompts', 'themes', 'npm')):
            (destination / resource).symlink_to('/opt/agent-lab/provider-config/' + name + '/' + resource)


def stage_auth(lock, private):
    name = 'agent-lab-config-' + uuid.uuid4().hex
    docker('create', '--name', name, lock['image'], '/usr/bin/true', stdout=subprocess.DEVNULL)
    try:
        docker('cp', name + ':/opt/agent-lab/provider-config', private / 'frozen-auth', stdout=subprocess.DEVNULL)
    finally:
        docker('rm', name, stdout=subprocess.DEVNULL)
    copy_auth(private)


def pinned_input(benchmark, base, destination):
    """Export only the pinned commit's reachable Git history, without host assets."""
    from .host import git
    destination.mkdir()
    fmt = git(benchmark['repo'], 'rev-parse', '--show-object-format').decode().strip()
    git(destination, 'init', '--quiet', '--object-format=' + fmt)
    git(destination, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head',
        '--no-recurse-submodules', '--', benchmark['repo'], base)
    git(destination, 'checkout', '--quiet', '--detach', base)


def run_pinned(benchmark, factors, output, lock_path, options, base=None):
    output = Path(output).resolve()
    existed = output.exists()
    try:
        return _run_pinned(benchmark, factors, output, lock_path, dict(options), base)
    except (Exception, KeyboardInterrupt) as exc:
        if not existed and output.is_dir() and not (output / 'result.json').exists():
            write_json(output / 'result.json', {'schema': 'agent-behavior-lab/v1', 'status': 'failed',
                'benchmark': benchmark['name'], 'output': str(output), 'factors': factors,
                'error': str(exc) or 'executor interrupted',
                'failure': {'origin': 'operator' if isinstance(exc, KeyboardInterrupt) else 'environment',
                            'stage': 'executor', 'message': str(exc)},
                'execution_environment': {'mode': 'rebuilt-executor-v1', 'profile': str(lock_path)},
                'usage': {'observed_raw_tokens': None, 'measurement_complete': False}})
        raise


def _run_pinned(benchmark, factors, output, lock_path, options, base=None):
    from .host import git
    lock = load_lock(lock_path)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(str(output))
    base = git(benchmark['repo'], 'rev-parse', '--verify', (base or benchmark['revision']) + '^{commit}').decode().strip()
    # Create a brand-new output on the host so bind mounting it never exposes
    # siblings. The inner workflow admits this directory only while empty.
    output.mkdir(parents=True, exist_ok=False)
    name = 'agent-lab-' + uuid.uuid4().hex
    # Keep Unix socket addresses below the platform's path-length ceiling.
    with tempfile.TemporaryDirectory(prefix='agent-lab-exec-') as temporary:
        private = Path(temporary)
        imported = private / 'input'
        pinned_input(benchmark, base, imported)
        defaults = lock.get('harnesses', {})
        if options['executable'] == 'codex':
            options['executable'] = defaults.get('codex', 'codex')
        if options['child_codex'] == 'codex':
            options['child_codex'] = defaults.get('codex', 'codex')
        identity = {'mode': 'rebuilt-executor-v1', 'image': lock['image'], 'platform': lock['platform'],
                    'backend_version': BACKEND_VERSION,
                    'environment_identity': lock['build_sha256'],
                    'network': 'host', 'resource_limits': 'host defaults',
                    'runner_root': lock['runner_root'], 'grading': 'host adapter',
                    'kernel': os.uname().release, 'harnesses': defaults}
        write_json(private / 'execution.json', identity)
        write_json(private / 'request.json', {'benchmark': benchmark, 'factors': factors,
                   'output': str(output), 'options': options, 'base': base})
        # Stage public configuration and inject only runtime authentication.
        stage_auth(lock, private)
        bridge = GradingBridge(private, benchmark, output, quality_proxy(lock, private, output))
        argv = container_argv(lock, name,
            [*runner_mounts(lock), (private, private, True),
             (imported, benchmark['repo'], False), (output, output, True)],
            [lock['python'], '-m', 'lab.executor', '_workflow', str(private)], private)
        previous = {}
        process = None
        def interrupt(signum, _frame):
            if process is not None:
                subprocess.run(['docker', 'kill', '--signal', signal.Signals(signum).name, name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        try:
            with (private / 'stdout').open('wb') as out, (private / 'stderr').open('wb') as err:
                process = subprocess.Popen(argv, stdout=out, stderr=err, env=clean_env())
                for kind in (signal.SIGINT, signal.SIGTERM):
                    previous[kind] = signal.signal(kind, interrupt)
                code = process.wait()
            path = output / 'result.json'
            if not path.is_file():
                raise RuntimeError('pinned workflow did not publish a result: ' +
                                   (private / 'stderr').read_text(errors='replace')[-4000:])
            result = json.loads(path.read_text())
            if code != 0 and result.get('status') == 'passed':
                raise RuntimeError(f'pinned workflow exited {code} despite a passed result')
            return result
        finally:
            for kind, handler in previous.items():
                signal.signal(kind, handler)
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            bridge.close()
            # Retain launch failures as well as successful workflow evidence.
            for filename in ('stdout', 'stderr', 'execution.json'):
                source = private / filename
                if source.exists():
                    shutil.copyfile(source, output / ('executor-' + filename))


def inner_workflow(folder):
    from .provider import Codex, Pi
    from .workflow import run
    request = json.loads((Path(folder) / 'request.json').read_text())
    options = request['options']
    backend = Pi if options.get('harness') == 'pi' else Codex
    result = run(request['benchmark'], request['factors'], request['output'], backend=backend,
                 _base_commit=request['base'], _admitted_output=True, **options)
    return int(result['status'] != 'passed')


def exec_command(lock_path, command):
    lock = load_lock(lock_path)
    name = 'agent-lab-probe-' + uuid.uuid4().hex
    try:
        return subprocess.run(container_argv(lock, name, runner_mounts(lock, True), command), env=clean_env()).returncode
    finally:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def doctor(lock_path, output, harness, native=False, model=None):
    """Exercise the actual provider initialization with no model generation."""
    from .host import git
    lock = load_lock(lock_path)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    name = 'agent-lab-doctor-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='agent-lab-doctor-') as directory:
        private = Path(directory)
        source = private / 'input'
        source.mkdir()
        git(source, 'init', '-q')
        stage_auth(lock, private)
        write_json(private / 'execution.json', {'mode': 'rebuilt-executor-v1', 'image': lock['image'],
                                               'environment_identity': lock['build_sha256']})
        argv = container_argv(lock, name, [*runner_mounts(lock), (private, private, True),
            (source, '/tmp/agent-lab-doctor-repo', native), (output, output, True)],
            [lock['python'], '-m', 'lab', 'doctor', '--repo', '/tmp/agent-lab-doctor-repo',
             '--out', str(output / 'provider'), '--harness', harness,
             '--codex', lock.get('harnesses', {}).get('codex', 'codex'),
             *(['--model', model] if model else []),
             *(['--native'] if native else [])], private)
        try:
            with (output / 'stdout.json').open('xb') as out, (output / 'stderr.txt').open('xb') as err:
                code = subprocess.run(argv, stdout=out, stderr=err, env=clean_env(), timeout=90).returncode
            if code:
                raise RuntimeError('pinned provider doctor failed: ' + (output / 'stderr.txt').read_text()[-4000:])
            value = json.loads((output / 'stdout.json').read_text())
            write_json(output / 'result.json', value)
            print(json.dumps(value, indent=2))
            return 0
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('build', help='build the executor from public pinned inputs')
    build.add_argument('lock', type=Path, nargs='?', default=DEFAULT_PROFILE)
    execute = sub.add_parser('exec', help='execute a verification command in the fixed environment')
    execute.add_argument('lock', type=Path)
    execute.add_argument('command', nargs=argparse.REMAINDER)
    probe = sub.add_parser('doctor', help='initialize a provider inside the image without generation')
    probe.add_argument('lock', type=Path)
    probe.add_argument('--out', type=Path, required=True)
    probe.add_argument('--harness', choices=('codex', 'pi'), default='codex')
    probe.add_argument('--native', action='store_true', help='also qualify the native delegation configuration')
    workflow = sub.add_parser('_workflow')
    workflow.add_argument('folder', type=Path)
    args = parser.parse_args()
    if args.action == '_workflow':
        return inner_workflow(args.folder)
    if args.action == 'doctor':
        return doctor(args.lock, args.out, args.harness, args.native)
    if args.action == 'exec':
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command:
            parser.error('exec requires a command after --')
        return exec_command(args.lock, command)
    print(json.dumps(load_lock(args.lock), indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('executor: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
