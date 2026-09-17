"""Explicit implementation smoke: python3 tests/real_protocol.py (not unittest-discovered)."""
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


def main():
    out = ROOT / "runs" / "real-protocol-001"
    out.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic()+180
    save_json(out / "admission.json", {"purpose": "implementation protocol verification, not a token experiment", "seconds": 180, "observed_raw_tokens": 80000, "turns": 6, "model": "gpt-5.5", "effort": "xhigh"})
    repo = out / "checkout"
    shutil.copytree(ROOT / "examples" / "tiny-project", repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Agent Behavior Lab")
    git(repo, "config", "user.email", "agent-behavior-lab@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "ADD protocol fixture")
    provider, result = None, {"status": "failed"}
    try:
        provider = Codex(repo, out / "provider", "gpt-5.5", "xhigh", deadline, 80000, 6)
        host = Host(repo, out / "host", "protocol", "author", deadline, settings({}))
        thread = provider.start_thread()

        def ask(prompt):
            reply = provider.turn(thread, prompt, "protocol", interrupt=True, host_request=True)
            host.unchanged()
            return host.consume(reply)

        feedback = ask("This is a bounded protocol test. Send exactly @standalone read numbers_demo.py as its own commentary message. Then attempt a read-only native sleep 3 command before your final response. Do not edit any file. The host is testing interruption after that request.")
        if "def identity" not in feedback:
            raise AssertionError("read did not deliver the fixture")
        # A separate accepted edit changes source after the author has seen it.
        # It is a controlled stale-state fixture, never a scientific observation.
        host.apply("fixture intervening edit", "*** Begin Patch\n*** Update File: numbers_demo.py\n@@\n-    return value\n+    return value + 0\n*** End Patch")
        stale = "@standalone edit stale protocol check\n*** Begin Patch\n*** Update File: numbers_demo.py\n@@\n-    return value\n+    return value * 1\n*** End Patch\n@standalone end"
        feedback = ask(feedback+"\nFor this controlled rejection test, do not inspect tools: return the following exact stale operation, without correcting it until the host responds:\n"+stale)
        if "Host proposal rejected" not in feedback or "+    return value + 0" not in feedback:
            raise AssertionError("stale edit did not produce the expected compact refresh")
        feedback = ask(feedback+"\nReturn one corrected @standalone edit operation changing the current return to value * 1, then wait. No other tools or operations.")
        if "Host accepted" not in feedback:
            raise AssertionError("corrected edit was not accepted")
        feedback = ask(feedback+"\nReply exactly: @standalone run -- python3 -m unittest discover -s tests -v")
        if "status: 0" not in feedback:
            raise AssertionError("host check failed")
        ask(feedback+"\nReply exactly: @standalone done")
        if not host.completed or not host.activations.get("C08"):
            raise AssertionError("protocol did not finish with a real conflict activation")
        if not any(t.get("status") == "interrupted" for t in provider.turns):
            raise AssertionError("real interruption was not observed")
        result.update(status="passed", activations=host.activations, final_source=(repo / "numbers_demo.py").read_text())
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc)
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        save_json(out / "result.json", result)
    print(json.dumps(result, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
