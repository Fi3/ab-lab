"""One bounded real-agent workflow verifies the three actual scb-check stages."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import settings
from lab.host import git, save_json
from lab.workflow import run, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scb-check", default="scb-check")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = output / "input"
    shutil.copytree(ROOT / "examples/tiny-project", repo,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Agent Behavior Lab")
    git(repo, "config", "user.email", "agent-behavior-lab@example.invalid")
    git(repo, "config", "commit.gpgSign", "false")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "ADD tiny quality-check verification input")
    benchmark = {"name": "three-quality-checkpoints", "repo": str(repo), "revision": "HEAD",
        "features": [{"id": "negate", "request": "Add negate(value) to numbers_demo.py, returning arithmetic negation. Test positive, negative and zero inputs. Preserve identity's behavior."}],
        "checks": ["python3 -m unittest discover -s tests -v",
                   "python3 -c 'from numbers_demo import identity, negate; assert identity(3) == 3; assert [negate(x) for x in (3, -4, 0)] == [-3, 4, 0]'"]}
    factors = settings({"C08": False, "C16": False, "C17": False})
    save_json(output / "admission.json", {"purpose": "implementation verification, not a savings experiment",
        "observations": 1, "benchmark": benchmark, "factors": factors,
        "source_sha256": source_hashes(), "seconds": 600, "observed_raw_tokens": 600000,
        "max_turns": 16, "model": "gpt-5.5", "effort": "xhigh",
        "auth": "existing ChatGPT subscription only", "scb_check": args.scb_check,
        "stop": "one terminal result, including any error or budget stop; no automatic replacement"})
    result = run(benchmark, factors, output / "workflow", 600, 600000, 16,
                 scb_check=args.scb_check)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "scb_check": result.get("scb_check"), "usage": result["usage"]}, indent=2))
    return int(result["status"] != "passed" or result.get("scb_check", {}).get("status") != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
