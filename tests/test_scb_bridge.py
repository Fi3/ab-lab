"""The optional evaluator cannot replace trusted tests or invent successful grades."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lab import scb_bridge


class CopyModel(SimpleNamespace):
    def model_copy(self, update):
        return CopyModel(**{**vars(self), **update})


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        (self.snapshot / "main.py").write_text("original\n")
        self.output = self.root / "evaluation"
        self.environment = SimpleNamespace(type="local")
        self.checkpoint = SimpleNamespace(include_prior_tests=True)
        self.problem = SimpleNamespace(load_checkpoint=Mock(return_value=self.checkpoint))
        self.result = SimpleNamespace(
            pass_counts={"Core": 2, "Error": 1},
            total_counts={"Core": 2, "Error": 1, "Regression": 1},
            pytest_collected=4, pytest_exit_code=1,
            infrastructure_failure=False, test_collection_hash="test-inventory",
            save=Mock())
        self.run = Mock(return_value=self.result)
        modules = {
            "slop_code.common": SimpleNamespace(WORKSPACE_TEST_DIR=".evaluation_tests"),
            "slop_code.evaluation.pytest_runner": SimpleNamespace(run_checkpoint_pytest=self.run),
            "slop_code.logging": SimpleNamespace(setup_logging=Mock()),
        }
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        patch.object(scb_bridge, "check", return_value={"image": "pinned-image"}).start()

    def evaluate(self, **kwargs):
        return scb_bridge.evaluate(self.problem, self.environment, self.snapshot,
                                   self.output, "checkpoint_2", **kwargs)

    def test_regression_failure_is_distinct_from_current_checkpoint_success(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["strict_pass"])
        self.assertTrue(result["isolated_pass"])
        self.assertTrue(result["core_pass"])
        self.assertEqual(result["tests"], {"passed": 3, "total": 4})
        self.assertEqual(result["strict_pass_rate"], 0.75)

    def test_evaluator_receives_disposable_copy_and_exact_upstream_checkpoint(self):
        def mutate(**kwargs):
            (kwargs["submission_path"] / "main.py").write_text("modified by evaluator\n")
            self.assertIs(kwargs["checkpoint"], self.checkpoint)
            return self.result

        self.run.side_effect = mutate
        self.evaluate()
        self.assertEqual((self.snapshot / "main.py").read_text(), "original\n")
        self.assertEqual((self.output / "submission/main.py").read_text(),
                         "modified by evaluator\n")
        self.result.save.assert_called_once_with(self.output)

    def test_infrastructure_failure_never_becomes_a_task_failure_or_success(self):
        self.result.infrastructure_failure = True
        self.result.pytest_exit_code = 2
        result = self.evaluate()
        self.assertEqual(result["status"], "error")
        self.assertNotIn("strict_pass", result)
        self.assertNotIn("core_pass_rate", result)
        self.assertIn("infrastructure", result["error"])
        self.result.save.assert_called_once()

    def test_empty_inventory_is_not_a_pass(self):
        self.result.pass_counts = self.result.total_counts = {}
        self.result.pytest_collected = 0
        self.result.pytest_exit_code = 0
        self.assertEqual(self.evaluate()["status"], "error")

    def test_submission_cannot_supply_trusted_tests_or_forged_reports(self):
        for reserved in (".evaluation_tests", ".scbench"):
            with self.subTest(reserved=reserved):
                path = self.snapshot / reserved
                path.symlink_to(self.root / "does-not-exist")
                with self.assertRaisesRegex(ValueError, "reserved"):
                    self.evaluate()
                path.unlink()
        self.run.assert_not_called()

    def test_changed_runtime_is_rejected_before_upstream_execution(self):
        with self.assertRaisesRegex(ValueError, "runtime changed"):
            self.evaluate(expected_runtime={"image": "a-different-image"})
        self.run.assert_not_called()
        self.assertFalse((self.output / "submission").exists())

    def test_docker_wrapper_adds_ownership_label_without_reinterpreting_arguments(self):
        docker = self.root / "docker with ' quotes"
        docker.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        docker.chmod(0o700)
        self.output.mkdir()
        environment = CopyModel(type="docker", docker=CopyModel(binary=str(docker)))
        labeled = scb_bridge.labeled_environment(environment, self.output)
        arguments = ["run", "--rm", "$(literal)", "argument with spaces"]
        completed = subprocess.run([labeled.docker.binary, *arguments],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout),
                         ["run", "--label", scb_bridge.container_label(self.output), *arguments[1:]])
        completed = subprocess.run([labeled.docker.binary, "version"],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout), ["version"])
        self.assertEqual(environment.docker.binary, str(docker))

    def test_cleanup_only_removes_containers_owned_by_this_evaluation(self):
        client = Mock()
        container = Mock()
        client.containers.list.return_value = [container]
        docker = SimpleNamespace(from_env=Mock(return_value=client),
                                 errors=SimpleNamespace(NotFound=FileNotFoundError))
        with patch.dict(sys.modules, {"docker": docker}):
            result = scb_bridge.cleanup(SimpleNamespace(type="docker"), self.output)
        self.assertEqual(result["status"], "completed")
        client.containers.list.assert_called_once_with(
            all=True, filters={"label": scb_bridge.container_label(self.output)})
        container.remove.assert_called_once_with(force=True)
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
