#!/usr/bin/env python3
"""Prepare the fixed client revision and separate dependency source evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

from benchmarks.dmnd_sri_baseline import PUBLIC_PATHS, build_commit
from benchmarks.dmnd_sri_source import SRI_REVISION as ROLES_REVISION
from benchmarks.dmnd_sri_source import SRI_SOURCE as ROLES_URL
from benchmarks.dmnd_sri_source import reference_files
from lab.host import Fatal, git, save_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT / ".benchmarks" / "dmnd-new-sri" / "repo"
PUBLIC_REPO = DEFAULT_REPO.parent / "public-v2" / "repo"
BASE_URL = "https://github.com/dmnd-pool/dmnd-client.git"
BASE_REVISION = "4c2a7341d3a9e1b1b46d063770a1e2c3bff005d7"
SCHEMA = "dmnd-new-sri-lab/v1"
PUBLIC_SCHEMA = "dmnd-new-sri-lab/v2"
PUBLIC_REVISION = "42350eabdea86c63a0113a53009c77992d00566f"


def clean_repository(repo):
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"{repo} has modified tracked files")
    if git(repo, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError(f"{repo} has incomplete Git history")


def verify_repository(repo, revision):
    clean_repository(repo)
    if git(repo, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError(f"{repo} is not at pinned revision {revision}")


def fetch_revision(repo, source, revision):
    subprocess.run(["git", "-C", str(repo), "fetch", "--no-tags", str(source), revision],
                   check=True, capture_output=True, timeout=300,
                   env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))


def pinned_repository(path, url, revision, source=None):
    if path.exists():
        verify_repository(path, revision)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix="dmnd-prepare-") as temporary:
        checkout = Path(temporary) / "repo"
        checkout.mkdir()
        git(checkout, "init", "-q")
        git(checkout, "remote", "add", "origin", url)
        # Fetch only the fixed revision and its ancestors. Local future branches
        # and tags must not expose a completed migration to a model.
        fetch_revision(checkout, source or "origin", revision)
        git(checkout, "checkout", "-q", "--detach", revision)
        verify_repository(checkout, revision)
        checkout.rename(path)


def dependency_sources(repo):
    lock = tomllib.loads(git(repo, "show", BASE_REVISION + ":Cargo.lock").decode())
    result = {"roles_logic_sv2": {"source": ROLES_URL, "revision": ROLES_REVISION}}
    for name in ("demand-sv2-connection", "demand-share-accounting-ext"):
        packages = [package for package in lock.get("package", []) if package["name"] == name]
        if len(packages) != 1:
            raise ValueError(f"Cargo.lock must contain one {name} package")
        match = re.fullmatch(r"git\+(https://[^?#]+)(?:\?[^#]+)?#([0-9a-f]{40})",
                             packages[0].get("source", ""))
        if not match:
            raise ValueError(f"Cargo.lock does not pin the Git source for {name}")
        result[name] = {"source": match[1], "revision": match[2]}
    return result


def dependency_reference(folder, name, identity):
    checkout = folder / "sources" / name
    pinned_repository(checkout, identity["source"], identity["revision"])
    files = reference_files(checkout, identity["revision"])
    evidence = {"repo": str(checkout), "revision": identity["revision"], "prefix": ""}
    if "Cargo.toml" not in files:
        raise ValueError(f"dependency source has no Cargo.toml: {name}")
    return {**identity, "files": files, "evidence": evidence}


def load_setup(path, identities, revision=None):
    setup = json.loads(path.read_text(encoding="utf-8"))
    revisions = {SCHEMA: BASE_REVISION, PUBLIC_SCHEMA: PUBLIC_REVISION}
    if (not isinstance(setup, dict) or not isinstance(setup.get("schema"), str)
            or setup["schema"] not in revisions) or (
            setup.get("source"), setup.get("base"), setup.get("revision")) != (
                BASE_URL, BASE_REVISION, revisions.get(setup.get("schema"))) or (
                    revision is not None and setup.get("revision") != revision):
        raise ValueError(f"prepared source identity changed: {path}")
    references = setup.get("references", {})
    if not isinstance(references, dict) or set(references) != set(identities):
        raise ValueError(f"prepared dependency names changed: {path}")
    for name, identity in identities.items():
        reference = references[name]
        if not isinstance(reference, dict) or any(
                reference.get(key) != value for key, value in identity.items()):
            raise ValueError(f"prepared dependency identity changed: {name}")
        evidence = reference.get("evidence")
        if not isinstance(evidence, dict) or evidence.get("revision") != identity["revision"] or (
                evidence.get("prefix") != "" or not isinstance(evidence.get("repo"), str)):
            raise ValueError(f"prepared dependency source evidence is invalid: {name}")
        files = reference.get("files")
        if not isinstance(files, dict) or "Cargo.toml" not in files or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in files.values()):
            raise ValueError(f"prepared dependency file evidence is invalid: {name}")
    return setup


def prepare(repo=DEFAULT_REPO, source=None):
    repo = Path(repo).resolve()
    if source is not None:
        source = Path(source).resolve()
        clean_repository(source)
    pinned_repository(repo, BASE_URL, BASE_REVISION, source)
    identities = dependency_sources(repo)
    receipt = repo.parent / "setup.json"
    if receipt.exists():
        load_setup(receipt, identities, BASE_REVISION)
        return repo
    references = {name: dependency_reference(repo.parent, name, identity)
                  for name, identity in identities.items()}
    setup = {"schema": SCHEMA, "source": BASE_URL, "base": BASE_REVISION, "revision": BASE_REVISION,
             "references": references}
    with tempfile.TemporaryDirectory(dir=repo.parent, prefix="dmnd-setup-") as temporary:
        pending = Path(temporary) / "setup.json"
        save_json(pending, setup)
        pending.rename(receipt)
    return repo


def build_public_commit(repo):
    return build_commit(Path(repo), BASE_REVISION)


def verify_public_repository(repo, revision=None):
    revision = PUBLIC_REVISION if revision is None else revision
    verify_repository(repo, revision)
    if revision != PUBLIC_REVISION or build_public_commit(repo) != revision:
        raise ValueError("The prepared public transport contract changed")


def prepare_public(repo=PUBLIC_REPO, source=None):
    repo = Path(repo).resolve()
    if source is not None:
        source = Path(source).resolve()
        clean_repository(source)
    receipt = repo.parent / "setup.json"
    if repo.exists():
        verify_public_repository(repo)
        load_setup(receipt, dependency_sources(repo), PUBLIC_REVISION)
        return repo
    if receipt.exists():
        raise FileExistsError(f"Prepared setup already exists without its repository: {receipt}")
    upstream = prepare(DEFAULT_REPO, source)
    original = load_setup(upstream.parent / "setup.json", dependency_sources(upstream), BASE_REVISION)
    repo.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repo.parent, prefix="dmnd-public-") as temporary:
        checkout = Path(temporary) / "repo"
        pinned_repository(checkout, BASE_URL, BASE_REVISION, upstream)
        revision = build_public_commit(checkout)
        if revision != PUBLIC_REVISION:
            raise ValueError("The public transport contract does not match its pinned revision")
        git(checkout, "checkout", "-q", "--detach", revision)
        verify_public_repository(checkout)
        setup = {**original, "schema": PUBLIC_SCHEMA, "revision": revision}
        pending = Path(temporary) / "setup.json"
        save_json(pending, setup)
        if receipt.exists():
            raise FileExistsError(f"Prepared setup already exists without its repository: {receipt}")
        checkout.rename(repo)
        pending.rename(receipt)
    return repo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--source", type=Path, help="local repository with the fixed client revision")
    parser.add_argument("--public", action="store_true", help="prepare the v2 public transport contract")
    args = parser.parse_args()
    try:
        if args.public:
            print(prepare_public(args.repo or PUBLIC_REPO, args.source))
        else:
            print(prepare(args.repo or DEFAULT_REPO, args.source))
    except subprocess.CalledProcessError as exc:
        parser.exit(1, exc.stderr.decode(errors="replace") + "\n")
    except (Fatal, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
