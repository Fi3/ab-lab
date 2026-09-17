"""One isolated, sequential implement/review/repair workflow per invocation."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

from .config import author_policy
from .host import Fatal, Rejected, Host, execute_child, git, save_json, snapshot, parse_operations, relative_path
from .provider import Codex, clean_env


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))}


def review_clean(reply):
    markers = [line.strip() for line in reply.splitlines() if line.strip() in ("NO_FINDINGS", "FINDINGS")]
    if len(markers) != 1:
        raise ValueError("review needs exactly one NO_FINDINGS or FINDINGS marker; malformed review is not approval")
    return markers == ["NO_FINDINGS"]


def author_prompt(benchmark, feature, factors, findings=None):
    action = "Implement this feature with focused tests." if findings is None else "Fix only the reviewed feature and its tests to resolve these findings:\n" + findings
    docs = ("Documentation and prose updates are deferred to final integration. Do not modify docs/**, README*, CHANGELOG*, *.md or *.txt during feature implementation/repair."
            if benchmark["defer_documentation"] else "Update documentation required by the assigned feature.")
    return f"You are a direct coding agent in this repository.\n\nRequest {feature['id']}:\n{feature['request']}\n\n{action}\nFollow repository instructions except the explicit procedural overrides below. Do not use Work Leaf or extra worktrees. Avoid unrelated refactors.\n{docs}\n{benchmark['instructions']}\n\n{author_policy(factors)}"


def review_prompt(benchmark, feature, base, evidence):
    docs = "Documentation is deferred to final integration; do not report deferred prose as missing." if benchmark["defer_documentation"] else "Check required documentation too."
    return f"You are an independent review agent. Do not modify files.\nReview only changes since {base} for request {feature['id']}:\n{feature['request']}\nInspect {base}..HEAD. Report only bugs, regressions or missing tests introduced by this feature. Do not report unrelated pre-existing issues.\n{docs}\n{benchmark['instructions']}\n{evidence}\nIf acceptable, include exactly one standalone marker NO_FINDINGS. Otherwise include exactly one standalone marker FINDINGS followed by concise actionable bullets."


def integration_prompts(benchmark, base, checkpoints):
    count = len(benchmark["features"])
    contract = f"Produce exactly {count} final commits rooted at {base}, one per feature. Fold implementation, tests, review repairs, validation fixes and required documentation into the corresponding feature commit. No separate support or documentation-only commits. Preserve all reviewed behavior and follow repository commit-message rules. Do not push or modify other checkouts."
    detail = json.dumps(checkpoints, indent=2)
    plan = f"You are the final integration agent for {count} sequentially reviewed features.\n{contract}\nReviewed feature boundaries:\n{detail}\nInspect history and source, identify required documentation, and propose a plan. Do not edit, commit, rewrite history or run the check suite yet. End with your plan and wait for acceptance.\n{benchmark['instructions']}"
    accept = f"Accept the proposed plan and execute it.\n{contract}\nRun these final checks and all additional repository-required checks; repair genuine failures until they pass within the run budget:\n"+"\n".join(benchmark["checks"])+"\nLeave the checkout clean and summarize final commits and actual verification results."
    return plan, accept


def after_read_fixture(host, fixture, output, deadline):
    """A declared non-agent update after delivered text, once per workflow.

    Only the configured tracked file may change. Both C08 conditions execute
    the same fixture; the old delivered snapshot deliberately remains old.
    """
    before = host.unchanged()
    name = relative_path(host.repo, fixture["path"])
    if name not in before["files"]:
        raise Fatal("after_read fixture needs a tracked source file")
    folder = output / "fixture-after-read"
    folder.mkdir()
    receipt = execute_child(["/bin/sh", "-c", fixture["command"]], host.repo, None,
        folder / "stdout.txt", folder / "stderr.txt", min(30, deadline-time.monotonic()), clean_env())
    save_json(folder / "result.json", receipt)
    after = snapshot(host.repo)
    if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
        raise Fatal("declared after_read fixture failed; source and output retained")
    if any(after[k] != before[k] for k in ("head", "index", "index_flags", "untracked")):
        raise Fatal("fixture must not change Git state or create untracked source")
    changed = {n for n in before["files"] if before["files"][n] != after["files"].get(n)}
    if changed != {name} or after["files"][name][0] != "file" or before["files"][name][1] == after["files"][name][1]:
        raise Fatal("fixture must change text in exactly its declared file")
    after["files"][name][1].decode("utf-8")
    (folder / "before.txt").write_bytes(before["files"][name][1])
    (folder / "after.txt").write_bytes(after["files"][name][1])
    git(host.repo, "add", "--", name)
    git(host.repo, "commit", "-qm", "UPDATE benchmark fixture to exercise an intervening source change")
    host.expected = snapshot(host.repo)
    host.event("declared_fixture_applied", path=name, commit=host.expected["head"])


def run(benchmark, factors, output, seconds, max_raw, max_turns,
        model="gpt-5.5", effort="xhigh", executable="codex", backend=Codex):
    if seconds <= 0 or max_raw <= 0 or max_turns <= 0:
        raise ValueError("positive wall-time, observed-token and turn limits are required")
    fixture = benchmark.get("after_read")
    if fixture and not factors["C17"]:
        raise ValueError("after_read fixture requires mediated host reads (C17=on)")
    fixture_fired = False
    output = Path(output).resolve()
    # Exclusive creation is the admission boundary: no overwrite, auto-resume,
    # replacement or automatic control run.
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic()+seconds
    provider = None
    result = {"schema": "agent-behavior-lab/v1", "status": "failed", "factors": factors,
              "output": str(output), "stages": [], "checkpoints": [], "checks": [], "factor_activations": {}}
    start = time.monotonic()
    code = source_hashes()
    try:
        base = git(benchmark["repo"], "rev-parse", "--verify", benchmark["revision"]+"^{commit}").decode().strip()
        manifest = {"schema": "agent-behavior-lab/v1", "benchmark": benchmark, "base_commit": base,
                    "factors": factors, "limits": {"seconds": seconds, "observed_raw_tokens": max_raw, "turns": max_turns},
                    "model": model, "effort": effort, "source_sha256": code,
                    "workflow": "sequential-implement-review-repair-then-plan-accept-and-one-commit-per-feature",
                    "transport": "codex-app-server-stdio", "created_at_unix": time.time()}
        save_json(output / "manifest.json", manifest)
        checkout = output / "checkout"
        clone = subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", "--", benchmark["repo"], str(checkout)], capture_output=True, timeout=max(1, deadline-time.monotonic()))
        if clone.returncode:
            raise Fatal("clone failed: "+clone.stderr.decode(errors="replace"))
        git(checkout, "checkout", "--quiet", "--detach", base)
        # Only the owned clone's identity is configured; no global changes.
        git(checkout, "config", "user.name", "Agent Behavior Lab")
        git(checkout, "config", "user.email", "agent-behavior-lab@example.invalid")
        git(checkout, "config", "commit.gpgSign", "false")
        provider = backend(checkout, output / "provider", model, effort, deadline, max_raw, max_turns, executable)
        invariant = {k: v for k, v in manifest.items() if k not in ("factors", "created_at_unix")}
        invariant["provider"] = provider.identity
        result["comparison_key"] = fingerprint(invariant)
        save_json(output / "invariants.json", invariant)

        def turn(thread, prompt, label, **options):
            result["stages"].append({"stage": label, "thread_id": thread, "started_at_unix": time.time()})
            with (output / "progress.jsonl").open("a") as out:
                out.write(json.dumps(result["stages"][-1])+"\n")
            return provider.turn(thread, prompt, label, **options)

        for feature in benchmark["features"]:
            name = feature["id"]
            feature_base = git(checkout, "rev-parse", "HEAD").decode().strip()
            author = provider.start_thread(writable=not factors["C17"])
            host = Host(checkout, output / (name+"-host"), name, "author", deadline, factors) if factors["C17"] else None

            def implement(prompt, label):
                nonlocal fixture_fired
                if host:
                    while not host.completed:
                        reply = turn(author, prompt, label, interrupt=factors["C25"], host_request=True)
                        host.unchanged()
                        host.evidence("AUTHOR REPLY", reply)
                        prompt = host.consume(reply)
                        if fixture and not fixture_fired:
                            try:
                                operations = parse_operations(reply)
                            except Rejected:
                                operations = []
                            if len(operations) == 1 and operations[0][0] == "read" and relative_path(checkout, operations[0][1]) == fixture["path"] and fixture["path"] in host.seen:
                                after_read_fixture(host, fixture, output, deadline)
                                fixture_fired = True
                else:
                    reply = turn(author, prompt, label, writable=True)
                    if reply.strip() != "@standalone done":
                        raise Fatal("native author did not supply the stage-completion marker")
                if git(checkout, "status", "--porcelain"):
                    raise Fatal("author left uncommitted source changes")

            implement(author_prompt(benchmark, feature, factors), name+"-implement")
            if (host and not host.accepted_commits) or git(checkout, "rev-parse", "HEAD").decode().strip() == feature_base:
                raise Fatal("initial implementation produced no commit")
            reviewer = provider.start_thread()
            round_number, evidence = 1, ""
            while True:
                before = snapshot(checkout)
                reply = turn(reviewer, review_prompt(benchmark, feature, feature_base, evidence), f"{name}-review-{round_number}")
                if snapshot(checkout) != before:
                    raise Fatal("reviewer changed source, index or history")
                if review_clean(reply):
                    break
                if host:
                    host.completed = False
                    evidence_start = host.evidence_path.stat().st_size
                implement(author_prompt(benchmark, feature, factors, reply), f"{name}-fix-{round_number}")
                if host:
                    with host.evidence_path.open("rb") as stream:
                        stream.seek(evidence_start)
                        evidence = "Author repair and real operation evidence:\n"+stream.read().decode()
                else:
                    evidence = "Author reports completed repairs. Inspect the actual new commits and test results."
                round_number += 1
            checkpoint = {"feature": name, "request": feature["request"], "base": feature_base,
                          "reviewed_head": git(checkout, "rev-parse", "HEAD").decode().strip(), "review_rounds": round_number}
            result["checkpoints"].append(checkpoint)
            if host:
                for key, count in host.activations.items():
                    result["factor_activations"][key] = result["factor_activations"].get(key, 0)+count
            save_json(output / (name+"-result.json"), {**checkpoint, "factor_activations": host.activations if host else {"C17": "native tools"}})

        reviewed = git(checkout, "rev-parse", "HEAD").decode().strip()
        git(checkout, "update-ref", "refs/agent-lab/reviewed", reviewed)
        plan, accept = integration_prompts(benchmark, base, result["checkpoints"])
        integrator = provider.start_thread()
        before = snapshot(checkout)
        turn(integrator, plan, "integration-plan")
        if snapshot(checkout) != before:
            raise Fatal("integration planning modified source/index/history")
        turn(integrator, accept, "integration-accept", writable=True)
        git(checkout, "merge-base", "--is-ancestor", base, "HEAD")
        commits = git(checkout, "rev-list", "--reverse", base+"..HEAD").decode().splitlines()
        if len(commits) != len(benchmark["features"]) or git(checkout, "rev-list", "--merges", base+"..HEAD"):
            raise Fatal("final history must be linear with exactly one commit per feature")
        for index, command in enumerate(benchmark["checks"], 1):
            folder = output / f"check-{index:02d}"
            folder.mkdir()
            receipt = execute_child(["/bin/sh", "-c", command], checkout, None, folder / "stdout.txt", folder / "stderr.txt", min(300, deadline-time.monotonic()), clean_env())
            receipt["command"] = command
            result["checks"].append(receipt)
            save_json(folder / "result.json", receipt)
            if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
                raise Fatal(f"final check {index} failed; no automatic replacement")
        if git(checkout, "status", "--porcelain"):
            raise Fatal("final checkout is not clean")
        if source_hashes() != code:
            raise Fatal("runner source changed during execution")
        result.update(status="passed", final_commits=commits)
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        else:
            result["usage"] = {"observed_raw_tokens": None, "measurement_complete": False,
                               "reason": "provider did not initialize; inspect retained stderr"}
        result["duration_seconds"] = time.monotonic()-start
        result["fixture_executed"] = fixture_fired
        save_json(output / "result.json", result)
    return result


def comparable(*reports):
    for result in reports:
        if result.get("status") != "passed" or not result.get("usage", {}).get("measurement_complete"):
            raise ValueError("percentage requires successful complete workflows with no flagged measurement gaps; partial results remain reportable")
        if not result.get("comparison_key") or result["comparison_key"] != reports[0]["comparison_key"]:
            raise ValueError("non-factor settings differ; these results cannot be used for an isolated percentage")


def compare(reference, changed):
    comparable(reference, changed)
    a, b = (r["usage"]["observed_raw_tokens"] for r in (reference, changed))
    if a <= 0:
        raise ValueError("reference usage must be positive")
    return {"reference_raw_tokens": a, "changed_raw_tokens": b, "observed_saved_raw_tokens": a-b,
            "observed_reduction_percent": 100*(a-b)/a, "denominator": "reference observed raw tokens",
            "changed_factors": [c for c in reference["factors"] if reference["factors"][c] != changed["factors"][c]],
            "limit": "observed sample difference, not causal certainty or additive historical shares"}


def interaction(neither, a_only, b_only, both):
    comparable(neither, a_only, b_only, both)
    base = neither["factors"]
    a = {k for k in base if a_only["factors"][k] != base[k]}
    b = {k for k in base if b_only["factors"][k] != base[k]}
    expected = {**base, **{k: a_only["factors"][k] for k in a}, **{k: b_only["factors"][k] for k in b}}
    if not a or not b or a & b or both["factors"] != expected:
        raise ValueError("need four cells: neither, A only, B only, both; disjoint declared factor changes")
    n, x, y, xy = (r["usage"]["observed_raw_tokens"] for r in (neither, a_only, b_only, both))
    return {"factors_a": sorted(a), "factors_b": sorted(b), "joint_saved_raw_tokens": n-xy,
            "extra_joint_saving_raw_tokens": x+y-n-xy,
            "definition": "extra joint saving = A-only + B-only - neither - both; positive means more saving together than the sum of separate savings",
            "limit": "four observed workflow differences; repetitions are needed for uncertainty"}
