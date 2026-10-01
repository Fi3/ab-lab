"""Structured review submission binds approval to a round and checkout head."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from lab.review import REVIEW_TOOLS, ReviewTools, validate_review
from lab.host import git, snapshot
from test_core import repo_at
from test_workflow import verdict


class ReviewToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifacts = Path(temporary.name) / "reviews"
        self.tools = ReviewTools(self.artifacts)
        self.target = self.tools.begin("one-review-1", "head-one")

    def submit(self, value, target=None):
        return self.tools.execute("submit_review", {"review_id": target or self.target, **value}, "call")

    def test_invalid_call_is_recoverable_then_corrected_verdict_is_recorded(self):
        self.assertFalse(self.submit(verdict("Broken", "P7"))["success"])
        self.assertIsNone(self.tools.decision)
        self.assertEqual(list(self.artifacts.iterdir()), [])
        self.assertTrue(self.submit(verdict("Broken", "P1"))["success"])
        self.assertFalse(self.tools.decision["approved"])
        receipt = json.loads(self.tools.receipt.read_text())
        self.assertEqual(receipt["decision"], self.tools.decision)
        self.assertEqual(receipt["arguments"]["review_id"], self.target)

    def test_previous_round_cannot_approve_new_round_even_for_same_head(self):
        self.assertTrue(self.submit(verdict())["success"])
        old_target = self.target
        self.target = self.tools.begin("one-review-2", "head-one")
        self.assertIsNone(self.tools.decision)
        self.assertFalse(self.submit(verdict(), old_target)["success"])
        self.assertIsNone(self.tools.decision)
        self.assertTrue(self.submit(verdict("Still broken"))["success"])
        self.assertFalse(self.tools.decision["approved"])

    def test_verdict_cannot_be_replaced_but_exact_retry_is_idempotent(self):
        value = verdict("Required fix")
        self.assertTrue(self.submit(value)["success"])
        self.assertTrue(self.submit(value)["success"])
        self.assertFalse(self.submit(verdict())["success"])
        self.assertFalse(self.tools.decision["approved"])
        value["findings"][0]["text"] = "Caller changed arguments"
        self.assertEqual(self.tools.decision["blocking_findings"][0]["text"], "Required fix")

    def test_incomplete_review_retains_supported_findings_and_never_approves(self):
        value = verdict("Concrete failure", incomplete_reason="Cannot reproduce on target platform")
        self.assertTrue(self.submit(value)["success"])
        self.assertIsNone(self.tools.decision["approved"])
        self.assertEqual(len(self.tools.decision["blocking_findings"]), 1)
        self.assertIn("target platform", self.tools.decision["incomplete_reason"])

    def test_tool_schema_and_runtime_require_same_top_level_fields(self):
        arguments = {"review_id": self.target, **verdict()}
        self.assertEqual(set(REVIEW_TOOLS[0]["inputSchema"]["required"]), set(arguments))
        for name in arguments:
            malformed = dict(arguments)
            del malformed[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_review(malformed, self.target)
        with self.assertRaises(ValueError):
            validate_review({**arguments, "approved": True}, self.target)

    def test_arbitrary_json_shapes_are_rejected_without_tool_failure(self):
        for value in (None, True, [], "NO_FINDINGS", {}, {"review_id": self.target}):
            with self.subTest(value=value):
                response = self.tools.execute("submit_review", value, "invalid")
                self.assertFalse(response["success"])
                self.assertIsNone(self.tools.decision)
        for field, value in (("status", []), ("status", {}), ("findings", None),
                             ("findings", [None]), ("findings", [{"priority": [], "text": "x"}]),
                             ("incomplete_reason", True)):
            arguments = {"review_id": self.target, **verdict(), field: value}
            with self.subTest(field=field, value=value):
                self.assertFalse(self.tools.execute("submit_review", arguments, "invalid")["success"])
                self.assertIsNone(self.tools.decision)


class ReviewCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = repo_at(self.root / "submission")
        self.before = snapshot(self.repo)
        self.tools = ReviewTools(self.root / "reviews", repo=self.repo,
                                 deadline=time.monotonic() + 30,
                                 command_argv=lambda checkout, argv: argv)
        self.tools.begin("one-review-1", self.before["head"])

    def test_build_and_temporary_tests_run_in_private_copy_without_original_changes(self):
        response = self.tools.execute("review_run", {"command":
            "mkdir build && printf output > build/result && test -f source.py && test -d .git && printf tested"}, "build")
        self.assertTrue(response["success"], response)
        self.assertIn("tested", response["text"])
        self.assertEqual(snapshot(self.repo), self.before)
        self.assertFalse((self.repo / "build").exists())
        self.assertIn('"source_changed": false', response["text"])
        # Each verification starts from the immutable reviewed commit.
        clean = self.tools.execute("review_run", {"command": "test ! -e build"}, "next")
        self.assertTrue(clean["success"], clean)

    def test_changing_tracked_source_invalidates_check_and_preserves_submission(self):
        response = self.tools.execute("review_run", {"command": "printf weakened > source.py"}, "change")
        self.assertFalse(response["success"])
        self.assertIn("Verification is invalid", response["text"])
        self.assertIn('"source_changed": true', response["text"])
        self.assertEqual(snapshot(self.repo), self.before)

    def test_failed_check_is_reported_as_failed_and_repeated_call_reuses_receipt(self):
        response = self.tools.execute("review_run", {"command": "printf failure >&2; exit 7"}, "failed")
        self.assertFalse(response["success"])
        self.assertIn('"exit_code": 7', response["text"])
        self.assertIn("failure", response["text"])
        self.tools.command_argv = lambda *_: self.fail("a retry must not execute again")
        self.assertEqual(response, self.tools.execute("review_run", {"command": "printf failure >&2; exit 7"}, "failed"))
        self.assertFalse(self.tools.execute("review_run", {"command": "true"}, "failed")["success"])

    def test_tracked_symlink_retargeting_invalidates_verification(self):
        (self.repo / "linked.py").symlink_to("source.py")
        git(self.repo, "add", "linked.py")
        git(self.repo, "commit", "-qm", "Add source alias")
        self.before = snapshot(self.repo)
        self.tools.begin("symlink-review-1", self.before["head"])
        response = self.tools.execute("review_run", {
            "command": "rm linked.py && ln -s weakened.py linked.py && printf weakened > weakened.py"
        }, "retarget")
        self.assertFalse(response["success"], response)
        self.assertIn('"source_changed": true', response["text"])
        self.assertEqual((self.repo / "linked.py").readlink(), Path("source.py"))
        self.assertEqual(snapshot(self.repo), self.before)

    def test_changed_head_retries_return_refusal_without_replaying(self):
        git(self.repo, "commit", "--allow-empty", "-qm", "New review target")
        self.tools.command_argv = lambda *_: self.fail("stale reviews cannot execute commands")
        for _ in range(2):
            response = self.tools.execute("review_run", {"command": "true"}, "stale")
            self.assertFalse(response["success"])
            self.assertIn("submission changed", response["text"])

    def test_unfinished_command_journal_is_reported_without_replaying(self):
        for state in ("no-request", "request-only", "partial-result"):
            folder = self.tools.artifacts / (self.tools.label + "-commands") / hashlib.sha256(state.encode()).hexdigest()
            folder.mkdir(parents=True)
            request = {"review_id": self.tools.review_id, "command": "true", "call_id": state}
            if state != "no-request":
                (folder / "request.json").write_text(json.dumps(request))
            if state == "partial-result":
                (folder / "result.json").write_text('{"success":')
            self.tools.command_argv = lambda *_: self.fail("unfinished commands cannot be replayed")
            with self.subTest(state=state):
                response = self.tools.execute("review_run", {"command": "true"}, state)
                self.assertFalse(response["success"])
                self.assertIn("incomplete", response["text"])
                self.assertIn("not executed again", response["text"])

    def test_command_is_unavailable_after_review_submission(self):
        accepted = self.tools.execute("submit_review", {"review_id": self.tools.review_id, **verdict()}, "submit")
        self.assertTrue(accepted["success"])
        self.assertFalse(self.tools.execute("review_run", {"command": "true"}, "late")["success"])


if __name__ == "__main__":
    unittest.main()
