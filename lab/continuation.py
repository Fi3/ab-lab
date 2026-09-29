"""Explicit, cost-preserving recovery of a completed first native author."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from lab.host import Fatal, git, save_json
from lab.review import DEFAULT_PRIORITIES


def read(path):
    return json.loads(Path(path).read_text())


def configuration_matches(provider, expected, redundant_trust=()):
    """Prove exact equality after removing only named redundant trust records."""
    if provider.identity == expected:
        return True
    key = 'effective_config_sha256'
    if ({k: v for k, v in provider.identity.items() if k != key} !=
            {k: v for k, v in expected.items() if k != key}) or not redundant_trust:
        return False
    config = provider.rpc('config/read', {'includeLayers': False})['config']
    config = json.loads(json.dumps(config, sort_keys=True).replace(str(provider.artifacts.resolve()), '<RUN_PROVIDER>'))
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    if digest(config) != provider.identity[key]:
        return False
    projects = config.get('projects', {})
    omitted = set(redundant_trust)
    for name in omitted:
        if not Path(name).is_absolute() or projects.get(name) != {'trust_level': 'trusted'}:
            return False
        if not any(str(parent) not in omitted and projects.get(str(parent), {}).get('trust_level') == 'trusted'
                   for parent in Path(name).parents):
            return False
    for name in omitted:
        del projects[name]
    if digest(config) != expected[key]:
        return False
    save_json(provider.artifacts/'config-equivalence.json', {
        'original_sha256': expected[key], 'actual_sha256': provider.identity[key],
        'removed_redundant_trust_records': sorted(omitted),
        'proof': 'original hash reproduced exactly; every removed entry already inherits trusted status',
        'global_config_modified': False})
    return True


def inspect_boundary(previous, expected_head):
    from lab.workflow import native_done
    previous = Path(previous).resolve()
    result, manifest = read(previous/'result.json'), read(previous/'manifest.json')
    usage = result['usage']
    first = manifest['benchmark']['features'][0]['id']+'-implement'
    stages = result['stages']
    if (result['status'] != 'failed' or
            result.get('error') != 'native author did not supply the stage-completion marker' or
            result.get('checkpoints') or len(stages) != 1 or stages[0]['stage'] != first or
            manifest['factors']['C17'] or result['factors'] != manifest['factors']):
        raise ValueError('only the stopped first native completion boundary is recoverable')
    if (not usage['measurement_complete'] or usage.get('uncertainties') or
            usage.get('unpriced_or_incomplete_turns') or len(usage['turns']) != 1 or
            usage['turns'][0]['status'] != 'completed'):
        raise ValueError('prior work needs complete, terminal accounting')
    reply = (previous/'provider/turn-0001/reply.txt').read_text()
    if not native_done(reply):
        raise ValueError('saved reply does not contain a valid final marker')
    checkout = previous/'checkout'
    if git(checkout, 'rev-parse', 'HEAD').decode().strip() != expected_head or git(checkout, 'status', '--porcelain'):
        raise ValueError('saved source differs from the expected clean checkpoint')
    git(checkout, 'merge-base', '--is-ancestor', manifest['base_commit'], 'HEAD')
    remaining = manifest['limits']['seconds']-result['duration_seconds']
    if remaining <= 0 or usage['observed_raw_tokens'] >= manifest['limits']['observed_raw_tokens']:
        raise ValueError('original allocation is exhausted')
    if (previous/'continuation.json').exists():
        raise ValueError('this boundary already has a continuation; no automatic repeat')
    return {'previous': previous, 'checkout': checkout, 'manifest': manifest,
            'result': result, 'identity': read(previous/'provider/provider.json'),
            'author': stages[0]['thread_id'], 'remaining_seconds': remaining,
            'source_head': expected_head, 'reply': reply,
            'prior_result_sha256': hashlib.sha256((previous/'result.json').read_bytes()).hexdigest()}


def archive_boundary(record, output):
    """Keep exact pre-continuation evidence before the original checkout moves."""
    previous, checkout = record['previous'], record['checkout']
    git(checkout, 'bundle', 'create', str(output/'input.bundle'), 'HEAD')
    folder = output/'prior-native'
    folder.mkdir()
    sessions = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
    usage = record['result']['usage']
    threads = set(usage['thread_totals']) | set(usage['nested']['thread_totals'])
    pins = {}
    for thread in sorted(threads):
        uuid.UUID(thread)
        paths = list(sessions.glob('????/??/??/*-'+thread+'.jsonl'))
        if len(paths) != 1:
            raise ValueError('expected one native history for '+thread)
        target = folder/(thread+'.jsonl')
        shutil.copyfile(paths[0], target)
        pins[thread] = hashlib.sha256(target.read_bytes()).hexdigest()
    metadata = {'previous': str(previous), 'output': str(output),
        'source_head': record['source_head'],
        'source_tree': git(checkout, 'rev-parse', 'HEAD^{tree}').decode().strip(),
        'prior_result_sha256': record['prior_result_sha256'], 'native_sha256': pins,
        'prior_duration_seconds': record['result']['duration_seconds'],
        'remaining_seconds': record['remaining_seconds'],
        'bundle_sha256': hashlib.sha256((output/'input.bundle').read_bytes()).hexdigest()}
    save_json(output/'continuation-input.json', metadata)
    # Exclusive claim prevents two processes from resuming the same author.
    with (previous/'continuation.json').open('x') as stream:
        json.dump(metadata, stream, indent=2)
        stream.write('\n')


def restore_usage_counters(target, usage):
    """Retain each source's baseline so ordinary updates do not erase compaction cost."""
    target.totals = {k: tuple(v) for k, v in usage['thread_totals'].items()}
    target.transport_totals = {k: tuple(v) for k, v in
        usage.get('app_server_thread_totals', usage['thread_totals']).items()}
    target.native_totals = {k: tuple(v) for k, v in usage.get('native_thread_totals', {}).items()}
    target.uncertain = list(usage.get('uncertainties', []))


