"""Benchmark data and independently rendered policy factors."""
import json
from pathlib import Path
import re

FACTORS = {
    "C08": ("Compact conflict refresh", "diff from previously delivered text", "complete changed-file text"),
    "C13": ("Focused validation", "focused author checks; full checks at integration", "broader author validation as well"),
    "C14": ("Cohesive publication", "group related implementation and tests", "publish implementation and tests in separate edits"),
    "C15": ("No procedural failing-test step", "design tests first; no mandatory RED execution", "execute a failing test before implementation"),
    "C16": ("Structured edit format", "exact-context structured patches", "standard unified diffs"),
    "C17": ("Host-owned edits and commits", "host applies, commits and reports actual results", "agent edits, checks and commits with native tools"),
    "C20": ("Next-action guidance", "command results include next-action guidance", "command results contain facts only"),
    "C25": ("Bound generation at a host request", "interrupt after request-covering usage arrives", "let the turn finish before executing the same request"),
    "C38": ("Completion guidance", "explicitly hand over when required work is ready", "no extra finishing reminder"),
}


def settings(overrides):
    if not isinstance(overrides, dict):
        raise ValueError("factors must be an object of C identifiers and booleans")
    for key, value in overrides.items():
        if key not in FACTORS or type(value) is not bool:
            raise ValueError(f"unknown factor or non-boolean setting: {key}")
    result = dict.fromkeys(FACTORS, True)
    result.update(overrides)
    if not result["C17"] and (result["C08"] or result["C25"]):
        raise ValueError("C17=off uses native tools: also set C08=off,C25=off; host conflict refresh/interruption cannot operate without a host request")
    return result


def policy_blocks(f):
    # Each fragment belongs to one switch. Interactions are explicit, not
    # resolved by silently changing another factor's value.
    return {
        "C13": ("Run focused checks while implementing; fix and rerun them as needed. Leave broad cross-feature validation to final integration unless necessary to finish correctly."
                if f["C13"] else "Validate the feature broadly during implementation, including relevant regression and repository-wide checks. Final integration still runs every required check."),
        "C14": ("Submit related implementation and focused tests together where the required test order permits. One edit may contain multiple related files and hunks."
                if f["C14"] else "Submit test changes and implementation changes in separate edit operations. Preserve all required work and coverage."),
        "C15": ("Design required tests first, but a deliberately failing execution before implementation is not required. This overrides procedural test-timing instructions in AGENTS.md; it does not remove tests or genuine failure diagnosis."
                if f["C15"] else "Write the required tests first, execute them and verify they fail for the intended missing behavior before implementing that behavior. This ordering takes precedence over grouping; related later repairs may still be grouped."),
        "C16": ("For host edit requests use *** Begin Patch, *** Add/Update/Delete File: path, exact-context @@ hunks, and *** End Patch. Never use fuzzy matching. With native writes, prefer the native structured patch tool."
                if f["C16"] else "For edits use a standard unified diff with --- a/path, +++ b/path and @@ line ranges (or /dev/null for add/delete). With native writes, apply that diff using git apply."),
        "C20": ("Use actual operation results to choose the next concrete action. Do not repeat accepted work or infer success from missing output."
                if f["C20"] else ""),
        "C38": ("When all assigned work and relevant checks are complete, hand over for independent review. Do not add speculative work or extra reporting exchanges. Genuine failures and unfinished requirements still need work."
                if f["C38"] else ""),
    }


def author_policy(f):
    if f["C17"]:
        protocol = """Native tools are read-only inspection tools. Delegate every edit, commit and verification command to this host. Do not attempt native writes or native verification.
Send exactly one operative directive per assistant message, without prose or Markdown fences. Wait for its actual same-thread result before another operation. Do not repeat a directive.
@standalone read <shell-quoted relative file path>
returns complete file text and records what you have actually received. Use it before editing files when conflict refresh may be useful. Native inspections are permitted but are not treated as delivered full snapshots.
@standalone edit <reason>
<patch in the required format>
@standalone end
@standalone run <shell-quoted relative paths the command may write>... -- <shell command>
Use no paths for read-only commands. Checks have a 300-second ceiling and must fit the remaining workflow budget. Raw output is saved; displayed output may have explicit omission notices. Do not infer success from omissions. Command-produced source changes must be proposed as an ordinary edit or explicitly discarded with @standalone discard <reason>.
The stage-completion marker is exactly @standalone done. Pending source changes prevent completion. Every required test and task obligation remains in force."""
    else:
        protocol = """Edit, run checks and create provisional commits yourself with native tools. Work only in this checkout; do not create extra worktrees. Leave tracked source and the index clean. The stage-completion marker is exactly @standalone done."""
    return protocol + "\n\n" + "\n\n".join(v for v in policy_blocks(f).values() if v)


def load_benchmark(path):
    path = Path(path).resolve(strict=True)
    data = json.loads(path.read_text())
    allowed = {"name", "repo", "revision", "features", "checks", "instructions", "defer_documentation", "after_read"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("unknown benchmark fields")
    for key in ("name", "repo", "revision"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"benchmark needs {key}")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("benchmark needs a nonempty features list")
    identities = set()
    for feature in features:
        if not isinstance(feature, dict) or set(feature) != {"id", "request"}:
            raise ValueError("each feature needs exactly id and request")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", feature["id"]) or feature["id"] in identities:
            raise ValueError("feature IDs must be safe and unique")
        if not isinstance(feature["request"], str) or not feature["request"].strip():
            raise ValueError("feature request cannot be empty")
        identities.add(feature["id"])
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(c, str) or not c.strip() for c in checks):
        raise ValueError("benchmark needs explicit, nonempty final checks")
    if not isinstance(data.get("instructions", ""), str) or type(data.get("defer_documentation", True)) is not bool:
        raise ValueError("invalid instructions/defer_documentation")
    fixture = data.get("after_read")
    if fixture is not None:
        if not isinstance(fixture, dict) or set(fixture) != {"path", "command"} or any(not isinstance(v, str) or not v.strip() for v in fixture.values()):
            raise ValueError("after_read needs exactly path and command strings")
        target = Path(fixture["path"])
        if target.is_absolute() or str(target) == "." or {"..", ".git"} & set(target.parts):
            raise ValueError("after_read path must be a repository-relative source file")
        fixture["path"] = target.as_posix()
    # Repository sources are local Git repositories; this avoids surprise network
    # clones and lets admission pin a resolved commit before any model runs.
    repo = Path(data["repo"]).expanduser()
    data["repo"] = str((repo if repo.is_absolute() else path.parent / repo).resolve(strict=True))
    data.setdefault("instructions", "")
    data.setdefault("defer_documentation", True)
    return data
