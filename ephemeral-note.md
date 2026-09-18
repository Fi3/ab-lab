# Benchmark attempts ended: 15 | Full workflows passing repository checks: 3

Current repair: **3 / 3 obligations verified**. Original comparison attempts: **6 / 6 started; 6 / 6 ended**. Saved-work continuations: **3 / 3 started; 3 / 3 ended; 0 running**.
The user authorizes repairs and completion of the requested comparison; reuse any
valid complete observation. The earlier third batch had no complete all-on
observation; the current fourth batch has two passes and one final-check failure.
[Current authority](experiments/on-off-20260918-r4/AUTHORITY.md).

Last updated: 2026-09-18 02:31 UTC.
Current activity: all model execution, observation, feature scoring and audits
have ended. No model or compiler is running. The requested complete three-versus-three
validation is **NOT ACHIEVED**: off-01/off-02 retain time-limit failures.
No first author or all-on result is regenerated. The exact outcome and remaining
evidence requirements are in [RESULT.md](experiments/on-off-20260918-r4/RESULT.md).
**Valid three-versus-three reduction: NOT AVAILABLE.** Descriptive comparison
only: the three all-on executions average **24.761M**, versus **42.177M** for the
one complete all-off workflow, a **41.29%** difference using that single off run
as denominator. This is not the requested complete comparison or a 50% proof.
**External feature checks:** on-01 **2/3**, on-03 **2/3**, off-03 **3/3**;
failed/unfinished workflows are not scored. On-02's failed terminal assertion
and full suite pass once on unchanged source; its original failure remains.
[Current protocol](experiments/on-off-20260918-r4/PROTOCOL.md) ·
[Current qualification](experiments/on-off-20260918-r4/QUALIFICATION.md) ·
[15-second continuation snapshot](runs/on-off-20260918-r4/continuation-monitor/current.json).

<!-- continuation-live-table -->
| Saved-work continuation | Current stage / outcome | Cumulative raw tokens | Runner incomplete-turn flags |
| --- | --- | ---: | ---: |
| off-01-continued | failed: workflow wall-time/observed-token limit reached | 40,043,900 | 1 |
| off-02-continued | failed: workflow wall-time/observed-token limit reached | 37,167,934 | 2 |
| off-03-continued | passed | 42,177,372 | 0 |
<!-- continuation-live-table-end -->

Off-01's single flag denotes its interrupted, unfinished planning turn; the
independent audit finds its delivered output priced. Off-02's two flags describe
one interrupted response with a genuinely missing final price, not two missing
responses. Earlier and resumed costs appear once in the cumulative totals.

Original terminal records before continuation (unchanged):

<!-- r4-live-table -->
| Current run | Switches | Stage / outcome | Observed raw tokens | Missing returned counts |
| --- | --- | --- | ---: | ---: |
| on-01 | All on | passed | 25,673,000 | 0 |
| on-02 | All on | failed: final check 3 failed; no automatic replacement | 22,490,575 | 0 |
| on-03 | All on | passed | 26,119,875 | 0 |
| off-01 | All off | failed: native author did not supply the stage-completion marker | 12,819,166 | 0 |
| off-02 | All off | failed: native author did not supply the stage-completion marker | 16,049,406 | 0 |
| off-03 | All off | failed: native author did not supply the stage-completion marker | 13,824,449 | 0 |
<!-- r4-live-table-end -->

Owned runner PID / tool session: on-01 **1429754 / 66262**, on-02
**1429773 / 30295**, on-03 **1429767 / 45701**. Observer **1429720 / 31103**.
Launch: 2026-09-17 22:47:56 UTC; observer began one second earlier.
Frozen implementation commit: `3f54c08`. No program changes during the batch.
All-on runner sessions are closed. All-off launch: **2026-09-18 00:08:08 UTC**.
Original runner PID / tool session: off-01 **1554844 / 16418**, off-02
**1554830 / 90896**, off-03 **1554857 / 29317**. These runner and observer sessions
are closed. Continuations have separate artifacts and monitoring.
Continuation launch: **2026-09-18 01:12:49 UTC**, implementation **196b660**.
Tool sessions: off-01 **97433**, off-02 **72012**, off-03 **59084**;
15-second observer **91069**. All configuration-equivalence guards pass before
generation. Source checkpoints, history bundles and prior native logs are saved.
Owned PIDs: off-01 **1643075**, off-02 **1643092**, off-03 **1643085**;
observer **1643053**.

## Previous third batch — retained failed observations

Previous batch: **3 / 6 ended**; **0 passed**, **3 failed/stopped**, **0 running**.
The three all-off attempts are unstarted after a shared token-accounting defect.
All prior batches and this batch remain retained; there are no automatic replacements.

The real Git-rewrite check passed. The full comparison failed a different path:
a nested Codex command generated 167,250 raw tokens absent from the runner's own total, using GPT-6 Astra/max instead of GPT-5.5/xhigh.
Run 2 also completed its second-feature stage without making the required commit.
Runs 1 and 3 were stopped under the frozen shared-accounting-failure rule.
Their last cancellation tails remain incomplete; prior returned turns have no coverage gap.
Measured on-versus-off reduction: NOT AVAILABLE. Roughly 50% is not established by this batch.
[Previous protocol](experiments/on-off-20260917-r3/PROTOCOL.md) · [Real-agent qualification](experiments/on-off-20260917-r3/QUALIFICATION.md).

