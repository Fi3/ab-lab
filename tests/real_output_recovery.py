"""Opt-in installed-Codex output recovery check with one disclosed local fault.

The model receives an ordinary fixture request. This script injects one soft
``trailing_whitespace`` result into OutputGuard.observe for the first nonempty
real message delta. It does not forge transport events, usage, or model text.
Actual Codex response receipts must cover the quarantined attempt, compaction,
and continuation before the fixture driver executes its pending host check once.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.config import settings
from lab.context import OutputGuard
from lab.host import Host, git, save_json, snapshot
from lab.host_tools import HostTools
from lab.provider import Codex
from lab.workflow import source_hashes
from real_compaction import events, native_receipts, save_native_receipts


SECONDS, MAX_RAW, MAX_TURNS = 600, 500000, 5
MODEL, EFFORT = "gpt-5.6-sol", "xhigh"
FIXTURE = '''import os
from pathlib import Path

marker = os.environ.get("CONTINUITY_MARKER", "")
assert marker == EXPECTED_MARKER, "continuity marker changed"
assert os.environ.get("REVIEW_REQUIRED") == "1", "review requirement changed"
counter = Path("build/invocations.txt")
assert not counter.exists(), "host command was replayed"
counter.parent.mkdir(exist_ok=True)
counter.write_text(marker + "\\n")
print("OUTPUT_RECOVERY_OK")
'''


def verify_recovery(provider, repo, thread, out, expected, injection):
    """Check actual lifecycle, permission settings, and independent numeric costs."""
    assert injection["count"] == 1, "the local guard fault was not injected exactly once"
    turns = provider.turns
    assert len(turns) == 3, "expected guarded attempt, compaction, and one retry"
    initial, compact, retry = turns
    assert all(row["thread_id"] == thread for row in turns), "recovery changed thread"
    assert initial["turn_id"] == injection["turn_id"]
    assert initial["error"] == "trailing_whitespace"
    assert initial["recovery_eligible"]
    assert initial["status"] in ("completed", "interrupted")
    assert compact.get("kind") == "compaction" and compact["status"] == "completed"
    assert retry["status"] in ("completed", "interrupted")
    assert all(row["usage_observed_after_last_message"] for row in turns)
    assert (provider.artifacts / "turn-0001/reply.txt").read_text().strip() == expected, (
        "quarantined attempt did not complete the expected valid fixture request")

    observed = events(provider)
    streamed = [event["params"] for event in observed
                if event.get("method") == "item/agentMessage/delta"
                and event["params"].get("threadId") == thread
                and event["params"].get("turnId") == initial["turn_id"]
                and event["params"].get("delta")]
    assert streamed and streamed[0]["itemId"] == injection["item_id"]
    assert len(streamed[0]["delta"]) == injection["delta_chars"], (
        "fault was not attached to the first genuine nonempty message delta")
    requests = [event for event in observed if event.get("method") in
                ("turn/start", "thread/compact/start")]
    assert [event["method"] for event in requests] == [
        "turn/start", "thread/compact/start", "turn/start"]
    assert all(event["params"]["threadId"] == thread for event in requests)
    first, last = requests[0]["params"], requests[-1]["params"]
    assert first["permissions"] == last["permissions"] == provider.sandbox.profile(False)
    assert first["approvalPolicy"] == last["approvalPolicy"] == "never"
    assert first["model"] == last["model"] == MODEL
    assert first["effort"] == last["effort"] == EFFORT
    item_types = {event.get("params", {}).get("item", {}).get("type")
                  for event in observed if event.get("method") in ("item/started", "item/completed")
                  and event.get("params", {}).get("threadId") == thread}
    assert item_types <= {"userMessage", "agentMessage", "reasoning", "contextCompaction"}, (
        "unexpected native tool execution", sorted(str(kind) for kind in item_types))

    usage = provider.report()
    assert usage["measurement_complete"], "real provider usage is incomplete"
    assert usage["nested"]["observed_raw_tokens"] == 0, "unexpected child generation"
    native = native_receipts(provider, repo, [thread])
    save_native_receipts(out, native)
    assert usage["observed_raw_tokens"] == native["observed_raw_tokens"], "native total mismatch"
    assert usage["cached_input_tokens"] == native["cached_input_tokens"], "cached total mismatch"
    assert 0 < usage["observed_raw_tokens"] < MAX_RAW
    assert {row["turn_id"] for row in native["responses"]} == {
        row["turn_id"] for row in turns}, "one of the three attempts lacks a genuine numeric receipt"
    assert {row["turn_id"] for row in native["compactions"]} == {compact["turn_id"]}
    return {"same_thread": True, "permissions_preserved": True,
            "attempts_with_native_receipts": len(turns),
            "quarantined_turn_id": initial["turn_id"],
            "compaction_turn_id": compact["turn_id"], "retry_turn_id": retry["turn_id"],
            "independent_raw_tokens": native["observed_raw_tokens"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    source = source_hashes()
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    marker = "retain-" + uuid.uuid4().hex
    injection = {"count": 0, "kind": "local soft OutputGuard.observe result",
                 "reason": "trailing_whitespace", "model_output_modified": False,
                 "transport_or_usage_modified": False}
    save_json(out / "admission.json", {
        "purpose": "real provider receipts and recovery with one locally injected soft output fault",
        "fault_injection": injection.copy(), "natural_runaway_reproduction": False,
        "seconds": SECONDS, "max_raw": MAX_RAW, "max_turns": MAX_TURNS,
        "model": MODEL, "effort": EFFORT,
        "auth": "existing ChatGPT subscription; no API fallback", "benchmark_run": False,
        "source_sha256": source, "script_sha256": script_hash,
        "receipt_auditor_sha256": hashlib.sha256(
            Path(__file__).with_name("real_compaction.py").read_bytes()).hexdigest(),
    })
    provider, thread = None, None
    result = {"status": "failed", "scope": "isolated installed-provider fault injection",
              "natural_runaway_reproduction": False}
    try:
        repo = out / "fixture"
        repo.mkdir()
        (repo / ".gitignore").write_text("build/\n__pycache__/\n")
        (repo / "verify.py").write_text("EXPECTED_MARKER = " + repr(marker) + "\n" + FIXTURE)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Output recovery verification")
        git(repo, "config", "user.email", "output-recovery@example.invalid")
        git(repo, "config", "commit.gpgSign", "false")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "Add isolated output recovery fixture")
        before = snapshot(repo)
        provider = Codex(repo, out / "provider", MODEL, EFFORT,
                         started + SECONDS, MAX_RAW, MAX_TURNS)
        thread = provider.start_thread()
        command = f"CONTINUITY_MARKER={marker} REVIEW_REQUIRED=1 python3 -B verify.py"
        expected = f"READY {marker} REVIEW_REQUIRED=1"
        prompt = (
            "This is a bounded conversation-continuity test. Do not use tools or edit files. "
            "Retain the exact marker and review requirement below across compaction. "
            "The fixture driver will execute its check after your response is fully accounted. "
            "Acknowledge with this exact line:\n" + expected)
        original_observe = OutputGuard.observe

        def inject_once(guard, item_id, delta):
            reason = original_observe(guard, item_id, delta)
            if delta and injection["count"] == 0:
                assert reason is None, "fixture unexpectedly triggered the real output guard"
                active = provider.active
                assert active is not None and active[0] == thread
                injection.update(count=1, thread_id=thread, turn_id=active[1],
                                 item_id=item_id, delta_chars=len(delta),
                                 elapsed_seconds=time.monotonic() - started)
                save_json(out / "fault-injection.json", injection)
                return "trailing_whitespace"
            return reason

        with patch.object(OutputGuard, "observe", inject_once):
            reply = provider.turn(thread, prompt, "output-recovery")
        assert reply.strip() == expected, "retry did not preserve the fixture state"
        assert snapshot(repo) == before, "model changed fixture source or Git state"
        assert not (repo / "build").exists(), "quarantined command executed before recovery"
        result["recovery"] = verify_recovery(provider, repo, thread, out, expected, injection)

        host = Host(repo, out / "host", "output-recovery", "verification", provider.deadline,
                    settings({}), command_env=provider.command_env, command_argv=provider.command_argv)
        host_tools = HostTools(host)
        feedback = host_tools.execute("host_run", {"command": command}, "output-recovery-check")
        assert feedback["success"] and "OUTPUT_RECOVERY_OK" in feedback["text"], feedback
        host.unchanged()
        receipts = list(host.artifacts.glob("tools/call-*/receipt.json"))
        assert len(receipts) == 1, "host command was not executed exactly once"
        receipt = json.loads(receipts[0].read_text())
        assert receipt["exit_code"] == 0 and not receipt["timed_out"]
        assert not host_tools.unfinished_calls()
        assert (repo / "build/invocations.txt").read_text() == marker + "\n"
        assert snapshot(repo) == before, "host command changed fixture source or Git state"
        assert source_hashes() == source, "runner changed during verification"
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == script_hash
        result.update(status="passed", host_command_executions=1,
                      host_receipt=str(receipts[0]), marker_retained=True,
                      review_requirement_retained=True)
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if not (out / "fault-injection.json").exists():
            save_json(out / "fault-injection.json", injection)
        if provider:
            provider.close()
            result["usage"] = provider.report()
            if thread:
                try:
                    native = native_receipts(provider, repo, [thread])
                    save_native_receipts(out, native)
                    assert result["usage"]["observed_raw_tokens"] == native["observed_raw_tokens"]
                    assert result["usage"]["cached_input_tokens"] == native["cached_input_tokens"]
                except Exception as exc:
                    result["native_receipts_error"] = str(exc) or type(exc).__name__
                    result["status"] = "failed"
            if not result["usage"]["measurement_complete"]:
                result["status"] = "failed"
                result.setdefault("error", "final token measurement is incomplete")
        result["duration_seconds"] = time.monotonic() - started
        save_json(out / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "fault_injected": injection["count"] == 1,
                      "natural_runaway_reproduction": False,
                      "raw_tokens": result.get("usage", {}).get("observed_raw_tokens"),
                      "output": str(out)}, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
