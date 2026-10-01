"""Benchmark data and independently rendered policy factors."""
import json
from pathlib import Path
import re

FACTORS = {
    "C08": ("Compact conflict refresh", "diff from previously delivered text", "complete changed-file text"),
    "C13": ("Focused validation", "focused author checks; broad checks when needed", "no extra validation instruction"),
    "C14": ("Cohesive publication", "group related implementation and tests", "no edit-grouping instruction"),
    "C15": ("No procedural failing-test step", "design tests first; no mandatory RED execution", "no test-order override; retain repository and agent rules"),
    "C16": ("Structured edit format", "exact-context structured patches", "no edit-format instruction; host accepts either supported format"),
    "C17": ("Host-owned edits and commits", "host applies, commits and reports actual results", "agent edits, checks and commits with native tools"),
    "C20": ("Next-action guidance", "command results include next-action guidance", "command results contain facts only"),
    "C38": ("Completion guidance", "explicitly finish the turn when required work is ready", "no extra finishing reminder"),
}

WORKFLOW_VERSION = "benchmark-native-delegation-no-integration-v5"
def settings(overrides):
    if not isinstance(overrides, dict):
        raise ValueError("factors must be an object of C identifiers and booleans")
    for key, value in overrides.items():
        if key not in FACTORS or type(value) is not bool:
            raise ValueError(f"unknown factor or non-boolean setting: {key}")
    result = dict.fromkeys(FACTORS, True)
    result.update(overrides)
    if not result["C17"] and result["C08"]:
        raise ValueError("C17=off uses native tools: also set C08=off; host conflict refresh requires host tools")
    return result


def policy_blocks(f):
    # Each fragment belongs to one switch. Interactions are explicit, not
    # resolved by silently changing another factor's value.
    return {
        "C13": ("Run focused checks while implementing; fix and rerun them as needed. Run broad cross-feature validation when necessary to finish correctly."
                if f["C13"] else ""),
        "C14": ("Submit related implementation and focused tests together where the required test order permits. One edit may contain multiple related files and hunks."
                if f["C14"] else ""),
        "C15": ("Design required tests first, but a deliberately failing execution before implementation is not required. This overrides procedural test-timing instructions in AGENTS.md; it does not remove tests or genuine failure diagnosis."
                if f["C15"] else ""),
        "C16": ("For host edit requests use *** Begin Patch, *** Add/Update/Delete File: path, exact-context @@ hunks, and *** End Patch. Never use fuzzy matching. With native writes, prefer the native structured patch tool."
                if f["C16"] else ""),
        "C20": ("Use actual operation results to choose the next concrete action. Do not repeat accepted work or infer success from missing output."
                if f["C20"] else ""),
        "C38": ("When all assigned work and relevant checks are complete, finish this turn. The runner handles any configured independent review. Do not add speculative work or extra reporting exchanges. Genuine failures and unfinished requirements still need work."
                if f["C38"] else ""),
    }


def author_policy(f):
    blocks = []
    if f["C17"]:
        blocks.append("Use the host tools for edits and commands. They commit source changes automatically; the host owns the Git index and history. Native tools are available for read-only inspection.")
    blocks.extend(v for v in policy_blocks(f).values() if v)
    return "\n\n".join(blocks)


def load_benchmark(path):
    path = Path(path).resolve(strict=True)
    data = json.loads(path.read_text())
    allowed = {"name", "repo", "revision", "features", "checks", "after_read", "slopcodebench"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("unknown benchmark fields")
    if "slopcodebench" in data:
        from .slopcodebench import expand
        data = expand(data, path)
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
    return data