| Previous run | All nine switches | Outcome | Runner-observed raw tokens | Incomplete returned counts |
| --- | --- | --- | ---: | ---: |
| on-01 | On | Stopped during second-feature review after shared accounting defect | 9,950,855 | 1 cancellation |
| on-02 | On | Failed: second-feature completion produced no commit | 5,413,894 | 0 in main provider; nested usage excluded |
| on-03 | On | Stopped during second-feature implementation after shared accounting defect | 5,643,268 | 1 cancellation |
| off-01 | Off | Not started | — | — |
| off-02 | Off | Not started | — | — |
| off-03 | Off | Not started | — | — |

Runner totals sum to 21,008,017 raw. Adding the recovered 167,250 gives 21,175,267 observed raw; two cancellation tails remain unknown. Run 2's corrected observed total is 5,581,144.
[Exact failure and next qualification](experiments/on-off-20260917-r3/RESULT.md).
Final snapshot: [stopped status](runs/on-off-20260917-r3/final-monitor/current.json).
The 15-second history is retained under runs/on-off-20260917-r3/monitor/.
This separate tool validation does not change Work Leaf's old research counter.

## Previous replacement batch — retained failed observations

<!-- replacement-live-table -->
| Replacement run | Switches | State | Observed raw tokens | Missing response counts |
| --- | --- | --- | --- | --- |
| on-01 | On | Failed: final Git-history rewrite denied | 18,364,740 | 0 |
| on-02 | On | Stopped after shared failure; feature 3 repair | 19,452,278 (partial) | 1 cancellation |
| on-03 | On | Failed: final Git-history rewrite denied | 19,340,267 | 0 |
| off-01 | Off | Not started: shared Git-permission failure | — | 0 |
| off-02 | Off | Not started: shared Git-permission failure | — | 0 |
| off-03 | Off | Not started: shared Git-permission failure | — | 0 |
<!-- replacement-live-table-end -->

Retained replacement snapshots: [saved status](runs/on-off-20260917-r2/monitor/current.json),
with the full history in `runs/on-off-20260917-r2/monitor/samples.jsonl`.
That batch's observer and generators are stopped. Failed totals are not completed-benchmark totals.

## Previous batch — retained failed observations

[First protocol](experiments/on-off-20260917/PROTOCOL.md).

| Run | All nine switches | State | Observed raw tokens |
| --- | --- | --- | --- |
| on-01 | On | Finished; failed (Feature 3: completion prompt / review 1) | 14,911,977 (partial) |
| on-02 | On | Finished; failed (Feature 3: completion prompt / repair 1) | 13,932,504 (partial) |
| on-03 | On | Finished; failed (Feature 3: completion prompt / implementation) | 12,962,583 (partial) |
| off-01 | Off | Not started: accounting failure in first group | — |
| off-02 | Off | Not started: accounting failure in first group | — |
| off-03 | Off | Not started: accounting failure in first group | — |

Finished counts terminal attempts, including failures—not successful, fully measured
benchmarks. All checkouts and outcomes are retained; no automatic replacement.
Raw tokens are input plus output, with cached input included only once.

[Saved status](runs/on-off-20260917/monitor-current.json) and the complete
30-second sample history remain in runs/on-off-20260917/monitor-samples.jsonl.
That previous observer is stopped; the replacement observer is separate.

## Activity log, with earlier entries retained

- 2026-09-18 02:21–02:31 UTC: the final six-record audit reproduces every
  observed total and all saved source/configuration links. It identifies only
  off-02's missing final response price. The unchanged external scorer returns
  2/3 for on-01, 2/3 for on-03 and 3/3 for off-03; other records remain explicitly
  not scored. On-01 fails to show the completion question; on-03 fails the
  visible-closure check. On-02's original failed terminal assertion and full
  suite both pass in the single unchanged-source diagnostic, without model
  generation. All 70 local tests, compilation, program/input hashes and whitespace
  checks pass. RESULT.md and SUMMARY.json retain the exact incomplete-comparison
  conclusion, descriptive denominator, network/recovery limitations and all
  earlier failures. No replacement, extra model turn or source repair follows
  scoring. All-owned-process checks show no remaining benchmark or scorer.

- 2026-09-18 02:19–02:20 UTC: off-03 passes all feature/review/integration
  stages and final checks at 42,177,372 raw, including 118,492 child tokens.
  Off-01 reaches its original active-time limit during integration planning
  at 40,043,900 observed raw. Its last delivered message has a later price,
  but the interrupted stage is incomplete and the runner conservatively marks
  the turn incomplete. Off-02's earlier 37,167,934 remains incomplete with a
  genuine missing post-message price. All generator and observer sessions close.
  Start the unchanged feature scorer on all six records (failed workflows retain
  its explicit not-scored result), the complete audit and the original-source
  on-02 diagnostic. No new model observation or budget extension is launched.

- 2026-09-18 02:02 UTC: off-02 reaches its original 5,400-second active
  limit while implementing the final feature. It retains two approved feature
  checkpoints and unfinished changes in three source files. Observed usage is
  37,167,934 raw, including 52,391 child tokens. Two diagnostic flags refer to
  one interrupted parent turn: the final message lacks a later fresh price,
  and the turn failed at its limit. This is not a complete workflow total.
  Its original and continued records remain unchanged; no replacement or
  extra model call is launched. Off-03 has reached final-feature review;
  off-01 continues implementation. The per-run time stop does not stop peers.

