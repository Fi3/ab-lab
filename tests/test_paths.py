from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from lab.config import settings
from lab.host import Host, Fatal, snapshot, refresh_text
from lab.host_tools import HostTools
from test_core import repo_at


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = repo_at(self.root / "repo")

    def host(self, **overrides):
        return Host(self.repo, self.root / ("host"+str(len(list(self.root.iterdir())))), "feature", "author", time.monotonic()+30, settings(overrides))

    def test_unified_format_applies_and_commits(self):
        host = self.host(C16=False)
        reply = HostTools(host).execute("host_edit", {"patch": "--- a/source.py\n+++ b/source.py\n@@ -1,3 +1,3 @@\n-first\n+start\n middle\n last\n"}, "unified")
        self.assertTrue(reply["success"], reply)
        self.assertEqual((self.repo / "source.py").read_text(), "start\nmiddle\nlast\n")
        self.assertEqual(len(host.accepted_commits), 1)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain"]), b"")

    def test_stale_proposal_refreshes_only_actual_seen_text(self):
        host = self.host()
        HostTools(host).execute("host_read", {"path": "source.py"}, "read")
        # Fixture represents a separately accepted intervening update. Host
        # custody has the new state; the author's last delivered snapshot does not.
        (self.repo / "source.py").write_text("revised\nmiddle\nlast\n")
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qam", "peer update"], check=True)
        host.expected = snapshot(self.repo)
        reply = HostTools(host).execute("host_edit", {"patch": "*** Begin Patch\n*** Update File: source.py\n@@\n-first\n+start\n*** End Patch\n"}, "stale")
        self.assertFalse(reply["success"], reply)
        self.assertIn("+revised", reply["text"])
        self.assertEqual(host.activations["C08"], 1)
        self.assertEqual(host.seen["source.py"], "revised\nmiddle\nlast\n")

    def test_oversize_refresh_has_same_omission_in_both_arms(self):
        previous, current = "before\n"*20000, "after\n"*20000
        self.assertEqual(refresh_text("f", previous, current, True), refresh_text("f", previous, current, False))

    def test_initial_automatic_refresh_uses_the_original_eight_kib_limit(self):
        text = "x" * (8*1024+1)
        self.assertEqual(refresh_text("f", None, text, True)[1], "omitted")
        self.assertEqual(refresh_text("f", None, text, True), refresh_text("f", None, text, False))

    def test_own_successful_edit_invalidates_the_read_snapshot_like_wl(self):
        host = self.host()
        HostTools(host).execute("host_read", {"path": "source.py"}, "read")
        reply = HostTools(host).execute("host_edit", {"patch": "*** Begin Patch\n*** Update File: source.py\n@@\n-first\n+start\n*** End Patch\n"}, "edit")
        self.assertTrue(reply["success"], reply)
        self.assertNotIn("source.py", host.seen)

    def test_native_mutation_is_not_accepted_as_host_work(self):
        host = self.host()
        (self.repo / "source.py").write_text("unexpected")
        with self.assertRaises(Fatal):
            HostTools(host).execute("host_read", {"path": "source.py"}, "drift")



if __name__ == "__main__":
    unittest.main()