def restore_provider(provider, manifest, usage, author):
    restore_usage_counters(provider.usage, usage)
    provider.turns = copy.deepcopy(usage['turns'])
    provider.parent_threads = set(usage['thread_totals'])
    provider.nested.started = manifest['created_at_unix']
    resumed = provider.rpc('thread/resume', {'threadId': author,
        'cwd': str(provider.repo), 'model': provider.model, 'modelProvider': 'openai',
        'approvalPolicy': 'never', 'sandbox': 'workspace-write',
        'config': {'model_reasoning_effort': provider.effort}})
    if resumed['thread']['id'] != author:
        raise Fatal('resume returned a different author conversation')
    if hasattr(provider, 'register_native_thread'):
        original = usage.get('native_usage', {}).get(author, {})
        provider.register_native_thread(resumed['thread'], cwd=original.get('cwd'))


def continue_native(previous, output, expected_head, *, backend=None, redundant_trust=()):
    from lab.provider import Codex
    from lab.workflow import run
    record = inspect_boundary(previous, expected_head)
    record['redundant_trust'] = list(redundant_trust)
    manifest = record['manifest']
    return run(manifest['benchmark'], manifest['factors'], output,
        record['remaining_seconds'], manifest['limits']['observed_raw_tokens'],
        manifest['limits']['turns'], manifest['model'], manifest['effort'],
        backend=backend or Codex, _prepared=record,
        skip_linearization=manifest.get('skip_linearization', False),
        review_priorities=manifest.get('review_priorities', DEFAULT_PRIORITIES),
        loop_options=manifest.get('loop_policy', {'enabled': False}),
        scb_check=manifest.get('scb_check', {}).get('executable'),
        scb_seconds=manifest.get('scb_check', {}).get('seconds_per_check', 300))
