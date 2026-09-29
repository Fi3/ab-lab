"""Verify the installed upstream evaluator without generating model responses."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.config import load_benchmark
from lab.host import save_json
from lab.slopcodebench import grade_one, preflight


def source_hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file()}


def main():
    cases = {
        "reference": ("scb-code-search.json", "checkpoint_1", False),
        "broken": ("scb-code-search.json", "checkpoint_1", True),
        "regression": ("scb-code-search.json", "checkpoint_2", False),
        "checkpoint-3": ("scb-code-search.json", "checkpoint_3", False),
        "checkpoint-4": ("scb-code-search.json", "checkpoint_4", False),
        "checkpoint-5": ("scb-code-search.json", "checkpoint_5", False),
        "config-service": ("scb-config-service.json", "checkpoint_1", False),
        "log-query": ("scb-log-query.json", "checkpoint_1", False),
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", choices=cases, action="append", dest="cases")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results, benchmarks = [], {}
    for name in args.cases or cases:
        definition, checkpoint, broken = cases[name]
        benchmark = load_benchmark(ROOT / "benchmarks" / definition)
        benchmarks[definition] = benchmark
        case_output = output / name
        case_output.mkdir()
        runtime = preflight(benchmark, case_output, time.monotonic() + 60)
        config = {**benchmark["slopcodebench"], "expected_runtime": runtime}
        snapshot = case_output / "snapshot"
        shutil.copytree(Path(config["dataset"]) / config["problem"] / "solutions" / checkpoint, snapshot)
        if broken:
            (snapshot / "code_search.py").write_text('raise SystemExit("deliberately broken submission")\n')
        before = source_hashes(snapshot)
        result = grade_one(config, {"feature": name, "snapshot": str(snapshot)}, case_output, checkpoint)
        results.append(result)
        save_json(output / (name + "-result.json"), result)
        assert source_hashes(snapshot) == before, "grading modified the captured source"
        assert result["status"] == ("failed" if broken else "passed"), result
        assert result["strict_pass"] is (not broken), result
        assert result["tests"]["total"] > 0, result
        print(name + ": " + result["status"] + " " + json.dumps(result["tests"]), flush=True)
    save_json(output / "result.json", {
        "status": "passed", "generation": "none", "benchmarks": benchmarks,
        "results": results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
