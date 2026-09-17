"""Single bounded native-command child probe; no parent model response."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.host import save_json
from lab.provider import Codex

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--',
        str(ROOT / 'runs/real-workflow-001/checkout'), str(repo)], check=True)
    save_json(out / 'admission.json', {'seconds': 60, 'max_observed_raw': 50000,
        'child_responses': 1, 'parent_responses': 0, 'created_at_unix': time.time()})
    provider = Codex(repo, out / 'provider', 'gpt-5.5', 'xhigh', time.monotonic()+60, 50000, 1)
    result = {'status': 'failed'}
    try:
        result['receipt'] = provider.rpc('command/exec', {'command': ['/bin/bash', '-lc',
            "printf '%s\\n' 'Reply exactly NATIVE_CHILD_OK without tools or file changes.' | codex --sandbox read-only --ask-for-approval never exec --color never --json -"],
            'cwd': str(repo), 'sandboxPolicy': provider.writable_policy(), 'timeoutMs': 55000}, timeout=58)
        result['nested'] = provider.child_report(force=True)
        if result['receipt']['exitCode'] == 0 and 'NATIVE_CHILD_OK' in result['receipt']['stdout'] and result['nested']['measurement_complete']:
            result['status'] = 'passed'
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        provider.close()
        save_json(out / 'result.json', result)
    print(json.dumps(result, indent=2))
    return int(result['status'] != 'passed')

if __name__ == '__main__':
    raise SystemExit(main())
