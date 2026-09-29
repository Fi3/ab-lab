"""Opt-in real Codex check of typed host requests in a fresh benign fixture.

Seven bounded turns exercise read, run, edit, discard, and done. The fixture
checks spaced paths, shell quoting, trailing command spaces, executable modes,
pending-source restoration, and real numeric usage. It never resumes a prior
conversation, retries provider refusals, or uses benchmark prompts or histories.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.config import settings
from lab.host import Host, git, parse_operations, save_json, snapshot
from lab.provider import Codex
from lab.workflow import source_hashes
from real_compaction import events, native_receipts, save_native_receipts


MODEL, EFFORT = "gpt-5.6-sol", "xhigh"
SECONDS, MAX_RAW, MAX_TURNS = 600, 400000, 8
NOTE_PATH, SCRIPT_PATH = "input note.txt", "verify fixture.py"
NOTE = "original fixture input\n"
SCRIPT = '''#!/usr/bin/env python3
from pathlib import Path

assert Path("input note.txt").read_text() == "original fixture input\\n"
counter = Path("build/verification-runs.txt")
assert not counter.exists(), "verification command was replayed"
counter.parent.mkdir(exist_ok=True)
counter.write_text("one\\n")
print("EXECUTABLE_TYPED_HOST_OK")
'''


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def cases():
    quoted_code = ("from pathlib import Path; "
                   f"assert Path({NOTE_PATH!r}).read_text() == {NOTE!r}; "
                   "print('QUOTED_READ_OK: \"double\"')")
    quoted_command = shlex.join(["python3", "-B", "-c", quoted_code]) + "  "
    patch_text = ("*** Begin Patch\n*** Add File: " + SCRIPT_PATH +
                  "\n*** Mode: 100755\n" +
                  "".join("+" + line + "\n" for line in SCRIPT.splitlines()) +
                  "*** End Patch")
    mutation_code = ("from pathlib import Path; "
                     f"Path({NOTE_PATH!r}).write_text('temporary fixture input\\n')")
    mutation_command = (shlex.quote("./" + SCRIPT_PATH) + " && " +
                        shlex.join(["python3", "-B", "-c", mutation_code]))
    return [
        ("read-spaced-path", {"kind": "read", "path": NOTE_PATH}),
        ("quoted-command", {"kind": "run", "paths": [], "command": quoted_command}),
        ("executable-edit", {"kind": "edit", "reason": "Add the isolated executable check.",
                             "patch": patch_text}),
        ("read-published-script", {"kind": "read", "path": SCRIPT_PATH}),
        ("run-and-stage-change", {"kind": "run", "paths": [NOTE_PATH],
                                   "command": mutation_command}),
        ("discard-temporary-change", {"kind": "discard",
                                      "reason": "Discard the deliberately temporary fixture change."}),
        ("finish", {"kind": "done"}),
    ]


def expected_operation(operation):
    """Independent expected tuple, without using the provider's JSON decoder."""
    kind = operation["kind"]
    if kind == "read":
        return kind, operation["path"]
    if kind == "run":
        return kind, operation["paths"], operation["command"]
    if kind == "edit":
        return kind, operation["reason"], operation["patch"]
    if kind == "discard":
        return kind, operation["reason"]
    return (kind,)


def exact_json(text):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("non-JSON numeric constant")

    return json.loads(text, object_pairs_hook=unique_keys, parse_constant=invalid_constant)


