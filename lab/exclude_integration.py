"""Audit historical results without changing what they originally measured.

Run ``python -m lab.exclude_integration PATH... --apply`` to attach a derived
pre-integration view. Original counters, outcomes, and source artifacts remain
intact. Missing attribution or source evidence produces an unavailable value.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess


FIELD = "integration_exclusion"
SCHEMA = "agent-behavior-lab/integration-exclusion-v1"
INTEGRATION_STAGES = {"integration-plan", "integration-accept",
                      "integration-plan-compact", "integration-accept-compact"}


def fingerprint(row):
    original = {key: value for key, value in row.items() if key != FIELD}
    return hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def run_records(value):
    """Yield only actual run rows, including arrays and batch exports."""
    if isinstance(value, list):
        for item in value:
            yield from run_records(item)
    elif isinstance(value, dict):
        if value.get("schema") == "agent-behavior-lab/v1" and isinstance(value.get("usage"), dict):
            yield value
        elif isinstance(value.get("results"), list):
            yield from run_records(value["results"])


def _triple(value):
    return (isinstance(value, list) and len(value) == 3 and
            all(type(number) is int and number >= 0 for number in value) and value[2] <= value[0])


def _usage(row, integration_threads):
    usage = row["usage"]
    totals = usage.get("thread_totals", {})
    if not totals or not all(_triple(value) for value in totals.values()):
        raise ValueError("per-thread counters are missing or invalid")
    if not integration_threads <= totals.keys():
        raise ValueError("integration thread counters are missing")
    nested = usage.get("nested", {})
    if nested.get("measurement_complete") is not True:
        raise ValueError("nested usage is not proven complete")
    nested_totals = nested.get("thread_totals", {})
    if not all(_triple(value) for value in nested_totals.values()):
        raise ValueError("nested counters are invalid")
    if sum(value[0] + value[1] for value in nested_totals.values()) != nested.get("observed_raw_tokens"):
        raise ValueError("nested totals do not reconcile")
    if sum(value[2] for value in nested_totals.values()) != nested.get("cached_input_tokens"):
        raise ValueError("nested cached totals do not reconcile")
    if totals.keys() & nested_totals.keys():
        raise ValueError("parent and nested counters overlap")
    if usage.get("native_children", {}).get("threads"):
        raise ValueError("native child attribution cannot be established from these saved counters")
    excluded_nested = set()
    for thread in nested_totals:
        parent = nested.get("threads", {}).get(thread, {}).get("parent_thread_id")
        if parent not in totals:
            raise ValueError("nested thread ownership was not recorded; parent-only subtraction is insufficient")
        if parent in integration_threads:
            excluded_nested.add(thread)
    complete_totals = {**totals, **nested_totals}
    all_raw = sum(value[0] + value[1] for value in complete_totals.values())
    all_cached = sum(value[2] for value in complete_totals.values())
    if all_raw != usage.get("observed_raw_tokens") or all_cached != usage.get("cached_input_tokens"):
        raise ValueError("recorded total and per-thread counters do not reconcile")
    if usage.get("measurement_complete") is not True:
        raise ValueError("original usage measurement is incomplete")

    def counters(threads):
        values = [complete_totals[thread] for thread in threads]
        return {"input_tokens": sum(value[0] for value in values),
                "output_tokens": sum(value[1] for value in values),
                "observed_raw_tokens": sum(value[0] + value[1] for value in values),
                "cached_input_tokens": sum(value[2] for value in values),
                "measurement_complete": True}

    excluded = integration_threads | excluded_nested
    return counters(complete_totals.keys() - excluded), counters(excluded)


def _verify_snapshot(checkout, snapshot, commit, tree):
    """Verify every archived blob and executable bit against the recorded Git tree."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(checkout), *args],
                                       stderr=subprocess.PIPE, timeout=30)
    if git("rev-parse", commit + "^{tree}").decode().strip() != tree:
        raise ValueError("recorded checkpoint commit and tree differ")
    entries = git("ls-tree", "-rz", "--full-tree", commit).split(b"\0")
    expected = {}
    for entry in entries:
        if not entry:
            continue
        head, filename = entry.split(b"\t", 1)
        mode, kind, digest = head.decode().split()
        relative = os.fsdecode(filename)
        if kind != "blob":
            raise ValueError("snapshot contains a non-blob Git entry")
        path = snapshot / relative
        if mode == "120000":
            if not path.is_symlink():
                raise ValueError("snapshot symlink differs: " + relative)
            content = os.fsencode(os.readlink(path))
        else:
            if path.is_symlink() or not path.is_file():
                raise ValueError("snapshot file is absent: " + relative)
            content = path.read_bytes()
            actual_mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            if mode != actual_mode:
                raise ValueError("snapshot mode differs: " + relative)
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if actual != digest:
            raise ValueError("snapshot content differs: " + relative)
        expected[relative] = [mode, digest]
    actual_paths = {str(path.relative_to(snapshot)) for path in snapshot.rglob("*")
                    if path.is_symlink() or path.is_file()}
    if actual_paths != expected.keys():
        raise ValueError("snapshot contains unrecorded files")
    return hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()


