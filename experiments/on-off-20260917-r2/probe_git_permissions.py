"""Exercise native sandboxed Git commands without starting any model turn."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lab.host import git, save_json
from lab.provider import Codex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify-current", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / ".git").is_dir():
        raise ValueError("use a separate initialized fixture repository")
    args.output.mkdir(parents=True, exist_ok=False)
    before = git(repo, "rev-parse", "HEAD").decode().strip()
    provider = Codex(repo, args.output / "provider", "gpt-5.5", "xhigh",
                     time.monotonic()+60, 1, 1, require_git_write=args.verify_current)
    result = {"generation": "none", "initial_head": before, "attempts": []}
    try:
        for label, roots in (("original", [str(repo)]),
                             ("explicit_git_root", [str(repo), str(repo / ".git")])):
            policy = {"type": "workspaceWrite", "writableRoots": roots, "networkAccess": False}
            if label == "explicit_git_root" and args.verify_current:
                policy = provider.writable_policy()
            response = provider.rpc("command/exec", {"cwd": str(repo),
                "command": ["git", "-c", "user.name=Probe", "-c", "user.email=probe@example.invalid",
                            "commit", "--quiet", "--allow-empty", "-m", "ADD isolated Git permission probe"],
                "sandboxPolicy": policy, "timeoutMs": 10000})
            result["attempts"].append({"label": label, "policy": policy, "response": response,
                "head": git(repo, "rev-parse", "HEAD").decode().strip()})
        result["model_turns"] = len(provider.turns)
        result["observed_raw_tokens"] = provider.usage.raw
        result["current_preflight_exercised"] = args.verify_current
    finally:
        provider.close()
        save_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
