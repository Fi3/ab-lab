import json
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Fatal, Host, Rejected, execute_child, snapshot
from test_core import repo_at


class FileModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = repo_at(self.root / "repo")
        self.source = self.repo / "source.py"
        self.source.chmod(0o644)

    def host(self):
        return Host(self.repo, self.root / "host", "feature", "implement",
                    time.monotonic() + 30, settings({}))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args])

    def mode(self, path=None):
        return stat.S_IMODE((path or self.source).stat().st_mode)

    def edit(self, host, body):
        return host.consume("@standalone edit executable contract\n"
                            "*** Begin Patch\n" + body +
                            "\n*** End Patch\n@standalone end")

    def receipt(self, host):
        return json.loads((host.artifacts / "operation-0001" / "receipt.json").read_text())

    def test_mode_only_update_adds_and_removes_executable_bit_in_commits(self):
        host = self.host()
        original = self.source.read_bytes()
        for target in ("100755", "100644"):
            with self.subTest(mode=target):
                reply = self.edit(host, "*** Update File: source.py\n*** Mode: " + target)
                self.assertIn("Host accepted", reply)
                self.assertEqual(self.source.read_bytes(), original)
                self.assertEqual(self.mode(), int(target, 8) & 0o777)
                self.assertTrue(self.git("ls-tree", "HEAD", "source.py").startswith(target.encode()))
                self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(len(host.accepted_commits), 2)

    def test_add_executable_file_commits_requested_mode(self):
        host = self.host()
        reply = self.edit(host, "*** Add File: cli.py\n*** Mode: 100755\n"
                               "+#!/usr/bin/env python3\n+print('hello')")
        self.assertIn("Host accepted", reply)
        self.assertEqual(self.mode(self.repo / "cli.py"), 0o755)
        self.assertEqual((self.repo / "cli.py").read_text(), "#!/usr/bin/env python3\nprint('hello')\n")
        self.assertTrue(self.git("ls-tree", "HEAD", "cli.py").startswith(b"100755"))
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_content_and_mode_update_are_one_commit(self):
        host = self.host()
        reply = self.edit(host, "*** Update File: source.py\n*** Mode: 100755\n"
                               "@@\n-first\n+start")
        self.assertIn("Host accepted", reply)
        self.assertEqual(self.source.read_text(), "start\nmiddle\nlast\n")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(len(host.accepted_commits), 1)
        self.assertEqual(self.git("show", "HEAD:source.py"), self.source.read_bytes())
        self.assertTrue(self.git("ls-tree", "HEAD", "source.py").startswith(b"100755"))

    def test_invalid_or_duplicate_modes_reject_entire_patch_atomically(self):
        host = self.host()
        before = snapshot(self.repo)
        invalid_sections = [
            "*** Add File: new.py\n*** Mode: " + mode + "\n+new"
            for mode in ("755", "0755", "100600", "100700", "120000", "100777", "100755 extra")
        ]
        invalid_sections += [
            "*** Add File: new.py\n*** Mode: 100755\n*** Mode: 100644\n+new",
            "*** Add File: new.py\n*** Mode: 100755\n*** Mode: 100755\n+new",
            "*** Add File: new.py\n+new\n*** Mode: 100755",
            "*** Delete File: source.py\n*** Mode: 100644",
        ]
        for section in invalid_sections:
            with self.subTest(section=section):
                proposal = ("*** Begin Patch\n*** Add File: first.py\n+first\n" +
                            section + "\n*** End Patch")
                with self.assertRaises(Rejected):
                    host.apply("invalid mode", proposal)
                self.assertEqual(snapshot(self.repo), before)
                self.assertFalse((self.repo / "first.py").exists())
                self.assertFalse((self.repo / "new.py").exists())
        self.assertEqual(host.accepted_commits, [])

    def test_declared_chmod_is_pending_until_explicit_mode_edit(self):
        host = self.host()
        before = snapshot(self.repo)
        reply = host.consume("@standalone run source.py -- chmod 755 source.py")
        self.assertIn("pending", reply.lower())
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(host.pending_changes, ["source.py"])
        self.assertEqual(host.pending["source.py"]["after"][2], 0o755)
        self.assertIn("DONE rejected", host.consume("@standalone done"))
        self.assertIn("Host accepted", self.edit(host, "*** Update File: source.py\n*** Mode: 100755"))
        self.assertEqual(host.pending_changes, [])
        self.assertEqual(self.mode(), 0o755)
        self.assertIsNone(host.consume("@standalone done"))

    def test_undeclared_chmod_recovers_with_receipt_and_requires_publication(self):
        host = self.host()
        before = snapshot(self.repo)
        reply = host.consume("@standalone run -- chmod +x source.py")
        self.assertIn("pending", reply.lower())
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(host.accepted_commits, [])
        self.assertEqual(host.pending_changes, ["source.py"])
        self.assertEqual(host.pending["source.py"]["after"][2], 0o755)
        self.assertIn("DONE rejected", host.consume("@standalone done"))
        self.assertFalse(host.completed)
        receipt = self.receipt(host)
        self.assertEqual(receipt["recovered_mode_paths"], ["source.py"])
        self.assertIn("source change outside declared paths: source.py", receipt["custody_errors"])
        self.assertEqual(receipt["before"]["files"]["source.py"]["mode"], 0o644)
        self.assertEqual(receipt["after"]["files"]["source.py"]["mode"], 0o755)
        identity = json.loads((host.artifacts / "operation-0001" / "pending" / "0" / "identity.json").read_text())
        self.assertEqual((identity["before_mode"], identity["after_mode"]), (0o644, 0o755))
        self.assertIn("Host accepted", self.edit(host, "*** Update File: source.py\n*** Mode: 100755"))
        self.assertEqual(host.pending_changes, [])
        self.assertEqual(len(host.accepted_commits), 1)
        self.assertTrue(self.git("ls-tree", "HEAD", "source.py").startswith(b"100755"))
        self.assertIsNone(host.consume("@standalone done"))

    def test_recovered_executable_removal_can_be_discarded(self):
        self.source.chmod(0o755)
        self.git("add", "source.py")
        self.git("commit", "-qm", "executable base")
        host = self.host()
        before = snapshot(self.repo)
        host.consume("@standalone run -- chmod -x source.py")
        self.assertEqual(snapshot(self.repo), before)
        self.assertEqual(host.pending["source.py"]["after"][2], 0o644)
        self.assertIn("DONE rejected", host.consume("@standalone done"))
        host.consume("@standalone discard executable bit is required")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(host.pending_changes, [])
        self.assertEqual(host.accepted_commits, [])
        self.assertIsNone(host.consume("@standalone done"))

    def test_undeclared_content_change_still_fails_and_preserves_evidence(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "source change outside declared paths"):
            host.consume("@standalone run -- printf 'changed\\n' > source.py")
        self.assertEqual(self.source.read_bytes(), b"changed\n")
        self.assertEqual(self.receipt(host)["pending_paths"], ["source.py"])
        self.assertEqual(host.pending_changes, [])

    def test_undeclared_combined_content_and_mode_change_still_fails(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "source change outside declared paths"):
            host.consume("@standalone run -- printf 'changed\\n' > source.py && chmod 755 source.py")
        self.assertEqual(self.source.read_bytes(), b"changed\n")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(host.pending_changes, [])

    def test_declared_content_change_does_not_allow_undeclared_mode_recovery(self):
        other = self.repo / "other.py"
        other.write_text("original\n")
        self.git("add", "other.py")
        self.git("commit", "-qm", "second source")
        host = self.host()
        with self.assertRaisesRegex(Fatal, "source change outside declared paths"):
            host.consume("@standalone run other.py -- printf 'changed\\n' > other.py && chmod 755 source.py")
        self.assertEqual(other.read_bytes(), b"changed\n")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(host.pending_changes, [])

    def test_undeclared_nonexecutable_permissions_still_fail(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "source change outside declared paths"):
            host.consume("@standalone run -- chmod 600 source.py")
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(host.pending_changes, [])

    def test_mode_and_index_change_still_fail(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "command changed HEAD or index"):
            host.consume("@standalone run -- chmod 755 source.py && git add source.py")
        self.assertEqual(self.mode(), 0o755)
        self.assertTrue(self.git("ls-files", "--stage", "source.py").startswith(b"100755"))
        self.assertEqual(host.pending_changes, [])

    def test_mode_and_index_flags_change_still_fail(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "command changed HEAD or index"):
            host.consume("@standalone run -- chmod 755 source.py && git update-index --assume-unchanged source.py")
        self.assertEqual(self.mode(), 0o755)
        self.assertTrue(self.git("ls-files", "-v", "source.py").startswith(b"h "))
        self.assertEqual(host.pending_changes, [])

    def test_mode_and_untracked_source_change_still_fail(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "command created nonignored untracked source"):
            host.consume("@standalone run -- chmod 755 source.py && printf 'new\\n' > new.py")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual((self.repo / "new.py").read_bytes(), b"new\n")
        self.assertEqual(host.pending_changes, [])

    def test_undeclared_symlink_replacement_still_fails(self):
        host = self.host()
        with self.assertRaisesRegex(Fatal, "nonregular changed source"):
            host.consume("@standalone run -- rm source.py && ln -s missing.py source.py")
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(host.pending_changes, [])

    def test_timed_out_undeclared_chmod_is_not_recovered(self):
        host = self.host()
        with patch("lab.host.COMMAND_SECONDS", 0.1):
            with self.assertRaises(Fatal):
                host.consume("@standalone run -- chmod 755 source.py && sleep 5")
        self.assertEqual(self.mode(), 0o755)
        self.assertTrue(self.receipt(host)["timed_out"])
        self.assertEqual(host.pending_changes, [])

    def test_unsuccessful_undeclared_chmod_is_not_recovered(self):
        host = self.host()
        with self.assertRaises(Fatal):
            host.consume("@standalone run -- chmod 755 source.py && exit 1")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(self.receipt(host)["exit_code"], 1)
        self.assertEqual(host.pending_changes, [])

    def test_cancelled_command_receipt_prevents_mode_recovery(self):
        host = self.host()

        def cancelled_child(*args, **kwargs):
            receipt = execute_child(*args, **kwargs)
            receipt["cancelled_signal"] = 15
            return receipt

        with patch("lab.host.execute_child", side_effect=cancelled_child):
            with self.assertRaises(Fatal):
                host.consume("@standalone run -- chmod 755 source.py")
        self.assertEqual(self.mode(), 0o755)
        self.assertEqual(self.receipt(host)["cancelled_signal"], 15)
        self.assertEqual(host.pending_changes, [])


if __name__ == "__main__":
    unittest.main()
