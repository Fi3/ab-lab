"""Own delegated CLI processes and account their native histories."""
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import time
import tempfile

from .environment import BLOCKED, clean_env
from .sandbox import CommandSandbox
from .child_process import Children, launch
from .native_usage import NativeUsage


DELEGATION_POLICY = 'agent-delegation-disabled-v1'
NATIVE_DELEGATION_POLICY = 'native-delegation-owned-usage-v1'


def delegation_paths(executable, pi_executable=None):
    """Protect installed launchers and the credentials needed to bypass them."""
    paths = {Path.home() / '.codex', Path.home() / '.pi' / 'agent',
             Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).expanduser().resolve(),
             Path(os.environ.get('PI_CODING_AGENT_DIR', Path.home() / '.pi' / 'agent')).expanduser().resolve()}
    for command in (executable, pi_executable or 'pi'):
        resolved = shutil.which(command)
        if not resolved:
            continue
        entry = Path(resolved).resolve()
        # Codex's native executable also implements apply_patch. Keep that
        # helper executable; deny dedicated script-launcher directories and auth.
        # File-level no-access masks fail in the supported Linux sandbox, while
        # masking a complete SDK/package would break native tools.
        with entry.open('rb') as stream:
            script = stream.read(2) == b'#!'
        if command == executable and not script:
            continue
        for parent in entry.parents:
            manifest = parent / 'package.json'
            if not manifest.is_file():
                continue
            metadata = json.loads(manifest.read_text())
            name = metadata.get('name', '')
            if command == executable and name == '@openai/codex' and entry.parent == parent / 'bin':
                paths.add(entry.parent)
                break
            if command != executable and name.endswith('/pi-coding-agent'):
                sdk = (parent / metadata['main']).resolve()
                if entry.parent == parent / 'dist' / 'bundle' and not sdk.is_relative_to(entry.parent):
                    paths.add(entry.parent)
                    break
                raise ValueError('Pi CLI must use a dedicated dist/bundle launcher directory separate from its SDK')
        else:
            raise ValueError('Unsupported script launcher layout; cannot isolate ' + str(entry))
    # Overlapping no-access masks cannot be mounted reliably by bubblewrap.
    paths = {path.resolve() for path in paths}
    return sorted(str(path) for path in paths if not any(parent in paths for parent in path.parents))


class NativeState:
    """Private runtime/auth copies; installed configuration/resources stay readable."""
    codex_files = ('config.toml', 'auth.json', 'models_cache.json', 'AGENTS.md', 'AGENTS.override.md')
    codex_resources = ('skills', 'plugins', 'agents', 'prompts')
    def __init__(self, artifacts, *, pi_vanilla=False):
        self.temporary = tempfile.TemporaryDirectory(prefix='agent-lab-native-state-')
        self.root = Path(self.temporary.name)
        self.environment, self.fingerprints = {}, {}
        sources = {
            'CODEX_HOME': (Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')), 'codex',
                self.codex_files, self.codex_resources),
            'PI_CODING_AGENT_DIR': (Path(os.environ.get('PI_CODING_AGENT_DIR', Path.home() / '.pi' / 'agent')), 'pi',
                ('settings.json', 'auth.json', 'models.json', 'models-store.json', 'AGENTS.override.md',
                 'AGENTS.md', 'AGENTS.MD', 'CLAUDE.md', 'CLAUDE.MD', 'SYSTEM.md', 'APPEND_SYSTEM.md'),
                ('extensions', 'skills', 'prompts', 'themes', 'npm')),
        }
        self.sessions, self.sources = {}, []
        for variable, (source, name, files, resources) in sources.items():
            if name == 'pi' and pi_vanilla:
                files, resources = ('auth.json',), ()
            source = source.expanduser().resolve()
            self.sources.append(source)
            destination = self.root / name
            destination.mkdir(mode=0o700)
            self.environment[variable] = str(destination)
            records = {}
            if name == 'codex':
                files = (*files, *(path.name for path in sorted(source.glob('*.config.toml'))))
            for filename in files:
                original = source / filename
                if original.is_file():
                    shutil.copyfile(original, destination / filename)
                    (destination / filename).chmod(0o600)
                    if filename != 'auth.json':
                        records[filename] = hashlib.sha256(original.read_bytes()).hexdigest()
            for resource in resources:
                original = source / resource
                if original.exists():
                    (destination / resource).symlink_to(original.resolve(), target_is_directory=original.is_dir())
                    digest = hashlib.sha256()
                    if resource in ('npm', 'plugins'):
                        selected = sorted({*original.glob('*.json'), *original.glob('node_modules/*/package.json'),
                            *original.glob('node_modules/@*/*/package.json'), *original.glob('cache/*/*/*/.claude-plugin/plugin.json')})
                    else:
                        selected = sorted(path for path in original.rglob('*') if path.is_file() and '.git' not in path.parts)
                    for path in selected:
                        digest.update(str(path.relative_to(original)).encode())
                        digest.update(path.read_bytes())
                    records[resource] = {'path': str(original), 'configuration_sha256': digest.hexdigest(),
                                         'hashed_files': len(selected)}
            sessions = Path(artifacts) / (name + '-sessions')
            sessions.mkdir()
            (destination / 'sessions').symlink_to(sessions, target_is_directory=True)
            self.sessions[name] = sessions
            self.fingerprints[name] = records

    def close(self):
        self.temporary.cleanup()


