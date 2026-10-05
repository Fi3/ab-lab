"""Prepare local benchmark inputs before the ordinary CLI workflow starts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def command(argv, **options):
    try:
        subprocess.run(list(map(str, argv)), check=True, stdout=sys.stderr, **options)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Benchmark setup failed; retry the same run command after fixing the error above") from exc


def python_with(folder, requirements):
    python = folder / "bin/python"
    if not python.is_file():
        command([sys.executable, "-m", "venv", folder])
    probe = subprocess.run([str(python), "-c",
        "import importlib.metadata as m, json, sys; "
        "assert all(m.version(r.split('==')[0]) == r.split('==')[1] "
        "for r in json.loads(sys.argv[1]))", json.dumps(requirements)], capture_output=True)
    if probe.returncode:
        command([python, "-m", "pip", "install", *requirements])
    return python


def ensure_benchmark(path):
    path = Path(path).resolve(strict=True)
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return  # The ordinary loader reports invalid benchmark definitions.
    if "swe_milestone" in data:
        from benchmarks.swe_milestone_evaluator import Evaluator
        project = Evaluator.expand(data, path)["swe_milestone"]["project"]
        command([sys.executable, ROOT / "benchmarks/swe_milestone.py", "prepare", project])
        requirements = (ROOT / "benchmarks/swe-milestone-requirements.txt").read_text().splitlines()
        python_with(ROOT / ".benchmarks/swe-milestone-venv", requirements)
    elif "slopcodebench" in data:
        # The existing setup command owns the standard dataset/runner/seed layout.
        config = data["slopcodebench"]
        if not isinstance(config, dict) or any(not isinstance(config.get(key), str)
                                               for key in ("dataset", "runner")):
            return
        sources = {key: (path.parent / Path(config[key]).expanduser()).resolve()
                   for key in ("dataset", "runner")}
        root = sources["dataset"].parent
        if sources != {"dataset": root / "scb-problems", "runner": root / "slop-code-bench"}:
            raise ValueError("Automatic SlopCodeBench setup needs scb-problems and slop-code-bench in the same directory")
        environment = dict(os.environ)
        if not shutil.which("uv"):
            python = python_with(root / "setup-venv", ["uv==0.12.16"])
            environment["PATH"] = str(python.parent) + os.pathsep + environment.get("PATH", "")
        command([sys.executable, "-m", "lab.slopcodebench", "setup", "--root", root],
                cwd=ROOT, env=environment)
    else:
        if not isinstance(data.get("repo"), str):
            return
        repo = (path.parent / Path(data["repo"]).expanduser()).resolve()
        if repo == ROOT / "examples/tiny-project":
            if not (repo / ".git").exists():
                command(["git", "-C", repo, "init", "-q"])
            if subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
                              capture_output=True).returncode == 0:
                return
            command(["git", "-C", repo, "add", "."])
            command(["git", "-C", repo, "-c", "user.name=Agent Behavior Lab",
                     "-c", "user.email=lab@example.invalid", "-c", "commit.gpgSign=false",
                     "commit", "-qm", "Initialize example benchmark"])
