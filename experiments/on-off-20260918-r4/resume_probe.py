"""Two bounded subscription replies verify real parent resume accounting."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.continuation import configuration_matches, restore_provider
from lab.host import git, save_json, snapshot
from lab.provider import Codex
from audit import inspect_native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--resume-first', type=Path)
    parser.add_argument('--redundant-trust', action='append', default=[])
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = output/'checkout'
    if args.resume_first:
        repo.symlink_to((args.resume_first/'checkout').resolve(), target_is_directory=True)
        repo = repo.resolve()
    else:
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--',
                        str(args.source.resolve()), str(repo)], check=True, timeout=60)
    before = snapshot(repo)
    created, started = time.time(), time.monotonic()
    prior_duration = json.loads((args.resume_first/'result.json').read_text())['duration_seconds'] if args.resume_first else 0
    deadline = started+300-prior_duration
    provider = None
    result = {'status': 'failed', 'generation': 'two subscription replies maximum',
              'limits': {'seconds': 300, 'raw': 200000, 'turns': 2}}
    try:
        if args.resume_first:
            first = json.loads((args.resume_first/'first-result.json').read_text())
            first_identity = json.loads((args.resume_first/'first/provider.json').read_text())
            first_reply = (args.resume_first/'first/turn-0001/reply.txt').read_text()
            thread = first['turns'][0]['thread_id']
            with (args.resume_first/'first/transport.jsonl').open() as stream:
                created = json.loads(stream.readline())['time']
            from lab.nested import NestedUsage
            sessions = NestedUsage(repo, 'gpt-5.5', 'xhigh').sessions
            result['prior_qualification'] = str(args.resume_first.resolve())
        else:
            provider = Codex(repo, output/'first', 'gpt-5.5', 'xhigh', deadline,
                             200000, 2, require_git_write=True)
            thread = provider.start_thread(writable=True)
            first_reply = provider.turn(thread,
                'Reply exactly PARENT_RESUME_ONE. Do not modify any file or run commands.',
                'first', writable=True)
            provider.close()
            first = provider.report()
            first_identity = provider.identity
            sessions = provider.nested.sessions
        save_json(output/'first-result.json', first)
        assert first_reply.strip() == 'PARENT_RESUME_ONE' and first['measurement_complete'], 'first reply or coverage'
        paths = list(sessions.glob('????/??/??/*-'+thread+'.jsonl'))
        assert len(paths) == 1, 'native history identity'
        native_path = paths[0]
        shutil.copyfile(native_path, output/'native-before-resume.jsonl')
        provider = Codex(repo, output/'second', 'gpt-5.5', 'xhigh', deadline,
                         200000, 2, require_git_write=True)
        assert configuration_matches(provider, first_identity, args.redundant_trust), 'effective configuration identity'
        restore_provider(provider, {'created_at_unix': created}, first, thread)
        assert provider.report()['observed_raw_tokens'] == first['observed_raw_tokens']
        second_reply = provider.turn(thread,
            'Reply exactly PARENT_RESUME_TWO. Do not modify any file or run commands.',
            'second', writable=True)
        provider.close()
        second = provider.report()
        save_json(output/'second-result.json', second)
        shutil.copyfile(native_path, output/'native-after-resume.jsonl')
        native = inspect_native(output/'native-after-resume.jsonl', 'gpt-5.5', 'xhigh')
        assert second_reply.strip() == 'PARENT_RESUME_TWO'
        assert second['measurement_complete'] and not native['errors'] and native['complete_child']
        assert native['raw'] == second['observed_raw_tokens'] > first['observed_raw_tokens']
        assert snapshot(repo) == before
        result.update(status='passed', thread=thread,
            first_raw=first['observed_raw_tokens'], cumulative_raw=second['observed_raw_tokens'],
            incremental_second_raw=second['observed_raw_tokens']-first['observed_raw_tokens'],
            identity=first_identity, native=native)
    except Exception as error:
        result['error'] = repr(error)
    finally:
        if provider and provider.process.poll() is None:
            provider.close()
        result['duration_seconds'] = time.monotonic()-started
        result['prior_duration_seconds'] = prior_duration
        save_json(output/'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'native'}, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