def _outcome(row):
    bench = row.get("slopcodebench")
    if not isinstance(bench, dict):
        raise ValueError("no independent pre-integration final checkpoint evaluation was recorded")
    checkpoints = bench.get("checkpoints", [])
    boundaries = row.get("checkpoints", [])
    count = row.get("feature_count")
    if not checkpoints or len(checkpoints) != count or len(boundaries) != count:
        raise ValueError("not every checkpoint has a recorded boundary and evaluation")
    if any(item.get("status") not in ("passed", "failed") for item in checkpoints):
        raise ValueError("not every checkpoint was independently evaluated")
    if [item.get("feature") for item in checkpoints] != [item.get("feature") for item in boundaries]:
        raise ValueError("checkpoint boundaries and evaluations do not correspond")
    last = checkpoints[-1]
    quality = row.get("scb_check", {}).get("measurements", {}).get("after_implementation", {})
    if (quality.get("status") != "completed" or not last.get("tree") or
            last.get("tree") != quality.get("tree") or last.get("commit") != quality.get("commit") or
            last.get("commit") != boundaries[-1].get("head")):
        raise ValueError("final checkpoint and after-implementation measurements do not identify the same source")
    if last.get("include_prior_tests") is not True:
        raise ValueError("the last checkpoint is not proven to include prior tests")
    snapshot = Path(last["snapshot"])
    checkout = Path(row["output"]) / "checkout"
    digest = _verify_snapshot(checkout, snapshot, last["commit"], last["tree"])
    all_passed = all(item.get("strict_pass") is True for item in checkpoints)
    unresolved = any(item.get("status") not in ("approved", "review_skipped") for item in boundaries)
    # Final runner checks occurred only after integration. Never reuse their
    # success for the earlier tree, even if benchmark correctness fully passes.
    status = "failed" if not all_passed else "needs_attention" if unresolved else "unavailable"
    keys = ("status", "strict_pass", "isolated_pass", "core_pass", "strict_pass_rate",
            "isolated_pass_rate", "core_pass_rate", "tests", "commit", "tree", "snapshot")
    return {"status": status, "execution_status": "completed", "all_tests_passed": all_passed,
            "solved": False if not all_passed or unresolved else None,
            "final": {key: last[key] for key in keys if key in last},
            "evaluation_origin": last["feature"], "snapshot_sha256": digest,
            "quality": deepcopy(quality),
            "checks": "unavailable: configured final checks were not run on this pre-integration tree"}


