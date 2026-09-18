"""Execute the frozen no-model diagnostic without changing a benchmark result."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.environment import clean_env
from lab.host import execute_child, git, save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    plan_path = Path(__file__).with_name('FINAL-CHECK-PLAN.json')
    plan = json.loads(plan_path.read_text())
    source = Path(plan['source']).resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'generation': 'none', 'source': str(source), 'status': 'failed',
              'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(), 'checks': []}
    def unchanged():
        return (git(source, 'rev-parse', 'HEAD').decode().strip() == plan['expected_head']
                and not git(source, 'status', '--porcelain'))
    try:
        if not unchanged():
            raise ValueError('source is not the pinned clean terminal result')
        report['source_commit'] = plan['expected_head']
        env = clean_env(dict(os.environ, CARGO_BUILD_JOBS=str(plan['CARGO_BUILD_JOBS']),
                             CARGO_TERM_COLOR='never'))
        for index, check in enumerate(plan['checks'], 1):
            folder = args.output/str(index)
            folder.mkdir()
            receipt = execute_child(check['argv'], source, None, folder/'stdout.txt',
                                    folder/'stderr.txt', check['seconds'], env)
            save_json(folder/'result.json', receipt)
            report['checks'].append(receipt)
        if not unchanged():
            raise ValueError('diagnostic changed the pinned source')
        report['status'] = 'passed' if all(c['exit_code'] == 0 and not c['timed_out']
            and not c['cancelled_signal'] for c in report['checks']) else 'failed'
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        save_json(args.output/'result.json', report)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
