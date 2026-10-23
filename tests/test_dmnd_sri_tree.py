"""Committed source must survive archive attributes and local checkout settings."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import dmnd_sri
from benchmarks.dmnd_sri_tree import extract_tree
from lab.host import git
from test_core import repo_at


class CommittedTreeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = repo_at(self.root / "repo")
        self.destination = self.root / "source"

    def commit(self):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "ADD source fixture to check exact extraction")
        return git(self.repo, "rev-parse", "HEAD").decode().strip()

    def file(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_archive_attributes_and_checkout_filters_cannot_change_source(self):
        self.file(".gitattributes", b"tests/** export-ignore\nversion.txt export-subst\n"
                  b"*.filtered filter=change\n*.crlf text eol=crlf\n")
        self.file("tests/required.rs", b"#[test] fn required() {}\n")
        self.file("version.txt", b"$Format:%H$\n")
        self.file("source.filtered", b"original bytes\n")
        self.file("source.crlf", b"original line\n")
        git(self.repo, "config", "filter.change.clean", "cat")
        git(self.repo, "config", "filter.change.smudge", "printf changed")
        revision = self.commit()
        self.file("tests/required.rs", b"uncommitted change\n")
        extract_tree(self.repo, revision, self.destination)
        for name, expected in (("tests/required.rs", b"#[test] fn required() {}\n"),
                               ("version.txt", b"$Format:%H$\n"),
                               ("source.filtered", b"original bytes\n"),
                               ("source.crlf", b"original line\n")):
            self.assertEqual((self.destination / name).read_bytes(), expected, name)

    def test_binary_bytes_file_names_and_executable_modes_are_preserved(self):
        content = b"\0\xff\xfe\r\n\x80"
        self.file("binary\twith\nnewlines", content)
        executable = self.file("bin/start", b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        self.file("plain", b"plain\n").chmod(0o644)
        extract_tree(self.repo, self.commit(), self.destination)
        self.assertEqual((self.destination / "binary\twith\nnewlines").read_bytes(), content)
        self.assertEqual(stat.S_IMODE((self.destination / "bin/start").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.destination / "plain").stat().st_mode), 0o644)
        self.assertFalse((self.destination / ".git").exists())

    def test_safe_relative_links_and_internal_dangling_links_are_preserved(self):
        self.file("data/value", b"original\n")
        (self.repo / "link").symlink_to("data/value")
        (self.repo / "data/up").symlink_to("../link")
        (self.repo / "dangling").symlink_to("missing/inside")
        extract_tree(self.repo, self.commit(), self.destination)
        for name, target in (("link", "data/value"), ("data/up", "../link"),
                             ("dangling", "missing/inside")):
            self.assertTrue((self.destination / name).is_symlink())
            self.assertEqual(os.readlink(self.destination / name), target)
        self.assertEqual((self.destination / "data/up").read_bytes(), b"original\n")

    def test_absolute_escaping_and_cyclic_links_reject_the_complete_export(self):
        outside = self.root / "outside"
        outside.write_bytes(b"unchanged\n")
        for target in (str(outside), "../outside", "missing/../../outside", "escape"):
            with self.subTest(target=target):
                link = self.repo / "escape"
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "symbolic link"):
                    extract_tree(self.repo, self.commit(), self.destination)
                self.assertFalse(self.destination.exists())
                self.assertEqual(outside.read_bytes(), b"unchanged\n")

    def test_submodules_are_rejected(self):
        revision = git(self.repo, "rev-parse", "HEAD").decode().strip()
        git(self.repo, "update-index", "--add", "--cacheinfo", "160000," + revision + ",dependency")
        git(self.repo, "commit", "-qm", "ADD submodule fixture")
        with self.assertRaisesRegex(ValueError, "unsupported submodule"):
            extract_tree(self.repo, "HEAD", self.destination)
        self.assertFalse(self.destination.exists())

    def test_unsafe_paths_in_raw_git_trees_are_rejected(self):
        blob = git(self.repo, "hash-object", "-w", "--stdin", input=b"unsafe\n").strip()
        for name in (b".", b"../outside", b"/outside", b".git/config", b"a/./file", b"a//file"):
            with self.subTest(name=name):
                tree = git(self.repo, "hash-object", "-w", "-t", "tree", "--literally", "--stdin",
                           input=b"100644 " + name + b"\0" + bytes.fromhex(blob.decode())).decode().strip()
                revision = git(self.repo, "commit-tree", tree, input=b"Unsafe path fixture\n").decode().strip()
                with self.assertRaisesRegex(ValueError, "Unsafe committed source path"):
                    extract_tree(self.repo, revision, self.destination)
                self.assertFalse(self.destination.exists())

    def test_existing_destination_is_not_changed(self):
        self.destination.mkdir()
        sentinel = self.destination / "sentinel"
        sentinel.write_bytes(b"existing\n")
        with self.assertRaises(FileExistsError):
            extract_tree(self.repo, "HEAD", self.destination)
        self.assertEqual(sentinel.read_bytes(), b"existing\n")

    def test_git_replacement_objects_cannot_change_committed_bytes(self):
        original = git(self.repo, "rev-parse", "HEAD:source.py").decode().strip()
        replacement = git(self.repo, "hash-object", "-w", "--stdin", input=b"replacement\n").decode().strip()
        git(self.repo, "replace", original, replacement)
        self.assertEqual(git(self.repo, "show", "HEAD:source.py"), b"replacement\n")
        extract_tree(self.repo, "HEAD", self.destination)
        self.assertEqual((self.destination / "source.py").read_bytes(), b"first\nmiddle\nlast\n")

    def test_source_context_keeps_tests_and_literal_substitution_markers(self):
        self.file("Cargo.toml", b'[package]\nname = "dmnd-client"\nversion = "0.1.0"\n'
                  b'[build-dependencies]\ntoml = "0.8"\n')
        self.file("tests/Dockerfile", b"FROM rust AS builder\n"
                  b"RUN --mount=type=cache,target=/workspace/target,sharing=locked true \\\n"
                  b"    && cargo test --locked --features mining-e2e --test mining_e2e --no-run -j 4 \\\n"
                  b"    && strip /out/mining-e2e /out/dmnd-client\n")
        self.file("tests/required.rs", b"#[test] fn required() {}\n")
        self.file("version.txt", b"$Format:%H$\n")
        base = self.commit()
        self.file(".gitattributes", b"tests/** export-ignore\nversion.txt export-subst\n")
        revision = self.commit()
        with patch.object(dmnd_sri, "BASE", base):
            result = dmnd_sri.source_context(self.repo, revision, self.destination)
        self.assertEqual(result["base"], base)
        self.assertEqual((self.destination / "tests/required.rs").read_bytes(), b"#[test] fn required() {}\n")
        self.assertEqual((self.destination / "version.txt").read_bytes(), b"$Format:%H$\n")
        self.assertTrue((self.destination / "tests/Dockerfile").is_file())


if __name__ == "__main__":
    unittest.main()
