# Runs finished: 3 / 6

Last sampled: 2026-09-17T18:17:45.924037+00:00.
Last updated: 2026-09-17 18:26 UTC.
Current activity: STOPPED for missing token measurements; saved-data audit complete. No generation running.
Successfully completed full benchmarks: 0 / 6. Three partial attempts ended; three were not started.
Measured on-versus-off reduction: NOT AVAILABLE; the requested comparison is not complete.
The expected roughly 50% difference is not a result.
[Result and exact failure](experiments/on-off-20260917/RESULT.md).

This is the standalone tool's six-run validation, separate from Work Leaf's old
research task counter. [Fixed protocol](experiments/on-off-20260917/PROTOCOL.md).

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
The observer is stopped because no benchmark is running.

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
