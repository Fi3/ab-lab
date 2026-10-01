"""Priority selection preserves independent review and gates only selected findings."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.batch import failure, run_batch, worker
from lab.config import settings
from lab.review import DEFAULT_PRIORITIES, normalize_priorities, validate_review
from lab.workflow import run
from test_batch import worker_at
from test_core import repo_at
from test_workflow import FakeCodex, verdict


class PriorityReviewer(FakeCodex):
    initial_review = verdict()

    def turn(self, thread, prompt, label, **kwargs):
        if "-review-" in label:
            self.calls.append((label, thread, prompt, kwargs))
            return self.submit_review(thread, prompt, label, self.initial_review if label == "one-review-1" else verdict())
        if label.startswith("integration-"):
            self.calls.append((label, thread, prompt, kwargs))
            return "Reviewed commits preserved; final checks remain with the host."
        return super().turn(thread, prompt, label, **kwargs)


class ReviewPriorityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.benchmark = {
            "name": "priorities", "repo": str(repo_at(self.root / "input")), "revision": "HEAD",
            "features": [{"id": "one", "request": "Create one.py with the requested value."}],
            "checks": ["test -f one.py"],
        }

    def execute(self, reply, name="run", **options):
        class Reviewer(PriorityReviewer):
            initial_review = reply

        result = run(self.benchmark, settings({}), self.root / name, 30, 10000, 30,
                     backend=Reviewer,  **options)
        return result, Reviewer.instances[-1]

    def test_each_default_blocking_priority_requires_a_repair_and_independent_rereview(self):
        self.assertEqual(DEFAULT_PRIORITIES, ("P0", "P1", "P2"))
        for priority in DEFAULT_PRIORITIES:
            with self.subTest(priority=priority):
                result, backend = self.execute(
                    verdict("one.py must return the requested value 2.", priority), name=priority)
                self.assertEqual(result["status"], "passed", result)
                labels = list(dict.fromkeys(call[0] for call in backend.calls))
                self.assertEqual(labels, ["one-implement", "one-review-1", "one-fix-1",
                                          "one-review-2"])
                threads = {label: thread for label, thread, _, _ in backend.calls}
                self.assertNotEqual(threads["one-review-1"], threads["one-implement"])
                self.assertEqual(threads["one-review-1"], threads["one-review-2"])
                self.assertEqual((self.root / priority / "checkout/one.py").read_text(), "value = 2\n")
                self.assertEqual(result["checkpoints"][0]["review_rounds"], 2)
                self.assertEqual(result["checks"][0]["exit_code"], 0)

    def test_advisory_only_review_allows_completion_without_repair(self):
        result, backend = self.execute(verdict("ADVISORY_ONLY: prefer a shorter local name.", "P3"))
        self.assertEqual(result["status"], "passed", result)
        self.assertFalse(any("-fix-" in label for label, *_ in backend.calls))
        self.assertEqual(result["checkpoints"][0]["review_rounds"], 1)
        self.assertEqual((self.root / "run/checkout/one.py").read_text(), "value = 1\n")
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        review = result["reviews"][0]
        self.assertTrue(review["approved"])
        self.assertEqual(review["blocking_findings"], [])
        self.assertEqual(review["advisory_findings"], [{"priority": "P3",
                         "text": "ADVISORY_ONLY: prefer a shorter local name."}])
        self.assertEqual(review["head"], result["checkpoints"][0]["reviewed_head"])
        self.assertEqual(json.loads((self.root / "run/result.json").read_text())["reviews"], result["reviews"])

    def test_custom_priorities_exclude_p2_but_can_include_p3(self):
        cases = [(("P0", "P1"), "P2", False), (("P0", "P1", "P2", "P3"), "P3", True)]
        for index, (priorities, finding, repaired) in enumerate(cases):
            with self.subTest(priorities=priorities):
                result, backend = self.execute(verdict("Change the value to 2.", finding),
                                               name=f"selection-{index}", review_priorities=priorities)
                self.assertEqual(result["status"], "passed", result)
                self.assertEqual(any("-fix-" in label for label, *_ in backend.calls), repaired)

    def test_mixed_review_sends_only_blocking_findings_and_their_continuations_to_author(self):
        reply = {"status": "complete", "incomplete_reason": None, "findings": [
            {"priority": "P1", "text": "REQUIRED_FIX: one.py returns the wrong value.\nReproduce by reading value; it must be 2, not 1."},
            {"priority": "P3", "text": "ADVISORY_ONLY: rename the value variable.\nADVISORY_DETAIL: this is only a style preference."}]}
        result, backend = self.execute(reply)
        self.assertEqual(result["status"], "passed", result)
        repair_prompt = next(prompt for label, _, prompt, _ in backend.calls if label == "one-fix-1")
        self.assertIn("REQUIRED_FIX", repair_prompt)
        self.assertIn("Reproduce by reading value", repair_prompt)
        self.assertNotIn("ADVISORY_ONLY", repair_prompt)
        self.assertNotIn("ADVISORY_DETAIL", repair_prompt)
        self.assertEqual(result["reviews"][0]["blocking_findings"][0]["priority"], "P1")
        self.assertIn("ADVISORY_DETAIL", result["reviews"][0]["advisory_findings"][0]["text"])

    def test_unlabelled_or_malformed_findings_never_approve_or_trigger_repairs(self):
        malformed = [
            {**verdict(), "status": "approved"},
            verdict("Unknown priority", "P4"),
            {**verdict(), "findings": [{"text": "Unlabelled regression"}]},
            {**verdict(), "findings": [{"priority": "P1", "text": ""}]},
            {**verdict(), "findings": "not an array"},
            {**verdict(), "incomplete_reason": "contradicts complete"},
        ]
        for index, reply in enumerate(malformed):
            with self.subTest(reply=reply):
                result, backend = self.execute(reply, name=f"malformed-{index}")
                self.assertEqual(result["status"], "needs_attention", result)
                self.assertEqual(result["checkpoints"], [])
                self.assertFalse(any("-fix-" in label for label, *_ in backend.calls))
                self.assertFalse(any(label.startswith("integration-") for label, *_ in backend.calls))

    def test_settings_are_recorded_and_canonicalized_in_comparison_keys(self):
        default, _ = self.execute(verdict(), name="default")
        selected, _ = self.execute(verdict(), name="selected", review_priorities=("P0", "P1"))
        reordered, _ = self.execute(verdict(), name="reordered", review_priorities=("P1", "P0", "P1"))
        for name, result, priorities in (("default", default, ["P0", "P1", "P2"]),
                                          ("selected", selected, ["P0", "P1"]),
                                          ("reordered", reordered, ["P0", "P1"])):
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(result["review_priorities"], priorities)
            manifest = json.loads((self.root / name / "manifest.json").read_text())
            self.assertEqual(manifest["review_priorities"], priorities)
        self.assertNotEqual(default["comparison_key"], selected["comparison_key"])
        self.assertEqual(selected["comparison_key"], reordered["comparison_key"])

    def test_invalid_priority_selection_is_rejected_before_run_creation(self):
        for index, selection in enumerate(((), "", "P1,P4", ("P1", 2))):
            with self.subTest(selection=selection):
                destination = self.root / f"invalid-{index}"
                with self.assertRaises(ValueError):
                    run(self.benchmark, settings({}), destination, 30, 10000, 30,
                        backend=PriorityReviewer, review_priorities=selection)
                self.assertFalse(destination.exists())


class ReviewPriorityConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.benchmark = {
            "name": "priorities", "repo": str(repo_at(self.root / "input")), "revision": "HEAD",
            "features": [{"id": "one", "request": "create one"}],
            "checks": ["true"],
        }
        self.path = self.root / "benchmark.json"
        self.path.write_text(json.dumps(self.benchmark))

    def test_normalization_has_one_canonical_order_and_rejects_invalid_inputs(self):
        for supplied in ("P2,P0,P1", " P2, P0, P1 ", ("P2", "P0", "P1", "P2")):
            self.assertEqual(normalize_priorities(supplied), DEFAULT_PRIORITIES)
        for supplied in ("", "P1,,P2", "P9", "P1 P2", (), ("P1", None), None):
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                normalize_priorities(supplied)

    def test_complete_empty_findings_approves(self):
        decision = validate_review({"review_id": "target", **verdict()}, "target")
        self.assertEqual(decision, {"approved": True, "blocking_findings": [], "advisory_findings": []})

    def test_plan_exposes_default_and_explicit_priorities_without_generation(self):
        for options, expected in (([], ["P0", "P1", "P2"]),
                                   (["--review-priorities", "P1,P0"], ["P0", "P1"])):
            output = io.StringIO()
            with patch.object(sys, "argv", ["lab", "plan", str(self.path), *options]):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["review_priorities"], expected)
            self.assertEqual(value["generation"], "none")

    def test_single_and_parallel_cli_forward_priorities_for_both_harnesses(self):
        for harness in ("codex", "pi"):
            for parallel in (1, 2):
                with self.subTest(harness=harness, parallel=parallel):
                    args = ["lab", "run", str(self.path), "--out", str(self.root / "run"),
                            "--harness", harness, "--parallel", str(parallel),
                            "--seconds", "30", "--max-raw", "10000", "--max-turns", "30",
                            "--review-priorities", "P1,P0"]
                    target = "run" if parallel == 1 else "run_batch"
                    with patch("lab.__main__." + target, return_value={"status": "passed"}) as launch:
                        with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(main(), 0)
                    self.assertEqual(tuple(launch.call_args.kwargs["review_priorities"]), ("P0", "P1"))

    def test_bad_cli_priority_fails_before_launch(self):
        args = ["lab", "run", str(self.path), "--out", str(self.root / "invalid"),
                "--harness", "codex", "--seconds", "30", "--max-raw", "10000",
                "--max-turns", "30", "--review-priorities", "P9"]
        with patch("lab.__main__.run") as launch:
            with patch.object(sys, "argv", args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main()
        self.assertEqual(raised.exception.code, 2)
        launch.assert_not_called()
        self.assertFalse((self.root / "invalid").exists())

    def test_batch_retains_and_forwards_priorities_to_each_worker(self):
        result = run_batch(self.benchmark, settings({}), self.root / "batch", 2, 2,
                           seconds=30, max_raw=10000, max_turns=30, review_priorities=("P0", "P1"),
                           _worker_command=worker_at(self.root))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["review_priorities"], ["P0", "P1"])
        config_path = self.root / "batch/batch-input.json"
        config = json.loads(config_path.read_text())
        self.assertEqual(config["options"]["review_priorities"], ["P0", "P1"])
        failed = failure(config, self.root / "failed-worker", "worker stopped")
        self.assertEqual(failed["review_priorities"], ["P0", "P1"])
        with patch("lab.batch.run", return_value={"status": "passed"}) as launch:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(worker(config_path, self.root / "worker"), 0)
        self.assertEqual(launch.call_args.kwargs["review_priorities"], ["P0", "P1"])


    def test_invalid_batch_priority_fails_before_creating_output(self):
        with self.assertRaises(ValueError):
            run_batch(self.benchmark, settings({}), self.root / "invalid-batch", 2, 2,
                      seconds=30, max_raw=10000, max_turns=30, review_priorities=("P4",))
        self.assertFalse((self.root / "invalid-batch").exists())


if __name__ == "__main__":
    unittest.main()
