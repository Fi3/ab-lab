"""Read-only scb-check observations, kept outside every model conversation."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time

from .environment import clean_env
from .host import Fatal, execute_child, git, save_json, snapshot

PHASES = ("before_changes", "after_implementation", "after_assembly")


def pending():
    return {"status": "incomplete", "measurements": {
        phase: {"phase": phase, "status": "not_run"} for phase in PHASES}}


def environment(executable):
    env = clean_env()
    # Use the checker's installed ast-grep, not an unrelated global executable.
    env["PATH"] = str(Path(executable).parent) + os.pathsep + env.get("PATH", "")
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env.pop("SCB_CHECK_EXTRA_SLOP_RULES", None)
    return env


def prepare(executable, output, deadline, seconds):
    folder = output / "scb-check" / "tool"
    folder.mkdir(parents=True)
    record = {"status": "error", "requested_executable": str(executable)}
    try:
        resolved = shutil.which(str(executable))
        if not resolved:
            raise Fatal("scb-check executable not found; install scb-check or supply --scb-check PATH")
        path = Path(resolved).resolve()
        receipt = execute_child([str(path), "--version"], folder, None,
            folder / "stdout.txt", folder / "stderr.txt",
            min(30, seconds, deadline-time.monotonic()), environment(path))
        record.update(receipt)
        if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
            raise Fatal("scb-check version check failed; inspect scb-check/tool/stderr.txt")
        version = (folder / "stdout.txt").read_text().strip()
        if not version or len(version.splitlines()) != 1:
            raise Fatal("scb-check did not report a version")
        identity = {"executable": str(path), "version": version,
                    "executable_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "seconds_per_check": seconds, "extra_environment_rules": False,
                    "arguments": ["check", ".", "--output-format", "json"]}
        record.update(status="completed", identity=identity)
        return identity
    except (Exception, KeyboardInterrupt) as exc:
        record["error"] = str(exc) or "operator interruption"
        raise
    finally:
        save_json(folder / "result.json", record)


def validate_report(report):
    if not isinstance(report, dict):
        raise ValueError("scb-check report must be a JSON object")
    for key in ("verbosity", "erosion", "cog_erosion"):
        value = report.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"scb-check report has invalid or missing {key}")
    for key in ("files_scanned", "total_loc"):
        value = report.get(key)
        if type(value) is not int or value < (1 if key == "files_scanned" else 0):
            raise ValueError(f"scb-check report has invalid or missing {key}")


def measure(repo, output, phase, identity, deadline):
    folder = output / "scb-check" / phase
    folder.mkdir()
    started = time.monotonic()
    record = {"phase": phase, "status": "error", "started_at_unix": time.time(),
              "artifacts": str(folder)}
    try:
        before = snapshot(repo)
        record.update(commit=before["head"], tree=git(repo, "rev-parse", "HEAD^{tree}").decode().strip())
        if git(repo, "status", "--porcelain"):
            raise Fatal("scb-check requires a clean committed checkpoint")
        path = Path(identity["executable"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != identity["executable_sha256"]:
            raise Fatal("scb-check executable changed during the workflow")
        try:
            receipt = execute_child([str(path), *identity["arguments"]], repo, None,
                folder / "stdout.json", folder / "stderr.txt",
                min(identity["seconds_per_check"], deadline-time.monotonic()), environment(path))
            record.update(receipt)
        finally:
            if snapshot(repo) != before:
                raise Fatal("scb-check changed source, index or history; retain the failed checkpoint")
        if receipt["timed_out"] or receipt["cancelled_signal"] or receipt["exit_code"] not in (0, 1):
            raise Fatal("scb-check failed or timed out; inspect the saved stderr")
        report = json.loads((folder / "stdout.json").read_text())
        validate_report(report)
        record.update(status="completed", report=report,
                      findings_present=receipt["exit_code"] == 1)
    except (Exception, KeyboardInterrupt) as exc:
        record["error"] = str(exc) or "operator interruption"
    record["duration_seconds"] = time.monotonic()-started
    save_json(folder / "result.json", record)
    return record