class CommandEnvironment:
    def __init__(self, repo, folder, executable, *, pi_executable=None, allow_delegation=False, deadline=None, pi_vanilla=False):
        self.bin = Path(folder).resolve()
        self.bin.mkdir(parents=True)
        resolved = shutil.which(executable)
        if not resolved:
            raise ValueError('Codex executable not found')
        self.executable = str(Path(resolved).absolute())
        self.children = None
        self.native_state = None
        blocked = delegation_paths(self.executable, pi_executable)
        if allow_delegation:
            if deadline is None:
                raise ValueError('Native delegation requires the global deadline')
            self.children = Children(self.bin / 'children', deadline)
            self.native_state = NativeState(self.bin, pi_vanilla=pi_vanilla)
            self.sandbox = CommandSandbox(repo, self.executable,
                (self.children.folder, self.native_state.root, *self.native_state.sessions.values()),
                read_only_blocked_paths=[*blocked, self.native_state.root],
                read_only_paths=self.native_state.sources)
        else:
            self.sandbox = CommandSandbox(repo, self.executable, blocked_paths=blocked)
        for name, executable in (('codex', self.executable), ('pi', pi_executable or shutil.which('pi'))):
            launcher = self.bin / name
            if allow_delegation and executable:
                config = {'repo': str(Path(repo).resolve()), 'executable': str(executable), 'harness': name,
                          'calls': str(self.children.folder), 'deadline': deadline,
                          'owner_lock': str(self.children.folder / 'owner.lock'), 'owner_pid': os.getpid(),
                          'runtime_root': str(self.native_state.root),
                          'codex_home': self.native_state.environment['CODEX_HOME']}
                config_path = self.bin / (name + '-settings.json')
                config_path.write_text(json.dumps(config))
                launcher.write_text('#!' + sys.executable + '\nimport sys\n'
                    + 'sys.path.insert(0, ' + repr(str(Path(__file__).resolve().parents[1])) + ')\n'
                    + 'from lab.nested import command_main\ncommand_main(' + repr(str(config_path)) + ')\n')
            else:
                launcher.write_text('#!/bin/sh\n'
                    'echo "Agent-created model sessions are disabled; the runner owns review sessions." >&2\n'
                    'exit 126\n')
            launcher.chmod(0o755)
        env = clean_env()
        if self.native_state is not None:
            env.update(self.native_state.environment)
        env['PATH'] = str(self.bin)+os.pathsep+env.get('PATH', os.defpath)
        # Bash login profiles can replace PATH. BASH_ENV runs after those profiles
        # for noninteractive shells; retain any existing hook before our PATH pin.
        shell_env = self.bin / 'shell-env.sh'
        previous = env.get('BASH_ENV')
        shell_env.write_text(('. '+shlex.quote(previous)+'\n' if previous else '')
                             +'unset '+' '.join(sorted(BLOCKED))+'\n'
                             +'export PATH='+shlex.quote(env['PATH'])+'\n')
        env.update(BASH_ENV=str(shell_env), AGENT_LAB_CHILD='1')
        self.env = env

    def config_arguments(self):
        return [part for key in ('PATH', 'BASH_ENV', 'AGENT_LAB_CHILD', 'CODEX_HOME', 'PI_CODING_AGENT_DIR') if key in self.env
                for part in ('-c', 'shell_environment_policy.set.'+key+'='+json.dumps(self.env[key]))]

    def close(self):
        if self.children is not None:
            self.children.close()
        if self.native_state is not None:
            self.native_state.close()