def verify_owned_response(provider, number, operation, reply):
    row = provider.turns[-1]
    folder = provider.artifacts / f"turn-{len(provider.turns):04d}"
    raw = (folder / "reply.txt").read_text()
    assert exact_json(raw) == {"operation": operation}, "final JSON changed the requested fixture operation"
    assert parse_operations(reply) == [expected_operation(operation)], "canonical operation changed field content"
    canonical = folder / "host-operation.txt"
    assert canonical.read_text() == reply, "returned operation differs from retained canonical artifact"
    assert Path(row["host_operation_file"]).resolve() == canonical.resolve()
    response_format = getattr(provider, "host_response_format", None)
    assert isinstance(response_format, str) and response_format
    assert row["response_format"] == response_format
    assert provider.identity["host_response_format"] == response_format
    assert row["usage_observed_after_last_message"], "typed operation lacks covering usage"
    observed = events(provider)
    starts = [event for event in observed if event.get("method") == "turn/start"]
    assert len(starts) == number, "unexpected extra generation or retry"
    request = starts[-1]["params"]
    schema = json.loads((folder / "output-schema.json").read_text())
    assert request["outputSchema"] == schema and schema["type"] == "object"
    assert schema["required"] == ["operation"] and schema["additionalProperties"] is False
    variants = schema["properties"]["operation"]["anyOf"]
    kinds = {value for branch in variants for value in
             branch["properties"]["kind"].get("enum", [branch["properties"]["kind"].get("const")])}
    assert kinds == {"read", "run", "edit", "discard", "done"}
    assert request["threadId"] == row["thread_id"]
    assert request["model"] == MODEL and request["effort"] == EFFORT
    assert request["approvalPolicy"] == "never"
    assert request["sandboxPolicy"] == provider.sandbox.policy(False)
    items = [event["params"]["item"] for event in observed
             if event.get("method") == "item/completed"
             and event.get("params", {}).get("turnId") == row["turn_id"]
             and event["params"].get("item", {}).get("type") == "agentMessage"]
    selected = [item for item in items if item["text"] == raw]
    assert len(selected) == 1 and selected[0].get("phase") == "final_answer"
    assert raw in json.loads((folder / "messages.json").read_text())
    return {"number": number, "operation": operation["kind"], "turn_id": row["turn_id"],
            "status": row["status"], "interrupt_reason": row.get("interrupt_reason"),
            "raw_reply_file": str(folder / "reply.txt"), "raw_json_sha256": sha256(raw.encode()),
            "host_operation_file": str(canonical), "host_operation_sha256": sha256(reply.encode()),
            "output_schema_sha256": sha256(json.dumps(schema, sort_keys=True).encode()),
            "selected_item_id": selected[0]["id"], "phase": selected[0]["phase"],
            "usage_complete_at_delivery": True, "typed_field_content_preserved": True}


