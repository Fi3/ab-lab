"""Compare local readbacks without exposing values or generating responses."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.provider import Codex
from lab.host import save_json


def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            yield from differences(a.get(key), b.get(key), path+'.'+key)
    elif a != b:
        yield {'key': path, 'left_type': type(a).__name__, 'right_type': type(b).__name__,
               'left_sha256': hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest(),
               'right_sha256': hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repo', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--omit-project', action='append', default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    values, identities = [], []
    for name in ('one', 'two'):
        folder = args.output.resolve()/name
        p = Codex(args.repo.resolve(), folder, 'gpt-5.5', 'xhigh', time.monotonic()+60, 1, 1)
        try:
            value = p.rpc('config/read', {'includeLayers': False})['config']
            values.append(json.loads(json.dumps(value, sort_keys=True).replace(str(folder), '<RUN_PROVIDER>')))
            identities.append(p.identity)
        finally:
            p.close()
    result = {'generation': 'none', 'identities': identities,
              'different_keys': list(differences(*values))}
    if args.omit_project:
        projected = json.loads(json.dumps(values[-1]))
        removed = {}
        for name in args.omit_project:
            removed[name] = projected.get('projects', {}).pop(name, None)
        result['projection'] = {'removed_projects': removed,
            'sha256': hashlib.sha256(json.dumps(projected, sort_keys=True).encode()).hexdigest()}
    save_json(args.output/'result.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