- 2026-09-18 01:52 UTC: all three workflows pass slash-routing review
  and start the third/final feature. Run 1's native author first reports its
  successful real-backend smoke in its reply, but native repair feedback sends
  only a generic completion sentence to the reviewer. The next review asks
  for durable evidence; the author records that smoke in an empty commit
  message and the following review accepts it. Both exchanges and all checks
  stay counted. This saved behavior is visible in continuation turns 9–12;
  no prompt or feedback format is changed during the admitted comparison.

- 2026-09-18 01:48 UTC: run 3 passes slash-routing review and begins
  the final review-completion feature. Run 1's reviewer requests actual backend
  routing verification; its additional child calls finish and are fully counted.
  Run 2 remains in slash-routing implementation. Complete cumulative totals
  are 25,314,091 / 30,446,728 / 28,183,096 raw; no source/configuration override,
  unknown completed price or replacement occurs.

- 2026-09-18 01:37 UTC: all three saved first-feature implementations
  pass independent review after their recorded repairs. All three workflows
  proceed to slash-command routing. Cumulative totals are 20,504,542 /
  24,962,476 / 23,515,067 raw, including all original work and child checks.
  No returned-response gap, model mismatch or program-source change appears.

- 2026-09-18 01:30 UTC: all three saved workflows remain active with
  complete observed accounting. Runs 1/3 are in their third text-selection
  review; run 2 is in its second. The intervening repairs address review
  findings, not a harness failure. Earlier first-author work is retained, and
  all resumed-author and nested-verification costs remain included. The final
  no-model test-diagnostic plan is frozen; it runs only after model generation
  ends and cannot change the original all-on-2 failed result.

- 2026-09-18 01:17–01:18 UTC: all three first-feature reviews request
  repairs from their original authors. Returned token counts remain complete.
  The independent continuation-audit regressions pass after their initial
  missing-helper failures. All three saved-source/result/allocation links pass;
  measured prompt functions are structurally identical across the repair,
  and provider, host, factor configuration, nested launcher and environment
  modules retain their original hashes. No measured program is edited while
  generation runs. The source bundle reconstructs the exact first checkpoint.

- 2026-09-18 01:12:49 UTC: launch the three saved all-off continuations
  concurrently from qualified commit 196b660. All three restore exact earlier
  costs and start independent review; no implementation response is repeated.
  The observer starts one second earlier. Actual configuration hashes and the
  proof of redundant trust metadata match the continuation freeze. Original
  allocation ceilings remain unchanged; no all-on observation is relaunched.

- 2026-09-18 01:04–01:12 UTC: the real resume check passes with 11,270
  earlier + 11,302 additional = 22,572 cumulative raw, matching the independent
  native history exactly. It resumes the original tiny conversation without
  repeating its first response. All 66 local tests, compilation and whitespace
  checks pass. The three saved all-off checkpoints are clean and retain
  4,017.08 / 2,957.92 / 4,013.18 seconds of their original active-time budgets.
  Freeze the qualified repair before simultaneous continuation; no all-on
  generation or first-feature replacement is selected.

- 2026-09-18 00:53–01:02 UTC: the first resume qualification stops after
  its 11,270-token first response and before a second response, because of a
  different configuration hash. Zero-generation probes trace this exactly to
  four new redundant trusted-folder records; subtracting only those records
  in memory reproduces the frozen full-batch hash. Each folder already inherits
  the same trusted status. No model/login/permission change or global config
  edit is made. Seven targeted tests pass, including a strict equivalence guard
  that still rejects other changes. Continue only the remaining planned tiny
  response, keeping the first response, original failure and total budget.

- 2026-09-18 00:49–00:51 UTC: off-02 ends with the same marker defect at
  16,049,406 raw, including 13,094 child tokens. All runner and observer sessions
  close. The independent six-record audit reproduces every total, with no
  accounting/model/source errors. Only after all generation ends, apply the
  parser fix and explicit continuation support. Five fail-first cases pass:
  summary acceptance, malformed markers, saved-boundary rejection, cumulative
  resume usage, and live inclusion of earlier costs. The small real resume
  qualification is prepared but has not started. The original results and
  protocol stay intact; the continuation plan is NATIVE-CONTINUATION.md.

- 2026-09-18 00:31–00:40 UTC: off-01/off-03 stop after their first author
  response at 12,819,166 / 13,824,449 raw, both with complete counts. Both real
  replies end with exactly one standalone `@standalone done` line after a
  normal summary. The prompt defines the marker, but the runner mistakenly
  requires the entire reply to equal it. No independent review runs yet. Two
  local regression cases fail before repair (one reproduced workflow failure,
  one missing parser helper). Off-02 remains active, so only new tests and
  supervising evidence are edited. The proposed next work is parsing repair
  and a verified same-conversation continuation retaining prior costs and
  outcomes, not automatic replacement observations. Continuation is not yet
  implemented, qualified or admitted; no additional model has been launched.

- 2026-09-18 00:30 UTC: saved native command receipts in off-01/off-03
  confirm `Operation not permitted` in local-server Rust checks. The provider's
  native writable policy disables network access; external host commands and
  final host checks run without that restriction. This same native limitation
  appeared in all-on integration, but author command execution differs when
  host operation is disabled. Therefore an observed cost difference cannot be
  assigned solely to the intended instruction/edit mechanisms without also
  disclosing execution-restriction and recovery costs. Keep the frozen policy
  and every outcome; do not silently broaden permissions, mark blocked tests
  passed or represent this as a clean isolated effect. No new model observation
  or product repair is added by this read-only finding.

