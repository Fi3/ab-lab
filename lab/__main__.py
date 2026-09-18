"""Run with python3 -m lab; scb-check is an external measurement command."""
import argparse
import json
from pathlib import Path
import sys
import time

from .config import FACTORS, author_policy, load_benchmark, settings
from .provider import Codex, Pi
from .host import Fatal
from .workflow import compare, interaction, run
from .batch import run_batch
from .summary import records


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def factors_from(args):
    result = {} if args.preset == "all" else {"C08": False, "C25": False}
    if args.preset == "native":
        result["C17"] = False
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
        p.add_argument("--preset", choices=("all", "j04", "native"), default="all")
        p.add_argument("--on", default="", help="comma-separated C identifiers")
        p.add_argument("--off", default="", help="comma-separated C identifiers")
        p.add_argument("--model", default=None)
        p.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh"), default="xhigh")
        p.add_argument("--scb-check", default="scb-check", help="scb-check executable; required for the three quality measurements")
        p.add_argument("--scb-seconds", type=float, default=300, help="maximum seconds per quality measurement, within the workflow deadline")
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
    report = commands.add_parser("report")
    report.add_argument("results", type=Path, nargs="+")
    comp = commands.add_parser("compare", help="observed change versus reference, with a named denominator")
    comp.add_argument("reference", type=Path)
    comp.add_argument("changed", type=Path)
    joint = commands.add_parser("interaction", help="four matched cells: neither, A only, B only, both")
    joint.add_argument("results", type=Path, nargs=4)
    args = parser.parse_args()
    try:
        if args.command == "factors":
            value = {key: dict(zip(("description", "on", "off"), meaning)) for key, meaning in FACTORS.items()}
        elif args.command in ("run", "plan"):
            benchmark, factors = load_benchmark(args.benchmark), factors_from(args)
            if args.command == "plan":
                harness = getattr(args, "harness", "codex")
                model = args.model or ("gemini-3.8-flash" if harness == "pi" else "gpt-5.5")
                value = {"benchmark": benchmark, "factors": factors, "model": model, "effort": args.effort,
                         "author_policy": author_policy(factors), "generation": "none",
                         "scb_check": {"executable": args.scb_check, "seconds_per_check": args.scb_seconds,
                                       "phases": ["before_changes", "after_implementation", "after_assembly"]}}
            else:
                if args.harness == "pi":
                    backend = Pi
                    executable = args.pi
                    model = args.model
                else:
                    backend = Codex
                    executable = args.codex
                    model = args.model or "gpt-5.5"
                repeat = args.repeat if args.repeat is not None else args.parallel
                if repeat > 1:
                    value = run_batch(benchmark, factors, args.out, repeat, args.parallel,
                        seconds=args.seconds, max_raw=args.max_raw, max_turns=args.max_turns,
                        model=model, effort=args.effort, executable=executable, harness=args.harness,
                        scb_check=args.scb_check, scb_seconds=args.scb_seconds)
                else:
                    value = run(benchmark, factors, args.out, args.seconds, args.max_raw, args.max_turns,
                                model, args.effort, executable, backend=backend, harness=args.harness,
                                scb_check=args.scb_check, scb_seconds=args.scb_seconds)
        elif args.command == "doctor":
            harness = getattr(args, "harness", "codex")
            if harness == "pi":
                backend = Pi
                executable = getattr(args, "pi", "pi")
                model = getattr(args, "model", None)
            else:
                backend = Codex
                executable = getattr(args, "codex", "codex")
                model = getattr(args, "model", None) or "gpt-5.5"
            provider = backend(args.repo.resolve(strict=True), args.out, model, "xhigh", time.monotonic()+30, 1, 1, executable)
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
                value = [{**r, "path": str(Path(r['output'])/'result.json') if r.get('output') else str(p),
                          "scb_check": r.get("scb_check"), "error": r.get("error")}
                         for p in args.results for r in records(read(p))]
        print(json.dumps(value, indent=2))
        return 1 if isinstance(value, dict) and value.get("status") == "failed" else 0
    except (OSError, ValueError, RuntimeError, Fatal) as exc:
        print(f"agent-behavior-lab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
