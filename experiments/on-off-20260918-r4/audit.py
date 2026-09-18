"""Independent read-only terminal audit, including command-launched conversations."""
import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def transport_records(paths):
    for path in paths:
        yield from lines(path)


def function_forms(source, names):
    functions = {node.name: ast.dump(node, include_attributes=False)
                 for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    return {name: functions[name] for name in names}


def native_prefix_errors(folder, pins, native):
    errors = []
    for thread, expected in pins.items():
        saved = folder/'prior-native'/(thread+'.jsonl')
        if sha(saved) != expected:
            errors.append('archived native boundary changed: '+thread)
            continue
        if thread not in native:
            errors.append('archived conversation absent from final history: '+thread)
            continue
        prefix = saved.read_bytes()
        with Path(native[thread]['path']).open('rb') as stream:
            if stream.read(len(prefix)) != prefix:
                errors.append('native history does not preserve original prefix: '+thread)
    return errors


def continuation_context(folder, manifest, freeze, continuation_freeze):
    paths = [folder/'provider/transport.jsonl']
    start = manifest['created_at_unix']
    if not manifest.get('continuation'):
        return paths, start, freeze, None, []
    if continuation_freeze is None:
        raise ValueError('continued observations require their explicit freeze')
    link = manifest['continuation']
    previous = Path(link['previous'])
    old_manifest, old_result = read(previous/'manifest.json'), read(previous/'result.json')
    saved = read(folder/'continuation-input.json')
    expected = next(r for r in continuation_freeze['observations'] if r['name'] == previous.name)
    errors = []
    if (previous.parent != folder.parent or folder.name != previous.name+'-continued' or
            (folder/'checkout').resolve() != (previous/'checkout').resolve()):
        errors.append('continuation checkout/path linkage differs')
    if any(manifest[k] != old_manifest[k] for k in
           ('benchmark', 'base_commit', 'model', 'effort', 'factors', 'workflow', 'transport')):
        errors.append('continuation changes a preserved benchmark setting')
    if old_manifest['source_sha256'] != freeze['source_sha256']:
        errors.append('original source differs from its freeze')
    if (sha(previous/'result.json') != expected['prior_result_sha256'] or
            link['prior_result_sha256'] != expected['prior_result_sha256'] or
            saved['prior_result_sha256'] != expected['prior_result_sha256']):
        errors.append('original result hash differs')
    if (saved != read(previous/'continuation.json') or
            saved['source_head'] != expected['source_head'] or
            link['source_head'] != expected['source_head'] or
            saved['bundle_sha256'] != sha(folder/'input.bundle')):
        errors.append('saved source/continuation claim differs')
    if (old_result['usage']['observed_raw_tokens'] != expected['prior_raw'] or
            not old_result['usage']['measurement_complete'] or
            old_result['duration_seconds'] != expected['prior_duration_seconds'] or
            manifest['limits']['seconds'] != expected['remaining_seconds'] or
            link['original_limits'] != old_manifest['limits'] or
            manifest['limits']['observed_raw_tokens'] != old_manifest['limits']['observed_raw_tokens'] or
            manifest['limits']['turns'] != old_manifest['limits']['turns']):
        errors.append('earlier accounting or total allocation differs')
    proof = read(folder/'provider/config-equivalence.json')
    if (proof['original_sha256'] != freeze['effective_config_sha256'] or
            proof['actual_sha256'] != continuation_freeze['actual_effective_config_sha256'] or
            sorted(proof['removed_redundant_trust_records']) != sorted(continuation_freeze['redundant_trust']) or
            proof['global_config_modified'] is not False):
        errors.append('configuration equivalence receipt differs from freeze')
    effective = dict(freeze, source_sha256=continuation_freeze['source_sha256'],
                     effective_config_sha256=continuation_freeze['actual_effective_config_sha256'])
    paths.insert(0, previous/'provider/transport.jsonl')
    start = old_manifest['created_at_unix']
    saved['repair_pause_seconds'] = manifest['created_at_unix']-start-old_result['duration_seconds']
    return paths, start, effective, saved, errors


def source_bridge(freeze, continuation_freeze):
    root = Path(__file__).resolve().parents[2]
    old = subprocess.check_output(['git', 'show', '3f54c08:lab/workflow.py'], cwd=root).decode()
    new = subprocess.check_output(['git', 'show', '196b660:lab/workflow.py'], cwd=root).decode()
    names = ['review_clean', 'author_prompt', 'review_prompt', 'integration_prompts', 'after_read_fixture']
    unchanged = ['config.py', 'host.py', 'provider.py', 'nested.py', 'environment.py']
    return {
        'old_commit': '3f54c08', 'new_commit': '196b660',
        'workflow_sources_match_freeze': hashlib.sha256(old.encode()).hexdigest() == freeze['source_sha256']['workflow.py'] and
            hashlib.sha256(new.encode()).hexdigest() == continuation_freeze['source_sha256']['workflow.py'],
        'measured_prompt_functions_identical': function_forms(old, names) == function_forms(new, names),
        'unchanged_shared_modules': {name: freeze['source_sha256'][name] == continuation_freeze['source_sha256'][name] for name in unchanged},
        'remaining_difference': 'final native marker parsing and explicit cost-preserving continuation; live observer includes earlier costs',
        'limitation': 'mixed runner revisions and a recorded supervision pause; comparison keys remain different'}


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


def audit(folder, freeze, continuation_freeze=None):
    folder = folder.resolve()
    result, manifest = read(folder/'result.json'), read(folder/'manifest.json')
    identity = read(folder/'provider/provider.json')
    paths, native_since, freeze, continuation, errors = continuation_context(folder, manifest, freeze, continuation_freeze)
    parent, owned_parents, messages, prices, completed = {}, set(), {}, {}, {}
    for position, row in enumerate(transport_records(paths), 1):
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
    start = datetime.fromtimestamp(native_since, timezone.utc).date()-timedelta(days=1)
    end = datetime.now(timezone.utc).date()+timedelta(days=1)
    sessions = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
    day = start
    while day <= end:
        for path in (sessions/day.strftime('%Y/%m/%d')).glob('*.jsonl'):
            with path.open() as stream:
                first = json.loads(stream.readline())
            meta = first.get('payload', {})
            if first.get('type') != 'session_meta' or not Path(meta.get('cwd', '/')).resolve().is_relative_to((folder/'checkout').resolve()):
                continue
            thread = meta['id']
            if thread in native:
                errors.append('multiple native files for one conversation: '+thread)
                continue
            native[thread] = inspect_native(path, manifest['model'], manifest['effort'])
        day += timedelta(days=1)
    if continuation:
        errors.extend(native_prefix_errors(folder, continuation['native_sha256'], native))
    for thread, value in parent.items():
        if native.get(thread, {}).get('totals') != value:
            errors.append('parent native/transport mismatch: '+thread)
    children = {t: row for t, row in native.items() if t not in parent}
    for thread, row in native.items():
        errors.extend(thread+': '+e for e in row['errors'])
        if not row['model_matches']:
            errors.append('native model/effort mismatch: '+thread)
        if any(plan in ('api', 'unknown') for plan in row['plans']):
            errors.append('unrecognized subscription plan: '+thread)
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
        'transport_parts_sha256': {str(path): sha(path) for path in paths},
        'continuation': continuation,
        'all_agent_stages_finished': len(result['checkpoints']) == len(manifest['benchmark']['features']) and
            any(stage['stage'] == 'integration-accept' for stage in result['stages']),
        'scope': 'native histories rooted in this owned checkout; unrelated external generation is unsupported'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, default=Path(__file__).with_name('FREEZE.json'))
    parser.add_argument('--continuation-freeze', type=Path)
    args = parser.parse_args()
    freeze = read(args.freeze)
    continuation_freeze = read(args.continuation_freeze) if args.continuation_freeze else None
    rows = [audit(path, freeze, continuation_freeze) for path in args.runs]
    on = [r['total_raw'] for r in rows if r['run'].startswith('on-')]
    off = [r['total_raw'] for r in rows if r['run'].startswith('off-')]
    valid = len(on) == len(off) == 3 and all(r['qualified'] for r in rows) and len({r['comparison_key'] for r in rows}) == 1
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'generation': 'none',
        'runs': rows, 'complete_three_vs_three': valid, 'reduction_percent': None}
    if continuation_freeze:
        report['source_bridge'] = source_bridge(freeze, continuation_freeze)
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