- 2026-09-18 00:19 UTC: independent read-only audit of the three completed
  all-on histories reproduces 25,673,000 / 22,490,575 / 26,119,875 exactly.
  Parent and child totals, source pins, model settings and returned-response
  coverage match with zero audit errors. On-02 remains failed solely because
  of its original host test; accurate counting does not turn it into a pass.
  The audit takes under one second, launches no model or compiler and changes
  no measured file. Full six-run audit still follows the ongoing all-off wave.

- 2026-09-18 00:08:08 UTC: launch off-01/off-02/off-03 concurrently with
  all nine switches explicitly disabled. Each retains the same 90-minute,
  60M-observed-raw and 600-parent-turn bounds. Record all three owned PIDs and
  sessions above. The observer remains uninterrupted; all-on sessions close.
  Post-run scoring and any failed-test diagnostic wait until all generation
  ends, so they do not add compilation load to this wave.

- 2026-09-18 00:07 UTC: all-on model generation and final checks finish.
  On-01 passes at 25,673,000 raw; on-02 retains its failed terminal assertion
  at 22,490,575; on-03 passes at 26,119,875. Each has complete parent/child
  coverage and matching frozen source/configuration. The unrelated failed
  test is not a shared authentication/accounting/setup failure, so the
  already-admitted three all-off workflows proceed. No source or permission
  change, replacement, extra model call or success-only selection occurs.

- 2026-09-17 23:53 UTC: on-02 ends at 22,490,575 raw, including 13,093
  child tokens counted once. Integration has the required three commits and
  clean checkout; formatting and Clippy pass. The host test suite fails
  `terminal_app_does_not_run_project_required_checks_outside_agent` because
  the captured frame does not contain `launch reply`; no timeout or accounting
  error occurs. The final agent separately reports sandbox restrictions for
  local TCP and native Codex startup. Preserve the failed result, inspect the
  exact assertion without changing source, and continue the two active runs.
  No replacement or extra model turn is admitted. Any provider-free diagnostic
  repeat must be separate evidence, not an overwrite or automatic pass.

- 2026-09-17 23:41 UTC: on-02 finishes all three author/review loops and
  enters final integration planning. On-01/on-03 repair their first review of
  the final feature. No full workflow is complete yet. All source pins match;
  parent and child coverage remain clear. The three all-off runs remain unstarted.

- 2026-09-17 23:31 UTC: on-02 reviews the third/final feature, on-01
  implements it, and on-03 is in slash-routing review two. All three full runs
  have exercised nested Codex verification. Child costs are included once:
  52,406 / 13,093 / 39,386 raw so far. No child model mismatch, incomplete
  returned count, terminal failure or source/configuration change is observed.

- 2026-09-17 23:18 UTC: on-02 reaches slash-routing review after actual nested
  verification. Its 13,093 child raw tokens are included by the observer, with
  matching model/effort and no incomplete child turn. On-01 is implementing
  slash routing; on-03 is repairing its third text-selection review. The frozen
  starting AGENTS.md explicitly documents bounded pre-agent sandbox failures;
  that limitation remains visible rather than prompting credential copying,
  permission broadening or repeated native-startup attempts.

- 2026-09-17 23:14 UTC: on-01 and on-02 finish the text-selection
  author/review loop and start slash-command routing. On-03 is in text-selection
  review two. No run is terminal; all returned responses have coverage, with no
  model mismatch or source change. Repair and review costs remain included.

- 2026-09-17 23:06 UTC: two all-on workflows reach independent review of
  text selection; the third is finishing implementation. Actual author edits,
  rejected proposals, checks and repairs remain in the totals. The independent
  final audit reproduces the tiny qualification exactly, and all three external
  scoring-fixture hashes match. No benchmark code, prompt, settings or limits
  change. The 15-second observer shows no returned-usage gap or model mismatch.

- 2026-09-17 22:47:55–22:48 UTC: observer starts, then all three all-on
  workflows launch concurrently from commit 3f54c08. All actual provider
  fingerprints equal the frozen preflight, all program hashes match and all
  native Git preflights pass. Three authors begin text selection. Process and
  session identities are recorded above. No off workflow or extra run starts.

- 2026-09-17 22:45–22:46 UTC: qualification 002 passes in 263.54 seconds:
  330,274 parent + 21,927 child = 352,201 raw tokens. Twelve parent turns and
  two child turns are complete. Independent review approves the unchanged
  feature, integration creates one verification-only empty commit, and all ten
  final tests pass. A final native-record inspection leads to two fail-first
  observational guards: assistant-item tail coverage and explicit API/unknown
  plan rejection. Saved-record replay preserves the exact complete child total;
  all 59 tests pass. Full benchmark input hash remains unchanged. The closed
  Work Leaf worktree's pre-existing changes are left untouched.

- 2026-09-17 22:38–22:42 UTC: tiny qualification 001 stops at 143,950 fully
  measured parent tokens after invalid CLI option placement and an unexpected
  output file. It generated no child response. Retain the failure and supply
  exact in-memory launch/resume syntax for qualification 002. Its author repairs
  a multiline shell representation error, then successfully launches and resumes
  one GPT-5.5/xhigh child. Both replies are asserted; the live observer includes
  21,927 child tokens once. No source changes or pricing gap is present.
  The separate native-sandbox probe fails before agent startup with read-only
  local-state initialization (zero child generation); a single `codex doctor`
  reports ChatGPT auth, reachable service and no failed diagnostics. Native
  sandbox restrictions remain unchanged, and blocked verification is not green.

