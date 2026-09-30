"""Disabled author hints do not impose an opposite policy or edit format."""
from pathlib import Path
import tempfile
import time
import unittest

from lab.config import settings
from lab.host import Host, git, snapshot
from lab.host_tools import HostTools
from test_core import repo_at


OPTIONAL = ("C13", "C14", "C15", "C16")


class NeutralHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = repo_at(self.root / "repo")

    def host(self, **overrides):
        return Host(self.repo, self.root / "host", "sample", "author", time.monotonic()+30,
                    settings({"C16": False, **overrides}))

    def execute(self, host, arguments):
        number = len(list((host.artifacts / "tools").glob("call-*"))) if (host.artifacts / "tools").exists() else 0
        result = HostTools(host).execute("host_edit", arguments, f"edit-{number}")
        return result["text"] if result["success"] else "ERROR: " + result["text"]

    @staticmethod
    def edit(patch):
        return {"patch": patch, "reason": "change text"}

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
            reply = self.execute(host, self.edit(patch))
            self.assertIn("Changed files", reply)
        self.assertEqual((self.repo / "source.py").read_text(), "final\nmiddle\nlast\n")
        self.assertEqual(len(host.accepted_commits), 2)
        self.assertEqual(git(self.repo, "status", "--porcelain"), b"")

    def test_off_structured_rejection_is_atomic_and_retry_can_succeed(self):
        host = self.host()
        before = snapshot(self.repo)
        patch = self.structured("first", "next").replace("*** End Patch",
            "*** Update File: missing.py\n@@\n-old\n+new\n*** End Patch")
        self.assertIn("ERROR:", self.execute(host, self.edit(patch)))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Changed files", self.execute(host, self.edit(self.structured("first", "next"))))

    def test_off_unified_rejection_is_atomic_and_retry_can_succeed(self):
        host = self.host()
        before = snapshot(self.repo)
        patch = self.unified("first", "next").replace("@@ -1,3 +1,3 @@", "@@ -1,99 +1,99 @@")
        self.assertIn("ERROR:", self.execute(host, self.edit(patch)))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Changed files", self.execute(host, self.edit(self.unified("first", "next"))))

    def test_off_stale_edit_refresh_uses_actual_format_and_preserves_c08(self):
        for compact in (False, True):
            for format_name in ("structured", "unified"):
                with self.subTest(compact=compact, format=format_name):
                    root = self.root / f"{compact}-{format_name}"
                    root.mkdir()
                    repo = repo_at(root / "repo")
                    host = Host(repo, root / "host", "sample", "author", time.monotonic()+30,
                                settings({"C16": False, "C08": compact}))
                    HostTools(host).execute("host_read", {"path": "source.py"}, "read")
                    (repo / "source.py").write_text("peer\nmiddle\nlast\n")
                    git(repo, "commit", "-qam", "UPDATE peer source")
                    host.expected = snapshot(repo)
                    before = snapshot(repo)
                    make_patch = getattr(self, format_name)
                    reply = self.execute(host, self.edit(make_patch("first", "next")))
                    self.assertIn("ERROR:", reply)
                    self.assertEqual(snapshot(repo), before)
                    expected = "+peer" if compact else "Current complete file:\npeer\nmiddle\nlast"
                    self.assertIn(expected, reply)
                    self.assertEqual(host.seen["source.py"], "peer\nmiddle\nlast\n")
                    self.assertIn("Changed files", self.execute(host, self.edit(make_patch("peer", "next"))))

    def test_off_keeps_path_safety_for_both_formats(self):
        host = self.host()
        before = snapshot(self.repo)
        for patch in (self.structured("first", "next"), self.unified("first", "next")):
            for unsafe in ("../outside.py", ".git/config"):
                with self.subTest(patch=patch, unsafe=unsafe):
                    self.assertIn("ERROR:", self.execute(host, self.edit(patch.replace("source.py", unsafe))))
                    self.assertEqual(snapshot(self.repo), before)
        self.assertFalse((self.root / "outside.py").exists())

    def test_c13_off_omits_post_edit_validation_guidance(self):
        host = self.host(C13=False)
        reply = self.execute(host, self.edit(self.unified("first", "next")))
        self.assertIn("Changed files", reply)
        self.assertNotIn("validation step", reply)
        self.assertNotIn("broad", reply)
        self.assertIn("finish with a concise summary", reply)  # C38 stays enabled.

    def test_enabled_format_remains_strict(self):
        host = self.host(C16=True)
        before = snapshot(self.repo)
        self.assertIn("ERROR:", self.execute(host, self.edit(self.unified("first", "next"))))
        self.assertEqual(snapshot(self.repo), before)
        self.assertIn("Changed files", self.execute(host, self.edit(self.structured("first", "next"))))


if __name__ == "__main__":
    unittest.main()
