"""Run with python3 -m lab; scb-check is an external measurement command."""
import argparse
import json
from pathlib import Path
import sys
import time

from .config import FACTORS, author_policy, load_benchmark, settings
from .provider import Codex
from .host import Fatal
from .workflow import compare, interaction, run


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
    parser = argparse.ArgumentParser(description="Standalone agent behavior research: one full workflow, retained outcomes, subscription only.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("factors", help="show the exact ON/OFF meanings")
    for name in ("plan", "run"):
        p = commands.add_parser(name)
        p.add_argument("benchmark", type=Path)
        p.add_argument("--preset", choices=("all", "j04", "native"), default="all")
        p.add_argument("--on", default="", help="comma-separated C identifiers")
        p.add_argument("--off", default="", help="comma-separated C identifiers")
        p.add_argument("--model", default="gpt-5.5")
        p.add_argument("--effort", choices=("minimal", "low", "medium", "high", "xhigh"), default="xhigh")
        p.add_argument("--scb-check", default="scb-check", help="scb-check executable; required for the three quality measurements")
        p.add_argument("--scb-seconds", type=float, default=300, help="maximum seconds per quality measurement, within the workflow deadline")
        if name == "run":
            p.add_argument("--out", type=Path, required=True, help="new run directory; must not exist")
            p.add_argument("--seconds", type=int, required=True)
            p.add_argument("--max-raw", type=int, required=True, help="observed-token stop, not a guaranteed hard charge cap")
            p.add_argument("--max-turns", type=int, required=True)
            p.add_argument("--codex", default="codex")
    doctor = commands.add_parser("doctor", help="read-only subscription/configuration check; no generation")
    doctor.add_argument("--repo", type=Path, default=Path.cwd())
    doctor.add_argument("--out", type=Path, required=True)
    doctor.add_argument("--codex", default="codex")
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
                value = {"benchmark": benchmark, "factors": factors, "model": args.model, "effort": args.effort,
                         "author_policy": author_policy(factors), "generation": "none",
                         "scb_check": {"executable": args.scb_check, "seconds_per_check": args.scb_seconds,
                                       "phases": ["before_changes", "after_implementation", "after_assembly"]}}
            else:
                value = run(benchmark, factors, args.out, args.seconds, args.max_raw, args.max_turns,
                            args.model, args.effort, args.codex,
                            scb_check=args.scb_check, scb_seconds=args.scb_seconds)
        elif args.command == "doctor":
            provider = Codex(args.repo.resolve(strict=True), args.out, "gpt-5.5", "xhigh", time.monotonic()+30, 1, 1, args.codex)
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
                value = [{"path": str(p), "status": (r := read(p))["status"], "factors": r["factors"],
                          "usage": r["usage"], "scb_check": r.get("scb_check"),
                          "error": r.get("error")} for p in args.results]
        print(json.dumps(value, indent=2))
        return 1 if isinstance(value, dict) and value.get("status") == "failed" else 0
    except (OSError, ValueError, RuntimeError, Fatal) as exc:
        print(f"agent-behavior-lab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
