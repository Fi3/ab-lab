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
        for stage in complete_lines(folder / "progress.jsonl", entry["offsets"]):
            entry["stage"] = stage["stage"]
        for coverage in complete_lines(folder / "provider/coverage.jsonl", entry["offsets"]):
            entry["turns"].add(coverage["turn_id"])
            if not coverage.get("usage_observed_after_last_message") or coverage.get("error") is not None:
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
        rows.append({"run": folder.name, "path": str(folder),
            "status": result.get("status", "running" if folder.exists() else "not_started"),
            "stage": entry["stage"], "observed_raw": usage.get("observed_raw_tokens", entry["usage"].raw+nested["observed_raw_tokens"]),
            "nested_raw": nested["observed_raw_tokens"], "nested_errors": nested["errors"],
            "nested_incomplete": nested["incomplete"],
            "counter_flags": entry["usage"].uncertain, "coverage_gaps": gaps,
            "completed_turns": len(entry["turns"]),
            "measurement_complete": usage.get("measurement_complete", False if gaps or entry["usage"].uncertain else None),
            "error": result.get("error")})
    return {"time_utc": datetime.now(timezone.utc).isoformat(), "runs": rows}


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
        if args.once or all(row["status"] in ("passed", "failed") for row in value["runs"]):
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
