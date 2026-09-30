"""Deterministic progress checks and bounded handoffs for unfinished features."""
from collections import deque
import hashlib
import json
from pathlib import Path
import time

from .host import Fatal, git, snapshot, state_summary


DEFAULT_LOOP_POLICY = {
    "enabled": True,
    "max_feature_raw": None,
    "max_repair_attempts": None,
    "repeat_limit": 3,
    "max_review_raw": None,
    "max_review_seconds": None,
    "max_review_settle_seconds": 600,
    "final_review": True,
}
POLICY_VERSION = "global-budget-defaults-v5"


def loop_policy(value=None):
    if value is not None and (not isinstance(value, dict) or set(value) - set(DEFAULT_LOOP_POLICY)):
        raise ValueError("loop policy must be an object with known policy fields")
    policy = {**DEFAULT_LOOP_POLICY, **(value or {})}
    for key in ("enabled", "final_review"):
        if type(policy[key]) is not bool:
            raise ValueError(f"loop policy {key} must be boolean")
    for key in ("max_feature_raw", "max_repair_attempts", "repeat_limit", "max_review_raw", "max_review_seconds",
                "max_review_settle_seconds"):
        if key in ("max_feature_raw", "max_review_raw", "max_review_seconds", "max_repair_attempts") and policy[key] is None:
            continue
        if type(policy[key]) is not int or policy[key] <= 0:
            raise ValueError(f"loop policy {key} must be a positive integer")
    if policy["repeat_limit"] < 2:
        raise ValueError("loop policy repeat_limit must be at least two")
    if (policy["final_review"] and policy["max_review_raw"] is not None
            and policy["max_feature_raw"] is not None
            and policy["max_review_raw"] >= policy["max_feature_raw"]):
        raise ValueError("final review reserve must be smaller than the feature budget")
    return policy


class WorkLimitReached(Fatal):
    def __init__(self, signal, *, settle_seconds=0):
        self.signal = signal
        self.settle_seconds = settle_seconds
        super().__init__(signal["reason"])


class NeedsAttention(Fatal):
    def __init__(self, flag):
        self.flag = flag
        super().__init__(f"{flag['feature']} stopped: {flag['reason']}; human or stronger-model review required")


