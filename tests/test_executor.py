"""Pinned execution must preserve native tools and isolate the host grader."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import patch

from lab.config import FACTORS, settings
from lab.evaluation import ADAPTERS, BaseEvaluator
from lab.executor import (GradingBridge, PRIVATE_ENV, RECEIPT_ENV, RemoteEvaluator, SCHEMA,
                          BUILD_FILES, DEFAULT_PROFILE, container_argv, fingerprint,
                          load_lock, merge_state, pinned_input, quality_proxy)
from lab.executor import normalize_runtime
from lab.executor import run_pinned
from lab.host import execute_child, git
from lab.sandbox import CommandSandbox
from lab.workflow import run
from test_core import repo_at
from test_evaluation import NativeAuthor
from test_scb import benchmark_at


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def recipe(self):
        for name in BUILD_FILES:
            (self.root / name).write_bytes((DEFAULT_PROFILE.parent / name).read_bytes())
        return self.root / 'default.json'

    def image_probe(self, path, architecture='amd64'):
        import hashlib
        profile = json.loads(path.read_text())
        inputs = {name: hashlib.sha256((path.parent / name).read_bytes()).hexdigest() for name in BUILD_FILES}
        inputs['profile'] = fingerprint(profile)
        return subprocess.CompletedProcess([], 0, json.dumps([{'Id': 'sha256:' + 'a' * 64,
            'Os': 'linux', 'Architecture': architecture,
            'Config': {'Labels': {'agent-lab.recipe': fingerprint(inputs)}}}]))

    def test_build_definition_cannot_depend_on_a_local_image(self):
        path = self.recipe()
        value = json.loads(path.read_text())
        value['image'] = 'sha256:' + 'a' * 64
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'public build recipe'):
            load_lock(path)

    def test_first_use_builds_and_recipe_identity_is_independent_of_clone_location(self):
        path = self.recipe()
        probe = self.image_probe(path)
        with patch('lab.executor.docker', side_effect=[subprocess.CalledProcessError(1, 'docker'), None, probe]) as mocked:
            rebuilt = load_lock(path)
        self.assertEqual(mocked.call_args_list[1].args[0], 'build')
        self.assertEqual(mocked.call_args_list[1].args[-1], path.parent)
        with patch('lab.executor.docker', return_value=self.image_probe(DEFAULT_PROFILE)):
            original = load_lock(DEFAULT_PROFILE)
        self.assertEqual(rebuilt['build_sha256'], original['build_sha256'])
        self.assertEqual(rebuilt['uid'], os.getuid())

    def test_wrong_platform_is_rejected_and_recipe_changes_invalidate_cache(self):
        path = self.recipe()
        with patch('lab.executor.docker', return_value=self.image_probe(path, 'arm64')), \
                self.assertRaisesRegex(ValueError, 'differs'):
            load_lock(path)
        with patch('lab.executor.docker', return_value=self.image_probe(path)):
            before = load_lock(path)
        with (path.parent / 'Dockerfile').open('a') as stream:
            stream.write('\n# new recipe\n')
        with patch('lab.executor.docker', return_value=self.image_probe(path)):
            after = load_lock(path)
        self.assertNotEqual(before['build_sha256'], after['build_sha256'])

    def test_container_has_only_explicit_mounts_and_no_host_socket(self):
        lock = {'image': 'sha256:' + 'a' * 64, 'uid': 123, 'gid': 456,
                'runner_root': '/runner', 'environment': {'PATH': '/usr/bin', 'HOME': '/home/agent'}}
        argv = container_argv(lock, 'owned', [('/source', '/checkout', False), ('/out', '/out', True)],
                              ['python3', '-m', 'lab'], '/private')
        self.assertIn('type=bind,src=/source,dst=/checkout,readonly', argv)
        self.assertIn('type=bind,src=/out,dst=/out', argv)
        self.assertIn('123:456', argv)
        self.assertNotIn('--privileged', argv)
        self.assertFalse(any('docker.sock' in arg for arg in argv))
        self.assertIn('AGENT_LAB_EXECUTOR_PRIVATE=/private', argv)
        with self.assertRaisesRegex(ValueError, 'commas'):
            container_argv(lock, 'owned', [('/x,y', '/x', True)], ['true'])

    def test_all_role_profiles_mask_bridge_and_auth_without_overlapping_masks(self):
        private = self.root / 'private'
        with patch.dict(os.environ, {PRIVATE_ENV: str(private)}):
            sandbox = CommandSandbox(self.root / 'checkout', '/usr/bin/codex',
                blocked_paths=[private / 'auth'], read_only_blocked_paths=[private / 'auth'])
        for writable, protected_git in ((True, False), (True, True), (False, False)):
            fs = sandbox.filesystem(writable, protected_git)
            self.assertEqual(fs[str(private)], 'none')
            self.assertNotIn(str(private / 'auth'), fs)

    def test_import_contains_only_pinned_history_and_no_untracked_host_assets(self):
        repo = repo_at(self.root / 'source')
        base = git(repo, 'rev-parse', 'HEAD').decode().strip()
        (repo / 'later.txt').write_text('future implementation')
        git(repo, 'add', 'later.txt')
        git(repo, 'commit', '-qm', 'later solution')
        future = git(repo, 'rev-parse', 'HEAD').decode().strip()
        (repo / 'installed-extension.so').write_bytes(b'host artifact')
        destination = self.root / 'imported'
        pinned_input({'repo': str(repo)}, base, destination)
        self.assertEqual(git(destination, 'rev-parse', 'HEAD').decode().strip(), base)
        self.assertFalse((destination / 'later.txt').exists())
        self.assertFalse((destination / 'installed-extension.so').exists())
        self.assertEqual(git(destination, 'remote'), b'')
        probe = subprocess.run(['git', '-C', str(destination), 'cat-file', '-e', future], capture_output=True)
        self.assertNotEqual(probe.returncode, 0)

    def test_state_updates_preserve_live_quality_references(self):
        state = {'quality': {'measurements': {'one': {'status': 'pending'}}}, 'removed': 1}
        quality = state['quality']
        measurement = quality['measurements']['one']
        merge_state(state, {'quality': {'measurements': {'one': {'status': 'completed'}}}})
        self.assertIs(state['quality'], quality)
        self.assertIs(quality['measurements']['one'], measurement)
        self.assertEqual(measurement['status'], 'completed')
        self.assertNotIn('removed', state)

    def test_temporary_auth_paths_do_not_change_comparison_identity(self):
        values = []
        for suffix in ('first', 'second'):
            private = '/tmp/private-' + suffix
            with patch.dict(os.environ, {PRIVATE_ENV: private}):
                values.append(normalize_runtime({'path': private + '/auth', 'version': 'same'}))
        self.assertEqual(values[0], values[1])
        self.assertEqual(values[0]['path'], '<EXECUTOR_PRIVATE>/auth')

    def test_rebuilt_image_metadata_does_not_change_the_condition_identity(self):
        bench = benchmark_at(self.root)
        receipt = self.root / 'execution.json'
        results = []
        for suffix in ('first', 'second'):
            receipt.write_text(json.dumps({'mode': 'rebuilt-executor-v1',
                'environment_identity': 'same-public-recipe', 'image': suffix}))
            with patch.dict(os.environ, {RECEIPT_ENV: str(receipt)}):
                results.append(run(bench, dict.fromkeys(FACTORS, False), self.root / suffix,
                    30, 10000, 30, backend=NativeAuthor, max_review_loops=0))
        self.assertEqual(results[0]['comparison_key'], results[1]['comparison_key'])
        self.assertNotEqual(results[0]['execution_environment']['image'],
                            results[1]['execution_environment']['image'])

    def test_quality_checker_proxy_runs_only_the_pinned_image_with_read_only_source(self):
        profile = {'uid': os.getuid(), 'gid': os.getgid(), 'image': 'sha256:' + 'a' * 64,
                   'quality': '/opt/quality/bin/scb-check'}
        checker = quality_proxy(profile, self.root, self.root / 'run')
        script = Path(checker['executable']).read_text()
        self.assertIn(profile['image'], script)
        self.assertIn('readonly', script)
        self.assertNotIn('docker.sock', script)

    def test_executor_admission_cannot_reuse_nonempty_output(self):
        bench = benchmark_at(self.root)
        output = self.root / 'run'
        output.mkdir()
        (output / 'old-result').touch()
        with patch.dict(os.environ, {PRIVATE_ENV: str(self.root / 'private')}), \
                self.assertRaisesRegex(ValueError, 'empty output'):
            run(bench, settings({}), output, 30, 100, 5, backend=NativeAuthor, _admitted_output=True)

    def test_whole_workflow_is_dispatched_before_starting_a_host_provider(self):
        from lab.provider import Codex, Pi
        bench = benchmark_at(self.root)
        for provider, harness in ((Codex, 'codex'), (Pi, 'pi')):
            for mediated in (True, False):
                with self.subTest(harness=harness, mediated=mediated), \
                        patch('lab.executor.run_pinned', return_value={'status': 'passed'}) as launch:
                    factors = settings({}) if mediated else dict.fromkeys(FACTORS, False)
                    value = run(bench, factors, self.root / 'run', 30, 100, 5,
                                backend=provider, harness=harness, executor='fixed.json')
                    self.assertEqual(value['status'], 'passed')
                    self.assertEqual(launch.call_args.args[4]['harness'], harness)
                    self.assertEqual(launch.call_args.args[1], factors)
        self.assertFalse((self.root / 'run').exists())

    def test_direct_pi_api_preserves_provider_without_a_harness_argument(self):
        from lab.provider import Pi
        bench = benchmark_at(self.root)
        with patch('lab.executor.run_pinned', return_value={'status': 'passed'}) as launch:
            run(bench, dict.fromkeys(FACTORS, False), self.root / 'run', 30, 100, 5,
                backend=Pi, executor='fixed.json')
        options = launch.call_args.args[4]
        self.assertEqual(options['harness'], 'pi')
        self.assertEqual(options['executable'], 'pi')

    def test_failed_setup_records_unknown_usage_without_overwriting_previous_runs(self):
        bench = benchmark_at(self.root)
        output = self.root / 'new-run'
        def failed_setup(*args, **kwargs):
            output.mkdir()
            raise RuntimeError('environment startup failed')
        with patch('lab.executor._run_pinned', side_effect=failed_setup), self.assertRaises(RuntimeError):
            run_pinned(bench, settings({}), output, 'fixed.json', {})
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['failure']['origin'], 'environment')
        self.assertIsNone(result['usage']['observed_raw_tokens'])
        previous = (output / 'result.json').read_bytes()
        with patch('lab.executor._run_pinned', side_effect=FileExistsError('existing run')), \
                self.assertRaises(FileExistsError):
            run_pinned(bench, settings({}), output, 'fixed.json', {})
        self.assertEqual((output / 'result.json').read_bytes(), previous)

    def test_host_grader_lifecycle_runs_after_provider_shutdown_and_keeps_source(self):
        from lab.evaluation import make_evaluator
        bench = benchmark_at(self.root)
        bench['fixture_executor_grader'] = {}
        output = self.root / 'run'
        output.mkdir()
        private = self.root / 'private'
        private.mkdir()

        class FixtureEvaluator(BaseEvaluator):
            config_key = 'fixture_executor_grader'

            def start(self, base, manifest, deadline):
                manifest['host_grader_started'] = True
                self.result['host_grader'] = {'pid': os.getpid()}
                execute_child(['/bin/sh', '-c', 'true'], output, None,
                              output / 'preflight.stdout', output / 'preflight.stderr', 5, dict(os.environ))

            def evaluate(self):
                if not (output / 'provider-closed').is_file():
                    raise AssertionError('grading before shutdown')
                report = output / 'grading.json'
                report.write_text(json.dumps({'hidden': 'grader-only'}))
                return {'status': 'completed', 'passed': True, 'report_path': str(report)}

        module = ModuleType('executor_fixture_grader')
        module.Evaluator = FixtureEvaluator
        with patch.dict(sys.modules, {module.__name__: module}), \
                patch.dict(ADAPTERS, {'fixture_executor_grader': module.__name__}):
            bridge = GradingBridge(private, bench, output)
            try:
                with patch.dict(os.environ, {PRIVATE_ENV: str(private)}):
                    result = run(bench, dict.fromkeys(FACTORS, False), output, 30, 10000, 30,
                                 backend=NativeAuthor, max_review_loops=0, _admitted_output=True)
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(result['evaluation']['passed'])
                self.assertNotEqual(result['host_grader']['pid'], os.getpid())
                self.assertTrue((output / 'checkout/one.py').is_file())
                manifest = json.loads((output / 'manifest.json').read_text())
                self.assertTrue(manifest['host_grader_started'])
                self.assertEqual(manifest['execution_environment']['mode'], 'host-v1')
                self.assertTrue(all('grader-only' not in c[2] for c in NativeAuthor.instances[-1].calls))
            finally:
                bridge.close()

    def test_bridge_rejects_host_shell_requests_and_wrong_workflow(self):
        private = self.root / 'private'
        private.mkdir()
        bridge = GradingBridge(private, {}, self.root / 'out')
        try:
            with self.assertRaisesRegex(ValueError, 'unknown evaluator'):
                bridge.dispatch({'benchmark': {}, 'output': str(self.root / 'out'), 'method': 'shell'})
            with self.assertRaisesRegex(ValueError, 'admitted'):
                bridge.dispatch({'benchmark': {}, 'output': '/elsewhere', 'method': 'start'})
        finally:
            bridge.close()


if __name__ == '__main__':
    unittest.main()
