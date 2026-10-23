"""Extract committed source without archive attributes or checkout filters."""
import io
import os
from pathlib import Path, PurePosixPath
import tempfile

from lab.host import git


def _git(repo, *args, **options):
    return git(repo, "--no-replace-objects", *args, **options)


def _path(raw):
    name = os.fsdecode(raw)
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or path.as_posix() != name
            or any(part in (".", "..", ".git") for part in path.parts)):
        raise ValueError(f"Unsafe committed source path: {name!r}")
    return path


def _entries(repo, revision):
    entries = []
    paths = set()
    for record in _git(repo, "ls-tree", "-rz", "--full-tree", revision).split(b"\0"):
        if not record:
            continue
        header, raw = record.split(b"\t", 1)
        mode, kind, blob = header.split()
        path = _path(raw)
        if kind == b"commit":
            raise ValueError(f"Committed source contains an unsupported submodule: {path}")
        if kind != b"blob" or mode not in (b"100644", b"100755", b"120000"):
            raise ValueError(f"Unsupported committed source mode at {path}: {mode.decode()}")
        if path in paths:
            raise ValueError(f"Duplicate committed source path: {path}")
        paths.add(path)
        entries.append((path, mode, blob))
    for path in paths:
        if any(parent in paths for parent in path.parents):
            raise ValueError(f"Committed source path crosses a file or symbolic link: {path}")
    return entries


def _blob(stream, path, expected):
    header = stream.readline().split()
    if len(header) != 3 or header[:2] != [expected, b"blob"] or not header[2].isdigit():
        raise ValueError(f"Cannot read committed source file: {path}")
    size = int(header[2])
    content = stream.read(size)
    if len(content) != size or stream.read(1) != b"\n":
        raise ValueError(f"Incomplete committed source file: {path}")
    return content


def _write_entry(root, path, mode, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == b"120000":
        if not content or b"\0" in content or content.startswith(b"/"):
            raise ValueError(f"Unsafe committed symbolic link: {path}")
        target.symlink_to(os.fsdecode(content))
    else:
        with target.open("xb") as stream:
            stream.write(content)
        target.chmod(0o755 if mode == b"100755" else 0o644)


def _check_links(root, entries):
    root = root.resolve()
    for path, mode, _ in entries:
        if mode != b"120000":
            continue
        try:
            try:
                resolved = (root / path).resolve(strict=True)
            except FileNotFoundError:
                resolved = (root / path).resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Cannot resolve committed symbolic link: {path}") from exc
        if not resolved.is_relative_to(root):
            raise ValueError(f"Committed symbolic link leaves the source tree: {path}")


def extract_tree(repo, revision, destination):
    """Create a new directory with exact committed file bytes, modes, and safe links."""
    repo = Path(repo).resolve()
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise FileExistsError(f"Source destination already exists: {destination}")
    revision = _git(repo, "rev-parse", "--verify", "--end-of-options",
                    revision + "^{commit}").decode().strip()
    entries = _entries(repo, revision)
    response = _git(repo, "cat-file", "--batch",
                    input=b"".join(blob + b"\n" for _, _, blob in entries))
    stream = io.BytesIO(response)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="dmnd-tree-") as temporary:
        root = Path(temporary) / "source"
        root.mkdir()
        for path, mode, blob in entries:
            _write_entry(root, path, mode, _blob(stream, path, blob))
        if stream.read(1):
            raise ValueError("Unexpected data after committed source files")
        _check_links(root, entries)
        root.rename(destination)
    return destination
