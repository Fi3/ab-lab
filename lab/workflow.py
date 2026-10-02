"""One isolated, sequential implement/review/repair workflow per invocation."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from contextlib import ExitStack

from .config import WORKFLOW_VERSION, author_policy
from .exclude_integration import comparison_view
from .host import Fatal, Host, execute_child, git, git_execution, save_json, snapshot, relative_path
from .host_tools import HOST_TOOLS, HostTools
from .provider import Codex, Pi, clean_env
from .review import (DEFAULT_PRIORITIES, DEFAULT_MAX_REVIEW_LOOPS, format_findings,
                     normalize_priorities, normalize_review_loops, REVIEW_TOOLS, ReviewTools, review_instructions)
from .loops import FeatureProgress, NeedsAttention, POLICY_VERSION, WorkLimitReached, loop_policy, work_limit_error
from . import scb, evaluation


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    root = Path(__file__).resolve().parents[1]
    sources = {p.name: p for p in (root / "lab").iterdir() if p.suffix in (".py", ".mjs")}
    sources.update({str(p.relative_to(root)): p for p in (root / "benchmarks").rglob("*")
                    if p.is_file() and p.suffix in (".py", ".json", ".txt")})
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(sources.items())}


def author_prompt(benchmark, feature, factors, findings=None):
    parts = [feature["request"]]
    if findings is not None:
        parts.append("Resolve these review findings:\n" + findings)
    policy = author_policy(factors)
    if policy:
        parts.append(policy)
    return "\n\n".join(parts)


def review_prompt(benchmark, feature, base, evidence, no_changes=False, *, review_priorities=DEFAULT_PRIORITIES, review_id=None):
    instructions = review_instructions(review_priorities)
    if no_changes:
        scope = f"There are no changes since {base}. Verify whether the requested behavior is already satisfied; an empty diff is not approval."
    else:
        scope = f"Inspect {base}..HEAD for defects introduced by this feature. Exclude unrelated pre-existing issues."
    return f"Independently review the following request. The submission is read-only; use writable temporary scratch space or a scratch copy for tests that create files.\nReview target: {review_id}\n{scope}\n\n{feature['request']}\n\n{evidence}\n{instructions}"


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


def capture_native_work(checkout, stage, output):
    """Record the native agent's actual files without requiring it to commit."""
    if git(checkout, "ls-files", "--unmerged"):
        raise Fatal("native author left unresolved merge entries; source retained")
    previous = git(checkout, "rev-parse", "HEAD").decode().strip()
    dirty = git(checkout, "status", "--porcelain").decode()
    if dirty:
        git(checkout, "add", "--all")
        if git(checkout, "diff", "--cached", "--name-only"):
            git(checkout, "commit", "-qm", "Record native work: " + stage)
    save_json(output / (stage + "-source.json"), {"stage": stage, "previous_head": previous,
        "head": git(checkout, "rev-parse", "HEAD").decode().strip(), "status_before_capture": dirty})


