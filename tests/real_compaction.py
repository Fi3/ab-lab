"""Opt-in installed-Codex compaction and accounting test; never unittest-discovered.

Run with an unused --out directory. This makes bounded real subscription calls,
retains transport/usage receipts, and never runs a benchmark or edits its code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import settings
from lab.host import Host, git, save_json, snapshot
from lab.host_tools import HOST_TOOLS, HostTools
from lab.provider import Codex
from lab.workflow import source_hashes


SECONDS, MAX_RAW, MAX_TURNS = 300, 250000, 6
AUTOMATIC_THRESHOLD = 24576
FIXTURE_TESTS = '''import os
import unittest


class PendingRequirementsTests(unittest.TestCase):
    def test_continuity_marker_reaches_real_test_process(self):
        self.assertRegex(os.environ.get("CONTINUITY_MARKER", ""), r"^retain-[0-9a-f]{32}$")

    def test_review_is_still_required(self):
        self.assertEqual(os.environ.get("REVIEW_REQUIRED"), "1")
'''


def events(provider):
    if not provider.log.closed:
        provider.log.flush()
    return [json.loads(line)["event"] for line in
            (provider.artifacts / "transport.jsonl").read_text().splitlines()]


def native_receipts(provider, repo, threads):
    """Independently sum unique owned response receipts, including compaction.

    Only numerical usage/provenance is returned. Native messages, encrypted
    reasoning, account settings and authentication files are never copied.
    """
    paths = {}
    for event in events(provider):
        thread = event.get("result", {}).get("thread", {})
        if thread.get("id") in threads and thread.get("path"):
            paths[thread["id"]] = Path(thread["path"])
    assert set(paths) == set(threads), "missing owned native session paths"
    receipts, compactions = {}, []
    for thread, path in paths.items():
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        metadata = rows[0]
        assert metadata["type"] == "session_meta"
        assert metadata["payload"]["id"] == thread
        assert Path(metadata["payload"]["cwd"]).resolve() == repo
        for row in rows:
            if row["type"] == "token_usage_record":
                payload = row["payload"]
                assert payload["thread_id"] == thread
                usage = payload["usage"]
                for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
                    assert type(usage[field]) is int and usage[field] >= 0
                assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
                key = (thread, payload["response_id"])
                record = {"thread_id": thread, "turn_id": payload["turn_id"],
                          "response_id": payload["response_id"], "usage": usage}
                assert key not in receipts or receipts[key] == record, "conflicting response receipts"
                receipts[key] = record
            elif row["type"] == "compacted":
                response_id = row["payload"].get("compaction_response_id")
                record = receipts.get((thread, response_id))
                assert record is not None, "compaction lacks its exact native response receipt"
                latest = row["payload"].get("latest_token_usage_record", {})
                assert latest.get("response_id") == response_id
                assert latest.get("thread_id") == thread
                assert latest.get("turn_id") == record["turn_id"]
                assert latest.get("usage") == record["usage"]
                assert record["usage"]["total_tokens"] > 0
                compactions.append(record)
    return {"responses": list(receipts.values()), "compactions": compactions,
            "observed_raw_tokens": sum(r["usage"]["total_tokens"] for r in receipts.values()),
            "cached_input_tokens": sum(r["usage"]["cached_input_tokens"] for r in receipts.values())}


def save_native_receipts(out, value):
    """Atomically refresh the receipt snapshot at each check and finalization."""
    temporary = out / (".native-usage-receipts-" + uuid.uuid4().hex + ".tmp")
    try:
        save_json(temporary, value)
        temporary.replace(out / "native-usage-receipts.json")
    finally:
        temporary.unlink(missing_ok=True)


def verify_accounting(provider, repo, threads, out):
    usage = provider.report()
    assert usage["measurement_complete"], "provider marked usage incomplete"
    assert usage["nested"]["observed_raw_tokens"] == 0, "unexpected child generation"
    native = native_receipts(provider, repo, threads)
    save_native_receipts(out, native)
    assert usage["observed_raw_tokens"] == native["observed_raw_tokens"], (
        "provider total differs from independent unique native response sum", usage, native)
    assert usage["cached_input_tokens"] == native["cached_input_tokens"]
    assert 0 < usage["observed_raw_tokens"] < MAX_RAW
    assert len(provider.turns) <= MAX_TURNS
    return native


def run_scenario(provider, repo, threads, out, scenario):
    host = Host(repo, out / (scenario + "-host"), "compaction", "verification", provider.deadline,
                settings({}), command_env=provider.command_env, command_argv=provider.command_argv)
    host_tools = HostTools(host)
    native_limit = provider.auto_compact_limit
    if scenario == "automatic":
        # Configure only the newly created native thread. Restore the host
        # threshold so its preflight cannot substitute manual compaction.
        provider.auto_compact_limit = AUTOMATIC_THRESHOLD
    try:
        thread = provider.start_thread(tools=HOST_TOOLS, tool_handler=host_tools.execute)
    finally:
        provider.auto_compact_limit = native_limit
    threads.append(thread)
    marker = "retain-" + uuid.uuid4().hex
    command = (f"CONTINUITY_MARKER={marker} REVIEW_REQUIRED=1 "
               "python3 -B -m unittest discover -s tests -v")
    prompt = (
        "This is a bounded conversation-continuity test. Do not use tools or edit files yet. "
        f"Remember this exact marker: {marker}. A pending requirement is to preserve review. "
        "When I later say RESUME, execute the fixture test suite using host_run with this "
        "exact command, then summarize its result:\n" + command +
        "\nThis command and its exact marker/review variables remain pending until RESUME, "
        "including across compaction. For now reply exactly READY."
    )
    if scenario == "automatic":
        padding = "".join(
            f"Discarded fixture record {i:04d}: previous check finished; "
            "no pending action remains in this record.\n" for i in range(1800))
        prompt = ("The following archived notes are disposable test padding. "
                  "Do not act on or retain them; retain the pending requirement after them.\n"
                  + padding + "\nEND ARCHIVED NOTES\n" + prompt)
    reply = provider.turn(thread, prompt, scenario + "-seed")
    assert reply.strip() == "READY", "unexpected seed response: " + repr(reply)
    if scenario == "manual":
        provider.compact(thread, "manual")
        assert provider.turns[-1]["kind"] == "compaction"
        assert provider.turns[-1]["status"] == "completed"
        verify_accounting(provider, repo, threads, out)
    reply = provider.turn(thread, "RESUME.", scenario + "-continue")
    assert reply.strip(), "missing final response after compaction"
    observed = events(provider)
    completed = [e["params"] for e in observed if e.get("method") == "item/completed"
                 and e["params"].get("threadId") == thread
                 and e["params"].get("item", {}).get("type") == "contextCompaction"]
    assert completed, scenario + " did not exercise actual compaction"
    manual_requests = [e for e in observed if e.get("method") == "thread/compact/start"
                       and e["params"].get("threadId") == thread]
    assert len(manual_requests) == (1 if scenario == "manual" else 0)
    native = verify_accounting(provider, repo, threads, out)
    compaction_turns = {e["turnId"] for e in completed}
    prices = [r for r in native["compactions"]
              if r["thread_id"] == thread and r["turn_id"] in compaction_turns]
    assert prices, "completed compaction lacks positive owned native usage"
    assert {r["turn_id"] for r in prices} == compaction_turns
    host.unchanged()
    assert not host_tools.unfinished_calls()
    command_receipts = list(host.artifacts.glob("tools/call-*/receipt.json"))
    assert len(command_receipts) == 1, "test suite was not executed exactly once"
    receipt = json.loads(command_receipts[0].read_text())
    assert receipt["command"] == command, "pending requirement changed across compaction"
    assert receipt["exit_code"] == 0 and not receipt["timed_out"]
    output = (command_receipts[0].parent / "stdout.txt").read_text() + (
        command_receipts[0].parent / "stderr.txt").read_text()
    assert "Ran 2 tests" in output and "\nOK\n" in output, output
    return {"scenario": scenario, "thread_id": thread, "marker_retained": True,
            "review_requirement_retained": True, "completed_compactions": len(completed),
            "compaction_raw_tokens": sum(r["usage"]["total_tokens"] for r in prices),
            "framework_tests_passed": 2, "framework_test_receipt": str(command_receipts[0])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scenario", choices=("manual", "automatic", "both"), default="manual")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + SECONDS
    save_json(out / "admission.json", {
        "purpose": "installed Codex compaction, continuation and accounting verification",
        "scenario": args.scenario, "seconds": SECONDS, "max_raw": MAX_RAW,
        "max_turns": MAX_TURNS, "model": "gpt-5.5", "effort": "xhigh",
        "auth": "existing ChatGPT subscription; no API fallback", "benchmark_run": False,
        "automatic_thread_threshold": AUTOMATIC_THRESHOLD if args.scenario != "manual" else None,
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    })
    provider, result, threads = None, {"status": "failed", "scenarios": []}, []
    try:
        repo = out / "checkout"
        repo.mkdir()
        (repo / "README.md").write_text("Isolated compaction continuity fixture.\n")
        (repo / "tests").mkdir()
        (repo / "tests/test_pending_requirements.py").write_text(FIXTURE_TESTS)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Compaction verification")
        git(repo, "config", "user.email", "compaction@example.invalid")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "ADD isolated compaction fixture")
        before = snapshot(repo)
        provider = Codex(repo, out / "provider", "gpt-5.5", "xhigh", deadline, MAX_RAW, MAX_TURNS)
        scenarios = ("manual", "automatic") if args.scenario == "both" else (args.scenario,)
        for scenario in scenarios:
            result["scenarios"].append(run_scenario(provider, repo, threads, out, scenario))
        assert snapshot(repo) == before, "unexpected fixture edits"
        result["status"] = "passed"
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
            try:
                save_native_receipts(out, native_receipts(provider, repo, threads))
            except Exception as exc:
                result["native_receipts_error"] = str(exc)
                result["status"] = "failed"
            if not result["usage"]["measurement_complete"]:
                result["status"] = "failed"
                result.setdefault("error", "final token measurement is incomplete")
        result["duration_seconds"] = time.monotonic() - started
        save_json(out / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "scenarios": result["scenarios"], "output": str(out)}, indent=2))
    return int(result["status"] != "passed")


class ArtifactLifecycleTests(unittest.TestCase):
    """Offline: python3 -m unittest discover -s tests -p real_compaction.py -v."""

    def test_repeated_verification_and_finalization_refresh_same_receipt_snapshot(self):
        class RecordedProvider:
            turns = [{}, {}, {}]

            def report(self):
                return {"measurement_complete": True, "observed_raw_tokens": 123,
                        "cached_input_tokens": 0, "nested": {"observed_raw_tokens": 0}}

        first = {"observed_raw_tokens": 123, "cached_input_tokens": 0, "responses": ["initial"]}
        final = {**first, "responses": ["initial", "compaction", "continuation"]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch(__name__ + ".native_receipts", side_effect=[first, final]):
                verify_accounting(RecordedProvider(), out, ["owned"], out)
                verify_accounting(RecordedProvider(), out, ["owned"], out)
            save_native_receipts(out, final)
            self.assertEqual(json.loads((out / "native-usage-receipts.json").read_text()), final)
            self.assertEqual([p.name for p in out.iterdir()], ["native-usage-receipts.json"])


if __name__ == "__main__":
    raise SystemExit(main())
