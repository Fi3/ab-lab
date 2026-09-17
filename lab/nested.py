"""Pin command-launched Codex and observe owned native histories without copying auth."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import tomllib

from .environment import BLOCKED, clean_env


def pinned_arguments(config, arguments):
    required = {'forced_login_method': 'chatgpt', 'model_provider': 'openai',
                'model': config['model'], 'model_reasoning_effort': config['effort']}
    # Refuse contradictory overrides instead of relying on ambiguous CLI ordering.
    args = iter(arguments)
    for arg in args:
        if arg in ('--oss', '--local-provider', '--profile', '-p') or arg.startswith(('--profile=', '--local-provider=')):
            raise ValueError('nested Codex must preserve the admitted provider/model/profile')
        if arg in ('-m', '--model') or arg.startswith('--model='):
            value = arg.split('=', 1)[1] if '=' in arg else next(args, '')
            if value != config['model']:
                raise ValueError('nested model override differs from the benchmark')
        elif arg in ('-c', '--config') or arg.startswith(('--config=', '-c')):
            value = next(args, '') if arg in ('-c', '--config') else arg.removeprefix('--config=').removeprefix('-c')
            key, sep, raw = value.partition('=')
            key = key.strip()
            if key in required:
                try:
                    parsed = tomllib.loads(value)[key]
                except (ValueError, KeyError):
                    parsed = raw.strip().strip('"')
                if parsed != required[key]:
                    raise ValueError('nested configuration override differs from the benchmark: '+key)
            elif key.startswith(('model_providers', 'profile', 'forced_chatgpt_workspace_id')):
                raise ValueError('nested provider/auth configuration overrides are not allowed')
        elif arg in ('-C', '--cd') or arg.startswith('--cd='):
            value = arg.split('=', 1)[1] if '=' in arg else next(args, '')
            if not Path(value).resolve().is_relative_to(Path(config['repo']).resolve()):
                raise ValueError('nested working directory must remain in the owned checkout')
    pins = ['--disable', 'apps']
    for key, value in required.items():
        pins += ['-c', key+'='+json.dumps(value)]
    return [config['executable'], *pins, *arguments]


class CommandEnvironment:
    def __init__(self, repo, folder, model, effort, executable):
        self.bin = Path(folder).resolve()
        self.bin.mkdir(parents=True)
        resolved = shutil.which(executable)
        if not resolved:
            raise ValueError('Codex executable not found')
        config = {'repo': str(Path(repo).resolve()), 'model': model, 'effort': effort,
                  'executable': str(Path(resolved).absolute())}
        self.executable = config['executable']
        config_path = self.bin / 'settings.json'
        config_path.write_text(json.dumps(config))
        launcher = self.bin / 'codex'
        launcher.write_text('#!'+sys.executable+'\nimport sys\n'
            +'sys.path.insert(0, '+repr(str(Path(__file__).resolve().parents[1]))+')\n'
            +'from lab.nested import command_main\ncommand_main('+repr(str(config_path))+')\n')
        launcher.chmod(0o755)
        env = clean_env()
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
        return [part for key in ('PATH', 'BASH_ENV', 'AGENT_LAB_CHILD')
                for part in ('-c', 'shell_environment_policy.set.'+key+'='+json.dumps(self.env[key]))]


def command_main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        if not Path.cwd().resolve().is_relative_to(Path(config['repo'])):
            raise ValueError('nested Codex must run inside the owned checkout')
        argv = pinned_arguments(config, sys.argv[1:])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    os.execvpe(argv[0], argv, clean_env())


class NestedUsage:
    """Read only histories rooted in this owned checkout, incrementally.

    Parent app-server threads are excluded; CLI launch and resume share one
    cumulative counter. Missing prices and model mismatches are never zeros.
    """
    def __init__(self, repo, model, effort, sessions=None):
        self.repo, self.model, self.effort = Path(repo).resolve(), model, effort
        self.sessions = Path(sessions) if sessions else Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
        self.started = time.time()
        self.files, self.threads, self.last_scan = {}, {}, 0.0

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
            if pair != [self.model, self.effort]:
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

    def refresh(self, parents=(), force=False):
        if not force and time.monotonic()-self.last_scan < 2:
            return
        self.last_scan = time.monotonic()
        today = datetime.now(timezone.utc).date()
        dates = {today+timedelta(days=n) for n in (-1, 0, 1)}
        dates.add(datetime.fromtimestamp(self.started, timezone.utc).date())
        for date in dates:
            folder = self.sessions / date.strftime('%Y/%m/%d')
            for path in folder.glob('*.jsonl'):
                if path not in self.files:
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
                        self.files[path] = {'thread': meta['id'], 'offset': stream.tell()} if owned else None
                entry = self.files[path]
                if not entry or entry['thread'] in parents:
                    continue
                with path.open() as stream:
                    stream.seek(entry['offset'])
                    while line := stream.readline():
                        if not line.endswith('\n'):
                            break
                        self.observe(entry['thread'], json.loads(line))
                        entry['offset'] = stream.tell()
                if entry['thread'] in self.threads:
                    self.threads[entry['thread']]['path'] = str(path)

    def report(self, parents=()):
        children = {k: v for k, v in self.threads.items() if k not in parents}
        errors, incomplete = [], []
        for thread, state in children.items():
            errors.extend(thread+': '+e for e in state['errors'])
            if not state['contexts'] or not state['plans'] or not state['turns']:
                incomplete.append(thread+': missing identity, subscription plan or turn evidence')
            for turn, result in state['turns'].items():
                if not result.get('completed') or not result.get('priced'):
                    incomplete.append(thread+': '+turn+' not complete and priced')
        return {'observed_raw_tokens': sum(sum(v['total'][:2]) for v in children.values()),
                'cached_input_tokens': sum(v['total'][2] for v in children.values()),
                'thread_totals': {k: v['total'] for k, v in children.items()},
                'threads': children, 'errors': sorted(set(errors)), 'incomplete': incomplete,
                'measurement_complete': not errors and not incomplete}
