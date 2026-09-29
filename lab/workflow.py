"""One isolated, sequential implement/review/repair workflow per invocation."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

from .config import author_policy
from .host import Fatal, Rejected, Host, execute_child, git, save_json, snapshot, parse_operations, relative_path
from .provider import Codex, Pi, clean_env
from .review import DEFAULT_PRIORITIES, conclusion_prompt, format_findings, normalize_priorities, parse_review, review_clean, review_instructions
from .loops import FeatureProgress, NeedsAttention, POLICY_VERSION, ReviewConclusionRequested, WorkLimitReached, loop_policy, work_limit_error
from . import scb, slopcodebench


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.iterdir()) if p.suffix in (".py", ".mjs")}


def native_done(reply):
    """A unique final marker may follow a normal human-readable summary."""
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    if not lines or lines[-1] != "@standalone done" or lines.count("@standalone done") != 1:
        return False
    fence = None
    for line in lines[:-1]:
        if line.startswith(("```", "~~~")):
            if fence == line[:3]:
                fence = None
            elif fence is None:
                fence = line[:3]
    return fence is None


def author_prompt(benchmark, feature, factors, findings=None):
    action = ("Implement this feature with focused tests." if findings is None else
              "Fix only the reviewed feature and its tests to resolve these blocking findings. "
              "Use a focused general fix and regression coverage; reuse existing test helpers instead of duplicating similar cases.\n" + findings)
    docs = ("Documentation and prose updates are deferred to final integration. Do not modify docs/**, README*, CHANGELOG*, *.md or *.txt during feature implementation/repair."
            if benchmark["defer_documentation"] else "Update documentation required by the assigned feature.")
    return f"You are a direct coding agent in this repository.\n\nRequest {feature['id']}:\n{feature['request']}\n\n{action}\nFollow repository instructions except the explicit procedural overrides below. Do not use Work Leaf or extra worktrees. Avoid unrelated refactors.\n{docs}\n{benchmark['instructions']}\n\n{author_policy(factors)}"


def review_prompt(benchmark, feature, base, evidence, no_changes=False, *, review_priorities=DEFAULT_PRIORITIES):
    docs = "Documentation is deferred to final integration; do not report deferred prose as missing." if benchmark["defer_documentation"] else "Check required documentation too."
    instructions = review_instructions(review_priorities)
    if no_changes:
        return f"You are an independent review agent. Do not modify files.\nThe author reports this feature already exists, with no source changes since {base}. Independently verify the complete requested behavior and its tests; an empty diff alone is not approval. Report missing behavior or tests for this request, not unrelated pre-existing issues.\nRequest {feature['id']}:\n{feature['request']}\n{docs}\n{benchmark['instructions']}\n{evidence}\n{instructions}"
    return f"You are an independent review agent. Do not modify files.\nReview only changes since {base} for request {feature['id']}:\n{feature['request']}\nInspect {base}..HEAD. Report only bugs, regressions, concrete maintainability problems or missing tests introduced by this feature. Do not report unrelated pre-existing issues.\n{docs}\n{benchmark['instructions']}\n{evidence}\n{instructions}"


def integration_prompts(benchmark, base, checkpoints, *, skip_linearization=False):
    count = len(benchmark["features"])
    contract = f"Produce exactly {count} final commits rooted at {base}, one per feature. Fold implementation, tests, review repairs, validation fixes and required documentation into the corresponding feature commit. No separate support or documentation-only commits. Preserve all reviewed behavior and follow repository commit-message rules. Do not push or modify other checkouts."
    if skip_linearization:
        contract = "Preserve all reviewed commits exactly as generated. Do not reorder, squash, amend, rebase or replace existing commits. Complete required documentation and repair genuine final-validation failures using new commits only. There is no required commit count; already-satisfied features need no empty commits. Preserve all reviewed behavior and follow repository commit-message rules. Do not push or modify other checkouts."
    elif any(item.get("already_satisfied") for item in checkpoints):
        contract += " A boundary marked already_satisfied was independently verified without source changes. Use an explicitly described verification-only empty commit for that feature; do not invent edits."
    detail = json.dumps(checkpoints, indent=2)
    plan = f"You are the final integration agent for {count} sequentially reviewed features.\n{contract}\nReviewed feature boundaries:\n{detail}\nInspect history and source, identify required documentation, and propose a plan. Do not edit, commit, rewrite history or run the check suite yet. End with your plan and wait for acceptance.\n{benchmark['instructions']}"
    accept = f"Accept the proposed plan and execute it.\n{contract}\nRun these final checks and all additional repository-required checks; repair genuine failures until they pass within the run budget:\n"+"\n".join(benchmark["checks"])+"\nLeave the checkout clean and summarize final commits and actual verification results."
    if any(item.get("status") == "needs_attention" for item in checkpoints):
        # Integration still runs, but must not manufacture review approval or
        # reopen the stopped checkpoint's repair loop under a different label.
        notice = ("Some checkpoint attempts stopped with unresolved review findings. "
                  "Their recorded snapshots and review outcomes remain unchanged. "
                  "Do not restart those stopped review/repair loops during integration. "
                  "Complete assembly, required documentation, and final checks; repairs to genuine "
                  "final-validation failures may change the final tree without approving earlier attempts. "
                  "Report actual failures.\n")
        plan = plan.replace("sequentially reviewed features", "sequential checkpoint attempts")
        plan = plan.replace("Reviewed feature boundaries:", "Checkpoint boundaries and review outcomes:")
        plan = notice + plan
        accept = notice + accept
    return plan, accept


def prior_attention_note(checkpoints):
    unresolved = [{key: item.get(key) for key in ("feature", "head", "review_approved", "blocking_findings",
                                                "incomplete_reason", "stop_reason", "loop_flags")}
                  for item in checkpoints if item.get("status") == "needs_attention"]
    if not unresolved:
        return ""
    return ("\n\nEarlier checkpoint attempts stopped with unresolved findings. "
            "The current source contains those attempts; they were not approved. "
            "Implement the current cumulative requirements within this checkpoint's budget. "
            "Earlier snapshot grades and review outcomes remain separate.\n" + json.dumps(unresolved))


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
        model="gpt-5.5", effort="xhigh", executable="codex", backend=Codex, *,
        harness=None, scb_check=None, scb_seconds=300, child_codex="codex", skip_linearization=False,
        review_priorities=DEFAULT_PRIORITIES, loop_options=None, _prepared=None, _base_commit=None):
    if seconds <= 0 or max_raw <= 0 or max_turns <= 0:
        raise ValueError("positive wall-time, observed-token and turn limits are required")
    if not math.isfinite(scb_seconds) or scb_seconds <= 0:
        raise ValueError("scb-check needs a positive finite time limit")
    review_priorities = normalize_priorities(review_priorities)
    if _prepared and review_priorities != normalize_priorities(_prepared["manifest"].get("review_priorities", DEFAULT_PRIORITIES)):
        raise ValueError("continuation must preserve the original review priorities")
    if _prepared and skip_linearization != _prepared["manifest"].get("skip_linearization", False):
        raise ValueError("continuation must preserve the original linearization setting")
    progress_policy = loop_policy(loop_options)
    if _prepared and progress_policy != loop_policy(_prepared["manifest"].get("loop_policy", {"enabled": False})):
        raise ValueError("continuation must preserve the original loop policy")
    if _prepared and _prepared["manifest"].get("loop_policy_version", POLICY_VERSION) != POLICY_VERSION:
        raise ValueError("continuation must preserve the original loop policy version")
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
    result = {"schema": "agent-behavior-lab/v1", "status": "failed", "factors": factors,
              "output": str(output), "benchmark": benchmark["name"],
              "skip_linearization": skip_linearization,
              "review_priorities": list(review_priorities), "reviews": [],
              "loop_policy": progress_policy, "loop_policy_version": POLICY_VERSION, "loop_flags": [], "review_wrapups": [],
              "feature_count": len(benchmark["features"]), "check_count": len(benchmark["checks"]),
              "stages": [], "checkpoints": [], "checks": [], "factor_activations": {}}
    if scb_check is not None:
        result["scb_check"] = scb.pending()
    if "slopcodebench" in benchmark:
        result["slopcodebench"] = slopcodebench.pending(benchmark)
        result["execution_status"] = "incomplete"
        result["checkpoint_stop_policy"] = slopcodebench.CHECKPOINT_STOP_POLICY
    start = time.monotonic()
    code = source_hashes()
    try:
        base = git(benchmark["repo"], "rev-parse", "--verify", (_base_commit or benchmark["revision"])+"^{commit}").decode().strip()
        default_transport = "pi-rpc-stdio" if harness == "pi" else "codex-app-server-stdio"
        transport = backend.transport if isinstance(getattr(backend, "transport", None), str) else default_transport
        manifest = {"schema": "agent-behavior-lab/v1", "benchmark": benchmark, "base_commit": base,
                    "factors": factors, "limits": {"seconds": seconds, "observed_raw_tokens": max_raw, "turns": max_turns},
                    "model": model, "effort": effort, "source_sha256": code,
                    "workflow": "sequential-implement-review-repair-then-plan-accept-and-one-commit-per-feature",
                    "transport": transport, "created_at_unix": time.time()}
        manifest["checkout_policy"] = (_prepared["manifest"].get("checkout_policy", "legacy-full-clone")
                                       if _prepared else "pinned-history-no-remotes-v1")
        manifest["skip_linearization"] = skip_linearization
        manifest["review_priorities"] = list(review_priorities)
        manifest["loop_policy"] = progress_policy
        manifest["loop_policy_version"] = POLICY_VERSION
        if skip_linearization:
            manifest["workflow"] = "sequential-implement-review-repair-then-plan-accept-preserving-commits"
        if scb_check is not None:
            manifest["scb_check"] = {"executable": str(scb_check), "seconds_per_check": scb_seconds}
        if "slopcodebench" in benchmark:
            manifest["checkpoint_stop_policy"] = slopcodebench.CHECKPOINT_STOP_POLICY
            files = git(benchmark["repo"], "ls-tree", "-r", "--name-only", base).decode().splitlines()
            if files not in ([], [".gitignore"]):
                raise Fatal("SlopCodeBench must start from an empty project (only .gitignore is allowed)")
            manifest["slopcodebench_runtime"] = slopcodebench.preflight(benchmark, output, deadline)
            result["slopcodebench"]["runtime"] = manifest["slopcodebench_runtime"]
        if _prepared:
            if factors["C17"] or base != _prepared['manifest']['base_commit']:
                raise Fatal('continuation must preserve native custody and the original base')
            from .continuation import archive_boundary
            archive_boundary(_prepared, output)
            manifest['continuation'] = {'previous': str(_prepared['previous']),
                'original_created_at': _prepared['manifest']['created_at_unix'],
                'prior_result_sha256': _prepared['prior_result_sha256'],
                'source_head': _prepared['source_head'],
                'original_limits': _prepared['manifest']['limits']}
            result['continuation'] = manifest['continuation']
            result['stages'] = list(_prepared['result']['stages'])
        save_json(output / "manifest.json", manifest)
        checkout = output / "checkout"
        if _prepared:
            checkout.symlink_to(_prepared['checkout'], target_is_directory=True)
            checkout = _prepared['checkout']
            if git(checkout, 'rev-parse', 'HEAD').decode().strip() != _prepared['source_head'] or git(checkout, 'status', '--porcelain'):
                raise Fatal('continuation source changed after qualification')
        else:
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
            if phase == "before_changes" and "slopcodebench" in benchmark:
                observation = {"phase": phase, "status": "not_applicable", "commit": base,
                               "reason": "Empty starting project has no source code to measure"}
                (output / "scb-check" / phase).mkdir()
                save_json(output / "scb-check" / phase / "result.json", observation)
            else:
                observation = scb.measure(checkout, output, phase, quality["tool"], deadline)
            quality["measurements"][phase] = observation
            if observation["status"] not in ("completed", "not_applicable"):
                raise Fatal(f"scb-check {phase}: {observation['error']}")
            if all(m["status"] in ("completed", "not_applicable") for m in quality["measurements"].values()):
                quality["status"] = "completed"

        if quality is not None and _prepared:
            prior = _prepared["result"].get("scb_check", {})
            initial = prior.get("measurements", {}).get("before_changes", {})
            initial_statuses = ("completed", "not_applicable") if "slopcodebench" in benchmark else ("completed",)
            if (prior.get("tool") != quality["tool"] or initial.get("status") not in initial_statuses
                    or initial.get("commit") != base):
                raise Fatal("continuation needs the same scb-check tool and original before-changes result")
            quality["measurements"]["before_changes"] = initial
        else:
            score("before_changes")
        provider = backend(checkout, output / "provider", model, effort, deadline, max_raw, max_turns, executable,
                           require_git_write=True, **({"codex_executable": child_codex} if backend is Pi else {}))
        if manifest["model"] is None and provider.identity.get("model"):
            manifest["model"] = provider.identity["model"]
            with (output / "manifest.json").open("w", encoding="utf-8") as out:
                json.dump(manifest, out, ensure_ascii=False, indent=2)
                out.write("\n")
        if _prepared:
            from .continuation import configuration_matches, restore_provider
            if not configuration_matches(provider, _prepared['identity'], _prepared.get('redundant_trust', ())):
                raise Fatal('continuation provider identity differs from the original')
            restore_provider(provider, _prepared['manifest'], _prepared['result']['usage'], _prepared['author'])
            prior_usage = provider.report()
            if not prior_usage['measurement_complete'] or prior_usage['observed_raw_tokens'] != _prepared['result']['usage']['observed_raw_tokens']:
                raise Fatal('continuation did not recover exact prior complete costs')
        invariant = {k: v for k, v in manifest.items() if k not in ("factors", "created_at_unix")}
        invariant["provider"] = provider.identity
        if quality is not None:
            invariant["scb_check_tool"] = quality["tool"]
        result["comparison_key"] = fingerprint(invariant)
        save_json(output / "invariants.json", invariant)

        def observed_raw():
            return provider.observed_raw() if hasattr(provider, "observed_raw") else provider.report()["observed_raw_tokens"]

        def turn(thread, prompt, label, **options):
            # Providers also enforce these limits inside long native turns.
            error = work_limit_error(getattr(provider, "work_limits", ()), observed_raw())
            if error:
                raise error
            result["stages"].append({"stage": label, "thread_id": thread, "started_at_unix": time.time()})
            with (output / "progress.jsonl").open("a") as out:
                out.write(json.dumps(result["stages"][-1])+"\n")
            reply = provider.turn(thread, prompt, label, **options)
            if not provider.report().get("measurement_complete"):
                raise Fatal("incomplete token measurement; stop before further host work or agent generation")
            error = work_limit_error(getattr(provider, "work_limits", ()), observed_raw())
            if error:
                if isinstance(error, ReviewConclusionRequested):
                    error.completed_reply = reply
                raise error
            return reply

        for feature_index, feature in enumerate(benchmark["features"]):
            name = feature["id"]
            reuse_author = _prepared is not None and feature_index == 0
            feature_base = base if reuse_author else git(checkout, "rev-parse", "HEAD").decode().strip()
            progress = FeatureProgress(feature, progress_policy, 0 if reuse_author else observed_raw())
            author = _prepared['author'] if reuse_author else provider.start_thread(writable=not factors["C17"])
            host = Host(checkout, output / (name+"-host"), name, "author", deadline, factors,
                        command_env=getattr(provider, "command_env", None),
                        command_argv=getattr(provider, "command_argv", None)) if factors["C17"] else None

            def record_stop(signal, label):
                flag = progress.record_flag(signal, output, checkout, feature_base, label, observed_raw(),
                                            progress.reviews, pending_changes={key: value["artifact"] for key, value in host.pending.items()} if host else None)
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
                nonlocal fixture_fired
                provider.work_limits = progress.limits(observed_raw())
                progress.operations.clear()
                try:
                    if host:
                        while not host.completed:
                            reply = turn(author, prompt + progress.budget_note(observed_raw()), label,
                                         interrupt=factors["C25"], host_request=True)
                            host.unchanged()
                            host.evidence("AUTHOR REPLY", reply)
                            prompt = host.consume(reply)
                            if hasattr(provider, "settle_children"):
                                provider.settle_children()
                            if fixture and not fixture_fired:
                                try:
                                    operations = parse_operations(reply)
                                except Rejected:
                                    operations = []
                                if len(operations) == 1 and operations[0][0] == "read" and relative_path(checkout, operations[0][1]) == fixture["path"] and fixture["path"] in host.seen:
                                    after_read_fixture(host, fixture, output, deadline)
                                    fixture_fired = True
                            if not host.completed:
                                signal = progress.observe_operation(reply, prompt, checkout)
                                if signal:
                                    return record_stop(signal, label)
                    else:
                        reply = turn(author, prompt + progress.budget_note(observed_raw()), label, writable=True)
                        if not native_done(reply):
                            raise Fatal("native author did not supply the stage-completion marker")
                except WorkLimitReached as exc:
                    return record_stop(exc.signal, label)
                if git(checkout, "status", "--porcelain"):
                    raise Fatal("author left uncommitted source changes")
                return None

            stopped_flag = None
            round_number = 0
            try:
                author_stop = None
                if not reuse_author:
                    author_stop = implement(author_prompt(benchmark, feature, factors)
                                            + prior_attention_note(result["checkpoints"]), name+"-implement")
                # Checks need build-output writes just as author/integration checks
                # do. The snapshot guard below still rejects reviewer source edits.
                reviewer = None
                round_number, evidence = 1, ""

                def review_turn(prompt, label):
                    try:
                        return turn(reviewer, prompt, label, writable=True)
                    except ReviewConclusionRequested as exc:
                        if snapshot(checkout) != before:
                            raise Fatal("reviewer changed source, index or history")
                        if not provider.report().get("measurement_complete"):
                            raise Fatal("incomplete token measurement; cannot request review conclusion")
                        event = {"feature": name, "round": round_number, "stage": label,
                                 "trigger": exc.signal, "status": "started", "used_completed_verdict": False,
                                 "raw_tokens_at_threshold": observed_raw()}
                        result["review_wrapups"].append(event)
                        path = output / (label + "-wrapup.json")
                        save_json(path, event)
                        try:
                            if exc.completed_reply:
                                try:
                                    parse_review(exc.completed_reply, review_priorities)
                                except ValueError:
                                    pass
                                else:
                                    event.update(status="completed", used_completed_verdict=True)
                                    return exc.completed_reply
                            # One continuation of the same review, never a fresh
                            # review round or another exploration allowance.
                            provider.work_limits = progress.limits(observed_raw(), reviewing=True, concluding=True)
                            reply = turn(reviewer, conclusion_prompt(review_priorities), label + "-conclude", writable=True)
                            event["status"] = "completed"
                            return reply
                        except WorkLimitReached as stopped:
                            event.update(status="stopped", stop=stopped.signal)
                            raise
                        except (Exception, KeyboardInterrupt) as error:
                            event.update(status="failed", error=str(error) or "operator interruption")
                            raise
                        finally:
                            event["raw_tokens_after_conclusion"] = observed_raw()
                            temporary = path.with_suffix(".tmp")
                            save_json(temporary, event)
                            temporary.replace(path)

                while True:
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
                    provider.work_limits = progress.limits(observed_raw(), reviewing=True, final=bool(author_stop))
                    if reviewer is None:
                        reviewer = provider.start_thread(writable=True)
                    before = snapshot(checkout)
                    no_changes = git(checkout, "rev-parse", "HEAD").decode().strip() == feature_base
                    review_label = f"{name}-review-{round_number}"
                    try:
                        reply = review_turn(review_prompt(benchmark, feature, feature_base, evidence, no_changes,
                                     review_priorities=review_priorities) + progress.budget_note(observed_raw()),
                                     review_label)
                        if snapshot(checkout) != before:
                            raise Fatal("reviewer changed source, index or history")
                        decision = parse_review(reply, review_priorities)
                    except WorkLimitReached as exc:
                        if snapshot(checkout) != before:
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
                        host.completed = False
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
                    round_number += 1
            except NeedsAttention as exc:
                if "slopcodebench" not in benchmark:
                    raise
                # A local attempt limit ends this checkpoint's agent work, not
                # the experiment. Global/provider/integrity failures still escape.
                stopped_flag = exc.flag
                retention = slopcodebench.retain_attempt(checkout, name)
                stopped_flag["continuation"] = {"status": "continued", **retention}
                progress.save_flag(stopped_flag)
                no_changes = git(checkout, "rev-parse", "HEAD").decode().strip() == feature_base

            provider.work_limits = []
            checkpoint = {"feature": name, "request": feature["request"], "base": feature_base,
                          "reviewed_head": git(checkout, "rev-parse", "HEAD").decode().strip(), "review_rounds": round_number,
                          "already_satisfied": no_changes, "observed_raw_tokens": observed_raw() - progress.raw_start,
                          "loop_flags": [f["artifact"] for f in progress.flags]}
            if "slopcodebench" in benchmark:
                checkpoint.update(status="needs_attention" if stopped_flag else "approved",
                                  head=checkpoint["reviewed_head"],
                                  review_approved=stopped_flag["review_approved"] if stopped_flag else True)
                if stopped_flag:
                    checkpoint["reviewed_head"] = None
                    checkpoint["already_satisfied"] = False
                    checkpoint["stop_reason"] = stopped_flag["reason"]
                    checkpoint["incomplete_reason"] = (progress.reviews[-1].get("incomplete_reason")
                                                       if progress.reviews else None)
                    checkpoint["blocking_findings"] = (progress.reviews[-1]["blocking_findings"]
                                                       if progress.reviews else [])
            result["checkpoints"].append(checkpoint)
            if host:
                for key, count in host.activations.items():
                    result["factor_activations"][key] = result["factor_activations"].get(key, 0)+count
            save_json(output / (name+"-result.json"), {**checkpoint, "factor_activations": host.activations if host else {"C17": "native tools"}})
            if "slopcodebench" in result:
                item = result["slopcodebench"]["checkpoints"][feature_index]
                item.update(slopcodebench.capture(checkout, output, name))
                item["review_approved"] = checkpoint["review_approved"]
                item["attempt_status"] = checkpoint["status"]
                if stopped_flag:
                    stopped_flag["continuation"].update({key: item[key] for key in ("snapshot", "commit", "tree")})
                    progress.save_flag(stopped_flag)
                if quality is not None:
                    item["quality"] = scb.measure(checkout, output, "checkpoint-" + name, quality["tool"], deadline)
                    if item["quality"]["status"] != "completed":
                        raise Fatal("scb-check checkpoint measurement failed: " + item["quality"]["error"])

        score("after_implementation")
        reviewed = git(checkout, "rev-parse", "HEAD").decode().strip()
        git(checkout, "update-ref", "refs/agent-lab/reviewed", reviewed)
        plan, accept = integration_prompts(benchmark, base, result["checkpoints"],
                                           skip_linearization=skip_linearization)
        integrator = provider.start_thread()
        before = snapshot(checkout)
        turn(integrator, plan, "integration-plan")
        if snapshot(checkout) != before:
            raise Fatal("integration planning modified source/index/history")
        turn(integrator, accept, "integration-accept", writable=True)
        git(checkout, "merge-base", "--is-ancestor", base, "HEAD")
        commits = git(checkout, "rev-list", "--reverse", base+"..HEAD").decode().splitlines()
        if skip_linearization:
            if git(checkout, "rev-list", reviewed, "--not", "HEAD"):
                raise Fatal("final integration must preserve reviewed commits when linearization is skipped")
        elif len(commits) != len(benchmark["features"]) or git(checkout, "rev-list", "--merges", base+"..HEAD"):
            raise Fatal("final history must be linear with exactly one commit per feature")
        score("after_assembly")
        if "slopcodebench" in result and not git(checkout, "status", "--porcelain"):
            result["slopcodebench"]["final"] = {"feature": "final", "status": "not_run",
                **slopcodebench.capture(checkout, output, "final")}
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
                raise Fatal(f"final check {index} failed; no automatic replacement")
        if git(checkout, "status", "--porcelain"):
            raise Fatal("final checkout is not clean")
        if source_hashes() != code:
            raise Fatal("runner source changed during execution")
        if not provider.report().get("measurement_complete"):
            raise Fatal("incomplete whole-workflow token measurement, including nested verification")
        unresolved = [c for c in result["checkpoints"] if c.get("status") == "needs_attention"]
        result.update(status="needs_attention" if unresolved else "passed", final_commits=commits)
        if "slopcodebench" in result:
            result["execution_status"] = "completed"
        if unresolved:
            result["attention_features"] = [c["feature"] for c in unresolved]
            result["blocked_features"] = []
            result["error"] = "Benchmark execution completed with unresolved checkpoint reviews; see loop_flags and slopcodebench grades"
    except NeedsAttention as exc:
        result.update(status="needs_attention", error=str(exc), attention=exc.flag,
                      blocked_features=[f["id"] for f in benchmark["features"][feature_index+1:]])
    except (Exception, KeyboardInterrupt) as exc:
        result["error"] = str(exc) or "operator interruption"
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        else:
            result["usage"] = {"observed_raw_tokens": None, "measurement_complete": False,
                               "reason": "provider did not initialize; inspect retained stderr"}
        if ("slopcodebench" in result and result.get("error") != "operator interruption"
                and any("snapshot" in item for item in result["slopcodebench"]["checkpoints"])):
            # All model sessions, including nested verification, are closed.
            # Hidden tests never enter the review/repair/integration loop.
            save_json(output / "slopcodebench" / "before-evaluation.json", result)
            slopcodebench.evaluate(benchmark, result, output)
        result["duration_seconds"] = time.monotonic()-start
        if _prepared:
            result['continuation_duration_seconds'] = result['duration_seconds']
            result['duration_seconds'] += _prepared['result']['duration_seconds']
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
