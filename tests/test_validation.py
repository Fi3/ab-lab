"""Final checks need private writable Cargo state inside the command sandbox."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from lab.config import settings
from lab.host import git, snapshot
from lab.sandbox import CommandSandbox
from lab.validation import CARGO_CACHE_POLICY, final_check_environment
from lab.workflow import run
from test_core import repo_at
from test_workflow import FakeCodex


class ValidationEnvironmentTests(unittest.TestCase):
    def test_cache_is_empty_separate_and_removed_without_changing_provider_environment(self):
        supplied = {"PATH": "/bin", "CARGO_HOME": "/author/cache", "CARGO_TARGET_DIR": "/author/build"}
        with final_check_environment(supplied) as first:
            cache, target = Path(first["CARGO_HOME"]), Path(first["CARGO_TARGET_DIR"])
            self.assertEqual(list(cache.iterdir()), [])
            self.assertEqual(list(target.iterdir()), [])
            self.assertNotEqual(cache, target)
            (cache / "marker").write_text("first check")
            with final_check_environment(supplied) as second:
                self.assertNotEqual(first["CARGO_HOME"], second["CARGO_HOME"])
                self.assertFalse((Path(second["CARGO_HOME"]) / "marker").exists())
        self.assertFalse(cache.exists())
        self.assertFalse(target.exists())
        self.assertEqual(supplied, {"PATH": "/bin", "CARGO_HOME": "/author/cache", "CARGO_TARGET_DIR": "/author/build"})

    def test_failed_check_keeps_receipt_and_releases_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark = {"name": "failure", "repo": str(repo_at(root / "input")), "revision": "HEAD",
                         "features": [{"id": "feature", "request": "create feature"}], "checks": ["exit 7"]}
            result = run(benchmark, settings({}), root / "run", 30, 10000, 10,
                         backend=FakeCodex, max_review_loops=0)
            self.assertEqual(result["status"], "failed", result)
            self.assertEqual(result["failure"]["origin"], "validation")
            receipt = result["checks"][0]
            self.assertEqual(receipt["exit_code"], 7)
            self.assertEqual(receipt["environment"]["cargo_cache_policy"], CARGO_CACHE_POLICY)
            self.assertFalse(Path(receipt["environment"]["CARGO_HOME"]).exists())
            self.assertEqual(json.loads((root / "run/check-01/result.json").read_text()), receipt)


@unittest.skipUnless(shutil.which("cargo") and shutil.which("codex"), "local Cargo and Codex sandbox required")
class CargoValidationSandboxTests(unittest.TestCase):
    def write(self, root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def fixture(self, root):
        dependency = repo_at(root / "dependency")
        self.write(dependency, "Cargo.toml", '[package]\nname="local-dependency"\nversion="0.1.0"\nedition="2021"\n')
        self.write(dependency, "src/lib.rs", "pub fn answer() -> u32 { 42 }\n")
        git(dependency, "add", "--all")
        git(dependency, "commit", "-qm", "ADD local Git dependency for cache checks")
        revision = git(dependency, "rev-parse", "HEAD").decode().strip()
        repo = repo_at(root / "input")
        self.write(repo, "Cargo.toml", '[package]\nname="cache-fixture"\nversion="0.1.0"\nedition="2021"\n'
                   '[dependencies]\nlocal-dependency={git="' + dependency.as_uri() + '", rev="' + revision + '"}\n')
        self.write(repo, "src/lib.rs", "pub fn answer() -> u32 { local_dependency::answer() }\n")
        self.write(repo, "src/main.rs", "fn main() { assert_eq!(cache_fixture::answer(), 42); }\n")
        seed = subprocess.run(["cargo", "generate-lockfile"], cwd=repo, text=True, capture_output=True,
                              timeout=30, env={**os.environ, "CARGO_HOME": str(root / "lock-cache")})
        self.assertEqual(seed.returncode, 0, seed.stderr)
        git(repo, "add", "--all")
        git(repo, "commit", "-qm", "ADD locked package for sandbox validation")
        return repo

    def test_workflow_fetches_local_git_and_checks_offline_without_home_or_git_write_access(self):
        # Keep these paths outside /tmp so the sandbox's scratch permission
        # cannot accidentally make the original home cache writable.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = self.fixture(root)
            original = snapshot(repo)
            cache, target, state = root / "home-cargo", root / "home-target", root / "codex-state"
            for path in (cache, target, state):
                path.mkdir()
            environment = {**os.environ, "CARGO_HOME": str(cache), "CARGO_TARGET_DIR": str(target), "CODEX_HOME": str(state)}
            command = "cargo check --locked --lib --bin cache-fixture"
            sandbox = CommandSandbox(repo, shutil.which("codex"))
            broken = subprocess.run(sandbox.command(True, ["/bin/sh", "-c", command], protect_git=True),
                                    cwd=repo, env=environment, text=True, capture_output=True, timeout=30)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn("Read-only file system", broken.stderr)

            probe = "\n".join([
                "import os,pathlib,subprocess",
                f"for path in ({str(cache / 'forbidden')!r}, '.git/config'):",
                "    try: pathlib.Path(path).write_text('forbidden')",
                "    except OSError: pass",
                "    else: raise AssertionError('protected write allowed: ' + path)",
                "assert subprocess.run(['git','add','src/lib.rs'],capture_output=True).returncode != 0",
                "cache = pathlib.Path(os.environ['CARGO_HOME'])",
                "assert list((cache / 'git/db').iterdir())",
                "assert (pathlib.Path(os.environ['CARGO_TARGET_DIR']) / 'debug').is_dir()",
            ])

            class Sandboxed(FakeCodex):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.command_env = dict(environment)
                    self.sandbox = CommandSandbox(self.repo, shutil.which("codex"))

                def command_argv(self, argv):
                    return self.sandbox.command(True, argv, protect_git=True)

            benchmark = {"name": "cargo-cache", "repo": str(repo), "revision": "HEAD",
                         "features": [{"id": "feature", "request": "create feature"}],
                         "checks": [command, "cargo check --offline --locked --lib --bin cache-fixture && "
                                    + shlex.join([sys.executable, "-c", probe])]}
            result = run(benchmark, settings({}), root / "run", 60, 10000, 10,
                         backend=Sandboxed, max_review_loops=0)
            logs = "\n".join(path.read_text() for path in (root / "run").glob("check-*/stderr.txt"))
            self.assertEqual(result["status"], "passed", logs + "\n" + str(result))
            first, second = result["checks"]
            self.assertEqual(first["environment"], second["environment"])
            self.assertEqual(first["environment"]["cargo_cache_policy"], CARGO_CACHE_POLICY)
            self.assertNotEqual(first["environment"]["CARGO_HOME"], str(cache))
            self.assertFalse(Path(first["environment"]["CARGO_HOME"]).exists())
            self.assertEqual(Sandboxed.instances[-1].command_env, environment)
            self.assertEqual(snapshot(repo), original)
            self.assertFalse((root / "run/checkout/target").exists())
            self.assertEqual(list(cache.iterdir()), [])
            self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
