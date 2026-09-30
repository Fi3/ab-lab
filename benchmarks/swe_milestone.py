#!/usr/bin/env python3
"""Import SWE-Milestone projects into the lab's existing benchmark format.

This is a dataset adapter, not a runner. Model execution still uses `lab run`.
Independent grading is deliberately a separate, post-run command.
"""
import argparse
import csv
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".benchmarks"
UPSTREAM = CACHE / "swe-milestone"
DATA = CACHE / "swe-milestone-data"
PROJECTS = json.loads(Path(__file__).with_name("swe-milestone-projects.json").read_text())
VERSION = "v1.0.2"
PINS = {
    "harness": "17a8f1593e172e26b36cea15e2b30fb9536c93f5",
    "data": "3500478e740d42583277c2658aa7729eb36e10f4",
}


def run(argv, *, cwd=None, **kwargs):
    return subprocess.run(argv, cwd=cwd, check=True, **kwargs)


def git(repo, *args):
    return run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE).stdout


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_clone(path, url, revision):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish only complete clones; interrupted preparation can be rerun.
        with tempfile.TemporaryDirectory(dir=path.parent, prefix="milestone-fetch-") as tmp:
            repo = Path(tmp) / "repo"
            run(["git", "init", "-q", str(repo)])
            git(repo, "remote", "add", "origin", url)
            git(repo, "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false",
                "fetch", "--depth=1", "origin", revision)
            git(repo, "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false",
                "checkout", "-q", "--detach", "FETCH_HEAD")
            repo.rename(path)
    if git(path, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError(f"{path} is not at pinned revision {revision}")
    if git(path, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"{path} has modified release files")


def release():
    pinned_clone(UPSTREAM, "https://github.com/DeepCommit-ai/SWE-Milestone.git", PINS["harness"])
    pinned_clone(DATA, "https://huggingface.co/datasets/DeepCommit-ai/SWE-Milestone-data", PINS["data"])


def read_ids(path):
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def milestones(workspace):
    """Use the release's active subset and strong DAG edges, including additions."""
    with (workspace / "milestones.csv").open(newline="") as stream:
        known = {row["id"] for row in csv.DictReader(stream)}
    selection = workspace / "selected_milestone_ids.txt"
    selected = read_ids(selection) if selection.exists() else sorted(known)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("selected milestones must be nonempty and unique")
    if not set(selected) <= known:
        raise ValueError("selected milestone is missing from milestones.csv")
    parents = {mid: set() for mid in selected}
    children = {mid: set() for mid in selected}
    for name in ("dependencies.csv", "additional_dependencies.csv"):
        path = workspace / name
        if not path.exists():
            continue
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                source, target = row["source_id"], row["target_id"]
                if source.startswith("#"):
                    continue
                strength = (row.get("strength") or "").lower()
                if strength not in ("weak", "strong"):
                    raise ValueError(f"invalid dependency strength in {path}: {row}")
                if strength == "weak":
                    continue  # Same unlocking policy as the upstream default.
                if source in parents and target in parents:
                    parents[target].add(source)
                    children[source].add(target)
    ready = [mid for mid, deps in parents.items() if not deps]
    heapq.heapify(ready)
    order = []
    while ready:
        mid = heapq.heappop(ready)
        order.append(mid)
        for child in sorted(children[mid]):
            parents[child].remove(mid)
            if not parents[child]:
                heapq.heappush(ready, child)
    if len(order) != len(selected):
        raise ValueError("selected milestones have a dependency cycle")
    nongraded_path = workspace / "non-graded_milestone_ids.txt"
    nongraded = set(read_ids(nongraded_path)) if nongraded_path.exists() else set()
    if not nongraded <= set(selected):
        raise ValueError("non-graded milestone is not selected")
    result, feature_ids = [], set()
    for mid in order:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", mid):
            raise ValueError(f"unsafe upstream milestone ID: {mid!r}")
        feature_id = mid.replace(".", "_")
        if feature_id in feature_ids:
            raise ValueError(f"milestone IDs collide after normalization: {mid}")
        feature_ids.add(feature_id)
        request = (workspace / "srs" / mid / "SRS.md").read_bytes().decode("utf-8")
        if not request.strip():
            raise ValueError(f"empty specification for {mid}")
        result.append({"id": feature_id, "milestone": mid, "graded": mid not in nongraded,
                       "request": request})
    return result


def image_ref(workspace, milestone):
    local = f"swe-milestone/{workspace.lower()}__{milestone.lower()}:{VERSION}"
    manifest = UPSTREAM / "manifests" / f"digests-{VERSION}.tsv"
    refs = dict(line.split("\t") for line in manifest.read_text().splitlines() if line.strip())
    return local, refs[local]


def pull_image(workspace, milestone):
    local, remote = image_ref(workspace, milestone)
    probe = subprocess.run(["docker", "image", "inspect", remote], capture_output=True)
    if probe.returncode:
        run(["docker", "pull", remote])
    # The official evaluator resolves these local names. Bind them to the
    # frozen manifest digest, never an ambient :latest image.
    run(["docker", "tag", remote, local])
    identity = json.loads(run(["docker", "image", "inspect", remote],
                              stdout=subprocess.PIPE).stdout)[0]["Id"]
    return remote, identity.removeprefix("sha256:")


def export_baseline(image, destination):
    """Export reachable baseline history only, without future refs or test images."""
    container = "lab-milestone-prepare-" + uuid.uuid4().hex
    script = """set -eu
cd /testbed
git config --global --add safe.directory /testbed
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    git init -q
    git add -A
    GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \\
        git -c user.name=Benchmark -c user.email=benchmark@localhost commit -qm 'Prepared baseline'
fi
test -z "$(git status --porcelain --untracked-files=no)"
git bundle create /tmp/baseline.bundle HEAD
"""
    try:
        run(["docker", "run", "--name", container, "--network", "none", "--entrypoint",
             "/bin/sh", image, "-c", script], stdout=subprocess.DEVNULL)
        bundle = destination.parent / "baseline.bundle"
        run(["docker", "cp", container + ":/tmp/baseline.bundle", str(bundle)])
        run(["git", "-c", "advice.detachedHead=false", "clone", "-q", str(bundle), str(destination)])
        git(destination, "remote", "remove", "origin")
        bundle.unlink()
        return git(destination, "rev-parse", "HEAD").decode().strip()
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def prepare(project, checks=None):
    release()
    spec = PROJECTS[project]
    workspace = DATA / spec["workspace"]
    tasks = milestones(workspace)
    destination = CACHE / "swe-milestone-projects" / project
    if destination.exists():
        prepared, imported, benchmark = load_prepared(project)
        if checks and checks != benchmark["checks"]:
            raise ValueError(f"{destination} already has different checks; existing inputs were retained")
        if git(prepared / "repo", "rev-parse", "HEAD").decode().strip() != imported["revision"] or git(
                prepared / "repo", "status", "--porcelain"):
            raise ValueError(f"prepared starting repository has changed: {prepared / 'repo'}")
        print(prepared / "benchmark.json")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    image, image_id = pull_image(spec["workspace"], "base-offline")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="prepare-") as tmp:
        folder = Path(tmp) / project
        folder.mkdir()
        revision = export_baseline(image, folder / "repo")
        for source, name in ((DATA / "config" / (spec["workspace"] + ".yaml"), "repo_config.yaml"),
                             (UPSTREAM / "quarantine_configs" / (spec["workspace"] + ".yaml"), "runtime_policy.yaml")):
            shutil.copyfile(source, folder / name)
        benchmark = {"name": f"swe-milestone-{project}-{VERSION}", "repo": "repo", "revision": revision,
                     "features": [{"id": task["id"], "request": task["request"]} for task in tasks],
                     "checks": checks or spec["checks"]}
        write_json(folder / "benchmark.json", benchmark)
        write_json(folder / "import.json", {
            "schema": "swe-milestone-lab/v1", "project": project, "workspace": spec["workspace"],
            "version": VERSION, "pins": PINS, "revision": revision,
            "baseline_image": image, "baseline_image_id": image_id,
            "benchmark_sha256": digest(folder / "benchmark.json"),
            "repo_config_sha256": digest(folder / "repo_config.yaml"),
            "runtime_policy_sha256": digest(folder / "runtime_policy.yaml"),
            "milestones": [{k: v for k, v in task.items() if k != "request"} for task in tasks],
            "adaptation": "fixed strong-dependency order; lab author sessions and review policy; native host execution",
        })
        folder.rename(destination)
    print(destination / "benchmark.json")


