"""Dependency checks must reject old code and modified first imports."""
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from benchmarks import dmnd_sri_source as source


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@localhost")
        self.write("Cargo.toml", '[package]\nname = "dmnd-client"\nversion = "1.0.0"\n')
        self.base = self.commit()
        self.metadata = self.graph()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "ADD fixture source to check dependency validation")
        return self.git("rev-parse", "HEAD")

    def package(self, name, version="1.0.0", origin=None, path=None):
        return {"id": name, "name": name, "version": version, "source": origin,
                "manifest_path": path or "/workspace/Cargo.toml"}

    def edge(self, name, kind=None, alias=None):
        return {"name": alias or name, "pkg": name, "dep_kinds": [{"kind": kind, "target": None}]}

    def graph(self):
        packages = [self.package("dmnd-client"), self.package(
            "roles_logic_sv2", "3.2.1", "git+" + source.SRI_SOURCE + "#" + source.SRI_REVISION)]
        packages.extend(self.package(name, version, "registry+https://github.com/rust-lang/crates.io-index")
                        for name, version in source.PROTOCOL_VERSIONS.items())
        nodes = [{"id": "dmnd-client", "deps": [self.edge("roles_logic_sv2")]},
                 {"id": "roles_logic_sv2", "deps": [self.edge(name) for name in source.PROTOCOL_VERSIONS]}]
        nodes.extend({"id": name, "deps": []} for name in source.PROTOCOL_VERSIONS)
        return {"packages": packages, "workspace_members": ["dmnd-client"], "resolve": {"nodes": nodes}}

    def audit(self, references=None, revision=None):
        return source.audit_dependencies(self.metadata, self.repo, revision or self.git("rev-parse", "HEAD"),
                                         self.base, references or {})

    def add_dependency(self, package, *, kind=None, parent="dmnd-client", alias=None):
        self.metadata["packages"].append(package)
        nodes = self.metadata["resolve"]["nodes"]
        nodes.append({"id": package["id"], "deps": []})
        next(node for node in nodes if node["id"] == parent)["deps"].append(
            self.edge(package["id"], kind, alias))

    def vendor_roles(self, prefix="vendor/roles-logic-sv2"):
        package = self.metadata["packages"][1]
        package.update(source=None, manifest_path=f"/workspace/{prefix}/Cargo.toml")
        files = {"Cargo.toml": '[package]\nname = "roles_logic_sv2"\n', "src/lib.rs": "pub fn original() {}\n"}
        for path, content in files.items():
            self.write(prefix + "/" + path, content)
        imported = self.commit()
        references = {"roles_logic_sv2": {"source": source.SRI_SOURCE, "revision": source.SRI_REVISION,
                                         "files": source.reference_files(self.repo, imported, prefix)}}
        return prefix, imported, references

    def test_pinned_git_source_and_protocol_versions_pass(self):
        report = self.audit()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["imports"], [])
        self.assertIn("roles_logic_sv2", report["production_packages"])

    def test_wrong_git_revision_and_same_name_other_origin_fail(self):
        for origin in ("git+" + source.SRI_SOURCE + "#" + "0" * 40,
                       "git+https://github.com/example/new-sri#" + source.SRI_REVISION,
                       "registry+https://github.com/rust-lang/crates.io-index"):
            with self.subTest(origin=origin):
                self.metadata["packages"][1]["source"] = origin
                report = self.audit()
                self.assertFalse(report["passed"])
                self.assertTrue(any("must use new-sri" in error for error in report["errors"]))

    def test_protocol_version_downgrade_fails(self):
        self.metadata["packages"][2]["version"] = "6.0.0"
        report = self.audit()
        self.assertFalse(report["passed"])
        self.assertTrue(any("binary_sv2" in error for error in report["errors"]))

    def test_dev_only_or_build_only_roles_do_not_pass(self):
        for kind in ("dev", "build"):
            with self.subTest(kind=kind):
                self.metadata["resolve"]["nodes"][0]["deps"][0]["dep_kinds"][0]["kind"] = kind
                report = self.audit()
                self.assertFalse(report["passed"])
                self.assertIn("The CLI must have one normal roles_logic_sv2 dependency", report["errors"])

    def test_renamed_transitive_legacy_dependency_fails(self):
        for owner in ("dmnd-pool", "demand-open-source"):
            with self.subTest(owner=owner):
                self.metadata = self.graph()
                self.add_dependency(self.package("hidden-old-code", origin=f"git+https://github.com/{owner}/stratum.git?rev=old#123"),
                                    parent="roles_logic_sv2", alias="new_codec")
                report = self.audit()
                self.assertFalse(report["passed"])
                self.assertTrue(any("old SRI source" in error for error in report["errors"]))

    def test_dev_only_old_source_is_not_a_production_dependency(self):
        self.add_dependency(self.package("legacy-helper", origin="git+https://github.com/dmnd-pool/stratum#123"), kind="dev")
        report = self.audit()
        self.assertTrue(report["passed"], report)
        self.assertNotIn("legacy-helper", report["production_packages"])

    def test_build_old_source_fails(self):
        self.add_dependency(self.package("legacy-build", origin="git+ssh://git@github.com/dmnd-pool/stratum#123"), kind="build")
        self.assertFalse(self.audit()["passed"])

    def test_pristine_import_then_changes_pass_and_record_origin(self):
        prefix, imported, references = self.vendor_roles()
        self.write(prefix + "/src/lib.rs", "pub fn adapted() {}\n")
        changed = self.commit()
        report = self.audit(references, changed)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["imports"][0]["import_commit"], imported)
        self.assertEqual(report["imports"][0]["revision"], source.SRI_REVISION)

    def test_pristine_import_without_changes_passes(self):
        _, imported, references = self.vendor_roles()
        self.assertTrue(self.audit(references, imported)["passed"])

    def test_changes_in_first_import_fail_even_if_later_restored(self):
        prefix, _, references = self.vendor_roles()
        original = copy.deepcopy(references)
        self.write(prefix + "/src/lib.rs", "pub fn already_changed() {}\n")
        self.git("add", "-A")
        self.git("commit", "--amend", "-qm", "ADD modified source without original import")
        self.write(prefix + "/src/lib.rs", "pub fn original() {}\n")
        self.commit()
        report = self.audit(original)
        self.assertFalse(report["passed"])
        self.assertEqual(report["imports"][0]["changes"]["modified"], ["src/lib.rs"])

    def test_incomplete_import_fails_after_remaining_files_added(self):
        prefix, _, references = self.vendor_roles()
        self.git("rm", prefix + "/src/lib.rs")
        self.git("commit", "--amend", "-qm", "ADD incomplete original source")
        self.write(prefix + "/src/lib.rs", "pub fn original() {}\n")
        self.commit()
        report = self.audit(references)
        self.assertFalse(report["passed"])
        self.assertEqual(report["imports"][0]["changes"]["missing"], ["src/lib.rs"])

    def test_roles_outside_vendor_still_need_original_import(self):
        _, _, references = self.vendor_roles("crates/roles")
        report = self.audit(references)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["imports"][0]["path"], "crates/roles")
        self.assertFalse(self.audit()["passed"])

    def test_unknown_vendor_source_fails(self):
        self.write("vendor/helper/Cargo.toml", '[package]\nname = "helper"\n')
        self.commit()
        self.add_dependency(self.package("helper", path="/workspace/vendor/helper/Cargo.toml"))
        report = self.audit()
        self.assertFalse(report["passed"])
        self.assertTrue(any("No trusted original source" in error for error in report["errors"]))

    def test_new_project_module_does_not_require_external_origin(self):
        self.write("crates/helper/Cargo.toml", '[package]\nname = "helper"\n')
        self.commit()
        self.add_dependency(self.package("helper", path="/workspace/crates/helper/Cargo.toml"))
        report = self.audit()
        self.assertTrue(report["passed"], report)
        self.assertIn({"name": "helper", "path": "crates/helper", "at_base": False}, report["project_crates"])

    def test_known_external_source_outside_vendor_requires_import(self):
        self.write("crates/helper/Cargo.toml", '[package]\nname = "helper"\n')
        self.commit()
        self.add_dependency(self.package("helper", path="/workspace/crates/helper/Cargo.toml"))
        report = self.audit({"helper": {}})
        self.assertFalse(report["passed"])

    def test_reusing_a_base_manifest_does_not_skip_roles_import_check(self):
        self.write("crates/existing/Cargo.toml", '[package]\nname = "existing"\n')
        self.base = self.commit()
        prefix, _, references = self.vendor_roles("crates/existing")
        references["roles_logic_sv2"]["files"]["src/lib.rs"] = "wrong-original-hash"
        report = self.audit(references)
        self.assertFalse(report["passed"])
        self.assertEqual(report["imports"][0]["path"], prefix)

    def test_dev_vendor_source_still_requires_original_import(self):
        self.write("vendor/helper/Cargo.toml", '[package]\nname = "helper"\n')
        self.commit()
        self.add_dependency(self.package("helper", path="/workspace/vendor/helper/Cargo.toml"), kind="dev")
        self.assertFalse(self.audit()["passed"])

    def test_uncommitted_or_outside_local_manifest_fails(self):
        for path in ("/workspace/crates/helper/Cargo.toml", "/tmp/external/Cargo.toml",
                     "/workspace/../outside/Cargo.toml"):
            with self.subTest(path=path):
                self.metadata = self.graph()
                self.add_dependency(self.package("helper", path=path))
                self.assertFalse(self.audit()["passed"])

    def test_reference_files_use_commit_content_and_relative_paths(self):
        prefix, imported, references = self.vendor_roles()
        self.write(prefix + "/src/lib.rs", "uncommitted change\n")
        hashes = source.reference_files(self.repo, imported, prefix + "/")
        self.assertEqual(hashes, references["roles_logic_sv2"]["files"])
        self.assertEqual(hashes["src/lib.rs"], hashlib.sha256(b"pub fn original() {}\n").hexdigest())
        self.assertEqual(source.reference_files(self.repo, imported, "absent"), {})
        self.assertIn("Cargo.toml", source.reference_files(self.repo, imported))

    def test_public_checks_accept_relative_repository_paths(self):
        relative = Path(os.path.relpath(self.repo))
        report = source.audit_dependencies(self.metadata, relative, self.base, self.base, {})
        self.assertTrue(report["passed"], report)
        self.assertEqual(source.reference_files(relative, self.base),
                         source.reference_files(self.repo, self.base))

    def test_invalid_metadata_and_unrelated_history_fail_closed(self):
        self.metadata["resolve"] = None
        self.assertFalse(self.audit()["passed"])
        self.metadata = self.graph()
        self.git("checkout", "--orphan", "unrelated")
        self.write("other", "value\n")
        unrelated = self.commit()
        self.assertFalse(self.audit(revision=unrelated)["passed"])


if __name__ == "__main__":
    unittest.main()