- 2026-09-17 22:26–22:36 UTC: read the restart contract and all three retained
  failure reports. None of the latest all-on observations is complete, so none
  can replace a complete new observation. Six new regressions initially fail
  (three assertions and three missing-module errors). The repair pins nested
  Codex model/login, strips API credentials, includes native child histories in
  totals without counting resumed cumulative usage twice, and sends unchanged
  features through whole-request review. Rejected unchanged work still requires
  repair/re-review. The first real zero-generation environment probe detects
  shell startup restoring an API-key variable; an additional failing regression
  precedes the fix. Probe 002 passes with ChatGPT/GPT-5.5/xhigh and the guarded
  command path. No model or API generation has occurred in these probes.

- Earlier implementation verification: 35 local tests; one tiny two-feature
  all-on attempt stopped at its token ceiling; a real conflict/interruption
  check and separate final integration check passed. Their recorded total is
  501,697 observed raw tokens. None belongs to this six-run comparison. Full
  outcomes and limitations are in [VERIFICATION.md](VERIFICATION.md).
- 2026-09-17 17:15 UTC: read the original research instructions, operator policy,
  original reproduction protocol, starting-commit agent instructions and frozen
  feature-scoring setup. The new user instruction admits exactly three all-on
  and three all-off workflows. No original result or Work Leaf counter changes.
- 2026-09-17 17:15 UTC: all 35 local tests and Python compilation pass. The
  non-generating subscription check confirms Codex 0.154.0, ChatGPT login and
  GPT-5.5/xhigh. Starting commit, disk/memory capacity and program hashes checked.
  Per-workflow limits are frozen at 90 minutes / 60M observed raw / 600 turns,
  identically in both groups; requested concurrency is three complete workflows.
- 2026-09-17 17:18:08 UTC: on-01, on-02 and on-03 start concurrently. Owning
  tool sessions are 62533, 87102 and 82642; runner PIDs are 1089149, 1089160
  and 1089150 respectively. All three reach the first author without a setup
  failure. No off workflow is launched early and no prompt/source is changed.
- 2026-09-17 17:21 UTC: all three actual provider configuration hashes match
  preflight. The incremental observer starts in session 46620 and retains a
  sample every 30 seconds without regenerating or changing benchmark input.
  The first two manual checks were 17:19:08 and 17:21:15 (a 127-second gap,
  exceeding the planned operator interval while the observer was prepared).
  The runner's independent limits remained active. Continuous 30-second
  sampling replaces that manual gap; no outcome or limit is changed.