def upstream_imports():
    sys.path.insert(0, str(UPSTREAM))
    try:
        import yaml
        import pathspec  # noqa: F401
    except ImportError as exc:
        raise ValueError("install benchmarks/swe-milestone-requirements.txt in this Python environment") from exc
    return yaml


def snapshot(repo, commit, imported, folder, prepared):
    """Create the current upstream tar/sidecar format using its own filters."""
    yaml = upstream_imports()
    from harness.utils.snapshot import (ManifestOverlay, expand_atomic_manifest_overlay,
        find_build_manifests, make_snapshot_metadata, should_include_snapshot_file)
    from harness.utils.src_filter import SrcFileFilter
    from harness.e2e.residue_prune import capture_filter_config, check_snapshot_integrity

    config = yaml.safe_load((prepared / "repo_config.yaml").read_text())
    metadata = json.loads((DATA / imported["workspace"] / "metadata.json").read_text())
    # Match upstream load_workspace_metadata: metadata owns the partition;
    # frozen YAML supplies optional patterns when metadata omits them.
    src_filter = SrcFileFilter(metadata["repo_src_dirs"], metadata["test_dirs"], metadata.get("exclude_patterns", []),
        metadata.get("generated_patterns", config.get("generated_patterns", [])),
        metadata.get("modifiable_test_patterns", config.get("modifiable_test_patterns", [])))
    baseline = imported["revision"]
    git(repo, "merge-base", "--is-ancestor", baseline, commit)
    paths = set(git(repo, "ls-tree", "-rz", "--name-only", commit).decode().split("\0")) - {""}
    changed = lambda kind: set(git(repo, "diff", "--no-renames", "--name-only", "-z",
                                   "--diff-filter=" + kind, baseline, commit, "--").decode().split("\0")) - {""}
    overlay = expand_atomic_manifest_overlay(ManifestOverlay.create(baseline,
        find_build_manifests(changed("ACMT"), src_filter), find_build_manifests(changed("D"), src_filter)),
        find_build_manifests(paths, src_filter), metadata["repo_src_dirs"])
    output = folder / "source_snapshot.tar"
    # Stream Git's immutable tree; never capture an in-progress working tree.
    with tempfile.TemporaryFile() as source:
        run(["git", "-C", str(repo), "archive", "--format=tar", commit], stdout=source)
        source.seek(0)
        with tarfile.open(fileobj=source) as src, tarfile.open(output, "w") as dst:
            captured = set()
            for member in src:
                if not member.isdir() and should_include_snapshot_file(member.name, src_filter, set(overlay.upserts)):
                    dst.addfile(member, src.extractfile(member) if member.isfile() else None)
                    captured.add(member.name)
    integrity = check_snapshot_integrity(paths, captured, src_filter, max_missing=0,
                                        max_missing_frac=0.0, extra_build_manifests=set(overlay.upserts))
    if not integrity.ok or find_build_manifests(captured) != set(overlay.upserts):
        raise ValueError("source snapshot lost files or build manifests")
    identity = {"schema_version": 1, "repo_name": imported["workspace"]}
    metadata = make_snapshot_metadata(tag="agent-impl-" + folder.name, snapshot_file=output,
        manifest_overlay=overlay, extra={
            "ok": True, "expected_count": integrity.expected_count, "missing_count": 0, "missing_sample": [],
            "capture_filter": capture_filter_config(src_filter),
            "agent_base_image_id": imported["baseline_image_id"], "agent_tag_commit": commit,
            "repo_config_binding": {**identity, "sha256": imported["repo_config_sha256"]},
            "runtime_policy_binding": {**identity, "sha256": imported["runtime_policy_sha256"], "mode": "protected"},
        })
    write_json(output.with_suffix(".integrity.json"), metadata)
    return output


