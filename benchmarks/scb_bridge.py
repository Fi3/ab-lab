"""Small subprocess bridge, executed with the pinned SCBench runner's Python.

The lab itself remains standard-library only. This script imports the authors'
configuration parser and correctness evaluator inside their separate environment.
"""
import argparse
from contextlib import closing, redirect_stdout
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shlex
import shutil
import sys
import traceback


def load(config):
    # -I prevents the submission or the lab's working directory from supplying
    # imports. Select the exact checkout whose revision the caller verified.
    sys.path.insert(0, str(Path(config["runner"]) / "src"))
    import yaml
    from slop_code.evaluation.config import ProblemConfig
    from slop_code.execution.docker_runtime import DockerEnvironmentSpec
    from slop_code.execution.local_streaming import LocalEnvironmentSpec

    problem = ProblemConfig.from_yaml(
        Path(config["dataset"]) / config["problem"])
    if problem.static_assets:
        raise ValueError("SCBench problems with static assets are not supported yet")
    environment_path = Path(config["environment"])
    if not environment_path.is_absolute():
        environment_path = Path(config["runner"]) / environment_path
    data = yaml.safe_load(environment_path.read_text())
    models = {"docker": DockerEnvironmentSpec, "local": LocalEnvironmentSpec}
    if data.get("type") not in models:
        raise ValueError("SCBench environment must have type docker or local")
    environment = models[data["type"]].model_validate(data)
    return problem, environment


def describe(problem, environment, runner):
    from slop_code.common import render

    entry_file = environment.format_entry_file(problem.entry_file)
    entry_command = environment.get_command(problem.entry_file, is_agent_run=True)
    template_path = Path(runner) / "configs/prompts/just-solve.jinja"
    template_bytes = template_path.read_bytes()
    template = template_bytes.decode("utf-8")
    features = []
    checkpoints = []
    for checkpoint in problem.iterate_checkpoints():
        if not (problem.path / "tests" / f"test_{checkpoint.name}.py").is_file():
            raise ValueError(f"SCBench tests missing for {checkpoint.name}")
        spec = problem.get_checkpoint_spec(checkpoint.name)
        # Use the same renderer and context as the pinned upstream runner. This
        # includes its canary removal and entrypoint substitution, not a local
        # paraphrase of the benchmark's execution requirements.
        context = {"is_continuation": bool(features), "agent_type": None,
                   "agent_version": "", "model_name": None}
        request = render.render_prompt(
            spec_text=spec, context=context, prompt_template=template,
            entry_file=entry_file, entry_command=entry_command)
        features.append({"id": checkpoint.name, "request": request})
        checkpoints.append({"feature": checkpoint.name, "context": context,
            "spec_sha256": hashlib.sha256(spec.encode("utf-8")).hexdigest(),
            "prompt_sha256": hashlib.sha256(request.encode("utf-8")).hexdigest()})
    if not features:
        raise ValueError("SCBench problem has no checkpoints")
    return {
        "problem": problem.name,
        "problem_version": problem.version,
        "features": features,
        "prompt_provenance": {
            "format": "upstream-scb-prompts-v1",
            "template": "configs/prompts/just-solve.jinja",
            "template_sha256": hashlib.sha256(template_bytes).hexdigest(),
            "renderer": "slop_code.common.render.render_prompt",
            "renderer_sha256": hashlib.sha256(Path(render.__file__).read_bytes()).hexdigest(),
            "spec_transforms": "upstream renderer: leading canary removal and entrypoint substitution",
            "entry_file": entry_file,
            "entry_command": entry_command,
            "checkpoints": checkpoints,
        },
        "entry_file": entry_file,
        "entry_command": entry_command,
        "environment_type": environment.type,
        "environment_name": environment.name,
    }


def prepare(environment):
    """Explicit setup only; normal grading never builds the base image."""
    if environment.type == "docker":
        import docker
        from slop_code.execution.docker_runtime import build_base_image

        with closing(docker.from_env()) as client:
            build_base_image(client, environment)
    return check(environment)


def check(environment):
    """Fail before agent work if the separately prepared runtime is unavailable."""
    result = {"status": "ready", "python": sys.version, "packages": dict(sorted(
        (distribution.metadata["Name"], distribution.version)
        for distribution in metadata.distributions()))}
    if environment.type == "docker":
        import docker

        if not shutil.which(environment.docker.binary):
            raise ValueError("SCBench Docker executable was not found")
        with closing(docker.from_env()) as client:
            client.ping()
            image = client.images.get(environment.get_base_image())
        result["image"] = image.id
    return result


def container_label(output):
    identifier = hashlib.sha256(str(Path(output).resolve()).encode()).hexdigest()
    return "agent-behavior-lab.eval=" + identifier


