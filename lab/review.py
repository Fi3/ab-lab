"""Priority-labelled reviews and the configured repair threshold."""
import copy
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager

from .host import COMMAND_SECONDS, execute_child, git, render_output, snapshot, save_json
from .sandbox import CommandSandbox
from .pi_sandbox import PiSandbox
from .environment import clean_env


PRIORITIES = ("P0", "P1", "P2", "P3")
DEFAULT_PRIORITIES = PRIORITIES[:3]
DEFAULT_MAX_REVIEW_LOOPS = 3
BLIND_REVIEW_POLICY = "isolated-review-trees-v2"
REVIEW_TOOLS = [{
    "name": "submit_review",
    "description": "Submit the final review of the current review_id. The runner determines approval from the findings and configured priorities.",
    "inputSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "review_id": {"type": "string"},
            "status": {"type": "string", "enum": ["complete", "incomplete"]},
            "findings": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"priority": {"type": "string", "enum": list(PRIORITIES)},
                               "text": {"type": "string", "minLength": 1}},
                "required": ["priority", "text"]}},
            "incomplete_reason": {"type": ["string", "null"]}},
        "required": ["review_id", "status", "findings", "incomplete_reason"]}},
    {"name": "review_run", "description": "Run a verification command in a fresh writable copy of the current reviewed commit. The original submission and Git metadata remain protected. Build files and temporary tests may be created in the copy; changes to tracked source invalidate the verification. Each call starts with a fresh copy.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}},
                     "required": ["command"], "additionalProperties": False}}]


def normalize_review_loops(value):
    if type(value) is not int or value < 0:
        raise ValueError("max_review_loops must be a non-negative integer")
    return value


def normalize_priorities(value):
    """Canonicalize a nonempty comma-separated string or sequence."""
    values = value.split(",") if isinstance(value, str) else value
    try:
        values = tuple(item.strip().upper() for item in values)
    except (AttributeError, TypeError):
        raise ValueError("review priorities must be a nonempty set of P0, P1, P2, P3") from None
    if not values or any(item not in PRIORITIES for item in values):
        raise ValueError("review priorities must be a nonempty set of P0, P1, P2, P3")
    return tuple(priority for priority in PRIORITIES if priority in values)


class BlindReview:
    """Copy only trees and blobs; original commit objects never enter this repo."""
    def __init__(self, source, base, repo):
        self.source, self.repo = source, Path(repo)
        self.base_tree = git(source, "rev-parse", base + "^{tree}").decode().strip()
        self.base = None
        self.repo.mkdir()
        object_format = git(source, "rev-parse", "--show-object-format").decode().strip()
        self.env = {"GIT_AUTHOR_NAME": "Reviewer", "GIT_AUTHOR_EMAIL": "reviewer@example.invalid",
                    "GIT_COMMITTER_NAME": "Reviewer", "GIT_COMMITTER_EMAIL": "reviewer@example.invalid",
                    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "0"}
        git(self.repo, "init", "--quiet", "--template=", "--initial-branch=review",
            "--object-format=" + object_format, extra_env=self.env)

    def update(self, head):
        tree = git(self.source, "rev-parse", head + "^{tree}").decode().strip()
        objects = git(self.source, "rev-list", "--objects", "--no-object-names", self.base_tree, tree)
        pack = git(self.source, "pack-objects", "--stdout", input=objects)
        git(self.repo, "index-pack", "--stdin", input=pack, extra_env=self.env)
        if self.base is None:
            self.base = git(self.repo, "commit-tree", self.base_tree, "-m", "Baseline", extra_env=self.env).decode().strip()
        self.head = self.base if tree == self.base_tree else git(
            self.repo, "commit-tree", tree, "-p", self.base, "-m", "Submission", extra_env=self.env).decode().strip()
        git(self.repo, "checkout", "--quiet", "--force", "--detach", self.head, extra_env=self.env)
        return self.head

    @contextmanager
    def activate(self, provider, blocked_paths):
        """Switch only the review's working directory and tool permissions."""
        original_repo = provider.repo
        original_sandbox = getattr(provider, "sandbox", None)
        original_env = getattr(provider, "command_env", None)
        try:
            provider.repo = self.repo
            if original_sandbox is not None:
                execution = original_sandbox.execution if isinstance(original_sandbox, PiSandbox) else original_sandbox
                isolated = CommandSandbox(self.repo, execution.codex,
                    blocked_paths=[*execution.blocked_paths, *execution.read_only_blocked_paths, *blocked_paths])
                isolated.shell_environment = {"BASH_ENV": "/dev/null"}
                if isinstance(original_sandbox, PiSandbox):
                    provider.sandbox = copy.copy(original_sandbox)
                    provider.sandbox.repo, provider.sandbox.execution = self.repo, isolated
                else:
                    provider.sandbox = isolated
                provider.command_env = {**(original_env or {}), "BASH_ENV": "/dev/null"}
            yield
        finally:
            provider.repo = original_repo
            if original_sandbox is not None:
                provider.sandbox, provider.command_env = original_sandbox, original_env


