"""Execution failures and missing token coverage are independent conditions."""
import json
from pathlib import Path
import tempfile
import unittest

from lab.monitor import sample


class MonitorCoverageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "provider").mkdir()
        self.state = {}

    def append_coverage(self, **row):
        with (self.root / "provider/coverage.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def observed(self):
        return sample([self.root], self.state)["runs"][0]

    def append_usage(self, totals):
        row = {"event": {"method": "thread/tokenUsage/updated", "params": {
            "threadId": "owned", "tokenUsage": {"total": dict(zip(
                ("inputTokens", "outputTokens", "cachedInputTokens"), totals))}}}}
        with (self.root / "provider/transport.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def native_summary(self, totals, **changes):
        report = {"thread_id": "owned", "validated": True, "thread_totals": totals,
                  "errors": [], "missing_compactions": [], **changes}
        (self.root / "provider/native-usage.json").write_text(json.dumps({"owned": report}))

    def test_native_compaction_cost_is_included_without_double_counting(self):
        self.append_usage([100, 10, 50])
        self.native_summary([200, 20, 100])
        first = self.observed()
        self.assertEqual(first["observed_raw"], 220)
        self.assertEqual(first["counter_flags"], [])
        self.assertEqual(self.observed()["observed_raw"], 220)
        self.append_usage([110, 12, 55])
        self.native_summary([210, 22, 105])
        later = self.observed()
        self.assertEqual(later["observed_raw"], 232)
        self.assertEqual(later["counter_flags"], [])

    def test_native_errors_and_unpriced_compactions_remain_visible(self):
        self.append_usage([100, 10, 50])
        self.native_summary([200, 20, 100], errors=["foreign session"],
                            missing_compactions=["response-compact"])
        row = self.observed()
        self.assertEqual(row["observed_raw"], 110)
        self.assertEqual(row["native_errors"], ["owned: foreign session"])
        self.assertEqual(row["native_incomplete"], ["owned: response-compact"])
        self.assertFalse(row["measurement_complete"])
        self.native_summary([200, 20, 100])
        row = self.observed()
        self.assertEqual(row["native_errors"], [])
        self.assertEqual(row["native_incomplete"], [])
        self.assertEqual(row["observed_raw"], 220)

    def test_unvalidated_or_foreign_summary_is_not_charged(self):
        for changes in ({"validated": False}, {"thread_id": "foreign"}):
            with self.subTest(changes=changes):
                self.native_summary([200, 20, 100], **changes)
                row = self.observed()
                self.assertEqual(row["observed_raw"], 0)
                self.assertTrue(row["native_errors"])
                self.assertFalse(row["measurement_complete"])

    def test_priced_context_failure_remains_covered_before_and_after_recovery(self):
        self.append_coverage(turn_id="failed", status="failed",
                             error="contextWindowExceeded",
                             usage_observed_after_last_message=True)
        first = self.observed()
        self.assertEqual(first["coverage_gaps"], 0)
        self.assertEqual(first["completed_turns"], 1)
        self.assertIsNone(first["measurement_complete"])

        self.append_coverage(turn_id="retry", status="completed", error=None,
                             usage_observed_after_last_message=True)
        for _ in range(2):
            recovered = self.observed()
            self.assertEqual(recovered["coverage_gaps"], 0)
            self.assertEqual(recovered["completed_turns"], 2)

    def test_unpriced_and_legacy_failed_tails_remain_gaps_after_success(self):
        self.append_coverage(turn_id="unpriced", status="failed",
                             error="stream interrupted",
                             usage_observed_after_last_message=False)
        self.append_coverage(turn_id="legacy", status="failed",
                             error="transport unavailable")
        self.assertEqual(self.observed()["coverage_gaps"], 2)

        self.append_coverage(turn_id="later", status="completed", error=None,
                             usage_observed_after_last_message=True)
        for _ in range(2):
            later = self.observed()
            self.assertEqual(later["coverage_gaps"], 2)
            self.assertFalse(later["measurement_complete"])

    def test_terminal_priced_failure_keeps_execution_error_without_coverage_gap(self):
        self.append_coverage(turn_id="failed", status="failed",
                             error="context recovery exhausted",
                             usage_observed_after_last_message=True)
        (self.root / "result.json").write_text(json.dumps({
            "status": "failed", "error": "context recovery exhausted",
            "usage": {"measurement_complete": True,
                      "observed_raw_tokens": 123,
                      "unpriced_or_incomplete_turns": []}}))

        row = self.observed()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "context recovery exhausted")
        self.assertEqual(row["coverage_gaps"], 0)
        self.assertTrue(row["measurement_complete"])
        self.assertEqual(row["observed_raw"], 123)


if __name__ == "__main__":
    unittest.main()
