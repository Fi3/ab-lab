"""Read-only Markdown summaries of single runs, batches and report arrays."""
from collections import Counter
import json
import math
from pathlib import Path
import re


def records(value):
    if isinstance(value, dict) and 'results' in value:
        value = value['results']
    if isinstance(value, list):
        if not value:
            raise ValueError('the JSON contains no runs')
        return [row for item in value for row in records(item)]
    if (not isinstance(value, dict) or value.get('status') not in
            ('passed', 'failed', 'not_run', 'running', 'cancelled') or
            not isinstance(value.get('usage'), dict)):
        raise ValueError('expected a run result, a batch result, or an array of run reports')
    return [value]


def cell(value):
    text = str(value) if value is not None else '—'
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text).replace('|', '\\|')


def table(headers, rows):
    rows = [[cell(value) for value in row] for row in [headers, *rows]]
    widths = [max(len(row[index]) for row in rows) for index in range(len(headers))]
    def line(row):
        return '| '+' | '.join(value.ljust(width) for value, width in zip(row, widths))+' |'
    return '\n'.join([line(rows[0]), '| '+' | '.join('-'*width for width in widths)+' |',
                       *(line(row) for row in rows[1:])])


def count(value):
    return value if type(value) is int and value >= 0 else None


def number(value):
    value = count(value)
    return f'{value:,}' if value is not None else '—'


def duration(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return '—'
    if value < 60:
        return f'{value:.1f}s'
    minutes, seconds = divmod(int(value), 60)
    if minutes < 60:
        return f'{minutes}m {seconds:02d}s'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m {seconds:02d}s'


def fraction(finished, expected):
    return f'{finished}/{expected if count(expected) is not None else "?"}'


def enabled(row):
    factors = row.get('factors')
    if not isinstance(factors, dict):
        return 'unknown'
    return ','.join(key for key, value in sorted(factors.items()) if value is True) or 'none'


def label(row, index):
    path = Path(row.get('output') or row.get('path') or f'run-{index+1:03d}')
    if not row.get('output') and path.name == 'result.json':
        path = path.parent
    return path.name or str(path)


def render(rows):
    if not rows:
        raise ValueError('no runs to summarize')
    seen = set()
    for row in rows:
        value = row.get('output') or row.get('path')
        if value:
            identity = Path(value)
            if not row.get('output') and identity.name == 'result.json':
                identity = identity.parent
            identity = str(identity.resolve())
            if identity in seen:
                raise ValueError('duplicate run: '+identity+'; supply the batch OR its individual results, not both')
            seen.add(identity)
    names = [label(row, index) for index, row in enumerate(rows)]
    duplicates = Counter(names)
    names = [str(row.get('output') or row.get('path') or name) if duplicates[name] > 1 else name
             for row, name in zip(rows, names)]
    counts = Counter(row['status'] for row in rows)
    lines = ['Runs: '+str(len(rows))+' | '+' | '.join(f'{key}: {value}' for key, value in counts.items()), '']
    main_rows = []
    for name, row in zip(names, rows):
        usage = row['usage']
        complete = {True: 'complete', False: 'incomplete', None: 'unknown'}.get(usage.get('measurement_complete'), 'unknown')
        checkpoints, checks = row.get('checkpoints'), row.get('checks')
        features = fraction(len(checkpoints), row.get('feature_count')) if isinstance(checkpoints, list) else '—'
        if isinstance(checks, list):
            passed = sum(item.get('exit_code') == 0 and not item.get('timed_out') and not item.get('cancelled_signal') for item in checks)
            checks = fraction(passed, row.get('check_count'))
        else:
            checks = '—'
        main_rows.append([name, row['status'], number(usage.get('observed_raw_tokens')),
            number(usage.get('cached_input_tokens')), complete, duration(row.get('duration_seconds')),
            features, checks])
    lines += [table(['Run', 'Result', 'Raw tokens', 'Cached input', 'Usage', 'Time', 'Reviewed features', 'Checks'], main_rows), '',
              'Reviewed features counts reviewer approvals, not independent feature acceptance tests.', '']
    configurations = [enabled(row) for row in rows]
    if len(set(configurations)) == 1:
        lines += ['Enabled switches: '+cell(configurations[0])+'.', '']
    else:
        lines += [table(['Run', 'Enabled switches'], list(zip(names, configurations))), '']

    known = [value for row in rows if (value := count(row['usage'].get('observed_raw_tokens'))) is not None]
    if known:
        lines.append(f'Observed raw tokens: {sum(known):,} ({len(known)}/{len(rows)} runs reported a number).')
    eligible = [row for row in rows if row['status'] == 'passed' and
                row['usage'].get('measurement_complete') is True and count(row['usage'].get('observed_raw_tokens')) is not None]
    keys = {(row.get('comparison_key'), json.dumps(row.get('factors'), sort_keys=True)) for row in eligible}
    if eligible and len(keys) == 1 and all(row.get('comparison_key') for row in eligible):
        average = sum(row['usage']['observed_raw_tokens'] for row in eligible)/len(eligible)
        lines.append(f'Mean raw tokens: {average:,.0f} ({len(eligible)} passed, fully measured run'+
                     ('s' if len(eligible) != 1 else '')+' with matching settings).')
    elif len(eligible) > 1:
        lines.append('No average shown: run settings differ or comparison metadata is missing.')
    if any(row['usage'].get('measurement_complete') is not True for row in rows):
        lines.append('Incomplete usage means the token number is an observed amount, not a complete total. Missing values are not zero.')
    errors = [(name, row['error']) for name, row in zip(names, rows) if row.get('error')]
    if errors:
        lines += ['', 'Errors:', '']+[f'- {cell(name)}: {cell(error)[:300]}' for name, error in errors]

    if any(isinstance(row.get('scb_check'), dict) for row in rows):
        quality_rows = []
        for name, row in zip(names, rows):
            measurements = (row.get('scb_check') or {}).get('measurements', {})
            for phase, title in (('before_changes', 'Before edits'), ('after_implementation', 'After implementation'),
                                 ('after_assembly', 'After assembly')):
                measurement = measurements.get(phase, {})
                report = measurement.get('report') or {}
                values = []
                for key in ('verbosity', 'erosion', 'cog_erosion'):
                    value = report.get(key)
                    values.append(f'{100*value:.2f}%' if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 else '—')
                quality_rows.append([name, title, measurement.get('status', 'not_recorded'), *values])
        lines += ['', 'Code-quality measurements (scb-check scores, not token savings):', '',
            table(['Run', 'Checkpoint', 'Status', 'Verbosity', 'Erosion', 'Cognitive erosion'], quality_rows)]
    return '\n'.join(lines)+'\n'
