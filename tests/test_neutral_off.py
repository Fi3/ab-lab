"""Disabled author hints do not impose an opposite policy or edit format."""
import itertools
from hashlib import sha256
from pathlib import Path
import tempfile
import time
import unittest

from lab.config import author_policy, policy_blocks, settings
from lab.host import Host, git, snapshot
from lab.workflow import author_prompt, run
from test_core import repo_at
from test_workflow import FakeCodex


OPTIONAL = ("C13", "C14", "C15", "C16")


class NeutralPolicyTests(unittest.TestCase):
    def test_enabled_instructions_match_pinned_protocol(self):
        # Host protocol includes file-mode publication; native instructions stay unchanged.
        cases = (({}, "e1919918ab08d9c52619121c297927fc4ba962e710f82265194a084294d58ed5"),
                 ({"C08": False, "C17": False, "C25": False},
                  "30b77197f17af01ae6701d6859e93e88bee015b93df6203d7350962e5a27842f"))
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                self.assertEqual(sha256(author_policy(settings(overrides)).encode()).hexdigest(), expected)

    def test_each_disabled_instruction_is_absent_not_replaced(self):
        enabled = policy_blocks(settings({}))
        for key in OPTIONAL:
            with self.subTest(factor=key):
                blocks = policy_blocks(settings({key: False}))
                self.assertEqual(blocks[key], "")
                self.assertEqual({k: v for k, v in blocks.items() if k != key},
                                 {k: v for k, v in enabled.items() if k != key})

    def test_every_combination_preserves_independent_switches(self):
        enabled = policy_blocks(settings({}))
        for values in itertools.product((False, True), repeat=len(OPTIONAL)):
            for native in (False, True):
                changes = dict(zip(OPTIONAL, values))
                if native:
                    changes.update(C08=False, C17=False, C25=False)
                factors = settings(changes)
                blocks = policy_blocks(factors)
                with self.subTest(values=values, native=native):
                    for key in OPTIONAL:
                        self.assertEqual(blocks[key], enabled[key] if factors[key] else "")
                    for key in ("C20", "C38"):
                        self.assertEqual(blocks[key], enabled[key])

    def test_native_all_off_keeps_only_the_execution_contract(self):
        factors = settings(dict.fromkeys(settings({}), False))
        self.assertEqual(author_policy(factors).strip(),
                         "Edit, run checks and create provisional commits yourself with native tools. "
                         "Work only in this checkout; do not create extra worktrees. "
                         "Leave tracked source and the index clean. "
                         "The stage-completion marker is exactly @standalone done.")

    def test_off_preserves_repository_rules_and_required_work_in_repairs(self):
        benchmark = {"instructions": "Repository policy: demonstrate a failing regression test before implementing.",
                     "defer_documentation": True}
        feature = {"id": "sample", "request": "Preserve existing behavior and cover the new behavior."}
        factors = settings({key: False for key in OPTIONAL})
        for findings in (None, "Fix the missing edge-case test."):
            with self.subTest(findings=findings):
                prompt = author_prompt(benchmark, feature, factors, findings)
                self.assertIn(benchmark["instructions"], prompt)
                self.assertIn("Follow repository instructions", prompt)
                self.assertNotIn("This overrides procedural test-timing", prompt)
                self.assertNotIn("This ordering takes precedence", prompt)
                self.assertNotIn("standard unified diff", prompt)
                self.assertNotIn("separate edit operations", prompt)
                self.assertNotIn("Validate the feature broadly", prompt)

    def test_off_host_prompt_does_not_require_an_unspecified_format(self):
        prompt = author_policy(settings({"C16": False}))
        self.assertIn("@standalone edit <reason>\n<patch>\n@standalone end", prompt)
        self.assertNotIn("required format", prompt)
        self.assertNotIn("standard unified diff", prompt)

    def test_all_four_off_preserve_the_complete_review_repair_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            benchmark = {"name": "neutral", "repo": str(repo), "revision": "HEAD", "features": [
                {"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
                "checks": ["test -f one.py && test -f two.py"], "instructions": "",
                "defer_documentation": True}
            result = run(benchmark, settings(dict.fromkeys(OPTIONAL, False)), root / "run",
                         30, 10000, 30, backend=FakeCodex)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual([item["review_rounds"] for item in result["checkpoints"]], [2, 1])
            calls = FakeCodex.instances[-1].calls
            self.assertEqual(list(dict.fromkeys(call[0] for call in calls)),
                             ["one-implement", "one-review-1", "one-fix-1", "one-review-2",
                              "two-implement", "two-review-1", "integration-plan", "integration-accept"])
            for label, _, prompt, _ in calls:
                if label.endswith("-implement") or "-fix-" in label:
                    self.assertNotIn("standard unified diff", prompt)
                    self.assertNotIn("separate edit operations", prompt)
                    self.assertNotIn("Validate the feature broadly", prompt)
            self.assertFalse((repo / "one.py").exists())


class NeutralHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = repo_at(self.root / "repo")

    def host(self, **overrides):
        return Host(self.repo, self.root / "host", "sample", "author", time.monotonic()+30,
                    settings({"C16": False, **overrides}))

    @staticmethod
    def edit(patch):
        return "@standalone edit change text\n" + patch + "\n@standalone end"

    @staticmethod
    def structured(old, new):
        return ("*** Begin Patch\n*** Update File: source.py\n@@\n-" + old +
                "\n+" + new + "\n*** End Patch")

    @staticmethod
    def unified(old, new):
        return ("--- a/source.py\n+++ b/source.py\n@@ -1,3 +1,3 @@\n-" + old +
                "\n+" + new + "\n middle\n last")

    def test_off_accepts_structured_and_unified_edits_in_same_conversation(self):
        host = self.host()
        for patch in (self.structured("first", "next"), self.unified("next", "final")):
            reply = host.consume(self.edit(patch))
            self.assertIn("Host accepted", reply)
        self.assertEqual((self.repo / "source.py").read_text(), "final\nmiddle\nlast\n")
        self.assertEqual(len(host.accepted_commits), 2)
        self.assertEqual(git(self.repo, "status", "--porcelain"), b"")

    def test_off_structured_rejection_is_atomic_and_retry_can_succeed(self):
        host = self.host()
        before = snapshot(self.repo)
        patch = self.structured("first", "next").replace("*** End Patch",
            "*** Update File: missing.py\n@@\n-old\n+new\n*** End Patch")
        self.assertIn("rejected", host.consume(self.edit(patch)))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Host accepted", host.consume(self.edit(self.structured("first", "next"))))

    def test_off_unified_rejection_is_atomic_and_retry_can_succeed(self):
        host = self.host()
        before = snapshot(self.repo)
        patch = self.unified("first", "next").replace("@@ -1,3 +1,3 @@", "@@ -1,99 +1,99 @@")
        self.assertIn("rejected", host.consume(self.edit(patch)))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Host accepted", host.consume(self.edit(self.unified("first", "next"))))

    def test_off_stale_edit_refresh_uses_actual_format_and_preserves_c08(self):
        for compact in (False, True):
            for format_name in ("structured", "unified"):
                with self.subTest(compact=compact, format=format_name):
                    root = self.root / f"{compact}-{format_name}"
                    root.mkdir()
                    repo = repo_at(root / "repo")
                    host = Host(repo, root / "host", "sample", "author", time.monotonic()+30,
                                settings({"C16": False, "C08": compact}))
                    host.consume("@standalone read source.py")
                    (repo / "source.py").write_text("peer\nmiddle\nlast\n")
                    git(repo, "commit", "-qam", "UPDATE peer source")
                    host.expected = snapshot(repo)
                    before = snapshot(repo)
                    make_patch = getattr(self, format_name)
                    reply = host.consume(self.edit(make_patch("first", "next")))
                    self.assertIn("rejected", reply)
                    self.assertEqual(snapshot(repo), before)
                    expected = "+peer" if compact else "Current complete file:\npeer\nmiddle\nlast"
                    self.assertIn(expected, reply)
                    self.assertEqual(host.seen["source.py"], "peer\nmiddle\nlast\n")
                    self.assertIn("Host accepted", host.consume(self.edit(make_patch("peer", "next"))))

    def test_off_keeps_path_safety_for_both_formats(self):
        host = self.host()
        before = snapshot(self.repo)
        for patch in (self.structured("first", "next"), self.unified("first", "next")):
            for unsafe in ("../outside.py", ".git/config"):
                with self.subTest(patch=patch, unsafe=unsafe):
                    self.assertIn("rejected", host.consume(self.edit(patch.replace("source.py", unsafe))))
                    self.assertEqual(snapshot(self.repo), before)
        self.assertFalse((self.root / "outside.py").exists())

    def test_c13_off_omits_post_edit_validation_guidance(self):
        host = self.host(C13=False)
        reply = host.consume(self.edit(self.unified("first", "next")))
        self.assertIn("Host accepted", reply)
        self.assertNotIn("validation step", reply)
        self.assertNotIn("broad", reply)
        self.assertIn("@standalone done", reply)  # C38 stays enabled.

    def test_enabled_format_remains_strict(self):
        host = self.host(C16=True)
        before = snapshot(self.repo)
        self.assertIn("rejected", host.consume(self.edit(self.unified("first", "next"))))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Host accepted", host.consume(self.edit(self.structured("first", "next"))))


if __name__ == "__main__":
    unittest.main()
