"""Independent read-only terminal audit, including command-launched conversations."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def inspect_native(path, model, effort):
    totals, errors, contexts, plans, active = [0, 0, 0], [], set(), set(), None
    turns, last_message, last_price, responses = {}, 0, 0, []
    for position, row in enumerate(lines(path), 1):
        payload = row.get('payload', {})
        kind = payload.get('type')
        if row['type'] == 'turn_context':
            contexts.add((payload.get('model'), payload.get('effort')))
        if row['type'] == 'response_item' and kind == 'message' and payload.get('role') == 'assistant':
            last_message = position
        if row['type'] != 'event_msg':
            continue
        if kind == 'task_started':
            active = payload['turn_id']
            turns[active] = {'started_raw': sum(totals[:2]), 'completed': False}
        elif kind == 'token_count' and payload.get('info'):
            info = payload['info']
            current = [info['total_token_usage'].get(k, 0)
                       for k in ('input_tokens', 'output_tokens', 'cached_input_tokens')]
            if any(a < b for a, b in zip(current, totals)):
                errors.append('native counter decreased')
                continue
            if current[:2] != totals[:2]:
                last_price = position
                last = info.get('last_token_usage') or {}
                delta = [current[i]-totals[i] for i in (0, 1)]
                if delta != [last.get('input_tokens'), last.get('output_tokens')]:
                    errors.append('native increment differs from last response')
                responses.append({'turn': active, 'raw': sum(delta), 'position': position})
            totals = current
            plan = (payload.get('rate_limits') or {}).get('plan_type')
            if plan:
                plans.add(plan)
        elif kind == 'task_complete':
            turn = turns.get(payload.get('turn_id'))
            if turn is None:
                errors.append('completion without native start')
            else:
                turn.update(completed=True, priced=sum(totals[:2]) > turn['started_raw'] and last_price >= last_message)
            active = None
        elif kind == 'turn_aborted':
            # Main C25 intentionally interrupts priced responses. Parent
            # completeness is independently checked from transport below.
            active = None
    return {'path': str(path), 'sha256': sha(path), 'totals': totals,
            'raw': sum(totals[:2]), 'contexts': sorted(contexts), 'plans': sorted(plans),
            'model_matches': bool(contexts) and contexts == {(model, effort)},
            'errors': errors, 'turns': turns, 'responses': responses,
            'complete_child': bool(turns) and bool(plans) and all(
                t.get('completed') and t.get('priced') for t in turns.values())}


def audit(folder, freeze):
    folder = folder.resolve()
    result, manifest = read(folder/'result.json'), read(folder/'manifest.json')
    identity = read(folder/'provider/provider.json')
    parent, owned_parents, messages, prices, completed, errors = {}, set(), {}, {}, {}, []
    for position, row in enumerate(lines(folder/'provider/transport.jsonl'), 1):
        event = row['event']
        started = (event.get('result') or {}).get('thread') or {}
        if started.get('id'):
            owned_parents.add(started['id'])
        params = event.get('params') or {}
        key = (params.get('threadId'), params.get('turnId') or (params.get('turn') or {}).get('id'))
        method = event.get('method')
        if method == 'item/completed' and (params.get('item') or {}).get('type') == 'agentMessage':
            messages[key] = position
        elif method == 'thread/tokenUsage/updated':
            count = params['tokenUsage']['total']
            current = [count[k] for k in ('inputTokens', 'outputTokens', 'cachedInputTokens')]
            previous = parent.get(key[0], [0, 0, 0])
            if any(a < b for a, b in zip(current, previous)):
                errors.append('parent counter decreased')
            if current[:2] != previous[:2]:
                prices[key] = position
            parent[key[0]] = current
        elif method == 'turn/completed':
            completed[key] = params['turn']['status']
    if not set(parent) <= owned_parents:
        errors.append('charged parent is not owned')
    for key, status in completed.items():
        if prices.get(key, 0) < messages.get(key, 1):
            errors.append('parent final message lacks a later price: '+str(key))
    native = {}
    start = datetime.fromtimestamp(manifest['created_at_unix'], timezone.utc).date()-timedelta(days=1)
    end = datetime.now(timezone.utc).date()+timedelta(days=1)
    sessions = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
    day = start
    while day <= end:
        for path in (sessions/day.strftime('%Y/%m/%d')).glob('*.jsonl'):
            with path.open() as stream:
                first = json.loads(stream.readline())
            meta = first.get('payload', {})
            if first.get('type') != 'session_meta' or not Path(meta.get('cwd', '/')).resolve().is_relative_to(folder/'checkout'):
                continue
            thread = meta['id']
            if thread in native:
                errors.append('multiple native files for one conversation: '+thread)
                continue
            native[thread] = inspect_native(path, manifest['model'], manifest['effort'])
        day += timedelta(days=1)
    for thread, value in parent.items():
        if native.get(thread, {}).get('totals') != value:
            errors.append('parent native/transport mismatch: '+thread)
    children = {t: row for t, row in native.items() if t not in parent}
    for thread, row in native.items():
        errors.extend(thread+': '+e for e in row['errors'])
        if not row['model_matches']:
            errors.append('native model/effort mismatch: '+thread)
        if thread in children and not row['complete_child']:
            errors.append('child coverage incomplete: '+thread)
    raw_parent = sum(v[0]+v[1] for v in parent.values())
    raw_children = sum(v['raw'] for v in children.values())
    if raw_parent+raw_children != result['usage']['observed_raw_tokens']:
        errors.append('whole-workflow total differs from independently summed histories')
    if parent != result['usage']['thread_totals']:
        errors.append('parent thread table differs')
    if {t: r['totals'] for t, r in children.items()} != result['usage']['nested']['thread_totals']:
        errors.append('nested thread table differs')
    if manifest['source_sha256'] != freeze['source_sha256'] or manifest['base_commit'] != freeze['resolved_base']:
        errors.append('admitted source differs')
    if identity['effective_config_sha256'] != freeze['effective_config_sha256']:
        errors.append('provider configuration differs')
    qualified = result['status'] == 'passed' and result['usage']['measurement_complete'] and not errors
    return {'run': folder.name, 'status': result['status'], 'error': result.get('error'),
        'qualified': qualified, 'audit_errors': errors, 'parent_raw': raw_parent,
        'child_raw': raw_children, 'total_raw': raw_parent+raw_children,
        'comparison_key': result['comparison_key'], 'identity': identity,
        'duration_seconds': result['duration_seconds'], 'parent_turns': len(result['usage']['turns']),
        'native': native, 'child_ids': list(children), 'checkpoints': result['checkpoints'],
        'factor_activations': result['factor_activations'], 'result_sha256': sha(folder/'result.json'),
        'transport_sha256': sha(folder/'provider/transport.jsonl'),
        'scope': 'native histories rooted in this owned checkout; unrelated external generation is unsupported'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, default=Path(__file__).with_name('FREEZE.json'))
    args = parser.parse_args()
    rows = [audit(path, read(args.freeze)) for path in args.runs]
    on = [r['total_raw'] for r in rows if r['run'].startswith('on-')]
    off = [r['total_raw'] for r in rows if r['run'].startswith('off-')]
    valid = len(on) == len(off) == 3 and all(r['qualified'] for r in rows) and len({r['comparison_key'] for r in rows}) == 1
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'generation': 'none',
        'runs': rows, 'complete_three_vs_three': valid, 'reduction_percent': None}
    if valid:
        report.update(mean_on=statistics.mean(on), mean_off=statistics.mean(off),
            reduction_percent=100*(statistics.mean(off)-statistics.mean(on))/statistics.mean(off),
            denominator='mean raw tokens of the three complete all-off workflows')
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'runs'}, indent=2))
    for row in rows:
        print(row['run'], row['total_raw'], row['qualified'], row['audit_errors'])


if __name__ == '__main__':
    main()
