import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import FACTORS, load_benchmark, settings, policy_blocks
from lab.host import Host, Fatal, Rejected, parse_operations, plan_edit, refresh_text
from lab.provider import Codex, Usage, InterruptGate, clean_env


def repo_at(path):
    path.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Test"),
                 ("config", "user.email", "test@example.invalid")):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    (path / "source.py").write_text("first\nmiddle\nlast\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "base"], check=True)
    return path


class ConfigurationTests(unittest.TestCase):
    def test_switches_and_owned_prompt_blocks(self):
        all_on = settings({})
        self.assertEqual(set(all_on), set(FACTORS))
        for key in ("C13", "C14", "C15", "C16", "C20", "C38"):
            changed = settings({key: False})
            a, b = policy_blocks(all_on), policy_blocks(changed)
            self.assertEqual([k for k in a if a[k] != b[k]], [key])

    def test_no_silent_unknown_or_inert_switches(self):
        for config in ({"C99": True}, {"C08": "off"}, {"C17": False}):
            with self.assertRaises(ValueError):
                settings(config)
        settings({"C17": False, "C08": False, "C25": False})

    def test_arbitrary_number_of_features(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "benchmark.json"
            p.write_text(json.dumps({"name": "different", "repo": directory,
                "revision": "HEAD", "features": [{"id": "one", "request": "First"},
                    {"id": "two", "request": "Second"}], "checks": ["true"]}))
            self.assertEqual(len(load_benchmark(p)["features"]), 2)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = repo_at(self.root / "repo")

    def test_global_bare_hunks_match_original_j04(self):
        patch = "*** Begin Patch\n*** Update File: source.py\n@@\n-last\n+end\n@@\n-first\n+start\n*** End Patch"
        result = plan_edit(self.repo, patch)
        self.assertEqual(result["source.py"][1][1], b"start\nmiddle\nend\n")

    def test_invalid_multifile_patch_does_not_mutate(self):
        patch = "*** Begin Patch\n*** Update File: source.py\n@@\n-first\n+start\n*** Update File: missing\n@@\n-x\n+y\n*** End Patch"
        with self.assertRaises(Rejected):
            plan_edit(self.repo, patch)
        self.assertEqual((self.repo / "source.py").read_text(), "first\nmiddle\nlast\n")

    def test_mixed_operations_do_not_execute(self):
        host = Host(self.repo, self.root / "host", "one", "implement", time.monotonic()+30, settings({}))
        reply = host.consume("@standalone run -- true\n@standalone done")
        self.assertIn("rejected", reply)
        self.assertFalse(host.completed)
        self.assertEqual(host.counter, 0)

    def test_read_then_conflict_has_compact_or_full_same_information(self):
        old = "\n".join(str(i) for i in range(1000)) + "\n"
        current = old.replace("500\n", "five hundred\n")
        compact, mode = refresh_text("f", old, current, True)
        full, other = refresh_text("f", old, current, False)
        self.assertEqual(mode, "diff")
        self.assertEqual(other, "full")
        self.assertIn("+five hundred", compact)
        self.assertIn("--- previous/f", compact)
        self.assertIn(current, full)
        self.assertLess(len(compact), len(full))
        self.assertEqual(refresh_text("f", None, current, True)[1], "full")
        self.assertEqual(refresh_text("f", old, old, True), refresh_text("f", old, old, False))

    def test_path_and_symlink_escape_rejected(self):
        (self.repo / "escape").symlink_to(self.root)
        for name in ("../outside", "escape/outside", ".git/config"):
            with self.assertRaises(Rejected):
                plan_edit(self.repo, f"*** Begin Patch\n*** Add File: {name}\n+x\n*** End Patch")


class AccountingTests(unittest.TestCase):
    def test_missing_login_is_a_clear_subscription_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("lab.provider.subprocess.Popen"), patch.object(Codex, "rpc", side_effect=[{}, {"account": None}]):
                with self.assertRaisesRegex(Fatal, "subscription login required"):
                    Codex(directory, Path(directory)/"provider", "test", "test", time.monotonic()+10, 1, 1)

    def test_provider_creates_nested_artifact_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "runs" / "doctor"
            with patch("lab.provider.subprocess.Popen", side_effect=OSError("test launch failure")):
                with self.assertRaises(OSError):
                    Codex(directory, target, "test", "test", time.monotonic()+10, 1, 1)
            self.assertTrue(target.is_dir())

    def test_cumulative_usage_not_added_twice(self):
        usage = Usage()
        params = {"threadId": "t", "turnId": "a", "tokenUsage": {
            "total": {"inputTokens": 100, "outputTokens": 20, "cachedInputTokens": 70},
            "last": {"inputTokens": 100, "outputTokens": 20}}}
        self.assertTrue(usage.observe(params))
        self.assertFalse(usage.observe(params))
        self.assertEqual(usage.raw, 120)
        self.assertEqual(usage.cached, 70)
        params["tokenUsage"]["total"] = {"inputTokens": 130, "outputTokens": 25, "cachedInputTokens": 90}
        self.assertTrue(usage.observe(params))
        self.assertEqual(usage.raw, 155)

    def test_usage_reset_is_not_zero_or_negative_saving(self):
        usage = Usage()
        for i in (100, 50):
            usage.observe({"threadId": "t", "turnId": "a", "tokenUsage": {
                "total": {"inputTokens": i, "outputTokens": 10},
                "last": {"inputTokens": i, "outputTokens": 10}}})
        self.assertTrue(usage.uncertain)

    def test_interrupt_grace_and_natural_finish(self):
        enabled = InterruptGate(True)
        enabled.directive(10)
        self.assertIsNone(enabled.reason(10.5))
        self.assertEqual(enabled.reason(11.1), "grace_expired")
        enabled = InterruptGate(True)
        enabled.directive(10)
        enabled.fresh_usage = True
        self.assertEqual(enabled.reason(10.1), "usage_received")
        disabled = InterruptGate(False)
        disabled.directive(10)
        self.assertIsNone(disabled.reason(100))

    def test_api_keys_and_endpoints_are_not_inherited(self):
        env = clean_env({"PATH": "/bin", "OPENAI_API_KEY": "secret", "OPENAI_BASE_URL": "elsewhere", "CODEX_API_KEY": "secret"})
        self.assertEqual(env, {"PATH": "/bin"})


if __name__ == "__main__":
    unittest.main()
