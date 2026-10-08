"""Automatic grading for SWE-Milestone through the generic runner lifecycle."""
import json
from pathlib import Path
import time

from benchmarks import swe_milestone as sm
from lab.environment import clean_env
from lab.evaluation import BaseEvaluator
from lab.host import Fatal, execute_child, save_json


RUNTIME_PROBE = """import importlib.metadata, json, subprocess, sys
import yaml, pathspec
import harness.e2e.evaluator
server = subprocess.check_output(['docker', 'version', '--format', '{{.Server.Version}}'], text=True).strip()
image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', sys.argv[1]], text=True))[0]['Id']
if image.removeprefix('sha256:') != sys.argv[2]:
    raise RuntimeError('prepared baseline image identity changed')
print(json.dumps({'python': sys.version, 'docker': server, 'baseline_image_id': image,
    'packages': {name: importlib.metadata.version(name) for name in ('PyYAML', 'pathspec', 'ast-grep-cli')}}))
"""


class Evaluator(BaseEvaluator):
    config_key = "swe_milestone"
    retain_stopped_attempts = True

    @classmethod
    def expand(cls, data, path):
        config = data[cls.config_key]
        if not isinstance(config, dict) or set(config) - {"project", "seconds", "repository_additions"}:
            raise ValueError("unknown SWE-Milestone evaluator fields")
        project = config.get("project")
        if not isinstance(project, str) or project not in sm.PROJECTS:
            raise ValueError("SWE-Milestone needs a known project")
        seconds = config.get("seconds", 3600)
        if type(seconds) is not int or seconds <= 0:
            raise ValueError("SWE-Milestone seconds must be a positive integer per grading invocation")
        expanded = {"project": project, "seconds": seconds}
        if "repository_additions" in config:
            expanded["repository_additions"] = sm.repository_addition_paths(config["repository_additions"])
        return {**data, cls.config_key: expanded}

    def start(self, base, manifest, deadline):
        self.config = self.benchmark[self.config_key]
        project = self.config["project"]
        for source, revision in ((sm.UPSTREAM, sm.PINS["harness"]), (sm.DATA, sm.PINS["data"])):
            if not source.is_dir() or sm.git(source, "rev-parse", "HEAD").decode().strip() != revision:
                raise Fatal("SWE-Milestone pinned release is unavailable; prepare " + project)
            if sm.git(source, "status", "--porcelain", "--untracked-files=no"):
                raise Fatal("SWE-Milestone pinned release has modified files")
        prepared, self.imported, expected = sm.load_prepared(project)
        if (self.imported.get("project") != project or self.imported.get("version") != sm.VERSION
                or self.imported.get("workspace") != sm.PROJECTS[project]["workspace"]):
            raise Fatal("SWE-Milestone prepared project identity differs from its declaration")
        selected = sm.benchmark_scope(self.imported, expected, self.benchmark)
        tasks = sm.milestones(sm.DATA / sm.PROJECTS[project]["workspace"])
        if expected["features"] != [{"id": task["id"], "request": task["request"]} for task in tasks]:
            raise Fatal("SWE-Milestone tasks differ from the pinned release")
        if self.imported["milestones"] != [{key: value for key, value in task.items() if key != "request"}
                                           for task in tasks]:
            raise Fatal("SWE-Milestone grading sequence differs from the pinned release")
        self.imported = selected
        if (base != self.benchmark["revision"]
                or sm.git(prepared / "repo", "rev-parse", "HEAD").decode().strip() != self.imported["revision"]
                or sm.git(prepared / "repo", "status", "--porcelain")):
            raise Fatal("SWE-Milestone prepared starting repository changed")
        if "repository_additions" in self.imported:
            manifest["swe_milestone_repository_additions"] = self.imported["repository_additions"]
        self.python = sm.CACHE / "swe-milestone-venv" / "bin" / "python"
        if not self.python.is_file():
            raise Fatal("SWE-Milestone evaluator Python is missing; install benchmarks/swe-milestone-requirements.txt "
                        "in .benchmarks/swe-milestone-venv")
        self.artifacts = self.output / "swe-milestone-process"
        self.artifacts.mkdir()
        self.environment = clean_env()
        self.environment["PYTHONPATH"] = str(sm.UPSTREAM)
        receipt = execute_child([str(self.python), "-c", RUNTIME_PROBE, self.imported["baseline_image"],
                                 self.imported["baseline_image_id"]], sm.ROOT, None,
                                self.artifacts / "runtime.json", self.artifacts / "runtime.stderr.txt",
                                min(60, deadline - time.monotonic()), self.environment)
        save_json(self.artifacts / "runtime-process.json", receipt)
        if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
            raise Fatal("SWE-Milestone evaluator runtime unavailable; inspect " +
                        str(self.artifacts / "runtime.stderr.txt"))
        runtime = json.loads((self.artifacts / "runtime.json").read_text())
        manifest["swe_milestone_runtime"] = runtime
        self.result[self.config_key] = {"project": project, "status": "incomplete", "solved": None,
                                      "version": sm.VERSION, "pins": sm.PINS, "runtime": runtime}

    def evaluate(self):
        checker = self.result.get("scb_check", {}).get("tool", {}).get("executable")
        argv = [str(self.python), str(Path(sm.__file__)), "evaluate", self.config["project"],
                str(self.output), "--seconds", str(self.config["seconds"])]
        argv.extend(["--scb-check", checker] if checker else ["--no-quality"])
        graded = sum(task["graded"] for task in self.imported["milestones"])
        seconds = 2 * graded * self.config["seconds"] + (300 * len(self.imported["milestones"]) if checker else 0) + 60
        receipt = execute_child(argv, sm.ROOT, None, self.artifacts / "stdout.txt",
                                self.artifacts / "stderr.txt", seconds, self.environment)
        save_json(self.artifacts / "process.json", receipt)
        raw_path = self.output / "swe-milestone" / "result.json"
        report = {**self.result[self.config_key], "status": "error", "solved": None,
                  "process": receipt}
        status, passed = "error", None
        try:
            if receipt["exit_code"] not in (0, 1, 2) or receipt["timed_out"] or receipt["cancelled_signal"]:
                raise ValueError("SWE-Milestone grader failed or was interrupted")
            raw = json.loads(raw_path.read_text())
            if (not isinstance(raw, dict) or raw.get("schema") != "swe-milestone-lab-evaluation/v1"
                    or raw.get("project") != self.config["project"] or raw.get("pins") != sm.PINS
                    or raw.get("status") not in ("completed", "incomplete") or type(raw.get("solved")) is not bool):
                raise ValueError("SWE-Milestone grader returned an invalid report")
            milestones = raw.get("milestones")
            final = raw.get("final", {}).get("milestones")
            if (not isinstance(milestones, list) or not isinstance(final, list)
                    or [(row["id"], row["milestone"], row["graded"]) for row in milestones] !=
                    [(row["id"], row["milestone"], row["graded"]) for row in self.imported["milestones"]]
                    or [row["milestone"] for row in final] !=
                    [row["milestone"] for row in self.imported["milestones"] if row["graded"]]):
                raise ValueError("SWE-Milestone grader returned a different milestone sequence")
            scored = [row for row in milestones if row["graded"]] + final
            complete = all(row.get("status") in ("passed", "failed") and type(row.get("resolved")) is bool
                           and row["resolved"] == (row["status"] == "passed") for row in scored)
            complete = complete and all(row.get("quality", {}).get("status") in ("completed", "not_requested")
                                        and row.get("status") == "not_graded"
                                        for row in milestones if not row["graded"])
            complete = complete and all(row.get("quality", {}).get("status") in ("completed", "not_requested")
                                        for row in milestones)
            if raw["status"] == "completed" and not complete:
                raise ValueError("SWE-Milestone completed report is missing grading or quality results")
            if raw["solved"] != (raw["status"] == "completed" and bool(scored) and all(row["resolved"] for row in scored)):
                raise ValueError("SWE-Milestone solved verdict disagrees with milestone results")
            status = raw["status"]
            expected_exit = (0 if raw["solved"] else 1) if status == "completed" else 2
            if receipt["exit_code"] != expected_exit or status == "incomplete" and raw["solved"]:
                raise ValueError("SWE-Milestone grader exit status disagrees with its report")
            passed = raw["solved"] if status == "completed" else None
            report.update(raw)
            if any(row.get("status") == "error" or row.get("quality", {}).get("status") == "error"
                   for row in raw.get("milestones", []) + raw.get("final", {}).get("milestones", [])):
                status, passed = "error", None
                report["status"] = "error"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            status, passed = "error", None
            report.update(status="error", solved=None, error=str(exc))
        self.result[self.config_key] = report
        path = self.output / "swe-milestone-evaluation.json"
        save_json(path, report)
        summary = {"status": status, "passed": passed, "report_path": str(path)}
        if status in ("completed", "incomplete"):
            summary["checkpoints"] = [{"feature": row["id"], "status": row["status"],
                "passed": row["resolved"] if row["graded"] and row["status"] in ("passed", "failed") else None,
                "quality": row.get("quality", {}), "graded": row["graded"]} for row in report["milestones"]]
            final = report["final"]["milestones"]
            summary["final"] = {"passed": all(row["resolved"] for row in final)
                                if final and all(row["status"] in ("passed", "failed") for row in final) else None}
        return summary
