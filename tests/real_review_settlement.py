"""Opt-in real Codex check of priced settlement after an expired review deadline.

One fresh, benign, tool-free review gets a one-second exploration allowance.
The expired review must remain stopped while its in-flight response settles.
This verifies cancellation/accounting, not benchmark completion or solution grade.
No prior conversation, failed request, benchmark source, or benchmark prompt is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.host import git, save_json, snapshot
from lab.loops import FeatureProgress, POLICY_VERSION, WorkLimitReached, loop_policy
from lab.provider import Codex
from lab.review import parse_review, review_instructions
from lab.workflow import source_hashes
from real_compaction import native_receipts, save_native_receipts


MODEL, EFFORT = "gpt-5.6-sol", "xhigh"
SECONDS, MAX_RAW, MAX_TURNS = 180, 200000, 1
REVIEW_SECONDS, SETTLE_SECONDS = 1, 600
SOURCE = '''from bisect import bisect_right


class IntervalIndex:
    """Index the union of half-open integer intervals."""

    def __init__(self, intervals):
        merged = []
        for start, end in sorted(intervals):
            if start > end:
                raise ValueError("interval ends before it starts")
            if start == end:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        self.intervals = tuple(merged)
        self.starts = tuple(start for start, _ in merged)

    def contains(self, point):
        position = bisect_right(self.starts, point) - 1
        return position >= 0 and point < self.intervals[position][1]

    def overlap_size(self, start, end):
        if start > end:
            raise ValueError("interval ends before it starts")
        return sum(max(0, min(end, right) - max(start, left))
                   for left, right in self.intervals)

    def gaps(self, start, end):
        if start > end:
            raise ValueError("interval ends before it starts")
        cursor = start
        result = []
        for left, right in self.intervals:
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                result.append((cursor, min(left, end)))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
        return result

    def union(self, other):
        return IntervalIndex(self.intervals + other.intervals)

    def intersection(self, other):
        result = []
        first = second = 0
        while first < len(self.intervals) and second < len(other.intervals):
            left_a, right_a = self.intervals[first]
            left_b, right_b = other.intervals[second]
            start, end = max(left_a, left_b), min(right_a, right_b)
            if start < end:
                result.append((start, end))
            if right_a < right_b:
                first += 1
            else:
                second += 1
        return IntervalIndex(result)
'''
PROMPT = (
    "Independently review the complete source below. All evidence needed for this "
    "bounded review is inline. Do not use tools, run commands, read additional files, "
    "edit anything, or delegate. Do not emit progress narration; give only your final "
    "supported review using the format below. The requirements are: accept finite "
    "iterables of half-open integer intervals; reject a reversed interval; ignore empty "
    "intervals; represent their union as sorted disjoint intervals with touching intervals "
    "merged. contains must implement half-open membership; overlap_size must return "
    "the number of covered integers in the given query interval; gaps must return sorted "
    "uncovered half-open pieces clipped to the query interval. union and intersection "
    "must preserve those invariants. Query methods must reject reversed intervals. "
    "Check interactions between nested, touching, disjoint, negative, empty and overlapping "
    "intervals, including two-pointer intersection progression and bounds clipping. "
    "Do not demand behavior for noninteger inputs or mutable shared internals; these "
    "are outside the stated contract. This is an independent benign fixture, not a "
    "benchmark solution.\n\nSource:\n" + SOURCE + "\n\n" + review_instructions()
)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def verify_transport(provider, row, output):
    records = [json.loads(line) for line in
               (provider.artifacts / "transport.jsonl").read_text().splitlines()]
    starts = [record for record in records
              if record["direction"] == "send" and record["event"].get("method") == "turn/start"]
    assert len(starts) == 1, "unexpected additional turn, retry, or recovery"
    start = starts[0]
    request = start["event"]["params"]
    assert request["threadId"] == row["thread_id"]
    assert request["model"] == MODEL and request["effort"] == EFFORT
    assert request["approvalPolicy"] == "never"
    assert request["sandboxPolicy"] == provider.sandbox.policy(False)
    assert request["input"] == [{"type": "text", "text": PROMPT}]
    assert "outputSchema" not in request, "review was incorrectly treated as a host operation"
    prompt_file = Path(row["prompt_file"])
    assert prompt_file.read_text() == PROMPT, "retained prompt differs from wire request"
    owned = []
    for record in records:
        event = record["event"]
        params = event.get("params", {})
        turn = params.get("turnId") or params.get("turn", {}).get("id")
        if params.get("threadId") == row["thread_id"] and turn == row["turn_id"]:
            owned.append(record)
    item_types = {record["event"]["params"]["item"]["type"] for record in owned
                  if record["event"].get("method") in ("item/started", "item/completed")}
    assert item_types <= {"userMessage", "agentMessage", "reasoning"}, "unexpected native tool activity"
    assert "reasoning" in item_types, "fixture did not exercise in-flight reasoning"
    assert not any(record["event"].get("method") == "thread/compact/start" for record in records)
    assert not any(record["event"].get("method") == "error" for record in owned), "provider error is not settlement success"
    prices = [record for record in owned
              if record["event"].get("method") == "thread/tokenUsage/updated"
              and sum(record["event"]["params"]["tokenUsage"]["total"].get(key, 0)
                      for key in ("inputTokens", "outputTokens")) > 0]
    assert prices, "no owned numeric transport receipt"
    first_price_seconds = prices[0]["time"] - start["time"]
    assert first_price_seconds > REVIEW_SECONDS, "first response finished before the intended timeout"
    interrupts = [record for record in owned if record["direction"] == "send"
                  and record["event"].get("method") == "turn/interrupt"]
    assert len(interrupts) <= 1, "cancellation was replayed"
    assert all(record["time"] >= prices[0]["time"] for record in interrupts), "cancelled before a fresh receipt"
    completed = [record for record in owned if record["event"].get("method") == "turn/completed"]
    assert len(completed) == 1 and completed[0]["event"]["params"]["turn"].get("error") is None
    assert completed[0]["event"]["params"]["turn"]["status"] in ("completed", "interrupted")
    result = {"prompt_sha256": sha256(PROMPT.encode()), "prompt_file": str(prompt_file),
              "turn_start_requests": 1, "interrupt_requests": len(interrupts),
              "first_numeric_receipt_after_request_seconds": first_price_seconds,
              "turn_completed_after_request_seconds": completed[0]["time"] - start["time"],
              "native_item_types": sorted(item_types), "native_tool_executions": 0,
              "retries": 0, "compactions": 0, "wire_prompt_exact": True}
    save_json(output / "transport-verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-source", type=Path,
                        help="Optional frozen JSON manifest containing source_sha256")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    source = source_hashes()
    script_hash = sha256(Path(__file__).read_bytes())
    if args.expected_source:
        expected = json.loads(args.expected_source.read_text())
        assert source == expected["source_sha256"], "runner differs from supplied frozen source manifest"
    policy = loop_policy({"max_feature_raw": MAX_RAW, "max_review_raw": 150000,
                          "max_review_seconds": REVIEW_SECONDS,
                          "max_review_settle_seconds": SETTLE_SECONDS})
    assert POLICY_VERSION == "global-budget-defaults-v5", "fixture requires the versioned settlement policy"
    admission = {"purpose": "one expired review settles its first in-flight response with exact usage",
                 "model": MODEL, "effort": EFFORT, "seconds": SECONDS,
                 "max_raw": MAX_RAW, "max_turns": MAX_TURNS,
                 "policy": policy, "loop_policy_version": POLICY_VERSION,
                 "effective_settlement_constraint": "600s maximum, preempted by the 180s global deadline and token caps",
                 "auth": "existing ChatGPT subscription; no API fallback",
                 "benchmark_run": False, "solution_grade": "not_evaluated",
                 "prior_conversation_or_blocked_prompt_reused": False,
                 "provider_failure_policy": "stop; do not retry or alter a refused prompt",
                 "source_sha256": source, "script_sha256": script_hash,
                 "receipt_auditor_sha256": sha256(Path(__file__).with_name("real_compaction.py").read_bytes())}
    save_json(output / "admission.json", admission)
    provider, thread, initial = None, None, None
    repo = output / "fixture"
    result = {"status": "failed", "scope": "isolated review timeout accounting verification",
              "benchmark_run": False, "solution_grade": "not_evaluated", "review_approved": None}
    try:
        repo.mkdir()
        (repo / "intervals.py").write_text(SOURCE)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Review settlement verification")
        git(repo, "config", "user.email", "review-settlement@example.invalid")
        git(repo, "config", "commit.gpgSign", "false")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "Add isolated interval review fixture")
        initial = snapshot(repo)
        provider = Codex(repo, output / "provider", MODEL, EFFORT,
                         started + SECONDS, MAX_RAW, MAX_TURNS)
        thread = provider.start_thread()
        progress = FeatureProgress({"id": "review-settlement-verification"}, policy, 0)
        provider.work_limits = progress.limits(0, reviewing=True)
        save_json(output / "work-limits.json", provider.work_limits)
        try:
            provider.turn(thread, PROMPT, "review-settlement-verification")
        except WorkLimitReached as stopped:
            assert type(stopped) is WorkLimitReached, "review cap must remain a hard stop"
            assert stopped.signal["reason"] == "review_time_limit"
            assert getattr(stopped, "completed_reply", None) is None, "expired hard review returned an eligible verdict"
            result["trigger"] = stopped.signal
        else:
            raise AssertionError("fixture did not exercise an expired review; no follow-up generation is allowed")
        assert len(provider.turns) == 1
        row = provider.turns[0]
        assert row["work_limit"] == result["trigger"]
        assert REVIEW_SECONDS <= row["work_limit"]["observed"] < REVIEW_SECONDS + 5
        settlement = row["work_limit_settlement"]
        assert settlement["trigger"] == result["trigger"]
        assert settlement["settle_seconds"] == SETTLE_SECONDS
        assert settlement["outcome"] in ("priced_boundary", "turn_completed")
        assert row["status"] in ("completed", "interrupted")
        assert row["usage_observed_after_last_message"]
        assert not row.get("recovery_eligible", False)
        assert not row.get("output_guard"), "output rejection was mistaken for review settlement"
        assert not (output / "provider/turn-0001/host-operation.txt").exists()
        result["transport"] = verify_transport(provider, row, output)
        result["settlement"] = settlement
        reply = (output / "provider/turn-0001/reply.txt").read_text()
        if reply.strip():
            try:
                decision = parse_review(reply)
            except ValueError:
                result["retained_reply_has_valid_review_format"] = False
            else:
                result["retained_reply_has_valid_review_format"] = True
                result["retained_verdict_eligible"] = False
                result["retained_verdict_marker"] = reply.splitlines()[0].strip()
                result["retained_findings_count"] = len(decision["blocking_findings"]) + len(decision["advisory_findings"])
        assert snapshot(repo) == initial, "review altered fixture source or Git state"
        assert source_hashes() == source, "runner changed during verification"
        assert sha256(Path(__file__).read_bytes()) == script_hash, "verifier changed during execution"
        result.update(status="passed", review_outcome="stopped_after_time_limit",
                      source_custody_preserved=True, host_actions_executed=0)
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            try:
                provider.close()
                usage = provider.report()
                result["usage"] = usage
                assert usage["measurement_complete"], "final measurement incomplete"
                assert not usage["unpriced_or_incomplete_turns"]
                assert usage["nested"]["observed_raw_tokens"] == 0
                assert 0 < usage["observed_raw_tokens"] < MAX_RAW
                assert provider.parent_threads == {thread}
                native = native_receipts(provider, repo, [thread])
                save_native_receipts(output, native)
                assert not native["compactions"]
                assert usage["observed_raw_tokens"] == native["observed_raw_tokens"]
                assert usage["cached_input_tokens"] == native["cached_input_tokens"]
                assert {receipt["turn_id"] for receipt in native["responses"]} == {provider.turns[0]["turn_id"]}
                assert snapshot(repo) == initial and source_hashes() == source
                assert sha256(Path(__file__).read_bytes()) == script_hash
                result["independent_raw_tokens"] = native["observed_raw_tokens"]
                result["independent_cached_input_tokens"] = native["cached_input_tokens"]
            except (Exception, KeyboardInterrupt) as exc:
                result["status"] = "failed"
                result["finalization_error"] = str(exc) or "operator interruption"
        result["duration_seconds"] = time.monotonic() - started
        save_json(output / "result.json", result)
    print(json.dumps({"status": result["status"], "scope": result["scope"],
                      "review_approved": None, "solution_grade": "not_evaluated",
                      "raw_tokens": result.get("usage", {}).get("observed_raw_tokens"),
                      "error": result.get("error"), "finalization_error": result.get("finalization_error"),
                      "output": str(output)}, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
