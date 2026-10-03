Runs: 1 | failed: 1

| Run     | Result | Execution | Raw tokens | Cached input | Usage    | Time    | Reviewed features | Checks |
| ------- | ------ | --------- | ---------- | ------------ | -------- | ------- | ----------------- | ------ |
| bench11 | failed | completed | 5,472,027  | 5,047,936    | complete | 38m 28s | 0/5               | 1/1    |

Reviewed features counts reviewer approvals, not independent feature acceptance tests.

Enabled switches: C13,C14,C15,C20,C38.

Observed raw tokens: 5,472,027 (1/1 runs reported a number).

Errors:

- bench11: SlopCodeBench correctness did not pass at every checkpoint and final evaluation; see slopcodebench results

Code-quality measurements (scb-check scores, not token savings):

| Run     | Checkpoint           | Status         | Verbosity | Erosion | Cognitive erosion |
| ------- | -------------------- | -------------- | --------- | ------- | ----------------- |
| bench11 | Before edits         | not_applicable | —         | —       | —                 |
| bench11 | After implementation | completed      | 2.14%     | 53.55%  | 80.64%            |

SlopCodeBench correctness:

| Run     | Problem     | Status    | Strict checkpoints | Final | All tests | Solved |
| ------- | ----------- | --------- | ------------------ | ----- | --------- | ------ |
| bench11 | code_search | completed | 2/5                | fail  | fail      | no     |

Strict checkpoints counts passing checkpoints out of the full task sequence; missing evaluations are not passes.
All tests reports upstream correctness separately from unresolved review findings and workflow success.

| Run     | Checkpoint       | Status | Review  | Strict | Isolated | Core | Tests  | Verbosity | Erosion |
| ------- | ---------------- | ------ | ------- | ------ | -------- | ---- | ------ | --------- | ------- |
| bench11 | checkpoint_1     | passed | skipped | pass   | pass     | pass | 13/13  | 0.00%     | 27.65%  |
| bench11 | checkpoint_2     | passed | skipped | pass   | pass     | pass | 25/25  | 0.00%     | 24.12%  |
| bench11 | checkpoint_3     | failed | skipped | fail   | fail     | fail | 46/47  | 1.78%     | 40.45%  |
| bench11 | checkpoint_4     | failed | skipped | fail   | fail     | fail | 73/75  | 2.28%     | 55.74%  |
| bench11 | checkpoint_5     | failed | skipped | fail   | fail     | pass | 99/104 | 2.14%     | 53.55%  |
| bench11 | Final evaluation | failed | —       | fail   | fail     | pass | 99/104 | —         | —       |

Benchmark evaluation:

| Run     | Evaluator     | Status    | All tests | Report                                                                   |
| ------- | ------------- | --------- | --------- | ------------------------------------------------------------------------ |
| bench11 | slopcodebench | completed | fail      | /home/user/src/agent-behavior-lab/runs/bench11/slopcodebench/result.json |
