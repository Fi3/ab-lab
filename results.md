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
* [bench25](runs/bench25/result.json)
* [bench26](runs/bench26/result.json)
* [bench27](runs/bench27/result.json)
* [bench28](runs/bench28/result.json)

| model/reasoning      | test passes    | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P | compaction |
| -------------------- | -------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - | ---------- |
| gpt-5.5 / xhigh      | 101/104        | 23,727,935   | 2,365,503       | Codex   | all        | 3       | 2.28%     | 71.63%  | 85.15%            | 1h 59m 25s | 2 | 131,072    |
| gpt-5.5 / xhigh      | 99/104         | 4,633,537    | 412,609         | Codex   | all        | 0       | 3.49%     | 65.87%  | 88.95%            | 45m 29s    | 2 | 131,072    |
| gpt-5.6-sol / xhigh  | 70/104         | 25,069,720   | 1,393,432       | Codex   | all        | 3       | 2.06%     | 67.56%  | 91.56%            | 1h 53m 08s | 2 | 131,072    |
| gpt-5.6-sol / xhigh  | 93/104         | 6,287,933    | 369,085         | Codex   | all        | 0       | 2.31%     | 79.49%  | 93.51%            | 45m 04s    | 2 | 131,072    |
| gpt-5.6-luna / xhigh | 70/104         | 25,049,138   | 1,807,922       | Codex   | all        | 3       | 4.77%     | 94.53%  | 98.08%            | 2h 11m 06s | 2 | 131,072    |
| gpt-5.6-luna / xhigh | 94/104         | 12,068,270   | 619,182         | Codex   | all        | 0       | 5.00%     | 90.10%  | 98.78%            | 57m 20s    | 2 | 131,072    |
| gpt-5.5 / xhigh      | 99/104         | 5,472,027    | 424,091         | Codex   | partial    | 0       | 2.14%     | 53.55%  | 80.64%            | 38m 28s    | 2 | 131,072    |
| gpt-5.5 / xhigh      | 73/104         | 25,096,148   | 1,905,492       | Codex   | partial    | 3       | 9.41%     | 79.17%  | 90.69%            | 1h 33m 04s | 2 | 131,072    |
| gpt-5.6-sol / xhigh  | 70/104         | 25,048,633   | 1,312,185       | Codex   | partial    | 3       | 3.61%     | 79.86%  | 91.09%            | 1h 41m 44s | 2 | 131,072    |
| gpt-5.6-sol / xhigh  | 97/104         | 8,540,186    | 514,074         | Codex   | partial    | 0       | 3.55%     | 74.04%  | 93.28%            | 49m 45s    | 2 | 131,072    |
| gpt-6-luna / xhigh   | 101/104        | 9,882,438    | 823,878         | Codex   | partial    | 3       | 2.51%     | 86.15%  | 97.95%            | 1h 15m 46s | 1 | 131,072    |
| gpt-6.1-sol / xhigh  | 94/104         | 8,794,492    | 954,620         | Codex   | partial    | 3       | 3.54%     | 71.68%  | 88.57%            | 1h 42m 58s | 1 | 131,072    |
| gpt-6.1-sol / xhigh  | 96/104         | 4,684,436    | 746,772         | Codex   | all        | 3       | 1.47%     | 71.69%  | 91.95%            | 1h 17m 09s | 1 | 131,072    |
| gpt-6-luna / xhigh   | 94/104         | 10,154,470   | 861,158         | Codex   | all        | 3       | 5.16%     | 84.33%  | 97.57%            | 1h 43m 47s | 1 | 131,072    |

### control run

* [bench7](runs/bench7/result.json)
* [bench8](runs/bench8/result.json)
* [bench9](runs/bench9/result.json)

| mode/reasoning       | test passes | total tokens | uncached tokens | harness | verbosity | erosion | cognitive erosion | time    | compaction |
| -------------------- | ----------- | ------------ | --------------- | ------- | --------- | ------- | ----------------- | ------- | ---------- |
| gpt-5.6-sol / xhigh  | 97/104      | 8,486,552    | 435,480         | Codex   | 7.34%     | 90.06%  | 93.02%            | 55m 36s | 131,072    |
| gpt-5.6-luna / xhigh | 98/104      | 14,579,455   | 654,847         | Codex   | 6.55%     | 95.96%  | 99.22%            | 59m 52s | 131,072    |
| gpt-5.5 / xhigh      | 101/104     | 6,429,222    | 477,478         | Codex   | 5.93%     | 68.77%  | 88.28%            | 53m 13s | 131,072    |

## SWE-Milestone — scikit-learn v1.0.2 (50M token limit)

### runs

* [bench12](runs/bench12/result.json)

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P | compaction |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - | ---------- |
| gpt-5.5 / xhigh      | 79227/266699      | 50,046,083   | 2,536,707       | Codex   | all        | 0       | 6.41%     | 39.68%  | 75.43%            | 3h 00m 57s | 2 | 131,072    |

