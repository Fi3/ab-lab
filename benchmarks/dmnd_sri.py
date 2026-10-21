"""Grade the pinned SRI migration with the mining suite and its complete evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
import uuid

from lab import scb
from lab.environment import clean_env
from lab.evaluation import BaseEvaluator, save_result
from lab.host import Fatal, execute_child, git, save_json
from benchmarks.dmnd_mining_logs import validate_mining
from benchmarks.dmnd_sri_source import audit_dependencies
from benchmarks.dmnd_sri_performance import install_harness, validate_performance
from benchmarks.dmnd_sri_prepare import BASE_REVISION as BASE, dependency_sources, load_setup
from benchmarks.dmnd_sri_tree import extract_tree


VERSION = "dmnd-new-sri-evaluation/v1"


def checked_process(argv, cwd, folder, name, seconds):
    receipt = execute_child(list(map(str, argv)), cwd, None,
                            folder / (name + ".stdout.txt"),
                            folder / (name + ".stderr.txt"), seconds, clean_env())
    receipt["argv"] = list(map(str, argv))
    save_json(folder / (name + ".process.json"), receipt)
    return receipt


def succeeded(receipt):
    return (receipt["exit_code"] == 0 and not receipt["timed_out"]
            and not receipt["cancelled_signal"])


def interrupted(receipt):
    return receipt["timed_out"] or receipt["cancelled_signal"]


def capture(checkout, folder, revision="HEAD"):
    """Retain the submitted commit and history without sharing Git objects."""
    folder.mkdir(parents=True)
    revision = git(checkout, "rev-parse", "--verify", "--end-of-options",
                   revision + "^{commit}").decode().strip()
    repo = folder / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "fetch", "-q", "--no-tags", "--no-write-fetch-head", "--",
        str(checkout), revision)
    git(repo, "checkout", "-q", "--detach", revision)
    return {"repo": str(repo), "commit": revision,
            "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip()}


def source_context(repo, revision, folder):
    """Use committed source only, with the original test suite unchanged."""
    changed = git(repo, "diff", "--name-only", BASE, revision, "--", "tests", "build.rs").decode().splitlines()
    if changed:
        raise ValueError("The pinned mining tests changed: " + ", ".join(changed))
    manifest = tomllib.loads(git(repo, "show", revision + ":Cargo.toml").decode())
    original = tomllib.loads(git(repo, "show", BASE + ":Cargo.toml").decode())
    if manifest.get("package", {}).get("build") != original["package"].get("build"):
        raise ValueError("The pinned transport build script changed")
    for key in ("lib", "bin", "test"):
        if manifest.get(key) != original.get(key):
            raise ValueError("The pinned Cargo targets changed: " + key)
    if manifest.get("build-dependencies", {}).get("toml") != original["build-dependencies"]["toml"]:
        raise ValueError("The pinned transport build dependency changed")
    extract_tree(repo, revision, folder)
    performance = install_harness(folder)
    tree = git(repo, "rev-parse", revision + "^{tree}").decode().strip()
    instrument_metadata(folder / "tests/Dockerfile", tree)
    return {"performance": performance, "base": BASE,
            "dockerfile_sha256": hashlib.sha256((folder / "tests/Dockerfile").read_bytes()).hexdigest()}


def instrument_metadata(dockerfile, tree=None):
    """Compile both CLI configurations and retain their resolved packages."""
    source = dockerfile.read_text()
    if tree is not None:
        mount = "--mount=type=cache,target=/workspace/target,sharing=locked"
        if source.count(mount) != 1:
            raise ValueError("The pinned build target cache changed")
        source = source.replace(mount, "--mount=type=cache,id=dmnd-sri-" + tree
                                + ",target=/workspace/target,sharing=locked")
    marker = "    && strip /out/mining-e2e /out/dmnd-client"
    if source.count(marker) != 1:
        raise ValueError("The pinned Docker build is missing its metadata insertion point")
    mining_build = "    && cargo test --locked --features mining-e2e --test mining_e2e --no-run -j 4"
    if source.count(mining_build) != 1:
        raise ValueError("The pinned mining build command changed")
    source = source.replace(mining_build,
                            "    && cargo build --locked --bin dmnd-client -j 4 " + chr(92) + "\n"
                            + mining_build)
    metadata = "".join("    && cargo metadata --locked --format-version 1 "
                       "--filter-platform x86_64-unknown-linux-gnu " + features
                       + "> /out/" + filename + " " + chr(92) + "\n"
                       for features, filename in (("", "cargo-metadata.json"),
                           ("--features mining-e2e ", "cargo-mining-metadata.json")))
    source = source.replace(marker, metadata + marker)
    source = source.replace("--test mining_e2e --no-run", "--test mining_e2e --test lab_sri_performance --no-run")
    source = source.replace(marker, "    && for binary in target/debug/deps/lab_sri_performance-*; do "
                            'if [ -x "$binary" ] && [ -f "$binary" ]; then cp "$binary" /out/lab-sri-performance; fi; '
                            "done " + chr(92) + "\n    && test -x /out/lab-sri-performance " + chr(92) + "\n" + marker)
    source += "\nCOPY --from=builder /out/cargo-metadata.json /opt/lab/cargo-metadata.json\n"
    source += "COPY --from=builder /out/cargo-mining-metadata.json /opt/lab/cargo-mining-metadata.json\n"
    source += "COPY --from=builder /out/lab-sri-performance /usr/local/bin/lab-sri-performance\n"
    dockerfile.write_text(source)


def runtime_identity():
    result = subprocess.run(["docker", "version", "--format", "{{json .Server}}"],
                            capture_output=True, text=True, timeout=30, env=clean_env())
    if result.returncode:
        raise Fatal("Docker is unavailable: " + result.stderr.strip())
    return json.loads(result.stdout)


def run_mining(image, folder, seconds, name):
    artifacts = folder / "artifacts"
    artifacts.mkdir()
    if "," in str(artifacts):
        raise ValueError("The artifact path cannot contain a comma")
    argv = ["docker", "run", "--rm", "--init", "--network", "none",
            "--platform", "linux/amd64", "--name", name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={artifacts.resolve()},dst=/artifacts", image]
    receipt = checked_process(argv, folder, folder, "mining", seconds)
    evidence = validate_mining(artifacts, (folder / "mining.stdout.txt").read_text(),
                               (folder / "mining.stderr.txt").read_text())
    return receipt, evidence


def cleanup_container(name, folder, label="mining"):
    probe = checked_process(["docker", "container", "ls", "-aq", "--filter", "name=^/" + name + "$"],
                            folder, folder, label + "-container-list", 30)
    if not succeeded(probe):
        raise RuntimeError("Cannot check the evaluation container after execution")
    if (folder / (label + "-container-list.stdout.txt")).read_text().strip():
        removed = checked_process(["docker", "rm", "-f", name], folder, folder, label + "-container-remove", 30)
        if not succeeded(removed):
            raise RuntimeError("Cannot remove the evaluation container")


def run_performance(image, folder, name):
    receipt = checked_process(["docker", "run", "--rm", "--init", "--network", "none",
                               "--platform", "linux/amd64", "--name", name,
                               "--user", f"{os.getuid()}:{os.getgid()}",
                               "--entrypoint", "/usr/local/bin/lab-sri-performance", image,
                               "--nocapture", "--test-threads=1"], folder, folder, "performance", 60)
    evidence = validate_performance((folder / "performance.stdout.txt").read_text(),
                                    (folder / "performance.stderr.txt").read_text())
    return receipt, evidence


def check_dependencies(image, folder, item, references, mining=False):
    label = "mining-metadata" if mining else "metadata"
    filename = "cargo-mining-metadata.json" if mining else "cargo-metadata.json"
    receipt = checked_process(["docker", "run", "--rm", "--network", "none",
                               "--platform", "linux/amd64", "--entrypoint", "cat",
                               image, "/opt/lab/" + filename], folder, folder, label, 60)
    if not succeeded(receipt):
        raise RuntimeError("Cannot read the resolved build dependencies: " + label)
    metadata = json.loads((folder / (label + ".stdout.txt")).read_text())
    return audit_dependencies(metadata, Path(item["repo"]), item["commit"], BASE, references)


def cleanup_evaluation(name, image, built, folder):
    errors = []
    for label in ("mining", "performance"):
        try:
            cleanup_container(name if label == "mining" else name + "-performance", folder, label)
        except (Exception, KeyboardInterrupt) as exc:
            errors.append(str(exc) or "Container cleanup interrupted")
    if built:
        try:
            removed = checked_process(["docker", "image", "rm", image], folder, folder, "image-remove", 30)
            if not succeeded(removed):
                raise RuntimeError("Cannot remove the evaluation image")
        except (Exception, KeyboardInterrupt) as exc:
            errors.append(str(exc) or "Image cleanup interrupted")
    return errors


def grade_submission(item, folder, config, references):
    folder.mkdir(parents=True)
    image = "dmnd-sri-eval:" + uuid.uuid4().hex
    name = "dmnd-sri-eval-" + uuid.uuid4().hex
    performance_name = name + "-performance"
    report = {"schema": VERSION, "status": "error", "passed": None,
              "submission": item, "errors": []}
    built = False
    try:
        context = folder / "source"
        try:
            report["tests"] = source_context(Path(item["repo"]), item["commit"], context)
        except ValueError as exc:
            report.update(status="completed", passed=False, errors=[str(exc)])
            return report
        build = checked_process(["docker", "build", "--platform", "linux/amd64",
                                 "-f", "tests/Dockerfile", "-t", image, "."],
                                context, folder, "build", config["build_seconds"])
        report["build"] = build
        if not succeeded(build):
            report.update(status="error" if interrupted(build) else "completed",
                          passed=None if interrupted(build) else False,
                          errors=["Docker build did not complete successfully"])
            return report
        built = True
        dependency_result = check_dependencies(image, folder, item, references)
        report["dependencies"] = dependency_result
        mining_dependencies = check_dependencies(image, folder, item, references, mining=True)
        report["mining_dependencies"] = mining_dependencies
        perf_receipt, performance = run_performance(image, folder, performance_name)
        report.update(performance_process=perf_receipt, performance=performance)
        receipt, evidence = run_mining(image, folder, config["run_seconds"], name)
        report.update(mining_process=receipt, mining=evidence)
        errors = (list(dependency_result["errors"]) + list(mining_dependencies["errors"])
                  + list(evidence["errors"]) + list(performance["errors"]))
        if not succeeded(perf_receipt):
            errors.append("The performance test did not complete successfully")
        if not succeeded(receipt):
            errors.append("The mining suite did not complete successfully")
        runtime_error = any(interrupted(process) or process["exit_code"] == 125
                            for process in (receipt, perf_receipt))
        report.update(status="error" if runtime_error else "completed",
                      passed=None if runtime_error else not errors,
                      errors=errors)
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="error", passed=None)
        report["errors"].append(str(exc) or "Evaluation interrupted")
    finally:
        cleanup_errors = cleanup_evaluation(name, image, built, folder)
        if cleanup_errors:
            report.update(status="error", passed=None)
            report["errors"].extend(cleanup_errors)
        save_json(folder / "result.json", report)
    return report


def load_references(repo):
    repo = Path(repo).resolve()
    path = repo.parent / "setup.json"
    data = load_setup(path, dependency_sources(repo))
    return data["references"]


class Evaluator(BaseEvaluator):
    config_key = "dmnd_sri"
    retain_stopped_attempts = True

    @classmethod
    def expand(cls, data, path):
        config = data[cls.config_key]
        if not isinstance(config, dict) or set(config) - {"build_seconds", "run_seconds"}:
            raise ValueError("Unknown dmnd_sri evaluator fields")
        config = {"build_seconds": 3600, "run_seconds": 1800, **config}
        if any(type(value) is not int or value <= 0 for value in config.values()):
            raise ValueError("dmnd_sri time limits must be positive integers")
        if data.get("revision") != BASE or [f.get("id") for f in data.get("features", [])] != ["new-sri"]:
            raise ValueError("dmnd_sri requires the pinned base and one new-sri feature")
        return {**data, cls.config_key: config}

    def start(self, base, manifest, deadline):
        if base != BASE:
            raise Fatal("The SRI benchmark base changed")
        self.references = load_references(self.benchmark["repo"])
        runtime = runtime_identity()
        record = {"schema": VERSION, "base": BASE, "runtime": runtime,
                  "references": self.references, "checkpoints": [], "final": None}
        manifest["dmnd_sri"] = record.copy()
        self.result["dmnd_sri"] = record

    def checkpoint(self, checkout, checkpoint, quality_tool, deadline):
        folder = self.output / "dmnd-sri" / "snapshots" / checkpoint["feature"]
        item = {"feature": checkpoint["feature"], **capture(checkout, folder)}
        if quality_tool is not None:
            item["quality"] = scb.measure(checkout, self.output, "checkpoint-new-sri", quality_tool, deadline)
            if item["quality"]["status"] != "completed":
                raise Fatal("SRI checkpoint quality measurement failed")
        self.result["dmnd_sri"]["checkpoints"].append(item)
        return item

    def final(self, checkout):
        self.result["dmnd_sri"]["final"] = {
            "feature": "final", **capture(checkout, self.output / "dmnd-sri/snapshots/final")}

    def evaluate(self):
        record = self.result["dmnd_sri"]
        items = record["checkpoints"] + ([record["final"]] if record["final"] else [])
        graded, cache = [], {}
        for item in items:
            key = item["commit"]
            if key not in cache:
                folder = self.output / "dmnd-sri" / "evaluation" / item["feature"]
                cache[key] = grade_submission(item, folder, self.benchmark["dmnd_sri"], self.references)
            graded.append({"feature": item["feature"], **cache[key]})
        complete = bool(record["final"]) and bool(graded)
        status = ("error" if any(row["status"] == "error" for row in graded)
                  else "completed" if complete else "incomplete")
        passed = all(row["passed"] for row in graded) if status == "completed" else None
        report = {"schema": VERSION, "status": status, "passed": passed, "results": graded}
        path = self.output / "dmnd-sri-evaluation.json"
        save_json(path, report)
        record.update(report)
        return {"status": status, "passed": passed, "report_path": str(path),
                "checkpoints": [{"feature": row["feature"], "status": row["status"],
                                 "passed": row["passed"]} for row in graded if row["feature"] != "final"],
                "final": {"passed": passed if record["final"] else None}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="Git repository with the candidate commit")
    parser.add_argument("revision")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, default=Path(".benchmarks/dmnd-new-sri/repo"))
    parser.add_argument("--build-seconds", type=int, default=3600)
    parser.add_argument("--run-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.out.exists() or min(args.build_seconds, args.run_seconds) <= 0:
        parser.error("Use a new output directory and positive time limits")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True)
    report = {"schema": VERSION, "status": "incomplete", "passed": None, "errors": []}
    save_result(args.out, report)
    try:
        references = load_references(args.prepared)
        item = capture(args.repo.resolve(), args.out / "submission", args.revision)
        report = grade_submission(item, args.out / "evaluation", vars(args), references)
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="error", passed=None, errors=[str(exc) or "Evaluation interrupted"])
    save_result(args.out, report)
    print(json.dumps({"status": report["status"], "passed": report["passed"],
                      "report_path": str(args.out / "result.json")}, indent=2))
    return 0 if report["passed"] else 1 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