def labeled_environment(environment, output):
    """Tag only this evaluation's containers so the caller can reap timeouts."""
    if environment.type != "docker":
        return environment
    executable = shutil.which(environment.docker.binary)
    if not executable:
        raise ValueError("SCBench Docker executable was not found")
    wrapper = output / "docker-eval"
    wrapper.write_text(
        '#!/bin/sh\nif [ "$1" = run ]; then\n  shift\n  exec '
        + shlex.quote(executable) + " run --label "
        + shlex.quote(container_label(output)) + ' "$@"\nfi\nexec '
        + shlex.quote(executable) + ' "$@"\n')
    wrapper.chmod(0o700)
    return environment.model_copy(update={"docker": environment.docker.model_copy(
        update={"binary": str(wrapper)})})


def cleanup(environment, output):
    if environment.type == "docker":
        import docker

        with closing(docker.from_env()) as client:
            for container in client.containers.list(
                    all=True, filters={"label": container_label(output)}):
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass  # --rm may already have removed a finished container.
    return {"status": "completed"}


def evaluate(problem, environment, snapshot, output, checkpoint_name, expected_runtime=None):
    from slop_code.common import WORKSPACE_TEST_DIR
    from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
    from slop_code.logging import setup_logging

    snapshot = Path(snapshot).resolve()
    output = Path(output).resolve()
    if not snapshot.is_dir() or output == snapshot or snapshot in output.parents:
        raise ValueError("SCBench output must be outside the snapshot directory")
    # Upstream deliberately reuses a pre-existing evaluation test directory.
    # Never allow submission-authored files to replace the authoritative tests.
    for name in (WORKSPACE_TEST_DIR, ".scbench"):
        path = snapshot / name
        if path.exists() or path.is_symlink():
            raise ValueError(f"Submission contains reserved SCBench path: {name}")
    output.mkdir(parents=True, exist_ok=True)
    setup_logging(log_dir=output, verbosity=0, suppress_console=True)
    runtime = check(environment)
    if expected_runtime is not None and runtime != expected_runtime:
        raise ValueError("SCBench evaluator runtime changed after preflight")
    submission = output / "submission"
    shutil.copytree(snapshot, submission, symlinks=True)
    environment = labeled_environment(environment, output)
    checkpoint = problem.load_checkpoint(checkpoint_name)
    results = run_checkpoint_pytest(
        submission_path=submission, problem=problem,
        checkpoint=checkpoint, env_spec=environment)
    results.save(output)

    passed = sum(results.pass_counts.values())
    total = sum(results.total_counts.values()) or results.pytest_collected
    regression_passed = results.pass_counts.get("Regression", 0)
    regression_total = results.total_counts.get("Regression", 0)
    isolated_passed = passed - regression_passed
    isolated_total = total - regression_total
    core_passed = results.pass_counts.get("Core", 0)
    core_total = results.total_counts.get("Core", 0)
    if results.infrastructure_failure or total <= 0:
        return {
            "status": "error",
            "error": f"Upstream pytest infrastructure failure (exit {results.pytest_exit_code}); inspect the saved evaluation output",
            "pytest_exit_code": results.pytest_exit_code,
            "infrastructure_failure": True,
            "test_collection_hash": results.test_collection_hash,
            "tests": {"passed": passed, "total": total},
        }
    strict_pass = results.pytest_exit_code == 0 and passed == total
    return {
        "status": "passed" if strict_pass else "failed",
        "strict_pass": strict_pass,
        "isolated_pass": isolated_total > 0 and isolated_passed == isolated_total,
        "core_pass": core_total > 0 and core_passed == core_total,
        "strict_pass_rate": passed / total if total else 0.0,
        "isolated_pass_rate": isolated_passed / isolated_total if isolated_total else 0.0,
        "core_pass_rate": core_passed / core_total if core_total else 0.0,
        "tests": {"passed": passed, "total": total},
        "pass_counts": results.pass_counts,
        "total_counts": results.total_counts,
        "pytest_exit_code": results.pytest_exit_code,
        "test_collection_hash": results.test_collection_hash,
        "infrastructure_failure": results.infrastructure_failure,
        "include_prior_tests": checkpoint.include_prior_tests,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("describe", "prepare", "check", "evaluate", "cleanup"))
    parser.add_argument("config", help="Normalized SCBench settings as a JSON object")
    parser.add_argument("evaluation", nargs="*")
    args = parser.parse_args(argv)
    required = {"evaluate": 3, "cleanup": 1}.get(args.action, 0)
    if len(args.evaluation) != required:
        parser.error("evaluate requires SNAPSHOT OUTPUT CHECKPOINT; cleanup requires OUTPUT")
    try:
        # Some upstream imports and Docker helpers log to stdout. Keep the
        # subprocess protocol a single JSON object regardless of logging setup.
        with redirect_stdout(sys.stderr):
            config = json.loads(args.config)
            problem, environment = load(config)
            if args.action == "describe":
                result = describe(problem, environment, config["runner"])
            elif args.action == "prepare":
                result = prepare(environment)
            elif args.action == "check":
                result = check(environment)
            elif args.action == "cleanup":
                result = cleanup(environment, *args.evaluation)
            else:
                result = evaluate(problem, environment, *args.evaluation,
                                  expected_runtime=config.get("expected_runtime"))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
