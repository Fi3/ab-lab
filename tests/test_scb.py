"""External quality measurements are observations, not agent instructions."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.config import settings
from lab.host import git, snapshot
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


PHASES = ("before_changes", "after_implementation", "after_assembly")
SCORES = {"verbosity": 0.25, "erosion": 0.1, "cog_erosion": 0.2,
          "files_scanned": 1, "total_loc": 4, "clone_loc": 1}


def checker_at(root, body=None):
    """An actual child process exercises argv, JSON, exit and timeout handling."""
    path = root / "checker with spaces"
    path.write_text(f"#!{sys.executable}\n"
                    "import json, pathlib, subprocess, sys, time\n"
                    "if sys.argv[1:] == ['--version']:\n"
                    "    print('0.2.0-test'); sys.exit(0)\n"
                    "assert sys.argv[1:] == ['check', '.', '--output-format', 'json']\n"
                    + (body or f"print(json.dumps({SCORES!r})); sys.exit(1)\n"))
    path.chmod(0o755)
    return str(path)


def benchmark_at(root):
    return {"name": "quality", "repo": str(repo_at(root / "input")), "revision": "HEAD",
            "features": [{"id": "one", "request": "create one"},
                         {"id": "two", "request": "create two"}],
            "checks": ["test -f one.py && test -f two.py"],}


class ScbWorkflowTests(unittest.TestCase):
    def test_three_measurements_use_correct_source_and_do_not_change_prompts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b = benchmark_at(root)
            original = snapshot(Path(b["repo"]))
            plain = run(b, settings({}), root / "plain", 30, 10000, 30, backend=FakeCodex)
            calls = list(FakeCodex.instances[-1].calls)
            tool = checker_at(root,
                f"result = {SCORES!r}\n"
                "result['observed_files'] = {p.name: p.read_text() for p in pathlib.Path('.').glob('*.py')}\n"
                "result['commits'] = subprocess.check_output(['git', 'rev-list', '--count', 'HEAD'], text=True).strip()\n"
                "print(json.dumps(result)); sys.exit(1)\n")
            result = run(b, settings({}), root / "scored", 30, 10000, 30,
                         backend=FakeCodex, scb_check=tool)
            self.assertEqual(result["status"], "passed", result)
            quality = result["scb_check"]
            self.assertEqual(quality["status"], "completed")
            self.assertEqual(list(quality["measurements"]), list(PHASES))
            before, implemented, final = (quality["measurements"][p] for p in PHASES)
            self.assertNotIn("one.py", before["report"]["observed_files"])
            self.assertEqual(implemented["report"]["observed_files"]["one.py"], "value = 2\n")
            self.assertEqual(implemented["report"]["commits"], "4")
            self.assertEqual(final["report"]["commits"], "3")
            self.assertEqual(implemented["tree"], final["tree"])
            for measurement in (before, implemented, final):
                self.assertEqual(measurement["status"], "completed")
                self.assertTrue(measurement["findings_present"])
                self.assertEqual(measurement["exit_code"], 1)
                folder = root / "scored" / "scb-check" / measurement["phase"]
                self.assertEqual(json.loads((folder / "stdout.json").read_text()), measurement["report"])
                self.assertEqual(json.loads((folder / "result.json").read_text()), measurement)
            # Git commit IDs may differ with the clock, but actual instructions
            # must match after replacing their run-specific commit hashes.
            def normalized(items):
                import re
                return [(label, re.sub(r"\b[0-9a-f]{40}\b", "<COMMIT>", prompt), options)
                        for label, _, prompt, options in items]
            self.assertEqual(normalized(calls), normalized(FakeCodex.instances[-1].calls))
            self.assertEqual(result["usage"], plain["usage"])
            self.assertNotEqual(result["comparison_key"], plain["comparison_key"])
            self.assertEqual(original, snapshot(Path(b["repo"])))
            self.assertEqual(quality, json.loads((root / "scored/result.json").read_text())["scb_check"])

    def test_missing_checker_fails_before_provider_or_generation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b = benchmark_at(root)
            with patch("lab.workflow.Codex") as provider:
                result = run(b, settings({}), root / "run", 30, 10000, 30,
                             backend=provider, scb_check=str(root / "missing"))
            provider.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertIn("scb-check", result["error"])
            self.assertTrue((root / "run/result.json").exists())

    def test_checker_errors_never_become_scores_or_launch_agents(self):
        cases = {
            "usage": "print('invalid configuration', file=sys.stderr); sys.exit(2)\n",
            "malformed": "print('not json')\n",
            "missing_metrics": "print('{}')\n",
            "nan": f"r = {SCORES!r}; r['verbosity'] = float('nan'); print(json.dumps(r))\n",
            "boolean": f"r = {SCORES!r}; r['erosion'] = True; print(json.dumps(r))\n",
            "mutation": f"pathlib.Path('source.py').write_text('changed'); print(json.dumps({SCORES!r}))\n",
        }
        for name, body in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                b = benchmark_at(root)
                with patch("lab.workflow.Codex") as provider:
                    result = run(b, settings({}), root / "run", 30, 10000, 30,
                                 backend=provider, scb_check=checker_at(root, body))
                provider.assert_not_called()
                self.assertEqual(result["status"], "failed", result)
                measured = result["scb_check"]["measurements"]
                self.assertEqual(measured["before_changes"]["status"], "error")
                self.assertEqual(measured["after_implementation"]["status"], "not_run")
                self.assertEqual(measured["after_assembly"]["status"], "not_run")
                self.assertTrue((root / "run/scb-check/before_changes/stderr.txt").exists())

    def test_timeout_is_bounded_and_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tool = checker_at(root, "time.sleep(30)\n")
            start = time.monotonic()
            result = run(benchmark_at(root), settings({}), root / "run", 30, 10000, 30,
                         backend=FakeCodex, scb_check=tool, scb_seconds=0.2)
            self.assertLess(time.monotonic()-start, 5)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["scb_check"]["measurements"]["before_changes"]["timed_out"])

    def test_intermediate_measurement_error_retains_first_score_and_stops_before_assembly(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tool = checker_at(root,
                "if pathlib.Path('one.py').exists():\n"
                "    print('broken scan', file=sys.stderr); sys.exit(2)\n"
                f"print(json.dumps({SCORES!r}))\n")
            result = run(benchmark_at(root), settings({}), root / "run", 30, 10000, 30,
                         backend=FakeCodex, scb_check=tool)
            self.assertEqual(result["status"], "failed")
            measured = result["scb_check"]["measurements"]
            self.assertEqual(measured["before_changes"]["status"], "completed")
            self.assertEqual(measured["after_implementation"]["status"], "error")
            self.assertEqual(measured["after_assembly"]["status"], "not_run")
            self.assertEqual(len(result["checkpoints"]), 2)
            self.assertNotIn("integration-plan", [c[0] for c in FakeCodex.instances[-1].calls])

    def test_finished_source_is_scored_even_when_final_tests_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            b = benchmark_at(root)
            b["checks"] = ["false"]
            result = run(b, settings({}), root / "run", 30, 10000, 30,
                         backend=FakeCodex, scb_check=checker_at(root))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["scb_check"]["status"], "completed")
            self.assertIn("final check 1 failed", result["error"])

    def test_report_includes_quality_and_distinguishes_old_unmeasured_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            quality = {"status": "completed", "measurements": {p: SCORES for p in PHASES}}
            report = {"status": "passed", "factors": {}, "usage": {}, "scb_check": quality}
            files = [root / "new.json", root / "old.json"]
            files[0].write_text(json.dumps(report))
            del report["scb_check"]
            files[1].write_text(json.dumps(report))
            output = io.StringIO()
            with patch.object(sys, "argv", ["lab", "report", *map(str, files)]), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            new, old = json.loads(output.getvalue())
            self.assertEqual(new["scb_check"], quality)
            self.assertIsNone(old["scb_check"])

    def test_cli_requires_scoring_by_default_and_supports_an_explicit_executable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = root / "bench.json"
            path.write_text(json.dumps(benchmark_at(root)))
            for options, executable in (([], "scb-check"), (["--scb-check", "/some/tool"], "/some/tool")):
                with self.subTest(options=options), patch("lab.__main__.run", return_value={"status": "passed"}) as runner:
                    argv = ["lab", "run", str(path), "--out", str(root / "run"),
                            "--seconds", "30", "--max-raw", "1000", "--max-turns", "10",
                            "--harness", "codex", *options]
                    with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main(), 0)
                    self.assertEqual(runner.call_args.kwargs["scb_check"], executable)


    def test_real_checker_matches_saved_json_without_affecting_the_workflow(self):
        import shutil
        tool = shutil.which("scb-check") or Path(__file__).resolve().parents[1] / ".venv/bin/scb-check"
        if not Path(tool).is_file():
            self.skipTest("install scb-check for external checker integration")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = run(benchmark_at(root), settings({}), root / "run", 30, 10000, 30,
                         backend=FakeCodex, scb_check=str(tool))
            self.assertEqual(result["status"], "passed", result)
            quality = result["scb_check"]
            self.assertEqual(quality["status"], "completed")
            for phase in PHASES:
                observed = quality["measurements"][phase]
                self.assertGreater(observed["report"]["files_scanned"], 0)
                raw = json.loads((root / "run/scb-check" / phase / "stdout.json").read_text())
                self.assertEqual(raw, observed["report"])


if __name__ == "__main__":
    unittest.main()
