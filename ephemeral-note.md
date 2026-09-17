# Runs finished: 0 / 6

Last sampled: 2026-09-17T17:31:15.272114+00:00.
Current activity: on-01, on-02, on-03 running.
Measured on-versus-off reduction: pending complete six-run measurement verification.
The expected roughly 50% difference is not a result.

This is the standalone tool's six-run validation, separate from Work Leaf's old
research task counter. [Fixed protocol](experiments/on-off-20260917/PROTOCOL.md).

| Run | All nine switches | State | Observed raw tokens |
| --- | --- | --- | --- |
| on-01 | On | Feature 1: text selection / review 1 | 1,657,270 (partial) |
| on-02 | On | Feature 1: text selection / implementation | 847,059 (partial) |
| on-03 | On | Feature 1: text selection / implementation | 1,908,085 (partial) |
| off-01 | Off | Waiting | — |
| off-02 | Off | Waiting | — |
| off-03 | Off | Waiting | — |

Finished counts terminal attempts, including failures—not successful, fully measured
benchmarks. All checkouts and outcomes are retained; no automatic replacement.
Raw tokens are input plus output, with cached input included only once.

[Live status](runs/on-off-20260917/monitor-current.json) updates every 30 seconds;
all samples remain in runs/on-off-20260917/monitor-samples.jsonl.

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
