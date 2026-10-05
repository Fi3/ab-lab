"""Run with python3 -m lab; scb-check is an external measurement command."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from .config import FACTORS, WORKFLOW_VERSION, author_policy, load_benchmark, settings
from .context import AUTO_COMPACT_TOKENS
from .provider import Codex, Pi
from .host import Fatal
from .review import DEFAULT_MAX_REVIEW_LOOPS, DEFAULT_PRIORITIES, normalize_priorities, normalize_review_loops
from .loops import POLICY_VERSION, loop_policy
from .workflow import compare, interaction, run
from .batch import run_batch
from .summary import records
from .executor import DEFAULT_PROFILE, PRIVATE_ENV


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def review_priorities(value):
    try:
        return normalize_priorities(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def review_loops(value):
    try:
        return normalize_review_loops(int(value))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError('max review loops must be a nonnegative integer') from exc


def factors_from(args):
    result = {} if args.preset == "all" else dict.fromkeys(FACTORS, False)
    on, off = set(filter(None, args.on.split(","))), set(filter(None, args.off.split(",")))
    if on & off:
        raise ValueError("a factor cannot be both --on and --off")
    result.update(dict.fromkeys(on, True))
    result.update(dict.fromkeys(off, False))
    return settings(result)


def main():
    parser = argparse.ArgumentParser(description="Standalone agent behavior research: isolated workflows, optional parallel repetitions, retained outcomes.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("factors", help="show the exact ON/OFF meanings")
    for name in ("plan", "run"):
        p = commands.add_parser(name)
        p.add_argument("benchmark", type=Path)
        p.add_argument("--preset", choices=("all", "native"), default="all")
        p.add_argument("--pi-vanilla", action="store_true", help="disable Pi customizations and context files; works with all or native")
        p.add_argument("--on", default="", help="comma-separated C identifiers")
        p.add_argument("--off", default="", help="comma-separated C identifiers")
        p.add_argument("--model", default=None)
        p.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh"), default="xhigh")
        p.add_argument("--compaction-tokens", type=positive_integer, default=AUTO_COMPACT_TOKENS,
                       metavar="N", help="context tokens at which the harness compacts (default: 131072 for every preset; unsupported harnesses fail)")
        p.add_argument("--review-priorities", type=review_priorities, default=DEFAULT_PRIORITIES,
                       metavar="P0,P1,P2",
                       help="comma-separated review priorities that require repairs (P0 through P3; default: P0,P1,P2)")
        p.add_argument("--max-review-loops", type=review_loops, default=None,
                       metavar="N", help="maximum reviews per feature; repair blocking findings after each review, then continue (default: 3 for all, 0 for native; 0 disables review)")
        progress = p.add_mutually_exclusive_group()
        progress.add_argument("--loop-policy", type=Path, help="JSON overrides for external feature/review limits and loop detection")
        progress.add_argument("--no-loop-detection", action="store_true", help="disable feature stopping rules; retain review allowance and global run limits")
        p.add_argument("--scb-check", default="scb-check", help="scb-check executable for source quality measurements")
        p.add_argument("--scb-seconds", type=float, default=300, help="maximum seconds per quality measurement, within the workflow deadline")
        p.add_argument('--executor', type=Path, default=DEFAULT_PROFILE,
                       help='public executor build definition (default: executors/default.json)')
        if name == "plan":
            p.add_argument("--harness", choices=("codex", "pi"), default="codex", help="agent harness: codex or pi")
        if name == "run":
            p.add_argument("--out", type=Path, required=True, help="new run or batch directory; must not exist")
            p.add_argument("--seconds", type=int, required=True)
            p.add_argument("--max-raw", type=int, required=True, help="observed-token stop, not a guaranteed hard charge cap")
            p.add_argument("--max-turns", type=int, required=True)
            p.add_argument("--harness", choices=("codex", "pi"), required=True, help="agent harness: codex or pi")
            p.add_argument("--codex", default="codex")
            p.add_argument("--pi", default="pi")
            p.add_argument("--parallel", type=positive_integer, default=1,
                           help="maximum simultaneous workflows; also the repetition count unless --repeat is set")
            p.add_argument("--repeat", type=positive_integer,
                           help="total repetitions of this benchmark; defaults to --parallel")
    doctor = commands.add_parser("doctor", help="read-only subscription/configuration check; no generation")
    doctor.add_argument("--repo", type=Path, default=Path.cwd())
    doctor.add_argument("--out", type=Path, required=True)
    doctor.add_argument("--harness", choices=("codex", "pi"), default="codex", help="agent harness: codex or pi")
    doctor.add_argument("--codex", default="codex")
    doctor.add_argument("--pi", default="pi")
    doctor.add_argument("--model", default=None)
    doctor.add_argument('--native', action='store_true', help='qualify native delegation without model generation')
    doctor.add_argument('--pi-vanilla', action='store_true', help='qualify Pi without installed or project customizations')
    doctor.add_argument('--executor', type=Path, default=DEFAULT_PROFILE)
    report = commands.add_parser("report")
    report.add_argument("results", type=Path, nargs="+")
    comp = commands.add_parser("compare", help="observed change versus reference, with a named denominator")
    comp.add_argument("reference", type=Path)
    comp.add_argument("changed", type=Path)
    joint = commands.add_parser("interaction", help="four matched cells: neither, A only, B only, both")
    joint.add_argument("results", type=Path, nargs=4)
    args = parser.parse_args()
    try:
        if getattr(args, 'pi_vanilla', False) and args.harness != 'pi':
            raise ValueError('--pi-vanilla requires --harness pi')
        if args.command == "factors":
            value = {key: dict(zip(("description", "on", "off"), meaning)) for key, meaning in FACTORS.items()}
        elif args.command in ("run", "plan"):
            benchmark, factors = load_benchmark(args.benchmark), factors_from(args)
            if args.max_review_loops is None:
                args.max_review_loops = 0 if args.preset == "native" else DEFAULT_MAX_REVIEW_LOOPS
            progress_policy = loop_policy(json.loads(args.loop_policy.read_text()) if args.loop_policy else
                                          {"enabled": False} if args.no_loop_detection or args.preset == "native" else None)
            if args.command == "plan":
                harness = getattr(args, "harness", "codex")
                model = args.model or "gpt-5.5"
                value = {"benchmark": benchmark, "factors": factors, "preset": args.preset, "model": model, "effort": args.effort,
                         "pi_vanilla": args.pi_vanilla,
                         "review_priorities": list(args.review_priorities),
                         "max_review_loops": args.max_review_loops,
                         "compaction_tokens": args.compaction_tokens,
                         "loop_policy": progress_policy,
                         "loop_policy_version": POLICY_VERSION, "workflow_version": WORKFLOW_VERSION,
                         "author_policy": author_policy(factors), "generation": "none",
                         "executor": str(args.executor.resolve()) if args.executor else None,
                         "scb_check": {"executable": args.scb_check, "seconds_per_check": args.scb_seconds,
                                       "phases": ["before_changes", "after_implementation"]}}
                if harness == 'pi':
                    value['pi_resource_policy'] = Pi.resource_policy(args.pi_vanilla)
            else:
                if args.harness == "pi":
                    backend = Pi
                    executable = args.pi
                    model = args.model or "gpt-5.5"
                else:
                    backend = Codex
                    executable = args.codex
                    model = args.model or "gpt-5.5"
                repeat = args.repeat if args.repeat is not None else args.parallel
                if repeat > 1:
                    value = run_batch(benchmark, factors, args.out, repeat, args.parallel,
                        seconds=args.seconds, max_raw=args.max_raw, max_turns=args.max_turns,
                        model=model, effort=args.effort, executable=executable, harness=args.harness,
                        scb_check=args.scb_check, scb_seconds=args.scb_seconds, child_codex=args.codex,
                        review_priorities=args.review_priorities,
                        max_review_loops=args.max_review_loops, preset=args.preset,
                        compaction_tokens=args.compaction_tokens,
                        loop_options=progress_policy, executor=args.executor, pi_vanilla=args.pi_vanilla)
                else:
                    value = run(benchmark, factors, args.out, args.seconds, args.max_raw, args.max_turns,
                                model, args.effort, executable, backend=backend, harness=args.harness,
                                scb_check=args.scb_check, scb_seconds=args.scb_seconds, child_codex=args.codex,
                                review_priorities=args.review_priorities,
                                max_review_loops=args.max_review_loops, preset=args.preset,
                                compaction_tokens=args.compaction_tokens,
                                loop_options=progress_policy, executor=args.executor, pi_vanilla=args.pi_vanilla)
        elif args.command == "doctor":
            if not os.environ.get(PRIVATE_ENV):
                from .executor import doctor as executor_doctor
                return executor_doctor(args.executor, args.out, args.harness, args.native, args.model, pi_vanilla=args.pi_vanilla)
            harness = getattr(args, "harness", "codex")
            if harness == "pi":
                backend = Pi
                executable = getattr(args, "pi", "pi")
                model = getattr(args, "model", None) or "gpt-5.5"
            else:
                backend = Codex
                executable = getattr(args, "codex", "codex")
                model = getattr(args, "model", None) or "gpt-5.5"
            provider = backend(args.repo.resolve(strict=True), args.out, model, "xhigh", time.monotonic()+30, 1, 1, executable,
                               **({'allow_delegation': True} if args.native else {}),
                               **({"codex_executable": args.codex, "pi_vanilla": args.pi_vanilla} if backend is Pi else {}))
            try:
                value = {**provider.identity, "generation": "none"}
            finally:
                provider.close()
        else:
            def read(path):
                return json.loads(path.read_text())
            if args.command == "compare":
                value = compare(read(args.reference), read(args.changed))
            elif args.command == "interaction":
                value = interaction(*(read(p) for p in args.results))
            else:
                value = [r for p in args.results for r in records(read(p))]
        print(json.dumps(value, indent=2))
        return 1 if isinstance(value, dict) and value.get("status") in ("failed", "needs_attention") else 0
    except (OSError, ValueError, RuntimeError, Fatal) as exc:
        print(f"agent-behavior-lab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
