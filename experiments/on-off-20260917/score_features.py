"""Run the unchanged earlier feature tests on a separate final-result clone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lab.host import execute_child, git, save_json


FIXTURES = {
    "visual": ("quality_visual.rs", "quality_visual_behavior", "5ce0782e37b8672e04d8016ca3fbec9caa12f6f9cfaf431cac847c1f6e6a26ca"),
    "status": ("quality_status.rs", "quality_status_behavior", "5f5295c9dec6be20abb28827b68e84342110fb748aa0cc887d8b58ffa3c6e6b5"),
    "completion": ("quality_completion.rs", "quality_completion_behavior", "4d6a19f4c6f515b9a97f184a056d08dc2882041d40d26dd82011180a949c5c87"),
}


def validate_fixtures(directory):
    for filename, _, expected in FIXTURES.values():
        actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"frozen scoring fixture differs: {filename}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    validate_fixtures(args.fixtures)
    result = json.loads((args.run / "result.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"run": args.run.name, "status": "failed", "checks": {},
              "generation": "none", "fixtures": {k: v[2] for k, v in FIXTURES.items()}}
    started = time.monotonic()
    try:
        if result["status"] != "passed":
            report.update(status="not_scored", reason="workflow did not complete; no base fallback")
            return
        source = (args.run / "checkout").resolve()
        head = git(source, "rev-parse", "HEAD").decode().strip()
        if head != result["final_commits"][-1] or git(source, "status", "--porcelain"):
            raise ValueError("source is not the recorded clean final result")
        checkout = args.output.resolve() / "checkout"
        subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", "--", str(source), str(checkout)], check=True, timeout=120)
        git(checkout, "checkout", "--quiet", "--detach", head)
        report["source_commit"] = head
        for filename, _, _ in FIXTURES.values():
            target = checkout / "tests" / filename
            if target.exists():
                raise ValueError(f"refuse to overwrite a source test: {filename}")
            shutil.copyfile(args.fixtures / filename, target)
        env = dict(os.environ, CARGO_BUILD_JOBS="4", CARGO_TERM_COLOR="never",
                   CARGO_TARGET_DIR=str(args.output.resolve() / "cargo-target"),
                   WORK_LEAF_CONTEXT_BUNDLE_DIR=str(args.output.resolve() / "runtime/bundles"),
                   WORK_LEAF_COMMAND_TMPDIR=str(args.output.resolve() / "runtime/commands"))
        for name, (filename, test, _) in FIXTURES.items():
            folder = args.output / name
            folder.mkdir()
            command = ["cargo", "test", "--test", Path(filename).stem, test, "--", "--exact"]
            receipt = execute_child(command, checkout, None, folder / "stdout.txt", folder / "stderr.txt", 900, env)
            receipt["status"] = "pass" if receipt["exit_code"] == 0 and not receipt["timed_out"] and not receipt["cancelled_signal"] else "fail"
            report["checks"][name] = receipt
            save_json(folder / "result.json", receipt)
        if git(source, "rev-parse", "HEAD").decode().strip() != head or git(source, "status", "--porcelain"):
            raise ValueError("original result changed during post-run scoring")
        report.update(status="scored", passed=sum(r["status"] == "pass" for r in report["checks"].values()), total=len(FIXTURES))
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        report["duration_seconds"] = time.monotonic() - started
        save_json(args.output / "result.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
