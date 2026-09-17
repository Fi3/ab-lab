# Benchmark attempts ended: 6 | Successful full benchmarks: 0

Current approved batch: **0 / 6 ended**, conditional on the small real Git-rewrite check.
Accounting repairs verified: **3 / 3**. Git-rewrite qualification: admitted, not yet run.
Both previous batches retain three failed attempts and three unstarted slots each.

Last sampled: 2026-09-17T20:11:42.184547+00:00.
Last updated: 2026-09-17 20:37 UTC.
Current activity: all 49 local tests and the non-generating subscription check pass. Starting the single approved real Git-rewrite check (four minutes / 200k observed raw / two turns). The six full workflows remain conditional on its verified success.
On-01/on-03 reached final integration with complete reported usage. On-02's sole incomplete response is the deliberate safety cancellation, not an earlier returned-response gap.
The real check used 76,865 raw tokens in 37.59 seconds, with six fully measured turns.
Measured on-versus-off reduction: NOT AVAILABLE; the requested comparison is not complete.
The expected roughly 50% difference is not a result.
[Result and exact failure](experiments/on-off-20260917/RESULT.md).
[Approved continuation](experiments/on-off-20260917-r2/REPAIR-AND-RUN-AUTHORITY.md).
[Replacement protocol](experiments/on-off-20260917-r2/PROTOCOL.md) · [Repair evidence](experiments/on-off-20260917-r2/QUALIFICATION.md).
[Replacement result and exact Git failure](experiments/on-off-20260917-r2/RESULT.md).
[Current conditional admission and frozen source](experiments/on-off-20260917-r3/PROTOCOL.md).

This is the standalone tool's six-run validation, separate from Work Leaf's old
research task counter. The retained observer sampled response coverage every 15 seconds.

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

Current 15-second snapshots: [live status](runs/on-off-20260917-r2/monitor/current.json),
with the full history in `runs/on-off-20260917-r2/monitor/samples.jsonl`.
The observer and all generators are stopped. Failed totals are not completed-benchmark totals.

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

## Activity, retained in time order

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
