"""Benchmark text comes from the pinned upstream renderer, without lab advice."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from lab import scb_bridge


class BridgePromptTests(unittest.TestCase):
    def test_renderer_output_is_forwarded_verbatim_with_reproducible_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template_path = root / "configs/prompts/just-solve.jinja"
            template_path.parent.mkdir(parents=True)
            template_bytes = b"UPSTREAM TEMPLATE\n{{ spec }}\n"
            template_path.write_bytes(template_bytes)
            renderer_path = root / "render.py"
            renderer_path.write_text("# upstream renderer source\n")
            tests = root / "tests"
            tests.mkdir()
            for name in ("first", "second"):
                (tests / f"test_{name}.py").touch()
            specs = {"first": "FIRST RAW SPEC", "second": "SECOND RAW SPEC"}
            requests = ["\nInitial upstream prompt.\n", "Continuation upstream prompt.\n\n"]
            renderer = SimpleNamespace(__file__=str(renderer_path),
                                       render_prompt=Mock(side_effect=requests))
            modules = {"slop_code.common": SimpleNamespace(render=renderer)}
            problem = SimpleNamespace(path=root, name="fixture", version=1, entry_file="main",
                iterate_checkpoints=lambda: [SimpleNamespace(name=name) for name in specs],
                get_checkpoint_spec=specs.__getitem__)
            environment = SimpleNamespace(type="local", name="python-test",
                format_entry_file=Mock(return_value="main.py"),
                get_command=Mock(return_value="python main.py"))
            with patch.dict(sys.modules, modules):
                result = scb_bridge.describe(problem, environment, root)
            self.assertEqual(result["features"], [
                {"id": name, "request": request} for name, request in zip(specs, requests)])
            self.assertNotIn("instructions", result)
            renderer.render_prompt.assert_has_calls([
                call(spec_text=spec, context={"is_continuation": bool(index),
                    "agent_type": None, "agent_version": "", "model_name": None},
                    prompt_template=template_bytes.decode(), entry_file="main.py",
                    entry_command="python main.py")
                for index, spec in enumerate(specs.values())])
            provenance = result["prompt_provenance"]
            self.assertEqual(provenance["template_sha256"], hashlib.sha256(template_bytes).hexdigest())
            self.assertEqual(provenance["renderer_sha256"],
                             hashlib.sha256(renderer_path.read_bytes()).hexdigest())
            for item, spec, request in zip(provenance["checkpoints"], specs.values(), requests):
                self.assertEqual(item["spec_sha256"], hashlib.sha256(spec.encode()).hexdigest())
                self.assertEqual(item["prompt_sha256"], hashlib.sha256(request.encode()).hexdigest())

    def test_pinned_benchmark_prompts_match_upstream_byte_for_byte(self):
        root = Path(__file__).resolve().parents[1]
        runner = root / ".benchmarks/slop-code-bench"
        dataset = root / ".benchmarks/scb-problems"
        python = runner / ".venv/bin/python"
        if not python.is_file() or not (dataset / "code_search").is_dir():
            self.skipTest("pinned SlopCodeBench checkout and evaluator environment are not installed")
        script = r'''
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root))
from lab import scb_bridge
config = {
    "runner": str(root / ".benchmarks/slop-code-bench"),
    "dataset": str(root / ".benchmarks/scb-problems"),
    "problem": "code_search",
    "environment": "configs/environments/docker-python3.12-uv.yaml",
}
problem, environment = scb_bridge.load(config)
result = scb_bridge.describe(problem, environment, config["runner"])
from slop_code.common.render import render_prompt
template = (pathlib.Path(config["runner"]) / "configs/prompts/just-solve.jinja").read_text()
for index, (checkpoint, feature) in enumerate(zip(problem.iterate_checkpoints(), result["features"])):
    expected = render_prompt(
        problem.get_checkpoint_spec(checkpoint.name),
        {"is_continuation": bool(index), "agent_type": None, "agent_version": "", "model_name": None},
        template, environment.format_entry_file(problem.entry_file),
        environment.get_command(problem.entry_file, is_agent_run=True))
    assert feature["request"].encode("utf-8") == expected.encode("utf-8")
    assert result["prompt_provenance"]["checkpoints"][index]["prompt_sha256"] == hashlib.sha256(expected.encode()).hexdigest()
assert "Use a virtual environment" in result["features"][0]["request"]
assert "Keep using the same virtual environment" in result["features"][1]["request"]
assert "instructions" not in result
print(json.dumps({"checkpoints": len(result["features"]), "byte_faithful": True}))
'''
        completed = subprocess.run([str(python), "-I", "-c", script, str(root)],
                                   capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"checkpoints": 5, "byte_faithful": True})


if __name__ == "__main__":
    unittest.main()
