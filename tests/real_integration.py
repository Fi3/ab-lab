"""Explicit remaining-stage verification; no author/reviewer reruns."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.host import git, save_json, snapshot
from lab.provider import Codex
from lab.workflow import integration_prompts


def main():
    original = ROOT / "runs" / "real-workflow-001"
    original_result = json.loads((original / "result.json").read_text())
    manifest = json.loads((original / "manifest.json").read_text())
    assert len(original_result["checkpoints"]) == 2
    out = ROOT / "runs" / "real-integration-001"
    out.mkdir(exist_ok=False)
    save_json(out / "admission.json", {"purpose": "remaining integration verification only", "source": str(original),
        "reviewed_head": original_result["checkpoints"][-1]["reviewed_head"], "seconds": 240, "observed_raw_tokens": 200000, "turns": 2})
    deadline = time.monotonic()+240
    repo = out / "checkout"
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--", str(original / "checkout"), str(repo)], check=True)
    assert git(repo, "rev-parse", "HEAD").decode().strip() == original_result["checkpoints"][-1]["reviewed_head"]
    git(repo, "config", "user.name", "Agent Behavior Lab")
    git(repo, "config", "user.email", "agent-behavior-lab@example.invalid")
    base = manifest["base_commit"]
    plan, accept = integration_prompts(manifest["benchmark"], base, original_result["checkpoints"])
    provider, result = None, {"status": "failed"}
    try:
        provider = Codex(repo, out / "provider", "gpt-5.5", "xhigh", deadline, 200000, 2)
        thread = provider.start_thread()
        before = snapshot(repo)
        provider.turn(thread, plan, "integration-plan")
        if snapshot(repo) != before:
            raise AssertionError("planning changed source")
        provider.turn(thread, accept, "integration-accept", writable=True)
        git(repo, "merge-base", "--is-ancestor", base, "HEAD")
        commits = git(repo, "rev-list", base+"..HEAD").decode().splitlines()
        if len(commits) != 2 or git(repo, "rev-list", "--merges", base+"..HEAD") or git(repo, "status", "--porcelain"):
            raise AssertionError("final history/cleanliness contract failed")
        checked = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=repo, capture_output=True, timeout=min(30, max(1, deadline-time.monotonic())))
        (out / "checks.stdout.txt").write_bytes(checked.stdout)
        (out / "checks.stderr.txt").write_bytes(checked.stderr)
        if checked.returncode:
            raise AssertionError("final tests failed")
        result.update(status="passed", final_commits=commits, checks_exit_code=0)
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
