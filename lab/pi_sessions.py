"""Expose this run's Pi history to normal CLI session-selection options."""
import json
from pathlib import Path


VALUE_OPTIONS = {'--mode', '--provider', '--model', '--api-key', '--system-prompt',
    '--append-system-prompt', '--name', '-n', '--session', '--session-id', '--fork',
    '--models', '--tools', '-t', '--exclude-tools', '-xt', '--thinking', '--export',
    '--extension', '-e', '--skill', '--prompt-template', '--theme', '--use-theme', '--tui-mode'}


def owned_sessions(config):
    root, repo = Path(config['calls']).resolve(), Path(config['repo']).resolve()
    found = {}
    for request_file in root.glob('call-*/request.json'):
        request = json.loads(request_file.read_text())
        if request.get('harness') != 'pi':
            continue
        directory = Path(request.get('session_dir', request_file.parent / 'sessions')).resolve()
        if not directory.is_relative_to(root):
            raise ValueError('Pi session directory is outside this run')
        for candidate in directory.rglob('*.jsonl'):
            path = candidate.resolve()
            if path in found:
                continue
            if not path.is_relative_to(root):
                raise ValueError('Pi session history is outside this run')
            with path.open() as stream:
                first = stream.readline()
            if not first.endswith('\n'):
                continue
            header = json.loads(first)
            if (header.get('type') != 'session' or not isinstance(header.get('id'), str)
                    or not isinstance(header.get('cwd'), str)
                    or not Path(header['cwd']).resolve().is_relative_to(repo)):
                continue
            found[path] = header['id']
    return found


def prepare_pi_call(config, folder, arguments):
    """Retain CLI selectors while limiting their lookup to owned session files."""
    kept, selected, resume = [], {}, False
    args = iter(arguments)
    for arg in args:
        if arg == '--':
            kept.extend([arg, *args])
            break
        if arg == '--session-dir':
            next(args, None)
        elif arg == '--no-session' or arg.startswith('--session-dir='):
            continue
        else:
            kept.append(arg)
            if arg in ('--continue', '-c', '--resume', '-r'):
                resume = True
            elif arg in VALUE_OPTIONS:
                value = next(args, None)
                if value is not None:
                    kept.append(value)
                    if arg in ('--session', '--session-id', '--fork'):
                        selected[arg] = value
                        resume = True
    sessions = folder / 'sessions'
    sessions.mkdir()
    operation = 'fork' if '--fork' in selected else 'resume' if resume else 'new'
    target = None
    if resume:
        owned = owned_sessions(config)
        for option in ('--session', '--fork'):
            if option not in selected:
                continue
            value = selected[option]
            if '/' in value or '\\' in value or value.endswith('.jsonl'):
                target = owned.get(Path(value).expanduser().resolve())
                if target is None:
                    raise ValueError('Pi session path is not owned by this benchmark run')
            elif value in owned.values():
                target = value
        if selected.get('--session-id') in owned.values():
            target = selected['--session-id']
        for index, (path, identity) in enumerate(sorted(owned.items())):
            alias = sessions / path.name
            if alias.exists():
                alias = sessions / f'{index}-{path.name}'
            alias.symlink_to(path)
    # Every visible old receipt is recorded before the CLI can append. The
    # supervisor separately freezes the final boundary for this invocation.
    from .nested import session_receipts
    baseline = {'operation': operation, 'responses': session_receipts(sessions, 'pi')}
    if target is not None:
        baseline['target_thread_id'] = target
    (folder / 'response-baseline.json').write_text(json.dumps(baseline))
    return ['--session-dir', str(sessions), *kept], sessions
