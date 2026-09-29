"""Opt-in: one native test command and one accounted child response per backend."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.host import git, save_json, snapshot
from lab.provider import Codex, Pi


PROBE = '''import errno, json, pathlib, socket, subprocess
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen()
c = socket.create_connection(s.getsockname())
a, _ = s.accept()
a.sendall(b"ok")
assert c.recv(2) == b"ok"
pathlib.Path("build").mkdir(exist_ok=True)
subprocess.run(["git", "update-index", "--refresh"], check=True)
try:
    pathlib.Path("../outside.txt").write_text("bad")
except OSError as e:
    assert e.errno in (errno.EACCES, errno.EPERM, errno.EROFS), e
else:
    raise AssertionError("write outside checkout allowed")
child = subprocess.run(["codex", "--sandbox", "read-only", "--ask-for-approval", "never",
    "exec", "--color", "never", "--json", "-"], input="Reply exactly CHILD_OK. Do not use tools or modify files.\\n",
    text=True, capture_output=True, timeout=60)
pathlib.Path("build/child-stdout.jsonl").write_text(child.stdout)
pathlib.Path("build/child-stderr.txt").write_text(child.stderr)
assert child.returncode == 0, child.stderr
events = [json.loads(line) for line in child.stdout.splitlines() if line.strip()]
assert any(e.get("type") == "item.completed" and e.get("item", {}).get("text", "").strip() == "CHILD_OK" for e in events)
pathlib.Path("build/result.txt").write_text("NETWORK_BUILD_CHILD_OK")
print("NETWORK_BUILD_CHILD_OK")
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--harness', choices=['codex', 'pi'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'checkout'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Permission test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'verify.py').write_text(PROBE)
    (repo / '.gitignore').write_text('build/\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'ADD permission smoke fixture')
    before = snapshot(repo)
    save_json(out / 'admission.json', {'harness': args.harness, 'model': 'gpt-5.5', 'effort': 'xhigh',
        'seconds': 120, 'max_raw': 100000, 'parent_turns': 1, 'child_turns': 1,
        'scenario': 'native test: localhost, build output, denied sibling write, guarded real child'})
    provider = None
    result = {'status': 'failed'}
    try:
        backend = Pi if args.harness == 'pi' else Codex
        provider = backend(repo, out / 'provider', 'gpt-5.5', 'xhigh', time.monotonic()+120,
                           100000, 1, require_git_write=True)
        thread = provider.start_thread(writable=True)
        provider.turn(thread, 'Run exactly this command once using your native shell tool: '
            + shlex.join([sys.executable, 'verify.py']) + '. This is a permission smoke check, not a coding task. '
            'Do not edit files, retry, or troubleshoot failures. Reply with the command result.',
            'native-test', writable=True)
        provider.settle_children()
        assert snapshot(repo) == before, 'agent changed tracked source or Git state'
        assert (repo / 'build/result.txt').read_text() == 'NETWORK_BUILD_CHILD_OK'
        usage = provider.report()
        assert usage['measurement_complete'], usage
        assert usage['nested']['observed_raw_tokens'] > 0, usage
        assert len(usage['nested']['threads']) == 1, usage
        assert usage['observed_raw_tokens'] < 100000, usage
        result.update(status='passed', scenarios=['localhost connection', 'build output', 'Git index write',
            'sibling write denied', 'real child response', 'complete parent and child accounting'])
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if provider:
            provider.close()
            result['usage'] = provider.report()
        save_json(out / 'result.json', result)
    print(json.dumps({'harness': args.harness, 'status': result['status'], 'error': result.get('error'),
        'raw': result.get('usage', {}).get('observed_raw_tokens'), 'output': str(out)}))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
