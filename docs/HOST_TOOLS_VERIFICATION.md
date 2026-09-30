# Host tools verification — 2026-09-30

This report describes the earlier stop-and-continue policy. Its completed
executions included unfinished reviews and do not verify approval of all five
features. The current runner requires review approval before advancing and
uses whole-run safety limits by default; see README.md for current behavior.

Workflow: `host-tools-upstream-prompts-v1`. This replaces the printed command
protocol; there is no alternate legacy execution path. Eight factors remain;
C25 is retired because its printed-request interruption boundary no longer exists.

## Reproduction and repair

The saved p012-9 patch ended in a normal trailing newline after `*** End Patch`.
The old parser rejected that newline. The later declared `touch requirements.txt`
request created the file, then the old host aborted because its untracked-file list
had changed. Both failures were reproduced before replacing the protocol.

The same patch and command now succeed, leave committed source, and return
recorded results. Replaying a completed tool call returns its saved result without
executing the operation again. An interrupted call without a completion receipt
stops with its actual effects retained.

Evidence (ignored run artifacts):

- `runs/runner-tools-verification-20260929/before-reproduction.json`
- `runs/runner-tools-verification-20260929/after-reproduction.json`
- The sibling host journals preserve exact requests, results, and source changes.

## Validation

The final complete suite passed **421 tests**, including cancellation-accounting
coverage. Its log is
`runs/runner-tools-verification-20260929/final-unit-suite-03.log`.

Host tests exercise new/deleted files, executable modes, partial changes after
nonzero exits and timeouts, duplicate delivery, conflicting call identities,
interruption after effects, and Git custody. Adapter tests exercise tool ownership,
actual Node pipe transport, failed-tool feedback, natural empty completion,
work-limit settlement, and missing usage. Workflow tests cover external review
limits, separate provider/evaluator failures, continued SCB snapshots, and shutdown
failure without exposing evaluation to a still-running provider.

Both live three-tool probes passed with GPT-5.5 and complete accounting:

| Harness | Observed raw tokens | Artifact |
| --- | ---: | --- |
| Codex | 47,030 | `runs/host-tools-verification-20260929/codex-02/result.json` |
| Pi | 6,707 | `runs/host-tools-verification-20260929/pi-03/result.json` |

Pi's first live probe found that its explicit tool allowlist omitted the registered
host tools. The allowlist now includes them, with regression coverage. Initial
probes also exposed restrictions imposed by the enclosing development sandbox;
verification subsequently ran with full access while testing the runner's own
sandbox permissions.

## Full benchmark verification

The first full-run pair reached checkpoint 3 but was deliberately interrupted
after its tool receipts exposed another valid-input rejection: an empty new
file in a mixed structured patch. Both agents recovered, but the runner should
have accepted the original patches. These interrupted runs are retained as
`codex-full` and `pi-full`; they are not successful full-run evidence.

Both exact rejected patches now succeed without modification, creating an empty
`requirements.txt` alongside implementation and tests in one commit. Regression
tests also distinguish empty files from a blank line and cover insertion into a
newly empty file. Before/after evidence is in
`runs/runner-tools-verification-20260929/empty-file-reproduction.json`.

The second pair is retained as `codex-full-02` and `pi-full-02`. Pi stopped during
checkpoint 3 review when a token-limit interruption left accounting incomplete.
Codex was interrupted during checkpoint 4 while a final audit removed obsolete
single-line edit-reason validation. This pair also does not establish complete
execution.

The Pi failure was reproduced at the boundary between review time and token
limits. After a fully priced response, the installed SDK emitted an empty local
cancellation message before dispatching another model request. That message
incorrectly invalidated usage coverage. The runner now intercepts requests
already cancelled before preparation, journals durable proof outside agent
writable paths, and recognizes only the matching synthetic message lifecycle.
Actual unpriced responses and historical aborts without proof remain incomplete.

