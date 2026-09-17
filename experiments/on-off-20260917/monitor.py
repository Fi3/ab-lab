"""Incremental, read-only benchmark observer; never starts or changes a run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.provider import Usage


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


def sample(root, state):
    rows = []
    for name in ("on-01", "on-02", "on-03", "off-01", "off-02", "off-03"):
        folder = root / name
        entry = state.setdefault(name, {"usage": Usage(), "offsets": {}, "stage": None})
        for record in complete_lines(folder / "provider/transport.jsonl", entry["offsets"]):
            event = record.get("event", {})
            if event.get("method") == "thread/tokenUsage/updated":
                entry["usage"].observe(event.get("params", {}))
        for stage in complete_lines(folder / "progress.jsonl", entry["offsets"]):
            entry["stage"] = stage["stage"]
        terminal = folder / "result.json"
        result = json.loads(terminal.read_text()) if terminal.exists() else {}
        rows.append({"run": name,
            "status": result.get("status", "running" if folder.exists() else "not_started"),
            "stage": entry["stage"],
            "observed_raw": result.get("usage", {}).get("observed_raw_tokens", entry["usage"].raw),
            "counter_flags": entry["usage"].uncertain,
            "measurement_complete": result.get("usage", {}).get("measurement_complete"),
            "error": result.get("error")})
    return {"time_utc": datetime.now(timezone.utc).isoformat(), "runs": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    state = {}
    while True:
        value = sample(args.directory, state)
        line = json.dumps(value)
        print(line, flush=True)
        if args.once:
            return
        with (args.directory / "monitor-samples.jsonl").open("a") as stream:
            stream.write(line + "\n")
        temporary = args.directory / "monitor-current.tmp"
        temporary.write_text(json.dumps(value, indent=2) + "\n")
        temporary.replace(args.directory / "monitor-current.json")
        if all(row["status"] in ("passed", "failed") for row in value["runs"]):
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
