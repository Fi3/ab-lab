# Repair qualification

Checked 2026-09-17 19:02 UTC. All three repair obligations are verified for
replacement-batch admission, not for an effect-size conclusion.

| Obligation | Evidence |
| --- | --- |
| Usage-preserving request interruption | Eight fail-first regressions; real intermediate request followed by an actual `usage_received` interruption; all six real turns have complete coverage |
| Stop before further work after missing measurement | Regression shows the unmeasured author's proposed edit is not applied and no reviewer or additional turn starts; the partial result is retained |
| Visible live per-response coverage | Incremental journal tests, including repeated samples; old failed records report 24/1/45 gaps, including operator cancellations; real six-turn journal reports zero gaps |

All 43 Python tests and compilation pass. Author prompts match the preceding
committed implementation byte for byte for all 320 valid switch combinations.
The host operations and review/integration prompts are unchanged. No Work Leaf
product code or historical research counter is modified. The new observer reads
only appended bytes and retains per-turn identity; it does not rescan every old
turn on each sample or inject any extra prompt text.

The real scenario is `runs/on-off-20260917-r2/real-usage-001`: 37.59 seconds,
76,865 raw tokens, five actual interruptions after fresh usage and one natural
finish with interruption disabled. It exercises a real compact stale-edit
refresh, corrected accepted edit, host test and completion. No report is missing.
Provider: Codex 0.154.0, GPT-5.5/xhigh, existing ChatGPT subscription.

Pins:

- Real result SHA256: `c61ab6d73aae1f35d2eeb393266cffb816edbe823b4e7fa887b1e081a5d0673c`.
- Real transport SHA256: `09ca6a40c9d728494dd5691b4a8d30aa3eb53153cbc557601b15bc40ec4da98c`.
- Effective configuration SHA256: `3398a4ddf498ad5c24906081499dadabf9398e5065cf7ece5d6d3e6a1439c3d8`.
- Program hashes in the real admission exactly equal the replacement protocol.

This small check does not guarantee every later response will be measured.
The full workflow must stop immediately after a returned missing measurement;
the operator observes live coverage and preserves any failed attempt. No
favorable small-test token total is inserted into the benchmark means.