def load_prepared(project):
    prepared = CACHE / "swe-milestone-projects" / project
    imported = json.loads((prepared / "import.json").read_text())
    if imported.get("schema") != "swe-milestone-lab/v1" or imported.get("pins") != PINS:
        raise ValueError("prepared project does not match this adapter's release")
    for name, key in (("benchmark.json", "benchmark_sha256"), ("repo_config.yaml", "repo_config_sha256"),
                      ("runtime_policy.yaml", "runtime_policy_sha256")):
        if digest(prepared / name) != imported[key]:
            raise ValueError(f"prepared {name} has changed")
    return prepared, imported, json.loads((prepared / "benchmark.json").read_text())


def recorded_commits(run_dir, benchmark):
    """Missing checkpoints stay missing; never substitute the latest checkout."""
    result = json.loads((run_dir / "result.json").read_text())
    if result.get("benchmark") != benchmark["name"]:
        raise ValueError("run belongs to a different benchmark")
    commits = {}
    expected_base = benchmark["revision"]
    for feature in benchmark["features"]:
        path = run_dir / (feature["id"] + "-result.json")
        if not path.exists():
            expected_base = None
            continue
        record = json.loads(path.read_text())
        if record.get("feature") != feature["id"] or record.get("request") != feature["request"]:
            raise ValueError(f"run's task differs from the imported specification: {feature['id']}")
        if expected_base is None or record.get("base") != expected_base:
            raise ValueError(f"broken checkpoint history at {feature['id']}")
        commit = record.get("head", "")
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise ValueError(f"missing immutable commit for {feature['id']}")
        git(run_dir / "checkout", "merge-base", "--is-ancestor", expected_base, commit)
        commits[feature["id"]] = commit
        expected_base = commit
    return commits