def exclusion(row):
    stages = row.get("stages", [])
    turns = row.get("usage", {}).get("turns", [])
    labeled = [(item.get("stage", ""), item.get("thread_id")) for item in stages]
    labeled += [(item.get("label", ""), item.get("thread_id")) for item in turns]
    integration = {thread for label, thread in labeled if label in INTEGRATION_STAGES and thread}
    result = {"schema": SCHEMA, "original_record_sha256": fingerprint(row),
              "integration_threads": sorted(integration), "usage": None, "outcome": None,
              "duration_seconds": None, "limitations": [
                  "This excludes a historical stage; it does not make the run a native-harness baseline.",
                  "Original usage remains the amount actually consumed; pre-integration wall time is unavailable."]}
    if not integration:
        result["status"] = "not_applicable" if labeled else "unavailable"
        result["reason"] = "integration never started" if labeled else "stage ownership evidence is missing"
        return result
    if integration & {thread for label, thread in labeled if label not in INTEGRATION_STAGES}:
        result["status"] = "unavailable"
        result["reason"] = "an integration thread was also used for another stage"
        return result
    try:
        result["usage"], result["excluded_usage"] = _usage(row, integration)
    except ValueError as exc:
        result["usage_reason"] = str(exc)
    try:
        result["outcome"] = _outcome(row)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result["outcome_reason"] = str(exc)
    result["status"] = "applied" if result["usage"] and result["outcome"] else "partial" if (
        result["usage"] or result["outcome"]) else "unavailable"
    return result


def comparison_view(row):
    """Return a display-only view; never overwrite the historical measurements."""
    correction = row.get(FIELD)
    if not correction or correction.get("status") == "not_applicable":
        return row
    if correction.get("schema") != SCHEMA or correction.get("original_record_sha256") != fingerprint(row):
        raise ValueError("integration exclusion provenance does not match the original result")
    view = dict(row)
    view["usage"] = correction.get("usage") or {"observed_raw_tokens": None,
        "cached_input_tokens": None, "measurement_complete": False}
    view["duration_seconds"] = None
    view["checks"] = None
    view["status"] = "unavailable"
    view["execution_status"] = "unavailable"
    view.pop("error", None)
    view["comparison_key"] = None  # Different workflow; never pool with original/new runs.
    outcome = correction.get("outcome")
    if isinstance(row.get("scb_check"), dict):
        view["scb_check"] = {**row["scb_check"], "measurements": {
            key: value for key, value in row["scb_check"].get("measurements", {}).items()
            if key != "after_assembly"}}
    if isinstance(row.get("slopcodebench"), dict):
        view["slopcodebench"] = {**row["slopcodebench"], "final": None,
            "status": "unavailable", "solved": None, "all_tests_passed": None}
    if outcome:
        view.update({key: outcome[key] for key in ("status", "execution_status")})
        view["slopcodebench"].update({key: outcome[key] for key in ("final", "solved", "all_tests_passed")})
        view["slopcodebench"]["status"] = "completed"
        if outcome["status"] == "failed":
            view["error"] = "Pre-integration SlopCodeBench correctness did not pass at every checkpoint"
    return view


def audit_paths(paths, apply=False):
    report = {"schema": "agent-behavior-lab/integration-exclusion-audit-v1", "files": [],
              "records": [], "counts": {}, "unique_runs": 0}
    seen_paths, identities = set(), set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        value = json.loads(path.read_text())
        rows = list(run_records(value))
        if not rows:
            continue
        changed = False
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in rows:
            correction = exclusion(row)
            changed |= row.get(FIELD) != correction
            row[FIELD] = correction
            identity = row.get("output", row.get("path", str(path)))
            identities.add(identity)
            report["records"].append({"file": str(path), "run": identity,
                "status": correction["status"], "original_raw_tokens": row["usage"].get("observed_raw_tokens"),
                "comparison_raw_tokens": (correction.get("usage") or {}).get("observed_raw_tokens"),
                "excluded_raw_tokens": (correction.get("excluded_usage") or {}).get("observed_raw_tokens"),
                "reason": correction.get("reason"), "usage_reason": correction.get("usage_reason"),
                "outcome_reason": correction.get("outcome_reason")})
        if apply and changed:
            temporary = path.with_name(path.name + ".integration-exclusion.tmp")
            temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        report["files"].append({"path": str(path), "original_sha256": before,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "changed": changed and apply})
    report["counts"] = dict(Counter(row["status"] for row in report["records"]))
    report["unique_runs"] = len(identities)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--apply", action="store_true", help="attach derived metadata; preserve original fields")
    parser.add_argument("--report", type=Path, help="write compact audit provenance")
    args = parser.parse_args()
    paths = sorted({item for path in args.paths for item in
                    (path.rglob("*.json") if path.is_dir() else [path])})
    report = audit_paths(paths, args.apply)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("counts", "unique_runs")}))


if __name__ == "__main__":
    main()
