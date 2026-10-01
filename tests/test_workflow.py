import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from lab.config import settings
from lab.workflow import run, compare, interaction
from lab.review import validate_review
from test_core import repo_at


def verdict(text=None, priority="P2", *, incomplete_reason=None):
    return {"status": "incomplete" if incomplete_reason is not None else "complete",
            "findings": [] if text is None else [{"priority": priority, "text": text}],
            "incomplete_reason": incomplete_reason}


def review_arguments(prompt, value):
    review_id = next(line.removeprefix("Review target: ") for line in prompt.splitlines()
                     if line.startswith("Review target: "))
    return {"review_id": review_id, **value}


class FakeCodex:
    instances = []

    def __init__(self, repo, artifacts, *args, **kwargs):
        self.repo = Path(repo)
        self.options = kwargs
        self.artifacts = Path(artifacts)
        self.artifacts.mkdir()
        self.identity = {"codex_version": "test", "auth": "chatgpt", "model": "test", "effort": "test", "effective_config_sha256": "test"}
        self.calls, self.authors, self.fixes = [], {}, {}
        self.threads = 0
        self.tool_handlers = {}
        self.instances.append(self)

    def start_thread(self, writable=False, tools=None, tool_handler=None):
        self.threads += 1
        thread = f"t{self.threads}"
        if tools:
            self.tool_handlers[thread] = tool_handler
        return thread

    def review_command_argv(self, checkout, argv):
        return argv

    def tool_call(self, thread, name, arguments, call_id):
        return self.tool_handlers[thread](name, arguments, f"{thread}:{call_id}")

    def submit_review(self, thread, prompt, label, value=None):
        self.tool_call(thread, "submit_review", review_arguments(prompt, verdict() if value is None else value), label + "-verdict")
        return "Review submitted."

    def turn(self, thread, prompt, label, **kwargs):
        self.calls.append((label, thread, prompt, kwargs))
        if label.endswith("-implement"):
            name = label.removesuffix("-implement")
            patch = f"*** Begin Patch\n*** Add File: {name}.py\n+value = 1\n*** End Patch\n"
            self.tool_call(thread, "host_edit", {"patch": patch}, label)
            return "Implemented."
        if "-review-" in label:
            return self.submit_review(thread, prompt, label, verdict("Change one.py value to 2") if label == "one-review-1" else verdict())
        if "-fix-" in label:
            patch = "*** Begin Patch\n*** Update File: one.py\n@@\n-value = 1\n+value = 2\n*** End Patch\n"
            self.tool_call(thread, "host_edit", {"patch": patch}, label)
            return "Repaired."
        raise AssertionError(label)

    def report(self):
        return {"observed_raw_tokens": 100, "measurement_complete": True, "unpriced_or_incomplete_turns": [], "turns": []}

    def close(self):
        pass


