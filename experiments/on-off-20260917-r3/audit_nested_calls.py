"""Read-only evidence query for the retained third batch; no agent execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run_root = root / "runs/on-off-20260917-r3"
    runs = {name: json.loads((run_root / name / "result.json").read_text())
            for name in ("on-01", "on-02", "on-03")}
    owners = {str((run_root / name / "checkout").resolve()): name for name in runs}
    histories = []
    for path in sorted(Path("/home/user/.codex/sessions/2026/09/17").glob("*.jsonl")):
        with path.open() as stream:
            first = json.loads(stream.readline())
            meta = first.get("payload", {})
            if first.get("type") != "session_meta" or meta.get("cwd") not in owners:
                continue
            rows = [json.loads(line) for line in stream]
        owner, identity = owners[meta["cwd"]], meta["id"]
        parent = identity in runs[owner]["usage"]["thread_totals"]
        totals, previous, problems, plans, contexts = [], [0, 0], [], set(), []
        for row in rows:
            p = row.get("payload", {})
            if row["type"] == "turn_context":
                context = {key: p.get(key) for key in ("model", "effort")}
                if context not in contexts:
                    contexts.append(context)
            if row["type"] != "event_msg" or p.get("type") != "token_count" or not p.get("info"):
                continue
            plan = (p.get("rate_limits") or {}).get("plan_type")
            if plan:
                plans.add(plan)
            info = p["info"]
            current = [info["total_token_usage"][key] for key in ("input_tokens", "output_tokens")]
            if current == previous:
                continue
            last = [info["last_token_usage"][key] for key in ("input_tokens", "output_tokens")]
            if any(a < b for a, b in zip(current, previous)):
                problems.append("cumulative counter decreased")
            if current != [a+b for a, b in zip(previous, last)]:
                problems.append("counter increment differs from last-response usage")
            totals.append({"timestamp": row["timestamp"], "cumulative": current,
                           "last_response": last, "last_response_raw": sum(last)})
            previous = current
        histories.append({"run": owner, "id": identity, "path": str(path),
            "sha256": digest(path), "source": meta.get("source"), "counted_by_runner": parent,
            "contexts": contexts, "reported_plan_types": sorted(plans),
            "final_cumulative_raw": sum(previous),
            "distinct_last_response_sum": sum(t["last_response_raw"] for t in totals),
            "reconciliation_problems": problems, "token_updates": totals if not parent else []})
    extra = [h for h in histories if not h["counted_by_runner"]]
    report = {"generation": "none", "time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "All local histories dated 2026-09-17 with exact owned checkout cwd; not a claim about unlinked other directories",
        "histories": histories, "extra_conversations": len(extra),
        "extra_raw": sum(h["final_cumulative_raw"] for h in extra),
        "extra_reconciliation_passes": all(not h["reconciliation_problems"] and
            h["final_cumulative_raw"] == h["distinct_last_response_sum"] for h in extra),
        "runs": [{"run": name, "runner_raw": r["usage"]["observed_raw_tokens"],
            "extra_raw": sum(h["final_cumulative_raw"] for h in extra if h["run"] == name),
            "combined_observed_raw": r["usage"]["observed_raw_tokens"] + sum(
                h["final_cumulative_raw"] for h in extra if h["run"] == name),
            "incomplete_parent_turns": len(r["usage"]["unpriced_or_incomplete_turns"])}
            for name, r in runs.items()]}
    report["combined_observed_raw_sum"] = sum(r["combined_observed_raw"] for r in report["runs"])
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "histories"}, indent=2))


if __name__ == "__main__":
    main()
