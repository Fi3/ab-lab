"""Explicit operator entry point; never creates a replacement observation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.continuation import continue_native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('previous', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--head', required=True)
    parser.add_argument('--redundant-trust', action='append', default=[])
    args = parser.parse_args()
    result = continue_native(args.previous, args.output, args.head,
                             redundant_trust=args.redundant_trust)
    print(json.dumps({'status': result['status'], 'error': result.get('error'),
        'raw': result['usage'].get('observed_raw_tokens'),
        'complete_accounting': result['usage'].get('measurement_complete')}, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
