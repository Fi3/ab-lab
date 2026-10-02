# RESULTS

* Conditions: `all` enables every C; `native` disables every C. Record explicit overrides separately. `partial` is all without C08,C16,C17,C25.
* priority accepted is always P0 P1 P2
* Control uses `--preset native`: all Cs off, no external review or loop detector; filesystem/global-budget safety, source capture and independent evaluation remain.

## Slope bench (25M token limit)


### runs

* [bench1](runs/bench1/result.json)
* [bench2](runs/bench2/result.json)
* [bench3](runs/bench3/result.json)
* [bench4](runs/bench4/result.json)
* [bench5](runs/bench5/result.json)
* [bench6](runs/bench6/result.json)
* [bench11](runs/bench11/result.json)
* [bench13](runs/bench13/result.json)
* [bench14](runs/bench14/result.json)
* [bench15](runs/bench15/result.json)

| model/reasoning      | test passes    | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P |
| -------------------- | -------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - |
| gpt-5.5 / xhigh      | 101/104        | 23,727,935   | 2,365,503       | Codex   | all        | 3       | 2.28%     | 71.63%  | 85.15%            | 1h 59m 25s | 2 |
| gpt-5.5 / xhigh      | 99/104         | 4,633,537    | 412,609         | Codex   | all        | 0       | 3.49%     | 65.87%  | 88.95%            | 45m 29s    | 2 |
| gpt-5.6-sol / xhigh  | 70/104         | 25,069,720   | 1,393,432       | Codex   | all        | 3       | 2.06%     | 67.56%  | 91.56%            | 1h 53m 08s | 2 |
| gpt-5.6-sol / xhigh  | 93/104         | 6,287,933    | 369,085         | Codex   | all        | 0       | 2.31%     | 79.49%  | 93.51%            | 45m 04s    | 2 |
| gpt-5.6-luna / xhigh | 70/104         | 25,049,138   | 1,807,922       | Codex   | all        | 3       | 4.77%     | 94.53%  | 98.08%            | 2h 11m 06s | 2 |
| gpt-5.6-luna / xhigh | 94/104         | 12,068,270   | 619,182         | Codex   | all        | 0       | 5.00%     | 90.10%  | 98.78%            | 57m 20s    | 2 |
| gpt-5.5 / xhigh      | 99/104         | 5,472,027    | 424,091         | Codex   | partial    | 0       | 2.14%     | 53.55%  | 80.64%            | 38m 28s    | 2 |
| gpt-5.5 / xhigh      | 73/104         | 25,096,148   | 1,905,492       | Codex   | partial    | 3       | 9.41%     | 79.17%  | 90.69%            | 1h 33m 04s | 2 |
| gpt-5.6-sol / xhigh  | 70/104         | 25,048,633   | 1,312,185       | Codex   | partial    | 3       | 3.61%     | 79.86%  | 91.09%            | 1h 41m 44s | 2 |
| gpt-5.6-sol / xhigh  | 97/104         | 8,540,186    | 514,074         | Codex   | partial    | 0       | 3.55%     | 74.04%  | 93.28%            | 49m 45s    | 2 |

### control run

* [bench7](runs/bench7/result.json)
* [bench8](runs/bench8/result.json)
* [bench9](runs/bench9/result.json)

| mode/reasoning       | test passes | total tokens | uncached tokens | harness | verbosity | erosion | cognitive erosion | time    |
| -------------------- | ----------- | ------------ | --------------- | ------- | --------- | ------- | ----------------- | ------- |
| gpt-5.6-sol / xhigh  | 97/104      | 8,486,552    | 435,480         | Codex   | 7.34%     | 90.06%  | 93.02%            | 55m 36s |
| gpt-5.6-luna / xhigh | 98/104      | 14,579,455   | 654,847         | Codex   | 6.55%     | 95.96%  | 99.22%            | 59m 52s |
| gpt-5.5 / xhigh      | 101/104     | 6,429,222    | 477,478         | Codex   | 5.93%     | 68.77%  | 88.28%            | 53m 13s |

## SWE-Milestone — scikit-learn v1.0.2 (50M token limit)

### runs

* [bench12](runs/bench12/result.json)

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - |
| gpt-5.5 / xhigh      | 79227/266699      | 50,046,083   | 2,536,707       | Codex   | all        | 0       | 6.41%     | 39.68%  | 75.43%            | 3h 00m 57s | 2 |

### control run

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- |

## SWE-Milestone — scikit-learn-light v1.0.2 (50M token limit)

### runs

* [bench16](runs/bench16/result.json)
* [bench17](runs/bench17/result.json)
* [bench19](runs/bench19/result.json)
* [bench20](runs/bench20/result.json)

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - |
| gpt-5.5 / xhigh      | 79235/79252       | 36,451,765   | 1,444,661       | Codex   | all        | 0       | 6.42%     | 39.64%  | 75.43%            | 2h 53m 36s | 2 |
| gpt-5.5 / xhigh      | 57539/79252       | 50,047,529   | 3,545,641       | Codex   | all        | 3       | 6.44%     | 39.63%  | 75.34%            | 3h 47m 40s | 2 |
| gpt-5.5 / xhigh      | 79234/79252       | 34,993,448   | 2,270,888       | Codex   | all        | 3       | 6.41%     | 39.63%  | 75.35%            | 2h 33m 42s | 1 |
| gpt-5.5 / xhigh      | 64565/79252       | 32,339,056   | 2,099,312       | Codex   | all        | 3       | 6.42%     | 39.58%  | 75.37%            | 2h 35m 50s | 0 |


### control run

* [bench18](runs/bench18/result.json)

| mode/reasoning       | test passes | total tokens | uncached tokens | harness | verbosity | erosion | cognitive erosion | time       |
| -------------------- | ----------- | ------------ | --------------- | ------- | --------- | ------- | ----------------- | ---------- |
| gpt-5.5 / xhigh      | 61775/79252 | 32,659,869   | 806,173         | Codex   | 6.42%     | 39.63%  | 75.38%            | 1h 13m 39s |
