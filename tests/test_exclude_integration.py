from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.exclude_integration import (FIELD, audit_paths, comparison_view, exclusion,
                                     fingerprint, run_records, _verify_snapshot)
from lab.summary import render


def result():
    return {"schema": "agent-behavior-lab/v1", "output": "/missing/run", "status": "failed",
            "execution_status": "incomplete", "error": "integration timed out", "feature_count": 1,
            "check_count": 1, "checks": [{"exit_code": 0}], "duration_seconds": 123,
            "stages": [{"stage": "one-implement", "thread_id": "author"},
                       {"stage": "integration-plan", "thread_id": "integrator"},
                       {"stage": "integration-accept", "thread_id": "integrator"}],
            "usage": {"measurement_complete": True, "observed_raw_tokens": 150,
                "cached_input_tokens": 85, "thread_totals": {"author": [100, 10, 80],
                                                             "integrator": [30, 10, 5]},
                "nested": {"observed_raw_tokens": 0, "cached_input_tokens": 0,
                           "measurement_complete": True}}}


class ExclusionTests(unittest.TestCase):
    def test_usage_is_subtracted_once_and_original_record_is_not_changed(self):
        row = result()
        original = deepcopy(row)
        row[FIELD] = exclusion(row)
        self.assertEqual(row[FIELD]["usage"]["observed_raw_tokens"], 110)
        self.assertEqual(row[FIELD]["usage"]["cached_input_tokens"], 80)
        self.assertEqual(row[FIELD]["excluded_usage"]["observed_raw_tokens"], 40)
        self.assertEqual(row[FIELD]["status"], "partial")
        self.assertEqual({key: value for key, value in row.items() if key != FIELD}, original)
        view = comparison_view(row)
        self.assertEqual(view["status"], "unavailable")
        self.assertIsNone(view["checks"])
        self.assertIsNone(view["duration_seconds"])
        self.assertEqual(row["usage"]["observed_raw_tokens"], 150)
        text = render([row])
        for expected in ("Actually consumed raw tokens", "Integration excluded", "150", "110", "40"):
            self.assertIn(expected, text)

    def test_no_integration_does_not_change_outcomes_or_usage(self):
        row = result()
        row["stages"] = row["stages"][:1]
        row[FIELD] = exclusion(row)
        self.assertEqual(row[FIELD]["status"], "not_applicable")
        self.assertIs(comparison_view(row), row)
        self.assertEqual(row["status"], "failed")

    def test_missing_stage_history_does_not_mean_zero_integration(self):
        row = result()
        row.pop("stages")
        row[FIELD] = exclusion(row)
        self.assertEqual(row[FIELD]["status"], "unavailable")
        self.assertIsNone(comparison_view(row)["usage"]["observed_raw_tokens"])

    def test_feature_named_integration_is_not_removed(self):
        row = result()
        row["stages"] = [{"stage": "integration-implement", "thread_id": "author"},
                         {"stage": "integration-review-1", "thread_id": "reviewer"}]
        row[FIELD] = exclusion(row)
        self.assertEqual(row[FIELD]["status"], "not_applicable")
        self.assertIs(comparison_view(row), row)

    def test_feature_named_integration_and_final_compaction_are_distinguished(self):
        row = result()
        row["stages"][0]["stage"] = "integration-implement"
        row["usage"]["turns"] = [{"label": "integration-accept-compact",
                                    "thread_id": "integrator"}]
        correction = exclusion(row)
        self.assertEqual(correction["usage"]["observed_raw_tokens"], 110)
        self.assertEqual(correction["integration_threads"], ["integrator"])

    def test_shared_thread_cannot_be_subtracted_whole(self):
        row = result()
        row["stages"][0]["thread_id"] = "integrator"
        correction = exclusion(row)
        self.assertEqual(correction["status"], "unavailable")
        self.assertIsNone(correction["usage"])
        self.assertIn("another stage", correction["reason"])

    def test_unknown_child_ownership_is_not_assumed_to_be_author_usage(self):
        row = result()
        row["usage"].update(observed_raw_tokens=170, cached_input_tokens=95)
        row["usage"]["nested"].update(observed_raw_tokens=20, cached_input_tokens=10,
            thread_totals={"child": [15, 5, 10]}, threads={"child": {}})
        correction = exclusion(row)
        self.assertIsNone(correction["usage"])
        self.assertIn("ownership", correction["usage_reason"])
        row["usage"]["nested"]["threads"]["child"]["parent_thread_id"] = "integrator"
        correction = exclusion(row)
        self.assertEqual(correction["excluded_usage"]["observed_raw_tokens"], 60)
        self.assertEqual(correction["usage"]["observed_raw_tokens"], 110)

    def test_bad_or_incomplete_accounting_does_not_produce_corrected_totals(self):
        for change in ({"observed_raw_tokens": 151}, {"cached_input_tokens": 84},
                       {"measurement_complete": False}, {"thread_totals": {}}):
            with self.subTest(change=change):
                row = result()
                row["usage"].update(change)
                self.assertIsNone(exclusion(row)["usage"])

    def test_provenance_rejects_modified_original_data(self):
        row = result()
        row[FIELD] = exclusion(row)
        original_hash = fingerprint(row)
        self.assertEqual(row[FIELD]["original_record_sha256"], original_hash)
        row["usage"]["observed_raw_tokens"] += 1
        with self.assertRaisesRegex(ValueError, "provenance"):
            comparison_view(row)

    def test_cli_report_preserves_correction_provenance(self):
        from lab.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            row = result()
            row[FIELD] = exclusion(row)
            path.write_text(json.dumps(row))
            output = io.StringIO()
            with patch.object(sys, "argv", ["lab", "report", str(path)]), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            exported = json.loads(output.getvalue())
            self.assertEqual(exported, [row])
            self.assertIn("110", render(exported))

    def test_comparison_does_not_silently_reuse_the_integrated_success(self):
        from lab.workflow import compare, interaction
        row = result()
        row.update(status="passed", comparison_key="same", factors={"C13": True})
        row[FIELD] = exclusion(row)
        for operation, rows in ((compare, (row, row)), (interaction, (row,) * 4)):
            with self.subTest(operation=operation.__name__), \
                    self.assertRaisesRegex(ValueError, "successful complete workflows"):
                operation(*rows)

    def test_arrays_and_batches_are_audited_and_application_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            value = {"schema": "agent-behavior-lab/batch-v1", "results": [result(), [result()]]}
            value["results"][1][0]["output"] = "/another/run"
            path.write_text(json.dumps(value))
            before = path.read_bytes()
            report = audit_paths([path, path], apply=False)
            self.assertEqual(report["unique_runs"], 2)
            self.assertEqual(len(report["records"]), 2)
            self.assertEqual(path.read_bytes(), before)
            report = audit_paths([path], apply=True)
            self.assertTrue(report["files"][0]["changed"])
            saved = path.read_bytes()
            second = audit_paths([path], apply=True)
            self.assertFalse(second["files"][0]["changed"])
            self.assertEqual(path.read_bytes(), saved)
            for original, annotated in zip(run_records(value), run_records(json.loads(saved))):
                self.assertEqual(original, {key: item for key, item in annotated.items() if key != FIELD})
            self.assertEqual(list(run_records({"usage": {}, "status": "passed"})), [])


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.checkout = self.folder / "checkout"
        self.checkout.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.checkout / "program.py").write_text("print('hello')\n")
        self.git("add", "program.py")
        self.git("commit", "-qm", "Checkpoint")
        self.commit = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.snapshot = self.folder / "snapshot"
        self.snapshot.mkdir()
        shutil.copy2(self.checkout / "program.py", self.snapshot / "program.py")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.checkout), *args],
                                       stderr=subprocess.PIPE).decode().strip()

    def row(self):
        row = result()
        row["output"] = str(self.folder)
        row["checkpoints"] = [{"feature": "one", "head": self.commit, "status": "review_skipped"}]
        row["slopcodebench"] = {"problem": "test", "checkpoints": [{
            "feature": "one", "status": "failed", "strict_pass": False, "commit": self.commit,
            "tree": self.tree, "snapshot": str(self.snapshot), "include_prior_tests": True,
            "tests": {"passed": 2, "total": 3}}], "final": {"strict_pass": True}}
        row["scb_check"] = {"measurements": {"after_implementation": {
            "status": "completed", "commit": self.commit, "tree": self.tree,
            "report": {"verbosity": 0.1}}, "after_assembly": {"report": {"verbosity": 0.9}}}}
        return row

    def test_verified_checkpoint_replaces_integrated_outcome_without_claiming_checks_passed(self):
        row = self.row()
        row[FIELD] = exclusion(row)
        self.assertEqual(row[FIELD]["status"], "applied")
        view = comparison_view(row)
        self.assertEqual(view["execution_status"], "completed")
        self.assertEqual(view["status"], "failed")
        self.assertEqual(view["slopcodebench"]["final"]["tests"], {"passed": 2, "total": 3})
        self.assertNotIn("after_assembly", view["scb_check"]["measurements"])
        self.assertIsNone(view["checks"])
        self.assertEqual(row["slopcodebench"]["final"], {"strict_pass": True})

    def test_passing_checkpoint_does_not_invent_a_successful_final_runner_check(self):
        row = self.row()
        row["slopcodebench"]["checkpoints"][0].update(status="passed", strict_pass=True)
        outcome = exclusion(row)["outcome"]
        self.assertIs(outcome["all_tests_passed"], True)
        self.assertIsNone(outcome["solved"])
        self.assertEqual(outcome["status"], "unavailable")

    def test_unrelated_quality_tree_and_incomplete_evaluation_are_not_reused(self):
        row = self.row()
        row["scb_check"]["measurements"]["after_implementation"]["tree"] = "other"
        self.assertIsNone(exclusion(row)["outcome"])
        row = self.row()
        row["slopcodebench"]["checkpoints"][0]["include_prior_tests"] = False
        self.assertIsNone(exclusion(row)["outcome"])

    def test_snapshot_content_modes_and_untracked_files_are_verified(self):
        original = self.snapshot / "program.py"
        digest = _verify_snapshot(self.checkout, self.snapshot, self.commit, self.tree)
        self.assertEqual(len(digest), 64)
        original.write_text("changed\n")
        self.assertIsNone(exclusion(self.row())["outcome"])
        shutil.copy2(self.checkout / "program.py", original)
        original.chmod(0o755)
        self.assertIsNone(exclusion(self.row())["outcome"])
        original.chmod(0o644)
        (self.snapshot / "untracked.py").write_text("extra\n")
        self.assertIsNone(exclusion(self.row())["outcome"])


if __name__ == "__main__":
    unittest.main()
