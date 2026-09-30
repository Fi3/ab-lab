"""A bounded checkpoint attempt must not prevent the rest of SCB from being measured."""
import json
from pathlib import Path
import unittest

from lab.config import settings
from lab.host import Fatal, git
import test_slopcodebench as fixtures


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
    preserve_history = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.script = {label: list(actions) for label, actions in self.script.items()}
        self.raw = 0
        self.complete = True
        self.limits_by_call = []

    def turn(self, thread, prompt, label, **kwargs):
        if label == "integration-accept" and not self.preserve_history:
            return super().turn(thread, prompt, label, **kwargs)
        self.calls.append((label, thread, prompt, kwargs))
        self.limits_by_call.append((label, [dict(limit) for limit in self.work_limits]))
        if label.startswith("integration-"):
            return "Keep the checkpoint commits and retained findings."
        while self.script[label]:
            action = self.script[label].pop(0)
            reply, cost = action if isinstance(action, tuple) else (action, 10)
            self.raw += cost
            reply = reply(self) if callable(reply) else reply
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

    def execute(self, script, *, name="run", native=False, harness="codex", preserve=True,
                policy=None, benchmark=None):
        class Backend(ScenarioBackend):
            pass
        Backend.script = script
        Backend.preserve_history = preserve
        Backend.transport = "pi-rpc-stdio" if harness == "pi" else "codex-app-server-stdio"
        factors = settings({"C17": False, "C08": False}) if native else settings({})
        result = self.workflow(benchmark=benchmark, name=name, backend=Backend, factors=factors,
                               harness=harness, skip_linearization=preserve, loop_options=policy)
        return result, Backend.instances[-1]

    def assert_completed_attention(self, result):
        self.assertEqual(result["status"], "needs_attention", result.get("error"))
        self.assertEqual(result["execution_status"], "completed", result.get("error"))
        self.assertFalse(result.get("blocked_features"))
        self.assertEqual([item["feature"] for item in result["checkpoints"]], ["one", "two"])
        self.assertTrue(result["usage"]["measurement_complete"])
        self.assertEqual(result["checks"][0]["exit_code"], 0)
        report = result["slopcodebench"]
        self.assertEqual(report["status"], "completed", report)
        self.assertFalse(report["solved"])
        self.assertIsInstance(report["all_tests_passed"], bool)
        self.assertEqual([item["feature"] for item in report["checkpoints"]], ["one", "two"])
        for item in [*report["checkpoints"], report["final"]]:
            self.assertIn(item["status"], ("passed", "failed"))
            self.assertTrue(Path(item["snapshot"]).is_dir())
            self.assertFalse(item.get("infrastructure_failure"))
        for flag in result["loop_flags"]:
            if flag["resolution"] == "needs_attention":
                self.assertEqual(flag["continuation"]["status"], "continued")
                self.assertEqual(json.loads(Path(flag["artifact"]).read_text()), flag)

    def test_rejection_continues_across_harness_custody_and_history_modes(self):
        for harness in ("codex", "pi"):
            for native in (False, True):
                for preserve in (False, True):
                    with self.subTest(harness=harness, native=native, preserve=preserve):
                        actions = lambda name, value, previous=None: ([native_edit(name, value)] if native
                            else [edit(name, value, previous), "Finished."])
                        script = {
                            "one-implement": actions("one", 1),
                            "one-review-1": ["FINDINGS\n- [P2] First unresolved behavior."],
                            "one-fix-1": actions("one", 2, 1),
                            "one-review-2": ["FINDINGS\n- [P2] STILL_UNRESOLVED call boundaries."],
                            "two-implement": actions("two", 1),
                            "two-review-1": ["NO_FINDINGS"],
                        }
                        name = f"{harness}-{native}-{preserve}"
                        result, backend = self.execute(script, name=name, native=native,
                            harness=harness, preserve=preserve, policy={"max_repair_attempts": 1})
                        self.assert_completed_attention(result)
                        one, two = result["checkpoints"]
                        self.assertEqual(one["status"], "needs_attention")
                        self.assertIs(one["review_approved"], False)
                        self.assertIsNone(one["reviewed_head"])
                        self.assertEqual(one["head"], result["reviews"][1]["head"])
                        self.assertIs(two["review_approved"], True)
                        self.assertEqual(two["reviewed_head"], two["head"])
                        self.assertEqual(result["loop_flags"][0]["reason"], "repair_limit_reached")
                        self.assertTrue(result["slopcodebench"]["all_tests_passed"])
                        later = next(prompt for label, _, prompt, _ in backend.calls if label == "two-implement")
                        self.assertIn("STILL_UNRESOLVED", later)
                        self.assertNotIn("EVALUATOR_SECRET", later)
                        self.assertFalse(any(label == "one-fix-2" for label, *_ in backend.calls))
                        manifest = json.loads((self.root / name / "manifest.json").read_text())
                        self.assertEqual(manifest["transport"], backend.transport)
                        self.assertEqual(len(result["final_commits"]), 3 if preserve else 2)
                        self.assertEqual([x["checkpoint"] for x in self.evaluated()][-3:], ["one", "two", "two"])

    def test_feature_budget_resets_for_the_next_checkpoint_and_integration(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), ({"name": "host_read", "arguments": {"path": "one.py"}}, 900)],
            "one-review-1": ["FINDINGS\n- [P2] First attempt remains incorrect."],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
        }, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_completed_attention(result)
        self.assertEqual(result["loop_flags"][0]["reason"], "feature_token_limit")
        self.assertEqual(result["checkpoints"][0]["observed_raw_tokens"], 920)
        self.assertEqual(result["checkpoints"][1]["observed_raw_tokens"], 30)
        second_limits = next(limits for label, limits in backend.limits_by_call if label == "two-implement")
        self.assertEqual(second_limits[0]["start"], 920)
        self.assertTrue(all(not limits for label, limits in backend.limits_by_call if label.startswith("integration-")))
        self.assertFalse(result["slopcodebench"]["all_tests_passed"])

    def test_multiple_incomplete_reviews_preserve_unknown_approval_and_grade_every_attempt(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 2), "Finished."],
            "one-review-1": ["INCOMPLETE_REVIEW\nMISSING_ONE_EVIDENCE"],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["INCOMPLETE_REVIEW\nMISSING_TWO_EVIDENCE"],
        })
        self.assert_completed_attention(result)
        self.assertEqual(len(result["loop_flags"]), 2)
        self.assertTrue(result["slopcodebench"]["all_tests_passed"])
        for checkpoint in result["checkpoints"]:
            self.assertEqual(checkpoint["status"], "needs_attention")
            self.assertIsNone(checkpoint["review_approved"])
            self.assertIsNone(checkpoint["reviewed_head"])
        second_prompt = next(prompt for label, _, prompt, _ in backend.calls if label == "two-implement")
        self.assertIn("MISSING_ONE_EVIDENCE", second_prompt)

    def test_stopped_dirty_native_work_gets_unapproved_retention_commit(self):
        result, backend = self.execute({
            "one-implement": [(native_edit("one", 1, commit=False), 900)],
            "two-implement": [native_edit("two", 1)],
            "two-review-1": ["NO_FINDINGS"],
        }, native=True, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_completed_attention(result)
        flag = result["loop_flags"][0]
        retention = flag["continuation"]
        self.assertIn("one.py", retention["working_tree_status_before_retention"])
        self.assertEqual(retention["previous_head"], flag["head"])
        self.assertEqual(retention["retention_commit"], result["checkpoints"][0]["head"])
        self.assertNotEqual(retention["retention_commit"], flag["head"])
        message = git(backend.repo, "show", "-s", "--format=%B", retention["retention_commit"]).decode().lower()
        self.assertIn("unapproved", message)
        self.assertIsNone(result["checkpoints"][0]["review_approved"])
        self.assertFalse(any(label.startswith("one-review-") for label, *_ in backend.calls))
        self.assertEqual((Path(result["slopcodebench"]["checkpoints"][0]["snapshot"]) / "one.py").read_text(), "value = 1\n")
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")


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
            "two-review-1": ["NO_FINDINGS"],
        }, native=True, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_completed_attention(result)
        flag = result["loop_flags"][0]
        retention = flag["continuation"]
        self.assertIn("MM one.py", retention["working_tree_status_before_retention"])
        self.assertIsNone(retention["retention_commit"])
        self.assertEqual(retention["previous_head"], result["checkpoints"][0]["head"])
        self.assertIsNone(result["checkpoints"][0]["review_approved"])
        self.assertEqual((backend.repo / "one.py").read_text(), "value = 1\n")
        self.assertEqual(len(result["final_commits"]), 2)
        self.assertEqual(git(backend.repo, "status", "--porcelain"), b"")

    def test_global_and_provider_failures_are_not_treated_as_checkpoint_attention(self):
        for reason in ("global observed-token budget exhausted", "provider unavailable"):
            with self.subTest(reason=reason):
                def fail(backend):
                    raise Fatal(reason)
                result, backend = self.execute({"one-implement": [fail]}, name=reason.replace(" ", "-"))
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["error"], reason)
                self.assertNotEqual(result.get("execution_status"), "completed")
                self.assertEqual(result["loop_flags"], [])
                self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))

    def test_incomplete_accounting_blocks_continuation_even_after_an_earlier_attention(self):
        def unpriced(backend):
            backend.complete = False
            return edit("two", 1)
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": ["INCOMPLETE_REVIEW\nNeed evidence."],
            "two-implement": [unpriced],
        })
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("incomplete token measurement", result["error"])
        self.assertNotEqual(result.get("execution_status"), "completed")
        self.assertFalse(result["usage"]["measurement_complete"])
        self.assertEqual(len(result["loop_flags"]), 1)
        self.assertFalse((backend.repo / "two.py").exists())
        self.assertFalse(any(label.startswith("integration-") for label, *_ in backend.calls))

    def test_evaluator_infrastructure_failure_is_not_hidden_by_attention(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 2), "Finished."],
            "one-review-1": ["INCOMPLETE_REVIEW\nNeed evidence."],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
        }, benchmark=self.benchmark("infrastructure"))
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["execution_status"], "completed")
        self.assertEqual(len(result["checkpoints"]), 2)
        self.assertEqual(len(result["loop_flags"]), 1)
        self.assertEqual(result["slopcodebench"]["status"], "error")
        self.assertFalse(result["slopcodebench"]["solved"])
        self.assertIsNone(result["slopcodebench"]["all_tests_passed"])
        self.assertTrue(any(label == "integration-accept" for label, *_ in backend.calls))

    def test_legacy_benchmark_still_blocks_dependent_features(self):
        benchmark = self.benchmark()
        del benchmark["slopcodebench"]
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": ["INCOMPLETE_REVIEW\nNeed evidence."],
        }, benchmark=benchmark)
        self.assertEqual(result["status"], "needs_attention", result)
        self.assertEqual(result["checkpoints"], [])
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))


if __name__ == "__main__":
    unittest.main()