def session_receipts(directory, harness):
    """Snapshot durable receipt IDs, including any embedded compaction receipt."""
    responses = {}
    for path in Path(directory).rglob('*.jsonl'):
        thread = None
        with path.open() as stream:
            for line in stream:
                if not line.endswith('\n'):
                    break
                row = json.loads(line)
                payload = row.get('payload', {})
                if harness == 'codex':
                    if row.get('type') == 'compacted':
                        payload = payload.get('latest_token_usage_record') or {}
                    elif row.get('type') != 'token_usage_record':
                        continue
                    thread, identity = payload.get('thread_id'), payload.get('response_id')
                else:
                    if row.get('type') == 'session':
                        thread = row['id']
                        continue
                    if (row.get('type') not in ('usage', 'compaction', 'branch_summary') and
                            not (row.get('type') == 'message' and row.get('message', {}).get('role') == 'assistant')):
                        continue
                    identity = row.get('id')
                if thread and identity:
                    responses.setdefault(thread, set()).add(identity)
    return {thread: sorted(ids) for thread, ids in responses.items()}


def capture_call_receipts(folder, harness):
    """Freeze each completed process's evidence before another resume can append."""
    request = json.loads((folder / 'request.json').read_text())
    snapshot = {'responses': session_receipts(request['session_dir'], harness)}
    (folder / 'response-final.json').write_text(json.dumps(snapshot))


def codex_resume_request(arguments):
    values = {'-c', '--config', '--enable', '--disable', '--remote', '--remote-auth-token-env',
              '-m', '--model', '--local-provider', '-p', '--profile', '-s', '--sandbox',
              '-C', '--cd', '--add-dir', '-a', '--ask-for-approval', '-i', '--image',
              '--output-schema', '-o', '--output-last-message', '--color'}
    positional = []
    args = iter(arguments)
    for arg in args:
        if arg == '--':
            positional.extend(args)
            break
        if arg in values:
            next(args, None)
        elif not arg.startswith('-'):
            positional.append(arg)
    if positional and positional[0] in ('exec', 'e'):
        positional.pop(0)
    if not positional or positional[0] not in ('resume', 'fork'):
        return None
    operation = positional[0]
    target = None if '--last' in arguments else next(iter(positional[1:]), None)
    return operation, target


