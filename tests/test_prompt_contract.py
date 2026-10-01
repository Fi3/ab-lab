"""Only supplied requirements and selected conditions reach the author."""
import json
from pathlib import Path
import tempfile
import unittest

from lab.config import FACTORS, author_policy, load_benchmark, settings
from lab.workflow import author_prompt, review_prompt


class PromptContractTests(unittest.TestCase):
    def test_removed_benchmark_fields_are_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.json"
            benchmark = {"name": "plain", "repo": directory, "revision": "HEAD",
                         "features": [{"id": "one", "request": "Original request."}],
                         "checks": ["true"]}
            for field, value in (("instructions", ""), ("defer_documentation", False)):
                with self.subTest(field=field):
                    path.write_text(json.dumps({**benchmark, field: value}))
                    with self.assertRaisesRegex(ValueError, "unknown benchmark fields"):
                        load_benchmark(path)

    def test_all_off_is_exact_request_even_when_old_metadata_is_present(self):
        feature = {"id": "one", "request": "  Original specification.\n"}
        benchmark = {"instructions": "EXTRA_COACHING", "defer_documentation": True}
        factors = settings(dict.fromkeys(FACTORS, False))
        self.assertEqual(author_prompt(benchmark, feature, factors), feature["request"])
        self.assertEqual(author_policy(factors), "")

    def test_selected_conditions_and_repair_evidence_are_explicit(self):
        feature = {"id": "one", "request": "Original specification."}
        factors = settings({**dict.fromkeys(FACTORS, False), "C17": True, "C20": True})
        prompt = author_prompt({}, feature, factors, "A demonstrated defect.")
        self.assertIn("Use the host tools", prompt)
        self.assertIn("actual operation results", prompt)
        self.assertIn("A demonstrated defect.", prompt)
        for unwanted in ("@standalone", "focused tests", "Work Leaf", "requirements.txt",
                         "remaining", "budget", "Markdown", "Declare", "virtual environment"):
            self.assertNotIn(unwanted, prompt)

    def test_removed_factor_is_rejected_before_generation(self):
        self.assertNotIn("C25", FACTORS)
        with self.assertRaises(ValueError):
            settings({"C25": True})

    def test_review_does_not_repeat_local_setup_coaching(self):
        feature = {"id": "one", "request": "Original specification."}
        benchmark = {"features": [feature], "checks": ["true"], "instructions": "EXTRA_COACHING"}
        prompts = [review_prompt(benchmark, feature, "base", "")]
        for prompt in prompts:
            self.assertNotIn("EXTRA_COACHING", prompt)
            self.assertNotIn("within run budget", prompt)
