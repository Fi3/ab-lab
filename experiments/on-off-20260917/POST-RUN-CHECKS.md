# Provider-free verification of the saved outcomes

The six measured workflows use the unchanged frozen program and benchmark.
`monitor.py` reads only appended transport/progress records, using the same
deduplicating usage-counter logic as the runner. It emits a snapshot every
30 seconds and keeps every sample. Re-reading the saved real-agent protocol
record reproduces 63,381 raw without double counting on a second sample.

After all six measured attempts are terminal, `score_features.py` checks each
completed result in a separate clone. It first requires the actual final commit
and clean original checkout, verifies the three frozen test-file hashes, and
copies those exact tests into the analysis clone. No measured source or fixture
assertion is rewritten. Failed workflows are recorded as not scored, with no
fallback to their starting commit. Each feature-test process has a 900-second
limit, matching the original external scorer's default; clone setup has a
120-second limit. These limits do not extend an agent's generation window.

The fixtures use a local fake backend or UI harness, not an actual model.
Post-run CPU-heavy scoring waits until all six model workflows have stopped,
so it does not load the machine during only the second comparison group.
Every stdout/stderr stream and result is retained. Setup failures and failing
feature assertions remain explicit and do not trigger a model repair or repeat.

Run-data roots:

- `runs/on-off-20260917/on-01` through `on-03`;
- `runs/on-off-20260917/off-01` through `off-03`;
- `runs/on-off-20260917/feature-scores/<run-id>` for post-run verification.

The committed protocol owns the exact comparison. These operator helpers do not
change the code hashes, instructions, switch settings or six-observation count.
