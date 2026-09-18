# Code-quality measurements

`scb-check` is an external, local source-code analyzer. Each command-line
benchmark run records its results before work begins, after all feature
implementation/review/repair cycles, and after final assembly. It requires no
model, network request or API credit while measuring source.

The author/reviewer loop and final integration prompts stay unchanged. Scores
are observations for the operator, not advice or extra tasks for the agents.
The middle checkpoint is once for the whole feature set, not after every edit
or individual feature. Final assembly includes integration's documentation and
repairs. Its measurement runs before the runner's independent final checks, so
a later failing test does not discard the quality report of that assembled code.

## Installation and command

The runner requires Python 3.11+. The separately installed checker requires
Python 3.12+; it does not add imports or dependencies to the runner itself.
Using a Python 3.12+ interpreter from the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install scb-check==0.2.0
. .venv/bin/activate
```

The normal `python3 -m lab run ...` command finds `scb-check` on `PATH`.
Alternatively pass `--scb-check /absolute/path/to/scb-check`. Keep the same
installed version and environment for compared runs. Neither `run` nor `plan`
downloads or upgrades anything. `plan` shows the selected executable and stages
without running the checker or a model. `doctor` checks subscription setup only.

The host first records `scb-check --version`, then runs the same command inside
the owned benchmark checkout at each clean checkpoint:

```sh
scb-check check . --output-format json
```

The installed checker's directory comes first on the scoring process's `PATH`
so its ast-grep executable is preferred. Ambient `SCB_CHECK_EXTRA_SLOP_RULES`
is removed for these measurements; no undeclared global extra rules are loaded.
Repository configuration and default exclusions remain in force. No score is
sent through the Codex transport or included in model-token totals.

## Understanding the numbers

| JSON field | Simple meaning |
| --- | --- |
| `verbosity` | Fraction of source lines flagged as duplication or supported code-pattern/structural findings |
| `erosion` | Share of weighted function size in functions with cyclomatic complexity above 10; this complexity counts branching paths |
| `cog_erosion` | The corresponding share using cognitive complexity above 10, which also considers how difficult nested control flow is to follow |
| `files_scanned`, `total_loc` | Number of source files and source lines used for the report |

The first three values are fractions from 0 to 1; for example `0.20` means
20%. Smaller means less of the checker-defined property, **not proven better
functionality or less model usage**. Function weighting is complexity multiplied
by the square root of its source-line count. The complete upstream JSON,
including component counts and per-language syntax statistics, is retained.

The checker supports Python, Rust, JavaScript, TypeScript, Zig, Haskell and C++.
Its pattern and structural rules are Python-only; other supported languages
participate in duplication and complexity measurements. Directory scans respect
`.gitignore` and supported repository configuration. These are whole-checkout
metrics, including discoverable tests, not scores of only the changed lines.
An unsupported repository or other checker error is not silently scored as zero.
The [upstream documentation](https://github.com/gabeorlanski/scb-check#readme)
defines the current metrics and discovery rules.

## Saved output and errors

`run` prints the final result; `report` exposes the same `scb_check` object.
The object records the tool identity and these named measurements:

```text
scb_check.measurements.before_changes
scb_check.measurements.after_implementation
scb_check.measurements.after_assembly
```

Each contains its status, timestamp, commit, source-tree ID, exact command,
exit code, duration, `findings_present`, and full `report`. Detailed artifacts
live beside the agent records, outside the measured checkout:

```text
RUN/scb-check/tool/                         version command and identity
RUN/scb-check/before_changes/               stdout.json, stderr.txt, result.json
RUN/scb-check/after_implementation/         stdout.json, stderr.txt, result.json
RUN/scb-check/after_assembly/               stdout.json, stderr.txt, result.json
```

Exit codes 0 and 1 both represent a completed measurement: 1 means findings
were reported. Other exit codes, missing/invalid metrics, timeout or cancellation
produce an `error` measurement and stop the workflow. Stages not reached stay
`not_run`. Earlier measurements and the failing command's raw output remain
available. The runner checks that tracked source, untracked source, index and
current commit have not changed during a scan. This is a mutation guard, not
an operating-system security sandbox; only use trusted checker executables.

`--scb-seconds` defaults to 300 per scan. The scan also consumes wall time within
`--seconds`, the overall workflow allowance. These host-only seconds and the
checker output do not consume model tokens. The initial successful measurement
is required before a provider is started; a late measurement error stops further
generation and preserves usage already incurred.

The checker settings and identity are part of the comparison key, so scored and
unscored workflows cannot silently form a matched token comparison. Existing
results without scores remain unchanged and show `scb_check: null` in `report`.
Explicit saved-author continuation retains the original before-changes result
and checks the tool identity; it never labels already-implemented source as the
untouched starting point. It does not repeat the completed author.

For Python callers, the backward-compatible `lab.workflow.run` function enables
the same three measurements with `scb_check="/path/to/scb-check"`; omitting that
keyword retains the older unscored library behavior. The CLI always supplies it.
