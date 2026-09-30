"""Offline adapter replay against retained runs; never execute recorded tools.

Example::

    python tests/replay_native_children.py runs/new-benches-{2,3,4,5} \
        --output /tmp/native-before.json
    python tests/replay_native_children.py runs/new-benches-{2,3,4,5} \
        --compare /tmp/native-before.json --expect-fixed \
        --output /tmp/native-after.json

Exact rollout files referenced by the reports, and native children identified by
their transport spawn events, must still be available. Only temporary copies are
read by the provider. No app-server, model, shell command, or benchmark is run.
"""
from collections import deque
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.host import Fatal
from lab.native_usage import NativeUsage
from lab.nested import NestedUsage
from lab.provider import Codex, Usage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def artifact_hashes(run):
    return {str(path.relative_to(run)): digest(path.read_bytes())
            for path in sorted(run.rglob("*")) if path.is_file()}


def load_sources(run, result, transport):
    """Resolve only exact owned thread IDs, without inspecting other histories."""
    reports = result["usage"]["native_usage"]
    paths = {thread: Path(report["path"]) for thread, report in reports.items()}
    folders = {path.parent for path in paths.values()}
    children = set()
    for row in transport:
        item = row["event"].get("params", {}).get("item", {})
        if item.get("type") == "subAgentActivity" and item.get("kind") == "started":
            children.add(item["agentThreadId"])
    for child in children:
        matches = {path for folder in folders for path in folder.glob(f"*-{child}.jsonl")}
        if len(matches) != 1:
            raise ValueError(f"expected exactly one retained rollout for {child}: {matches}")
        paths[child] = matches.pop()
    sources = {thread: (path, path.read_bytes()) for thread, path in paths.items()}
    for thread, report in reports.items():
        data = sources[thread][1][:report["complete_bytes"]]
        if digest(data) != report["complete_prefix_sha256"]:
            raise ValueError(f"saved native rollout prefix hash changed: {paths[thread]}")
    return sources, children


def snapshot_rollout(data, cutoff):
    if cutoff is None:
        return data
    selected = []
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        event = json.loads(line)
        stamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        if stamp.timestamp() > cutoff:
            break
        selected.append(line)
    return b"".join(selected)


def make_provider(run, result, transport, sources, workspace, cutoff):
    """Construct the actual adapter without its process-starting constructor."""
    identity = json.loads((run / "provider/provider.json").read_text())
    p = Codex.__new__(Codex)
    p.repo, p.artifacts = run / "checkout", workspace / "provider"
    p.artifacts.mkdir()
    p.model, p.effort = identity["model"], identity["effort"]
    p.usage, p.native_usage, p.context_usage = Usage(), {}, {}
    p.parent_threads = set(result["usage"]["native_usage"])
    p.turns = copy.deepcopy(result["usage"]["turns"])
    p.missing_turns = copy.deepcopy(result["usage"]["unpriced_or_incomplete_turns"])
    p.pending, p.events = deque(), queue.Queue()
    p.counter, p.active, p.process = 0, None, None
    p.max_raw, p.max_turns, p.deadline = 10**15, 1000000, time.monotonic() + 30
    p.sent = []
    p.send = p.sent.append
    if hasattr(Codex, "observe_notification"):
        from lab.codex_children import NativeChildren
        p.native_children = NativeChildren()

    sessions = workspace / "sessions"
    date = datetime.fromtimestamp(transport[0]["time"], timezone.utc)
    folder = sessions / date.strftime("%Y/%m/%d")
    folder.mkdir(parents=True)
    snapshots = {}
    for thread, (path, data) in sources.items():
        if thread in result["usage"]["native_usage"]:
            data = data[:result["usage"]["native_usage"][thread]["complete_bytes"]]
        target = folder / path.name
        target.write_bytes(snapshot_rollout(data, cutoff))
        snapshots[thread] = target
        if thread in p.parent_threads:
            p.native_usage[thread] = NativeUsage(target, thread, p.repo)
    p.nested = NestedUsage(p.repo, p.model, p.effort, sessions=sessions)
    p.nested.started = transport[0]["time"]
    processes = {"measurement_complete": True, "pending": [], "errors": [],
                 "completed": {}, "abandoned": {}, "artifacts": str(workspace / "children")}
    p.commands = SimpleNamespace(children=SimpleNamespace(
        settle=lambda check: copy.deepcopy(processes), report=lambda: copy.deepcopy(processes)),
        close=lambda: None)
    for row in transport:
        if cutoff is not None and row["time"] > cutoff:
            break
        if row["direction"] != "receive":
            continue
        event = copy.deepcopy(row["event"])
        if hasattr(p, "observe_notification"):
            p.observe_notification(event)
        elif event.get("method") == "thread/tokenUsage/updated":
            p.usage.observe(event["params"])
            p.remember_context(event["params"])
    return p


