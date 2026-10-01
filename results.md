# RESULTS

* Conditions: `all` enables every C; `native` disables every C. Record explicit overrides separately.
* Current workflow has no integration agent or history linearization.
* priority accepted is always P0 P1 P2
* Control uses `--preset native`: all Cs off, no external review or loop detector; filesystem/global-budget safety, source capture and independent evaluation remain.

## Slope bench


### runs

* [bench1](runs/bench1/result.json)
* [bench2](runs/bench2/result.json)
* [bench3](runs/bench3/result.json)
* [bench4](runs/bench4/result.json)
* [bench5](runs/bench5/result.json)
* [bench6](runs/bench6/result.json)

| model/reasoning      | test passes    | total tokens | uncached tokens | harness | conditions | reviews | verbosity | erosion | cognitive erosion | time       |
| -------------------- | -------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- |
| gpt-5.5 / xhigh      | 101/104        | 23,727,935   | 2,365,503       | Codex   | all        | 3       | 2.28%     | 71.63%  | 85.15%            | 1h 59m 25s |
| gpt-5.5 / xhigh      | 99/104         | 4,633,537    | 412,609         | Codex   | all        | 0       | 3.49%     | 65.87%  | 88.95%            | 45m 29s    |
| gpt-5.6-sol / xhigh  | 70/104         | 25,069,720   | 1,393,432       | Codex   | all        | 3       | 2.06%     | 67.56%  | 91.56%            | 1h 53m 08s |
| gpt-5.6-sol / xhigh  | 93/104         | 6,287,933    | 369,085         | Codex   | all        | 0       | 2.31%     | 79.49%  | 93.51%            | 45m 04s    |
| gpt-5.6-luna / xhigh | 70/104         | 25,049,138   | 1,807,922       | Codex   | all        | 3       | 4.77%     | 94.53%  | 98.08%            | 2h 11m 06s |
| gpt-5.6-luna / xhigh | 94/104         | 12,068,270   | 619,182         | Codex   | all        | 0       | 5.00%     | 90.10%  | 98.78%            | 57m 20s    |

### control run

| mode/reasoning | test passes | total tokens | uncached tokens | harness |verbosity | erosion | cognitive erosion | time |
| -------------- | ----------- | ------------ | --------------- | ------- | -------- | --------| ----------------- | ---- |
