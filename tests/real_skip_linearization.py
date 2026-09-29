"""Opt-in real-provider check: finish docs without rewriting reviewed commits."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.host import git, save_json, snapshot
from lab.provider import Codex, Pi
from lab.workflow import integration_prompts


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
    git(repo, 'config', 'user.name', 'History preservation test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'commit.gpgSign', 'false')
    git(repo, 'commit', '--allow-empty', '-qm', 'ADD smoke fixture base')
    base = git(repo, 'rev-parse', 'HEAD').decode().strip()
    (repo / 'answer.py').write_text('def answer():\n    return 42\n')
    (repo / '.gitignore').write_text('__pycache__/\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'ADD answer function')
    (repo / 'test_answer.py').write_text('import unittest\nfrom answer import answer\n'
        'class AnswerTest(unittest.TestCase):\n'
        '    def test_answer(self):\n        self.assertEqual(answer(), 42)\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'ADD answer coverage')
    reviewed = git(repo, 'rev-parse', 'HEAD').decode().strip()
    commits = git(repo, 'rev-list', '--reverse', base+'..HEAD').decode().splitlines()
    bench = {'features': [{'id': 'answer', 'request': 'Expose answer() returning 42.'}],
        'checks': ['python3 -m unittest -v test_answer'],
        'instructions': 'Use only the standard library. Document answer() in README.md. '
                        'The implementation and tests are complete; no other edits are needed.'}
    checkpoints = [{'feature': 'answer', 'request': bench['features'][0]['request'],
                    'base': base, 'reviewed_head': reviewed}]
    save_json(out / 'admission.json', {'harness': args.harness, 'model': 'gpt-5.5',
        'effort': 'xhigh', 'seconds': 120, 'max_raw': 100000, 'max_turns': 2,
        'skip_linearization': True, 'reviewed_commits': commits})
    provider = None
    result = {'status': 'failed', 'reviewed_commits': commits}
    try:
        backend = Codex if args.harness == 'codex' else Pi
        provider = backend(repo, out / 'provider', 'gpt-5.5', 'xhigh',
                           time.monotonic()+120, 100000, 2, require_git_write=True)
        thread = provider.start_thread()
        plan, accept = integration_prompts(bench, base, checkpoints, skip_linearization=True)
        before = snapshot(repo)
        provider.turn(thread, plan, 'integration-plan')
        assert snapshot(repo) == before, 'planning changed source/history'
        provider.turn(thread, accept, 'integration-accept', writable=True)
        assert not git(repo, 'rev-list', reviewed, '--not', 'HEAD'), 'reviewed commits lost'
        assert not git(repo, 'status', '--porcelain'), 'unclean checkout'
        assert git(repo, 'diff', '--name-only', reviewed, 'HEAD').decode().splitlines() == ['README.md']
        assert 'answer' in (repo / 'README.md').read_text()
        import subprocess
        subprocess.run([sys.executable, '-m', 'unittest', '-v', 'test_answer'],
                       cwd=repo, check=True, capture_output=True, timeout=10)
        result.update(status='passed', final_commits=git(repo, 'rev-list', '--reverse', base+'..HEAD').decode().splitlines())
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if provider:
            provider.close()
            result['usage'] = provider.report()
            if not result['usage']['measurement_complete']:
                result.update(status='failed', error='incomplete usage measurement')
        save_json(out / 'result.json', result)
    print(json.dumps({'status': result['status'], 'error': result.get('error'),
        'raw': result.get('usage', {}).get('observed_raw_tokens'), 'output': str(out)}))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
