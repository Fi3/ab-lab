"""Bounded reviews advance; safety failures retain the attempt and stop."""
import json
from pathlib import Path
import unittest

from lab.config import settings
from lab.host import Fatal, git
from lab.workflow import run
import test_slopcodebench as fixtures
from test_workflow import verdict


def edit(name, value, previous=None):
    body = (f"*** Add File: {name}.py\n+value = {value}\n" if previous is None else
            f"*** Update File: {name}.py\n@@\n-value = {previous}\n+value = {value}\n")
    return {"name": "host_edit", "arguments": {"patch": "*** Begin Patch\n" + body + "*** End Patch\n"}}


def native_edit(name, value, *, commit=True):
    def apply(backend):
        (backend.repo / (name + ".py")).write_text(f"value = {value}\n")
        if commit:
            git(backend.repo, "add", name + ".py")
            git(backend.repo, "commit", "-qm", "Implement " + name)
        return "Finished."
    return apply


class ScenarioBackend(fixtures.ClosingCodex):
    script = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.script = {label: list(actions) for label, actions in self.script.items()}
        self.raw = 0
        self.complete = True
        self.limits_by_call = []

    def turn(self, thread, prompt, label, **kwargs):
        self.calls.append((label, thread, prompt, kwargs))
        self.limits_by_call.append((label, [dict(limit) for limit in self.work_limits]))
        while self.script[label]:
            action = self.script[label].pop(0)
            reply, cost = action if isinstance(action, tuple) else (action, 10)
            self.raw += cost
            reply = reply(self) if callable(reply) else reply
            if isinstance(reply, dict) and "status" in reply:
                return self.submit_review(thread, prompt, label, reply)
            if isinstance(reply, dict):
                from lab.loops import work_limit_error
                from lab.host import Fatal
                if not self.complete:
                    raise Fatal("incomplete token measurement")
                error = work_limit_error(self.work_limits, self.raw)
                if error:
                    raise error
                self.tool_call(thread, reply["name"], reply["arguments"], f"{label}-{len(self.script[label])}")
            else:
                return reply
        return "Finished."

    def report(self):
        return {"observed_raw_tokens": self.raw, "measurement_complete": self.complete,
                "unpriced_or_incomplete_turns": [], "turns": []}


