"""Stopped attempts retain real source changes without manufacturing approval."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab.__main__ import main
from lab.batch import collect, run_batch, worker
from lab.config import settings
from lab.host import git
from lab.loops import FeatureProgress, WorkLimitReached, loop_policy, work_limit_error
from lab.summary import records, render
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex
from test_batch import worker_at


def edit(value, previous=None):
    body = (f"*** Add File: one.py\n+value = {value}\n" if previous is None else
            f"*** Update File: one.py\n@@\n-value = {previous}\n+value = {value}\n")
    return {"name": "host_edit", "arguments": {"patch": "*** Begin Patch\n" + body + "*** End Patch\n"}}


def finding(text):
    return "FINDINGS\n- [P2] " + text


class Scripted(FakeCodex):
    script = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_script = {key: list(value) for key, value in self.script.items()}
        self.raw = 0

    def turn(self, thread, prompt, label, **kwargs):
        self.calls.append((label, thread, prompt, kwargs))
        if label.startswith("integration-"):
            return "Keep all reviewed commits."
        while self.pending_script[label]:
            action = self.pending_script[label].pop(0)
            reply, charge = action if isinstance(action, tuple) else (action, 10)
            self.raw += charge
            reply = reply(self.repo) if callable(reply) else reply
            if isinstance(reply, dict):
                error = work_limit_error(self.work_limits, self.raw)
                if error:
                    raise error
                self.tool_call(thread, reply["name"], reply["arguments"], f"{label}-{len(self.pending_script[label])}")
            else:
                return reply
        return "Finished."

    def report(self):
        return {"observed_raw_tokens": self.raw, "measurement_complete": True, "turns": []}


class LoopWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.benchmark = {"name": "loops", "repo": str(repo_at(self.root / "source")), "revision": "HEAD",
                          "features": [{"id": "one", "request": "Implement one.py."}],
                          "checks": ["test -f one.py"]}

    def execute(self, script, *, name="run", policy=None, factors=None):
        class Backend(Scripted):
            pass
        Backend.script = script
        result = run(self.benchmark, settings(factors or {}), self.root / name, 60, 10000000, 100,
                     backend=Backend, skip_linearization=True, loop_options=policy)
        return result, Backend.instances[-1]

    def assert_attention(self, result, reason):
        self.assertEqual(result["status"], "needs_attention", result)
        self.assertEqual(result["attention"]["reason"], reason)
        self.assertEqual(result["checkpoints"], [])
        self.assertTrue(result["usage"]["measurement_complete"])
        flag = result["attention"]
        handoff = Path(flag["artifact"])
        self.assertEqual(json.loads(handoff.read_text()), flag)
        self.assertTrue((handoff.parent / "changes.patch").is_file())
        self.assertTrue((handoff.parent / "request.txt").is_file())
        self.assertEqual(records(result), [result])
        self.assertIn(reason, render([result]))
        self.assertIn(str(handoff), render([result]))


    def test_repeated_review_finding_after_two_real_repairs_stops(self):
        script = {"one-implement": [edit(1), "Finished."]}
        for round_number in range(1, 4):
            script[f"one-review-{round_number}"] = [finding("Wrong behavior; reproduce with input 0.")]
            if round_number < 3:
                script[f"one-fix-{round_number}"] = [edit(round_number + 1, round_number), "Finished."]
        result, backend = self.execute(script)
        self.assert_attention(result, "repeated_blocking_findings")
        self.assertEqual(result["attention"]["rounds"], [1, 2, 3])
        self.assertEqual(result["attention"]["repair_attempts"], 2)
        self.assertEqual(backend.calls[-1][0], "one-review-3")
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")

    def test_source_cycle_is_detected_despite_different_commits_and_different_findings(self):
        result, backend = self.execute({
            "one-implement": [edit(1), "Finished."], "one-review-1": [finding("First defect")],
            "one-fix-1": [edit(2, 1), "Finished."], "one-review-2": [finding("Another defect")],
            "one-fix-2": [edit(1, 2), "Finished."], "one-review-3": [finding("Different wording")],
        })
        self.assert_attention(result, "repeated_rejected_tree")
        self.assertEqual(result["attention"]["rounds"], [1, 3])
        self.assertNotEqual(result["reviews"][0]["head"], result["reviews"][2]["head"])
        self.assertEqual(backend.calls[-1][0], "one-review-3")

    def test_new_findings_and_changing_trees_still_obey_repair_cap(self):
        script = {"one-implement": [edit(1), "Finished."]}
        for round_number in range(1, 5):
            script[f"one-review-{round_number}"] = [finding(f"Distinct defect {round_number}")]
            if round_number < 4:
                script[f"one-fix-{round_number}"] = [edit(round_number + 1, round_number), "Finished."]
        result, backend = self.execute(script)
        self.assert_attention(result, "repair_limit_reached")
        self.assertEqual(result["attention"]["repair_attempts"], 3)
        self.assertEqual(backend.calls[-1][0], "one-review-4")

    def test_successful_last_allowed_repair_is_approved(self):
        result, _ = self.execute({"one-implement": [edit(1), "Finished."],
                                  "one-review-1": [finding("Wrong value")],
                                  "one-fix-1": [edit(2, 1), "Finished."], "one-review-2": ["NO_FINDINGS"]},
                                 policy={"max_repair_attempts": 1})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"], [])

    def test_checkpoint_token_budget_stops_before_host_executes_over_budget_proposal(self):
        result, backend = self.execute({"one-implement": [(edit(1), 300), (edit(2, 1), 600)],
                                        "one-review-1": [("NO_FINDINGS", 50)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"][0]["reason"], "feature_token_limit")
        self.assertEqual(result["loop_flags"][0]["feature_raw_tokens"], 900)
        self.assertEqual((backend.repo / "one.py").read_text(), "value = 1\n")
        self.assertEqual(result["usage"]["observed_raw_tokens"], 950)

    def test_overshoot_can_use_up_final_review_reserve_without_authorizing_more_generation(self):
        result, backend = self.execute({"one-implement": [(edit(1), 1100)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result["attention"]["final_review"]["status"], "stopped")


    def test_feature_budget_has_precedence_over_review_threshold(self):
        result, backend = self.execute({"one-implement": [edit(1), "Finished."],
                                       "one-review-1": [("NO_FINDINGS", 1000)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertNotIn("review_wrapups", result)
        self.assertEqual(backend.calls[-1][0], "one-review-1")

    def test_review_can_finish_using_feature_reserve_without_another_review(self):
        result, _ = self.execute({"one-implement": [(edit(1), 700), "Finished."],
                                 "one-review-1": [("NO_FINDINGS", 190)]},
                                policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["usage"]["observed_raw_tokens"], 900)

    def test_rejection_consuming_author_allowance_stops_without_fake_repair_or_duplicate_review(self):
        result, backend = self.execute({"one-implement": [(edit(1), 700), "Finished."],
                                       "one-review-1": [(finding("Defect"), 100)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertEqual(result["attention"]["repair_attempts"], 0)
        self.assertFalse(result["attention"]["review_approved"])
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")
        self.assertEqual(backend.calls[-1][0], "one-review-1")

    def test_stopped_repair_of_unchanged_rejected_tree_does_not_buy_another_review(self):
        result, backend = self.execute({"one-implement": [edit(1), "Finished."],
                                       "one-review-1": [finding("Defect")],
                                       "one-fix-1": [({"name": "host_read", "arguments": {"path": "one.py"}}, 850)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertFalse(result["attention"]["review_approved"])
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")
        self.assertEqual(backend.calls[-1][0], "one-fix-1")

    def test_stopped_repair_that_changed_rejected_tree_still_gets_final_review(self):
        result, _ = self.execute({"one-implement": [edit(1), "Finished."],
                                 "one-review-1": [finding("Defect")],
                                 "one-fix-1": [(edit(2, 1), 200), ({"name": "host_read", "arguments": {"path": "one.py"}}, 650)],
                                 "one-review-2": ["NO_FINDINGS"]},
                                policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["loop_flags"][0]["review_approved"])


    def test_final_review_has_its_own_limit_and_is_not_retried(self):
        result, backend = self.execute({"one-implement": [edit(1)] + [{"name": "host_edit", "arguments": {"patch": "invalid"}}] * 3,
                                        "one-review-1": [("NO_FINDINGS", 210)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "repeated_operations")
        self.assertEqual(result["attention"]["final_review"]["reason"], "review_token_limit")
        self.assertEqual(len([c for c in backend.calls if "-review-" in c[0]]), 1)

    def test_dirty_native_work_is_preserved_and_never_treated_as_reviewed_commit(self):
        def unfinished(repo):
            (repo / "one.py").write_text("value = 1\n")
            return "Finished."
        result, backend = self.execute({"one-implement": [(unfinished, 900)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200},
                                       factors={"C17": False, "C08": False})
        self.assert_attention(result, "feature_token_limit")
        self.assertIn("one.py", result["attention"]["working_tree_status"])
        self.assertEqual(result["attention"]["final_review"]["status"], "skipped")
        self.assertTrue((backend.repo / "one.py").is_file())
        self.assertEqual(len(backend.calls), 1)

    def test_final_review_can_be_disabled(self):
        result, backend = self.execute({"one-implement": [(edit(1), 1001)]},
                                       policy={"final_review": False, "max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertFalse(any("-review-" in c[0] for c in backend.calls))

    def test_same_operation_after_real_source_changes_is_not_a_loop(self):
        result, _ = self.execute({"one-implement": [edit(1), {"name": "host_read", "arguments": {"path": "one.py"}}, edit(2, 1),
                                                    {"name": "host_read", "arguments": {"path": "one.py"}}, edit(3, 2),
                                                    {"name": "host_read", "arguments": {"path": "one.py"}}, "Finished."],
                                  "one-review-1": ["NO_FINDINGS"]})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"], [])


    def test_malformed_final_review_retains_flag_without_manufacturing_approval(self):
        result, backend = self.execute({"one-implement": [edit(1)] + [{"name": "host_read", "arguments": {"path": "one.py"}}] * 3,
                                        "one-review-1": ["Probably fine"]})
        self.assertEqual(result["status"], "needs_attention", result)
        self.assertEqual(result["checkpoints"], [])
        flag = json.loads(Path(result["loop_flags"][0]["artifact"]).read_text())
        self.assertEqual(flag["review"]["status"], "incomplete")
        self.assertIsNone(flag["review_approved"])
        self.assertFalse(any(c[0].startswith("integration") for c in backend.calls))

    def test_disabled_policy_changes_comparison_key(self):
        script = {"one-implement": [edit(1)] + [{"name": "host_read", "arguments": {"path": "one.py"}}] * 4 + ["Finished."],
                  "one-review-1": ["NO_FINDINGS"]}
        disabled, backend = self.execute(script, policy={"enabled": False}, name="disabled")
        enabled, _ = self.execute(script, name="enabled")
        self.assertEqual(disabled["status"], "passed", disabled)
        self.assertEqual(disabled["loop_flags"], [])
        self.assertEqual(len([c for c in backend.calls if c[0] == "one-implement"]), 1)
        self.assertNotEqual(disabled["comparison_key"], enabled["comparison_key"])


class LoopConfigurationTests(unittest.TestCase):

    def test_rejected_scalar_arguments_do_not_crash_failure_tracking(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = repo_at(Path(directory) / "repo")
            progress = FeatureProgress({"id": "one"}, loop_policy(), 0)
            for arguments in (None, "invalid", [1, 2]):
                self.assertIsNone(progress.observe_operation(
                    {"name": "host_run", "arguments": arguments},
                    {"success": False, "text": "arguments must be an object"}, repo))

    def test_invalid_policy_is_rejected(self):
        for value in ([], {"wat": 1}, {"enabled": 1}, {"max_feature_raw": True}, {"repeat_limit": 1},
                      {"max_review_raw": 3000000}, {"max_repair_attempts": -1}, {"max_review_seconds": 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                loop_policy(value)

    def test_review_time_and_token_limits_are_inclusive(self):
        progress = FeatureProgress({"id": "one"}, loop_policy(), 100)
        limits = progress.limits(200, reviewing=True)
        self.assertIsNone(work_limit_error(limits, 200, limits[-1]["start"]))
        error = work_limit_error(limits, 200, limits[-1]["start"] + 300)
        self.assertIsInstance(error, WorkLimitReached)
        self.assertIsInstance(error, WorkLimitReached)
        self.assertEqual(error.signal["reason"], "review_time_limit")
        error = work_limit_error(limits, 500200, limits[-1]["start"])
        self.assertEqual(error.signal["reason"], "review_token_limit")
        self.assertEqual(error.signal["kind"], "budget_exhausted")

    def test_cli_plan_records_overrides_and_stop_status_has_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark = {"name": "b", "repo": str(repo_at(root / "repo")), "revision": "HEAD",
                         "features": [{"id": "one", "request": "Create one"}], "checks": ["true"]}
            path = root / "b.json"
            path.write_text(json.dumps(benchmark))
            policy = root / "policy.json"
            policy.write_text(json.dumps({"max_repair_attempts": 2, "final_review": False}))
            output = io.StringIO()
            with patch.object(sys, "argv", ["lab", "plan", str(path), "--loop-policy", str(policy)]), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue())["loop_policy"]["max_repair_attempts"], 2)
            with patch.object(sys, "argv", ["lab", "run", str(path), "--out", str(root / "run"),
                              "--seconds", "30", "--max-raw", "10000", "--max-turns", "10", "--harness", "codex"]):
                with patch("lab.__main__.run", return_value={"status": "needs_attention"}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 1)

    def test_batch_forwards_policy_and_preserves_attention_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark = {"name": "b", "repo": str(repo_at(root / "repo")), "revision": "HEAD",
                         "features": [{"id": "one", "request": "Create one"}], "checks": ["true"]}
            result = run_batch(benchmark, settings({}), root / "batch", 2, 1, seconds=30, max_raw=10000,
                               max_turns=10, loop_options={"max_repair_attempts": 2}, _worker_command=worker_at(root))
            self.assertEqual(result["loop_policy"]["max_repair_attempts"], 2)
            config_path = root / "batch/batch-input.json"
            config = json.loads(config_path.read_text())
            with patch("lab.batch.run", return_value={"status": "needs_attention"}) as launch, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(worker(config_path, root / "worker"), 1)
            self.assertEqual(launch.call_args.kwargs["loop_options"]["max_repair_attempts"], 2)
            out = root / "attention"
            out.mkdir()
            (out / "result.json").write_text(json.dumps({"status": "needs_attention", "loop_flags": [{"reason": "repeated_operations"}],
                                                       "usage": {"measurement_complete": True, "observed_raw_tokens": 123}}))
            collected = collect(config, out, 1, 2)
            self.assertEqual(collected["status"], "needs_attention")
            self.assertEqual(collected["usage"]["observed_raw_tokens"], 123)

    def test_independent_batch_repetitions_continue_after_attention_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark = {"name": "b", "repo": str(repo_at(root / "repo")), "revision": "HEAD",
                         "features": [{"id": "one", "request": "Create one"}], "checks": ["true"]}
            command = worker_at(root)
            path = Path(command[-1])
            path.write_text(path.read_text().replace("'status': 'failed' if failed else 'passed'",
                                                    "'status': 'needs_attention' if index == 1 else 'passed'").replace(
                                                    "sys.exit(1 if failed else 0)", "sys.exit(1 if result['status'] != 'passed' else 0)"))
            result = run_batch(benchmark, settings({}), root / "batch", 3, 1,
                               seconds=30, max_raw=10000, max_turns=10, _worker_command=command)
            self.assertEqual([r["status"] for r in result["results"]], ["needs_attention", "passed", "passed"])
            self.assertEqual(result["results"][0]["usage"]["observed_raw_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
