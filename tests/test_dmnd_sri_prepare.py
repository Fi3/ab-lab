"""Preparation preserves the base history and keeps dependency evidence separate."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import dmnd_sri_prepare as prepare
from benchmarks import dmnd_sri_baseline as baseline
from lab.host import Fatal, git
from lab.review import BlindReview


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
        (self.source / "README.md").write_text("Original project instructions.\n")
        (self.source / "AGENTS.md").write_text("Keep the protected tests unchanged.\n")
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

    def public_fixture(self):
        assets = self.root / "public-assets"
        assets.mkdir()
        (assets / "README.md").write_text("Run the public transport example.\n")
        (assets / "sri_transport_contract.rs").write_text("fn main() {}\n")
        self.enterContext(patch.object(baseline, "ASSETS", assets))
        self.enterContext(patch.object(prepare, "DEFAULT_REPO", self.destination))
        revision = prepare.build_public_commit(self.source)
        self.enterContext(patch.object(prepare, "PUBLIC_REVISION", revision))
        return self.root / "public-v2" / "repo"

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
            (lambda receipt: receipt.update(schema="unknown", revision=None), "source identity"),
            (lambda receipt: receipt.update(schema=[]), "source identity"),
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

    def test_public_baseline_is_an_isolated_child_with_the_same_source_evidence(self):
        public = self.public_fixture()
        self.local_prepare()
        original_receipt = (self.destination.parent / "setup.json").read_bytes()
        original_head = git(self.destination, "rev-parse", "HEAD")
        with patch.object(prepare, "dependency_reference") as reference:
            self.assertEqual(prepare.prepare_public(public, self.source), public)
        reference.assert_not_called()
        self.assertEqual(git(self.destination, "rev-parse", "HEAD"), original_head)
        self.assertEqual((self.destination.parent / "setup.json").read_bytes(), original_receipt)
        self.assertEqual(git(public, "rev-list", "--parents", "-n", "1", "HEAD").decode().split(),
                         [prepare.PUBLIC_REVISION, self.base])
        self.assertEqual(set(git(public, "diff", "--name-only", self.base, "HEAD").decode().splitlines()),
                         {"README.md", "AGENTS.md", "examples/sri_transport_contract.rs"})
        self.assertEqual((public / "client.rs").read_text(), "old_client();\n")
        self.assertEqual((public / "README.md").read_bytes(),
                         git(self.source, "show", self.base + ":README.md")
                         + b"\n\nRun the public transport example.\n")
        self.assertFalse((public / "private.txt").exists())
        with self.assertRaises(Fatal):
            git(public, "cat-file", "-e", self.future)
        receipt = json.loads((public.parent / "setup.json").read_text())
        self.assertEqual((receipt["schema"], receipt["base"], receipt["revision"]),
                         (prepare.PUBLIC_SCHEMA, self.base, prepare.PUBLIC_REVISION))
        self.assertEqual(receipt["references"], self.setup_data()["references"])

    def test_public_commit_is_deterministic_and_does_not_change_the_source_index(self):
        self.public_fixture()
        head, index = git(self.source, "rev-parse", "HEAD"), git(self.source, "write-tree")
        git(self.source, "config", "user.name", "Another user")
        git(self.source, "config", "user.email", "another@example.invalid")
        git(self.source, "config", "commit.gpgSign", "true")
        git(self.source, "config", "core.autocrlf", "true")
        git(self.source, "config", "i18n.commitEncoding", "ISO-8859-1")
        self.assertEqual(prepare.build_public_commit(self.source), prepare.PUBLIC_REVISION)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.source, "write-tree"), index)
        self.assertFalse(git(self.source, "status", "--porcelain", "--untracked-files=no"))

    def test_existing_public_setup_needs_no_fetch_or_dependency_copy(self):
        public = self.public_fixture()
        prepare.prepare_public(public)
        original = (public.parent / "setup.json").read_bytes()
        with patch.object(prepare, "fetch_revision") as fetch, \
                patch.object(prepare, "dependency_reference") as reference:
            self.assertEqual(prepare.prepare_public(public), public)
        fetch.assert_not_called()
        reference.assert_not_called()
        self.assertEqual((public.parent / "setup.json").read_bytes(), original)

    def test_public_contract_is_available_in_the_neutral_review_tree(self):
        public = self.public_fixture()
        prepare.prepare_public(public)
        (public / "client.rs").write_text("candidate_change();\n")
        git(public, "add", "client.rs")
        git(public, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-qm", "UPDATE candidate fixture")
        candidate = git(public, "rev-parse", "HEAD").decode().strip()
        review = BlindReview(public, prepare.PUBLIC_REVISION, self.root / "review")
        head = review.update(candidate)
        for name in ("README.md", "AGENTS.md", *prepare.PUBLIC_PATHS):
            expected = git(public, "show", prepare.PUBLIC_REVISION + ":" + name)
            self.assertEqual(git(review.repo, "show", review.base + ":" + name), expected)
            self.assertEqual(git(review.repo, "show", head + ":" + name), expected)
            self.assertEqual((review.repo / name).read_bytes(), expected)
        self.assertNotEqual(head, candidate)
        with self.assertRaises(Fatal):
            git(review.repo, "cat-file", "-e", candidate)

    def test_public_source_changes_are_rejected_without_reset(self):
        public = self.public_fixture()
        prepare.prepare_public(public)
        (public / "client.rs").write_text("user_work();\n")
        with self.assertRaisesRegex(ValueError, "modified tracked files"):
            prepare.prepare_public(public)
        self.assertEqual((public / "client.rs").read_text(), "user_work();\n")
        git(public, "checkout", "--", "client.rs")
        git(public, "checkout", "-q", "--detach", self.base)
        with self.assertRaisesRegex(ValueError, "pinned revision"):
            prepare.prepare_public(public)
        self.assertEqual(git(public, "rev-parse", "HEAD").decode().strip(), self.base)

    def test_changed_public_assets_do_not_publish_a_different_baseline(self):
        public = self.public_fixture()
        (baseline.ASSETS / "sri_transport_contract.rs").write_text("fn changed() {}\n")
        with self.assertRaisesRegex(ValueError, "pinned revision"):
            prepare.prepare_public(public)
        self.assertFalse(public.exists())
        self.assertFalse((public.parent / "setup.json").exists())
        self.assertEqual(git(self.destination, "rev-parse", "HEAD").decode().strip(), self.base)

    def test_existing_public_setup_rejects_changed_assets_and_wrong_receipt_version(self):
        public = self.public_fixture()
        prepare.prepare_public(public)
        contract = baseline.ASSETS / "sri_transport_contract.rs"
        original = contract.read_bytes()
        contract.write_bytes(b"fn changed() {}\n")
        with self.assertRaisesRegex(ValueError, "public transport contract changed"):
            prepare.prepare_public(public)
        contract.write_bytes(original)
        (public.parent / "setup.json").write_bytes((self.destination.parent / "setup.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "source identity"):
            prepare.prepare_public(public)

    def test_public_prepare_rejects_dirty_source_before_creating_caches(self):
        public = self.public_fixture()
        (self.source / "client.rs").write_text("uncommitted_work();\n")
        with self.assertRaisesRegex(ValueError, "modified tracked files"):
            prepare.prepare_public(public, self.source)
        self.assertFalse(public.exists())
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
