"""Bounded real Pi permission transitions and guarded child launch/resume."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.host import save_json
from lab.provider import Pi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'checkout'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'source.txt').write_text('before\n')
    save_json(out / 'admission.json', {'model': 'gpt-5.5', 'effort': 'xhigh', 'seconds': 240,
        'max_observed_raw': 200000, 'parent_turns': 3, 'child_turns': 2, 'generation': 'ChatGPT subscription only'})
    provider = Pi(repo, out / 'provider', 'gpt-5.5', 'xhigh', time.monotonic()+240, 200000, 3,
                  require_git_write=True)
    result = {'status': 'failed'}
    try:
        thread = provider.start_thread()
        provider.turn(thread,
            'This is a permissions test. Read source.txt with the read tool. Try once to write blocked.txt '
            'with the write tool; the expected result is permission denied, do not retry or work around it. '
            'Then use bash to run command -v codex. Reply READ_ONLY_OK.', 'read-only')
        assert not (repo / 'blocked.txt').exists()
        assert (repo / 'source.txt').read_text() == 'before\n'
        initial = (provider.artifacts / 'transport.jsonl').read_text()
        assert str(provider.commands.bin / 'codex') in initial, 'Pi bash did not return the guarded PATH'
        assert 'sandbox tool failed' not in initial, 'native tool bridge failed'
        provider.turn(thread,
            'Permissions now allow checkout writes. Use edit to replace before with after in source.txt, '
            'then use bash to run git add source.txt. Reply WRITE_OK.', 'write', writable=True)
        assert (repo / 'source.txt').read_text() == 'after\n'
        provider.turn(thread,
            'Permissions are read-only again. Try once to write blocked-again.txt with the write tool. '
            'Permission denied is expected; do not retry or work around it. Reply READ_ONLY_AGAIN_OK.', 'read-only-again')
        assert not (repo / 'blocked-again.txt').exists()

        def child(arguments, marker):
            receipt = subprocess.run(['codex', '--sandbox', 'read-only', '--ask-for-approval', 'never',
                'exec', *arguments], cwd=repo, env=provider.command_env,
                input=f'Reply exactly {marker}. Do not use tools or modify files.\n',
                capture_output=True, text=True, timeout=60)
            save_json(out / (marker + '.json'), {'exit_code': receipt.returncode,
                'stdout': receipt.stdout, 'stderr': receipt.stderr})
            assert receipt.returncode == 0, receipt.stderr
            events = [json.loads(line) for line in receipt.stdout.splitlines() if line.strip()]
            assert any(event.get('type') == 'item.completed' and
                       event.get('item', {}).get('text', '').strip() == marker for event in events), events
            provider.settle_children()
            assert provider.observed_raw() < provider.max_raw
            return events

        events = child(['--color', 'never', '--json', '-'], 'PI_CHILD_OK')
        child_id = next(event['thread_id'] for event in events if event.get('type') == 'thread.started')
        child(['resume', '--json', child_id, '-'], 'PI_CHILD_RESUME_OK')
        report = provider.report()
        assert report['measurement_complete'], report
        nested = report['nested']
        assert len(nested['threads']) == 1 and len(nested['threads'][child_id]['turns']) == 2, nested
        assert report['observed_raw_tokens'] == report['parent_observed_raw_tokens'] + nested['observed_raw_tokens']
        assert nested['observed_raw_tokens'] > 0
        transport = [json.loads(line)['event'] for line in (provider.artifacts / 'transport.jsonl').read_text().splitlines()]
        tools = [event for event in transport if event.get('type') == 'tool_execution_end']
        assert sum(event.get('toolName') == 'write' and event.get('isError') for event in tools) == 2, tools
        assert any(event.get('toolName') == 'bash' and str(provider.commands.bin / 'codex') in json.dumps(event) for event in tools), tools
        result.update(status='passed', scenarios=['read-only tools', 'same-session write/read-only transitions',
            'guarded PATH in Pi bash', 'same-model child launch/resume', 'parent plus child accounting'])
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        provider.close()
        result['usage'] = provider.report()
        save_json(out / 'result.json', result)
    print(json.dumps({'status': result['status'], 'error': result.get('error'),
                      'raw': result['usage']['observed_raw_tokens'],
                      'nested_raw': result['usage']['nested']['observed_raw_tokens']}))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
