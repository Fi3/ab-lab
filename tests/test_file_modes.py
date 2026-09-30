import json
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Host, Rejected, snapshot
from lab.host_tools import HostTools
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
        result = HostTools(host).execute("host_edit", {
            "patch": "*** Begin Patch\n" + body + "\n*** End Patch\n",
            "reason": "executable contract"}, f"edit-{len(host.accepted_commits)}")
        self.assertTrue(result["success"], result)
        return result["text"]

    def test_mode_only_update_adds_and_removes_executable_bit_in_commits(self):
        host = self.host()
        original = self.source.read_bytes()
        for target in ("100755", "100644"):
            with self.subTest(mode=target):
                reply = self.edit(host, "*** Update File: source.py\n*** Mode: " + target)
                self.assertIn("Changed files", reply)
                self.assertEqual(self.source.read_bytes(), original)
                self.assertEqual(self.mode(), int(target, 8) & 0o777)
                self.assertTrue(self.git("ls-tree", "HEAD", "source.py").startswith(target.encode()))
                self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(len(host.accepted_commits), 2)

    def test_add_executable_file_commits_requested_mode(self):
        host = self.host()
        reply = self.edit(host, "*** Add File: cli.py\n*** Mode: 100755\n"
                               "+#!/usr/bin/env python3\n+print('hello')")
        self.assertIn("Changed files", reply)
        self.assertEqual(self.mode(self.repo / "cli.py"), 0o755)
        self.assertEqual((self.repo / "cli.py").read_text(), "#!/usr/bin/env python3\nprint('hello')\n")
        self.assertTrue(self.git("ls-tree", "HEAD", "cli.py").startswith(b"100755"))
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_content_and_mode_update_are_one_commit(self):
        host = self.host()
        reply = self.edit(host, "*** Update File: source.py\n*** Mode: 100755\n"
                               "@@\n-first\n+start")
        self.assertIn("Changed files", reply)
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

if __name__ == "__main__":
    unittest.main()
