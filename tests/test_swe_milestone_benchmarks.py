"""All advertised SWE-Milestone projects have committed runner inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks import swe_milestone as sm
from lab.config import load_benchmark


class CommittedMilestoneBenchmarksTests(unittest.TestCase):
    counts = {"ripgrep": 13, "dubbo": 13, "element-web": 18, "navidrome": 9,
              "nushell": 13, "scikit-learn": 12, "go-zero": 23}

    def test_every_project_has_a_complete_runner_input(self):
        self.assertEqual(set(sm.PROJECTS), set(self.counts))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            # Substitute only the machine-local repository dependency. The
            # committed requests, revision and checks go through the real loader.
            for project, count in self.counts.items():
                with self.subTest(project=project):
                    path = sm.ROOT / "benchmarks" / f"swe-milestone-{project}.json"
                    benchmark = json.loads(path.read_text())
                    self.assertEqual(benchmark["repo"],
                                     f"../.benchmarks/swe-milestone-projects/{project}/repo")
                    self.assertRegex(benchmark["revision"], r"^[0-9a-f]{40}$")
                    benchmark["repo"] = str(folder)
                    config = folder / "benchmark.json"
                    config.write_text(json.dumps(benchmark))
                    loaded = load_benchmark(config)
                    self.assertEqual(loaded["name"], f"swe-milestone-{project}-{sm.VERSION}")
                    self.assertEqual(len(loaded["features"]), count)
                    self.assertEqual(loaded["checks"], sm.PROJECTS[project]["checks"])

    @unittest.skipUnless((sm.DATA / "README.md").is_file(), "requires the pinned dataset checkout")
    def test_committed_tasks_match_the_pinned_upstream_sequence_verbatim(self):
        self.assertEqual(sm.git(sm.DATA, "rev-parse", "HEAD").decode().strip(), sm.PINS["data"])
        for project, spec in sm.PROJECTS.items():
            with self.subTest(project=project):
                path = sm.ROOT / "benchmarks" / f"swe-milestone-{project}.json"
                benchmark = json.loads(path.read_text())
                tasks = sm.milestones(sm.DATA / spec["workspace"])
                self.assertEqual(benchmark["features"],
                                 [{"id": task["id"], "request": task["request"]} for task in tasks])
