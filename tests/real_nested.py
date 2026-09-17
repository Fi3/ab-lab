"""Bounded real verification of nested calls and an unchanged reviewed feature."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import shlex

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import settings
from lab.host import git, save_json
from lab.provider import Codex
from lab.workflow import run


def preflight(out):
    source = ROOT / 'runs/real-workflow-001/checkout'
    repo = out / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--', str(source), str(repo)], check=True)
    provider = Codex(repo, out / 'provider', 'gpt-5.5', 'xhigh', time.monotonic()+45, 1, 1)
    try:
        result = provider.rpc('command/exec', {'command': ['/bin/bash', '-lc',
            'command -v codex && codex --version && test -z "$OPENAI_API_KEY$CODEX_API_KEY"'],
            'cwd': str(repo), 'sandboxPolicy': {'type': 'readOnly'}, 'timeoutMs': 10000})
        save_json(out / 'command-result.json', result)
        if result['exitCode'] or str(provider.commands.bin / 'codex') not in result['stdout']:
            raise AssertionError('native shell did not preserve the guarded Codex path')
        return provider.identity
    finally:
        provider.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    if args.preflight_only:
        print(json.dumps(preflight(out), indent=2))
        return 0
    source = ROOT / 'runs/real-workflow-001/checkout'
    before = git(source, 'rev-parse', 'HEAD').decode().strip()
    child_check = '''import json,subprocess
def call(args,prompt,marker):
    r=subprocess.run(['codex','--sandbox','read-only','--ask-for-approval','never','exec',*args],input=prompt+'\\n',text=True,capture_output=True,timeout=60)
    print(r.stdout); print(r.stderr)
    assert r.returncode == 0, r.returncode
    rows=[json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert any(row.get('type') == 'item.completed' and row.get('item',{}).get('text') == marker for row in rows), rows
    return rows
rows=call(['--color','never','--json','-'],'Reply exactly CHILD_LAUNCH_OK without tools or file changes.','CHILD_LAUNCH_OK')
thread=next(row['thread_id'] for row in rows if row.get('type') == 'thread.started')
call(['resume','--json',thread,'-'],'Reply exactly CHILD_RESUME_OK without tools or file changes.','CHILD_RESUME_OK')
'''
    request = ('Verify that is_even(value) already implements integer parity including zero and negative integers, '
        'with existing unittest coverage. Do not change files if the requested behavior and tests already exist. '
        'During the author stage only, execute this exact real Codex launch/resume verification command. '
        'It captures output in memory, creates no source files, and asserts both replies. '
        'Do not rebuild the command, write temporary output files, use a status slash command, '
        'or change model/login settings. Reviewers only inspect the '
        'author verification evidence and existing feature; they need not repeat nested model generation.')
    request += '\nVerification command:\npython3 -c '+shlex.quote(child_check)
    benchmark = {'name': 'existing-feature-and-nested-codex', 'repo': str(source), 'revision': before,
        'features': [{'id': 'existing-parity', 'request': request}],
        'checks': ['python3 -m unittest discover -s tests -v'], 'defer_documentation': True,
        'instructions': 'Use only Python standard library. Keep source unchanged if already correct.'}
    save_json(out / 'admission.json', {'purpose': 'real nested and no-change qualification',
        'benchmark': benchmark, 'seconds': 600, 'observed_raw': 500000, 'turns': 16,
        'created_at_unix': time.time()})
    result = run(benchmark, settings({}), out / 'workflow', 600, 500000, 16)
    assert git(source, 'rev-parse', 'HEAD').decode().strip() == before
    nested = result.get('usage', {}).get('nested', {})
    qualified = (result['status'] == 'passed' and result['usage']['measurement_complete']
        and len(result['checkpoints']) == 1 and result['checkpoints'][0]['already_satisfied']
        and len(nested.get('threads', {})) == 1
        and sum(len(t['turns']) for t in nested['threads'].values()) == 2
        and nested['observed_raw_tokens'] > 0)
    save_json(out / 'result.json', {'status': 'passed' if qualified else 'failed',
        'workflow_status': result['status'], 'error': result.get('error'),
        'usage': result['usage'], 'checkpoints': result['checkpoints'], 'source_unchanged': True})
    print(json.dumps({'qualified': qualified, 'workflow': result['status'],
                      'raw': result['usage'].get('observed_raw_tokens'), 'error': result.get('error')}, indent=2))
    return int(not qualified)


if __name__ == '__main__':
    raise SystemExit(main())