- 2026-09-17 17:27 UTC: the startup warning is identical in all three clones.
  Their tracked `.codex/config.toml` contains only approval, sandbox and network
  defaults, not model/task instructions; the runner supplies its explicit
  per-role settings. The actual provider identities match preflight. The older
  local command rules concern Docker/shell operations. No trust, login, prompt
  or permission setting is changed after admission. Project-local settings
  being skipped is documented in the [official configuration guide](https://learn.chatgpt.com/docs/config-file/config-basic).
  Keep this environment detail in the comparison rather than suppressing the warning.
- 2026-09-17 17:27 UTC: the incremental observer is checked against the retained
  real-agent protocol record: it reproduces 63,381 raw and does not count the
  same input twice. No new model invocation belongs to this observer check.
- 2026-09-17 17:31 UTC: on-01 reaches the first independent review. The other
  two authors remain active on text selection. Provider-free scoring is prepared
  using the exact earlier three fixtures; it waits until all six measured
  workflows stop, so it does not create unequal CPU load during the off batch.
  [Post-run check details](experiments/on-off-20260917/POST-RUN-CHECKS.md).
- 2026-09-17 17:35 UTC: all three on workflows reach independent review of
  feature 1. On-01 has already completed one repair round and reached review 2;
  on-02 and on-03 are in review 1. No terminal failure, counter-reset warning
  or budget stop is recorded. The live table shows within-workflow progress
  while the finished-workflow count remains 0/6.
- 2026-09-17 17:45 UTC: on-02 finishes the first feature's author/review loop
  and starts slash-command routing. On-01 and on-03 remain in text-selection
  review/repair. A read-only ownership audit finds every usage-report thread
  was started by its own runner; there are no unrelated charged conversations.
  Counts are 2/3/2 started-and-charged conversations for on-01/on-02/on-03.
- 2026-09-17 17:47 UTC: on-02 and on-03 are implementing the second feature;
  on-01 remains in text-selection review 6. Different amounts of
  review/repair activity stay inside the original run totals. No response, retry
  or expensive prefix is removed, and no result-dependent setting is changed.
- 2026-09-17 17:49 UTC: all three on workflows have finished the first
  feature's implementation/review loop and are implementing slash-command
  routing. Their differing first-feature costs remain recorded, not averaged
  with incomplete later stages or treated as final benchmark totals.
- 2026-09-17 17:55 UTC: all three on workflows reach review of the second
  feature. No workflow has terminated or reached its fixed limit. The three
  off observations remain unstarted, preserving the requested two-wave schedule.
- 2026-09-17 18:03 UTC: all three on workflows finish the second feature's
  implementation/review loop and start the third feature. The continuous
  sample history retains all intervening observations, including long responses
  during which no new token total is delivered.
- 2026-09-17 18:14 UTC: on-02 is repairing its third feature after the first
  review; on-01 and on-03 remain in implementation. All three owned runner
  processes are alive, with no terminal failure or counter-decrease warning.
  No measured source, switch, prompt or limit is changed.
- 2026-09-17 18:15–18:17 UTC: a completed-response coverage audit finds
  missing reports in on-01 and on-03. Empty counter-decrease warnings did not
  mean complete usage: the live observer tracked cumulative totals, but omitted
  the runner's per-response missing-usage flags. Earlier updates stating no
  failures were based on that insufficient live check. This monitoring gap is
  retained explicitly; it does not erase the missing responses.
- 2026-09-17 18:17:04 UTC: after checking the exact owned runner identities,
  send SIGINT to all three under the frozen common-accounting-failure rule.
  Each closes with its usage-drain path and saved partial result; no provider
  process remains. No off workflow starts. On-01/on-02/on-03 retain
  14,911,977 / 13,932,504 / 12,962,583 observed raw respectively, all incomplete.
  The operator stop adds one unfinished response per run; earlier missing
  completed responses are a separate issue, not caused by that final stop.
- 2026-09-17 18:18 UTC: begin a bounded local-only recovery check, at most
  15 minutes, using saved transport and the three runs' native histories.
  No model call, authentication change, source repair, new observation or
  replacement is permitted in this check. Determine whether later counters
  or saved response metadata supply the missing usage before recommending
  another benchmark admission. Official app-server documentation describes
  interruption and usage notifications separately and supplies no missing
  numeric values for these observations.
- 2026-09-17 18:22 UTC: the saved-data audit identifies 67 earlier completed
  responses without final-message usage coverage: 23 in on-01, none in on-02,
  and 44 in on-03. Sixty-six end in an intermediate host-request message and
  are interrupted after 0.45–12.53 milliseconds; one further final-answer gap
  remains after the full one-second grace. The final operator cancellations
  add one separate unfinished response per run. All 17 native histories match
  already-counted transport totals and supply no additional total. The exact
  recorded sum is 41,807,064 raw, still incomplete. The saved audit is local
  only and ends well before its 15-minute ceiling.
- 2026-09-17 18:25 UTC: save the failure report, reproducible audit and detailed
  counter/timing evidence. All 35 existing tests pass, but do not qualify this
  failed real-agent path. README and VERIFICATION describe the unresolved
  measurement limitation. No measured program or input hash changes. No
  external feature scoring is applied to a partial checkout. Off runs remain
  unstarted; fixing and re-admitting replacement observations needs a new
  prospective admission, not silent reuse of failed attempts.
- 2026-09-17 18:26 UTC: replaying the local audit reproduces all saved values
  after normal JSON serialization. The first comparison assertion treated a
  Python null dictionary key differently from its serialized JSON key; only
  the comparison expression was corrected, with no evidence change. All
  native metadata key checks, source pins, 35 unit tests, Python compilation
  and whitespace checks pass. The actual benchmark measurement remains
  failed, not green. Both groups require the same repaired frozen code before
  any newly approved replacement comparison; no new model call occurs here.
- 2026-09-17 18:51 UTC: record the user's explicit repair/small-test/fresh-six
  approval. Reread the supervising contract, live records, operator policy and
  previous failure protocol. The repair targets cancellation only after fresh
  request-covering usage, immediate workflow failure on missing coverage, and
  visible live coverage flags. No task instructions or model changes are planned.
  Three repair obligations and the small real verification are recorded before
  implementation; the six full workflows wait for their qualification gate.
- 2026-09-17 18:54 UTC: all eight new regressions fail before the fix
  (five failed assertions, three missing observer/journal errors). The stream
  example demonstrates cancellation with zero reported raw before its later
  110-token report. The workflow example incorrectly accepts an unmeasured
  author's edit before repair. These are local tests, not new model observations.
- 2026-09-17 18:56 UTC: all eight new tests and all 43 total tests pass after
  the repair. Cancellation requires request-covering fresh usage; neither
  resumed output nor elapsed grace is enough. The post-completion collection
  window may extend from one to five seconds if usage is missing. A missing
  measurement stops the workflow before another host operation or agent turn.
  Incremental live monitoring reads a per-turn coverage journal and explicitly
  reports the retained first batch's 24/1/45 gaps (including final cancellations).
- 2026-09-17 18:58 UTC: non-generating readback confirms the same Codex 0.154.0,
  ChatGPT login, GPT-5.5/xhigh and effective configuration hash. Start exactly
  one small real verification under `runs/on-off-20260917-r2/real-usage-001`:
  240 seconds / 150,000 observed raw / eight turns. It must demonstrate an
  actual priced interruption, intermediate request, compact stale-edit recovery,
  real check, natural-finish mode and completion with no missing usage.
- 2026-09-17 19:00–19:02 UTC: real verification passes in 37.59 seconds with
  76,865 raw, five priced interruptions and one natural finish. All six turns
  have final-message usage coverage; compact refresh, corrected edit, real
  Python tests and completion pass. The verified program hashes are exactly
  the current hashes. All 320 valid author-prompt combinations remain byte
  identical. Record qualification of all three repairs, retain the first-batch
  failures, and freeze the six replacement attempts before generation. Available
  memory is about 36 GiB and free disk space about 572 GiB.
- 2026-09-17 19:04:41 UTC: launch replacement on-01/on-02/on-03 concurrently
  after commit `746630e`. Runner PIDs: 1201021/1201012/1201036; owning tool
  sessions: 41982/24397/28208. All nine switches are on. Separate clones use
  the frozen base, program, subscription, model and 90-minute/60M/600-turn limits.
- 2026-09-17 19:07–19:09 UTC: recover the live sessions after context
  compaction; no duplicate run is launched. Start the 15-second observer in
  session 37457 at 19:08:25 UTC. There was a four-minute startup gap before
  this observer began; the runner's immediate missing-coverage stop was active
  throughout. Its first scan includes all retained events since launch, finding
  zero coverage gaps or counter warnings. All three are implementing text selection.
- 2026-09-17 19:15 UTC: replacement on-01 and on-02 reach independent review
  of text selection; on-03 remains in implementation. All actual provider
  configuration hashes match the qualification check, and program/input hashes
  remain frozen. No returned-response coverage gap or counter warning is present.
- 2026-09-17 19:24 UTC: all replacement workflows reach independent review
  of the first feature; on-01/on-02 are in their second review after repairs.
  A direct saved-transport check of on-01 turn 6 shows final message, fresh
  usage, interruption, then terminal acknowledgement in that order. This
  supports the repaired boundary for that checked response, not a blanket
  claim about every internal response. Full retained-data audit follows all six.
- 2026-09-17 19:34 UTC: replacement on-01 completes the first feature's
  implementation/review loop and starts slash-command routing. On-02 is in
  text-selection review 5 and on-03 in review 3. The live coverage gate still
  reports zero gaps and zero counter warnings; no settings or limits change.
- 2026-09-17 19:39 UTC: all three replacements complete text selection's
  implementation/review loop. On-01 reaches slash-command review 1 while
  on-02/on-03 implement that second feature. All returned-response coverage
  checks remain clear. Earlier repair rounds and their full token costs remain
  included; no outcome-dependent changes or early all-off launch occur.
- 2026-09-17 19:47 UTC: on-01/on-03 finish slash-command routing and start
  the review-completion prompt, the third feature. On-02 repairs its second
  feature after review. All three runner processes and the observer remain
  alive; only this supervising note differs from the frozen committed source.
  Coverage gaps and counter warnings remain zero.
- 2026-09-17 19:54 UTC: all replacements have completed slash-command
  routing and entered the third feature. On-03 is in its first independent
  review; on-01/on-02 are implementing it. No final-workflow total or saving
  percentage is declared before review, integration and final checks finish.
- 2026-09-17 20:04 UTC: on-03 finishes all three feature implementation/
  review loops and enters final integration planning. On-01 is reviewing the
  third feature for the second time; on-02 reaches its first third-feature
  review. Final commit-history acceptance, Rust checks and usage audit still
  precede any completed-comparison claim. No missing coverage is reported.
- 2026-09-17 20:10 UTC: on-03, then on-01 fail the final commit-history gate.
  Both actual integration replies report `.git/index.lock: Read-only file system`.
  Their source files are writable, but native agent Git metadata writes are not.
  Both retain complete reported usage; neither reaches final host checks.
- 2026-09-17 20:11:30 UTC: confirm the shared failure from both saved replies
  and frozen writable sandbox policy; send SIGINT only to remaining owned
  runner 1201012. On-02 saves its partial third-feature repair and usage tail.
  All provider processes exit. No off run is launched; monitor 1206517 is
  stopped after retaining the final samples. Replacement observed usage is
  57,157,285 raw, including the incomplete operator-cancelled tail.
- 2026-09-17 20:14 UTC: the earlier tiny integration verifier's false-positive
  scope is identified: its input already had exactly two feature commits and
  its real reply explicitly says no history rewrite was needed. It checked a
  final shape, not actual native Git writes. Preserve that record, but withdraw
  it as evidence that history rewriting works. Begin a bounded local-only
  permission reproduction/repair check, at most 15 minutes and zero model calls.
  No saved benchmark checkout or measurement will be changed, and no additional
  generated observation is admitted by this local check.
- 2026-09-17 20:14–20:16 UTC: CLI-only sandbox probes first hit command-syntax
  and missing-profile errors, without executing Git or generating model output.
  The installed protocol schema and official command-execution documentation
  identify the exact no-generation app-server path using the benchmark's policy.
  `git-command-probe-001` reproduces exit 128 with the original policy and an
  actual commit with only `.git` added as a writable root. No benchmark source
  is modified. The provider records zero model turns and zero raw tokens.
- 2026-09-17 20:17 UTC: independent accounting audit reproduces all three
  replacement totals and all 20 native history totals. There are no counter
  decreases, unowned charges or earlier returned-response gaps. On-02 has only
  its deliberate cancellation tail. All non-switch comparison keys match.
- 2026-09-17 20:19–20:22 UTC: five new permission/preflight/verifier tests run
  before repair: two failed assertions, two missing-method/guard errors and one
  already-passing read-only invariant. All pass after the narrow repair. The
  full runner performs a zero-generation Git-write preflight in its own clone;
  `doctor` remains non-mutating. The real integration fixture requires actual
  collapse of an extra disposable commit, so a no-op cannot pass again.
  `git-command-probe-002` exercises the actual repaired helper and preflight,
  again with zero model calls/tokens. Read-only roles and network policy remain
  unchanged. Frozen benchmark outcomes and admission files are untouched.
- 2026-09-17 20:26–20:27 UTC: all 49 local tests, compilation and whitespace
  checks pass after adding the positive history-collapse case. No model or
  monitor process remains. The bounded local check ends within 15 minutes;
  save the result and repair without claiming an unrun real-agent rewrite or
  a three-versus-three percentage. Preserve every reviewed checkout for a
  separately authorized, cost-conscious continuation rather than automatic reruns.
- 2026-09-17 20:29 UTC: commit `5849501` preserves the replacement accounting
  audit, precise failure report, zero-generation probe, narrow Git permission
  fix, early preflight and stricter verifier. The source fix is not represented
  as having passed the still-unrun model-backed rewrite. No full-workflow
  replacement or off observation is started.
- 2026-09-17 20:37 UTC: save the user's conditional restart approval before
  generation. The required small check must actually rewrite its disposable
  input history, pass tests and retain complete token counts. One check only:
  240 seconds / 200,000 observed raw / two turns. On success, the approved new
  batch is three all-on workflows concurrently followed by three all-off.
  All earlier failed observations remain intact; no Work Leaf counter changes.
- 2026-09-17 20:39 UTC: the small real check passes native Git preflight and
  completes read-only planning without source mutation. It enters its second
  turn with complete reported usage so far. Owning session 37935, PID 1317323.
  Admission and preflight are committed as `409f41d`; no full benchmark starts
  before actual rewrite, tests and final usage are independently checked.
- 2026-09-17 20:40 UTC: the real agent actually rewrites three input commits
  into two feature commits. All ten tiny tests pass, both turns have complete
  token counts, and 191,320 raw tokens stay below the approved threshold.
  The original source and frozen program hashes are unchanged. The conditional
  six-workflow gate passes; no further permission pause is needed.
- 2026-09-17 20:41:26 UTC: launch on-01/on-02/on-03 concurrently from
  committed source `2563ea1`; the 15-second observer starts first, at 20:41:25.
  Runner PIDs are 1320896/1320920/1320906; owning sessions 52740/75945/8150.
  Observer PID 1320876, session 72660. Each native Git preflight passes before
  generation; all three actual provider identities and configuration hashes
  match the approved preflight. No off workflow has started.
- 2026-09-17 20:52 UTC: on-02 reaches the first independent text-selection
  review; on-01/on-03 remain in implementation. Several multi-minute model
  responses leave live totals temporarily unchanged, then return with usage.
  No failed response, missing returned count or counter decrease is detected.
  All three source manifests and all-on switch sets match the frozen protocol.
  The three external scoring fixture hashes also match; scoring waits until
  generation ends so it does not alter concurrent benchmark resource load.
- 2026-09-17 20:57 UTC: all three initial implementations reach independent
  review. On-02 submits its first repair and starts review two; on-01 makes
  its first repair; on-03 is in review one. These are ordinary measured feature
  iterations, not setup failures or replacement observations. All returned-turn
  coverage checks remain clear; about 569 GiB of disk remains available.
- 2026-09-17 21:03 UTC: on-01 completes text selection after four reviews
  and begins slash-command routing. On-02 is in first-feature review three;
  on-03 makes its second repair. All review/repair usage stays in each workflow.
  No accounting gap or safety failure is present, and no source or budget changes.
- 2026-09-17 21:07 UTC: all three workflows complete the first feature's
  implementation/review loop and implement slash-command routing. Review costs
  differ across runs and are retained in full. All returned responses remain
  measured, all processes are alive, and the all-off wave is still unstarted.
- 2026-09-17 21:10 UTC: on-02 ends after its second-feature author declares
  completion without proposing an edit. The required-new-commit gate stops it
  before independent review. Inspecting its command receipt reveals a separate
  Codex launch/resume conversation omitted from the main usage table.
- 2026-09-17 21:11:31 UTC: after verifying process ownership and the concrete
  omitted child, SIGINT on-01/on-03 under the frozen common-accounting-failure
  rule. Each retains one incomplete cancellation tail. All-off stays unstarted;
  stop the observer after final samples. No generator remains.
- 2026-09-17 21:12–21:19 UTC: bounded local-only audit finds ten parent
  conversations plus one child in the exact three owned checkout directories.
  All parent counters match their saved native histories. The child uses
  GPT-6 Astra/max, not pinned GPT-5.5/xhigh, and reports Pro subscription usage.
  Its exact seven-response charge is 167,250 raw. The initial 184,841 estimate
  mistakenly added two cumulative CLI reports; their shared first response is
  counted only once in the corrected native-response calculation. Existing
  benchmark totals stay untouched; recovery is a separate evidence supplement.
- 2026-09-17 21:19–21:22 UTC: source inspection identifies the unguarded
  host-command environment and the no-new-commit completion boundary. The frozen
  starting source already contains slash-routing code and four passing focused
  checks; independent feature review did not run on the no-edit outcome. Save
  exact source/event evidence and current limitations. One documentation patch
  fails format validation before writing and is retried correctly. No product
  code, prompt, old outcome, original research counter or new observation changes.
- 2026-09-17 21:24 UTC: the saved-data query reproduces every value exactly
  except its expected observation timestamp. All 49 existing local tests pass
  in 20.373 seconds, compilation and whitespace checks pass, and measured source
  hashes remain unchanged. These tests do not cover the discovered child-process
  and no-commit boundaries and do not make the runner ready. The local-only
  recovery finishes within its 15-minute ceiling; no next generated check is
  admitted. Preserve reviewed source and seek a small targeted qualification
  before any further full-benchmark spending.
