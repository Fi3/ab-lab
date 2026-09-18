"""One real subscription call: kill its caller, then verify saved final usage.

This is a small lifecycle regression, not a benchmark or a benchmark retry.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.host import save_json
from lab.provider import Codex
from lab.workflow import source_hashes

PROMPT = 'Reply exactly NESTED_SHUTDOWN_OK. Do not use tools or modify files.\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out/'checkout'
    repo.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    start = time.monotonic()
    pins = source_hashes()
    save_json(out/'input.json', {'prompt': PROMPT, 'seconds': 180, 'max_observed_raw_tokens': 100000,
        'child_generations': 1, 'parent_generations': 0, 'model': 'gpt-5.5', 'effort': 'xhigh',
        'auth': 'existing ChatGPT subscription', 'source_sha256': pins,
        'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    result = {'status': 'failed'}
    provider = caller = None
    try:
        provider = Codex(repo, out/'provider', 'gpt-5.5', 'xhigh', start+180, 100000, 1)
        result['provider'] = provider.identity
        caller = subprocess.Popen([str(provider.commands.bin/'codex'), '--sandbox', 'read-only',
            '--ask-for-approval', 'never', 'exec', '--color', 'never', '--json', '-'],
            cwd=repo, env=provider.command_env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        caller.stdin.write(PROMPT.encode())
        caller.stdin.close()
        caller.stdin = None
        prefix = []
        while time.monotonic() < start+40:
            if select.select([caller.stdout], [], [], 0.1)[0]:
                line = caller.stdout.readline()
                if not line:
                    raise RuntimeError('caller exited before generation start')
                prefix.append(line.decode())
                event = json.loads(line)
                if event.get('type') == 'turn.started':
                    break
        else:
            raise RuntimeError('no generation-start event within 40 seconds')
        # Native thread state is mutable; freeze the observation before waiting.
        result['at_shutdown'] = json.loads(json.dumps(provider.child_report(force=True)))
        if not result['at_shutdown'].get('processes', {}).get('pending'):
            raise RuntimeError('child already finished; shutdown path was not exercised')
        result['shutdown_at_unix'] = time.time()
        save_json(out/'at-shutdown.json', result['at_shutdown'])
        os.killpg(caller.pid, signal.SIGKILL)
        tail, stderr = caller.communicate(timeout=5)
        (out/'caller.stdout').write_text(''.join(prefix)+tail.decode())
        (out/'caller.stderr').write_bytes(stderr)
        result['caller_exit_code'] = caller.returncode
        provider.settle_children()
        child = provider.child_report(force=True)
        result['nested'] = child
        calls = child['processes']['completed']
        if len(calls) != 1 or len(child['threads']) != 1 or not child['measurement_complete']:
            raise RuntimeError('expected exactly one fully measured child call')
        call, receipt = next(iter(calls.items()))
        events = [json.loads(line) for line in (provider.commands.children.folder/call/'stdout').read_text().splitlines()]
        completions = [row for row in events if row.get('type') == 'turn.completed']
        if receipt['exit_code'] != 0 or len(completions) != 1:
            raise RuntimeError('real CLI did not finish successfully after caller shutdown')
        usage = completions[0]['usage']
        result['cli_raw_tokens'] = usage['input_tokens']+usage['output_tokens']
        if child['observed_raw_tokens'] != result['cli_raw_tokens']:
            raise RuntimeError('CLI usage and independent native history do not match')
        if not any(row.get('item', {}).get('text') == PROMPT.split('.')[0].removeprefix('Reply exactly ')
                   for row in events):
            raise RuntimeError('expected reply missing')
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo):
            raise RuntimeError('read-only verification changed source')
        if provider.turns or source_hashes() != pins:
            raise RuntimeError('unexpected parent generation or changing runner source')
        result['status'] = 'passed'
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if caller is not None and caller.poll() is None:
            os.killpg(caller.pid, signal.SIGKILL)
            caller.wait(timeout=5)
        if caller is not None:
            for stream in (caller.stdin, caller.stdout, caller.stderr):
                if stream is not None:
                    stream.close()
        if provider is not None:
            provider.close()
            result['nested'] = provider.child_report(force=True)
        result['duration_seconds'] = time.monotonic()-start
        save_json(out/'result.json', result)
    print(json.dumps({'status': result['status'], 'error': result.get('error'),
        'observed_raw_tokens': result.get('nested', {}).get('observed_raw_tokens'),
        'measurement_complete': result.get('nested', {}).get('measurement_complete'),
        'duration_seconds': result['duration_seconds']}, indent=2))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
