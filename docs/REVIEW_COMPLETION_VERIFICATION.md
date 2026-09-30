# Review completion verification — 2026-09-30

Workflow: `host-tools-review-approval-v2`. Limit policy:
`global-budget-defaults-v5`. Checkpoint policy:
`review-approval-required-v2`.

## Reproduced failure

The preceding verification runs completed all checkpoint attempts, but their
checkpoint 3–5 reviews were interrupted before returning verdicts. Codex hit
the 500,000-token review limit in all three; Pi hit the 300-second limit in
checkpoint 3 and the token limit in checkpoints 4–5. None of those stopped
reviews triggered a repair round. The SCB adapter then advanced to the next
checkpoint and eventually reported completed execution with only two approved
features.

Removing the earlier reviewer conclusion generation had made those thresholds
hard stops. Retaining the old thresholds without validating review completion
was a policy error. Raw tokens include repeated input context, so 500,000 raw
tokens are not 500,000 tokens of new reviewer output. The separate 3-million
feature cap could terminate the same work even without a review cap.

The deterministic reproduction starts a review at 100,000 cumulative raw
tokens and supplies 600,000 cumulative raw tokens. The old default interrupts
with `review_token_limit`. The new default does not interrupt at that boundary,
or at 3.5 million cumulative raw tokens and 600 seconds. Exact inputs and
results are retained in the ignored verification directory's
`stage-limits-before.json` and `stage-limits-after.json`.

## Changed behavior

Default feature/review token and review time caps are `null`. Author and
reviewer work share the explicit whole-run time, token, and turn safety limits.
Stage caps and a fixed repair-attempt cap remain available when deliberately
configured; all are disabled by default. Unchanged-loop guards remain active,
without budget instructions in prompts.

A completed review with blockers triggers author repairs and another review.
Only approval advances the workflow. An unresolved review, exhausted guard,
or explicitly configured stage cap stops it. SCB retains a snapshot of a local
review/loop stop and independently grades it after provider shutdown; later
checkpoints and integration remain unrun. Whole-run or provider stops retain
the checkout and grade previously captured snapshots; an active checkpoint
without a captured snapshot remains ungraded. Neither stop can report
completed execution.

## Automated verification

The final suite passed **434 tests** in 109.878 seconds after removing the
default repair-count cap. Coverage includes:

- A review/repair/approval cycle exceeding both the old review and feature
  token limits under the new defaults.
- Codex and Pi provider event sequences that complete a review at 400 seconds
  and 605,000 raw review tokens without interruption.
- An explicitly configured 500,000-token cutoff that retains the stopped
  attempt and blocks later checkpoints and integration.
- Malformed/incomplete verdicts, unresolved findings, repeated rejection,
  retained dirty work, late accounting, and partial independent grading.
- More than three progressing repair rounds under default settings, with an
  explicitly configured repair-count cap still enforced.

Evidence: `runs/review-completion-verification-20260930/unit-suite-02.log`.

## Live verification

The first pair is retained as `codex-full` and `pi-full`. Codex completed four
checkpoint 3 reviews and three repair rounds, then stopped with one remaining
finding at the default three-repair cap. Its execution is incomplete and its
accounting is complete. This exposed another arbitrary stage cutoff, so the
repair-count default was also removed. Pi was deliberately interrupted during
its fourth checkpoint 3 review to apply the same correction to both harnesses;
its result preserves the operator interruption and incomplete accounting.
Neither attempt is successful full-run evidence.

Fresh Codex and Pi runs use GPT-5.5, xhigh effort, all eight active factors,
P0/P1/P2 review priorities, preserved history, and identical whole-run safety
limits: 21,600 seconds, 50,000,000 raw tokens, and 250 turns. Both manifests
match the frozen source hashes and settings in `admission-02.json`.

Pi completed checkpoint 3 reviews 1–11 and repair rounds 1–11. During review
12, the explicit whole-run token limit stopped execution at **50,117,286 raw
tokens**, including **48,578,048 cached input tokens**, after **6,363.899
seconds**. Accounting is complete. The result correctly reports failed,
incomplete execution with only checkpoints 1–2 approved; checkpoints 4–5 and
integration did not run. This is not successful full-run evidence.

A read-only audit of recent review prompts, verdicts, and existing tool
receipts found concrete violations of the original structural-matching
requirements, rather than added runner obligations. Both generated solutions
use hand-written token heuristics; earlier repairs worked while later probes
revealed additional capture and grammar errors. No evaluation tests were
provided to the agents or used for these repairs.

Codex recorded checkpoint 3 review verdicts 1–22 and completed repair rounds
1–22. Review 23 also completed and returned `NO_FINDINGS`, but its final token
receipt crossed the explicit whole-run limit. The runner rejected the turn
before accepting that verdict and stopped execution at
**50,015,616 raw tokens**, including **44,618,496 cached input tokens**, after
**11,646.918 seconds**. Accounting is complete. It also reports failed,
incomplete execution with only checkpoints 1–2 approved. The completed,
unaccepted verdict is retained in `provider/turn-0060/reply.txt`; it is not a
recorded checkpoint approval. Compaction turns are accounted separately and
do not count as additional repair rounds.

| Full run | Approved checkpoints | Accepted checkpoint 3 verdicts | Completed checkpoint 3 repairs | Stop |
| --- | ---: | ---: | ---: | --- |
| `codex-full-02` | 2/5 | 22 | 22 | Whole-run token limit at completed review 23; `NO_FINDINGS` unaccepted |
| `pi-full-02` | 2/5 | 11 | 11 | Whole-run token limit during review 12 |

Both independently passed the captured checkpoint 1 and 2 snapshots (13/13
and 25/25 tests respectively). Checkpoint 3 was not captured at the global
stop and is ungraded; checkpoints 4–5 and final assembly did not run. The live
checkouts and provider/host receipts retain checkpoint 3 work. **Neither full
run passed or completed all five checkpoints.** These attempts demonstrate
that reviews and repairs proceed beyond the old local caps and that global
stops cannot masquerade as completion; they do not demonstrate that GPT-5.5
can solve this benchmark under the selected conditions and run budget.

Results belong under
`runs/review-completion-verification-20260930/{codex-full-02,pi-full-02}/`.
Generated run directories are not part of the source commit.

## End-to-end fixture

The existing `benchmarks/scb-code-search-smoke.json` fixture contains only the
first checkpoint. It was run separately on both harnesses with the same frozen
source, model, factors, priorities, and history policy, under explicit limits
of 1,800 seconds, 5,000,000 raw tokens, and 40 turns (`admission-smoke.json`).

| Run | Execution | Review | Independent tests | Raw tokens | Seconds |
| --- | --- | --- | --- | ---: | ---: |
| `codex-smoke-02` | Completed, passed | Approved | 13/13 | 609,507 | 638.113 |
| `pi-smoke-02` | Completed, passed | Approved | 13/13 | 253,569 | 602.144 |

Both completed integration, final checks, and quality measurements with
complete token accounting. Their manifests match the admitted source and
policy. These establish that the runner's successful completion path works
on both harnesses; they are not evidence of a five-checkpoint benchmark pass.
