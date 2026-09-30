"""Incremental observer of explicitly named runs; never generates or repairs."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .provider import Usage
from .nested import NestedUsage


def complete_lines(path, offsets):
    if not path.exists():
        return
    with path.open() as stream:
        stream.seek(offsets.get(str(path), 0))
        while line := stream.readline():
            if not line.endswith("\n"):
                break
            offsets[str(path)] = stream.tell()
            yield json.loads(line)


def sample(folders, state):
    rows = []
    for folder in folders:
        entry = state.setdefault(str(folder), {"usage": Usage(), "offsets": {}, "stage": None,
                                               "missing": set(), "turns": set(), "result": None,
                                               "parents": set(), "nested": None})
        if entry["nested"] is None and (folder / "manifest.json").exists():
            manifest = json.loads((folder / "manifest.json").read_text())
            entry["nested"] = NestedUsage(folder / "checkout", manifest["model"], manifest["effort"])
            entry["nested"].started = manifest["created_at_unix"]
        for record in complete_lines(folder / "provider/transport.jsonl", entry["offsets"]):
            event = record.get("event", {})
            identity = event.get("result", {}).get("thread", {}).get("id")
            if identity:
                entry["parents"].add(identity)
            if event.get("method") == "thread/tokenUsage/updated":
                entry["usage"].observe(event.get("params", {}))
        native_errors, native_incomplete = native_counters(folder, entry)
        for stage in complete_lines(folder / "progress.jsonl", entry["offsets"]):
            entry["stage"] = stage["stage"]
        for coverage in complete_lines(folder / "provider/coverage.jsonl", entry["offsets"]):
            entry["turns"].add(coverage["turn_id"])
            # A failed or recovered turn can still have fully observed usage.
            # Its execution error does not by itself leave an accounting gap.
            if not coverage.get("usage_observed_after_last_message"):
                entry["missing"].add(coverage["turn_id"])
        terminal = folder / "result.json"
        if entry["result"] is None and terminal.exists():
            entry["result"] = json.loads(terminal.read_text())
        result = entry["result"] or {}
        usage = result.get("usage", {})
        nested = {"observed_raw_tokens": 0, "errors": [], "incomplete": []}
        if entry["nested"] is not None:
            parents = entry["parents"] | set(entry["usage"].totals)
            entry["nested"].refresh(parents)
            nested = entry["nested"].report(parents)
        gaps = max(len(entry["missing"]), len(usage.get("unpriced_or_incomplete_turns", [])))
        complete = usage.get("measurement_complete", False if gaps or entry["usage"].uncertain else None)
        if native_errors or native_incomplete:
            complete = False
        rows.append({"run": folder.name, "path": str(folder),
            "status": result.get("status", "running" if folder.exists() else "not_started"),
            "stage": entry["stage"], "observed_raw": usage.get("observed_raw_tokens", entry["usage"].raw+nested["observed_raw_tokens"]),
            "nested_raw": nested["observed_raw_tokens"], "nested_errors": nested["errors"],
            "nested_incomplete": nested["incomplete"],
            "native_errors": native_errors, "native_incomplete": native_incomplete,
            "counter_flags": entry["usage"].uncertain, "coverage_gaps": gaps,
            "completed_turns": len(entry["turns"]),
            "measurement_complete": complete,
            "loop_flags": result.get("loop_flags", []),
            "attention": result.get("attention"),
            "error": result.get("error")})
    return {"time_utc": datetime.now(timezone.utc).isoformat(), "runs": rows}


def native_counters(folder, entry):
    """Read the provider's atomic receipt summary, never search unrelated sessions."""
    path = folder / "provider/native-usage.json"
    errors, incomplete = [], []
    try:
        reports = json.loads(path.read_text())
        if not isinstance(reports, dict):
            raise ValueError("native usage summary is not an object")
        for thread, report in reports.items():
            if not isinstance(report, dict) or report.get("thread_id") != thread:
                raise ValueError("native usage summary identity mismatch")
            errors.extend(f"{thread}: {error}" for error in report.get("errors", []))
            incomplete.extend(f"{thread}: {response}" for response in report.get("missing_compactions", []))
            totals = report.get("thread_totals")
            if totals is None or report.get("errors"):
                continue
            if not report.get("validated") or not isinstance(totals, list) or len(totals) != 3:
                raise ValueError("unvalidated native usage totals")
            entry["usage"].observe_native(thread, *totals)
            entry["parents"].add(thread)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    return errors, incomplete


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    state = {}
    while True:
        value = sample(args.runs, state)
        line = json.dumps(value)
        print(line, flush=True)
        with (args.output / "samples.jsonl").open("a") as stream:
            stream.write(line+"\n")
        temporary = args.output / "current.tmp"
        temporary.write_text(json.dumps(value, indent=2)+"\n")
        temporary.replace(args.output / "current.json")
        if args.once or all(row["status"] in ("passed", "failed", "needs_attention") for row in value["runs"]):
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
