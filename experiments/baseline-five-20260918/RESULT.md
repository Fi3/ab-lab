# Five-policy native baseline results

Three workflows ran concurrently with **C13, C14, C15, C20 and C38 on** and
**C08, C16, C17 and C25 off**, exactly as selected. All three attempts have ended.
One completed all implementation, review, integration and repository checks.
Two remain incomplete; there is no complete three-baseline comparison.
No all-on workflow or failed baseline was repeated.

## Outcomes

Raw tokens are input plus output, including cached input once. Child verification
conversations are included once; reasoning and cache are not added again.

| Run | Observed raw tokens | Active duration | Outcome | External feature checks |
| --- | ---: | ---: | --- | --- |
| baseline-01 | 40,983,813 plus unknown usage | 61m 53.86s | Stopped after second-feature implementation: two child verification turns lack complete usage records | Not scored: workflow incomplete |
| baseline-02 | 55,659,262 | 101m 16.71s | Completed; formatting, strict Clippy and all-target/all-feature tests passed | 1/3: slash-command check passed; visual-status and visible-closure checks failed |
| baseline-03 | 60,125,802 observed | 104m 32.36s | All three features reviewed; final integration stopped at the 60M observed-token limit | Not scored: workflow incomplete |

Total expenditure is **156,768,877 observed raw tokens**, plus baseline-01's
unknown usage. This is not the cost of three completed workflows. No workflow
reached the four-hour time ceiling.

### Run 1: missing nested verification records

All five parent turns have usage covering their returned messages. Two child
turns created during real-terminal verification lack completion and final usage.
The author's verification scripts explicitly shut down their process groups;
the saved child histories remain unfinished afterward. One ends after a new
turn-start record; the other has no first response price. No process remains
in this checkout, and the independent audit finds no later price to recover.
Missing usage is not treated as zero.

The first feature passed review. The second author committed its work, but the
runner stopped before that feature's review. The clean source remains at
`88b92eb54260ecd8bd13af89b6d709260a1d447f`. This is not a time or subscription limit.

### Run 3: token ceiling during final integration

All three features passed review. During final integration, observed usage
crossed the operator-selected **60,000,000 raw-token ceiling**. The count
overshoots by 125,802 because an in-flight response is reported in increments.
The four-hour time allocation was not exhausted. This is a runner limit, not
a ChatGPT subscription limit.

The interrupted turn has usage after its last delivered message. The independent
audit finds no native/transport discrepancy or missing final-message price.
The runner retains an incomplete-turn flag because the work did not finish;
that flag is not the same as run 1's missing child charges.

Partial integration source remains at
`65eff5b9a3f216bc0c8ab1cda79bd5c6a9b7d217`, with uncommitted changes in
`src/http_controller.rs`, `tests/http_orchestrator.rs`, `tests/start_script.rs`
and `tests/terminal_pty.rs`. It is not reset, externally repaired or scored as
a finished workflow. Native local-server restrictions produced actual validation
and repair work before the stop.

## Comparison with the saved all-on runs

The saved all-on executions used 25,673,000, 22,490,575 and 26,119,875 raw tokens:
**24,761,150 on average**. Against the **one completed new baseline** at 55,659,262,
that mean is **55.5129746420% lower**:

`100 * (55,659,262 - 24,761,150) / 55,659,262`.

This is descriptive: three saved all-on executions versus one completed new
baseline. It is **not a complete three-versus-three estimate**, a quality-matched
result or an isolated saving assigned to a switch. Failed attempts are retained,
not averaged as completed workflows. A 50% target did not select the results.

The saved all-on qualifications remain: on-02 failed its initial final test;
on-01 and on-03 passed repository checks but scored 2/3 externally. The completed
new baseline scores 1/3. Native commands retain restrictions that host commands
do not share. Source before the native-completion parser repair, time allowances
and execution dates also differ. Comparison keys are not rewritten to hide these
differences.

## Observed editing overhead

**C16 off does not mean freedom to choose an editing tool.** It asks the native
author to submit standard unified diffs through `git apply`.

| Run | Nonzero-exit commands containing `git apply` | Explicit corrupt-patch errors | Explicit patch-matching errors |
| --- | ---: | ---: | ---: |
| baseline-01 | 79 | 57 | 22 |
| baseline-02 | 31 | 27 | 1 |
| baseline-03 | 62 | 56 | 4 |

The first column counts command executions, not necessarily unique rejected
proposals. Other failures explain why the other columns need not sum to it.
Saved messages repeatedly correct hunk line counts and split changes into
smaller patches. This is concrete extra work in the selected baseline, but this
batch does not measure its independent token cost. Do not assign the 55.51%
descriptive gap to C16 or another individual switch.

## Feature scoring and verification

The original scorer and three byte-pinned fixtures are unchanged. Separate
final-source clones are scored without model calls or score-driven repairs.
Run 2 compiles successfully under the fixtures; its failures are assertions:

- `quality_visual.rs:26`: expected left-pane character-selection status absent.
- `quality_completion.rs:41`: expected visible closure after answering yes absent.
- The slash-command/status check passes.

All 70 local tests passed before launch. The non-generating readback confirmed
ChatGPT authentication, Codex 0.154.0 and GPT-5.5/xhigh. All three admitted factor
vectors, source pins, base commits, model identities, configurations and limits
match [FREEZE.json](FREEZE.json). The accounting audit reproduces every observed
total, including child costs; it qualifies only run 2 as a complete workflow.
All saved earlier reference-result hashes remain intact.

Model execution, observation, scoring and audits have ended. No generated pilot,
replacement, continuation, all-on repeat or normal Work Leaf source change is
part of this batch. Only supervising experiment records are edited in the lab
repo; all lab implementation hashes remain frozen. The user's later request for
less frequent checks governs monitoring: manual checks were about ten minutes
apart, with background snapshots every 15 seconds. No measured instruction or
workflow limit changed with that supervisor cadence.

[Machine-readable summary](SUMMARY.json) · [Protocol](PROTOCOL.md) ·
[Raw audit](../../runs/baseline-five-20260918/accounting-final.json) ·
[Feature scores](../../runs/baseline-five-20260918/feature-scores/baseline-02/result.json) ·
[Operational note](../../ephemeral-note.md).
