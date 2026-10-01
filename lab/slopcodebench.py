"""SlopCodeBench task loading and external grading; no model calls or new loop."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time

from .environment import clean_env
from .host import Fatal, execute_child, git, save_json


DATASET_REVISION = "38d627ecf668a88f88f8d260f8df8df6116e9b03"
RUNNER_REVISION = "31ceea3add480edb33431e70475c4c70597e6b31"
ENVIRONMENT = "configs/environments/docker-python3.12-uv.yaml"
BRIDGE = Path(__file__).with_name("scb_bridge.py")
SEED_IGNORE = "__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n"
CHECKPOINT_STOP_POLICY = "bounded-review-and-continue-v3"


def pinned(repo, revision):
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("SlopCodeBench revisions must be full Git commit hashes")
    if git(repo, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError(f"SlopCodeBench checkout is not at its pinned revision: {repo}")
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError(f"SlopCodeBench checkout has local changes: {repo}")


def validate(config):
    pinned(config["dataset"], config["revision"])
    pinned(config["runner"], config["runner_revision"])
    if not (Path(config["runner"]) / ".venv/bin/python").is_file():
        raise ValueError("SlopCodeBench evaluator is not installed; run python3 -m lab.slopcodebench setup")


def bridge_argv(config, action, *args):
    return [str(Path(config["runner"]) / ".venv/bin/python"), "-I", str(BRIDGE),
            action, json.dumps(config), *map(str, args)]


def preflight(benchmark, output, deadline):
    config = benchmark["slopcodebench"]
    validate(config)
    folder = output / "slopcodebench" / "runtime"
    folder.mkdir(parents=True)
    receipt = execute_child(bridge_argv(config, "check"), config["runner"], None,
        folder / "stdout.json", folder / "stderr.txt", min(60, deadline - time.monotonic()), clean_env())
    save_json(folder / "result.json", receipt)
    if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
        raise Fatal("SlopCodeBench runtime unavailable; run python3 -m lab.slopcodebench setup; inspect " + str(folder / "stderr.txt"))
    identity = json.loads((folder / "stdout.json").read_text())
    if identity.get("status") != "ready":
        raise Fatal("SlopCodeBench runtime did not report readiness")
    return identity


def expand(data, path):
    if "features" in data:
        raise ValueError("SlopCodeBench supplies its own checkpoint features")
    raw = data["slopcodebench"]
    allowed = {"dataset", "revision", "problem", "runner", "runner_revision", "environment", "seconds", "checkpoint_limit"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("unknown SlopCodeBench fields")
    config = dict(raw)
    for key in ("dataset", "revision", "problem", "runner", "runner_revision"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"SlopCodeBench needs {key}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", config["problem"]):
        raise ValueError("SlopCodeBench problem must be a directory name")
    for key in ("dataset", "runner"):
        source = Path(config[key]).expanduser()
        config[key] = str((source if source.is_absolute() else path.parent / source).resolve(strict=True))
    env = Path(config.setdefault("environment", ENVIRONMENT))
    if env.is_absolute() or ".." in env.parts:
        raise ValueError("SlopCodeBench environment must be relative to its pinned runner")
    config["environment"] = env.as_posix()
    if not (Path(config["runner"]) / env).is_file():
        raise ValueError("SlopCodeBench environment configuration does not exist")
    seconds = config.setdefault("seconds", 300)
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("SlopCodeBench seconds must be a positive integer per graded snapshot")
    validate(config)
    described = subprocess.run(bridge_argv(config, "describe"), cwd=config["runner"],
        env=clean_env(), capture_output=True, text=True, timeout=60)
    if described.returncode:
        raise ValueError("SlopCodeBench task loading failed: " + described.stderr[-4000:])
    description = json.loads(described.stdout)
    limit = config.get("checkpoint_limit", len(description["features"]))
    if type(limit) is not int or not 1 <= limit <= len(description["features"]):
        raise ValueError("SlopCodeBench checkpoint_limit must be a positive integer no greater than the available checkpoints")
    # Fresh author/reviewer threads need the requirements already revealed.
    previous, features, checkpoint_prompts = [], [], []
    for feature in description["features"][:limit]:
        previous.append(feature["request"])
        request = "\n\n".join(previous)
        features.append({"id": feature["id"], "request": request})
        checkpoint_prompts.append({"feature": feature["id"],
            "request_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest()})
    provenance = {**description["prompt_provenance"],
        "dataset_revision": config["revision"], "runner_revision": config["runner_revision"],
        "history": "verbatim-prior-prompts-with-two-newline-separator",
        "checkpoints": description["prompt_provenance"]["checkpoints"][:limit],
        "cumulative_requests": checkpoint_prompts}
    data = {**data, "slopcodebench": config, "features": features,
            "prompt_provenance": provenance}
    return data


def pending(benchmark):
    config = benchmark["slopcodebench"]
    return {"problem": config["problem"], "dataset_revision": config["revision"],
            "runner_revision": config["runner_revision"], "status": "incomplete", "solved": None,
            "prompt_provenance": benchmark["prompt_provenance"],
            **({"checkpoint_limit": config["checkpoint_limit"]} if "checkpoint_limit" in config else {}),
            "checkpoints": [{"feature": f["id"], "status": "not_run"} for f in benchmark["features"]],
            "final": None}


def capture(checkout, output, name):
    """Archive a committed attempt, whether approved or stopped, for evaluation."""
    folder = output / "slopcodebench" / "snapshots" / name
    folder.mkdir(parents=True)
    head = git(checkout, "rev-parse", "HEAD").decode().strip()
    archive = folder.parent / (name + ".tar")
    with archive.open("xb") as stream:
        stream.write(git(checkout, "archive", head))
    with tarfile.open(archive) as stream:
        stream.extractall(folder, filter="data")
    return {"snapshot": str(folder), "commit": head,
            "tree": git(checkout, "rev-parse", "HEAD^{tree}").decode().strip()}


def retain_attempt(checkout, feature):
    """Checkpoint applied native edits without claiming author/reviewer completion.

    Only source actually present in the checkout is retained. Tool receipts
    preserve execution state separately; no operation is replayed.
    """
    previous = git(checkout, "rev-parse", "HEAD").decode().strip()
    dirty = git(checkout, "status", "--porcelain").decode()
    if git(checkout, "ls-files", "--unmerged"):
        raise Fatal("cannot retain an unmerged SlopCodeBench attempt")
    if dirty:
        git(checkout, "add", "--all")
        if git(checkout, "diff", "--cached", "--name-only"):
            git(checkout, "commit", "-qm", f"Checkpoint unapproved stopped attempt: {feature}")
    if git(checkout, "status", "--porcelain"):
        raise Fatal("cannot retain stopped SlopCodeBench attempt as a clean checkpoint")
    head = git(checkout, "rev-parse", "HEAD").decode().strip()
    return {"previous_head": previous, "retention_commit": head if head != previous else None,
            "working_tree_status_before_retention": dirty}


def grade_one(config, item, output, checkpoint):
    folder = output / "slopcodebench" / "evaluation" / item["feature"]
    folder.mkdir(parents=True)
    started = time.monotonic()
    record = {**item, "status": "error"}
    try:
        receipt = execute_child(bridge_argv(config, "evaluate", item["snapshot"], folder / "details", checkpoint),
            config["runner"], None, folder / "stdout.json", folder / "stderr.txt",
            config["seconds"], clean_env())
        record.update(receipt)
        if receipt["exit_code"] != 0 or receipt["timed_out"] or receipt["cancelled_signal"]:
            raise ValueError("evaluator failed or timed out; inspect " + str(folder / "stderr.txt"))
        report = json.loads((folder / "stdout.json").read_text())
        if report.get("status") == "error":
            record["evaluation"] = report
            raise ValueError(report.get("error") or "upstream evaluator reported an infrastructure failure")
        for key in ("strict_pass", "isolated_pass", "core_pass"):
            if type(report.get(key)) is not bool:
                raise ValueError("evaluator returned missing or invalid " + key)
        counts = report.get("tests", {})
        if any(type(counts.get(k)) is not int or counts[k] < 0 for k in ("passed", "total")) or not 0 <= counts["passed"] <= counts["total"] or counts["total"] == 0:
            raise ValueError("evaluator returned invalid or empty test counts")
        if report.get("status") != ("passed" if report["strict_pass"] else "failed"):
            raise ValueError("evaluator status disagrees with correctness")
        record.update(report)
    except (Exception, KeyboardInterrupt) as exc:
        record.update(status="error", error=str(exc) or "evaluation interrupted")
    finally:
        # A killed docker CLI does not necessarily stop its daemon container.
        # The bridge tags only this evaluation's containers and removes them.
        try:
            cleanup = execute_child(bridge_argv(config, "cleanup", folder / "details"), config["runner"], None,
                folder / "cleanup.json", folder / "cleanup.stderr.txt", 30, clean_env())
            record["cleanup"] = cleanup
            if cleanup["cancelled_signal"]:
                record["cancelled_signal"] = record.get("cancelled_signal") or cleanup["cancelled_signal"]
            if cleanup["exit_code"] or cleanup["timed_out"] or cleanup["cancelled_signal"]:
                raise ValueError("evaluator container cleanup failed; inspect " + str(folder / "cleanup.stderr.txt"))
        except (Exception, KeyboardInterrupt) as exc:
            record.update(status="error", error=str(exc) or "evaluation cleanup interrupted")
    record["duration_seconds"] = time.monotonic() - started
    save_json(folder / "result.json", record)
    return record


def evaluate(benchmark, result, output):
    """Only called after provider shutdown; failed model runs retain their grades."""
    report = result["slopcodebench"]
    config = {**benchmark["slopcodebench"], "expected_runtime": report.get("runtime")}
    started = time.monotonic()
    report["workflow_status"] = result["status"]
    try:
        validate(config)
        for index, item in enumerate(report["checkpoints"]):
            if "snapshot" in item:
                report["checkpoints"][index] = grade_one(config, item, output, item["feature"])
                if report["checkpoints"][index].get("cancelled_signal"):
                    report["cancelled_signal"] = report["checkpoints"][index]["cancelled_signal"]
                    break
        if report["final"] is not None and not report.get("cancelled_signal"):
            report["final"] = grade_one(config, report["final"], output, benchmark["features"][-1]["id"])
            if report["final"].get("cancelled_signal"):
                report["cancelled_signal"] = report["final"]["cancelled_signal"]
        items = [*report["checkpoints"], report["final"] or {"status": "not_run"}]
        report["status"] = ("error" if any(i["status"] == "error" for i in items) else
                            "incomplete" if any(i["status"] == "not_run" for i in items) else "completed")
        report["all_tests_passed"] = (all(i["status"] == "passed" for i in items)
                                      if report["status"] == "completed" else None)
        if report["workflow_status"] != "passed" or any(i["status"] == "failed" for i in items):
            report["solved"] = False
        else:
            report["solved"] = True if all(i["status"] == "passed" for i in items) else None
        if report["status"] == "error" and result["status"] in ("passed", "needs_attention"):
            result.update(status="failed", error="SlopCodeBench evaluator infrastructure failed; see slopcodebench results",
                          failure={"origin": "evaluator", "stage": "evaluation", "message": "Evaluator infrastructure failed"})
        elif not report["solved"] and result["status"] == "passed":
            result.update(status="failed", error="SlopCodeBench correctness did not pass at every checkpoint and final evaluation; see slopcodebench results",
                          failure={"origin": "agent", "stage": "evaluation", "message": "Submission failed benchmark tests"})
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="error", solved=None, error=str(exc) or "evaluation interrupted")
        if result["status"] in ("passed", "needs_attention"):
            result.update(status="failed", error="SlopCodeBench evaluation failed: " + report["error"],
                          failure={"origin": "evaluator", "stage": "evaluation", "message": report["error"]})
    report["duration_seconds"] = time.monotonic() - started


def setup(root):
    """Explicit, one-time installation; never called by plan or run."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name, url, revision in (
        ("scb-problems", "https://github.com/gabeorlanski/scb-problems.git", DATASET_REVISION),
        ("slop-code-bench", "https://github.com/SprocketLab/slop-code-bench.git", RUNNER_REVISION),
    ):
        destination = root / name
        if not destination.exists():
            destination.mkdir()
            git(destination, "init", "--quiet")
            subprocess.run(["git", "-C", str(destination), "fetch", "--depth=1", url, revision], check=True)
            git(destination, "checkout", "--quiet", "--detach", revision)
        pinned(destination, revision)
    runner = root / "slop-code-bench"
    subprocess.run(["uv", "sync", "--frozen", "--no-dev", "--python", "3.12"], cwd=runner, check=True)
    seed = root / "scb-empty"
    if not seed.exists():
        seed.mkdir()
        git(seed, "init", "--quiet")
        git(seed, "config", "user.name", "Agent Behavior Lab")
        git(seed, "config", "user.email", "agent-behavior-lab@example.invalid")
        git(seed, "config", "commit.gpgSign", "false")
        (seed / ".gitignore").write_text(SEED_IGNORE)
        git(seed, "add", ".gitignore")
        subprocess.run(["git", "-C", str(seed), "commit", "-qm", "Initialize empty SlopCodeBench project"],
            env={**clean_env(), "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}, check=True)
    config = {"dataset": str(root / "scb-problems"), "revision": DATASET_REVISION,
              "runner": str(runner), "runner_revision": RUNNER_REVISION,
              "problem": "code_search", "environment": ENVIRONMENT}
    subprocess.run(bridge_argv(config, "prepare"), cwd=runner, env=clean_env(),
                   stdout=subprocess.PIPE, check=True)
    print("SlopCodeBench installed at " + str(root))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install the pinned SlopCodeBench tasks and evaluator; no agent generation.")
    parser.add_argument("command", choices=("setup",))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / ".benchmarks")
    args = parser.parse_args()
    setup(args.root)
