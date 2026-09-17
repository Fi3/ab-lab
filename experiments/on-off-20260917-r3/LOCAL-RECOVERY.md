# Retained-data recovery after the nested-call accounting failure

Prospective local-only check, 2026-09-17 21:12 UTC. Ceiling: 15 minutes, zero
model calls, zero new benchmark observations. No source repair or frozen outcome
mutation. The aim is to recover all discoverable nested-call usage, distinguish
the no-commit outcome from the shared accounting defect, and preserve exact
evidence before proposing any further generated work.

The runner records only its app-server's thread counters. Run on-02's saved
second host command launches a separate Codex process and resumes it. Its stdout
reports two charges: 17,551 input + 40 output, then 165,739 input + 1,511 output.
Their sum is 184,841 raw. That thread ID is absent from the runner's charged
thread list. This is a concrete omission despite the main-provider report saying
measurement_complete=true. The exact child ID is
`01a0b132-e18a-7141-a50f-ca926accbd7c`.

At 21:11:31 UTC, verify the identities and SIGINT the remaining owned runners
1320896 and 1320906. They drain and retain one incomplete cancellation tail each.
On-02 was already terminal. Stop observer 1320876 after final snapshots. All-off
is unstarted. Preserve every reviewed source, original total and usage event.

Read native history metadata for the exact owned checkout directories and compare
all discovered conversation IDs to the parent runner's IDs. Reconcile separate
exec/resume totals using their saved session events, not an assumption that an
app-server counter includes a shell-launched child. Retain any unpriceable tail.
Read the no-commit run's actual feature input, replies and source to identify why
it declared completion. Do not turn a failed run into a successful benchmark.

The small Git-rewrite check's pass remains valid for that behavior. It did not
exercise either a nested verification process or completion without a new commit.
No automatic tiny retry, resumed observation, source change or full rerun follows.

## Terminal local result

The [result](RESULT.md) and [native-history query](NESTED-USAGE-AUDIT.json)
recover exactly 167,250 child tokens. The initial 184,841 figure above is a
double count: the second CLI report includes the first report's 17,591 tokens.
Seven distinct response prices reconcile exactly to the final native cumulative
total. The child also uses GPT-6 Astra/max rather than the pinned model; its
actual usage records report the Pro plan. The main provider's model, auth and
accounting controls do not cover this host-launched process. The current
no-commit gate rejects the separate already-present-code completion path.
No source repair or further model generation occurs. All observed usage is
21,175,267 raw, plus two still-unknown operator-cancellation tails.

At 21:24 UTC, replay reproduces the saved audit except its timestamp. All 49
existing tests, compilation and whitespace checks pass; they do not cover the
two discovered boundaries. This local allocation ends before its 15-minute
ceiling. No measured source change or model-backed verification is performed.