class WorkflowTests(unittest.TestCase):
    def test_two_features_review_repair_same_threads_without_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            initial = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
            bench = {"name": "generic", "repo": str(repo), "revision": "HEAD", "features": [
                {"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
                "checks": ["test -f one.py && test -f two.py"]}
            result = run(bench, settings({}), root / "run", 30, 10000, 30, backend=FakeCodex)
            self.assertEqual(result["status"], "passed", result)
            calls = FakeCodex.instances[-1].calls
            unique = list(dict.fromkeys(c[0] for c in calls))
            self.assertEqual(unique, ["one-implement", "one-review-1", "one-fix-1", "one-review-2", "two-implement", "two-review-1"])
            threads = {label: thread for label, thread, _, _ in calls}
            self.assertEqual(threads["one-implement"], threads["one-fix-1"])
            self.assertEqual(threads["one-review-1"], threads["one-review-2"])
            self.assertNotEqual(threads["one-implement"], threads["one-review-1"])
            self.assertEqual(len(result["final_commits"]), 3)
            self.assertEqual(result["final_commits"][-1], result["checkpoints"][-1]["head"])
            self.assertEqual(initial, subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]))
            self.assertFalse((repo / "one.py").exists())
            with self.assertRaises(FileExistsError):
                run(bench, settings({}), root / "run", 30, 10000, 30, backend=FakeCodex)

    def test_failures_retained_not_replaced(self):
        class Broken(FakeCodex):
            def turn(self, *args, **kwargs):
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            b = {"name": "b", "repo": str(repo), "revision": "HEAD", "features": [{"id": "f", "request": "x"}], "checks": ["true"]}
            result = run(b, settings({}), root / "failed", 20, 100, 5, backend=Broken)
            self.assertEqual(result["status"], "failed")
            self.assertTrue((root / "failed" / "result.json").is_file())
            self.assertIn("provider unavailable", result["error"])

    def test_thread_start_failure_is_attributed_to_provider_and_retained(self):
        class Disconnected(FakeCodex):
            def start_thread(self, **options):
                raise RuntimeError("thread/start disconnected")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bench = {"name": "b", "repo": str(repo_at(root / "input")), "revision": "HEAD",
                     "features": [{"id": "one", "request": "Create one."}], "checks": ["true"]}
            result = run(bench, settings({}), root / "run", 30, 10000, 10, backend=Disconnected)
            self.assertEqual(result["failure"]["origin"], "provider")
            self.assertEqual(result["failure"]["stage"], "one-implement")
            self.assertEqual(json.loads((root / "run/result.json").read_text()), result)

    def test_declared_after_read_fixture_exercises_conflict_in_actual_loop(self):
        class ConflictCodex(FakeCodex):
            feedback = []

            def turn(self, thread, prompt, label, **kwargs):
                if label == "one-implement":
                    self.calls.append((label, thread, prompt, kwargs))
                    self.tool_call(thread, "host_read", {"path": "source.py"}, label+"-read")
                    stale = "*** Begin Patch\n*** Update File: source.py\n@@\n-first\n+start\n*** End Patch\n"
                    response = self.tool_call(thread, "host_edit", {"patch": stale}, label+"-stale")
                    self.feedback.append(response["text"])
                    corrected = "*** Begin Patch\n*** Update File: source.py\n@@\n-peer\n+start\n*** Add File: one.py\n+value = 1\n*** End Patch\n"
                    self.tool_call(thread, "host_edit", {"patch": corrected}, label+"-corrected")
                    return "Implemented."
                if label == "one-review-1":
                    return self.submit_review(thread, prompt, label)
                return super().turn(thread, prompt, label, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = repo_at(root / "input")
            benchmark = {"name": "conflict", "repo": str(source), "revision": "HEAD",
                "features": [{"id": "one", "request": "implement one"}, {"id": "two", "request": "implement two"}],
                "checks": ["true"],
                "after_read": {"path": "source.py", "command": "printf 'peer\\nmiddle\\nlast\\n' > source.py"}}
            result = run(benchmark, settings({}), root / "run", 30, 10000, 30, backend=ConflictCodex)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(len(ConflictCodex.feedback), 1, result)
            self.assertIn("+peer", ConflictCodex.feedback[0])
            events = (root / "run" / "one-host" / "events.jsonl").read_text()
            self.assertIn('"factor": "C08"', events)
            self.assertTrue((root / "run" / "fixture-after-read" / "result.json").exists())

            other = run(benchmark, settings({"C08": False}), root / "full", 30, 10000, 30, backend=ConflictCodex)
            self.assertEqual(len(ConflictCodex.feedback), 2, other)
            self.assertIn("Current complete file:\npeer\nmiddle\nlast", ConflictCodex.feedback[1])

    def test_final_prose_is_never_a_review_verdict(self):
        class Prose(FakeCodex):
            def turn(self, thread, prompt, label, **options):
                if "-review-" in label:
                    return "NO_FINDINGS"
                return super().turn(thread, prompt, label, **options)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bench = {"name": "prose", "repo": str(repo_at(root / "input")), "revision": "HEAD",
                     "features": [{"id": "one", "request": "create one"}], "checks": ["true"]}
            result = run(bench, settings({}), root / "run", 30, 10000, 20, backend=Prose)
            self.assertEqual(result["status"], "needs_attention", result)
            self.assertIsNone(result["reviews"][0]["approved"])
            self.assertIn("without an accepted submit_review", result["reviews"][0]["incomplete_reason"])


class ComparisonTests(unittest.TestCase):
    def sample(self, raw, overrides=None):
        return {"status": "passed", "comparison_key": "same", "factors": settings(overrides or {}),
                "usage": {"observed_raw_tokens": raw, "measurement_complete": True}}

    def test_percentage_names_its_denominator(self):
        self.assertEqual(compare(self.sample(200), self.sample(150, {"C08": False}))["observed_reduction_percent"], 25)
        b = self.sample(150)
        b["comparison_key"] = "different"
        with self.assertRaises(ValueError):
            compare(self.sample(200), b)
        b = self.sample(150)
        b["usage"]["measurement_complete"] = False
        with self.assertRaises(ValueError):
            compare(self.sample(200), b)

    def test_joint_interaction_uses_four_matching_cells(self):
        a = self.sample(200, {"C08": False, "C20": False})
        b = self.sample(170, {"C20": False})
        c = self.sample(180, {"C08": False})
        d = self.sample(140)
        self.assertEqual(interaction(a, b, c, d)["extra_joint_saving_raw_tokens"], 10)
        with self.assertRaises(ValueError):
            interaction(a, b, b, d)


if __name__ == "__main__":
    unittest.main()
