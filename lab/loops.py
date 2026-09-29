"""Deterministic progress checks and bounded handoffs for unfinished features."""
from collections import deque
import hashlib
import json
from pathlib import Path
import time

from .host import Fatal, git, parse_operations, Rejected, snapshot, state_summary


DEFAULT_LOOP_POLICY = {
    "enabled": True,
    "max_feature_raw": 3_000_000,
    "max_repair_attempts": 3,
    "repeat_limit": 3,
    "max_review_raw": 500_000,
    "max_review_seconds": 300,
    "max_review_wrapup_raw": 200_000,
    "max_review_wrapup_seconds": 90,
    "max_review_settle_seconds": 600,
    "final_review": True,
}
POLICY_VERSION = "bounded-feature-review-v3"


def loop_policy(value=None):
    if value is not None and (not isinstance(value, dict) or set(value) - set(DEFAULT_LOOP_POLICY)):
        raise ValueError("loop policy must be an object with known policy fields")
    policy = {**DEFAULT_LOOP_POLICY, **(value or {})}
    for key in ("enabled", "final_review"):
        if type(policy[key]) is not bool:
            raise ValueError(f"loop policy {key} must be boolean")
    for key in ("max_feature_raw", "max_repair_attempts", "repeat_limit", "max_review_raw", "max_review_seconds",
                "max_review_wrapup_raw", "max_review_wrapup_seconds", "max_review_settle_seconds"):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise ValueError(f"loop policy {key} must be a positive integer")
    if policy["repeat_limit"] < 2:
        raise ValueError("loop policy repeat_limit must be at least two")
    if policy["final_review"] and policy["max_review_raw"] >= policy["max_feature_raw"]:
        raise ValueError("final review reserve must be smaller than the feature budget")
    return policy


class WorkLimitReached(Fatal):
    def __init__(self, signal, *, settle_seconds=0):
        self.signal = signal
        self.settle_seconds = settle_seconds
        super().__init__(signal["reason"])


class ReviewConclusionRequested(WorkLimitReached):
    """End exploration, then collect one verdict from the same reviewer."""
    completed_reply = None


class NeedsAttention(Fatal):
    def __init__(self, flag):
        self.flag = flag
        super().__init__(f"{flag['feature']} stopped: {flag['reason']}; human or stronger-model review required")


def work_limit_error(limits, raw, now=None):
    now = time.monotonic() if now is None else now
    for limit in limits:
        observed = (raw if limit["metric"] == "observed_raw_tokens" else now) - limit["start"]
        if observed >= limit["limit"]:
            conclusion = limit.get("action") == "conclude_review"
            error = ReviewConclusionRequested if conclusion else WorkLimitReached
            return error({"reason": limit["reason"], "kind": "review_wrapup" if conclusion else "budget_exhausted",
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

    def limits(self, raw, *, reviewing=False, final=False, concluding=False):
        if not self.policy["enabled"]:
            return []
        # An ongoing review can use the feature's remaining allowance. Reserve
        # only author work, so a verdict is not replaced by another full review.
        reserve = self.policy["max_review_raw"] if self.policy["final_review"] and not reviewing else 0
        limits = [{"reason": "feature_token_limit", "metric": "observed_raw_tokens",
                   "start": self.raw_start, "limit": self.policy["max_feature_raw"] - reserve}]
        if reviewing:
            soft = not final and not concluding
            prefix = "max_review_wrapup" if concluding else "max_review"
            reason = "review_wrapup" if concluding else "review"
            suffix = "threshold" if soft else "limit"
            action = {"action": "conclude_review"} if soft else {}
            limits += [
                {"reason": f"{reason}_token_{suffix}", "metric": "observed_raw_tokens",
                 "start": raw, "limit": self.policy[prefix + "_raw"], **action},
                {"reason": f"{reason}_time_{suffix}", "metric": "seconds",
                 "start": time.monotonic(), "limit": self.policy[prefix + "_seconds"],
                 "settle_seconds": self.policy["max_review_settle_seconds"], **action},
            ]
        return limits

    def budget_note(self, raw):
        if not self.policy["enabled"]:
            return ""
        remaining = max(0, self.policy["max_feature_raw"] - (raw - self.raw_start))
        reserve = self.policy["max_review_raw"] if self.policy["final_review"] else 0
        return (f"\n\nRunner budget for {self.feature['id']}: {remaining} observed raw tokens remain, "
                f"including reviews and compaction ({reserve} reserved for a final review); "
                f"ordinary reviews should conclude by {self.policy['max_review_raw']} raw tokens or "
                f"{self.policy['max_review_seconds']} seconds. At that threshold the runner requests "
                f"one conclusion, limited to {self.policy['max_review_wrapup_raw']} additional raw tokens "
                f"and a {self.policy['max_review_wrapup_seconds']}-second stop threshold. "
                f"After a review time threshold, the in-flight response has at most "
                f"{self.policy['max_review_settle_seconds']} seconds to reach an accounted boundary; "
                "this does not authorize another response or approve an over-time conclusion. "
                "Feature/review token limits and global limits still apply immediately. "
                f"{self.repairs}/{self.policy['max_repair_attempts']} "
                "repair attempts used. Token limits count cached input once. "
                "A runner stop is not an approval or a claim that requirements are complete.")

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
        if self.repairs >= self.policy["max_repair_attempts"]:
            return {"reason": "repair_limit_reached", "kind": "attempt_limit",
                    "limit": self.policy["max_repair_attempts"], "observed": self.repairs}
        return None

    def observe_operation(self, request, response, repo):
        if not self.policy["enabled"]:
            return None
        try:
            operation = parse_operations(request)
            # The author's explanation is not a change to the requested edit.
            operation = [(item[0], item[2]) if item[0] == "edit" else item for item in operation]
        except Rejected:
            operation = request.strip()
        state = state_summary(snapshot(repo))
        state.pop("head")  # Empty commits do not constitute source progress.
        signature = digest({"operation": operation, "response": response, "state": state})
        self.operation_count += 1
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
            + ("\nThe benchmark continued. Use the immutable attempt snapshot and commit in "
               "handoff.json continuation, since the live checkout may now contain later checkpoints.\n"
               if flag.get("continuation") else "")
        )
