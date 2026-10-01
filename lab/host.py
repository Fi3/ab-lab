#!/usr/bin/env python3
"""Repository custody, exact edits, and process execution for native host tools."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
import tempfile
import re
from contextlib import contextmanager
from contextvars import ContextVar

from .environment import clean_env

MAX_FINAL_BYTES = 4 * 1024 * 1024
COMMAND_SECONDS = 300
OUTPUT_CHARS = 12000
_GIT_EXECUTION = ContextVar("agent_lab_git_execution", default=None)


class Rejected(Exception):
    """A proposal grants no valid action; the author may correct it."""


class Fatal(Exception):
    """Retained custody/transport failure; no automatic retry or success ACK."""


def save_json(path, value):
    with Path(path).open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def git_execution(repo, command_argv, env, deadline):
    """Keep Git callbacks from an agent-owned checkout inside its sandbox."""
    token = _GIT_EXECUTION.set((Path(repo).resolve(), command_argv, dict(env), deadline))
    try:
        yield
    finally:
        _GIT_EXECUTION.reset(token)


def git(repo, *args, input=None, extra_env=None):
    argv = ["git", "-C", str(repo), *args]
    env, seconds = clean_env(), 30
    execution = _GIT_EXECUTION.get()
    if execution is not None and Path(repo).resolve() == execution[0]:
        _, wrap, env, deadline = execution
        argv = wrap(argv)
        seconds = min(seconds, deadline - time.monotonic())
    env = dict(clean_env(env), GIT_OPTIONAL_LOCKS="0", **(extra_env or {}))
    # Git may launch hooks, clean filters or fsmonitor commands. Terminate their
    # process group as well as Git when the command or workflow deadline ends.
    with tempfile.TemporaryDirectory(prefix="agent-lab-git-") as directory:
        folder = Path(directory)
        incoming = folder / "stdin" if input is not None else None
        if incoming is not None:
            incoming.write_bytes(input)
        receipt = execute_child(argv, repo, incoming, folder / "stdout", folder / "stderr", seconds, env)
        if receipt["timed_out"] or receipt["cancelled_signal"]:
            raise Fatal(f"git {args[0]} timed out or was interrupted")
        if receipt["exit_code"]:
            raise Fatal(f"git {args[0]} failed ({receipt['exit_code']}): "
                        + (folder / "stderr").read_text(errors="replace"))
        return (folder / "stdout").read_bytes()


def relative_path(repo, value, allow_root=False):
    if not value or "\x00" in value:
        raise Rejected("empty or NUL path")
    path = Path(value)
    if ".." in path.parts or ".git" in path.parts:
        raise Rejected("parent or Git administrative path")
    if path.is_absolute():
        try:
            path = path.relative_to(repo)
        except ValueError as exc:
            raise Rejected("path outside repository") from exc
    if str(path) == "." and not allow_root:
        raise Rejected("file path required")
    current = repo
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise Rejected("symlink path")
    return path.as_posix()


def file_state(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return ("missing", b"", 0)
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", os.readlink(path).encode("utf-8"), stat.S_IMODE(info.st_mode))
    if not stat.S_ISREG(info.st_mode):
        return ("special", b"", stat.S_IMODE(info.st_mode))
    return ("file", path.read_bytes(), stat.S_IMODE(info.st_mode))


def occurrences(lines, block, start):
    # KMP gives linear line-comparison work per search. Repeated hunk searches
    # and list rewrites can still be O(hunks * file size); not a global bound.
    if not block:
        return []
    prefix, matched = [0] * len(block), 0
    for index in range(1, len(block)):
        while matched and not block[index] == block[matched]:
            matched = prefix[matched - 1]
        if block[index] == block[matched]:
            matched += 1
        prefix[index] = matched
    result, matched = [], 0
    for index in range(start, len(lines)):
        while matched and not lines[index] == block[matched]:
            matched = prefix[matched - 1]
        if lines[index] == block[matched]:
            matched += 1
        if matched == len(block):
            result.append(index - len(block) + 1)
            matched = prefix[matched - 1]
    return result


def update_text(before, body):
    try:
        text = before.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Rejected("update requires UTF-8 source") from exc
    if "\r" in text.replace("\r\n", ""):
        raise Rejected("bare CR source is outside the text contract")
    newline = "\r\n" if "\r\n" in text else "\n"
    if newline == "\r\n" and "\n" in text.replace("\r\n", ""):
        raise Rejected("mixed source newline convention")
    terminal = text.endswith("\n") or not text
    lines = text.replace("\r\n", "\n").split("\n")
    if terminal:
        lines.pop()
    if text == "":
        lines = []
    cursor, index, hunks = 0, 0, 0
    while index < len(body):
        header = body[index]
        if header != "@@" and not header.startswith("@@ "):
            raise Rejected("update requires @@ or exact-context @@ header")
        index += 1
        context = header[3:] if header.startswith("@@ ") else ""
        if context:
            matches = occurrences(lines, [context], cursor)
            if len(matches) != 1:
                raise Rejected("context header absent or ambiguous")
            cursor = matches[0] + 1
        old, new, eof = [], [], False
        while index < len(body) and not body[index].startswith("@@"):
            line = body[index]
            index += 1
            if line == "*** End of File":
                eof = True
                if index != len(body) and not body[index].startswith("@@"):
                    raise Rejected("EOF must terminate its hunk")
                break
            if not line or line[0] not in " +-":
                raise Rejected("unsupported hunk line")
            if line[0] in " -":
                old.append(line[1:])
            if line[0] in " +":
                new.append(line[1:])
        if not old:
            if lines or not new:
                raise Rejected("hunk requires nonempty exact old block unless inserting into an empty file")
            matches = [0]
        else:
            matches = occurrences(lines, old, cursor if context else 0)
        if eof:
            matches = [i for i in matches if i + len(old) == len(lines)]
        if len(matches) != 1:
            raise Rejected("old block absent or ambiguous in declared range")
        location = matches[0]
        lines[location:location + len(old)] = new
        cursor = location + len(new)
        hunks += 1
    if not hunks:
        raise Rejected("empty update")
    return (newline.join(lines) + (newline if terminal and lines else "")).encode("utf-8")


def plan_edit(repo, patch):
    if len(patch.encode("utf-8")) > MAX_FINAL_BYTES:
        raise Rejected("patch exceeds 4 MiB")
    # A normal terminal line ending follows the envelope, not another patch
    # body line. Preserve every line inside the envelope exactly.
    lines = patch.replace("\r\n", "\n").removesuffix("\n").split("\n")
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise Rejected("exact patch envelope required")
    changes, seen, index = {}, set(), 1
    while index < len(lines) - 1:
        header = lines[index]
        index += 1
        kind = next((kind for kind in ("Add", "Update", "Delete") if header.startswith(f"*** {kind} File: ")), None)
        if kind is None:
            raise Rejected("unsupported file header")
        name = relative_path(repo, header[len(f"*** {kind} File: "):])
        if name in seen:
            raise Rejected("duplicate normalized file identity")
        seen.add(name)
        before = file_state(repo / name)
        body = []
        while index < len(lines) - 1 and not any(lines[index].startswith(f"*** {k} File: ") for k in ("Add", "Update", "Delete")):
            body.append(lines[index])
            index += 1
        mode = None
        if body and body[0].startswith("*** Mode:"):
            if kind == "Delete" or body[0] not in ("*** Mode: 100644", "*** Mode: 100755"):
                raise Rejected("mode must be 100644 or 100755 on an Add or Update file")
            mode = int(body.pop(0).split()[-1], 8) & 0o777
        if kind == "Add":
            if before[0] != "missing" or any(not line.startswith("+") for line in body):
                raise Rejected("add requires absent regular path and only + content lines")
            content = "".join(line[1:] + "\n" for line in body).encode("utf-8")
            after = ("file", content, mode if mode is not None else 0o644)
        elif kind == "Delete":
            if before[0] != "file" or body:
                raise Rejected("delete requires existing regular file and no body")
            after = ("missing", b"", 0)
        else:
            if before[0] != "file":
                raise Rejected("update requires existing regular file")
            content = before[1] if mode is not None and not body else update_text(before[1], body)
            after = ("file", content, mode if mode is not None else before[2])
        if before != after:
            changes[name] = (before, after)
    if not changes:
        raise Rejected("edit has no actual change" if seen else "empty patch")
    return changes


def snapshot(repo):
    index = git(repo, "ls-files", "--stage", "-z")
    names = []
    for row in index.split(b"\x00"):
        if row:
            metadata, name = row.split(b"\t", 1)
            if metadata.split()[-1] != b"0":
                raise Fatal("unmerged index")
            names.append(name.decode("utf-8"))
    files = {}
    for name in names:
        try:
            relative_path(repo, name)
        except Rejected:
            files[name] = ("unsafe-path", b"", 0)
        else:
            files[name] = file_state(repo / name)
    return {"head": git(repo, "rev-parse", "HEAD").decode().strip(), "index": index,
            "index_flags": git(repo, "ls-files", "-v", "-z"),
            "files": files,
            "untracked": git(repo, "ls-files", "--others", "--exclude-standard", "-z")}


def state_summary(state):
    return {"head": state["head"], "index_sha256": digest(state["index"]),
            "index_flags_sha256": digest(state["index_flags"]),
            "untracked": state["untracked"].decode("utf-8").split("\x00")[:-1],
            "files": {name: {"kind": value[0], "sha256": digest(value[1]), "mode": value[2]}
                      for name, value in state["files"].items()}}


def write_state(path, value):
    if value[0] == "missing":
        path.unlink()
    elif value[0] == "file":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value[1])
        path.chmod(value[2])
    else:
        raise Fatal("cannot publish nonregular source")


def execute_child(argv, cwd, stdin_path, stdout_path, stderr_path, seconds, env):
    if seconds <= 0:
        raise Fatal("workflow deadline exhausted before child")
    started = time.monotonic()
    child, cancelled_signal, timed_out = None, None, False

    def stop_group():
        if child is None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=1)

    def cancelled(signum, _frame):
        nonlocal cancelled_signal
        if cancelled_signal is None:
            cancelled_signal = signum
            stop_group()

    previous = {kind: signal.getsignal(kind) for kind in (signal.SIGTERM, signal.SIGINT)}
    with Path(stdout_path).open("xb") as out, Path(stderr_path).open("xb") as err:
        incoming = Path(stdin_path).open("rb") if stdin_path else subprocess.DEVNULL
        for kind in previous:
            signal.signal(kind, cancelled)
        try:
            child = subprocess.Popen(argv, cwd=cwd, stdin=incoming, stdout=out, stderr=err,
                                     env=env, start_new_session=True)
            if cancelled_signal is not None:
                stop_group()
            try:
                child.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_group()
        finally:
            for kind, handler in previous.items():
                signal.signal(kind, handler)
            if stdin_path:
                incoming.close()
    return {"argv": argv, "exit_code": child.returncode, "timed_out": timed_out, "cancelled_signal": cancelled_signal,
            "duration_seconds": time.monotonic() - started}


def inclusive_lines(text):
    pieces = text.split("\n")
    for piece in pieces[:-1]:
        yield piece + "\n"
    if pieces[-1]:
        yield pieces[-1]


def render_output(text, _path=None):
    if not text:
        return "<empty>\n"
    # Rust char::is_whitespace (Unicode White_Space), excluding Python's
    # additional U+001C..U+001F classification; preserve CR and LF bytes.
    whitespace = "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
    parts, blanks = [], 0
    for line in inclusive_lines(text):
        if not line.strip(whitespace):
            blanks += 1
            if blanks <= 8:
                parts.append(line)
            continue
        if blanks > 8:
            parts.append(f"[standalone compacted {blanks - 8} whitespace-only output lines]\n")
        blanks = 0
        parts.append(line)
    if blanks > 8:
        parts.append(f"[standalone compacted {blanks - 8} whitespace-only output lines]\n")
    rendered, parts = "".join(parts), []
    for line in inclusive_lines(rendered):
        newline = line.endswith("\n")
        content = line[:-1] if newline else line
        if len(content) <= 4096:
            parts.append(line)
        else:
            parts.append(content[:1600] + f"\n[standalone compacted {len(content) - 3200} characters from one long output line]\n" + content[-1600:] + ("\n" if newline else ""))
    rendered = "".join(parts)
    if len(rendered) > OUTPUT_CHARS:
        rendered = rendered[:6000] + f"\n[standalone compacted {len(rendered) - 10000} characters from command output]\n" + rendered[-4000:]
    return rendered if rendered.endswith("\n") else rendered + "\n"



class Host:
    def __init__(self, repo, artifact_dir, feature, stage, deadline, factors, *, command_env=None, command_argv=None):
        from .environment import clean_env
        self.command_env = dict(clean_env(command_env), AGENT_LAB_CHILD="1")
        self.command_argv = command_argv or (lambda argv: argv)
        self.repo = Path(repo).resolve(strict=True)
        self.artifacts = Path(artifact_dir).absolute()
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.feature, self.stage, self.deadline = feature, stage, deadline
        self.factors = factors
        self.seen = {}
        self.activations = {}
        try:
            self.expected = snapshot(self.repo)
            if self.expected["untracked"] or git(self.repo, "status", "--porcelain", "--untracked-files=no"):
                raise Fatal("initial checkout must have clean index/tracked source and no nonignored untracked files")
            if any(value[0] != "file" for value in self.expected["files"].values()):
                raise Fatal("initial tracked sources must be regular files")
        except (Fatal, OSError, ValueError) as exc:
            save_json(self.artifacts / "initialization-error.json", {"repo": str(self.repo), "feature": feature, "stage": stage, "error": str(exc)})
            raise
        self.accepted_commits = []
        self.counter = 0
        self.events_path = self.artifacts / "events.jsonl"
        self.events_path.touch(exist_ok=False)
        self.evidence_path = self.artifacts / "evidence.txt"
        self.evidence_path.touch(exist_ok=False)

    def event(self, kind, **fields):
        with self.events_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps({"kind": kind, **fields}, ensure_ascii=False) + "\n")

    def evidence(self, label, text):
        with self.evidence_path.open("a", encoding="utf-8") as out:
            out.write(f"[{label}]\n{text}\n\n")

    def unchanged(self):
        current = snapshot(self.repo)
        if current != self.expected:
            self.event("unexpected_source_state", expected=state_summary(self.expected), actual=state_summary(current))
            raise Fatal("unexpected source/index/HEAD state; retained without restoration")
        return current

    def operation_dir(self):
        self.counter += 1
        path = self.artifacts / f"operation-{self.counter:04d}"
        path.mkdir()
        return path

    def structured_patch(self, patch):
        # OFF removes the format restriction; dispatch from the actual envelope.
        # Selecting one validator (rather than retrying another) keeps malformed
        # proposals rejected before any source or index mutation.
        return self.factors["C16"] or patch.startswith("*** Begin Patch")

    def apply(self, reason, patch):
        self.unchanged()
        changes = plan_edit(self.repo, patch) if self.structured_patch(patch) else plan_unified(self.repo, patch)
        folder = self.operation_dir()
        (folder / "proposal.txt").write_text(patch, encoding="utf-8")
        before_head = self.expected["head"]
        for name, (before, after) in changes.items():
            relative_path(self.repo, name)
            if file_state(self.repo / name) != before:
                raise Fatal("source drift before publication")
            write_state(self.repo / name, after)
        git(self.repo, "add", "--", *changes)
        message = f"UPDATE {self.feature}: {reason}"
        git(self.repo, "commit", "-m", message, "--", *changes)
        after = snapshot(self.repo)
        commit = after["head"]
        if commit == before_head or git(self.repo, "rev-parse", f"{commit}^").decode().strip() != before_head:
            raise Fatal("accepted commit does not extend exact preceding HEAD")
        expected_files = dict(self.expected["files"])
        for name, (_, value) in changes.items():
            if value[0] == "missing":
                expected_files.pop(name)
            else:
                expected_files[name] = value
        if after["files"] != expected_files or after["untracked"] or git(self.repo, "status", "--porcelain", "--untracked-files=no"):
            raise Fatal("commit left unexplained source effects")
        self.accepted_commits.append(commit)
        self.expected = after
        receipt = {"before_head": before_head, "commit": commit, "paths": list(changes), "reason": reason}
        save_json(folder / "receipt.json", receipt)
        self.event("edit_accepted", **receipt)
        self.evidence("HOST EDIT", f"accepted provisional commit {commit}; changed paths: {', '.join(changes)}")
        return list(changes)

    def activation(self, key, **detail):
        self.activations[key] = self.activations.get(key, 0) + 1
        self.event("factor_activation", factor=key, enabled=self.factors[key], **detail)

    def read(self, name):
        name = relative_path(self.repo, name)
        kind, data, _ = file_state(self.repo / name)
        if kind != "file":
            raise Rejected("read requires a regular file")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Rejected("read requires UTF-8") from exc
        self.seen[name] = text
        self.event("file_delivered", path=name, sha256=digest(data), bytes=len(data))
        return f"Current complete file: {name}\nsha256: {digest(data)}\n{text}"

    def refresh(self, patch):
        # Only actual previously delivered full text can serve as a diff base.
        # A native inspection, a file on disk, or an omitted refresh is not one.
        names = []
        if self.structured_patch(patch):
            names = re.findall(r"^\*\*\* (?:Update|Delete) File: (.+)$", patch, re.M)
        else:
            names = re.findall(r"^--- a/(.+)$", patch, re.M)
        sections = []
        for value in dict.fromkeys(names):
            try:
                name = relative_path(self.repo, value)
                kind, data, _ = file_state(self.repo / name)
                if kind != "file":
                    continue
                current = data.decode("utf-8")
                previous = self.seen.get(name)
                text, mode = refresh_text(name, previous, current, self.factors["C08"])
                sections.append(text)
                if previous is not None and previous != current:
                    self.activation("C08", path=name, representation=mode, rendered_bytes=len(text.encode()))
                if mode in ("full", "diff", "unchanged"):
                    self.seen[name] = current
            except (Rejected, UnicodeDecodeError):
                continue
        return "\n\n".join(sections)


def refresh_text(name, previous, current, compact):
    """Change only the successful changed-file body, as in the C08 contrast.

    Git's bounded unified diff avoids difflib.SequenceMatcher's quadratic worst
    case. Oversize and unavailable diffs have identical behavior in both arms.
    """
    heading = f"File refresh (not a patch to submit): {name}\ncurrent sha256: {digest(current.encode())}\n"
    if previous is None:
        if len(current.encode()) > 8 * 1024:
            return heading + "No previous snapshot; full text omitted. Request host_read for this file.", "omitted"
        return heading + "Current complete file:\n" + current, "full"
    heading += f"previous sha256: {digest(previous.encode())}\n"
    if previous == current:
        return heading + "Unchanged since the last delivered snapshot.", "unchanged"
    with tempfile.TemporaryDirectory(prefix="agent-lab-diff-") as directory:
        safe = relative_path(Path(directory), name)
        before, after = Path(directory) / "previous" / safe, Path(directory) / "current" / safe
        before.parent.mkdir(parents=True)
        after.parent.mkdir(parents=True)
        before.write_text(previous, encoding="utf-8")
        after.write_text(current, encoding="utf-8")
        result = subprocess.run(["git", "diff", "--no-index", "--no-ext-diff", "--no-textconv", "--no-prefix", "--", "previous/"+safe, "current/"+safe], cwd=directory, capture_output=True, timeout=10)
        if result.returncode not in (0, 1):
            return heading + "Diff unavailable; request host_read for this file.", "omitted"
        diff = result.stdout.decode("utf-8")
    if len(diff.encode()) > 48 * 1024:
        return heading + "Diff exceeds 49152 bytes; request host_read for this file.", "omitted"
    if compact:
        return heading + "Changed since the last delivered snapshot:\n" + diff, "diff"
    return heading + "Current complete file:\n" + current, "full"


def plan_unified(repo, patch):
    """Validate standard diffs against a temporary index, never the worktree."""
    if len(patch.encode()) > MAX_FINAL_BYTES:
        raise Rejected("patch exceeds 4 MiB")
    if not patch.endswith("\n"):
        patch += "\n"
    with tempfile.TemporaryDirectory(prefix="agent-lab-index-") as directory:
        env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}

        def run(*args, input=None):
            try:
                return git(repo, *args, input=input, extra_env=env)
            except Fatal as exc:
                raise Rejected(str(exc)) from exc

        run("read-tree", "HEAD")
        run("apply", "--cached", "--check", "--whitespace=nowarn", "-", input=patch.encode())
        run("apply", "--cached", "--whitespace=nowarn", "-", input=patch.encode())
        names = run("diff", "--cached", "--name-only", "--no-renames", "-z").split(b"\0")
        changes = {}
        for raw in filter(None, names):
            name = relative_path(repo, raw.decode())
            before = file_state(repo / name)
            if before[0] not in ("file", "missing"):
                raise Rejected("only regular source files can be edited")
            entry = run("ls-files", "--stage", "--", name)
            if not entry:
                after = ("missing", b"", 0)
            else:
                mode = entry.split()[0]
                if mode not in (b"100644", b"100755"):
                    raise Rejected("symlinks and submodules are unsupported")
                after = ("file", run("show", ":" + name), int(mode, 8) & 0o777)
            if before != after:
                changes[name] = before, after
    if not changes:
        raise Rejected("edit has no actual change")
    return changes
