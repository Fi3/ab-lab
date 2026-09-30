"""Native tools preserve actual effects and never repeat uncertain operations."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Fatal, Host, git, snapshot
from lab.host_tools import HOST_TOOLS, HostTools, _record
from test_core import repo_at


class HostToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = repo_at(self.root / "repo")
        self.host = Host(self.repo, self.root / "host", "feature", "implement",
                         time.monotonic() + 30, settings({}))
        self.tools = HostTools(self.host)

    def folder(self, call_id):
        return self.tools.artifacts / ("call-" + hashlib.sha256(call_id.encode()).hexdigest())

    def run_command(self, command, call_id="run"):
        return self.tools.execute("host_run", {"command": command}, call_id)

    def assert_clean(self):
        self.assertEqual(git(self.repo, "status", "--porcelain"), b"")
        self.host.unchanged()

    def test_tools_have_only_actual_inputs_and_no_completion_protocol(self):
        self.assertEqual([item["name"] for item in HOST_TOOLS], ["host_read", "host_edit", "host_run"])
        schemas = {item["name"]: item["inputSchema"] for item in HOST_TOOLS}
        self.assertEqual(set(schemas["host_run"]["properties"]), {"command"})
        self.assertEqual(set(schemas["host_edit"]["properties"]), {"patch", "reason"})
        self.assertTrue(all(schema["additionalProperties"] is False for schema in schemas.values()))

    def test_terminal_newline_patch_from_failed_run_is_accepted(self):
        for number, newline in enumerate(("\n", "\r\n")):
            patch_text = newline.join(["*** Begin Patch", f"*** Add File: requirements-{number}.txt",
                                      "+tree-sitter==0.25.2", "*** End Patch", ""])
            result = self.tools.execute("host_edit", {"patch": patch_text}, f"patch-{number}")
            self.assertTrue(result["success"], result)
            self.assertEqual((self.repo / f"requirements-{number}.txt").read_text(), "tree-sitter==0.25.2\n")
        self.assertEqual(len(self.host.accepted_commits), 2)
        self.assert_clean()

    def test_empty_add_file_is_zero_bytes_and_plus_line_is_one_newline(self):
        result = self.tools.execute("host_edit", {"patch":
            "*** Begin Patch\n*** Add File: empty.txt\n*** Add File: blank.txt\n+\n*** End Patch\n"}, "empty-and-blank")
        self.assertTrue(result["success"], result)
        self.assertEqual(git(self.repo, "show", "HEAD:empty.txt"), b"")
        self.assertEqual(git(self.repo, "show", "HEAD:blank.txt"), b"\n")
        self.assert_clean()

    def test_empty_add_with_mode_and_mixed_patch_is_one_atomic_commit(self):
        result = self.tools.execute("host_edit", {"patch":
            "*** Begin Patch\n*** Add File: before.py\n+before\n"
            "*** Add File: empty.sh\n*** Mode: 100755\n"
            "*** Update File: source.py\n@@\n-first\n+changed\n"
            "*** Add File: after.py\n+after\n*** Add File: last.txt\n*** End Patch\n"}, "mixed-empty")
        self.assertTrue(result["success"], result)
        self.assertEqual(git(self.repo, "show", "HEAD:empty.sh"), b"")
        self.assertTrue(git(self.repo, "ls-tree", "HEAD", "empty.sh").startswith(b"100755"))
        self.assertEqual(git(self.repo, "show", "HEAD:last.txt"), b"")
        self.assertEqual(git(self.repo, "show", "HEAD:before.py"), b"before\n")
        self.assertEqual(git(self.repo, "show", "HEAD:after.py"), b"after\n")
        self.assertEqual(git(self.repo, "show", "HEAD:source.py"), b"changed\nmiddle\nlast\n")
        self.assertEqual(len(self.host.accepted_commits), 1)
        self.assert_clean()

    def test_insert_into_empty_file_requires_no_old_context(self):
        self.assertTrue(self.run_command("touch empty.txt", "empty-base")["success"])
        result = self.tools.execute("host_edit", {"patch":
            "*** Begin Patch\n*** Update File: empty.txt\n@@\n+first\n+second\n*** End Patch\n"}, "fill-empty")
        self.assertTrue(result["success"], result)
        self.assertEqual(git(self.repo, "show", "HEAD:empty.txt"), b"first\nsecond\n")
        before = snapshot(self.repo)
        result = self.tools.execute("host_edit", {"patch":
            "*** Begin Patch\n*** Update File: empty.txt\n@@\n+ambiguous\n*** End Patch\n"}, "nonempty-contextless")
        self.assertFalse(result["success"], result)
        self.assertEqual(snapshot(self.repo), before)
        self.assert_clean()

    def test_edit_reason_accepts_multiline_cr_and_empty_text(self):
        for number, reason in enumerate(("Summary\n\nBody", "Summary\rBody", "Summary\r\n\r\nBody", "")):
            with self.subTest(reason=reason):
                arguments = {"patch": f"*** Begin Patch\n*** Add File: reason-{number}.txt\n+content\n*** End Patch\n", "reason": reason}
                result = self.tools.execute("host_edit", arguments, f"reason-{number}")
                self.assertTrue(result["success"], result)
                message = git(self.repo, "log", "-1", "--format=%B").decode()
                self.assertTrue(message.startswith("UPDATE feature:"), message)
                if reason:
                    self.assertIn("Summary", message)
                    self.assertIn("Body", message)
                receipt = json.loads((self.host.artifacts / f"operation-{number + 1:04d}/receipt.json").read_text())
                self.assertEqual(receipt["reason"], reason)
                request = json.loads((self.folder(f"reason-{number}") / "request.json").read_text())
                self.assertEqual(request["arguments"], arguments)
                self.assert_clean()

    def test_empty_or_whitespace_shell_command_is_a_valid_noop(self):
        before = snapshot(self.repo)
        for number, command in enumerate(("", " \t\n")):
            result = self.run_command(command, f"noop-{number}")
            self.assertTrue(result["success"], result)
            self.assertEqual(snapshot(self.repo), before)
            receipt = json.loads((self.folder(f"noop-{number}") / "receipt.json").read_text())
            self.assertEqual(receipt["command"], command)
            self.assertEqual(receipt["exit_code"], 0)
        self.assertEqual(self.host.accepted_commits, [])

    def test_schema_and_text_safety_checks_remain_recoverable(self):
        before = snapshot(self.repo)
        cases = [("host_edit", {}), ("host_edit", {"patch": "", "reason": "ok"}),
                 ("host_edit", {"patch": "", "reason": None}), ("host_read", {"path": ""}),
                 ("host_read", {"path": "../outside"}), ("host_run", {"command": "true", "paths": []}),
                 ("host_run", {"command": "true\x00"}), ("host_run", {"command": "\ud800"}),
                 ("host_edit", {"patch": "", "reason": "invalid\x00"})]
        for number, (name, arguments) in enumerate(cases):
            result = self.tools.execute(name, arguments, f"schema-{number}")
            self.assertFalse(result["success"], result)
            self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(self.tools.unfinished_calls(), [])

    def test_new_source_command_is_committed_without_predicted_paths(self):
        result = self.run_command("touch requirements.txt")
        self.assertTrue(result["success"], result)
        self.assertEqual(git(self.repo, "show", "HEAD:requirements.txt"), b"")
        receipt = json.loads((self.folder("run") / "receipt.json").read_text())
        self.assertEqual(receipt["changed_paths"], ["requirements.txt"])
        self.assertEqual(len(self.host.accepted_commits), 1)
        self.assert_clean()

    def test_command_records_created_deleted_modified_files_and_modes(self):
        result = self.run_command("mkdir nested; printf 'new\\n' > nested/cli.py; chmod 755 nested/cli.py; rm source.py")
        self.assertTrue(result["success"], result)
        receipt = json.loads((self.folder("run") / "receipt.json").read_text())
        self.assertEqual(set(receipt["changed_paths"]), {"source.py", "nested/cli.py"})
        self.assertFalse((self.repo / "source.py").exists())
        self.assertTrue(git(self.repo, "ls-tree", "HEAD", "nested/cli.py").startswith(b"100755"))
        self.assertEqual((self.folder("run") / "changes/0/before").read_bytes(), b"first\nmiddle\nlast\n")
        self.assert_clean()

    def test_unsuccessful_command_retains_and_commits_partial_work(self):
        result = self.run_command("printf 'partial\\n' > source.py; printf 'new\\n' > new.py; exit 7")
        self.assertFalse(result["success"])
        self.assertIn("Exit code: 7", result["text"])
        self.assertEqual(git(self.repo, "show", "HEAD:source.py"), b"partial\n")
        self.assertEqual(git(self.repo, "show", "HEAD:new.py"), b"new\n")
        self.assertTrue(self.tools.execute("host_read", {"path": "new.py"}, "inspect")["success"])
        self.assert_clean()

    def test_timed_out_command_retains_partial_work_and_allows_repair(self):
        with patch("lab.host_tools.COMMAND_SECONDS", 0.05):
            result = self.run_command("printf 'partial\\n' > source.py; sleep 5")
        self.assertFalse(result["success"])
        self.assertIn("timed out: True", result["text"])
        self.assertEqual(git(self.repo, "show", "HEAD:source.py"), b"partial\n")
        self.assertTrue(self.run_command("printf 'repaired\\n' > source.py", "repair")["success"])
        self.assert_clean()

    def test_non_git_permission_change_is_preserved_in_receipt(self):
        result = self.run_command("chmod 600 source.py")
        self.assertTrue(result["success"], result)
        self.assertEqual((self.repo / "source.py").stat().st_mode & 0o777, 0o600)
        identity = json.loads((self.folder("run") / "changes/0/identity.json").read_text())
        self.assertEqual((identity["before_mode"], identity["after_mode"]), (0o644, 0o600))
        self.assertEqual(self.host.accepted_commits, [])
        self.assert_clean()

    def test_ignored_build_artifacts_remain_ignored(self):
        # Initial setup is a fixture change, before the tool's next operation.
        (self.repo / ".gitignore").write_text("build/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore builds")
        self.host.expected = snapshot(self.repo)
        result = self.run_command("mkdir build; printf 'compiled' > build/result")
        self.assertTrue(result["success"], result)
        self.assertEqual((self.repo / "build/result").read_text(), "compiled")
        self.assertEqual(self.host.accepted_commits, [])
        self.assert_clean()

    def test_duplicate_call_returns_recorded_result_without_repeating_effects(self):
        arguments = {"command": "printf 'once\\n' >> source.py"}
        original = self.tools.execute("host_run", arguments, "duplicate")
        again = HostTools(self.host).execute("host_run", arguments, "duplicate")
        self.assertEqual(again, original)
        self.assertEqual((self.repo / "source.py").read_text().count("once"), 1)
        self.assertEqual(len(self.host.accepted_commits), 1)
        self.assert_clean()

    def test_call_identity_collision_executes_nothing(self):
        self.run_command("printf 'once\\n' >> source.py", "identity")
        before = snapshot(self.repo)
        with self.assertRaisesRegex(Fatal, "identity collision"):
            self.run_command("printf 'twice\\n' >> source.py", "identity")
        self.assertEqual(snapshot(self.repo), before)

    def test_interruption_after_commit_never_blindly_replays_command(self):
        def interrupt_result(path, value):
            if path.name == "result.json":
                raise KeyboardInterrupt("lost before response receipt")
            return _record(path, value)

        with patch("lab.host_tools._record", side_effect=interrupt_result):
            with self.assertRaises(KeyboardInterrupt):
                self.run_command("printf 'once\\n' >> source.py", "interrupted")
        self.assertEqual(len(self.host.accepted_commits), 1)
        unfinished = HostTools(self.host).unfinished_calls()
        self.assertEqual(unfinished[0]["state"], "interrupted")
        self.assertEqual(unfinished[0]["call_id"], "interrupted")
        for call_id in ("interrupted", "next"):
            with self.assertRaisesRegex(Fatal, "unfinished|unresolved"):
                self.run_command("printf 'once\\n' >> source.py", call_id)
        self.assertEqual((self.repo / "source.py").read_text().count("once"), 1)

    def test_partial_edit_publication_failure_retains_work_and_blocks_replay(self):
        from lab.host import git as real_git
        def fail_commit(repo, *args):
            if args[0] == "commit":
                raise Fatal("injected commit failure")
            return real_git(repo, *args)
        arguments = {"patch": "*** Begin Patch\n*** Add File: new.py\n+retained\n*** End Patch\n"}
        with patch("lab.host.git", side_effect=fail_commit):
            with self.assertRaisesRegex(Fatal, "injected"):
                self.tools.execute("host_edit", arguments, "partial-edit")
        self.assertEqual((self.repo / "new.py").read_text(), "retained\n")
        self.assertIn(b"A  new.py", git(self.repo, "status", "--porcelain"))
        self.assertEqual(self.tools.unfinished_calls()[0]["state"], "failed")
        with self.assertRaisesRegex(Fatal, "unfinished"):
            self.tools.execute("host_edit", arguments, "partial-edit")

    def test_invalid_arguments_and_patch_are_recoverable_without_mutation(self):
        before = snapshot(self.repo)
        cases = [("unknown", {}), ("host_run", {"command": "touch unwanted", "paths": []}),
                 ("host_run", []), ("host_read", {"path": 7}),
                 ("host_edit", {"patch": "*** Begin Patch\n*** Add File: new.py\n+new\n*** End Patch\nJUNK"})]
        for index, (name, arguments) in enumerate(cases):
            result = self.tools.execute(name, arguments, f"invalid-{index}")
            self.assertFalse(result["success"], result)
            self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(self.tools.unfinished_calls(), [])
        self.assertTrue(self.run_command("true", "continue")["success"])

    def test_index_mutation_is_fatal_and_preserves_actual_state(self):
        with self.assertRaisesRegex(Fatal, "HEAD or index"):
            self.run_command("chmod 755 source.py; git add source.py")
        self.assertTrue(git(self.repo, "ls-files", "--stage", "source.py").startswith(b"100755"))
        self.assertTrue((self.folder("run") / "process.json").exists())
        self.assertEqual(self.tools.unfinished_calls()[0]["state"], "failed")

    def test_index_flags_cannot_hide_source_changes(self):
        with self.assertRaisesRegex(Fatal, "HEAD or index"):
            self.run_command("git update-index --assume-unchanged source.py; printf 'hidden' > source.py")
        self.assertEqual((self.repo / "source.py").read_text(), "hidden")
        self.assertTrue(git(self.repo, "ls-files", "-v", "source.py").startswith(b"h "))

    def test_nonregular_source_change_is_fatal_and_retained(self):
        with self.assertRaisesRegex(Fatal, "nonregular source"):
            self.run_command("rm source.py; ln -s missing.py source.py")
        self.assertTrue((self.repo / "source.py").is_symlink())
        self.assertEqual(self.tools.unfinished_calls()[0]["state"], "failed")

    def test_external_source_change_is_not_silently_accepted(self):
        (self.repo / "source.py").write_text("external")
        with self.assertRaisesRegex(Fatal, "unexpected source"):
            self.run_command("printf 'should not run' > other.py")
        self.assertFalse((self.repo / "other.py").exists())
        self.assertEqual((self.repo / "source.py").read_text(), "external")

    def test_whitespace_filename_is_read_as_a_literal_argument(self):
        (self.repo / " ").write_text("space")
        git(self.repo, "add", "--", " ")
        git(self.repo, "commit", "-qm", "space filename")
        self.host.expected = snapshot(self.repo)
        result = self.tools.execute("host_read", {"path": " "}, "space")
        self.assertTrue(result["success"], result)
        self.assertTrue(result["text"].endswith("space"))

    def test_factor_feedback_has_no_completion_markers(self):
        result = self.run_command("true")
        self.assertNotIn("@standalone", result["text"])
        self.assertIn("finish with a concise summary", result["text"])
        self.assertEqual(self.host.activations["C20"], 1)


if __name__ == "__main__":
    unittest.main()
