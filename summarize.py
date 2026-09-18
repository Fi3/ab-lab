#!/usr/bin/env python3
"""Print a compact table from run/batch JSON files or JSON on standard input."""
import argparse
import json
from pathlib import Path
import sys

from lab.summary import records, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path, nargs='*', help='one or more JSON files; omit to read stdin')
    args = parser.parse_args()
    try:
        if args.results:
            rows = [row for path in args.results for row in records(json.loads(path.read_text()))]
        else:
            if sys.stdin.isatty():
                raise ValueError('supply a result JSON file or pipe JSON into this script')
            rows = records(json.load(sys.stdin))
        print(render(rows), end='')
        return 0
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f'summarize: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
