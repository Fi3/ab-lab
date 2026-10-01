"""Runner Git cannot turn author-owned configuration into unsandboxed code."""
import os
from pathlib import Path
import shlex
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.environment import clean_env
from lab.host import Fatal, git, git_execution
from lab.sandbox import CommandSandbox
from lab.workflow import capture_native_work
from test_core import repo_at


class RunnerGitTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="runner-git-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = repo_at(self.root / "checkout")

    def hook(self, text):
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\n" + text)
        hook.chmod(0o755)
        return hook

    def test_capture_uses_scoped_executor_and_clean_environment_for_every_git_call(self):
        commands = []
        self.hook('printf "%s" "$OPENAI_API_KEY" > secret-seen\n')
        (self.repo / "source.py").write_text("changed\n")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-reach-hook"}):
            with git_execution(self.repo, lambda argv: commands.append(argv) or argv,
                               clean_env(), time.monotonic() + 10):
                capture_native_work(self.repo, "test", self.root)
        self.assertEqual((self.repo / "secret-seen").read_text(), "")
        operations = {argv[3] for argv in commands}
        self.assertTrue({"ls-files", "rev-parse", "status", "add", "diff", "commit"} <= operations)

    def test_native_capture_deadline_kills_callback_descendants(self):
        marker = self.repo / "late-write"
        self.hook('touch hook-started\n(sleep 1; touch late-write) &\nwait\n')
        (self.repo / "source.py").write_text("changed\n")
        started = time.monotonic()
        with git_execution(self.repo, lambda argv: argv, clean_env(), started + 0.3):
            with self.assertRaisesRegex(Fatal, "timed out|deadline exhausted"):
                capture_native_work(self.repo, "timeout", self.root)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue((self.repo / "hook-started").exists())
        time.sleep(1.1)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "timeout-source.json").exists())

    @unittest.skipUnless(shutil.which("codex"), "installed Codex sandbox required; no model calls")
    def test_hook_filter_and_fsmonitor_cannot_write_outside_allowed_filesystem(self):
        outside = self.root / "protected"
        outside.mkdir()
        sandbox = CommandSandbox(self.repo, shutil.which("codex"), read_only_paths=[outside])
        for kind in ("hook", "filter", "fsmonitor"):
            with self.subTest(kind=kind):
                marker = outside / kind
                script = self.repo / (kind + ".sh")
                script.write_text("#!/bin/sh\nprintf reached > " + shlex.quote(str(marker)) +
                                  ("\ncat\n" if kind == "filter" else "\nexit 0\n"))
                script.chmod(0o755)
                if kind == "hook":
                    self.hook("exec " + shlex.quote(str(script)) + "\n")
                elif kind == "filter":
                    git(self.repo, "config", "filter.probe.clean", str(script))
                    (self.repo / ".gitattributes").write_text("source.py filter=probe\n")
                else:
                    git(self.repo, "config", "core.fsmonitor", str(script))
                (self.repo / "source.py").write_text(kind + "\n")
                with git_execution(self.repo, lambda argv: sandbox.command(True, argv),
                                   clean_env(), time.monotonic() + 20):
                    capture_native_work(self.repo, kind, self.root)
                self.assertFalse(marker.exists())
                # Remove active callbacks before the next test setup uses Git.
                if kind == "hook":
                    (self.repo / ".git/hooks/pre-commit").unlink()
                elif kind == "filter":
                    git(self.repo, "config", "--unset", "filter.probe.clean")
                else:
                    git(self.repo, "config", "--unset", "core.fsmonitor")
