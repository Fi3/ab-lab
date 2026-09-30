"""Regressions for the retained real intermediate-message accounting failure."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from lab.config import settings
from lab.host import Fatal
from lab.workflow import run
import test_provider as stream
from test_core import repo_at
from test_workflow import FakeCodex


class BoundaryTests(unittest.TestCase):
    provider = stream.StreamTests.provider

    def test_natural_completion_collects_usage_delayed_beyond_one_second(self):
        p = self.provider([stream.message("Finished."), stream.completed(), stream.price()])
        original = p.incoming
        available = time.monotonic()+1.25
        def incoming(timeout, private_id=None):
            if p.remaining and p.remaining[0].get("method") == "thread/tokenUsage/updated" and time.monotonic() < available:
                time.sleep(min(timeout, 0.01))
                return None
            return original(timeout, private_id)
        p.incoming = incoming
        p.turn("t", "request", "author")
        self.assertTrue(p.report()["measurement_complete"])
        self.assertEqual(p.usage.raw, 110)

    def test_missing_coverage_is_published_before_another_turn(self):
        p = self.provider([stream.price(), stream.message("Finished."), stream.completed()])
        with self.assertRaisesRegex(Fatal, "incomplete native token measurement"):
            p.turn("t", "request", "author")
        journal = [json.loads(line) for line in (p.artifacts / "coverage.jsonl").read_text().splitlines()]
        self.assertEqual(len(journal), 1)
        self.assertFalse(journal[0]["usage_observed_after_last_message"])
        self.assertEqual(journal[0]["turn_id"], "u")


class WorkflowCoverageTests(unittest.TestCase):
    def test_unmeasured_author_preserves_executed_tool_and_does_not_start_review(self):
        class Missing(FakeCodex):
            def report(self):
                return {**super().report(), "measurement_complete": False,
                        "unpriced_or_incomplete_turns": [{"reason": "missing response usage"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = repo_at(root / "input")
            bench = {"name": "b", "repo": str(source), "revision": "HEAD",
                     "features": [{"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
                     "checks": ["true"]}
            result = run(bench, settings({}), root / "run", 30, 10000, 30, backend=Missing)
            self.assertEqual(result["status"], "failed")
            self.assertIn("incomplete token measurement", result["error"])
            self.assertEqual(len(Missing.instances[-1].calls), 1)
            self.assertTrue((root / "run/checkout/one.py").exists())
            self.assertFalse((root / "run/checkout/two.py").exists())
            self.assertTrue((root / "run/result.json").exists())


class MonitorCoverageTests(unittest.TestCase):
    def test_live_missing_turn_is_visible_without_a_terminal_result(self):
        from lab.monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "provider").mkdir()
            (root / "provider/coverage.jsonl").write_text(json.dumps({"turn_id": "u", "usage_observed_after_last_message": False})+"\n")
            state = {}
            first = sample([root], state)["runs"][0]
            second = sample([root], state)["runs"][0]
            self.assertEqual(first["coverage_gaps"], 1)
            self.assertFalse(first["measurement_complete"])
            self.assertEqual(second["coverage_gaps"], 1)

    def test_old_failed_record_remains_visible_without_a_coverage_journal(self):
        from lab.monitor import sample
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.json").write_text(json.dumps({"status": "failed", "usage": {
                "observed_raw_tokens": 123, "measurement_complete": False,
                "unpriced_or_incomplete_turns": [{"turn_id": "u"}, {"turn_id": "v"}]}}))
            row = sample([root], {})["runs"][0]
            self.assertEqual(row["coverage_gaps"], 2)
            self.assertEqual(row["observed_raw"], 123)


if __name__ == "__main__":
    unittest.main()
