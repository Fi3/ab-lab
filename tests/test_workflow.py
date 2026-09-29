import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from lab.config import settings
from lab.workflow import run, review_clean, compare, interaction
from test_core import repo_at


class FakeCodex:
    instances = []

    def __init__(self, repo, artifacts, *args, **kwargs):
        self.repo = Path(repo)
        self.artifacts = Path(artifacts)
        self.artifacts.mkdir()
        self.identity = {"codex_version": "test", "auth": "chatgpt", "model": "test", "effort": "test", "effective_config_sha256": "test"}
        self.calls, self.authors, self.fixes = [], {}, {}
        self.threads = 0
        self.instances.append(self)

    def start_thread(self, writable=False):
        self.threads += 1
        return f"t{self.threads}"

    def turn(self, thread, prompt, label, **kwargs):
        self.calls.append((label, thread, prompt, kwargs))
        if label.endswith("-implement"):
            n = self.authors.get(label, 0)
            self.authors[label] = n+1
            if n == 0:
                name = label.removesuffix("-implement")
                return f"@standalone edit implement {name}\n*** Begin Patch\n*** Add File: {name}.py\n+value = 1\n*** End Patch\n@standalone end"
            return "@standalone done"
        if "-review-" in label:
            return "FINDINGS\n- [P2] Change one.py value to 2" if label == "one-review-1" else "NO_FINDINGS"
        if "-fix-" in label:
            n = self.fixes.get(label, 0)
            self.fixes[label] = n+1
            return ("@standalone edit resolve review\n*** Begin Patch\n*** Update File: one.py\n@@\n-value = 1\n+value = 2\n*** End Patch\n@standalone end" if n == 0 else "@standalone done")
        if label == "integration-plan":
            return "One final commit for each feature, with its tests and repairs."
        if label == "integration-accept":
            base = subprocess.check_output(["git", "-C", str(self.repo), "rev-list", "--max-parents=0", "HEAD"], text=True).strip()
            # Tests rewrite only their own disposable clone.
            subprocess.run(["git", "-C", str(self.repo), "reset", "--soft", base], check=True)
            subprocess.run(["git", "-C", str(self.repo), "reset"], check=True, capture_output=True)
            for name in ("one", "two"):
                subprocess.run(["git", "-C", str(self.repo), "add", name+".py"], check=True)
                subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "ADD "+name], check=True)
            return "Finished"
        raise AssertionError(label)

    def report(self):
        return {"observed_raw_tokens": 100, "measurement_complete": True, "unpriced_or_incomplete_turns": [], "turns": []}

    def close(self):
        pass


