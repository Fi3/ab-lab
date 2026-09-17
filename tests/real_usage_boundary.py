"""Explicit bounded subscription verification; never run by unittest discovery."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import settings
from lab.host import Host, git, save_json
from lab.provider import Codex
from lab.workflow import source_hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic()+240
    save_json(out / "admission.json", {"purpose": "approved usage-boundary repair verification, not an effect-size observation",
        "seconds": 240, "observed_raw_tokens": 150000, "turns": 8, "model": "gpt-5.5", "effort": "xhigh",
        "source_sha256": source_hashes(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "authority": "experiments/on-off-20260917-r2/REPAIR-AND-RUN-AUTHORITY.md"})
    repo = out / "checkout"
    shutil.copytree(ROOT / "examples/tiny-project", repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Agent Behavior Lab")
    git(repo, "config", "user.email", "agent-behavior-lab@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "ADD isolated usage-boundary verification fixture")
    provider, result = None, {"status": "failed"}
    started = time.monotonic()
    try:
        provider = Codex(repo, out / "provider", "gpt-5.5", "xhigh", deadline, 150000, 8)
        host = Host(repo, out / "host", "protocol", "author", deadline, settings({}))
        thread = provider.start_thread()

        def ask(prompt, label, interrupt=True):
            reply = provider.turn(thread, prompt, label, interrupt=interrupt, host_request=True)
            if not provider.report()["measurement_complete"]:
                raise AssertionError("incomplete usage; do not execute more host work or generation")
            host.unchanged()
            return host.consume(reply)

        feedback = ask("This is a bounded protocol test. Send exactly @standalone read numbers_demo.py as its own commentary message. After that message, continue with a read-only native sleep 3 command before your final response. Do not edit any file. The host is testing cancellation after its request's token usage is available.", "intermediate-request")
        if "def identity" not in feedback:
            raise AssertionError("host read did not deliver the fixture")
        if provider.turns[0].get("interrupt_reason") != "usage_received":
            raise AssertionError("first scenario did not exercise an actual priced interruption")
        first_turn = provider.turns[0]["turn_id"]
        first_events = [json.loads(line)["event"] for line in (out / "provider/transport.jsonl").read_text().splitlines()]
        if not any(e.get("method") == "item/completed" and e.get("params", {}).get("turnId") == first_turn
                   and e["params"].get("item", {}).get("phase") == "commentary"
                   and e["params"]["item"].get("text", "").strip() == "@standalone read numbers_demo.py" for e in first_events):
            raise AssertionError("first scenario did not deliver the required intermediate host request")
        host.apply("fixture intervening edit", "*** Begin Patch\n*** Update File: numbers_demo.py\n@@\n-    return value\n+    return value + 0\n*** End Patch")
        stale = "@standalone edit stale protocol check\n*** Begin Patch\n*** Update File: numbers_demo.py\n@@\n-    return value\n+    return value * 1\n*** End Patch\n@standalone end"
        feedback = ask(feedback+"\nFor this controlled rejection test, do not inspect tools. Return this exact stale operation without correcting it before the host responds:\n"+stale, "stale-edit")
        if "Host proposal rejected" not in feedback or "+    return value + 0" not in feedback:
            raise AssertionError("stale edit did not return compact refreshed information")
        feedback = ask(feedback+"\nReturn one corrected @standalone edit operation changing the current return to value * 1. No other tools or operations.", "corrected-edit")
        if "Host accepted" not in feedback:
            raise AssertionError("corrected edit was not accepted")
        feedback = ask(feedback+"\nReply exactly: @standalone run -- python3 -m unittest discover -s tests -v", "host-check")
        if "status: 0" not in feedback:
            raise AssertionError("real host test failed")
        feedback = ask(feedback+"\nFor a natural-finish check, reply exactly: @standalone read numbers_demo.py", "natural-finish", interrupt=False)
        if provider.turns[-1].get("interrupt_reason") is not None or "return value * 1" not in feedback:
            raise AssertionError("disabled interruption did not finish naturally and deliver the read")
        ask(feedback+"\nReply exactly: @standalone done", "completion")
        if not host.completed or not host.activations.get("C08") or not provider.report()["measurement_complete"]:
            raise AssertionError("scenario lacks completed work, actual compact refresh or complete usage")
        result.update(status="passed", activations=host.activations,
                      scenarios=["intermediate priced interruption", "stale rejection and compact refresh",
                                 "accepted correction", "real host check", "natural finish", "completion"])
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        result["duration_seconds"] = time.monotonic()-started
        save_json(out / "result.json", result)
    print(json.dumps(result, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
