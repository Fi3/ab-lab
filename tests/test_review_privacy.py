"""Exercise private input/history paths through real sandboxes, without models."""
import contextlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.batch import run_batch, worker
from lab.config import load_benchmark, settings
from lab.environment import clean_env
from lab.host import git
from lab.provider import ChildAccounting, Codex
from lab.review import blind_review_paths
from lab.sandbox import CommandSandbox
from lab.workflow import run
from test_batch import worker_at
from test_core import repo_at
from test_workflow import FakeCodex

ROOT = Path(__file__).resolve().parents[1]


class ReviewPrivacyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = repo_at(self.root / "input")
        definitions = self.root / "custom-definitions"
        definitions.mkdir()
        self.path = definitions / "custom.json"
        self.data = {"name": "private-input", "repo": str(source), "revision": "HEAD",
                     "features": [{"id": "one", "request": "PRIVATE_ISSUE: create one"}],
                     "checks": ["test -f one.py"]}
        self.path.write_text(json.dumps(self.data))
        self.benchmark = load_benchmark(self.path)

    def test_source_location_does_not_change_serialized_benchmark_or_legacy_manifest(self):
        self.assertEqual(self.benchmark.source_path, self.path.resolve())
        self.assertEqual(json.loads(json.dumps(self.benchmark)), self.data)
        output = self.root / "legacy"
        result = run(self.benchmark, settings({}), output, 30, 10000, 30,
                     backend=FakeCodex, review_issue_description=True)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(json.loads((output / "manifest.json").read_text())["benchmark"], self.data)
        self.assertNotIn("blind_review_policy", result)

    def test_batch_retains_input_location_only_for_blind_workers(self):
        for informed in (False, True):
            with self.subTest(informed=informed):
                output = self.root / f"batch-{informed}"
                result = run_batch(self.benchmark, settings({}), output, 1, 1,
                    seconds=30, max_raw=10000, max_turns=30,
                    review_issue_description=informed, _worker_command=worker_at(self.root))
                self.assertEqual(result["status"], "passed", result)
                config_path = output / "batch-input.json"
                config = json.loads(config_path.read_text())
                self.assertEqual(config["benchmark"], self.data)
                self.assertEqual(config["options"].get("_review_private_paths"), None if informed else [str(self.path)])
                with patch("lab.batch.run", return_value={"status": "passed"}) as launch, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(worker(config_path, output / "forwarded"), 0)
                self.assertEqual(launch.call_args.kwargs.get("_review_private_paths"), None if informed else [str(self.path)])

    def test_pinned_run_retains_input_location_only_for_blind_execution(self):
        for informed in (False, True):
            with self.subTest(informed=informed), patch("lab.executor.run_pinned", return_value={"status": "passed"}) as launch:
                run(self.benchmark, settings({}), self.root / "pinned", 30, 10000, 30,
                    backend=Codex, executor="unused-lock", review_issue_description=informed)
                options = launch.call_args.args[4]
                self.assertEqual(options.get("_review_private_paths"), None if informed else [str(self.path)])

    def test_non_git_input_directories_with_git_named_files_remain_supported(self):
        (self.path.parent / ".git").mkdir()
        paths = blind_review_paths(ROOT, self.benchmark, self.root / "run", [self.path])
        self.assertIn(self.path, paths)

    @unittest.skipUnless(shutil.which("codex"), "installed Codex sandbox required; no model calls")
    def test_workflow_hides_runner_history_custom_inputs_and_sibling_evidence(self):
        experiments = self.root / "custom-experiments"
        sibling = experiments / "previous-run"
        sibling.mkdir(parents=True)
        evidence = sibling / "author-evidence.txt"
        evidence.write_text("PRIVATE_AUTHOR_REASON")
        (sibling / "manifest.json").write_text("{}")
        protected = [str(self.path), str(evidence), str(ROOT / "benchmarks/example.json")]
        for informed in (False, True):
            script = "\n".join([
                "from pathlib import Path",
                "import subprocess",
                f"expected = {informed!r}",
                f"for filename in {protected!r}:",
                "    try: Path(filename).read_bytes()",
                "    except OSError: assert not expected, filename",
                "    else: assert expected, filename",
                f"history = subprocess.run(['git', '-C', {str(ROOT)!r}, 'show', 'HEAD:benchmarks/example.json'], capture_output=True)",
                "assert (history.returncode == 0) == expected, history.stdout + history.stderr",
            ])
            test = self

            class Inspects(FakeCodex):
                review_command_argv = ChildAccounting.review_command_argv

                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.sandbox = CommandSandbox(self.repo, shutil.which("codex"))
                    self.command_env = clean_env()

                def turn(self, thread, prompt, label, **options):
                    if "-review-" in label:
                        receipt = subprocess.run(self.sandbox.command(False, [sys.executable, "-c", script]),
                            cwd=self.repo, env=self.command_env, capture_output=True, text=True, timeout=20)
                        test.assertEqual(receipt.returncode, 0, receipt.stderr)
                        response = self.tool_call(thread, "review_run", {
                            "command": shlex.quote(sys.executable) + " -c " + shlex.quote(script)}, label + "-privacy")
                        test.assertTrue(response["success"], response)
                    return super().turn(thread, prompt, label, **options)

            with self.subTest(informed=informed):
                result = run(self.benchmark, settings({}), experiments / str(informed), 30, 10000, 30,
                             backend=Inspects, review_issue_description=informed)
                self.assertEqual(result["status"], "passed", result)

    @unittest.skipUnless(shutil.which("codex"), "installed Codex sandbox required; no model calls")
    def test_worktree_cannot_bypass_mask_using_its_shared_object_store(self):
        store = repo_at(self.root / "runner-store")
        (store / "benchmarks").mkdir()
        (store / "benchmarks/example.json").write_text("PRIVATE_ISSUE")
        git(store, "add", "benchmarks/example.json")
        git(store, "commit", "-qm", "benchmark definition")
        runner = self.root / "runner-worktree"
        git(store, "worktree", "add", "--quiet", "--detach", str(runner))
        neutral = repo_at(self.root / "neutral")
        output = self.root / "experiments/current"
        output.mkdir(parents=True)
        paths = blind_review_paths(runner, self.benchmark, output, [self.path])
        sandbox = CommandSandbox(neutral, shutil.which("codex"), blocked_paths=paths)
        argv = ["git", "--git-dir=" + str(store / ".git"), "show", "HEAD:benchmarks/example.json"]
        result = subprocess.run(sandbox.command(False, argv), cwd=neutral, env=clean_env(), capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b"PRIVATE_ISSUE", result.stdout)

    @unittest.skipUnless(shutil.which("codex"), "installed Codex sandbox required; no model calls")
    def test_shared_output_parent_blocks_sibling_runs_and_keeps_scratch_usable(self):
        sibling = self.root / "previous-run"
        sibling.mkdir()
        (sibling / "manifest.json").write_text("{}")
        evidence = sibling / "evidence.txt"
        evidence.write_text("PRIVATE_EVIDENCE")
        neutral = repo_at(self.root / "neutral")
        output = self.root / "current"
        output.mkdir()
        scratch = self.root / "scratch"
        scratch.mkdir()
        with patch("lab.review.tempfile.gettempdir", return_value=str(self.root)):
            paths = blind_review_paths(ROOT, self.benchmark, output, [self.path])
        sandbox = CommandSandbox(neutral, shutil.which("codex"), blocked_paths=paths)
        script = (f"from pathlib import Path\n"
                  f"try: Path({str(evidence)!r}).read_text()\n"
                  "except OSError: pass\n"
                  "else: raise AssertionError('sibling evidence readable')\n"
                  f"Path({str(scratch / 'built')!r}).write_text('built')\n")
        result = subprocess.run(sandbox.command(False, [sys.executable, "-c", script]),
                                cwd=neutral, env=clean_env(), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
