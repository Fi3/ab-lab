"""Check the resolved dependencies and the first import of local source."""
import hashlib
import io
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from lab.host import Fatal, git as _git


SRI_SOURCE = "https://github.com/dmnd-pool/new-sri"
SRI_REVISION = "4f4fcb1d9b035ced1a77cdc020be028f2dca084f"
PROTOCOL_VERSIONS = {
    "binary_sv2": "7.0.0",
    "common_messages_sv2": "9.0.0",
    "mining_sv2": "12.0.0",
    "template_distribution_sv2": "7.0.0",
    "job_declaration_sv2": "10.0.0",
    "framing_sv2": "8.0.0",
}
OLD_SOURCES = {"github.com/demand-open-source/stratum", "github.com/dmnd-pool/stratum"}


def _commit(repo, revision):
    return _git(repo, "rev-parse", "--verify", "--end-of-options",
                revision + "^{commit}").decode().strip()


def _check_history(repo, base, revision):
    ancestor = _git(repo, "merge-base", base, revision).decode().strip()
    if ancestor != base:
        raise ValueError("The evaluated revision does not descend from the benchmark base")


def _prefix(prefix):
    path = PurePosixPath(prefix)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid source prefix: {prefix}")
    return "" if str(path) == "." else str(path)


def _tree_files(repo, revision, prefix):
    args = ["ls-tree", "-rz", "--full-tree", revision]
    if prefix:
        args.extend(["--", ":(literal)" + prefix])
    files = []
    for entry in _git(repo, *args).split(b"\0"):
        if not entry:
            continue
        header, path = entry.split(b"\t", 1)
        _, kind, blob = header.split()
        if kind != b"blob":
            raise ValueError(f"Source contains an unavailable submodule: {path.decode()}")
        relative = PurePosixPath(path.decode()).relative_to(prefix or ".")
        files.append((str(relative), blob))
    return files


def reference_files(repo, revision, prefix=""):
    """Return SHA-256 hashes of all committed files below the source prefix."""
    repo = Path(repo).resolve()
    revision = _commit(repo, revision)
    files = _tree_files(repo, revision, _prefix(prefix))
    if not files:
        return {}
    response = _git(repo, "cat-file", "--batch", input=b"".join(blob + b"\n" for _, blob in files))
    stream = io.BytesIO(response)
    hashes = {}
    for path, blob in files:
        actual_blob, kind, size = stream.readline().split()
        if actual_blob != blob or kind != b"blob":
            raise ValueError(f"Cannot read source file: {path}")
        content = stream.read(int(size))
        if len(content) != int(size) or stream.read(1) != b"\n":
            raise ValueError(f"Incomplete source file: {path}")
        hashes[path] = hashlib.sha256(content).hexdigest()
    return hashes


def _source(source):
    parsed = urlsplit((source or "").removeprefix("git+"))
    name = (parsed.hostname or "") + parsed.path.rstrip("/").removesuffix(".git")
    return name.lower(), parsed.fragment


def _graph(metadata):
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    roots = [key for key in metadata["workspace_members"]
             if packages[key]["name"] == "dmnd-client"]
    if len(roots) != 1:
        raise ValueError("Cargo metadata must contain one dmnd-client workspace package")
    return packages, nodes, roots[0]


def _reachable(nodes, root, kinds):
    reached = set()
    pending = [root]
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        reached.add(key)
        if key not in nodes:
            raise ValueError(f"Cargo metadata has no dependency node for {key}")
        for dependency in nodes[key]["deps"]:
            if any(kind["kind"] in kinds for kind in dependency["dep_kinds"]):
                pending.append(dependency["pkg"])
    return reached


def _check_roles(packages, nodes, normal, references, errors):
    roles = [packages[key] for key in sorted(normal) if packages[key]["name"] == "roles_logic_sv2"]
    if len(roles) != 1:
        errors.append("The CLI must have one normal roles_logic_sv2 dependency")
        return
    package = roles[0]
    source = package.get("source")
    reference = references.get("roles_logic_sv2", {})
    origin = source or reference.get("source")
    name, revision = _source(origin)
    if not source:
        revision = reference.get("revision")
    if name != _source(SRI_SOURCE)[0] or revision != SRI_REVISION:
        errors.append("roles_logic_sv2 must use new-sri at " + SRI_REVISION)
    dependencies = [packages[key] for key in _reachable(nodes, package["id"], {None, "normal"})]
    for name, version in PROTOCOL_VERSIONS.items():
        versions = {item["version"] for item in dependencies if item["name"] == name}
        if versions != {version}:
            errors.append(f"roles_logic_sv2 must use {name} {version}; found {sorted(versions)}")


