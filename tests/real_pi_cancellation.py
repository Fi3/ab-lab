"""Opt-in installed-Pi cancellation at a fully priced native-tool boundary."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.host import git, save_json, snapshot
from lab.loops import FeatureProgress, WorkLimitReached, loop_policy
from lab.provider import Pi, pi_usage_tokens
from lab.workflow import source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = output / "fixture"
    repo.mkdir()
    (repo / "sample.py").write_text("def double(value):\n    return value * 2\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Cancellation Verification")
    git(repo, "config", "user.email", "verification@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Add isolated review fixture")
    initial, code = snapshot(repo), source_hashes()
    policy = loop_policy({"max_review_raw": 1, "max_review_seconds": 1, "max_feature_raw": 200000})
    result = {"status": "failed", "scope": "isolated Pi cancellation accounting verification",
              "source_sha256": code, "policy": policy}
    provider = None
    try:
        provider = Pi(repo, output / "provider", "gpt-5.5", "xhigh", time.monotonic() + 180,
                      200000, 1)
        thread = provider.start_thread(writable=False)
        journal = provider.artifacts / (thread + "-requests.jsonl")
        journal.write_text("")
        # Even the more permissive native workspace-write profile must not
        # grant model-authored commands access to this runner-owned journal.
        custody = subprocess.run(provider.sandbox.command(True, [sys.executable, "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('forged')", str(journal)]),
            cwd=repo, env=provider.command_env, capture_output=True, text=True, timeout=15)
        save_json(output / "journal-custody.json", {"exit_code": custody.returncode,
                  "stdout": custody.stdout, "stderr": custody.stderr})
        assert custody.returncode != 0 and journal.read_text() == "", "model can alter accounting journal"
        progress = FeatureProgress({"id": "cancellation-probe"}, policy, 0)
        provider.work_limits = progress.limits(0, reviewing=True)
        try:
            provider.turn(thread, "Review sample.py without changing files. As your first action, use bash to run "
                "python3 -c 'import time; time.sleep(2); print(\"review fixture ready\")', then read sample.py "
                "and assess whether double(value) returns twice its input. This is an isolated tool test.",
                "cancellation-probe-review-1")
            raise AssertionError("review limit did not stop generation")
        except WorkLimitReached as stopped:
            result["trigger"] = stopped.signal
        usage = provider.report()
        row = provider.turns[-1]
        result["turn"] = row
        assert row["work_limit_settlement"]["trigger"]["reason"] == "review_time_limit", row
        assert row["work_limit_settlement"]["outcome"] == "hard_limit", row
        assert row["work_limit"]["reason"] == "review_token_limit", row
        assert row.get("cancelled_requests"), "probe did not exercise a prevented next request"
        assert usage["measurement_complete"], "cancellation accounting incomplete"
        totals = [0, 0, 0]
        sessions = list((provider.sessions_dir / thread).glob("*.jsonl"))
        assert len(sessions) == 1, sessions
        for line in sessions[0].read_text().splitlines():
            entry = json.loads(line)
            message = entry.get("message", {})
            if message.get("role") == "assistant" and message.get("usage"):
                counts = pi_usage_tokens(message["usage"])
                totals = [a+b for a, b in zip(totals, counts)]
        result["independent_session_totals"] = totals
        assert totals == list(provider.usage.totals[thread]), (totals, usage)
        assert snapshot(repo) == initial, "review changed fixture"
        assert source_hashes() == code, "runner source changed during verification"
        result["status"] = "passed"
    except BaseException as error:
        result["error"] = str(error)
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        save_json(output / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
        "raw_tokens": result.get("usage", {}).get("observed_raw_tokens"), "output": str(output)}))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