def verify_host_effect(repo, host, operation, feedback):
    kind = operation["kind"]
    assert (repo / NOTE_PATH).read_text() == NOTE, "temporary command change was not restored"
    host.unchanged()
    if kind == "read":
        expected = NOTE if operation["path"] == NOTE_PATH else SCRIPT
        assert feedback.endswith(expected), "host read did not return exact file content"
    elif kind == "edit":
        assert (repo / SCRIPT_PATH).read_text() == SCRIPT
        assert stat.S_IMODE((repo / SCRIPT_PATH).stat().st_mode) == 0o755
        assert len(host.accepted_commits) == 1
    elif kind == "run":
        receipt = json.loads((host.artifacts / f"operation-{host.counter:04d}/receipt.json").read_text())
        assert receipt["command"] == operation["command"], "host changed command quoting or trailing spaces"
        assert receipt["exit_code"] == 0 and not receipt["timed_out"]
        assert not receipt["cancelled_signal"] and not receipt["custody_errors"]
        if operation["paths"]:
            assert "EXECUTABLE_TYPED_HOST_OK" in feedback
            assert host.pending_changes == [NOTE_PATH]
            assert receipt["pending_paths"] == [NOTE_PATH]
            assert (repo / "build/verification-runs.txt").read_text() == "one\n"
        else:
            assert 'QUOTED_READ_OK: "double"' in feedback
            assert not host.pending_changes and not receipt["pending_paths"]
            assert receipt["command"].endswith("  ")
    elif kind == "discard":
        assert not host.pending_changes
    else:
        assert feedback is None and host.completed and not host.pending_changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    source = source_hashes()
    script_hash = sha256(Path(__file__).read_bytes())
    save_json(out / "admission.json", {
        "purpose": "fresh benign fixture verifying actual schema-constrained host responses",
        "model": MODEL, "effort": EFFORT, "seconds": SECONDS,
        "max_raw": MAX_RAW, "max_turns": MAX_TURNS, "planned_host_turns": 7,
        "auth": "existing ChatGPT subscription; no API fallback",
        "benchmark_run": False, "prior_conversation_or_blocked_prompt_reused": False,
        "provider_failure_policy": "stop; do not retry or alter a refused prompt",
        "source_sha256": source, "script_sha256": script_hash,
        "receipt_auditor_sha256": sha256(Path(__file__).with_name("real_compaction.py").read_bytes()),
    })
    provider, thread = None, None
    result = {"status": "failed", "steps": [], "scope": "fresh typed host fixture"}
    try:
        repo = out / "fixture"
        repo.mkdir()
        (repo / ".gitignore").write_text("build/\n__pycache__/\n")
        (repo / NOTE_PATH).write_text(NOTE)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Typed host verification")
        git(repo, "config", "user.email", "typed-host@example.invalid")
        git(repo, "config", "commit.gpgSign", "false")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "Add isolated typed host fixture")
        initial = snapshot(repo)
        provider = Codex(repo, out / "provider", MODEL, EFFORT,
                         started + SECONDS, MAX_RAW, MAX_TURNS)
        thread = provider.start_thread()
        host = Host(repo, out / "host", "typed-host", "verification", provider.deadline,
                    settings({}), command_env=provider.command_env, command_argv=provider.command_argv)
        feedback = None
        for number, (name, operation) in enumerate(cases(), 1):
            prompt = (
                "This is a fresh isolated test of the framework's typed host protocol. "
                "Do not use native tools, execute commands, or edit files yourself. "
                "Return exactly the supplied operation as your final JSON response, "
                "preserving every field's content, including spaces, quotes, and newlines. "
                "Do not add progress narration or a second operation. The framework will "
                "execute the operation once and return its real result.\n")
            if feedback is not None:
                prompt += "Previous actual host result:\n" + feedback + "\n"
            prompt += "Requested response object:\n" + json.dumps({"operation": operation}, ensure_ascii=False)
            before = snapshot(repo)
            interrupt = number % 2 == 0
            reply = provider.turn(thread, prompt, "typed-host-" + name,
                                  host_request=True, interrupt=interrupt)
            assert snapshot(repo) == before, "model changed fixture source or Git state"
            step = verify_owned_response(provider, number, operation, reply)
            assert provider.report()["measurement_complete"], "incomplete measurement before host execution"
            step.update(name=name, interrupt_requested=interrupt)
            feedback = host.consume(reply)
            verify_host_effect(repo, host, operation, feedback)
            step["host_effect_verified"] = True
            result["steps"].append(step)
            save_json(out / f"step-{number:02d}.json", step)
        assert len(provider.turns) == 7 and host.completed
        assert len(host.accepted_commits) == 1 and not host.pending_changes
        assert git(repo, "rev-list", "--count", initial["head"] + "..HEAD").strip() == b"1"
        assert not git(repo, "status", "--porcelain")
        assert len(list(host.artifacts.glob("operation-*/receipt.json"))) == 3
        observed = events(provider)
        item_types = {event.get("params", {}).get("item", {}).get("type")
                      for event in observed if event.get("method") in ("item/started", "item/completed")}
        assert item_types <= {"userMessage", "agentMessage", "reasoning"}, "unexpected native tool activity"
        assert source_hashes() == source, "runner changed during verification"
        assert sha256(Path(__file__).read_bytes()) == script_hash, "verifier changed during verification"
        result.update(status="passed", typed_operations=[op["kind"] for _, op in cases()],
                      source_custody_preserved=True, accepted_edit_commits=1,
                      host_command_executions=2, executable_runtime_checks=1,
                      native_tool_executions=0, pending_change_discarded=True)
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            try:
                provider.close()
                result["usage"] = provider.report()
                assert result["usage"]["measurement_complete"], "final measurement incomplete"
                assert result["usage"]["nested"]["observed_raw_tokens"] == 0
                assert 0 < result["usage"]["observed_raw_tokens"] < MAX_RAW
                if thread:
                    native = native_receipts(provider, repo, [thread])
                    save_native_receipts(out, native)
                    assert result["usage"]["observed_raw_tokens"] == native["observed_raw_tokens"]
                    assert result["usage"]["cached_input_tokens"] == native["cached_input_tokens"]
                    assert {r["turn_id"] for r in native["responses"]} == {
                        row["turn_id"] for row in provider.turns}, "turn lacks a real numeric receipt"
                    result["independent_raw_tokens"] = native["observed_raw_tokens"]
            except (Exception, KeyboardInterrupt) as exc:
                result["status"] = "failed"
                result["finalization_error"] = str(exc) or "operator interruption"
        result["duration_seconds"] = time.monotonic() - started
        save_json(out / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "finalization_error": result.get("finalization_error"),
                      "verified_host_turns": len(result["steps"]),
                      "raw_tokens": result.get("usage", {}).get("observed_raw_tokens"),
                      "output": str(out)}, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