def codex_owned_resume(config, arguments):
    selection = codex_resume_request(arguments)
    if selection is None:
        return None
    operation, target = selection
    cwd = Path.cwd().resolve()
    args = iter(arguments)
    for arg in args:
        if arg == '--':
            break
        if arg in ('-C', '--cd'):
            cwd = (Path.cwd() / next(args, '.')).resolve()
        elif arg.startswith('--cd='):
            cwd = (Path.cwd() / arg.partition('=')[2]).resolve()
    homes = {Path(config['codex_home']).resolve()}
    for request in Path(config['calls']).glob('call-*/request.json'):
        value = json.loads(request.read_text())
        home = value.get('environment', {}).get('CODEX_HOME')
        if value.get('harness') == 'codex' and home:
            homes.add(Path(home).resolve())
    candidates = []
    for home in homes:
        named = set()
        if target:
            for database in home.glob('state_*.sqlite'):
                try:
                    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
                        named.update(row[0] for row in connection.execute('SELECT id FROM threads WHERE name = ?', (target,)))
                except sqlite3.Error:
                    pass
        for path in (home / 'sessions').rglob('*.jsonl'):
            with path.open() as stream:
                line = stream.readline()
            if not line.endswith('\n'):
                continue
            row = json.loads(line)
            meta = row.get('payload', {})
            if row.get('type') != 'session_meta' or not Path(meta.get('cwd', '/')).resolve().is_relative_to(Path(config['repo']).resolve()):
                continue
            if target and meta.get('id') != target and meta.get('id') not in named:
                continue
            if not target and '--all' not in arguments and Path(meta['cwd']).resolve() != cwd:
                continue
            candidates.append((path.stat().st_mtime_ns, str(path), home, meta['id']))
    if not candidates:
        return None
    _, _, home, thread = max(candidates)
    return operation, home, thread


def prepare_codex_call_state(config, folder, arguments=()):
    """A CLI process owns its session directory without changing model arguments."""
    resumed = codex_owned_resume(config, arguments)
    if resumed:
        operation, home, thread = resumed
        sessions = (home / 'sessions').resolve()
        (folder / 'sessions').symlink_to(sessions, target_is_directory=True)
        (folder / 'response-baseline.json').write_text(json.dumps({'operation': operation,
            'target_thread_id': thread, 'responses': session_receipts(sessions, 'codex')}))
        return home
    source = Path(config['codex_home'])
    destination = Path(config['runtime_root']) / folder.name / 'codex'
    destination.mkdir(parents=True, mode=0o700)
    for filename in (*NativeState.codex_files, *(path.name for path in sorted(source.glob('*.config.toml')))):
        original = source / filename
        if original.is_file():
            shutil.copyfile(original, destination / filename)
            (destination / filename).chmod(0o600)
    for resource in NativeState.codex_resources:
        original = source / resource
        if original.exists():
            (destination / resource).symlink_to(original.resolve(), target_is_directory=original.is_dir())
    sessions = folder / 'sessions'
    sessions.mkdir()
    (destination / 'sessions').symlink_to(sessions, target_is_directory=True)
    return destination


def command_main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        if not Path.cwd().resolve().is_relative_to(Path(config['repo'])):
            raise ValueError('Delegated CLI must remain inside the owned checkout')
        arguments = sys.argv[1:]
        if arguments in (['--version'], ['-V'], ['-v'], ['--help'], ['-h']):
            os.execvpe(config['executable'], [config['executable'], *arguments], clean_env())
        # Model and role selection belong to the harness. Only the subprocess
        # lifetime and usage receipts belong to the runner.
        code = launch(config, [config['executable'], *arguments])
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(code if code >= 0 else 128-code)


