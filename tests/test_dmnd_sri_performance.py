"""Performance evidence must come from a complete independent test."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks import dmnd_sri_performance as performance


class PerformanceTests(unittest.TestCase):
    def output(self, evidence=None, inline=True):
        evidence = performance.expected_evidence() if evidence is None else evidence
        marker = performance.MARKER + json.dumps(evidence)
        test = "test lab_sri_performance ... "
        lines = ["running 1 test", test + marker, "ok"] if inline else [
            "running 1 test", marker, test + "ok"]
        lines.append("test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s")
        return "\n".join(lines) + "\n"

    def test_complete_evidence_passes_with_inline_or_separate_output(self):
        for inline in (False, True):
            with self.subTest(inline=inline):
                report = performance.validate_performance(self.output(inline=inline), "")
                self.assertTrue(report["passed"], report)

    def test_allocation_increase_or_changed_wire_output_fails(self):
        original = performance.expected_evidence()
        for key in original:
            with self.subTest(key=key):
                evidence = copy.deepcopy(original)
                evidence[key] = evidence[key] + 1 if type(evidence[key]) is int else "different"
                report = performance.validate_performance(self.output(evidence), "")
                self.assertFalse(report["passed"])
                self.assertTrue(any(key in error for error in report["errors"]))

    def test_missing_extra_or_wrong_type_evidence_fails(self):
        cases = [[], {}, {**performance.expected_evidence(), "extra": 1},
                 {**performance.expected_evidence(), "size_allocations": False}]
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertFalse(performance.validate_performance(self.output(evidence), "")["passed"])

    def test_success_summary_cannot_hide_errors_or_duplicate_evidence(self):
        output = self.output()
        cases = [(output, "error: failed to run the operation"),
                 (output + "thread panicked at source.rs\n", ""),
                 (output + performance.MARKER + json.dumps(performance.expected_evidence()) + "\n", ""),
                 (output.replace("1 passed", "0 passed"), ""),
                 (output.replace("running 1 test", "running 0 tests"), ""),
                 (output.replace("lab_sri_performance ...", "different_test ..."), "")]
        for stdout, stderr in cases:
            with self.subTest(stdout=stdout, stderr=stderr):
                self.assertFalse(performance.validate_performance(stdout, stderr)["passed"])

    def test_installed_harness_is_exact_and_cannot_replace_candidate_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = Path(temporary)
            record = performance.install_harness(context)
            target = context / "tests/lab_sri_performance.rs"
            self.assertEqual(target.read_bytes(), performance.HARNESS.read_bytes())
            self.assertEqual(record["target"], "lab_sri_performance")
            with self.assertRaisesRegex(ValueError, "already contains"):
                performance.install_harness(context)


if __name__ == "__main__":
    unittest.main()
