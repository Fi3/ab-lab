# Five-policy native baseline: three parallel workflows

## Scope and user direction

The user's final selection is: "no removoe it so it will be: C38 C20 C15 C14 C13",
following the request for three baseline tests in parallel. This admits exactly
three new complete workflows, baseline-01 through baseline-03, in separate
checkouts. It does not admit another all-on wave, replacement observations or
resumption of Work Leaf's closed mechanism investigation. Its old counters and
source remain untouched.

This baseline uses the agent's own editing, command and Git tools. The selected
policies provide focused author validation (C13), grouped related code and tests
(C14), no mandatory pre-implementation failing-test demonstration (C15), guidance
to use actual command results (C20), and guidance to finish when required work
and checks are complete (C38).

All other switches are explicitly off: compact host conflict updates (C08),
structured patch format (C16), host-executed edits/commands/commits (C17), and
host-request interruption (C25). C16 off requests standard unified diffs through
git apply. C25 is inapplicable to this native-tool route; ordinary tool results
remain available. No switch is silently enabled as a dependency.

## Fixed inputs and behavior

- Benchmark: `benchmarks/work-leaf.json`, SHA256
  `beace51ce596f9c5afb6329d0a132e7dddf716b24b47c321b41dcd15c3aa613e`.
- Base source: `c92a0b7060a36eac6db2d869b85e589a7a9480f9`.
- Model and reasoning: GPT-5.5, xhigh; existing ChatGPT subscription only.
  No API credentials, credits, credential copies or alternate login home.
- Three sequential requested features per workflow; each includes implementation,
  independent review, same-author repairs and re-review. Final integration has
  planning, acceptance, exactly one final commit per feature, and all required
  repository checks. No requirement, reviewer or final check is removed.
- `CARGO_BUILD_JOBS=4`. Native permissions and command execution remain unchanged.
  Native network/local-server restrictions are retained and must be reported if
  they cause failures or recovery work. No live prompt, permission or source tuning.
- Program source, effective configuration, exact factor vector, input hashes and
  launch arguments are pinned in `FREEZE.json` before generation.

Existing verification covers real native completion, same-conversation repairs,
nested subscription usage and a completed native full workflow. This task changes
only existing supported switches and the time allocation; no new agent-facing
implementation is required. Re-run local tests and a non-generating subscription
configuration check before launching. Do not spend an extra generated pilot on
an unchanged, already exercised execution path.

## Prospective limits and monitoring

Each workflow has a four-hour (14,400-second) safety limit, a 60,000,000
observed-raw-token limit and a 600-parent-turn limit. The operator selects the
larger time allowance because the user rejected the preceding 90-minute limit
as too short; four hours is not a number the user explicitly specified. These
are maximum allocations, not targets. Stop immediately on ordinary completion.
An in-flight response can exceed an observed-token threshold. Record usage
coverage and any unknown cancellation tail; do not estimate it as zero.

Run all three workflows concurrently. Observe at 15-second intervals, inspect
progress at least once per minute, and maintain the current table and dated
activity in root `ephemeral-note.md`. Keep original raw records, failures, partial
source, reviews, child-agent costs and final integration costs. A failure of one
attempt does not stop healthy peers unless it demonstrates a shared unsafe
accounting, authentication or source-integrity defect. Do not silently replace
failed observations or restart successful work.

## Endpoint and interpretation

After all three attempts terminate, audit recorded source/configuration and
parent/child usage. Run the unchanged external feature scorer on eligible final
sources without score-driven repairs. Publish all three outcomes, complete
totals where available, missing-usage flags, elapsed times and feature scores.
A failed or partial observation is not a completed benchmark total.

Reuse the three existing all-on outcomes in `runs/on-off-20260918-r4/`; retain
their original failure/score qualifications. Their mean is 24,761,150 observed
raw tokens. If all three new baselines finish with complete accounting, report
their mean and `100 * (mean_baseline - 24,761,150) / mean_baseline` as a descriptive
comparison with those saved all-on executions, not an isolated causal share.
Also retain the individual all-off outcomes, including two unfinished workflows.

The earlier all-on runs differ in execution ownership and permissions as well as
switches, use the earlier source before the native-completion parser repair,
and have a different time ceiling and execution date. Automatic comparison keys
must not be rewritten to hide these differences. A roughly 50% difference is
neither a success criterion nor grounds for tuning or replacement. Finish this
three-workflow batch and report its actual result; no subsequent wave is selected.