def replay(run):
    before = artifact_hashes(run)
    result = json.loads((run / "result.json").read_text())
    transport = [json.loads(line) for line in (run / "provider/transport.jsonl").read_text().splitlines()]
    sources, children = load_sources(run, result, transport)
    source_hashes = {str(path): digest(data) for path, data in sources.values()}
    race = str(result.get("error", "")).startswith("incomplete nested token measurement;")
    boundary = next(row for row in reversed(transport)
                    if row["direction"] == "receive" and row["event"].get("method") == "item/tool/call")
    cutoff = boundary["time"] if race else None
    with tempfile.TemporaryDirectory(prefix="native-child-replay-") as directory:
        workspace = Path(directory)
        phase = workspace / "boundary"
        phase.mkdir()
        p = make_provider(run, result, transport, sources, phase, cutoff)
        params = boundary["event"]["params"]
        calls = []
        p.host_tools = {params["threadId"]: {"names": {params["tool"]}, "calls": {},
            "handler": lambda *args: calls.append(args) or {"success": True, "text": "offline replay receipt"}}}
        error = None
        try:
            p.dispatch_host_tool(params["threadId"], params["turnId"], params["tool"],
                                 params["arguments"], params["callId"])
        except Fatal as exc:
            error = str(exc)
        boundary_report = p.report()
        phase = workspace / "full"
        phase.mkdir()
        full = make_provider(run, result, transport, sources, phase, None).report()
    if before != artifact_hashes(run):
        raise AssertionError(f"run artifacts changed during replay: {run}")
    for path, data in sources.values():
        if digest(path.read_bytes()) != digest(data):
            raise AssertionError(f"source rollout changed during replay: {path}")
    keys = ("observed_raw_tokens", "cached_input_tokens", "thread_totals", "measurement_complete")
    return json.loads(json.dumps({"artifact_hashes": before, "rollout_hashes": source_hashes,
            "native_child_ids": sorted(children), "captured_race": race,
            "saved": {key: result["usage"][key] for key in keys},
            "boundary": {"transport_time": boundary["time"], "host_call_id": params["callId"],
                         "handler_calls": len(calls), "dispatch_error": error,
                         **{key: boundary_report[key] for key in keys},
                         "native_children": boundary_report.get("native_children")},
            "full": {**{key: full[key] for key in keys},
                     "native_children": full.get("native_children"),
                     "unpriced_or_incomplete_turns": full["unpriced_or_incomplete_turns"]},
            "originals_unchanged": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--expect-fixed", action="store_true")
    args = parser.parse_args()
    runs = [run.resolve() for run in args.runs]
    output = args.output.resolve()
    if any(output.is_relative_to(run) for run in runs):
        parser.error("--output must be outside the original run directories")
    previous = json.loads(args.compare.read_text()) if args.compare else {}
    reports = {}
    with patch("subprocess.Popen", side_effect=AssertionError("offline replay cannot launch processes")):
        for run in runs:
            value = reports[str(run)] = replay(run)
            if not value["native_child_ids"]:
                assert value["full"]["measurement_complete"] == value["saved"]["measurement_complete"]
                for key in ("observed_raw_tokens", "cached_input_tokens", "thread_totals"):
                    assert value["full"][key] == value["saved"][key], (run, key)
            if args.expect_fixed:
                assert value["boundary"]["dispatch_error"] is None, value["boundary"]["dispatch_error"]
                assert value["boundary"]["handler_calls"] == 1
                if value["captured_race"]:
                    assert not value["full"]["measurement_complete"]
                    native = value["full"]["native_children"]
                    assert native and not native["measurement_complete"], native
            if previous:
                old = previous[str(run)]
                for key in ("artifact_hashes", "rollout_hashes", "saved"):
                    assert value[key] == old[key], (run, key)
                if not value["native_child_ids"]:
                    for key in ("observed_raw_tokens", "cached_input_tokens", "thread_totals",
                                "measurement_complete", "unpriced_or_incomplete_turns"):
                        assert value["full"][key] == old["full"][key], (run, key)
                    for key in ("handler_calls", "dispatch_error"):
                        assert value["boundary"][key] == old["boundary"][key], (run, key)
            print(f"{run.name}: host calls={value['boundary']['handler_calls']}; "
                  f"raw={value['full']['observed_raw_tokens']}; "
                  f"complete={value['full']['measurement_complete']}; originals unchanged")
    output.write_text(json.dumps(reports, indent=2) + "\n")
    print(f"Replay evidence: {output}")


if __name__ == "__main__":
    main()