class NestedUsage:
    """Read only histories rooted in this owned checkout, incrementally.

    Parent app-server threads are excluded; CLI launch and resume share one
    cumulative counter. Missing prices and model mismatches are never zeros.
    """
    def __init__(self, repo, model, effort, sessions=None, *, allow_model_variation=False, calls=None):
        self.repo, self.model, self.effort = Path(repo).resolve(), model, effort
        self.allow_model_variation = allow_model_variation
        self.calls = Path(calls) if calls is not None else None
        self.sessions = Path(sessions) if sessions else Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
        self.started = time.time()
        self.files, self.threads, self.last_scan = {}, {}, 0.0
        self._scan_pending = False
        self.native_readers = {}
        self.fork_offsets = {}

    def observe(self, thread, row):
        state = self.threads.setdefault(thread, {'total': [0, 0, 0], 'errors': [], 'turns': {},
            'active': None, 'contexts': [], 'plans': [], 'position': 0, 'price_at': 0, 'message_at': 0})
        state['position'] += 1
        p = row.get('payload', {})
        kind = p.get('type')
        if row.get('type') == 'response_item' and kind == 'message' and p.get('role') == 'assistant':
            state['message_at'] = state['position']
        if row.get('type') == 'turn_context':
            pair = [p.get('model'), p.get('effort')]
            if pair not in state['contexts']:
                state['contexts'].append(pair)
            if not self.allow_model_variation and pair != [self.model, self.effort]:
                state['errors'].append('child model/effort differs from admission')
        if row.get('type') == 'event_msg':
            if kind == 'task_started':
                state['active'] = p['turn_id']
                state['turns'][p['turn_id']] = {'before': sum(state['total'][:2]), 'completed': False}
            elif kind == 'agent_message':
                state['message_at'] = state['position']
            elif kind == 'token_count' and p.get('info'):
                value = p['info']['total_token_usage']
                now = [value.get(k, 0) for k in ('input_tokens', 'output_tokens', 'cached_input_tokens')]
                if any(type(v) is not int or v < 0 for v in now) or any(a < b for a, b in zip(now, state['total'])):
                    state['errors'].append('child counter invalid or decreased')
                elif now[:2] != state['total'][:2]:
                    state['total'] = now
                    state['price_at'] = state['position']
                plan = (p.get('rate_limits') or {}).get('plan_type')
                if plan and plan not in state['plans']:
                    state['plans'].append(plan)
                if plan in ('api', 'unknown'):
                    state['errors'].append('child does not report a recognized subscription plan')
            elif kind == 'task_complete':
                turn = state['turns'].get(p.get('turn_id'))
                if turn is None:
                    state['errors'].append('child completion has no owned start')
                else:
                    turn['completed'] = True
                    turn['priced'] = (sum(state['total'][:2]) > turn['before'] and
                                      state['price_at'] >= state['message_at'])
                state['active'] = None
            elif kind == 'turn_aborted':
                state['errors'].append('child turn aborted; tail not certified')

    def scan(self, force=False):
        """Discover owned session headers before any history is interpreted."""
        if not force and time.monotonic()-self.last_scan < 2:
            return False
        self.last_scan = time.monotonic()
        today = datetime.now(timezone.utc).date()
        dates = {today+timedelta(days=n) for n in (-1, 0, 1)}
        dates.add(datetime.fromtimestamp(self.started, timezone.utc).date())
        candidates = [(path, None) for date in dates
                      for path in (self.sessions / date.strftime('%Y/%m/%d')).glob('*.jsonl')]
        if self.calls is not None:
            candidates += [(path, folder.name) for folder in self.calls.glob('call-*')
                for path in (folder / 'sessions').rglob('*.jsonl')]
        for path, call_id in candidates:
            path = path.resolve()
            if path in self.files:
                if self.files[path] and call_id:
                    self.files[path]['calls'].add(call_id)
                continue
            if path.stat().st_mtime < self.started-2:
                self.files[path] = None
                continue
            with path.open() as stream:
                first = stream.readline()
                if not first.endswith('\n'):
                    continue
                try:
                    row = json.loads(first)
                    meta = row.get('payload', {})
                    owned = row.get('type') == 'session_meta' and Path(meta.get('cwd', '/')).resolve().is_relative_to(self.repo)
                except (ValueError, TypeError):
                    owned = False
                self.files[path] = {'thread': meta['id'], 'offset': stream.tell(), 'line': 1,
                    'parent_thread_id': meta.get('parent_thread_id'), 'calls': {call_id} if call_id else set(),
                    'session_meta': meta} if owned else None
        self._scan_pending = True
        return True

    def refresh(self, parents=(), force=False):
        self.scan(force=force)
        self.consume(parents)

    def consume(self, parents=()):
        """Interpret only files admitted by the most recent header scan."""
        if not self._scan_pending:
            return
        self._scan_pending = False
        for path, entry in self.files.items():
            if not entry or entry['thread'] in parents:
                continue
            reader = None
            if self.allow_model_variation:
                reader = self.native_readers.setdefault(entry['thread'], NativeUsage(path, entry['thread'],
                    entry['session_meta']['cwd'], parent_thread_id=entry.get('parent_thread_id')))
                reader.refresh()
                self.observe(entry['thread'], {'type': 'native_reader'})
            with path.open() as stream:
                stream.seek(entry['offset'])
                while line := stream.readline():
                    if not line.endswith('\n'):
                        break
                    entry['line'] += 1
                    if not reader or not reader._own_start_line or entry['line'] >= reader._own_start_line:
                        self.observe(entry['thread'], json.loads(line))
                    entry['offset'] = stream.tell()
            if entry['thread'] in self.threads:
                state = self.threads[entry['thread']]
                state['path'] = str(path)
                if reader:
                    state['native_usage'] = reader.report()
                    for turn, result in state['turns'].items():
                        result['priced'] = result.get('priced', False) and any(
                            row['turn_id'] == turn for row in reader.responses.values())

    def cli_fork_offset(self, thread, visiting=()):
        """A paginated CLI fork inherits counters through a specific owned byte prefix."""
        if thread in self.fork_offsets:
            return self.fork_offsets[thread]
        entry = next((entry for entry in self.files.values() if entry and entry['thread'] == thread), None)
        if entry is None:
            raise ValueError('CLI fork has no owned parent history')
        meta = entry['session_meta']
        if not meta.get('forked_from_id') or meta.get('parent_thread_id'):
            return (0, 0, 0)
        base = meta.get('history_base') or {}
        parent, limit = base.get('thread_id'), base.get('end_byte_offset')
        if (meta.get('history_mode') != 'paginated' or parent != meta['forked_from_id'] or
                type(limit) is not int or limit <= 0 or parent in (*visiting, thread)):
            raise ValueError('CLI fork lacks a valid paginated parent boundary')
        path = next((path for path, row in self.files.items() if row and row['thread'] == parent), None)
        if path is None:
            raise ValueError('CLI fork has no owned parent history')
        total = None
        with path.open('rb') as stream:
            while stream.tell() < limit:
                line = stream.readline()
                if not line.endswith(b'\n') or stream.tell() > limit:
                    raise ValueError('CLI fork parent boundary is incomplete or not a record boundary')
                row = json.loads(line)
                payload = row.get('payload', {})
                if row.get('type') == 'compacted':
                    payload = payload.get('latest_token_usage_record') or {}
                elif row.get('type') != 'token_usage_record':
                    continue
                if payload.get('thread_id') == parent:
                    value = payload.get('thread_token_usage') or {}
                    total = tuple(value.get(key) for key in ('input_tokens', 'output_tokens', 'cached_input_tokens'))
                    if any(type(n) is not int or n < 0 for n in total):
                        raise ValueError('CLI fork parent receipt has invalid counters')
        if total is None:
            total = self.cli_fork_offset(parent, (*visiting, thread))
        self.fork_offsets[thread] = total
        return total

    def report(self, parents=(), external_readers=None):
        children = {k: {**v, 'total': list(self.native_readers[k].totals or (0, 0, 0))}
                    if k in self.native_readers else v for k, v in self.threads.items() if k not in parents}
        errors, incomplete = [], []
        for thread, state in children.items():
            errors.extend(thread+': '+e for e in state['errors'])
            reader = self.native_readers.get(thread)
            if self.allow_model_variation and reader:
                errors.extend(thread+': '+e for e in reader.errors)
                if not reader.validated or not reader.responses or reader.missing_compactions:
                    incomplete.append(thread+': incomplete native response/compaction receipts')
                try:
                    offset = self.cli_fork_offset(thread)
                    if any(offset):
                        previous = offset
                        for receipt in reader.responses.values():
                            expected = tuple(a + b for a, b in zip(previous, receipt['usage']))
                            if receipt['thread_totals'] != expected:
                                raise ValueError('CLI fork cumulative counters do not match its owned response receipts')
                            previous = receipt['thread_totals']
                        state['total'] = [a - b for a, b in zip(previous, offset)]
                        state['inherited_counter_offset'] = list(offset)
                except ValueError as exc:
                    # Do not turn an unsupported/unknown fork boundary into a
                    # huge false budget charge or a claimed complete zero.
                    state['total'] = [sum(row['usage'][i] for row in reader.responses.values()) for i in range(3)]
                    incomplete.append(thread + ': ' + str(exc))
            if not state['contexts'] or not state['plans'] or not state['turns']:
                incomplete.append(thread+': missing identity, subscription plan or turn evidence')
            for turn, result in state['turns'].items():
                if not result.get('completed') or not result.get('priced'):
                    incomplete.append(thread+': '+turn+' not complete and priced')
        if self.calls is not None:
            claimed = {}
            readers = {**self.native_readers, **(external_readers or {})}
            for folder in self.calls.glob('call-*'):
                request_file = folder / 'request.json'
                if not request_file.is_file():
                    continue
                request = json.loads(request_file.read_text())
                if request.get('harness') != 'codex' or not request.get('requires_usage'):
                    continue
                admitted = [entry['thread'] for entry in self.files.values()
                            if entry and folder.name in entry['calls']]
                evidence = call_response_evidence(folder, {thread: set(readers[thread].responses)
                    for thread in admitted if thread in readers})
                if not evidence:
                    incomplete.append(folder.name + ': no owned Codex response usage receipts')
                for receipt in evidence:
                    claimed.setdefault(receipt, []).append(folder.name)
            for calls in claimed.values():
                if len(calls) > 1:
                    incomplete.append('ambiguous Codex response ownership: ' + ', '.join(sorted(calls)))
        return {'observed_raw_tokens': sum(sum(v['total'][:2]) for v in children.values()),
                'cached_input_tokens': sum(v['total'][2] for v in children.values()),
                'thread_totals': {k: v['total'] for k, v in children.items()},
                'threads': children, 'errors': sorted(set(errors)), 'incomplete': incomplete,
                'measurement_complete': not errors and not incomplete}