class WorkflowTests(unittest.TestCase):
    def test_two_features_review_repair_same_threads_then_integrate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = repo_at(root / "input")
            initial = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"])
            bench = {"name": "generic", "repo": str(repo), "revision": "HEAD", "features": [
                {"id": "one", "request": "create one"}, {"id": "two", "request": "create two"}],
                "checks": ["test -f one.py && test -f two.py"], "instructions": "", "defer_documentation": True}
            result = run(bench, settings({}), root / "run", 30, 10000, 30, backend=FakeCodex)
            self.assertEqual(result["status"], "passed", result)
            calls = FakeCodex.instances[-1].calls
            unique = list(dict.fromkeys(c[0] for c in calls))
            self.assertEqual(unique, ["one-implement", "one-review-1", "one-fix-1", "one-review-2", "two-implement", "two-review-1", "integration-plan", "integration-accept"])
            threads = {label: thread for label, thread, _, _ in calls}
            self.assertEqual(threads["one-implement"], threads["one-fix-1"])
            self.assertEqual(threads["one-review-1"], threads["one-review-2"])
            self.assertEqual(threads["integration-plan"], threads["integration-accept"])
            self.assertNotEqual(threads["one-implement"], threads["one-review-1"])
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
            b = {"name": "b", "repo": str(repo), "revision": "HEAD", "features": [{"id": "f", "request": "x"}], "checks": ["true"], "instructions": "", "defer_documentation": True}
            result = run(b, settings({}), root / "failed", 20, 100, 5, backend=Broken)
            self.assertEqual(result["status"], "failed")
            self.assertTrue((root / "failed" / "result.json").is_file())
            self.assertIn("provider unavailable", result["error"])

    def test_declared_after_read_fixture_exercises_conflict_in_actual_loop(self):
        class ConflictCodex(FakeCodex):
            feedback = []

            def turn(self, thread, prompt, label, **kwargs):
                if label == "one-implement":
                    self.calls.append((label, thread, prompt, kwargs))
                    n = self.authors.get(label, 0)
                    self.authors[label] = n+1
                    if n == 0:
                        return "@standalone read source.py"
                    if n == 1:
                        return "@standalone edit stale\n*** Begin Patch\n*** Update File: source.py\n@@\n-first\n+start\n*** End Patch\n@standalone end"
                    if n == 2:
                        self.feedback.append(prompt)
                        return "@standalone edit corrected\n*** Begin Patch\n*** Update File: source.py\n@@\n-peer\n+start\n*** Add File: one.py\n+value = 1\n*** End Patch\n@standalone end"
                    return "@standalone done"
                if label == "one-review-1":
                    return "NO_FINDINGS"
                if label == "integration-accept":
                    return "Already two feature commits plus one fixture commit"
                return super().turn(thread, prompt, label, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = repo_at(root / "input")
            benchmark = {"name": "conflict", "repo": str(source), "revision": "HEAD",
                "features": [{"id": "one", "request": "implement one"}, {"id": "two", "request": "implement two"}],
                "checks": ["true"], "instructions": "", "defer_documentation": True,
                "after_read": {"path": "source.py", "command": "printf 'peer\\nmiddle\\nlast\\n' > source.py"}}
            # Final integration intentionally fails its commit-count gate in this
            # fixture; the real author loop must still have exercised C08 first.
            result = run(benchmark, settings({}), root / "run", 30, 10000, 30, backend=ConflictCodex)
            self.assertEqual(len(ConflictCodex.feedback), 1, result)
            self.assertIn("+peer", ConflictCodex.feedback[0])
            events = (root / "run" / "one-host" / "events.jsonl").read_text()
            self.assertIn('"factor": "C08"', events)
            self.assertTrue((root / "run" / "fixture-after-read" / "result.json").exists())

            class RejectedThenConflict(ConflictCodex):
                invalid_sent = False

                def turn(self, thread, prompt, label, **kwargs):
                    if not self.invalid_sent:
                        self.invalid_sent = True
                        return "not an operative directive"
                    return super().turn(thread, prompt, label, **kwargs)

            other = run(benchmark, settings({"C08": False}), root / "full", 30, 10000, 30, backend=RejectedThenConflict)
            self.assertEqual(len(ConflictCodex.feedback), 2, other)
            self.assertIn("Current complete file:\npeer\nmiddle\nlast", ConflictCodex.feedback[1])

    def test_ambiguous_or_missing_review_marker_is_not_success(self):
        self.assertTrue(review_clean("NO_FINDINGS\nLooks good."))
        self.assertFalse(review_clean("FINDINGS\n- [P2] Broken"))
        for text in ("probably okay", "NO_FINDINGS\nFINDINGS\n- Oops"):
            with self.assertRaises(ValueError):
                review_clean(text)


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
        a = self.sample(200, {"C08": False, "C25": False})
        b = self.sample(170, {"C25": False})
        c = self.sample(180, {"C08": False})
        d = self.sample(140)
        self.assertEqual(interaction(a, b, c, d)["extra_joint_saving_raw_tokens"], 10)
        with self.assertRaises(ValueError):
            interaction(a, b, b, d)


if __name__ == "__main__":
    unittest.main()