def blind_review_paths(root, benchmark, output, private_paths=()):
    """Hide input definitions, experiment artifacts, and their Git stores."""
    private_paths = [Path(path) for path in private_paths]
    paths = [output, Path(benchmark["repo"]), root / "benchmarks", root / "runs",
             root / "experiments", root / ".git", *private_paths]
    shared = {root, *root.parents, Path.home(), *Path.home().parents, Path(tempfile.gettempdir())}
    for folder in {output.parent, *(path.parent for path in private_paths)}:
        if folder not in shared:
            paths.append(folder)
        elif folder.is_dir():
            # Do not hide the runner, installed tools, or all temporary scratch
            # space when outputs/inputs are directly in a shared directory.
            paths.extend(path for path in folder.iterdir() if path.is_dir() and any(
                (path / name).is_file() for name in ("manifest.json", "result.json", "batch-input.json")))
    for folder in {root, Path(benchmark["repo"]), *(path.parent for path in private_paths)}:
        if folder.is_dir():
            probe = subprocess.run(["git", "-C", str(folder), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                   capture_output=True, env=clean_env(), timeout=30)
            if probe.returncode == 0:
                paths.append(Path(probe.stdout.decode().strip()))
    return paths


def validate_review(arguments, review_id, priorities=DEFAULT_PRIORITIES):
    """Validate tool arguments before accepting any finding or approval."""
    required = {"review_id", "status", "findings", "incomplete_reason"}
    if not isinstance(arguments, dict) or set(arguments) != required:
        raise ValueError("submit_review requires exactly review_id, status, findings and incomplete_reason")
    if arguments["review_id"] != review_id:
        raise ValueError("review_id does not identify the current review target")
    if arguments["status"] not in ("complete", "incomplete"):
        raise ValueError("status must be complete or incomplete")
    findings = arguments["findings"]
    if not isinstance(findings, list):
        raise ValueError("findings must be an array")
    for item in findings:
        if (not isinstance(item, dict) or set(item) != {"priority", "text"}
                or item["priority"] not in PRIORITIES or not isinstance(item["text"], str)
                or not item["text"].strip()):
            raise ValueError("each finding requires a P0/P1/P2/P3 priority and nonempty text")
    reason = arguments["incomplete_reason"]
    incomplete = arguments["status"] == "incomplete"
    if incomplete and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("an incomplete review requires a nonempty incomplete_reason")
    if not incomplete and reason is not None:
        raise ValueError("a complete review requires incomplete_reason=null")
    try:
        json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("review arguments must be valid UTF-8 JSON") from exc
    priorities = normalize_priorities(priorities)
    blocking = [dict(item) for item in findings if item["priority"] in priorities]
    advisory = [dict(item) for item in findings if item["priority"] not in priorities]
    decision = {"approved": None if incomplete else not blocking,
                "blocking_findings": blocking, "advisory_findings": advisory}
    if incomplete:
        decision["incomplete_reason"] = reason
    return decision


class ReviewTools:
    """A verdict belongs to one immutable checkout target and one review round."""
    def __init__(self, artifacts, priorities=DEFAULT_PRIORITIES, *, repo=None, deadline=None,
                 command_env=None, command_argv=None):
        self.artifacts = Path(artifacts)
        self.priorities = normalize_priorities(priorities)
        self.repo, self.deadline = repo, deadline
        self.command_env, self.command_argv = command_env, command_argv
        self.review_id = None
        self.decision = None
        self.accepted_arguments = None

    def begin(self, label, head):
        self.label, self.head = label, head
        self.review_id = label + ":" + head
        self.decision = self.accepted_arguments = None
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.receipt = self.artifacts / (label + ".json")
        return self.review_id

    def execute(self, name, arguments, call_id):
        try:
            if name == "review_run" and self.review_id is not None:
                return self._run(arguments, call_id)
            if name != "submit_review" or self.review_id is None:
                raise ValueError("no active submit_review target")
            decision = validate_review(arguments, self.review_id, self.priorities)
            if self.decision is not None:
                if arguments != self.accepted_arguments:
                    raise ValueError("the current review already has a submitted verdict")
            else:
                receipt = {"call_id": call_id, "arguments": arguments, "decision": decision}
                with self.receipt.open("x") as stream:
                    json.dump(receipt, stream, indent=2)
                    stream.write("\n")
                self.decision = decision
                self.accepted_arguments = copy.deepcopy(arguments)
        except ValueError as exc:
            return {"success": False, "text": str(exc) + ". Correct the tool arguments and submit again."}
        return {"success": True, "text": "Review submitted. Finish the review turn; no further inspection is needed."}

    def _run(self, arguments, call_id):
        if (not isinstance(arguments, dict) or set(arguments) != {"command"}
                or not isinstance(arguments["command"], str) or not arguments["command"].strip()
                or "\x00" in arguments["command"]):
            raise ValueError("review_run requires a nonempty command string without NUL")
        try:
            arguments["command"].encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("review command must be valid UTF-8") from exc
        if self.repo is None or self.command_argv is None or self.deadline is None:
            raise ValueError("review command execution is unavailable")
        if self.decision is not None:
            raise ValueError("review already submitted; no further verification is needed")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("review_run requires a call identity")
        folder = self.artifacts / (self.label + "-commands") / hashlib.sha256(call_id.encode()).hexdigest()
        request = {"review_id": self.review_id, "command": arguments["command"], "call_id": call_id}
        if folder.exists():
            incomplete = {"success": False, "text": "The retained review command is incomplete. It was not executed again; inspect its retained artifacts: " + str(folder)}
            try:
                retained_request = json.loads((folder / "request.json").read_text())
            except (OSError, ValueError):
                return incomplete
            if retained_request != request:
                raise ValueError("review command identity collision")
            try:
                return json.loads((folder / "result.json").read_text())
            except (OSError, ValueError):
                return incomplete
        if git(self.repo, "rev-parse", "HEAD").decode().strip() != self.head:
            raise ValueError("submission changed since the current review started")
        folder.mkdir(parents=True)
        save_json(folder / "request.json", request)
        with tempfile.TemporaryDirectory(prefix="agent-lab-review-") as temporary:
            checkout = Path(temporary) / "checkout"
            git(self.repo, "clone", "--quiet", "--no-local", "--no-checkout", str(self.repo), str(checkout))
            git(checkout, "checkout", "--quiet", "--detach", self.head)
            git(checkout, "remote", "remove", "origin")
            before = snapshot(checkout)
            argv = self.command_argv(checkout, ["/bin/sh", "-c", arguments["command"]])
            receipt = execute_child(argv, checkout, None, folder / "stdout.txt", folder / "stderr.txt",
                                    min(COMMAND_SECONDS, self.deadline - time.monotonic()), self.command_env)
            after = snapshot(checkout)
            # Git also compares tracked symlink targets, which the general host
            # snapshot represents only as nonregular-file sentinels.
            tracked_diff = git(checkout, "diff", "--no-ext-diff", "--no-textconv", "--name-only", self.head, "--")
            source_changed = bool(tracked_diff) or any(
                before[key] != after[key] for key in ("head", "index", "index_flags", "files"))
        receipt.update(review_id=self.review_id, command=arguments["command"], source_changed=source_changed)
        save_json(folder / "receipt.json", receipt)
        text = json.dumps(receipt, sort_keys=True)
        for stream in ("stdout", "stderr"):
            text += f"\n{stream}:\n" + render_output((folder / f"{stream}.txt").read_bytes().decode("utf-8", errors="replace"))
        if source_changed:
            text += "\nVerification is invalid: the command changed tracked source or Git state in its copy. The original submission is unchanged."
        success = not source_changed and receipt["exit_code"] == 0 and not receipt["timed_out"] and not receipt["cancelled_signal"]
        result = {"success": success, "text": text}
        save_json(folder / "result.json", result)
        return result


def format_findings(findings):
    return "\n".join(f"- [{item['priority']}] {item['text']}" for item in findings)


def review_instructions(priorities=DEFAULT_PRIORITIES):
    selected = ", ".join(normalize_priorities(priorities))
    return f"""Assess the supplied requirements without adding new obligations. Give concrete evidence and impact for each finding.
Assign priorities by demonstrated impact:
P0: critical blocker requiring immediate correction.
P1: high-impact defect that breaks essential required behavior.
P2: concrete functional defect, regression, or substantial maintainability problem with explained impact.
P3: low-impact nit, cosmetic preference, or optional improvement.
Report all priorities; only {selected} require repairs. Recheck previous findings and repairs for regressions. Missing tests or documentation are findings only when required by the supplied task; explain any demonstrated functional or maintainability defect independently.
Use review_run for checks that need build outputs or temporary test files in the checkout; it runs on a fresh copy of the reviewed commit.
Submit the final verdict using the submit_review tool and the current review_id. Use status=complete with all concrete findings (an empty array means none) and incomplete_reason=null. If evidence is insufficient, use status=incomplete and explain the missing evidence in incomplete_reason; retain any supported findings. The runner determines approval from actual priorities. Finish after the tool accepts the verdict; final prose is not a verdict."""
