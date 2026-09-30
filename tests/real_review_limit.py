"""Opt-in installed-provider check of an accounted hard review stop.

Uses an isolated repository. A tiny token cap stops the review without a
conclusion prompt or another model response.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.host import git, save_json, snapshot
from lab.loops import FeatureProgress, WorkLimitReached, loop_policy
from lab.provider import Codex, clean_env
from lab.review import review_instructions
from lab.workflow import source_hashes
from real_compaction import native_receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = output / "fixture"
    repo.mkdir()
    files = {
        ".gitignore": "__pycache__/\n",
        "sample.py": "def double(value):\n    return value * 2\n",
        "test_sample.py": "import unittest\nfrom sample import double\n\n"
                          "class DoubleTests(unittest.TestCase):\n"
                          "    def test_integers(self):\n"
                          "        for value in (-5, 0, 7):\n"
                          "            with self.subTest(value=value):\n"
                          "                self.assertEqual(double(value), value + value)\n",
    }
    for name, content in files.items():
        (repo / name).write_text(content)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Review Verification")
    git(repo, "config", "user.email", "review-verification@example.invalid")
    git(repo, "config", "commit.gpgSign", "false")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Add isolated review verification fixture")
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"], cwd=repo,
                           capture_output=True, text=True, env=clean_env(), timeout=15)
    (output / "tests.stdout.txt").write_text(tests.stdout)
    (output / "tests.stderr.txt").write_text(tests.stderr)
    assert tests.returncode == 0, tests.stderr
    initial, code = snapshot(repo), source_hashes()
    policy = loop_policy({"max_review_raw": 1, "max_feature_raw": 200000})
    progress = FeatureProgress({"id": "review-verification"}, policy, 0)
    provider = Codex(repo, output / "provider", "gpt-5.5", "xhigh", time.monotonic() + 180,
                     200000, 4, "codex")
    result = {"status": "failed", "scope": "isolated installed-provider review verification",
              "policy": policy, "source_sha256": code}
    try:
        thread = provider.start_thread(writable=True)
        provider.work_limits = progress.limits(0, reviewing=True)
        prompt = ("Independently review this small repository without editing it. The requirement is "
                  "double(value) returns twice any integer, with a focused unit test. The runner captured "
                  "the following current file contents and actual successful test output; inspect the "
                  "repository as part of your review. First give a brief progress update, then run "
                  "python -m unittest discover -v and inspect sample.py before giving a verdict.\n" +
                  json.dumps(files) + "\nActual unittest output:\n" + tests.stdout + tests.stderr +
                  "\n" + review_instructions())
        try:
            provider.turn(thread, prompt, "review-verification-review-1", writable=True)
            raise AssertionError("tiny review cap did not stop the turn")
        except WorkLimitReached as stopped:
            result["trigger"] = stopped.signal
            assert provider.report()["measurement_complete"], "interruption usage incomplete"
            assert snapshot(repo) == initial, "review changed fixture state"
            result["review_status"] = "incomplete"
            result["generation_count"] = len(provider.turns)
            assert result["generation_count"] == 1, "review stop started another response"
        assert snapshot(repo) == initial, "review stop changed fixture state"
        assert source_hashes() == code, "runner changed during verification"
    except BaseException as error:
        result["error"] = str(error)
        raise
    finally:
        provider.close()
        try:
            result["usage"] = provider.report()
            receipts = native_receipts(provider, repo, provider.parent_threads)
            result["independent_receipts"] = receipts
            assert result["usage"]["measurement_complete"], "final accounting incomplete"
            assert result["usage"]["observed_raw_tokens"] == receipts["observed_raw_tokens"], "receipt total mismatch"
            if "error" not in result:
                result["status"] = "passed"
        except BaseException as error:
            result["error"] = str(error)
            raise
        finally:
            save_json(output / "result.json", result)
    print(json.dumps({"status": result["status"], "review_status": result["review_status"],
                      "raw_tokens": result["usage"]["observed_raw_tokens"]}))


if __name__ == "__main__":
    main()
