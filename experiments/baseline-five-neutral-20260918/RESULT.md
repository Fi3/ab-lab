# Three completed neutral-format baseline workflows

All three requested workflows finish in parallel with complete usage records,
three reviewed features, three final commits, clean source, and passing
formatting, strict Clippy and all-target/all-feature repository tests.
The separate external feature checks pass 1/3, 2/3 and 3/3 respectively.

The exact settings are C13, C14, C15, C20 and C38 ON; C08, C16, C17 and C25 OFF.
These enable focused implementation checks, related code/test grouping, optional
pre-implementation failing-test demonstration, result-based action guidance and
finishing guidance. The agent executes edits, tests and commits through its own
tools. C16 contributes no edit-format instruction. Compact host updates and
host-request interruption do not operate on this native-tools path.

## Results

Raw tokens are input plus output, including cached input once. Child verification
usage is included once; it is not an extra amount to add to the table's totals.
No usage is missing and none of the workflows reaches its safety limits.

| Run | Total raw tokens | Included child tokens | Duration | External feature checks |
| --- | ---: | ---: | ---: | --- |
| baseline-01 | 29,650,393 | 100,736 | 67m 35.77s | 1/3: slash commands pass; visual status and completion question fail |
| baseline-02 | 39,059,021 | 104,790 | 75m 1.94s | 2/3: visual status and slash commands pass; completion question fails |
| baseline-03 | 36,296,420 | 91,871 | 76m 54.71s | 3/3 pass |

**Mean: 35,001,944.67 raw tokens per completed workflow.**
Total batch expenditure: **105,005,834 raw tokens**.
All three start at 2026-09-18 12:15:18 UTC. They finish at 13:22:54, 13:30:20
and 13:32:13 UTC. There are no failed, replaced or resumed observations in this
batch; earlier failed batches retain their original outcomes.

## Comparison with the saved all-on runs

The three saved executions with every switch enabled used 25,673,000,
22,490,575 and 26,119,875 raw tokens: **24,761,150 on average**. Relative to the
new three-run baseline mean, their observed difference is:

`100 * (35,001,944.67 - 24,761,150) / 35,001,944.67 = 29.2577877149%`.

Thus the saved all-on mean is **29.26% lower**, not approximately 50% against
this baseline. The denominator is the mean of all three completed new workflows;
no result is omitted because its tokens or feature score are unfavorable.

This is a descriptive comparison, not a qualified isolated three-versus-three
causal estimate. The saved all-on group retains one initial final-test failure;
its other two workflows pass 2/3 external feature checks. Execution ownership
and permissions, earlier runner source, effective configuration, time allowances
and execution dates differ. The failed saved all-on test passes a later
unchanged-source diagnostic, but its original result is not relabeled.
No old all-on workflow is repeated. This batch does not assign the remaining
difference to a specific switch or settle the older Work Leaf causal study.

The previous five-policy batch's sole completed run used 55,659,262 raw tokens
with a forced Git-diff instruction. The new mean is 37.11% lower than that one
old observation. This is not an isolated C16 effect estimate: it is one old
completed run versus three new ones with different effective configuration and
date. Old partial/failed runs are not pooled as completed totals.

## Editing behavior and the neutral-OFF repair

The admitted author policy differs from the previous five-policy policy only
by the absence of C16's instruction to use Git-style patches. All other author
policy text matches exactly. Current source and configuration are separately
pinned in the prospective freeze.

| Run | Native patch operations | Commands containing git apply | Failed such commands | Corrupt Git-patch errors |
| --- | ---: | ---: | ---: | ---: |
| baseline-01 | 52 | 3 | 0 | 0 |
| baseline-02 | 65 | 0 | 0 | 0 |
| baseline-03 | 51 | 12 | 0 | 0 |

These count completed tool records and command executions, not unique proposed
changes. The agent may choose Git commands itself; neutral OFF does not ban
them. Zero corrupt Git-patch errors does not claim that every native edit or
test succeeds. The earlier completed five-policy run had 27 explicit corrupt
Git-patch errors. The saved traces establish different editing behavior, not
an exact number of tokens attributable to that difference.

## External checks and evidence integrity

The original scorer and byte-pinned fixtures run without agent generation in
separate final-source clones. Original results stay clean and unchanged. All
three score builds succeed; failures are behavioral assertions, not compilation:

- Run 1: `quality_visual.rs:26` does not find the expected left-pane
  character-selection status.
- Runs 1 and 2: `quality_completion.rs:23` does not find the expected completion
  question in the rendered screen. Later assertions in that test are not reached.
- Run 3: all three external tests pass.

The independent audit reconciles parent transport, native histories and child
usage exactly for all three workflows, with no accounting errors. All frozen
model/authentication identities, source hashes, factors, input commit and limits
match. The nine pinned earlier result hashes remain unchanged. No runner code,
permission, prompt or safety-limit change occurs during execution.

All 84 local tests pass before admission. Generation uses the existing ChatGPT
subscription only. The user's post-launch twenty-minute manual-check instruction
governs supervision; the original protocol and its hash are preserved alongside
that direction. Background snapshots remain in the observer log. The final
manual check sees all three already finished; the terminal snapshot time is
13:32:19 UTC, not a claim that the manual inspection occurred then.

All model, observer, scoring and audit processes have finished. This batch changes
only operator records and makes no normal Work Leaf or agent-facing implementation
change. No subsequent benchmark wave is selected.

[Machine-readable summary](SUMMARY.json) · [Prospective protocol](PROTOCOL.md) ·
[Input freeze](FREEZE.json) · [Twenty-minute direction](MONITORING-DIRECTION.md) ·
[Accounting audit](../../runs/baseline-five-neutral-20260918/accounting-final.json) ·
[Feature scores](../../runs/baseline-five-neutral-20260918/feature-scores) ·
[Live/history note](../../ephemeral-note.md).
