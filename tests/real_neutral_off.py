"""Bounded subscription-backed author verification, never a savings benchmark."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import policy_blocks, settings
from lab.host import Host, git, save_json
from lab.provider import Codex
from lab.workflow import author_prompt, native_done, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("native", "host"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    overrides = dict.fromkeys(("C13", "C14", "C15", "C16"), False)
    if args.mode == "native":
        overrides.update(C08=False, C17=False, C25=False)
    factors = settings(overrides)
    assert all(not policy_blocks(factors)[key] for key in ("C13", "C14", "C15", "C16"))
    code = source_hashes()
    save_json(out / "admission.json", {
        "purpose": "neutral-OFF implementation verification, not a token comparison",
        "mode": args.mode, "factors": factors, "source_sha256": code,
        "seconds": 180, "observed_raw_tokens": 150000,
        "turns": 1 if args.mode == "native" else 8,
        "model": "gpt-5.5", "effort": "xhigh", "auth": "existing ChatGPT subscription",
        "scope": "one tiny author task; no review, integration or full benchmark rerun",
    })
    start = time.monotonic()
    deadline = start+180
    repo = out / "checkout"
    shutil.copytree(ROOT / "examples" / "tiny-project", repo,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Agent Behavior Lab")
    git(repo, "config", "user.email", "agent-behavior-lab@example.invalid")
    git(repo, "config", "commit.gpgSign", "false")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "ADD neutral-policy verification fixture")
    initial = git(repo, "rev-parse", "HEAD").decode().strip()
    feature = {"id": "negate", "request": "Add negate(value) to numbers_demo.py, returning the arithmetic negation. Cover positive, negative and zero values with tests. Preserve identity's existing behavior."}
    prompt = author_prompt({"instructions": "", "defer_documentation": True}, feature, factors)
    save_json(out / "request.json", {"prompt": prompt, "feature": feature, "initial_head": initial})
    provider, result = None, {"status": "failed", "mode": args.mode, "factors": factors}
    try:
        provider = Codex(repo, out / "provider", "gpt-5.5", "xhigh", deadline, 150000,
                         1 if args.mode == "native" else 8, require_git_write=True)
        thread = provider.start_thread(writable=args.mode == "native")
        if args.mode == "native":
            reply = provider.turn(thread, prompt, "neutral-native-author", writable=True)
            if not native_done(reply):
                raise AssertionError("native author did not complete")
        else:
            host = Host(repo, out / "host", "negate", "author", deadline, factors,
                        command_env=provider.command_env)
            while not host.completed:
                reply = provider.turn(thread, prompt, "neutral-host-author",
                                      interrupt=factors["C25"], host_request=True)
                if not provider.report()["measurement_complete"]:
                    raise AssertionError("incomplete usage before host operation")
                host.unchanged()
                host.evidence("AUTHOR REPLY", reply)
                prompt = host.consume(reply)
            result["accepted_commits"] = host.accepted_commits
        if not provider.report()["measurement_complete"]:
            raise AssertionError("incomplete author usage")
        if git(repo, "status", "--porcelain"):
            raise AssertionError("author left uncommitted files")
        changed = git(repo, "diff", "--name-only", initial, "HEAD").decode().splitlines()
        if "numbers_demo.py" not in changed or not any(path.startswith("tests/") for path in changed):
            raise AssertionError("implementation and tests were not both committed")
        checks = ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                  [sys.executable, "-c", "from numbers_demo import identity, negate; assert identity(3) == 3; assert [negate(x) for x in (3, -4, 0)] == [-3, 4, 0]"])
        result["checks"] = []
        for command in checks:
            receipt = subprocess.run(command, cwd=repo, capture_output=True, text=True,
                                     timeout=max(1, min(20, deadline-time.monotonic())),
                                     env=provider.command_env)
            result["checks"].append({"command": command, "exit_code": receipt.returncode,
                                     "stdout": receipt.stdout, "stderr": receipt.stderr})
            if receipt.returncode:
                raise AssertionError("verification command failed")
        if source_hashes() != code:
            raise AssertionError("runner source changed during verification")
        result.update(status="passed", changed_files=changed,
                      final_head=git(repo, "rev-parse", "HEAD").decode().strip())
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc)
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        result["duration_seconds"] = time.monotonic()-start
        save_json(out / "result.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "usage"}, indent=2))
    if provider:
        print(json.dumps({"raw_tokens": result["usage"]["observed_raw_tokens"],
                          "measurement_complete": result["usage"]["measurement_complete"]}))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