def work_limit_error(limits, raw, now=None):
    now = time.monotonic() if now is None else now
    for limit in limits:
        observed = (raw if limit["metric"] == "observed_raw_tokens" else now) - limit["start"]
        if observed >= limit["limit"]:
            return WorkLimitReached({"reason": limit["reason"], "kind": "budget_exhausted",
                          "metric": limit["metric"], "limit": limit["limit"], "observed": observed},
                         settle_seconds=limit.get("settle_seconds", 0))
    return None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class FeatureProgress:
    def __init__(self, feature, policy, raw_start):
        self.feature, self.policy, self.raw_start = feature, policy, raw_start
        self.repairs = 0
        self.reviews = []
        self.operations = deque(maxlen=3 * policy["repeat_limit"])
        self.operation_count = 0
        self.flags = []

    def limits(self, raw, *, reviewing=False):
        if not self.policy["enabled"]:
            return []
        limits = []
        feature_raw = self.policy["max_feature_raw"]
        review_raw = self.policy["max_review_raw"]
        review_seconds = self.policy["max_review_seconds"]
        if feature_raw is not None:
            # Only an explicit review cap provides a definite reserve. Reviews
            # themselves can use the feature's entire remaining allowance.
            reserve = (review_raw or 0) if self.policy["final_review"] and not reviewing else 0
            limits.append({"reason": "feature_token_limit", "metric": "observed_raw_tokens",
                           "start": self.raw_start, "limit": feature_raw - reserve})
        if reviewing:
            if review_raw is not None:
                limits.append({"reason": "review_token_limit", "metric": "observed_raw_tokens",
                               "start": raw, "limit": review_raw})
            if review_seconds is not None:
                limits.append({"reason": "review_time_limit", "metric": "seconds",
                               "start": time.monotonic(), "limit": review_seconds,
                               "settle_seconds": self.policy["max_review_settle_seconds"]})
        return limits

    def observe_review(self, review, tree):
        row = {**review, "tree": tree}
        self.reviews.append(row)
        if not self.policy["enabled"] or review["approved"]:
            return None
        previous = [r for r in self.reviews[:-1] if not r["approved"] and r["tree"] == tree]
        if previous:
            return {"reason": "repeated_rejected_tree", "kind": "loop_detected", "tree": tree,
                    "rounds": [r["round"] for r in previous] + [review["round"]]}
        count = self.policy["repeat_limit"]
        window = self.reviews[-count:]
        if len(window) == count:
            signatures = [{" ".join(f["text"].split()) for f in r["blocking_findings"]} for r in window]
            repeated = set.intersection(*signatures)
            if repeated:
                return {"reason": "repeated_blocking_findings", "kind": "loop_detected",
                        "rounds": [r["round"] for r in window], "findings": sorted(repeated)}
        if self.policy["max_repair_attempts"] is not None and self.repairs >= self.policy["max_repair_attempts"]:
            return {"reason": "repair_limit_reached", "kind": "attempt_limit",
                    "limit": self.policy["max_repair_attempts"], "observed": self.repairs}
        return None

    def observe_operation(self, request, response, repo):
        if not self.policy["enabled"]:
            return None
        self.operation_count += 1
        if request["name"] == "host_read" or response["success"]:
            # Reading and successful polling are not failures; either breaks an
            # unchanged failure sequence even when the source itself is stable.
            self.operations.clear()
            return None
        arguments = request["arguments"]
        if isinstance(arguments, dict):
            arguments = {key: value for key, value in arguments.items() if key != "reason"}
        operation = {"name": request["name"], "arguments": arguments}
        state = state_summary(snapshot(repo))
        state.pop("head")  # Empty commits do not constitute source progress.
        signature = digest({"operation": operation, "response": response, "state": state})
        self.operations.append(signature)
        repeats = self.policy["repeat_limit"]
        recent = list(self.operations)
        for period in range(1, 4):
            size = period * repeats
            if len(recent) >= size and recent[-size:] == recent[-period:] * repeats:
                return {"reason": "repeated_operations", "kind": "loop_detected", "period": period,
                        "repeats": repeats, "operation_numbers": [self.operation_count - size + 1, self.operation_count],
                        "signatures": recent[-period:]}
        return None

    def record_flag(self, signal, output, repo, base, stage, raw, reviews, *, pending_changes=None):
        folder = Path(output) / "attention" / self.feature["id"] / f"event-{len(self.flags)+1:02d}"
        folder.mkdir(parents=True)
        host_artifacts = Path(output) / (self.feature["id"] + "-host")
        flag = {**signal, "feature": self.feature["id"], "stage": stage,
                "attempt_status": "stopped", "resolution": "needs_attention", "review_approved": None,
                "feature_raw_tokens": raw - self.raw_start, "repair_attempts": self.repairs,
                "base": base, "head": git(repo, "rev-parse", "HEAD").decode().strip(),
                "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
                "working_tree_status": git(repo, "status", "--porcelain").decode(),
                "pending_host_changes": bool(pending_changes), "pending_host_artifacts": pending_changes or {},
                "checkout": str(repo),
                "provider_artifacts": str(Path(output) / "provider"),
                "host_artifacts": str(host_artifacts) if host_artifacts.exists() else None,
                "artifact": str(folder / "handoff.json"), "policy": self.policy,
                "final_review": {"status": "not_run"}}
        (folder / "request.txt").write_text(self.feature["request"])
        (folder / "changes.patch").write_bytes(git(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary", base, "--"))
        (folder / "reviews.json").write_text(json.dumps(reviews, indent=2) + "\n")
        self.flags.append(flag)
        self.save_flag(flag)
        return flag

    @staticmethod
    def save_flag(flag):
        path = Path(flag["artifact"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(flag, indent=2) + "\n")
        temporary.replace(path)
        (path.parent / "README.md").write_text(
            f"# Review handoff: {flag['feature']}\n\n"
            f"Reason: `{flag['reason']}`. Resolution: `{flag['resolution']}`.\n\n"
            f"The automated attempt stopped at `{flag['head']}`. "
            "Stopping does not imply that the feature is correct.\n\n"
            f"Feature usage at detection: {flag['feature_raw_tokens']:,} raw tokens. "
            f"Repair attempts: {flag['repair_attempts']}.\n\n"
            f"Inspect `{flag['checkout']}`, including any uncommitted or untracked work. "
            "`changes.patch` contains the tracked changes; it does not contain untracked files. "
            "`request.txt` contains the requirements, `reviews.json` the recorded reviews, "
            "and `handoff.json` the trigger, source state and final-review outcome. "
            "The provider_artifacts and host_artifacts paths in handoff.json retain operation and test evidence.\n"
            + ("\nThe stopped checkpoint is retained in the immutable snapshot and commit recorded in "
               "handoff.json retention. Subsequent checkpoints remain blocked until review approval.\n"
               if flag.get("retention") else "")
        )