### control run

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | compaction |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | ---------- |

## SWE-Milestone — scikit-learn-light v1.0.2 (50M token limit)

### runs

* [bench16](runs/bench16/result.json)
* [bench17](runs/bench17/result.json)
* [bench19](runs/bench19/result.json)
* [bench20](runs/bench20/result.json)
* [bench21](runs/bench21/result.json)
* [bench33](runs/bench33/result.json)
* [bench34](runs/bench34/result.json)
* [bench34](runs/bench35/result.json)
* [bench36](runs/bench36/result.json)
* [bench37](runs/bench37/result.json)

| model/reasoning      | test passes       | total tokens | uncached tokens | harness | conditions | maxrevs | verbosity | erosion | cognitive erosion | time       | P | compaction |
| -------------------- | ----------------- | ------------ | --------------- | ------- | ---------- | ------- | --------- | ------- | ----------------- | ---------- | - | ---------- |
| gpt-5.5 / xhigh      | 79235/79252       | 36,451,765   | 1,444,661       | Codex   | all        | 0       | 6.42%     | 39.64%  | 75.43%            | 2h 53m 36s | 2 | 131,072    |
| gpt-5.5 / xhigh      | 57539/79252       | 50,047,529   | 3,545,641       | Codex   | all        | 3       | 6.44%     | 39.63%  | 75.34%            | 3h 47m 40s | 2 | 131,072    |
| gpt-5.5 / xhigh      | 79234/79252       | 34,993,448   | 2,270,888       | Codex   | all        | 3       | 6.41%     | 39.63%  | 75.35%            | 2h 33m 42s | 1 | 131,072    |
| gpt-5.5 / xhigh      | 64565/79252       | 32,339,056   | 2,099,312       | Codex   | all        | 3       | 6.42%     | 39.58%  | 75.37%            | 2h 35m 50s | 0 | 131,072    |
| gpt-5.5 / xhigh      | 57539/79252       | 50,119,241   | 2,044,489       | Pi      | all        | 3       | 6.44%     | 39.62%  | 75.39%            | 1h 35m 11s | 1 | 255,616    |
| gpt-5.5 / xhigh      | 57536/79252       | 50,121,274   | 1,950,778       | Pi      | all        | 3       | 6.42%     | 39.70%  | 75.41%            | 1h 48m 51s | 1 | 131,072    |
| gpt-6-luna / xhigh   | 79230/79252       | 34,661,945   | 1,498,169       | Codex   | partial    | 3       | 6.40%     | 39.57%  | 75.35%            | 1h 52m 21s | 1 | 131,072    |
| gpt-6-luna / xhigh   | 79235/79252       | 40,565,380   | 1,692,804       | Codex   | partial    | 3       | 6.42%     | 39.72%  | 75.37%            | 2h 40m 02s | 1 | 131,072    |
| gpt-6.1-sol / xhigh  | 79242/79252       | 18,732,192   | 1,039,264       | Codex   | all        | 3       | 6.39%     | 39.61%  | 75.20%            | 2h 42m 08s | 1 | 131,072    |
| gpt-6.1-sol / xhigh  | 79242/79252       | 17,205,223   | 1,057,383       | Codex   | partial    | 3       | 6.39%     | 39.45%  | 75.21%            | 2h 20m 20s | 1 | 131,072    |
| gpt-6.1-sol / xhigh  | 79243/79252       | 15,948,363   | 586,187         | Codex   | all        | 0       | 6.40%     | 39.50%  | 75.24%            | 1h 43m 17s | 2 | 131,072    |


### control run

* [bench18](runs/bench18/result.json)
* [bench22](runs/bench22/result.json)
* [bench23](runs/bench23/result.json)
* [bench38](runs/bench38/result.json)

| mode/reasoning       | test passes | total tokens | uncached tokens | harness | verbosity | erosion | cognitive erosion | time       | compaction |
| -------------------- | ----------- | ------------ | --------------- | ------- | --------- | ------- | ----------------- | ---------- | ---------- |
| gpt-5.5 / xhigh      | 61775/79252 | 32,659,869   | 806,173         | Codex   | 6.42%     | 39.63%  | 75.38%            | 1h 13m 39s | 131,072    |
| gpt-5.5 / xhigh      | 57534/79252 | 50,029,172   | 896,628         | Pi      | 6.44%     | 39.67%  | 75.44%            | 1h 15m 38s | 255,616    |
| gpt-5.5 / xhigh      | 57536/79252 | 50,151,058   | 1,373,330       | Pi      | 6.46%     | 39.62%  | 75.35%            | 1h 26m 29s | 131,072    |
| gpt-6.1-sol / xhigh  | 79244/79252 | 9,194,682    | 532,282         | Codex   | 6.40%     | 39.45%  | 75.28%            | 1h 12m 36s | 131,072    |