def call_response_evidence(folder, responses):
    """Old receipts cannot certify a new call, nor can a later call certify it."""
    baseline_file, final_file = folder / 'response-baseline.json', folder / 'response-final.json'
    baseline = json.loads(baseline_file.read_text()) if baseline_file.is_file() else {}
    before = {identity for ids in baseline.get('responses', {}).values() for identity in ids}
    final = json.loads(final_file.read_text()).get('responses', {}) if final_file.is_file() else None
    if (folder / 'result.json').is_file() and final is None:
        return set()
    target = baseline.get('target_thread_id')
    evidence = set()
    for thread, ids in responses.items():
        if target and baseline.get('operation') == 'resume' and thread != target:
            continue
        if target and baseline.get('operation') == 'fork' and thread == target:
            continue
        candidates = set(ids) - before
        if final is not None:
            candidates &= set(final.get(thread, ()))
        evidence.update((thread, identity) for identity in candidates)
    return evidence


class PiNestedUsage:
    """Price persistent sessions emitted by owned delegated Pi CLI processes."""
    def __init__(self, repo, calls):
        self.repo, self.calls = Path(repo).resolve(), Path(calls)
        self.report_cache = None
        self.last_scan = 0.0

    def report(self, force=False):
        if not force and self.report_cache is not None and time.monotonic() - self.last_scan < .25:
            return self.report_cache
        self.last_scan = time.monotonic()
        threads, errors, incomplete = {}, [], []
        calls, paths, inherited = {}, {}, {}
        def started(folder):
            request = folder / 'request.json'
            return (json.loads(request.read_text()).get('started_at_unix', request.stat().st_mtime)
                    if request.is_file() else folder.stat().st_mtime)
        for folder in sorted(self.calls.glob('call-*'), key=started):
            request_file = folder / 'request.json'
            if not request_file.is_file():
                continue
            request = json.loads(request_file.read_text())
            if request.get('harness') != 'pi':
                continue
            calls[folder] = set()
            baseline_file = folder / 'response-baseline.json'
            if baseline_file.is_file():
                baseline = json.loads(baseline_file.read_text())
                for thread, ids in baseline.get('responses', {}).items():
                    for identity in ids:
                        inherited.setdefault(identity, thread)
            for path in Path(request.get('session_dir', folder / 'sessions')).rglob('*.jsonl'):
                paths.setdefault(path.resolve(), set()).add(folder)
        for path, owners in paths.items():
            lines = path.read_text().splitlines(keepends=True)
            if not lines or not lines[0].endswith('\n'):
                continue
            header = json.loads(lines[0])
            if header.get('type') != 'session' or not Path(header.get('cwd', '/')).resolve().is_relative_to(self.repo):
                errors.append(f'{path}: Pi session has no owned checkout identity')
                continue
            raw_thread = header['id']
            thread = 'pi:' + raw_thread
            for folder in owners:
                calls[folder].add(raw_thread)
            state = threads.setdefault(thread, {'total': [0, 0, 0], 'responses': {}, 'paths': [], 'models': []})
            state['paths'].append(str(path))
            for line in lines[1:]:
                if not line.endswith('\n'):
                    incomplete.append(f'{thread}: incomplete session record')
                    break
                row = json.loads(line)
                kind = row.get('type')
                message = row.get('message', {})
                if kind == 'message' and message.get('role') == 'assistant':
                    value = message
                elif kind in ('usage', 'compaction', 'branch_summary'):
                    value = row
                else:
                    continue
                identity = row.get('id')
                if not identity:
                    errors.append(f'{thread}: usage record has no identity')
                    continue
                if identity in state['responses']:
                    continue
                if identity in inherited and raw_thread != inherited[identity]:
                    continue  # A native fork copies history, not a new model response.
                try:
                    counts = pi_usage_tokens(value.get('usage'))
                except ValueError as exc:
                    errors.append(f'{thread}: {exc}')
                    continue
                if value.get('provider') not in (None, 'openai-codex'):
                    errors.append(f'{thread}: delegated Pi provider is outside the admitted subscription')
                if value.get('stopReason') in ('error', 'aborted'):
                    incomplete.append(f'{thread}: delegated Pi response did not finish successfully')
                pair = [value.get('provider'), value.get('model')]
                if pair not in state['models']:
                    state['models'].append(pair)
                state['responses'][identity] = {'usage': counts, 'kind': kind}
                state['total'] = [a+b for a, b in zip(state['total'], counts)]
        claimed = {}
        for folder, admitted in calls.items():
            evidence = call_response_evidence(folder, {thread: set(threads['pi:' + thread]['responses'])
                for thread in admitted})
            if not evidence:
                incomplete.append(f'{folder.name}: no owned Pi response usage receipts')
            for receipt in evidence:
                claimed.setdefault(receipt, []).append(folder.name)
        for owners in claimed.values():
            if len(owners) > 1:
                incomplete.append('ambiguous Pi response ownership: ' + ', '.join(sorted(owners)))
        report = {'observed_raw_tokens': sum(sum(row['total'][:2]) for row in threads.values()),
                  'cached_input_tokens': sum(row['total'][2] for row in threads.values()),
                  'thread_totals': {thread: row['total'] for thread, row in threads.items()},
                  'threads': threads, 'errors': sorted(set(errors)), 'incomplete': sorted(set(incomplete)),
                  'measurement_complete': not errors and not incomplete}
        self.report_cache = report
        return report


def pi_usage_tokens(value):
    """Pi separates uncached input, cache reads and cache writes."""
    if not isinstance(value, dict):
        raise ValueError('Pi session/response usage is missing')
    counts = (value.get('input'), value.get('output'), value.get('cacheRead', 0), value.get('cacheWrite', 0))
    if any(type(n) is not int or n < 0 for n in counts):
        raise ValueError('Pi session/response usage has invalid token counts')
    for key in ('total', 'totalTokens'):
        if key in value and (type(value[key]) is not int or value[key] != sum(counts)):
            raise ValueError('Pi session/response usage has inconsistent totals')
    inputs, outputs, reads, writes = counts
    return inputs + reads + writes, outputs, reads