def run(benchmark, factors, output, seconds, max_raw, max_turns,
        model="gpt-5.5", effort="xhigh", executable="codex", backend=Codex, *,
        harness=None, scb_check=None, scb_seconds=300, child_codex="codex",
        review_priorities=DEFAULT_PRIORITIES, max_review_loops=DEFAULT_MAX_REVIEW_LOOPS,
        loop_options=None, preset=None, _base_commit=None):
    if seconds <= 0 or max_raw <= 0 or max_turns <= 0:
        raise ValueError("positive wall-time, observed-token and turn limits are required")
    if not math.isfinite(scb_seconds) or scb_seconds <= 0:
        raise ValueError("scb-check needs a positive finite time limit")
    review_priorities = normalize_priorities(review_priorities)
    max_review_loops = normalize_review_loops(max_review_loops)
    progress_policy = loop_policy(loop_options)
    if harness == "pi":
        if backend is Codex:
            backend = Pi
        if executable == "codex":
            executable = "pi"
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
    git_context = ExitStack()
    result = {"schema": "agent-behavior-lab/v1", "status": "failed", "factors": factors,
              "output": str(output), "benchmark": benchmark["name"], "preset": preset,
              "max_review_loops": max_review_loops,
              "review_priorities": list(review_priorities), "reviews": [],
              "loop_policy": progress_policy, "loop_policy_version": POLICY_VERSION, "loop_flags": [], "workflow_version": WORKFLOW_VERSION,
              "feature_count": len(benchmark["features"]), "check_count": len(benchmark["checks"]),
              "stages": [], "checkpoints": [], "checks": [], "factor_activations": {}}
    if scb_check is not None:
        result["scb_check"] = scb.pending()
    evaluator = evaluation.adapter_type(benchmark)(benchmark, output, result)
    if evaluator.config_key:
        result["evaluation"] = {"evaluator": evaluator.config_key, "status": "not_run", "passed": None}
        result["execution_status"] = "incomplete"
    start = time.monotonic()
    failure_origin = "runner"
    active_stage = "setup"
    code = source_hashes()
    try:
        base = git(benchmark["repo"], "rev-parse", "--verify", (_base_commit or benchmark["revision"])+"^{commit}").decode().strip()
        default_transport = "pi-rpc-stdio" if harness == "pi" else "codex-app-server-stdio"
        transport = backend.transport if isinstance(getattr(backend, "transport", None), str) else default_transport
        manifest = {"schema": "agent-behavior-lab/v1", "benchmark": benchmark, "base_commit": base,
                    "factors": factors, "preset": preset, "limits": {"seconds": seconds, "observed_raw_tokens": max_raw, "turns": max_turns},
                    "model": model, "effort": effort, "source_sha256": code,
                    "workflow": "sequential-implement-optional-review-repair-and-evaluate",
                    "transport": transport, "created_at_unix": time.time()}
        manifest["checkout_policy"] = "pinned-history-no-remotes-v1"
        manifest["workflow_version"] = WORKFLOW_VERSION
        manifest["review_priorities"] = list(review_priorities)
        manifest["max_review_loops"] = max_review_loops
        manifest["loop_policy"] = progress_policy
        manifest["loop_policy_version"] = POLICY_VERSION
        if scb_check is not None:
            manifest["scb_check"] = {"executable": str(scb_check), "seconds_per_check": scb_seconds}
        evaluator.start(base, manifest, deadline)
        save_json(output / "manifest.json", manifest)
        checkout = output / "checkout"
        # Fetch only the pinned commit's reachable history into an empty
        # object database. A full clone also exposes later solutions, even
        # after removing their refs. Do not retain an origin to fetch them.
        checkout.mkdir()
        object_format = git(benchmark["repo"], "rev-parse", "--show-object-format").decode().strip()
        git(checkout, "init", "--quiet", "--object-format="+object_format)
        fetched = subprocess.run(["git", "-C", str(checkout), "fetch", "--quiet", "--no-tags",
            "--no-write-fetch-head", "--no-recurse-submodules", "--", benchmark["repo"], base],
            capture_output=True, env=clean_env(), timeout=max(1, deadline-time.monotonic()))
        if fetched.returncode:
            raise Fatal("pinned checkout fetch failed: "+fetched.stderr.decode(errors="replace"))
        git(checkout, "checkout", "--quiet", "--detach", base)
        # Only the owned clone's identity is configured; no global changes.
        git(checkout, "config", "user.name", "Agent Behavior Lab")
        git(checkout, "config", "user.email", "agent-behavior-lab@example.invalid")
        git(checkout, "config", "commit.gpgSign", "false")
        quality = result.get("scb_check")
        if quality is not None:
            quality["tool"] = scb.prepare(scb_check, output, deadline, scb_seconds)

        def score(phase):
            if quality is None:
                return
            observation = evaluator.baseline_measurement(base) if phase == "before_changes" else None
            if observation is not None:
                (output / "scb-check" / phase).mkdir()
                save_json(output / "scb-check" / phase / "result.json", observation)
            else:
                observation = scb.measure(checkout, output, phase, quality["tool"], deadline)
            quality["measurements"][phase] = observation
            if observation["status"] not in ("completed", "not_applicable"):
                raise Fatal(f"scb-check {phase}: {observation['error']}")
            if all(m["status"] in ("completed", "not_applicable") for m in quality["measurements"].values()):
                quality["status"] = "completed"

        score("before_changes")
        failure_origin = "provider"
        provider = backend(checkout, output / "provider", model, effort, deadline, max_raw, max_turns, executable,
                           require_git_write=True, allow_delegation=not factors["C17"], **({"codex_executable": child_codex} if backend is Pi else {}))
        git_context.enter_context(git_execution(checkout, getattr(provider, "git_argv", lambda argv: argv),
                                               getattr(provider, "command_env", clean_env()), deadline))
        failure_origin = "runner"
        if manifest["model"] is None and provider.identity.get("model"):
            manifest["model"] = provider.identity["model"]
            with (output / "manifest.json").open("w", encoding="utf-8") as out:
                json.dump(manifest, out, ensure_ascii=False, indent=2)
                out.write("\n")
        invariant = {k: v for k, v in manifest.items() if k not in ("factors", "created_at_unix")}
        invariant["provider"] = provider.identity
        if quality is not None:
            invariant["scb_check_tool"] = quality["tool"]
        result["comparison_key"] = fingerprint(invariant)
        save_json(output / "invariants.json", invariant)

        def observed_raw():
            return provider.observed_raw() if hasattr(provider, "observed_raw") else provider.report()["observed_raw_tokens"]

        def start_agent(stage, **options):
            nonlocal failure_origin, active_stage
            failure_origin, active_stage = "provider", stage
            thread = provider.start_thread(**options)
            failure_origin = "runner"
            return thread

        def turn(thread, prompt, label, **options):
            nonlocal failure_origin, active_stage
            active_stage = label
            # Providers also enforce these limits inside long native turns.
            error = work_limit_error(getattr(provider, "work_limits", ()), observed_raw())
            if error:
                raise error
            result["stages"].append({"stage": label, "thread_id": thread, "started_at_unix": time.time()})
            with (output / "progress.jsonl").open("a") as out:
                out.write(json.dumps(result["stages"][-1])+"\n")
            failure_origin = "provider"
            reply = provider.turn(thread, prompt, label, **options)
            failure_origin = "measurement"
            if not provider.report().get("measurement_complete"):
                raise Fatal("incomplete token measurement; stop before further host work or agent generation")
            error = work_limit_error(getattr(provider, "work_limits", ()), observed_raw())
            if error:
                raise error
            failure_origin = "runner"
            return reply

        for feature_index, feature in enumerate(benchmark["features"]):
            name = feature["id"]
            feature_base = git(checkout, "rev-parse", "HEAD").decode().strip()
            progress = FeatureProgress(feature, progress_policy, observed_raw())
            host = Host(checkout, output / (name+"-host"), name, "author", deadline, factors,
                        command_env=getattr(provider, "command_env", None),
                        command_argv=getattr(provider, "command_argv", None)) if factors["C17"] else None
            host_tools = HostTools(host) if host else None

            def host_call(tool, arguments, call_id):
                nonlocal fixture_fired, failure_origin
                failure_origin = "runner"
                error = work_limit_error(getattr(provider, "work_limits", ()), observed_raw())
                if error:
                    raise error
                response = host_tools.execute(tool, arguments, call_id)
                signal = progress.observe_operation({"name": tool, "arguments": arguments}, response, checkout)
                if signal:
                    stopped = WorkLimitReached(signal)
                    stopped.completed_tool_result = response
                    raise stopped
                if (fixture and not fixture_fired and tool == "host_read" and response["success"]
                        and relative_path(checkout, arguments["path"]) == fixture["path"]):
                    after_read_fixture(host, fixture, output, deadline)
                    fixture_fired = True
                failure_origin = "provider"
                return response

            author = start_agent(name + "-implement", writable=not factors["C17"],
                **({"tools": HOST_TOOLS, "tool_handler": host_call} if host else {}))

            def record_stop(signal, label):
                flag = progress.record_flag(signal, output, checkout, feature_base, label, observed_raw(),
                                            progress.reviews, pending_changes=host_tools.unfinished_calls() if host_tools else None)
                result["loop_flags"].append(flag)
                if host:
                    host.event("work_stopped", reason=signal["reason"], artifact=flag["artifact"])
                return flag

            def escalate(flag):
                flag["resolution"] = "needs_attention"
                progress.save_flag(flag)
                if not provider.report().get("measurement_complete"):
                    raise Fatal("work stopped with incomplete token measurement; inspect " + flag["artifact"])
                raise NeedsAttention(flag)

            def implement(prompt, label):
                provider.work_limits = progress.limits(observed_raw())
                try:
                    reply = turn(author, prompt, label, writable=not factors["C17"])
                    if host:
                        host.unchanged()
                        host.evidence("AUTHOR REPLY", reply)
                        if host_tools.unfinished_calls():
                            raise Fatal("author completed with an unfinished host call; inspect retained receipts")
                    else:
                        capture_native_work(checkout, label, output)
                except WorkLimitReached as exc:
                    return record_stop(exc.signal, label)
                return None

            stopped_flag = None
            round_number = 0
            approved = False
            try:
                author_stop = implement(author_prompt(benchmark, feature, factors), name+"-implement")
                reviewer = None
                review_tools = ReviewTools(output / (name + "-reviews"), review_priorities,
                    repo=checkout, deadline=deadline,
                    command_env=getattr(provider, "command_env", None),
                    command_argv=getattr(provider, "review_command_argv", None))
                evidence = ""

                while True:
                    if round_number >= max_review_loops:
                        if author_stop:
                            author_stop["final_review"] = {"status": "skipped", "reason": "max_review_loops"}
                            escalate(author_stop)
                        break
                    if author_stop:
                        skipped = ("disabled" if not progress_policy["final_review"] else
                                   "dirty_working_tree" if author_stop["working_tree_status"] else
                                   "pending_host_changes" if author_stop["pending_host_changes"] else
                                   "incomplete_usage" if not provider.report().get("measurement_complete") else None)
                        if skipped:
                            author_stop["final_review"] = {"status": "skipped", "reason": skipped}
                            escalate(author_stop)
                        rejected = next((r for r in reversed(progress.reviews)
                                         if r["approved"] is False and r.get("tree") == author_stop["tree"]), None)
                        if rejected:
                            author_stop["review_approved"] = False
                            author_stop["final_review"] = {
                                "status": "already_reviewed", "label": f"{name}-review-{rejected['round']}",
                                **{key: rejected[key] for key in ("approved", "blocking_findings", "advisory_findings")}}
                            escalate(author_stop)
                        evidence += ("\nThe runner stopped the author after " + author_stop["reason"] + ". "
                                     "This is the single final review of the current code. Apply the unchanged "
                                     "requirements and priorities; stopping is not evidence of correctness. "
                                     "No further automatic repairs will follow a rejection.")
                    round_number += 1
                    provider.work_limits = progress.limits(observed_raw(), reviewing=True)
                    if reviewer is None:
                        reviewer = start_agent(f"{name}-review-{round_number}", writable=False,
                                               tools=REVIEW_TOOLS, tool_handler=review_tools.execute)
                    before = snapshot(checkout)
                    no_changes = git(checkout, "rev-parse", "HEAD").decode().strip() == feature_base
                    review_label = f"{name}-review-{round_number}"
                    review_id = review_tools.begin(review_label, before["head"])
                    try:
                        reply = turn(reviewer, review_prompt(benchmark, feature, feature_base, evidence, no_changes,
                                     review_priorities=review_priorities, review_id=review_id), review_label, writable=False)
                        if snapshot(checkout) != before:
                            failure_origin = "agent"
                            raise Fatal("reviewer changed source, index or history")
                        decision = review_tools.decision or {
                            "approved": None, "blocking_findings": [], "advisory_findings": [],
                            "incomplete_reason": "Reviewer finished without an accepted submit_review verdict"}
                    except WorkLimitReached as exc:
                        if snapshot(checkout) != before:
                            failure_origin = "agent"
                            raise Fatal("reviewer changed source, index or history")
                        flag = author_stop or record_stop(exc.signal, review_label)
                        flag["final_review" if author_stop else "review"] = {"status": "stopped", "label": review_label, **exc.signal}
                        escalate(flag)
                    except (Exception, KeyboardInterrupt) as exc:
                        if author_stop:
                            author_stop["final_review"] = {"status": "failed", "error": str(exc) or "operator interruption"}
                            progress.save_flag(author_stop)
                        raise
                    review = {"feature": name, "round": round_number, "head": before["head"], **decision}
                    result["reviews"].append(review)
                    if decision["approved"] is None:
                        progress.reviews.append(review)
                        flag = author_stop or record_stop({"reason": "review_incomplete", "kind": "incomplete_review"}, review_label)
                        flag["final_review" if author_stop else "review"] = {"status": "incomplete", "label": review_label, **decision}
                        (Path(flag["artifact"]).parent / "reviews.json").write_text(json.dumps(progress.reviews, indent=2) + "\n")
                        escalate(flag)
                    signal = progress.observe_review(review, git(checkout, "rev-parse", "HEAD^{tree}").decode().strip())
                    if author_stop:
                        author_stop["final_review"] = {"status": "completed", "label": review_label, **decision}
                        author_stop["review_approved"] = decision["approved"]
                        author_stop["feature_raw_tokens_after_review"] = observed_raw() - progress.raw_start
                        author_stop["resolution"] = "review_approved" if decision["approved"] else "needs_attention"
                        (Path(author_stop["artifact"]).parent / "reviews.json").write_text(json.dumps(progress.reviews, indent=2) + "\n")
                        progress.save_flag(author_stop)
                        if not decision["approved"]:
                            escalate(author_stop)
                    if decision["approved"]:
                        approved = True
                        break
                    if signal is None:
                        raw = observed_raw()
                        exhausted = work_limit_error(progress.limits(raw), raw)
                        if exhausted:
                            signal = exhausted.signal
                    if signal:
                        flag = record_stop(signal, review_label)
                        flag["review_approved"] = False
                        flag["final_review"] = {"status": "already_reviewed", "label": review_label, **decision}
                        escalate(flag)
                    if host:
                        evidence_start = host.evidence_path.stat().st_size
                    progress.repairs += 1
                    author_stop = implement(author_prompt(benchmark, feature, factors, format_findings(decision["blocking_findings"])),
                                            f"{name}-fix-{round_number}")
                    if host:
                        with host.evidence_path.open("rb") as stream:
                            stream.seek(evidence_start)
                            evidence = "Author repair and real operation evidence:\n"+stream.read().decode()
                    else:
                        evidence = "Author reports completed repairs. Inspect the actual new commits and test results."
            except NeedsAttention as exc:
                if not evaluator.retain_stopped_attempts:
                    raise
                # Safety stops still end the workflow; reaching the configured
                # review allowance after a completed repair does not.
                stopped_flag = exc.flag
                retention = evaluation.retain_attempt(checkout, name)
                stopped_flag["retention"] = retention
                progress.save_flag(stopped_flag)

            provider.work_limits = []
            head = git(checkout, "rev-parse", "HEAD").decode().strip()
            no_changes = head == feature_base
            checkpoint = {"feature": name, "request": feature["request"], "base": feature_base,
                          "head": head, "reviewed_head": head if approved else None, "review_rounds": round_number,
                          "repair_attempts": progress.repairs,
                          "status": "approved" if approved else "review_skipped" if max_review_loops == 0 else "review_limit_reached",
                          "review_approved": True if approved else None,
                          "already_satisfied": no_changes and approved, "observed_raw_tokens": observed_raw() - progress.raw_start,
                          "loop_flags": [f["artifact"] for f in progress.flags]}
            if stopped_flag:
                checkpoint.update(status="needs_attention", review_approved=stopped_flag["review_approved"],
                                  reviewed_head=None, already_satisfied=False, stop_reason=stopped_flag["reason"],
                                  incomplete_reason=progress.reviews[-1].get("incomplete_reason") if progress.reviews else None,
                                  blocking_findings=progress.reviews[-1]["blocking_findings"] if progress.reviews else [])
            result["checkpoints"].append(checkpoint)
            if host:
                for key, count in host.activations.items():
                    result["factor_activations"][key] = result["factor_activations"].get(key, 0)+count
            save_json(output / (name+"-result.json"), {**checkpoint, "factor_activations": host.activations if host else {"C17": "native tools"}})
            captured = evaluator.checkpoint(checkout, checkpoint, quality["tool"] if quality else None, deadline)
            if stopped_flag and captured:
                stopped_flag["retention"].update(captured)
                progress.save_flag(stopped_flag)
            if stopped_flag:
                raise NeedsAttention(stopped_flag)

        score("after_implementation")
        commits = git(checkout, "rev-list", "--reverse", base+"..HEAD").decode().splitlines()
        final_source = snapshot(checkout)
        if not git(checkout, "status", "--porcelain"):
            result["final_submission"] = {"commit": final_source["head"],
                "tree": git(checkout, "rev-parse", "HEAD^{tree}").decode().strip()}
            evaluator.final(checkout)
        for index, command in enumerate(benchmark["checks"], 1):
            folder = output / f"check-{index:02d}"
            folder.mkdir()
            argv = getattr(provider, "command_argv", lambda argv: argv)(["/bin/sh", "-c", command])
            receipt = execute_child(argv, checkout, None, folder / "stdout.txt", folder / "stderr.txt", min(300, deadline-time.monotonic()), getattr(provider, "command_env", clean_env()))
            receipt["command"] = command
            result["checks"].append(receipt)
            save_json(folder / "result.json", receipt)
            if hasattr(provider, "settle_children"):
                provider.settle_children()
            if receipt["exit_code"] or receipt["timed_out"] or receipt["cancelled_signal"]:
                failure_origin = "validation"
                raise Fatal(f"final check {index} failed; no automatic replacement")
        if snapshot(checkout) != final_source:
            raise Fatal("final validation changed submitted source, index or history")
        if git(checkout, "status", "--porcelain"):
            raise Fatal("final checkout is not clean")
        if source_hashes() != code:
            raise Fatal("runner source changed during execution")
        if not provider.report().get("measurement_complete"):
            raise Fatal("incomplete whole-workflow token measurement, including nested verification")
        result.update(status="passed", final_commits=commits)
        if evaluator.config_key:
            result["execution_status"] = "completed"
    except NeedsAttention as exc:
        result.update(status="needs_attention", error=str(exc), attention=exc.flag,
                      blocked_features=[f["id"] for f in benchmark["features"][feature_index+1:]])
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
        result["failure"] = {"origin": "operator" if isinstance(exc, KeyboardInterrupt) else failure_origin,
                             "stage": active_stage, "type": type(exc).__name__, "message": result["error"]}
    finally:
        if provider:
            try:
                provider.close()
                result["usage"] = provider.report()
            except (Exception, KeyboardInterrupt) as exc:
                result["status"] = "failed"
                result["shutdown_error"] = str(exc) or "operator interruption"
                result["usage"] = {"measurement_complete": False, "observed_raw_tokens": None,
                                   "reason": "provider shutdown/accounting failed"}
                result.setdefault("failure", {"origin": "provider", "stage": "shutdown",
                                               "type": type(exc).__name__, "message": result["shutdown_error"]})
        else:
            result["usage"] = {"observed_raw_tokens": None, "measurement_complete": False,
                               "reason": "provider did not initialize; inspect retained stderr"}
        git_context.close()
        if (evaluator.config_key and "shutdown_error" not in result
                and result.get("failure", {}).get("origin") != "operator"
                and result["checkpoints"]):
            # All model sessions, including nested verification, are closed.
            # Hidden tests never enter the author/review/repair loop.
            if source_hashes() != code:
                result.update(status="failed", error="runner or benchmark source changed before evaluation")
                result["evaluation"].update(status="error", error=result["error"])
            else:
                evaluation.finish(evaluator)
        result["duration_seconds"] = time.monotonic()-start
        result["fixture_executed"] = fixture_fired
        evaluation.save_result(output, result)
    return result


def comparable(*reports):
    for result in reports:
        if result.get("status") != "passed" or not result.get("usage", {}).get("measurement_complete"):
            raise ValueError("percentage requires successful complete workflows with no flagged measurement gaps; partial results remain reportable")
        if not result.get("comparison_key") or result["comparison_key"] != reports[0]["comparison_key"]:
            raise ValueError("non-factor settings differ; these results cannot be used for an isolated percentage")


def compare(reference, changed):
    reference, changed = map(comparison_view, (reference, changed))
    comparable(reference, changed)
    a, b = (r["usage"]["observed_raw_tokens"] for r in (reference, changed))
    if a <= 0:
        raise ValueError("reference usage must be positive")
    return {"reference_raw_tokens": a, "changed_raw_tokens": b, "observed_saved_raw_tokens": a-b,
            "observed_reduction_percent": 100*(a-b)/a, "denominator": "reference observed raw tokens",
            "changed_factors": [c for c in reference["factors"] if reference["factors"][c] != changed["factors"][c]],
            "limit": "observed sample difference, not causal certainty or additive historical shares"}


def interaction(neither, a_only, b_only, both):
    neither, a_only, b_only, both = map(comparison_view, (neither, a_only, b_only, both))
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