An installed-Pi probe exercised the same time-limit-to-token-limit transition
and passed with **1,327 observed raw tokens**, matching independent native session
totals. It also verified journal write protection. Evidence:
`runs/runner-tools-verification-20260929/pi-cancellation-probe-01/result.json`.

Full five-checkpoint code_search verification uses
GPT-5.5, xhigh effort, all eight active factors, P0/P1/P2 reviews, and preserved
history. Each run has the default external checkpoint limits and an overall
14,400-second / 25,000,000 observed-raw-token / 100-turn safety limit.

The final pair, `codex-full-03` and `pi-full-03`, completed all five checkpoint
attempts, final integration, all five independent checkpoint evaluations, and
the independent final evaluation. Both have `execution_status: completed`,
`slopcodebench.status: completed`, and `usage.measurement_complete: true`.
Neither recorded a terminal execution failure, shutdown error, evaluator
infrastructure failure, missing usage turn, or pending owned child process.

| Result | Codex / GPT-5.5 | Pi / GPT-5.5 |
| --- | ---: | ---: |
| Checkpoint 1 tests | 13/13 | 13/13 |
| Checkpoint 2 tests | 25/25 | 25/25 |
| Checkpoint 3 tests | 46/47 | 46/47 |
| Checkpoint 4 tests | 74/75 | 73/75 |
| Checkpoint 5 tests | 102/104 | 100/104 |
| Final assembled tests | 102/104 | 100/104 |
| Observed raw tokens | 8,807,814 | 8,023,508 |
| Cached input tokens (included in raw) | 7,978,880 | 7,241,216 |
| Duration | 3,711.41 seconds | 3,848.68 seconds |
| Overall workflow status | `needs_attention` | `needs_attention` |

These are complete experiments, **not fully passing benchmark solutions**.
Only checkpoints 1 and 2 passed all authoritative tests and received review
approval. Codex reviews reached the token limit at checkpoints 3–5. Pi's
checkpoint 3 review reached the time limit, and its checkpoint 4–5 reviews
reached the token limit. Those reviews remain incomplete; the runner did not
convert a limit stop into approval. Both results retain `solved: false` and
`all_tests_passed: false`.

The final evaluator failures were:

- Both harnesses: `test_optional_metavar` (empty optional capture emits
  `captures: {}` where the expected object omits it), and
  `test_go_struct_and_interface` (matched declarations omit the leading
  `type` and name).
- Pi additionally: `test_ordering_match_before_fix` (missing match/fix for an
  indented standalone return), and `test_java_class_method_patterns`
  (class match omits `public`).

These were assertion mismatches with submission exit code 0. Exact failures
are retained in each run's `slopcodebench/evaluation/final/details/evaluation/`
`report.json`; the runner did not feed these hidden evaluation results back to
the agents. Both final checkouts were clean, and the authoritative test
collection hashes matched across harnesses at every checkpoint and final grade.

The configured final command passed for both runs. The separate `scb-check`
measurements completed after implementation and after assembly, reporting
quality findings (exit 1); those findings are not evaluator infrastructure
errors or proof of benchmark correctness.

The current runner source hashes and both final manifests match
`runs/runner-tools-verification-20260929/admission-03.json`. The model, effort,
factors, limits, and runner implementation were held fixed across the pair;
the harness differed. One pair does not establish a general harness advantage,
and these runs do not establish a GPT-5.5 versus GPT-5.6 comparison.

Final result artifacts, relative to
`runs/runner-tools-verification-20260929/`:

| Artifact | SHA-256 |
| --- | --- |
| `codex-full-03/result.json` | `bad174ec83c161a7f84e2cdb38381002b0dc135dbe333f5a11a2d6da5199c4cb` |
| `pi-full-03/result.json` | `e73c031cebfc3aa13f7b8e31ca55ef53093c88c73a4c605df61bf082f74077c0` |

Run directories are excluded from the source commit. This compact report
preserves the outcomes and artifact identities without committing generated
source trees, transport logs, or provider sessions.
