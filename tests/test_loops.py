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
from lab.loops import FeatureProgress, ReviewConclusionRequested, WorkLimitReached, loop_policy, work_limit_error
from lab.summary import records, render
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex
from test_batch import worker_at


def edit(value, previous=None):
    body = (f"*** Add File: one.py\n+value = {value}\n" if previous is None else
            f"*** Update File: one.py\n@@\n-value = {previous}\n+value = {value}\n")
    return "@standalone edit implement\n*** Begin Patch\n" + body + "*** End Patch\n@standalone end"


def finding(text):
    return "FINDINGS\n- [P2] " + text


def interrupted_review(repo):
    raise ReviewConclusionRequested({"reason": "review_token_threshold", "kind": "review_wrapup",
                                     "metric": "observed_raw_tokens", "limit": 200, "observed": 210})


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
        action = self.pending_script[label].pop(0)
        reply, charge = action if isinstance(action, tuple) else (action, 10)
        self.raw += charge
        return reply(self.repo) if callable(reply) else reply

    def report(self):
        return {"observed_raw_tokens": self.raw, "measurement_complete": True, "turns": []}


class LoopWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.benchmark = {"name": "loops", "repo": str(repo_at(self.root / "source")), "revision": "HEAD",
                          "features": [{"id": "one", "request": "Implement one.py."}],
                          "checks": ["test -f one.py"], "instructions": "", "defer_documentation": True}

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

    def test_author_repeating_reads_hands_off_once_and_can_pass_independent_review(self):
        result, backend = self.execute({"one-implement": [edit(1)] + ["@standalone read one.py"] * 3,
                                        "one-review-1": ["NO_FINDINGS"]})
        self.assertEqual(result["status"], "passed", result)
        flag = result["loop_flags"][0]
        self.assertEqual(flag["reason"], "repeated_operations")
        self.assertEqual(flag["resolution"], "review_approved")
        self.assertTrue(flag["review_approved"])
        self.assertEqual(len([c for c in backend.calls if "-review-" in c[0]]), 1)
        self.assertEqual(result["checkpoints"][0]["loop_flags"], [flag["artifact"]])
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        self.assertNotIn('"kind": "done"', (self.root / "run/one-host/events.jsonl").read_text())

    def test_cycle_of_two_operations_is_flagged_and_rejected_work_blocks_later_features(self):
        self.benchmark["features"].append({"id": "two", "request": "Build on one."})
        cycle = ["@standalone read one.py", "@standalone run -- printf ok"]
        result, backend = self.execute({"one-implement": [edit(1)] + cycle * 3,
                                        "one-review-1": [finding("one.py is still incorrect")]})
        self.assert_attention(result, "repeated_operations")
        self.assertEqual(result["attention"]["period"], 2)
        self.assertFalse(result["attention"]["review_approved"])
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertFalse(any("-fix-" in c[0] or c[0].startswith(("two", "integration")) for c in backend.calls))
        self.assertEqual((self.root / "run/checkout/one.py").read_text(), "value = 1\n")
        self.assertIn("one.py is still incorrect", (Path(result["attention"]["artifact"]).parent / "reviews.json").read_text())

    def test_repeated_review_finding_after_two_real_repairs_stops(self):
        script = {"one-implement": [edit(1), "@standalone done"]}
        for round_number in range(1, 4):
            script[f"one-review-{round_number}"] = [finding("Wrong behavior; reproduce with input 0.")]
            if round_number < 3:
                script[f"one-fix-{round_number}"] = [edit(round_number + 1, round_number), "@standalone done"]
        result, backend = self.execute(script)
        self.assert_attention(result, "repeated_blocking_findings")
        self.assertEqual(result["attention"]["rounds"], [1, 2, 3])
        self.assertEqual(result["attention"]["repair_attempts"], 2)
        self.assertEqual(backend.calls[-1][0], "one-review-3")
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")

    def test_source_cycle_is_detected_despite_different_commits_and_different_findings(self):
        result, backend = self.execute({
            "one-implement": [edit(1), "@standalone done"], "one-review-1": [finding("First defect")],
            "one-fix-1": [edit(2, 1), "@standalone done"], "one-review-2": [finding("Another defect")],
            "one-fix-2": [edit(1, 2), "@standalone done"], "one-review-3": [finding("Different wording")],
        })
        self.assert_attention(result, "repeated_rejected_tree")
        self.assertEqual(result["attention"]["rounds"], [1, 3])
        self.assertNotEqual(result["reviews"][0]["head"], result["reviews"][2]["head"])
        self.assertEqual(backend.calls[-1][0], "one-review-3")

    def test_new_findings_and_changing_trees_still_obey_repair_cap(self):
        script = {"one-implement": [edit(1), "@standalone done"]}
        for round_number in range(1, 5):
            script[f"one-review-{round_number}"] = [finding(f"Distinct defect {round_number}")]
            if round_number < 4:
                script[f"one-fix-{round_number}"] = [edit(round_number + 1, round_number), "@standalone done"]
        result, backend = self.execute(script)
        self.assert_attention(result, "repair_limit_reached")
        self.assertEqual(result["attention"]["repair_attempts"], 3)
        self.assertEqual(backend.calls[-1][0], "one-review-4")

    def test_successful_last_allowed_repair_is_approved(self):
        result, _ = self.execute({"one-implement": [edit(1), "@standalone done"],
                                  "one-review-1": [finding("Wrong value")],
                                  "one-fix-1": [edit(2, 1), "@standalone done"], "one-review-2": ["NO_FINDINGS"]},
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

    def test_completed_first_review_over_soft_threshold_is_not_discarded(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
                                        "one-review-1": [("NO_FINDINGS", 210)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"], [])
        self.assertTrue(result["review_wrapups"][0]["used_completed_verdict"])
        self.assertFalse(any(c[0].endswith("-conclude") for c in backend.calls))

    def test_interrupted_first_review_concludes_then_repairs_and_continues(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
            "one-review-1": [(interrupted_review, 210)], "one-review-1-conclude": [finding("Defect")],
            "one-fix-1": [edit(2, 1), "@standalone done"], "one-review-2": ["NO_FINDINGS"]},
            policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"], [])
        self.assertEqual([r["approved"] for r in result["reviews"]], [False, True])
        calls = [c for c in backend.calls if c[0].startswith("one-review-1")]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertIn("Do not start new tools", calls[1][2])
        self.assertEqual(result["review_wrapups"][0]["status"], "completed")

    def test_completed_rejection_over_threshold_also_reaches_author(self):
        result, _ = self.execute({"one-implement": [edit(1), "@standalone done"],
            "one-review-1": [(finding("Defect"), 210)], "one-fix-1": [edit(2, 1), "@standalone done"],
            "one-review-2": ["NO_FINDINGS"]}, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len(result["reviews"]), 2)

    def test_unfinished_conclusion_is_attention_without_fabricated_approval(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
            "one-review-1": [(interrupted_review, 210)],
            "one-review-1-conclude": ["INCOMPLETE_REVIEW\nNeed evidence for statement boundaries."]},
            policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "review_incomplete")
        self.assertIsNone(result["reviews"][0]["approved"])
        self.assertEqual(result["attention"]["review"]["status"], "incomplete")
        self.assertEqual(result["attention"]["final_review"]["status"], "not_run")
        self.assertEqual(backend.calls[-1][0], "one-review-1-conclude")

    def test_conclusion_has_hard_budget_and_never_restarts(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
            "one-review-1": [(interrupted_review, 210)], "one-review-1-conclude": [("NO_FINDINGS", 110)]},
            policy={"max_feature_raw": 1000, "max_review_raw": 200, "max_review_wrapup_raw": 100})
        self.assert_attention(result, "review_wrapup_token_limit")
        self.assertIsNone(result["attention"]["review_approved"])
        self.assertEqual(result["attention"]["review"]["status"], "stopped")
        self.assertEqual(result["review_wrapups"][0]["status"], "stopped")
        self.assertEqual(backend.calls[-1][0], "one-review-1-conclude")

    def test_feature_budget_has_precedence_over_review_threshold(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
                                       "one-review-1": [("NO_FINDINGS", 1000)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertEqual(result["review_wrapups"], [])
        self.assertEqual(backend.calls[-1][0], "one-review-1")

    def test_review_can_finish_using_feature_reserve_without_another_review(self):
        result, _ = self.execute({"one-implement": [(edit(1), 700), "@standalone done"],
                                 "one-review-1": [("NO_FINDINGS", 210)]},
                                policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["usage"]["observed_raw_tokens"], 920)

    def test_rejection_consuming_author_allowance_stops_without_fake_repair_or_duplicate_review(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
                                       "one-review-1": [(finding("Defect"), 850)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertEqual(result["attention"]["repair_attempts"], 0)
        self.assertFalse(result["attention"]["review_approved"])
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")
        self.assertEqual(backend.calls[-1][0], "one-review-1")

    def test_stopped_repair_of_unchanged_rejected_tree_does_not_buy_another_review(self):
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
                                       "one-review-1": [finding("Defect")],
                                       "one-fix-1": [("@standalone read one.py", 850)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "feature_token_limit")
        self.assertFalse(result["attention"]["review_approved"])
        self.assertEqual(result["attention"]["final_review"]["status"], "already_reviewed")
        self.assertEqual(backend.calls[-1][0], "one-fix-1")

    def test_stopped_repair_that_changed_rejected_tree_still_gets_final_review(self):
        result, _ = self.execute({"one-implement": [edit(1), "@standalone done"],
                                 "one-review-1": [finding("Defect")],
                                 "one-fix-1": [(edit(2, 1), 200), ("@standalone read one.py", 650)],
                                 "one-review-2": ["NO_FINDINGS"]},
                                policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["loop_flags"][0]["review_approved"])

    def test_recorded_full_benchmark_stops_at_conclusion_without_redundant_fourth_review(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/review-reserve-exhaustion.json").read_text())
        costs = fixture["stage_raw"]
        script = {"one-implement": [(edit(1), costs["checkpoint_3-implement"] - 10), "@standalone done"]}
        for review in fixture["reviews"]:
            number = review["round"]
            verdict = "FINDINGS\n" + "\n".join(f"- [{f['priority']}] Recorded finding {f['text_sha256']}"
                                              for f in review["blocking_findings"])
            if number < 3:
                script[f"one-review-{number}"] = [(verdict, costs[f"checkpoint_3-review-{number}"])]
                script[f"one-fix-{number}"] = [(edit(number + 1, number), costs[f"checkpoint_3-fix-{number}"] - 10),
                                              "@standalone done"]
            else:
                def threshold(repo):
                    raise ReviewConclusionRequested(fixture["trigger"])
                script["one-review-3"] = [(threshold, costs["checkpoint_3-review-3"])]
                script["one-review-3-conclude"] = [(verdict, costs["checkpoint_3-review-3-conclude"])]
        result, backend = self.execute(script)
        self.assert_attention(result, "feature_token_limit")
        self.assertEqual(result["attention"]["repair_attempts"], fixture["repair_attempts_before_conclusion"])
        self.assertEqual(result["usage"]["observed_raw_tokens"], fixture["feature_raw_at_conclusion"])
        self.assertEqual(result["review_wrapups"][0]["trigger"], fixture["trigger"])
        self.assertEqual(result["attention"]["final_review"]["label"], "one-review-3")
        self.assertEqual(backend.calls[-1][0], "one-review-3-conclude")

    def test_missing_usage_after_interruption_prevents_conclusion(self):
        def unpriced(repo):
            Scripted.instances[-1].report = lambda: {"observed_raw_tokens": 230, "measurement_complete": False}
            return interrupted_review(repo)
        result, backend = self.execute({"one-implement": [edit(1), "@standalone done"],
                                       "one-review-1": [(unpriced, 210)]},
                                      policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("incomplete token measurement", result["error"])
        self.assertEqual(backend.calls[-1][0], "one-review-1")

    def test_final_review_has_its_own_limit_and_is_not_retried(self):
        result, backend = self.execute({"one-implement": [edit(1)] + ["@standalone read one.py"] * 3,
                                        "one-review-1": [("NO_FINDINGS", 210)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_attention(result, "repeated_operations")
        self.assertEqual(result["attention"]["final_review"]["reason"], "review_token_limit")
        self.assertEqual(len([c for c in backend.calls if "-review-" in c[0]]), 1)

    def test_dirty_native_work_is_preserved_and_never_treated_as_reviewed_commit(self):
        def unfinished(repo):
            (repo / "one.py").write_text("value = 1\n")
            return "@standalone done"
        result, backend = self.execute({"one-implement": [(unfinished, 900)]},
                                       policy={"max_feature_raw": 1000, "max_review_raw": 200},
                                       factors={"C17": False, "C08": False, "C25": False})
        self.assert_attention(result, "feature_token_limit")
        self.assertIn("one.py", result["attention"]["working_tree_status"])
        self.assertEqual(result["attention"]["final_review"]["status"], "skipped")
        self.assertTrue((backend.repo / "one.py").is_file())
        self.assertEqual(len(backend.calls), 1)

    def test_final_review_can_be_disabled(self):
        result, backend = self.execute({"one-implement": [edit(1)] + ["@standalone read one.py"] * 3},
                                       policy={"final_review": False})
        self.assert_attention(result, "repeated_operations")
        self.assertFalse(any("-review-" in c[0] for c in backend.calls))

    def test_same_operation_after_real_source_changes_is_not_a_loop(self):
        result, _ = self.execute({"one-implement": [edit(1), "@standalone read one.py", edit(2, 1),
                                                    "@standalone read one.py", edit(3, 2),
                                                    "@standalone read one.py", "@standalone done"],
                                  "one-review-1": ["NO_FINDINGS"]})
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["loop_flags"], [])

    def test_pending_command_edits_are_preserved_and_prevent_final_review(self):
        result, backend = self.execute({"one-implement": [edit(1),
            "@standalone run one.py -- printf 'value = 2\\n' > one.py"] + ["@standalone read one.py"] * 3})
        self.assert_attention(result, "repeated_operations")
        self.assertTrue(result["attention"]["pending_host_changes"])
        self.assertEqual(result["attention"]["final_review"]["reason"], "pending_host_changes")
        self.assertEqual((backend.repo / "one.py").read_text(), "value = 1\n")
        self.assertTrue(any((self.root / "run/one-host").rglob("receipt.json")))
        self.assertFalse(any("-review-" in c[0] for c in backend.calls))

    def test_malformed_final_review_retains_flag_without_manufacturing_approval(self):
        result, backend = self.execute({"one-implement": [edit(1)] + ["@standalone read one.py"] * 3,
                                        "one-review-1": ["Probably fine"]})
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["checkpoints"], [])
        flag = json.loads(Path(result["loop_flags"][0]["artifact"]).read_text())
        self.assertEqual(flag["final_review"]["status"], "failed")
        self.assertIsNone(flag["review_approved"])
        self.assertFalse(any(c[0].startswith("integration") for c in backend.calls))

    def test_disabled_policy_preserves_old_loop_behavior_and_changes_comparison_key(self):
        script = {"one-implement": [edit(1)] + ["@standalone read one.py"] * 4 + ["@standalone done"],
                  "one-review-1": ["NO_FINDINGS"]}
        disabled, backend = self.execute(script, policy={"enabled": False}, name="disabled")
        enabled, _ = self.execute(script, name="enabled")
        self.assertEqual(disabled["status"], "passed", disabled)
        self.assertEqual(disabled["loop_flags"], [])
        self.assertEqual(len([c for c in backend.calls if c[0] == "one-implement"]), 6)
        self.assertNotEqual(disabled["comparison_key"], enabled["comparison_key"])


class LoopConfigurationTests(unittest.TestCase):
    def test_recorded_first_review_threshold_requests_conclusion_within_feature_budget(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/review-threshold.json").read_text())
        progress = FeatureProgress({"id": "checkpoint_3"}, loop_policy(), 0)
        raw = fixture["feature_author_raw"]
        limits = progress.limits(raw, reviewing=True)
        for index, usage in enumerate(fixture["review_responses"]):
            raw += usage[0] + usage[1]
            error = work_limit_error(limits, raw, limits[-1]["start"])
            if index < len(fixture["review_responses"]) - 1:
                self.assertIsNone(error)
        self.assertEqual(raw, fixture["feature_raw"])
        self.assertIsInstance(error, ReviewConclusionRequested)
        self.assertEqual(error.signal["observed"], fixture["review_raw"])
        self.assertEqual(error.signal["kind"], "review_wrapup")
        self.assertEqual(progress.repairs, 0)
        conclusion = progress.limits(raw, reviewing=True, concluding=True)
        self.assertIsNone(work_limit_error(conclusion, raw + 60000, conclusion[-1]["start"]))

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
        self.assertIsInstance(error, ReviewConclusionRequested)
        self.assertEqual(error.signal["reason"], "review_time_threshold")
        error = work_limit_error(limits, 500200, limits[-1]["start"])
        self.assertEqual(error.signal["reason"], "review_token_threshold")
        self.assertEqual(error.signal["kind"], "review_wrapup")

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
                         "features": [{"id": "one", "request": "Create one"}], "checks": ["true"], "instructions": ""}
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
                         "features": [{"id": "one", "request": "Create one"}], "checks": ["true"], "instructions": ""}
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
