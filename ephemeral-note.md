# Runs finished: 0 / 6

Current activity: prelaunch checks passed; the three all-on workflows are next.
Measured on-versus-off token reduction: not available; no run in this comparison
has finished yet. User expectation of roughly 50% is not a measured result.

This is the standalone tool's six-run validation, not the old Work Leaf task
counter. [Fixed experiment protocol](experiments/on-off-20260917/PROTOCOL.md).

| Run | All nine switches | State | Observed raw tokens |
| --- | --- | --- | --- |
| on-01 | On | Ready | — |
| on-02 | On | Ready | — |
| on-03 | On | Ready | — |
| off-01 | Off | Waiting for first batch | — |
| off-02 | Off | Waiting for first batch | — |
| off-03 | Off | Waiting for first batch | — |

“Finished” counts terminal attempts, including failures, not successful or fully
measured runs. Each workflow retains its own checkout and evidence. No automatic
replacement is authorized. Raw tokens are input plus output, including cached
input only once; partial totals are not complete benchmark measurements.

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
