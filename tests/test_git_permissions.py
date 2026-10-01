"""Regression coverage for native Git writes and preflight."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Fatal, git
from lab.provider import Codex
from lab.workflow import run
import test_provider as stream
from test_core import repo_at
from test_workflow import FakeCodex


class GitPermissionTests(unittest.TestCase):
    provider = stream.StreamTests.provider

    def test_native_write_turn_includes_only_checkout_and_its_git_directory(self):
        p = self.provider([stream.message("Finished"), stream.price(), stream.completed()])
        calls = []
        def rpc(method, params):
            calls.append((method, params))
            return {"turn": {"id": "u"}}
        p.rpc = rpc
        p.turn("t", "commit the feature", "author", writable=True)
        self.assertEqual(calls[0][1]["permissions"], p.sandbox.profile(True))
        self.assertNotIn("sandboxPolicy", calls[0][1])
        self.assertEqual(p.sandbox.filesystem(True)[str(p.repo / ".git")], "write")

    def test_read_only_turn_does_not_gain_git_write_access(self):
        p = self.provider([stream.message("NO_FINDINGS"), stream.price(), stream.completed()])
        calls = []
        p.rpc = lambda method, params: calls.append(params) or {"turn": {"id": "u"}}
        p.turn("t", "review", "review")
        self.assertEqual(calls[0]["permissions"], p.sandbox.profile(False))
        self.assertNotIn("sandboxPolicy", calls[0])
        self.assertEqual(p.sandbox.filesystem(False)[str(p.repo / ".git")], "read")

    def test_preflight_records_native_failure_without_starting_a_model_turn(self):
        p = self.provider([])
        p.command_env = {}
        with patch("lab.provider.subprocess.run") as execute:
            execute.return_value.returncode = 128
            execute.return_value.stdout = ""
            execute.return_value.stderr = "index.lock: Read-only file system"
            with self.assertRaisesRegex(Fatal, "Git-write preflight failed"):
                p.verify_git_write()
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0],
                         p.sandbox.command(True, ["git", "update-index", "--refresh"]))
        self.assertEqual(p.turns, [])
        self.assertTrue((p.artifacts / "git-write-preflight.json").exists())

    def test_workflow_requires_git_preflight_before_any_model_work(self):
        class Denied(FakeCodex):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if kwargs.get("require_git_write"):
                    raise Fatal("Git-write preflight failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            bench = {"name": "b", "repo": str(repo), "revision": "HEAD",
                "features": [{"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
                "checks": ["true"]}
            result = run(bench, settings({}), root / "run", 30, 10000, 30, backend=Denied)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"], "Git-write preflight failed")
            self.assertEqual(Denied.instances[-1].calls, [])
