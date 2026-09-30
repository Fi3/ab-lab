"""Native host tools with recorded results and no predicted-write protocol."""
import fcntl
import hashlib
import json
import os
import time

from .config import policy_blocks
from .host import (COMMAND_SECONDS, MAX_FINAL_BYTES, Fatal, Rejected, execute_child,
                   file_state, git, relative_path, render_output, snapshot, state_summary)


HOST_TOOLS = [
    {"name": "host_read", "description": "Read a repository file and return its current complete UTF-8 text.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"], "additionalProperties": False}},
    {"name": "host_edit", "description": "Apply and commit a patch to repository files.",
     "inputSchema": {"type": "object", "properties": {
         "patch": {"type": "string"}, "reason": {"type": "string"}},
         "required": ["patch"], "additionalProperties": False}},
    {"name": "host_run", "description": "Run a shell command in the checkout. The host records and automatically commits actual source changes, including new files. The host owns the Git index and history; do not stage, commit, reset, or change index flags in the command.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}},
                     "required": ["command"], "additionalProperties": False}},
]


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _record(path, value):
    """An atomic durable receipt; an incomplete temporary file is never replayed."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(_encoded(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


class HostTools:
    def __init__(self, host):
        self.host = host
        self.artifacts = host.artifacts / "tools"
        self.artifacts.mkdir(exist_ok=True)
        _sync_directory(self.artifacts.parent)

    def unfinished_calls(self):
        result = []
        for folder in sorted(self.artifacts.glob("call-*")):
            if (folder / "result.json").exists():
                continue
            try:
                request = json.loads((folder / "request.json").read_text())
            except (OSError, ValueError):
                request = {}
            try:
                failure = json.loads((folder / "failure.json").read_text())
            except (OSError, ValueError):
                failure = {}
            result.append({"call_id": request.get("call_id"), "name": request.get("name"),
                           "state": failure.get("state", "in_flight"), "artifact": str(folder),
                           "error": failure.get("error")})
        return result

    def execute(self, name, arguments, call_id):
        if not isinstance(call_id, str) or not call_id or "\x00" in call_id:
            raise Fatal("host tool call requires a nonempty call identity")
        request = {"call_id": call_id, "name": name, "arguments": arguments}
        try:
            encoded = _encoded(request)
        except (TypeError, ValueError) as exc:
            raise Fatal("host tool request is not JSON data") from exc
        folder = self.artifacts / ("call-" + hashlib.sha256(call_id.encode()).hexdigest())
        with (self.artifacts / "calls.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if folder.exists():
                try:
                    retained = json.loads((folder / "request.json").read_text())
                except (OSError, ValueError) as exc:
                    raise Fatal(f"unfinished host tool journal; actual state retained: {folder}") from exc
                if _encoded(retained) != encoded:
                    raise Fatal(f"host tool call identity collision; no operation executed: {call_id}")
                if (folder / "result.json").exists():
                    receipt = json.loads((folder / "result.json").read_text())
                    if receipt.get("request_sha256") != hashlib.sha256(encoded).hexdigest():
                        raise Fatal("host tool result does not belong to its recorded request")
                    return receipt["result"]
                raise Fatal(f"unfinished host tool call; inspect retained state before continuing: {folder}")
            unfinished = self.unfinished_calls()
            if unfinished:
                raise Fatal(f"unresolved host tool call prevents new work; actual state retained: {unfinished[0]['artifact']}")
            folder.mkdir()
            _sync_directory(self.artifacts)
            _record(folder / "request.json", request)
            self.host.event("tool_call_started", call_id=call_id, name=name, artifact=str(folder))
            try:
                self.host.unchanged()
                if time.monotonic() >= self.host.deadline:
                    raise Fatal("workflow deadline exhausted before host tool")
                try:
                    self._validate(name, arguments)
                    result = self._dispatch(name, arguments, folder)
                except Rejected as exc:
                    self.host.unchanged()
                    refresh = self.host.refresh(arguments.get("patch", "")) if name == "host_edit" and isinstance(arguments, dict) and isinstance(arguments.get("patch"), str) else ""
                    result = {"success": False, "text": str(exc) + ("\n" + refresh if refresh else "")}
                self.host.unchanged()
                _record(folder / "result.json", {"request_sha256": hashlib.sha256(encoded).hexdigest(), "result": result})
                self.host.event("tool_call_completed", call_id=call_id, name=name, success=result["success"], artifact=str(folder))
                return result
            except BaseException as exc:
                try:
                    retained_state = state_summary(snapshot(self.host.repo))
                except BaseException as state_error:
                    retained_state = {"unavailable": str(state_error)}
                _record(folder / "failure.json", {"state": "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed",
                                                 "error": str(exc), "checkout_state": retained_state})
                raise

    @staticmethod
    def _validate(name, arguments):
        definitions = {item["name"]: item["inputSchema"] for item in HOST_TOOLS}
        if not isinstance(name, str) or name not in definitions:
            raise Rejected("unknown host tool")
        schema = definitions[name]
        if not isinstance(arguments, dict) or set(arguments) - set(schema["properties"]) or not set(schema["required"]) <= set(arguments):
            raise Rejected("host tool arguments do not match its schema")
        if any(not isinstance(value, str) or "\x00" in value for value in arguments.values()):
            raise Rejected("host tool arguments must be strings without NUL")
        try:
            size = sum(len(value.encode("utf-8")) for value in arguments.values())
        except UnicodeEncodeError as exc:
            raise Rejected("host tool arguments must be valid UTF-8 text") from exc
        if size > MAX_FINAL_BYTES:
            raise Rejected("host tool arguments exceed 4 MiB")

    def _dispatch(self, name, arguments, folder):
        if name == "host_read":
            return {"success": True, "text": self.host.read(arguments["path"])}
        if name == "host_edit":
            changed = self.host.apply(arguments.get("reason", "Apply source edit"), arguments["patch"])
            for path in changed:
                self.host.seen.pop(path, None)
            self.host.activation("C16", paths=changed)
            self.host.activation("C17", commit=self.host.expected["head"])
            text = f"Changed files: {', '.join(changed)}. Commit: {self.host.expected['head']}."
            if self.host.factors["C13"]:
                text += " Run at most one relevant focused validation step for this accepted work; further checks and edits remain appropriate for concrete unfinished work or failures."
            if self.host.factors["C38"]:
                text += " When the required work and relevant checks are complete, finish with a concise summary. Do not repeat accepted edits."
            return {"success": True, "text": text}
        return self._run(arguments["command"], folder)

    def _changes(self, before, after):
        if any(after[key] != before[key] for key in ("head", "index", "index_flags")):
            raise Fatal("host command changed HEAD or index; actual state retained")
        files = dict(after["files"])
        for raw in filter(None, after["untracked"].split(b"\x00")):
            name = relative_path(self.host.repo, raw.decode("utf-8"))
            files[name] = file_state(self.host.repo / name)
        if any(value[0] not in ("file", "missing") for value in files.values()):
            raise Fatal("host command produced nonregular source; actual state retained")
        return {name: (before["files"].get(name, ("missing", b"", 0)), value)
                for name, value in files.items() if before["files"].get(name, ("missing", b"", 0)) != value}

    def _publish_command(self, before, after, changes, folder):
        for number, (name, (old, new)) in enumerate(changes.items()):
            retained = folder / "changes" / str(number)
            retained.mkdir(parents=True)
            for label, value in (("before", old), ("after", new)):
                with (retained / label).open("xb") as stream:
                    stream.write(value[1])
                    stream.flush()
                    os.fsync(stream.fileno())
            _record(retained / "identity.json", {"path": name, "before_kind": old[0], "after_kind": new[0],
                                                "before_mode": old[2], "after_mode": new[2]})
        _record(folder / "changes.json", {"paths": list(changes), "before": state_summary(before), "after": state_summary(after)})
        if snapshot(self.host.repo) != after or any(file_state(self.host.repo / name) != new for name, (_, new) in changes.items()):
            raise Fatal("source drift before recording command changes; actual state retained")
        commit = None
        if changes:
            git(self.host.repo, "add", "--all", "--", *changes)
            if git(self.host.repo, "diff", "--cached", "--name-only", "-z"):
                git(self.host.repo, "commit", "-m", f"UPDATE {self.host.feature}: record command-produced source changes")
                commit = git(self.host.repo, "rev-parse", "HEAD").decode().strip()
                if git(self.host.repo, "rev-parse", "HEAD^").decode().strip() != before["head"]:
                    raise Fatal("command change commit does not extend preceding HEAD")
            expected_files = dict(before["files"])
            for name, (_, new) in changes.items():
                if new[0] == "missing":
                    expected_files.pop(name, None)
                else:
                    expected_files[name] = new
            final = snapshot(self.host.repo)
            if final["files"] != expected_files or final["untracked"] or git(self.host.repo, "status", "--porcelain", "--untracked-files=no"):
                raise Fatal("recorded command left unexplained source effects; actual state retained")
            if final["head"] != (commit or before["head"]):
                raise Fatal("unexpected HEAD after recording command changes")
            if commit:
                self.host.accepted_commits.append(commit)
                self.host.activation("C17", commit=commit)
            self.host.expected = final
            for name in changes:
                self.host.seen.pop(name, None)
        return commit

    def _run(self, command, folder):
        before = self.host.unchanged()
        receipt = execute_child(self.host.command_argv(["/bin/sh", "-c", command]), self.host.repo, None,
                                folder / "stdout.txt", folder / "stderr.txt",
                                min(COMMAND_SECONDS, self.host.deadline - time.monotonic()), self.host.command_env)
        _record(folder / "process.json", receipt)
        after = snapshot(self.host.repo)
        changes = self._changes(before, after)
        commit = self._publish_command(before, after, changes, folder)
        receipt.update(command=command, before=state_summary(before), after=state_summary(self.host.expected),
                       changed_paths=list(changes), commit=commit)
        _record(folder / "receipt.json", receipt)
        self.host.event("command_result", receipt=str(folder / "receipt.json"), status=receipt["exit_code"],
                        timed_out=receipt["timed_out"], custody_errors=[])
        self.host.evidence("HOST CHECK", f"command: {command}\nstatus: {receipt['exit_code']}; timed_out: {receipt['timed_out']}\nreceipt: {folder / 'receipt.json'}")
        text = f"Command completed.\nExit code: {receipt['exit_code']}; timed out: {receipt['timed_out']}; cancelled signal: {receipt['cancelled_signal']}."
        for stream in ("stdout", "stderr"):
            text += f"\n{stream}:\n" + render_output((folder / f"{stream}.txt").read_bytes().decode("utf-8", errors="replace"))
        if changes:
            text += f"\nRecorded source changes: {', '.join(changes)}. " + (f"Commit: {commit}." if commit else "Git content unchanged; filesystem metadata retained in receipt.")
        if self.host.factors["C20"]:
            self.host.activation("C20")
            text += "\n" + policy_blocks(self.host.factors)["C20"]
        if self.host.factors["C38"]:
            text += "\nWhen all required work and checks are complete, finish with a concise summary."
        return {"success": receipt["exit_code"] == 0 and not receipt["timed_out"] and not receipt["cancelled_signal"], "text": text}
