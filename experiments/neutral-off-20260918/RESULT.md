# Neutral OFF verification result

C13/C14/C15/C16 OFF contribute no extra validation, edit-grouping, test-order or
edit-format instruction. Existing agent/repository rules remain in force.
C16 OFF accepts both supported host patch formats; rejected-edit refresh uses
the submitted format. All enabled author instructions remain byte-identical.
Other switches, permissions, usage handling and the complete workflow sequence
retain their previous implementation.

## Automated checks

Before repair, three selected regression methods produced seven failing
assertions: all four opposite policy instructions, structured-edit acceptance,
and compact/full refresh for a rejected structured edit. All 84 tests pass after
repair, including 14 neutral-OFF regression methods. Coverage includes all sixteen instruction
combinations in both execution modes, malformed-edit rejection and correction,
path safety, repository-rule preservation and author/review/repair/integration.
Python compilation, CLI factor/plan readback and `git diff --check` also pass.
Existing tests are untouched. Only `lab/config.py` and `lab/host.py` differ from
the preceding runner's implementation hashes; Work Leaf source is unchanged.

## Real-agent checks

The two bounded checks use the existing ChatGPT subscription with GPT-5.5/xhigh.
Each implements `negate(value)` and its positive/negative/zero tests, preserves
`identity`, commits clean source, and passes four repository tests plus independent
value assertions. All four instructions are disabled in both checks.

| Execution | Outcome | Duration | Recorded raw tokens |
| --- | --- | ---: | ---: |
| Agent edits directly | PASS: normal native patch tool changes code and tests together | 51.42 seconds | 103,510 |
| External runner applies edits | PASS: structured code-and-tests patch accepted with C16 OFF | 62.39 seconds | 92,500 |

The direct path uses one agent turn. The host path uses seven operation/result
turns, including a rejected read of a nonexistent test filename followed by
successful inspection and correction. Neither path is instructed to use a
particular edit format. Both usage records are complete; total verification
cost is 196,010 raw tokens. These are functional checks, not a savings comparison.
No full benchmark or prior failed observation is repeated.

[Prospective scope](QUALIFICATION.md) ·
[Direct result](../../runs/neutral-off-20260918/native-001/result.json) ·
[Runner-managed result](../../runs/neutral-off-20260918/host-001/result.json) ·
[Runner operation evidence](../../runs/neutral-off-20260918/host-001/host/evidence.txt).

Result SHA-256 values:

- Direct: `7fe7916ba16f176db2e6bd166fbb0f088495a845d961e5e6498d23bc8e937652`.
- Runner-managed: `8930db98f49b7120e5dafdacfe86d5b583f1d3ee2c70185b786cecd48a87a7e6`.

Earlier opposite-policy measurements keep their original prompts and outcomes.
They are not measurements of neutral OFF behavior and are not relabeled.
