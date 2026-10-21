"""Preparation preserves the base history and keeps dependency evidence separate."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import dmnd_sri_prepare as prepare
from lab.host import Fatal, git


class DmndPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dependencies = {}
        for name in ("roles_logic_sv2", "demand-sv2-connection", "demand-share-accounting-ext"):
            folder = self.repository(name)
            (folder / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "1.0.0"\n')
            (folder / "src").mkdir()
            (folder / "src/lib.rs").write_text("pub fn original() {}\n")
            (folder / ".gitignore").write_text("target/\n")
            (folder / "Cargo.lock").write_text("version = 4\n")
            (folder / "tests").mkdir()
            (folder / "tests/pool_api.rs").write_text("#[test] fn original_test() {}\n")
            self.dependencies[name] = (folder, self.commit(folder))
        self.source = self.repository("client")
        (self.source / "client.rs").write_text("old_client();\n")
        self.parent = self.commit(self.source)
        lock = "version = 4\n"
        for name in ("demand-sv2-connection", "demand-share-accounting-ext"):
            revision = self.dependencies[name][1]
            lock += (f'\n[[package]]\nname = "{name}"\nversion = "1.0.0"\n'
                     f'source = "git+https://example.invalid/{name}#{revision}"\n')
        (self.source / "Cargo.lock").write_text(lock)
        self.base = self.commit(self.source)
        (self.source / "client.rs").write_text("completed_migration();\n")
        self.future = self.commit(self.source)
        git(self.source, "tag", "solution", self.future)
        (self.source / "private.txt").write_text("untracked local data\n")
        for key, value in (("BASE_REVISION", self.base),
                           ("ROLES_REVISION", self.dependencies["roles_logic_sv2"][1])):
            override = patch.object(prepare, key, value)
            override.start()
            self.addCleanup(override.stop)
        self.destination = self.root / "prepared" / "repo"
        self.remote_sources()

    def remote_sources(self):
        fetch_revision = prepare.fetch_revision
        sources = {prepare.ROLES_URL: self.dependencies["roles_logic_sv2"][0],
                   prepare.BASE_URL: self.source}
        sources.update({"https://example.invalid/" + name: folder
                        for name, (folder, _) in self.dependencies.items()})

        def fetch(repo, source, revision):
            if source == "origin":
                url = git(repo, "remote", "get-url", "origin").decode().strip()
                source = sources[url]
            fetch_revision(repo, source, revision)

        override = patch.object(prepare, "fetch_revision", side_effect=fetch)
        override.start()
        self.addCleanup(override.stop)

    def repository(self, name):
        folder = self.root / name
        folder.mkdir()
        git(folder, "init", "-q")
        git(folder, "config", "user.name", "Test")
        git(folder, "config", "user.email", "test@localhost")
        git(folder, "config", "commit.gpgSign", "false")
        return folder

    def commit(self, folder):
        git(folder, "add", "-A")
        git(folder, "commit", "-qm", "ADD test data to verify preparation")
        return git(folder, "rev-parse", "HEAD").decode().strip()

    def local_prepare(self):
        return prepare.prepare(self.destination, self.source)

    def setup_data(self):
        return json.loads((self.destination.parent / "setup.json").read_text())

    def test_local_prepare_preserves_base_history_without_future_solution(self):
        self.assertEqual(self.local_prepare(), self.destination)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD").decode().strip(), self.base)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD^").decode().strip(), self.parent)
        self.assertEqual(git(self.destination, "rev-parse", "--is-shallow-repository"), b"false\n")
        self.assertEqual((self.destination / "client.rs").read_text(), "old_client();\n")
        self.assertFalse((self.destination / "vendor").exists())
        self.assertFalse((self.destination / "private.txt").exists())
        self.assertEqual(git(self.destination, "show-ref", "--head").decode().splitlines(),
                         [self.base + " HEAD"])
        with self.assertRaises(Fatal):
            git(self.destination, "cat-file", "-e", self.future)
        self.assertEqual(git(self.source, "rev-parse", "HEAD").decode().strip(), self.future)
        receipt = self.setup_data()
        self.assertEqual((receipt["base"], receipt["revision"]), (self.base, self.base))
        roles = receipt["references"]["roles_logic_sv2"]
        self.assertEqual(roles["source"], prepare.ROLES_URL)
        self.assertEqual(roles["revision"], prepare.ROLES_REVISION)
        self.assertEqual(set(roles["files"]), {
            "src/lib.rs", "Cargo.toml", ".gitignore", "Cargo.lock", "tests/pool_api.rs"})
        self.assertEqual(roles["evidence"]["prefix"], "")
        self.assertEqual(roles["evidence"]["revision"], prepare.ROLES_REVISION)

    def test_existing_upstream_evidence_needs_no_network(self):
        self.local_prepare()
        receipt = (self.destination.parent / "setup.json").read_bytes()
        with patch.object(prepare, "fetch_revision") as fetch, \
                patch.object(prepare, "dependency_reference") as reference:
            self.assertEqual(prepare.prepare(self.destination), self.destination)
        fetch.assert_not_called()
        reference.assert_not_called()
        self.assertEqual((self.destination.parent / "setup.json").read_bytes(), receipt)

    def test_tracked_dirty_source_is_rejected_before_target_creation(self):
        (self.source / "client.rs").write_text("uncommitted_work();\n")
        with self.assertRaisesRegex(ValueError, "modified tracked files"):
            self.local_prepare()
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.source / "client.rs").read_text(), "uncommitted_work();\n")

    def test_changed_prepared_repository_is_rejected_without_reset(self):
        self.local_prepare()
        (self.destination / "client.rs").write_text("user_work();\n")
        with self.assertRaisesRegex(ValueError, "modified tracked files"):
            prepare.prepare(self.destination)
        self.assertEqual((self.destination / "client.rs").read_text(), "user_work();\n")
        git(self.destination, "checkout", "--", "client.rs")
        git(self.destination, "checkout", "-q", "--detach", self.parent)
        with self.assertRaisesRegex(ValueError, "pinned revision"):
            prepare.prepare(self.destination)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD").decode().strip(), self.parent)

    def test_changed_setup_identities_and_missing_hashes_are_rejected(self):
        self.local_prepare()
        original = self.setup_data()
        mutations = (
            (lambda receipt: receipt.update(base="0" * 40), "source identity"),
            (lambda receipt: receipt["references"]["roles_logic_sv2"].update(revision="0" * 40),
             "dependency identity"),
            (lambda receipt: receipt["references"]["roles_logic_sv2"].update(files={}),
             "file evidence"),
            (lambda receipt: receipt["references"]["roles_logic_sv2"]["evidence"].update(
                prefix="vendor/roles-logic-sv2"), "source evidence"),
            (lambda receipt: receipt["references"]["roles_logic_sv2"]["evidence"].update(
                revision="0" * 40), "source evidence"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message):
                receipt = json.loads(json.dumps(original))
                mutate(receipt)
                (self.destination.parent / "setup.json").write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, message):
                    prepare.prepare(self.destination)

    def test_fetch_failure_does_not_publish_an_incomplete_target(self):
        with patch.object(prepare, "BASE_REVISION", "0" * 40):
            with self.assertRaises(subprocess.CalledProcessError):
                self.local_prepare()
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.destination.parent / "setup.json").exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_original_sources_are_fetched_without_a_local_base(self):
        prepare.prepare(self.destination)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD").decode().strip(), self.base)
        for name, reference in self.setup_data()["references"].items():
            self.assertEqual(reference["revision"], self.dependencies[name][1])
            self.assertEqual(reference["evidence"]["prefix"], "")
            checkout = self.destination.parent / "sources" / name
            self.assertEqual(git(checkout, "rev-parse", "HEAD").decode().strip(), reference["revision"])


if __name__ == "__main__":
    unittest.main()
