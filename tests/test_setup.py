"""The existing run command prepares local inputs before model execution."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.setup import command, ensure_benchmark, python_with
from test_core import repo_at


class SetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def invoke(self, action, path, *options):
        output, error = io.StringIO(), io.StringIO()
        argv = ["lab", action, str(path), *options]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(error):
            code = main()
        return code, output.getvalue(), error.getvalue()

    def test_same_run_command_prepares_a_fresh_checkout_but_plan_stays_read_only(self):
        from benchmarks import swe_milestone as sm
        path = self.root / "benchmark.json"
        data = json.loads((sm.ROOT / "benchmarks/swe-milestone-scikit-learn-light.json").read_text())
        repo = self.root / ".benchmarks/swe-milestone-projects/scikit-learn/repo"
        data["repo"] = str(repo)
        path.write_text(json.dumps(data))

        def prepare(argv, **options):
            self.assertEqual(argv[-2:], ["prepare", "scikit-learn"])
            repo.mkdir(parents=True, exist_ok=True)
            print("Preparing benchmark", file=sys.stderr)

        with patch("lab.setup.command", side_effect=prepare) as setup, \
                patch("lab.setup.python_with"), patch("lab.__main__.run", return_value={"status": "passed"}) as run:
            code, output, error = self.invoke("plan", path)
            self.assertEqual(code, 2)
            self.assertIn("prepare scikit-learn", error)
            setup.assert_not_called()
            run.assert_not_called()
            for _ in range(2):
                code, output, error = self.invoke("run", path, "--harness", "codex", "--out",
                    str(self.root / "run"), "--seconds", "30", "--max-raw", "1000", "--max-turns", "10",
                    "--scb-check", ".venv/bin/scb-check")
                self.assertEqual(code, 0, error)
                self.assertEqual(json.loads(output), {"status": "passed"})
                self.assertIn("Preparing benchmark", error)
                self.assertEqual(run.call_args.args[0]["repo"], str(repo))
                self.assertEqual(run.call_args.kwargs["scb_check"], "scb-check")

    def test_slopcodebench_installs_missing_uv_privately(self):
        path = self.root / "benchmark.json"
        root = self.root / ".benchmarks"
        path.write_text(json.dumps({"slopcodebench": {
            "dataset": str(root / "scb-problems"), "runner": str(root / "slop-code-bench")}}))
        python = root / "setup-venv/bin/python"
        with patch("lab.setup.shutil.which", return_value=None), \
                patch("lab.setup.python_with", return_value=python) as install, \
                patch("lab.setup.command") as setup:
            ensure_benchmark(path)
        install.assert_called_once_with(root / "setup-venv", ["uv==0.12.16"])
        self.assertEqual(setup.call_args.args[0][-3:], ["setup", "--root", root])
        self.assertTrue(setup.call_args.kwargs["env"]["PATH"].startswith(str(python.parent)))

    def test_private_environment_creation_and_dependency_repair_are_reused(self):
        folder = self.root / "venv"
        with patch("lab.setup.command") as install, \
                patch("lab.setup.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            python_with(folder, ["pathspec==0.12.1"])
        self.assertEqual(install.call_count, 2)
        python = folder / "bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        with patch("lab.setup.command") as install, \
                patch("lab.setup.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            python_with(folder, ["pathspec==0.12.1"])
        install.assert_not_called()

    def test_setup_failure_never_starts_a_model_or_emits_a_success_result(self):
        path = self.root / "benchmark.json"
        path.write_text('{"repo": "missing"}')
        with patch("lab.__main__.ensure_benchmark", side_effect=RuntimeError("download failed")), \
                patch("lab.__main__.run") as run:
            code, output, error = self.invoke("run", path, "--harness", "codex", "--out",
                str(self.root / "run"), "--seconds", "30", "--max-raw", "1000", "--max-turns", "10")
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertIn("download failed", error)
        run.assert_not_called()

    def test_tiny_example_gets_its_own_repository_and_reuses_the_same_commit(self):
        parent = repo_at(self.root / "checkout")
        repo = parent / "examples/tiny-project"
        repo.mkdir(parents=True)
        (repo / "demo.py").write_text("value = 1\n")
        path = parent / "example.json"
        path.write_text(json.dumps({"repo": str(repo)}))
        with patch("lab.setup.ROOT", parent):
            ensure_benchmark(path)
            first = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
            ensure_benchmark(path)
        self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--show-toplevel"]).decode().strip(), str(repo))
        self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]), first)
        self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "rev-list", "--count", "HEAD"]).strip(), b"1")

    def test_failed_setup_command_has_a_retryable_cli_error(self):
        with self.assertRaisesRegex(RuntimeError, "retry the same run command"):
            command([sys.executable, "-c", "raise SystemExit(2)"])

    def test_interrupted_slopcodebench_download_leaves_no_partial_checkout(self):
        from benchmarks.slopcodebench import setup
        root = self.root / ".benchmarks"
        with patch("benchmarks.slopcodebench.subprocess.run", side_effect=subprocess.CalledProcessError(1, "fetch")), \
                self.assertRaises(subprocess.CalledProcessError):
            setup(root)
        self.assertEqual(list(root.iterdir()), [])
