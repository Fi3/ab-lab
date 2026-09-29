"""One bounded real Pi turn verifying large read-only shell output."""
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
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'checkout'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    save_json(out / 'admission.json', {
        'model': 'gpt-5.5', 'effort': 'xhigh', 'seconds': 120,
        'max_observed_raw': 60000, 'parent_turns': 1,
        'generation': 'ChatGPT subscription only',
        'scenario': 'native bash truncation and read-back under read-only permissions',
    })
    provider = Pi(repo, out / 'provider', 'gpt-5.5', 'xhigh', time.monotonic()+120, 60000, 1)
    result = {'status': 'failed'}
    try:
        thread = provider.start_thread()
        provider.turn(thread,
            'This is a read-only native-tool verification. Use the native bash tool exactly once '
            'to execute: seq 1 3000\n'
            'The truncated output should include a full-output file path. Use the native read tool '
            'to read that path with offset 2999 and limit 2. Do not use other commands or tools, '
            'write files, or retry failures. If those lines are 2999 and 3000, reply exactly '
            'PI_LARGE_OUTPUT_OK. Otherwise report the error.', 'large-output')
        events = [json.loads(line)['event'] for line in
                  (provider.artifacts / 'transport.jsonl').read_text().splitlines()]
        results = [event for event in events if event.get('type') == 'tool_execution_end']
        assert not any(event.get('isError') for event in results), results
        bash = [event for event in results if event.get('toolName') == 'bash']
        reads = [event for event in results if event.get('toolName') == 'read']
        assert len(bash) == len(reads) == 1, results
        details = bash[0]['result']['details']
        assert details['truncation']['truncated'], details
        output = Path(details['fullOutputPath'])
        assert output.read_text() == ''.join(f'{number}\n' for number in range(1, 3001))
        assert reads[0]['result']['content'][0]['text'].splitlines()[:2] == ['2999', '3000'], reads
        assert provider.report()['measurement_complete'], provider.report()
        result.update(status='passed', full_output_path=str(output),
                      scenario='one native bash call, successful full-output read-back, no retries')
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        provider.close()
        result['usage'] = provider.report()
        save_json(out / 'result.json', result)
    print(json.dumps({'status': result['status'], 'error': result.get('error'),
                      'raw': result['usage']['observed_raw_tokens'], 'output': str(out)}))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
