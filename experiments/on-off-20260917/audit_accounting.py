"""Read-only, independently summed audit of retained run and native counters."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def audit(folder):
    result = json.loads((folder / "result.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    totals, native_paths, last_message, interruptions, message_phase = {}, {}, {}, {}, {}
    updates, decreases = Counter(), []
    for row in records(folder / "provider/transport.jsonl"):
        event = row["event"]
        params = event.get("params", {})
        turn = params.get("turnId") or params.get("turn", {}).get("id")
        method = event.get("method")
        thread = event.get("result", {}).get("thread")
        if thread and thread.get("path"):
            native_paths[thread["id"]] = thread["path"]
        if row["direction"] == "send" and method == "turn/interrupt":
            interruptions[turn] = row["time"]
        if method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
            last_message[turn] = row["time"]
            message_phase[turn] = params["item"].get("phase")
        if method != "thread/tokenUsage/updated":
            continue
        thread = params["threadId"]
        value = params["tokenUsage"]["total"]
        current = [value[k] for k in ("inputTokens", "outputTokens", "cachedInputTokens")]
        if any(type(v) is not int or v < 0 for v in current):
            raise ValueError("invalid counter")
        old = totals.get(thread, [0, 0, 0])
        if any(a < b for a, b in zip(current, old)):
            decreases.append({"thread": thread, "old": old, "new": current})
            continue
        if current[:2] != old[:2]:
            updates[turn] += 1
        totals[thread] = current
    missing = []
    for turn in result["usage"]["turns"]:
        if turn.get("usage_observed_after_last_message") is True:
            continue
        identity = turn["turn_id"]
        delay = None
        if identity in last_message and identity in interruptions:
            delay = 1000 * (interruptions[identity] - last_message[identity])
        missing.append({k: turn.get(k) for k in ("label", "thread_id", "turn_id", "status", "interrupt_reason")}
                       | {"message_to_interrupt_ms": delay, "fresh_counter_updates": updates[identity],
                          "last_message_phase": message_phase.get(identity)})
    native = []
    for thread, name in native_paths.items():
        path = Path(name)
        count, empty, numeric = 0, 0, []
        metadata_keys = set()
        for row in records(path):
            payload = row.get("payload", {})
            if row["type"] == "response_item":
                metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
                if isinstance(metadata, dict):
                    metadata_keys.update(metadata)
            if row["type"] == "event_msg" and payload.get("type") == "token_count":
                count += 1
                info = payload.get("info")
                if info is None:
                    empty += 1
                else:
                    usage = info["total_token_usage"]
                    numeric.append([usage[k] for k in ("input_tokens", "output_tokens", "cached_input_tokens")])
        last = numeric[-1] if numeric else [0, 0, 0]
        native.append({"thread": thread, "path": name, "sha256": digest(path),
                       "token_events": count, "empty_token_events": empty,
                       "numeric_events": len(numeric), "unique_numeric_totals": len({tuple(n) for n in numeric}),
                       "last_total": last, "matches_transport": last == totals.get(thread, [0, 0, 0]),
                       "message_metadata_keys": sorted(metadata_keys)})
    raw = sum(v[0] + v[1] for v in totals.values())
    return {"run": folder.name, "status": result["status"], "error": result.get("error"),
            "result_sha256": digest(folder / "result.json"),
            "transport_sha256": digest(folder / "provider/transport.jsonl"),
            "observed_raw_tokens": raw, "matches_runner_raw": raw == result["usage"]["observed_raw_tokens"],
            "matches_runner_thread_totals": totals == result["usage"]["thread_totals"],
            "no_unowned_charged_threads": set(totals) <= set(native_paths),
            "counter_decreases": decreases, "measurement_complete": result["usage"]["measurement_complete"],
            "turns": len(result["usage"]["turns"]), "uncovered_turns": missing,
            "uncovered_by_interrupt_reason": dict(Counter(t["interrupt_reason"] for t in missing)),
            "native_histories": native, "comparison_key": result["comparison_key"],
            "source_sha256": manifest["source_sha256"], "duration_seconds": result["duration_seconds"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = [audit(folder) for folder in args.runs]
    report = {"generation": "none", "time_utc": datetime.now(timezone.utc).isoformat(),
              "runs": rows, "observed_raw_sum": sum(row["observed_raw_tokens"] for row in rows),
              "all_comparison_keys_match": len({row["comparison_key"] for row in rows}) == 1,
              "percentage": None, "percentage_reason": "No completed three-versus-three comparison"}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
    for row in rows:
        print(row["run"], row["observed_raw_tokens"], row["uncovered_by_interrupt_reason"])


if __name__ == "__main__":
    main()
