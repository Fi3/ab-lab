"""Provider-free regressions for the retained two-part observation audit."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[1]/'experiments/on-off-20260918-r4/audit.py'
SPEC = importlib.util.spec_from_file_location('study_audit', PATH)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class ContinuationAuditTests(unittest.TestCase):
    def test_lineage_rejects_changed_factor_or_earlier_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, current = root/'off-01', root/'off-01-continued'
            (previous/'checkout').mkdir(parents=True)
            (current/'provider').mkdir(parents=True)
            (current/'checkout').symlink_to(previous/'checkout', target_is_directory=True)
            def put(path, value):
                path.write_text(json.dumps(value))
            original = {'benchmark': {'features': []}, 'base_commit': 'base',
                'model': 'model', 'effort': 'effort', 'factors': {'C17': False},
                'workflow': 'fixed', 'transport': 'fixed', 'created_at_unix': 1,
                'source_sha256': {'workflow.py': 'before'},
                'limits': {'seconds': 10, 'observed_raw_tokens': 100, 'turns': 3}}
            result = {'duration_seconds': 2, 'usage': {'observed_raw_tokens': 10,
                                                       'measurement_complete': True}}
            put(previous/'manifest.json', original)
            put(previous/'result.json', result)
            result_sha = AUDIT.sha(previous/'result.json')
            (current/'input.bundle').write_bytes(b'checkpoint')
            saved = {'source_head': 'head', 'prior_result_sha256': result_sha,
                     'bundle_sha256': AUDIT.sha(current/'input.bundle')}
            put(current/'continuation-input.json', saved)
            put(previous/'continuation.json', saved)
            put(current/'provider/config-equivalence.json', {
                'original_sha256': 'old', 'actual_sha256': 'new',
                'removed_redundant_trust_records': ['/trusted'], 'global_config_modified': False})
            freeze = {'source_sha256': original['source_sha256'], 'effective_config_sha256': 'old'}
            later = {'source_sha256': {'workflow.py': 'after'},
                'actual_effective_config_sha256': 'new', 'redundant_trust': ['/trusted'],
                'observations': [{'name': 'off-01', 'prior_result_sha256': result_sha,
                    'source_head': 'head', 'prior_raw': 10, 'prior_duration_seconds': 2, 'remaining_seconds': 8}]}
            manifest = dict(original, created_at_unix=20, limits=dict(original['limits'], seconds=8),
                continuation={'previous': str(previous), 'prior_result_sha256': result_sha,
                              'source_head': 'head', 'original_limits': original['limits']})
            paths, start, effective, lineage, errors = AUDIT.continuation_context(current, manifest, freeze, later)
            self.assertEqual(errors, [])
            self.assertEqual(start, 1)
            self.assertEqual(len(paths), 2)
            self.assertEqual(lineage['repair_pause_seconds'], 17)
            manifest['factors'] = {'C17': True}
            self.assertTrue(AUDIT.continuation_context(current, manifest, freeze, later)[-1])
            manifest['factors'] = original['factors']
            put(previous/'result.json', dict(result, changed=True))
            self.assertTrue(AUDIT.continuation_context(current, manifest, freeze, later)[-1])

    def test_transport_reader_keeps_old_then_new_without_summing_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root/'old.jsonl', root/'new.jsonl'
            old.write_text(json.dumps({'value': 110})+'\n')
            new.write_text(json.dumps({'value': 143})+'\n')
            rows = list(AUDIT.transport_records([old, new]))
            self.assertEqual(rows, [{'value': 110}, {'value': 143}])

    def test_native_boundary_requires_exact_retained_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'prior-native').mkdir()
            saved = root/'prior-native/thread.jsonl'
            live = root/'live.jsonl'
            saved.write_text('earlier-record\n')
            live.write_text('earlier-record\nlater-record\n')
            pins = {'thread': AUDIT.sha(saved)}
            native = {'thread': {'path': str(live)}}
            self.assertEqual(AUDIT.native_prefix_errors(root, pins, native), [])
            live.write_text('different-record\nlater-record\n')
            self.assertTrue(AUDIT.native_prefix_errors(root, pins, native))
            live.write_text('earlier-record\nlater-record\n')
            saved.write_text('tampered\n')
            self.assertTrue(AUDIT.native_prefix_errors(root, pins, native))

    def test_measured_prompt_functions_are_unchanged_across_repair(self):
        old = 'def author_prompt(x):\n    return x\n\ndef native_done(x):\n    return False\n'
        new = 'def author_prompt(x):\n    return x\n\ndef native_done(x):\n    return True\n'
        self.assertEqual(AUDIT.function_forms(old, ['author_prompt']),
                         AUDIT.function_forms(new, ['author_prompt']))
        changed = new.replace('return x', 'return str(x)')
        self.assertNotEqual(AUDIT.function_forms(old, ['author_prompt']),
                            AUDIT.function_forms(changed, ['author_prompt']))


if __name__ == '__main__':
    unittest.main()