def _manifest_path(package, repo):
    path = PurePosixPath(package["manifest_path"])
    if ".." in path.parts:
        raise ValueError(f"Invalid local manifest path: {path}")
    for root in (PurePosixPath("/workspace"), PurePosixPath(str(Path(repo).resolve()))):
        if path.is_relative_to(root):
            relative = path.relative_to(root)
            if relative.name != "Cargo.toml":
                break
            return relative
    raise ValueError(f"Local dependency is outside the checked repository: {path}")


def _exists(repo, revision, path):
    return bool(_git(repo, "ls-tree", "-z", revision, "--", ":(literal)" + str(path)))


def _import_commit(repo, revision, base, prefix):
    commits = _git(repo, "rev-list", "--reverse", "--topo-order", base + ".." + revision,
                   "--", ":(literal)" + prefix).decode().splitlines()
    if not commits:
        raise ValueError(f"No source import commit exists for {prefix}")
    return commits[0]


def _file_changes(expected, actual):
    return {"missing": sorted(expected.keys() - actual.keys()),
            "extra": sorted(actual.keys() - expected.keys()),
            "modified": sorted(path for path in expected.keys() & actual.keys()
                               if expected[path] != actual[path])}


def _check_import(package, prefix, reference, repo, revision, base, errors):
    name = package["name"]
    if not reference or not reference.get("files") or not reference.get("source") or not reference.get("revision"):
        errors.append(f"No trusted original source is available for local dependency {name} at {prefix}")
        return {"name": name, "path": prefix, "passed": False}
    imported = _import_commit(repo, revision, base, prefix)
    changes = _file_changes(reference["files"], reference_files(repo, imported, prefix))
    passed = not any(changes.values())
    if not passed:
        errors.append(f"The first import of {name} at {imported} does not match its original source")
    return {"name": name, "path": prefix, "passed": passed, "import_commit": imported,
            "source": reference["source"], "revision": reference["revision"], "changes": changes}


def _check_local(packages, repo, revision, base, references, errors):
    imports = []
    project_crates = []
    for package in sorted(packages.values(), key=lambda item: item["id"]):
        if package.get("source") is not None:
            continue
        manifest = _manifest_path(package, repo)
        prefix = str(manifest.parent)
        known_source = package["name"] in references or package["name"] == "roles_logic_sv2"
        if _exists(repo, base, manifest) and not known_source:
            project_crates.append({"name": package["name"], "path": prefix, "at_base": True})
            continue
        if not _exists(repo, revision, manifest):
            errors.append(f"Local manifest is not committed: {manifest}")
            continue
        if known_source or "vendor" in manifest.parts:
            imports.append(_check_import(package, prefix, references.get(package["name"]),
                                         repo, revision, base, errors))
        else:
            project_crates.append({"name": package["name"], "path": prefix, "at_base": False})
    return imports, project_crates


def audit_dependencies(metadata, repo, revision, base, references):
    """Check production dependencies and preserve source import evidence."""
    repo = Path(repo).resolve()
    result = {"passed": False, "errors": [], "production_packages": [],
              "imports": [], "project_crates": []}
    errors = result["errors"]
    try:
        revision, base = _commit(repo, revision), _commit(repo, base)
        _check_history(repo, base, revision)
        packages, nodes, root = _graph(metadata)
        production = _reachable(nodes, root, {None, "normal", "build"})
        normal = _reachable(nodes, root, {None, "normal"})
        result["production_packages"] = sorted(production)
        for key in sorted(production):
            package = packages[key]
            if _source(package.get("source"))[0] in OLD_SOURCES:
                errors.append(f"Production dependency {package['name']} uses old SRI source: {package['source']}")
            expected = PROTOCOL_VERSIONS.get(package["name"])
            if expected and package["version"] != expected:
                errors.append(f"Production dependency {package['name']} must use {expected}, not {package['version']}")
        _check_roles(packages, nodes, normal, references, errors)
        result["imports"], result["project_crates"] = _check_local(
            packages, repo, revision, base, references, errors)
    except Fatal as error:
        errors.append("Cannot check committed source: " + str(error))
    except (KeyError, TypeError, ValueError) as error:
        errors.append("Invalid dependency evidence: " + str(error))
    result["passed"] = not errors
    return result
