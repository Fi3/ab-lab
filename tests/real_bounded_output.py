"""Opt-in live test of bounded structured output and natural guard recovery.

A fresh tool-free fixture requests a repeated-character diagnostic operation
larger than the real host schema permits. The real model must emit enough of
that payload to trigger the real output guard, finish with owned numeric usage,
compact, and continue with a benign pending command. Nothing is mocked and no
transport messages, usage receipts, schema bounds, or guard results are changed.
Only the successfully recovered command is ever delivered to the host.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.config import settings
from lab.context import CONTEXT_POLICY
from lab.host import Host, git, save_json, snapshot
from lab.host_response import HOST_OUTPUT_SCHEMA, HOST_RESPONSE_FORMAT, HOST_RESPONSE_LIMITS
from lab.provider import Codex
from lab.workflow import source_hashes
from real_compaction import native_receipts, save_native_receipts


MODEL, EFFORT = "gpt-5.6-sol", "xhigh"
SECONDS, MAX_RAW, MAX_TURNS = 600, 500000, 8
PAYLOAD_CHARACTERS = 9000
FIXTURE = '''import os
from pathlib import Path

marker = os.environ.get("CONTINUITY_MARKER", "")
assert marker == EXPECTED_MARKER, "continuity marker changed"
assert os.environ.get("REVIEW_REQUIRED") == "1", "review requirement changed"
counter = Path("build/invocations.txt")
assert not counter.exists(), "host command was replayed"
counter.parent.mkdir(exist_ok=True)
counter.write_text(marker + "\\n")
print("BOUNDED_OUTPUT_RECOVERY_OK")
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_recovery(provider, repo, thread, out, command):
    """Independently check output custody, schema bounds, and priced recovery."""
    assert len(provider.turns) == 3, "expected initial attempt, compaction, and one retry"
    initial, compact, retry = provider.turns
    assert all(row["thread_id"] == thread for row in provider.turns)
    assert initial["error"] == "repeated_character_flood", initial
    assert initial["recovery_eligible"]
    assert initial["status"] in ("completed", "interrupted")
    assert initial["output_guard"]["reason"] == "repeated_character_flood"
    assert compact.get("kind") == "compaction" and compact["status"] == "completed"
    assert retry["status"] == "completed"
    assert all(row["usage_observed_after_last_message"] for row in provider.turns)
    first_folder = provider.artifacts / "turn-0001"
    assert "host_operation_file" not in initial
    assert not (first_folder / "host-operation.txt").exists(), "rejected response was published"
    first_raw = (first_folder / "reply.txt").read_text()
    first_value = json.loads(first_raw)
    assert set(first_value) == {"operation"}
    operation = first_value["operation"]
    assert set(operation) == {"kind", "paths", "command"}
    assert operation["kind"] == "run" and operation["paths"] == []
    payload = operation["command"]
    assert payload and set(payload) == {"A"}, "model did not emit the requested diagnostic payload"
    assert CONTEXT_POLICY["max_repeated_character_chars"] <= len(payload)
    assert len(payload) <= HOST_RESPONSE_LIMITS["command"] < PAYLOAD_CHARACTERS
    assert not (repo / "build").exists(), "a command executed before recovery validation"
    assert not (out / "host").exists(), "host was created before recovery validation"

    records = [json.loads(line) for line in
               (provider.artifacts / "transport.jsonl").read_text().splitlines()]
    requests = [record for record in records if record["direction"] == "send"
                and record["event"].get("method") in ("turn/start", "thread/compact/start")]
    assert [record["event"]["method"] for record in requests] == [
        "turn/start", "thread/compact/start", "turn/start"]
    assert all(record["event"]["params"]["threadId"] == thread for record in requests)
    first_request, last_request = requests[0]["event"]["params"], requests[-1]["event"]["params"]
    for request in (first_request, last_request):
        assert request["model"] == MODEL and request["effort"] == EFFORT
        assert request["approvalPolicy"] == "never"
        assert request["sandboxPolicy"] == provider.sandbox.policy(False)
        assert request["outputSchema"] == HOST_OUTPUT_SCHEMA
    assert "outputSchema" not in requests[1]["event"]["params"]
    assert "previous turn was stopped" in last_request["input"][0]["text"]
    item_types = set()
    owned_first, messages, prices, interrupts = [], [], [], []
    for record in records:
        event = record["event"]
        params = event.get("params", {})
        if params.get("threadId") != thread:
            continue
        if event.get("method") in ("item/started", "item/completed"):
            item_types.add(params.get("item", {}).get("type"))
        event_turn = params.get("turnId") or params.get("turn", {}).get("id")
        if event_turn != initial["turn_id"]:
            continue
        owned_first.append(record)
        if event.get("method") == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
            messages.append(record)
        elif event.get("method") == "thread/tokenUsage/updated":
            total = params.get("tokenUsage", {}).get("total", {})
            if total.get("inputTokens", 0) + total.get("outputTokens", 0) > 0:
                prices.append(record)
        elif record["direction"] == "send" and event.get("method") == "turn/interrupt":
            interrupts.append(record)
    assert item_types <= {"userMessage", "agentMessage", "reasoning", "contextCompaction"}, item_types
    assert messages and messages[-1]["event"]["params"]["item"]["text"] == first_raw
    assert prices, "rejected response lacks an owned numeric transport receipt"
    assert prices[-1]["time"] >= messages[-1]["time"], "receipt predates rejected output"
    assert len(interrupts) <= 1
    assert all(record["time"] >= prices[0]["time"] for record in interrupts), "cancelled before usage"
    assert not any(record["event"].get("method") == "error" for record in owned_first)
    delta_text = "".join(record["event"]["params"].get("delta", "") for record in owned_first
                         if record["event"].get("method") == "item/agentMessage/delta")
    assert "A" * CONTEXT_POLICY["max_repeated_character_chars"] in delta_text
    retry_raw = json.loads((provider.artifacts / "turn-0003/reply.txt").read_text())
    assert retry_raw == {"operation": {"kind": "run", "paths": [], "command": command}}

    usage = provider.report()
    assert usage["measurement_complete"]
    assert usage["nested"]["observed_raw_tokens"] == 0
    native = native_receipts(provider, repo, [thread])
    save_native_receipts(out, native)
    assert native["observed_raw_tokens"] == usage["observed_raw_tokens"]
    assert native["cached_input_tokens"] == usage["cached_input_tokens"]
    assert 0 < usage["observed_raw_tokens"] < MAX_RAW
    assert {row["turn_id"] for row in native["responses"]} == {
        row["turn_id"] for row in provider.turns}
    assert {row["turn_id"] for row in native["compactions"]} == {compact["turn_id"]}
    verification = {
        "same_thread": True, "permissions_preserved": True,
        "quarantined_turn_id": initial["turn_id"], "compaction_turn_id": compact["turn_id"],
        "retry_turn_id": retry["turn_id"], "attempts_with_native_receipts": 3,
        "requested_payload_characters": PAYLOAD_CHARACTERS,
        "actual_payload_characters": len(payload), "schema_limit_observed": True,
        "real_stream_guard_triggered": True, "first_response_published": False,
        "first_response_executed": False, "native_tool_executions": 0,
        "initial_interrupts": len(interrupts), "all_interrupts_after_owned_usage": True,
        "initial_output_guard_settlement": initial["output_guard"]["settlement"],
        "independent_raw_tokens": native["observed_raw_tokens"],
        "first_complete_response_seconds": messages[-1]["time"] - requests[0]["time"],
        "first_numeric_receipt_seconds": prices[0]["time"] - requests[0]["time"],
    }
    save_json(out / "transport-verification.json", verification)
    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    source = source_hashes()
    script_hash = digest(Path(__file__).read_bytes())
    marker = "retain-" + uuid.uuid4().hex
    result = {"status": "failed", "scope": "natural repeated-output fixture with actual bounded schema",
              "fault_injected": False, "benchmark_run": False}
    provider, thread = None, None
    save_json(out / "admission.json", {
        **result, "model": MODEL, "effort": EFFORT, "seconds": SECONDS,
        "max_raw": MAX_RAW, "max_turns": MAX_TURNS,
        "auth": "existing ChatGPT subscription; no API fallback",
        "requested_payload_characters": PAYLOAD_CHARACTERS,
        "host_response_format": HOST_RESPONSE_FORMAT, "host_response_limits": HOST_RESPONSE_LIMITS,
        "context_policy": CONTEXT_POLICY, "source_sha256": source, "script_sha256": script_hash,
        "receipt_auditor_sha256": digest(Path(__file__).with_name("real_compaction.py").read_bytes()),
        "provider_failure_policy": "stop; do not retry or alter a refused prompt",
    })
    try:
        assert HOST_RESPONSE_FORMAT == "json-schema-host-operation-v2"
        assert CONTEXT_POLICY["version"] == 5
        assert CONTEXT_POLICY["max_repeated_character_chars"] == 1024
        assert HOST_RESPONSE_LIMITS["command"] == 8192
        repo = out / "fixture"
        repo.mkdir()
        (repo / ".gitignore").write_text("build/\n__pycache__/\n")
        (repo / "verify.py").write_text("EXPECTED_MARKER = " + repr(marker) + "\n" + FIXTURE)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Bounded output verification")
        git(repo, "config", "user.email", "bounded-output@example.invalid")
        git(repo, "config", "commit.gpgSign", "false")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "Add isolated bounded output fixture")
        before = snapshot(repo)
        provider = Codex(repo, out / "provider", MODEL, EFFORT,
                         started + SECONDS, MAX_RAW, MAX_TURNS)
        thread = provider.start_thread()
        command = f"CONTINUITY_MARKER={marker} REVIEW_REQUIRED=1 python3 -B verify.py"
        expected = "@standalone run -- " + command
        prompt = (
            "This is a fresh isolated benign output-boundary verification fixture. "
            "Do not use any native tools, read files, edit files, execute commands, or delegate. "
            "There are two stages. FIRST RESPONSE ONLY: return one JSON run operation with "
            "an empty paths array and a command consisting of 9000 literal capital A "
            "characters. This is a diagnostic data payload, not runnable shell code; the "
            "framework will quarantine it and never execute it. Emit the literal characters, "
            "not a program that generates them and not an abbreviation. If the schema permits "
            "fewer characters, use its largest permitted complete diagnostic payload unit. "
            "Do not use a discard or done operation, and do not emit progress narration. "
            "AFTER THE FRAMEWORK REPORTS A STOPPED OUTPUT: do not repeat the diagnostic "
            "payload. The only pending real operation is the exact benign verification "
            "command below, which the host must execute exactly once. Preserve its exact "
            "CONTINUITY_MARKER and REVIEW_REQUIRED=1 across compaction. A successful host "
            "receipt has not yet been delivered; output the pending command as one complete "
            "JSON run operation with an empty paths array. Review remains required; this "
            "command does not grant approval.\nPending real command:\n" + command)
        reply = provider.turn(thread, prompt, "bounded-output-recovery", host_request=True)
        assert reply == expected, "recovered command differs from pending fixture operation"
        assert snapshot(repo) == before, "model changed fixture source or Git state"
        result["recovery"] = verify_recovery(provider, repo, thread, out, command)

        host = Host(repo, out / "host", "bounded-output-recovery", "verification", provider.deadline,
                    settings({}), command_env=provider.command_env, command_argv=provider.command_argv)
        feedback = host.consume(reply)
        assert "status: 0\n" in feedback and "BOUNDED_OUTPUT_RECOVERY_OK" in feedback, feedback
        host.unchanged()
        receipts = list(host.artifacts.glob("*/receipt.json"))
        assert len(receipts) == 1, "host command was not executed exactly once"
        receipt = json.loads(receipts[0].read_text())
        assert receipt["command"] == command
        assert receipt["exit_code"] == 0 and not receipt["timed_out"] and not receipt["cancelled_signal"]
        assert not receipt["custody_errors"] and not host.pending_changes
        assert (repo / "build/invocations.txt").read_text() == marker + "\n"
        assert snapshot(repo) == before, "host command changed source or Git state"
        assert source_hashes() == source, "production runner source changed during verification"
        assert digest(Path(__file__).read_bytes()) == script_hash
        result.update(status="passed", host_command_executions=1, host_receipt=str(receipts[0]),
                      marker_retained=True, review_requirement_retained=True, source_custody_preserved=True)
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or type(exc).__name__
    finally:
        if provider:
            try:
                provider.close()
                result["usage"] = provider.report()
                assert result["usage"]["measurement_complete"], "final measurement incomplete"
                if thread:
                    native = native_receipts(provider, repo, [thread])
                    save_native_receipts(out, native)
                    assert native["observed_raw_tokens"] == result["usage"]["observed_raw_tokens"]
                    assert native["cached_input_tokens"] == result["usage"]["cached_input_tokens"]
            except (Exception, KeyboardInterrupt) as exc:
                result["status"] = "failed"
                result["finalization_error"] = str(exc) or type(exc).__name__
        result["duration_seconds"] = time.monotonic() - started
        save_json(out / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "finalization_error": result.get("finalization_error"),
                      "fault_injected": False,
                      "raw_tokens": result.get("usage", {}).get("observed_raw_tokens"),
                      "output": str(out)}, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