class SlopAttentionTests(unittest.TestCase):
    # Reuse repository/evaluator fixtures without inheriting their test methods.
    setUp = fixtures.SlopCodeBenchTests.setUp
    benchmark = fixtures.SlopCodeBenchTests.benchmark
    workflow = fixtures.SlopCodeBenchTests.workflow
    evaluated = fixtures.SlopCodeBenchTests.evaluated

    def execute(self, script, *, name="run", native=False, harness="codex",
                policy=None, benchmark=None, max_raw=10_000, max_review_loops=3):
        class Backend(ScenarioBackend):
            pass
        Backend.script = script
        Backend.transport = "pi-rpc-stdio" if harness == "pi" else "codex-app-server-stdio"
        factors = settings({"C17": False, "C08": False}) if native else settings({})
        result = run(benchmark or self.benchmark(), factors, self.root / name, 30, max_raw, 30,
                     backend=Backend, harness=harness,                      loop_options=policy, max_review_loops=max_review_loops)
        return result, Backend.instances[-1]

    def assert_stopped_attention(self, result, backend):
        self.assertEqual(result["status"], "needs_attention", result.get("error"))
        self.assertEqual(result["execution_status"], "incomplete", result.get("error"))
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertEqual([item["feature"] for item in result["checkpoints"]], ["one"])
        self.assertEqual(result["checkpoints"][0]["review_rounds"],
                         sum(label.startswith("one-review-") for label, *_ in backend.calls))
        self.assertTrue(result["usage"]["measurement_complete"])
        self.assertEqual(result["checks"], [])
        self.assertNotIn("final_commits", result)
        self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))
        self.assertFalse((backend.repo / "two.py").exists())
        report = result["slopcodebench"]
        self.assertEqual(report["status"], "incomplete", report)
        self.assertFalse(report["solved"])
        self.assertIsNone(report["all_tests_passed"])
        self.assertIsNone(report["final"])
        one, two = report["checkpoints"]
        self.assertIn(one["status"], ("passed", "failed"))
        self.assertTrue(Path(one["snapshot"]).is_dir())
        self.assertFalse(one.get("infrastructure_failure"))
        self.assertEqual(two, {"feature": "two", "status": "not_run"})
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")
        for flag in result["loop_flags"]:
            self.assertNotIn("continuation", flag)
            self.assertEqual(flag["retention"]["commit"], result["checkpoints"][0]["head"])
            self.assertEqual(json.loads(Path(flag["artifact"]).read_text()), flag)

    def test_bounded_reviews_advance_across_harness_and_custody_modes(self):
        for harness in ("codex", "pi"):
            for native in (False, True):
                for limit in (0, 1, 3):
                    with self.subTest(harness=harness, native=native, limit=limit):
                        actions = lambda name, value, previous=None: ([native_edit(name, value)] if native
                            else [edit(name, value, previous), "Finished."])
                        previous = 1 if limit else 2
                        script = {"one-implement": actions("one", previous),
                                  "two-implement": actions("two", 1)}
                        expected = ["one-implement"]
                        for number in range(1, limit + 1):
                            script[f"one-review-{number}"] = [verdict(f"Defect {number}.")]
                            value = 2 if number == limit else previous + 1
                            script[f"one-fix-{number}"] = actions("one", value, previous)
                            previous = value
                            expected += [f"one-review-{number}", f"one-fix-{number}"]
                        expected.append("two-implement")
                        if limit:
                            script["two-review-1"] = [verdict()]
                            expected.append("two-review-1")
                        name = f"{harness}-{native}-{limit}"
                        before = len(self.evaluated())
                        result, backend = self.execute(script, name=name, native=native,
                            harness=harness, max_review_loops=limit)
                        self.assertEqual(result["status"], "passed", result.get("error"))
                        self.assertEqual(result["execution_status"], "completed")
                        self.assertTrue((self.root / name / "provider-closed").exists())
                        self.assertEqual([label for label, *_ in backend.calls], expected)
                        self.assertEqual(result["loop_flags"], [])
                        one, two = result["checkpoints"]
                        self.assertEqual(one["status"], "review_limit_reached" if limit else "review_skipped")
                        self.assertIsNone(one["review_approved"])
                        self.assertIsNone(one["reviewed_head"])
                        self.assertFalse(one["already_satisfied"])
                        self.assertEqual(one["review_rounds"], limit)
                        self.assertEqual(one["repair_attempts"], limit)
                        self.assertIs(two["review_approved"], True if limit else None)
                        if limit:
                            self.assertNotEqual(one["head"], result["reviews"][limit-1]["head"])
                        else:
                            self.assertEqual(result["reviews"], [])
                            self.assertEqual(backend.threads, 2)
                        self.assertTrue(result["slopcodebench"]["solved"])
                        saved = result["slopcodebench"]["checkpoints"][0]
                        self.assertEqual(saved["commit"], one["head"])
                        self.assertEqual((Path(saved["snapshot"]) / "one.py").read_text(), "value = 2\n")
                        self.assertIsNone(saved["review_approved"])
                        self.assertEqual(saved["attempt_status"], one["status"])
                        manifest = json.loads((self.root / name / "manifest.json").read_text())
                        self.assertEqual(manifest["transport"], backend.transport)
                        self.assertEqual(manifest["max_review_loops"], limit)
                        self.assertEqual(result["max_review_loops"], limit)
                        self.assertEqual([x["checkpoint"] for x in self.evaluated()[before:]], ["one", "two", "two"])

    def test_review_limit_is_part_of_comparison_identity(self):
        script = {"one-implement": [edit("one", 2), "Finished."],
                  "one-review-1": [verdict()],
                  "two-implement": [edit("two", 1), "Finished."],
                  "two-review-1": [verdict()]}
        first, _ = self.execute(script, name="one-review", max_review_loops=1)
        second, _ = self.execute(script, name="three-reviews", max_review_loops=3)
        self.assertEqual(first["status"], "passed", first.get("error"))
        self.assertEqual(second["status"], "passed", second.get("error"))
        self.assertNotEqual(first["comparison_key"], second["comparison_key"])

    def test_invalid_review_limit_fails_before_creating_run(self):
        for limit in (-1, True, 1.5, "3", None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.execute({}, max_review_loops=limit)
        self.assertFalse((self.root / "run").exists())

    def test_default_review_can_exceed_former_cutoff_and_repair_before_progressing(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": [(verdict('Set the required value to 2.'), 600_000)],
            "one-fix-1": [edit("one", 2, 1), "Finished."],
            "one-review-2": [(verdict(), 600_000)],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": [verdict()],
        }, max_raw=5_000_000)
        self.assertEqual(result["status"], "passed", result.get("error"))
        self.assertEqual(result["execution_status"], "completed")
        self.assertTrue(result["slopcodebench"]["solved"])
        self.assertEqual(result["loop_flags"], [])
        self.assertEqual([c["review_rounds"] for c in result["checkpoints"]], [2, 1])
        labels = [label for label, *_ in backend.calls]
        self.assertLess(labels.index("one-fix-1"), labels.index("one-review-2"))
        self.assertLess(labels.index("one-review-2"), labels.index("two-implement"))
        self.assertTrue(all(not limits for _, limits in backend.limits_by_call))
        self.assertGreater(result["usage"]["observed_raw_tokens"], 1_200_000)
        for _, _, prompt, _ in backend.calls:
            self.assertNotIn("EVALUATOR_SECRET", prompt)
            self.assertNotIn("500000", prompt)

    def test_explicit_former_review_cutoff_stops_without_skipping_to_next_feature(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 2), "Finished."],
            "one-review-1": [(verdict(), 600_000)],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": [verdict()],
        }, policy={"max_review_raw": 500_000}, max_raw=5_000_000)
        self.assert_stopped_attention(result, backend)
        flag, = result["loop_flags"]
        self.assertEqual(flag["reason"], "review_token_limit")
        self.assertEqual(flag["limit"], 500_000)
        self.assertEqual(flag["observed"], 600_000)
        self.assertEqual(result["reviews"], [])
        self.assertIsNone(result["checkpoints"][0]["review_approved"])
        self.assertEqual([item["checkpoint"] for item in self.evaluated()], ["one"])

    def test_feature_budget_stop_retains_attempt_and_blocks_next_checkpoint(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), ({"name": "host_read", "arguments": {"path": "one.py"}}, 900)],
            "one-review-1": [verdict('First attempt remains incorrect.')],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": [verdict()],
        }, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_stopped_attention(result, backend)
        self.assertEqual(result["loop_flags"][0]["reason"], "feature_token_limit")
        self.assertEqual(result["checkpoints"][0]["observed_raw_tokens"], 920)
        self.assertEqual(result["slopcodebench"]["checkpoints"][0]["status"], "failed")

    def test_repeated_rejection_blocks_successors_without_replaying_unchanged_repairs(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": [verdict('The required value must be 2.')],
            "one-fix-1": ["No edits were made."],
            "one-review-2": [verdict('The required value must still be 2.')],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": [verdict()],
        })
        self.assert_stopped_attention(result, backend)
        flag, = result["loop_flags"]
        self.assertEqual(flag["reason"], "repeated_rejected_tree")
        self.assertIs(flag["review_approved"], False)
        self.assertEqual(flag["rounds"], [1, 2])
        self.assertEqual(result["reviews"][0]["head"], result["reviews"][1]["head"])
        self.assertFalse(any(label == "one-fix-2" for label, *_ in backend.calls))

    def test_incomplete_review_preserves_unknown_approval_and_blocks_successors(self):
        for value in (verdict(incomplete_reason="MISSING_ONE_EVIDENCE"), "Not a verdict"):
            with self.subTest(verdict=value):
                result, backend = self.execute({
                    "one-implement": [edit("one", 2), "Finished."],
                    "one-review-1": [value],
                    "two-implement": [edit("two", 1), "Finished."],
                    "two-review-1": [verdict()],
                }, name="incomplete" if isinstance(value, dict) else "malformed")
                self.assert_stopped_attention(result, backend)
                self.assertEqual(len(result["loop_flags"]), 1)
                checkpoint, = result["checkpoints"]
                self.assertEqual(checkpoint["status"], "needs_attention")
                self.assertIsNone(checkpoint["review_approved"])
                self.assertIsNone(checkpoint["reviewed_head"])
                self.assertTrue(checkpoint["incomplete_reason"])

    def test_stopped_dirty_native_work_gets_unapproved_retention_commit(self):
        result, backend = self.execute({
            "one-implement": [(native_edit("one", 1, commit=False), 900)],
            "two-implement": [native_edit("two", 1)],
            "two-review-1": [verdict()],
        }, native=True, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_stopped_attention(result, backend)
        flag = result["loop_flags"][0]
        retention = flag["retention"]
        self.assertIn("one.py", retention["working_tree_status_before_retention"])
        self.assertEqual(retention["previous_head"], flag["head"])
        self.assertEqual(retention["retention_commit"], result["checkpoints"][0]["head"])
        self.assertNotEqual(retention["retention_commit"], flag["head"])
        message = git(backend.repo, "show", "-s", "--format=%B", retention["retention_commit"]).decode().lower()
        self.assertIn("unapproved", message)
        self.assertIsNone(result["checkpoints"][0]["review_approved"])
        self.assertFalse(any(label.startswith("one-review-") for label, *_ in backend.calls))
        self.assertEqual((Path(result["slopcodebench"]["checkpoints"][0]["snapshot"]) / "one.py").read_text(), "value = 1\n")

    def test_staged_edit_reverted_in_worktree_does_not_create_empty_retention_commit(self):
        def staged_then_restored(backend):
            native_edit("one", 1)(backend)
            path = backend.repo / "one.py"
            path.write_text("value = 2\n")
            git(backend.repo, "add", "one.py")
            path.write_text("value = 1\n")
            return "Finished."

        result, backend = self.execute({
            "one-implement": [(staged_then_restored, 900)],
            "two-implement": [native_edit("two", 1)],
            "two-review-1": [verdict()],
        }, native=True, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_stopped_attention(result, backend)
        retention = result["loop_flags"][0]["retention"]
        self.assertIn("MM one.py", retention["working_tree_status_before_retention"])
        self.assertIsNone(retention["retention_commit"])
        self.assertEqual(retention["previous_head"], result["checkpoints"][0]["head"])
        self.assertEqual((backend.repo / "one.py").read_text(), "value = 1\n")

    def test_global_and_provider_failures_are_not_treated_as_checkpoint_attention(self):
        for reason in ("global observed-token budget exhausted", "provider unavailable"):
            with self.subTest(reason=reason):
                def fail(backend):
                    raise Fatal(reason)
                result, backend = self.execute({"one-implement": [fail]}, name=reason.replace(" ", "-"))
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["error"], reason)
                self.assertEqual(result["execution_status"], "incomplete")
                self.assertEqual(result["loop_flags"], [])
                self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))

    def test_incomplete_accounting_does_not_capture_or_approve_stopped_checkpoint(self):
        def unpriced(backend):
            backend.complete = False
            return verdict(incomplete_reason='Need evidence.')
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": [unpriced],
            "two-implement": [edit("two", 1), "Finished."],
        })
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("incomplete token measurement", result["error"])
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertFalse(result["usage"]["measurement_complete"])
        self.assertEqual(result["checkpoints"], [])
        self.assertEqual(self.evaluated(), [])
        self.assertFalse((backend.repo / "two.py").exists())
        self.assertFalse(any(label.startswith("integration-") for label, *_ in backend.calls))

    def test_evaluator_infrastructure_failure_is_not_hidden_by_attention(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 2), "Finished."],
            "one-review-1": [verdict(incomplete_reason='Need evidence.')],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": [verdict()],
        }, benchmark=self.benchmark("infrastructure"))
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["execution_status"], "incomplete")
        self.assertEqual(len(result["checkpoints"]), 1)
        self.assertEqual(len(result["loop_flags"]), 1)
        self.assertEqual(result["slopcodebench"]["status"], "error")
        self.assertFalse(result["slopcodebench"]["solved"])
        self.assertIsNone(result["slopcodebench"]["all_tests_passed"])
        self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))

    def test_generic_benchmark_also_blocks_dependent_features(self):
        benchmark = self.benchmark()
        del benchmark["slopcodebench"]
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": [verdict(incomplete_reason='Need evidence.')],
        }, benchmark=benchmark)
        self.assertEqual(result["status"], "needs_attention", result)
        self.assertEqual(result["checkpoints"], [])
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))


if __name__ == "__main__":
    unittest.main()
