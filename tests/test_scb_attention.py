"""Every checkpoint needs review approval before dependent work can begin."""
import json
from pathlib import Path
import unittest

from lab.config import settings
from lab.host import Fatal, git
from lab.workflow import run
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
                policy=None, benchmark=None, max_raw=10_000):
        class Backend(ScenarioBackend):
            pass
        Backend.script = script
        Backend.preserve_history = preserve
        Backend.transport = "pi-rpc-stdio" if harness == "pi" else "codex-app-server-stdio"
        factors = settings({"C17": False, "C08": False}) if native else settings({})
        result = run(benchmark or self.benchmark(), factors, self.root / name, 30, max_raw, 30,
                     backend=Backend, harness=harness, skip_linearization=preserve,
                     loop_options=policy)
        return result, Backend.instances[-1]

    def assert_stopped_attention(self, result, backend):
        self.assertEqual(result["status"], "needs_attention", result.get("error"))
        self.assertEqual(result["execution_status"], "incomplete", result.get("error"))
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertEqual([item["feature"] for item in result["checkpoints"]], ["one"])
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

    def test_rejection_blocks_successors_across_harness_custody_and_history_modes(self):
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
                        before = len(self.evaluated())
                        result, backend = self.execute(script, name=name, native=native,
                            harness=harness, preserve=preserve, policy={"max_repair_attempts": 1})
                        self.assert_stopped_attention(result, backend)
                        one, = result["checkpoints"]
                        self.assertIs(one["review_approved"], False)
                        self.assertIsNone(one["reviewed_head"])
                        self.assertEqual(one["head"], result["reviews"][1]["head"])
                        self.assertEqual(result["loop_flags"][0]["reason"], "repair_limit_reached")
                        # Even a passing independent grade cannot approve a rejected review.
                        self.assertEqual(result["slopcodebench"]["checkpoints"][0]["status"], "passed")
                        self.assertFalse(any(label == "one-fix-2" for label, *_ in backend.calls))
                        manifest = json.loads((self.root / name / "manifest.json").read_text())
                        self.assertEqual(manifest["transport"], backend.transport)
                        self.assertEqual([x["checkpoint"] for x in self.evaluated()[before:]], ["one"])

    def test_default_review_can_exceed_former_cutoff_and_repair_before_progressing(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": [("FINDINGS\n- [P2] Set the required value to 2.", 600_000)],
            "one-fix-1": [edit("one", 2, 1), "Finished."],
            "one-review-2": [("NO_FINDINGS", 600_000)],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
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
            "one-review-1": [("NO_FINDINGS", 600_000)],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
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
            "one-review-1": ["FINDINGS\n- [P2] First attempt remains incorrect."],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
        }, policy={"max_feature_raw": 1000, "max_review_raw": 200})
        self.assert_stopped_attention(result, backend)
        self.assertEqual(result["loop_flags"][0]["reason"], "feature_token_limit")
        self.assertEqual(result["checkpoints"][0]["observed_raw_tokens"], 920)
        self.assertEqual(result["slopcodebench"]["checkpoints"][0]["status"], "failed")

    def test_repeated_rejection_blocks_successors_without_replaying_unchanged_repairs(self):
        result, backend = self.execute({
            "one-implement": [edit("one", 1), "Finished."],
            "one-review-1": ["FINDINGS\n- [P2] The required value must be 2."],
            "one-fix-1": ["No edits were made."],
            "one-review-2": ["FINDINGS\n- [P2] The required value must still be 2."],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
        })
        self.assert_stopped_attention(result, backend)
        flag, = result["loop_flags"]
        self.assertEqual(flag["reason"], "repeated_rejected_tree")
        self.assertIs(flag["review_approved"], False)
        self.assertEqual(flag["rounds"], [1, 2])
        self.assertEqual(result["reviews"][0]["head"], result["reviews"][1]["head"])
        self.assertFalse(any(label == "one-fix-2" for label, *_ in backend.calls))

    def test_incomplete_review_preserves_unknown_approval_and_blocks_successors(self):
        for verdict in ("INCOMPLETE_REVIEW\nMISSING_ONE_EVIDENCE", "Not a verdict"):
            with self.subTest(verdict=verdict):
                result, backend = self.execute({
                    "one-implement": [edit("one", 2), "Finished."],
                    "one-review-1": [verdict],
                    "two-implement": [edit("two", 1), "Finished."],
                    "two-review-1": ["NO_FINDINGS"],
                }, name="incomplete" if verdict.startswith("INCOMPLETE") else "malformed")
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
            "two-review-1": ["NO_FINDINGS"],
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
            "two-review-1": ["NO_FINDINGS"],
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
            return "INCOMPLETE_REVIEW\nNeed evidence."
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
            "one-review-1": ["INCOMPLETE_REVIEW\nNeed evidence."],
            "two-implement": [edit("two", 1), "Finished."],
            "two-review-1": ["NO_FINDINGS"],
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
            "one-review-1": ["INCOMPLETE_REVIEW\nNeed evidence."],
        }, benchmark=benchmark)
        self.assertEqual(result["status"], "needs_attention", result)
        self.assertEqual(result["checkpoints"], [])
        self.assertEqual(result["blocked_features"], ["two"])
        self.assertFalse(any(label.startswith(("two-", "integration-")) for label, *_ in backend.calls))


if __name__ == "__main__":
    unittest.main()