def grade(repo, commit, imported, prepared, folder, seconds):
    mid = folder.name
    archive = snapshot(repo, commit, imported, folder, prepared)
    workspace = DATA / imported["workspace"]
    pull_image(imported["workspace"], "base-offline")
    pull_image(imported["workspace"], mid)
    argv = [sys.executable, "-m", "harness.e2e.evaluator", "--workspace-root", str(workspace),
            "--milestone-id", mid, "--patch-file", str(archive),
            "--baseline-classification", str(workspace / "test_results" / mid / (mid + "_classification.json")),
            "--output", str(folder / "evaluation_result.json"),
            "--repo-config", str(prepared / "repo_config.yaml"),
            "--repo-config-sha256", imported["repo_config_sha256"],
            "--runtime-policy", str(prepared / "runtime_policy.yaml"),
            "--runtime-policy-sha256", imported["runtime_policy_sha256"], "--runtime-policy-mode", "protected"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWE_MILESTONE_")}
    env.update(PYTHONPATH=str(UPSTREAM), SWE_MILESTONE_IMAGE_TAG=VERSION,
               PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    started, timed_out = time.monotonic(), False
    with (folder / "stdout.txt").open("w") as stdout, (folder / "stderr.txt").open("w") as stderr:
        process = subprocess.Popen(argv, cwd=UPSTREAM, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            # The pinned evaluator names its container with its PID. Remove
            # only this evaluation's container if a timeout interrupted cleanup.
            container = f"{imported['workspace'].split('_')[0]}-{mid.lower()}-{process.pid}-eval"
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    receipt = {"argv": argv, "exit_code": process.returncode, "timed_out": timed_out,
               "duration_seconds": time.monotonic() - started}
    write_json(folder / "process.json", receipt)
    return evaluation_result(folder, receipt)


def evaluation_result(folder, receipt):
    raw_path = folder / "evaluation_result.json"
    if receipt["timed_out"] or receipt["exit_code"] not in (0, 1) or not raw_path.exists():
        return {"status": "error", "resolved": False, "error": "grader failed or timed out; inspect process.json and stderr.txt"}
    raw = json.loads(raw_path.read_text())
    # Upstream excludes invalid/unscorable tests via this release-owned list.
    filtered_path = folder / "evaluation_result_filtered.json"
    scored = json.loads(filtered_path.read_text()) if filtered_path.exists() else raw
    if raw.get("infrastructure_failure") or raw.get("scoring_blocked"):
        return {"status": "error", "resolved": False,
                "error": raw.get("infrastructure_failure") or raw["scoring_blocked"]}
    if type(scored.get("resolved")) is not bool:
        raise ValueError("grader did not return a boolean resolved verdict")
    return {"status": "passed" if scored["resolved"] else "failed", "resolved": scored["resolved"],
            "test_summary": scored.get("test_summary", {}),
            "report": str(filtered_path if filtered_path.exists() else raw_path)}


def quality(repo, commit, folder, executable):
    """Measure the complete committed tree in a disposable checkout."""
    folder.mkdir()
    checker = shutil.which(executable)
    if not checker:
        raise ValueError(f"scb-check executable not found: {executable}")
    checker = str(Path(checker).absolute())
    with tempfile.TemporaryDirectory(prefix="milestone-quality-") as tmp:
        checkout = Path(tmp) / "repo"
        run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(checkout)])
        git(checkout, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", commit)
        env = dict(os.environ, PATH=str(Path(checker).parent) + os.pathsep + os.environ.get("PATH", ""))
        env.pop("SCB_CHECK_EXTRA_SLOP_RULES", None)
        with (folder / "stdout.json").open("w") as stdout, (folder / "stderr.txt").open("w") as stderr:
            completed = subprocess.run([checker, "check", ".", "--output-format", "json"], cwd=checkout,
                                       env=env, stdout=stdout, stderr=stderr, timeout=300)
        if completed.returncode not in (0, 1):
            raise ValueError("scb-check failed; inspect " + str(folder / "stderr.txt"))
        report = json.loads((folder / "stdout.json").read_text())
        for metric in ("verbosity", "erosion", "cog_erosion"):
            value = report.get(metric)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"scb-check returned invalid {metric}")
        if type(report.get("files_scanned")) is not int or report["files_scanned"] < 1:
            raise ValueError("scb-check did not measure any files")
        if git(checkout, "status", "--porcelain") or git(checkout, "rev-parse", "HEAD").decode().strip() != commit:
            raise ValueError("scb-check modified its disposable checkout")
    return {"status": "completed", "commit": commit, "report": report,
            "executable": checker, "executable_sha256": digest(Path(checker))}


def final_assembly(run_dir, imported, prepared, output, only, seconds, checkpoints):
    """Use the runner's recorded final measurement commit, never a mutable HEAD."""
    final = {"commit": None, "milestones": []}
    receipt_path = run_dir / "scb-check" / "after_assembly" / "result.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("status") == "completed":
            commit = receipt.get("commit", "")
            if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                raise ValueError("final assembly lacks an immutable commit")
            git(run_dir / "checkout", "merge-base", "--is-ancestor", imported["revision"], commit)
            final.update(commit=commit, quality=receipt)
    previous = {row["milestone"]: row for row in checkpoints}
    for task in imported["milestones"]:
        if not task["graded"]:
            continue
        row = {"milestone": task["milestone"], "status": "not_run", "resolved": False}
        final["milestones"].append(row)
        if not final["commit"] or (only and task["milestone"] not in only):
            continue
        prior = previous[task["milestone"]]
        if prior["commit"] == final["commit"] and prior["status"] in ("passed", "failed"):
            row.update({key: prior[key] for key in ("status", "resolved", "report", "test_summary") if key in prior})
            continue
        folder = output / "final" / task["milestone"]
        folder.mkdir(parents=True)
        print(f"Final assembly: {task['milestone']} at {final['commit'][:12]}", flush=True)
        try:
            row.update(grade(run_dir / "checkout", final["commit"], imported, prepared, folder, seconds))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            row.update(status="error", error=str(exc))
        write_json(output / "final.json", final)
    final["passed"] = sum(row["resolved"] for row in final["milestones"])
    final["total"] = len(final["milestones"])
    write_json(output / "final.json", final)
    return final


def evaluate(project, run_dir, output, only, seconds, checker):
    release()
    upstream_imports()
    prepared, imported, benchmark = load_prepared(project)
    run_dir = run_dir.resolve(strict=True)
    commits = recorded_commits(run_dir, benchmark)
    available = {task["milestone"] for task in imported["milestones"]}
    if only and not set(only) <= available:
        raise ValueError("unknown milestone in --milestone")
    output = output.resolve() if output else run_dir / "swe-milestone"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(prepared / "import.json", output / "import.json")
    report = {"schema": "swe-milestone-lab-evaluation/v1", "project": project, "run": str(run_dir),
              "version": VERSION, "pins": PINS, "adapter_sha256": digest(Path(__file__)),
              "status": "incomplete", "solved": False, "passed": 0,
              "total": sum(task["graded"] for task in imported["milestones"]),
              "milestones": [{**task, "commit": commits.get(task["id"]), "status": "not_run", "resolved": False}
                             for task in imported["milestones"]]}
    write_json(output / "result.json", report)
    for task, row in zip(imported["milestones"], report["milestones"]):
        if not row["commit"] or (only and task["milestone"] not in only):
            continue
        folder = output / task["milestone"]
        folder.mkdir()
        print(f"{project}: {task['milestone']} at {row['commit'][:12]}", flush=True)
        try:
            row["quality"] = quality(run_dir / "checkout", row["commit"], folder / "quality", checker)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            row["quality"] = {"status": "error", "error": str(exc)}
        write_json(output / "result.json", report)
        try:
            if task["graded"]:
                row.update(grade(run_dir / "checkout", row["commit"], imported, prepared, folder, seconds))
            else:
                row["status"] = "not_graded"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            row.update(status="error", error=str(exc))
        report["passed"] = sum(item["resolved"] for item in report["milestones"] if item["graded"])
        write_json(output / "result.json", report)
    graded = [row for row in report["milestones"] if row["graded"]]
    report["passed"] = sum(row["resolved"] for row in graded)
    report["total"] = len(graded)
    report["final"] = final_assembly(run_dir, imported, prepared, output, only, seconds, report["milestones"])
    complete = all(row["status"] in ("passed", "failed", "not_graded")
                   and row.get("quality", {}).get("status") == "completed" for row in report["milestones"])
    complete = complete and bool(graded) and report["final"]["commit"] is not None and all(
        row["status"] in ("passed", "failed") for row in report["final"]["milestones"])
    report["status"] = "completed" if complete else "incomplete"
    report["solved"] = complete and all(row["resolved"] for row in graded + report["final"]["milestones"])
    write_json(output / "result.json", report)
    print(f"{report['passed']}/{report['total']} graded milestones passed; {report['status']}; {output / 'result.json'}")
    return 0 if report["solved"] else 1 if complete else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the seven separately runnable projects")
    prep = commands.add_parser("prepare", help="download pinned data and export one project's starting repository")
    prep.add_argument("project", choices=PROJECTS)
    prep.add_argument("--check", action="append", help="override public final build checks (repeatable)")
    evaluation = commands.add_parser("evaluate", help="grade saved milestone commits and measure their code quality")
    evaluation.add_argument("project", choices=PROJECTS)
    evaluation.add_argument("run", type=Path)
    evaluation.add_argument("--out", type=Path, help="new directory; defaults to RUN/swe-milestone")
    evaluation.add_argument("--milestone", action="append", help="grade only this upstream ID (repeatable; report stays incomplete)")
    evaluation.add_argument("--seconds", type=int, default=3600, help="maximum seconds per grading invocation")
    evaluation.add_argument("--scb-check", default="scb-check")
    args = parser.parse_args()
    try:
        if args.command == "list":
            for project, spec in PROJECTS.items():
                print(f"{project:14} {spec['workspace']}")
        elif args.command == "prepare":
            prepare(args.project, args.check)
        elif args.command == "evaluate":
            if args.seconds <= 0:
                parser.error("--seconds must be positive")
            return evaluate(args.project, args.run, args.out, args.milestone, args.seconds, args.scb_check)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"swe-milestone: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
