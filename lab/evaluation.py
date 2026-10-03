"""Generic benchmark evaluation lifecycle, independent of coding harnesses."""
import importlib
from pathlib import Path

from benchmarks.evaluators import ADAPTERS
from .host import Fatal, git, save_json


class BaseEvaluator:
    config_key = None
    retain_stopped_attempts = False

    def __init__(self, benchmark, output, result):
        self.benchmark, self.output, self.result = benchmark, output, result

    @classmethod
    def expand(cls, data, path):
        return data

    def start(self, base, manifest, deadline):
        pass

    def baseline_measurement(self, base):
        return None

    def checkpoint(self, checkout, checkpoint, quality_tool, deadline):
        pass

    def final(self, checkout):
        pass

    def evaluate(self):
        raise NotImplementedError


def adapter_type(benchmark):
    selected = set(benchmark) & ADAPTERS.keys()
    if len(selected) > 1:
        raise ValueError("a benchmark may declare only one evaluator")
    if not selected:
        return BaseEvaluator
    key = selected.pop()
    adapter = importlib.import_module(ADAPTERS[key]).Evaluator
    if not issubclass(adapter, BaseEvaluator) or adapter.config_key != key:
        raise ValueError("invalid benchmark evaluator registration: " + key)
    return adapter


def make_evaluator(benchmark, output, result):
    """Use the host grader when the workflow runs in a frozen executor."""
    import os
    adapter = adapter_type(benchmark)
    if os.environ.get('AGENT_LAB_EXECUTOR_PRIVATE'):
        from .executor import RemoteEvaluator
        return RemoteEvaluator(benchmark, output, result, adapter)
    return adapter(benchmark, output, result)


def retain_attempt(checkout, feature):
    """Save actually applied edits at a stopped boundary for external grading."""
    previous = git(checkout, "rev-parse", "HEAD").decode().strip()
    dirty = git(checkout, "status", "--porcelain").decode()
    if git(checkout, "ls-files", "--unmerged"):
        raise Fatal("cannot retain an unmerged benchmark attempt")
    if dirty:
        git(checkout, "add", "--all")
        if git(checkout, "diff", "--cached", "--name-only"):
            git(checkout, "commit", "-qm", f"Checkpoint unapproved stopped attempt: {feature}")
    if git(checkout, "status", "--porcelain"):
        raise Fatal("cannot retain stopped attempt as a clean checkpoint")
    head = git(checkout, "rev-parse", "HEAD").decode().strip()
    return {"previous_head": previous, "retention_commit": head if head != previous else None,
            "working_tree_status_before_retention": dirty}


def save_result(output, result):
    """Publish the owned run report atomically before and after grading."""
    temporary = output / "result.json.tmp"
    save_json(temporary, result)
    temporary.replace(output / "result.json")


def finish(evaluator):
    """Evaluate saved submissions after provider shutdown, retaining failures."""
    result, output = evaluator.result, evaluator.output
    workflow_status = result["status"]
    save_json(output / "before-evaluation.json", result)
    # A killed evaluator must never leave a successful overall result on disk.
    pending = {**result, "evaluation": {**result["evaluation"], "status": "incomplete",
                                       "passed": None, "workflow_status": workflow_status}}
    if workflow_status == "passed":
        pending.update(status="failed", error="Benchmark evaluation has not completed")
    save_result(output, pending)
    try:
        report = evaluator.evaluate()
        if not isinstance(report, dict) or report.get("status") not in ("completed", "incomplete", "error"):
            raise ValueError("evaluator returned an invalid status")
        if report["status"] == "completed":
            if type(report.get("passed")) is not bool:
                raise ValueError("completed evaluation needs a boolean passed verdict")
        elif report.get("passed") is not None:
            raise ValueError("incomplete evaluation cannot claim a test verdict")
        path = report.get("report_path")
        if not isinstance(path, str) or not Path(path).is_file():
            raise ValueError("evaluator did not save its report")
        result["evaluation"].update(report, workflow_status=workflow_status)
        if (report["status"] != "completed" or not report["passed"]) and result["status"] == "passed":
            error = ("Benchmark tests failed" if report["status"] == "completed"
                     else "Benchmark evaluation did not complete")
            result.update(status="failed", error=error, failure={
                "origin": "agent" if report["status"] == "completed" else "evaluator",
                "stage": "evaluation", "message": error})
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        error = str(exc) or "evaluation interrupted"
        result["evaluation"].update(status="error", passed=None, error=error,
                                    workflow_status=workflow_status)
        if result["status"] in ("passed", "needs_attention"):
            result.update(status="failed", error=error, failure={
                "origin": "evaluator", "stage": "evaluation", "message": error})
