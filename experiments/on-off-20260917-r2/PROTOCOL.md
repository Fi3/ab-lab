# Replacement three-all-on versus three-all-off comparison

Frozen before full-workflow generation, 2026-09-17 19:02 UTC.

## Authority and advance gate

The [user-approved repair and replacement scope](REPAIR-AND-RUN-AUTHORITY.md)
admits exactly six fresh workflows after the small real check passes.
[Qualification](QUALIFICATION.md) passes: all 43 automated tests, actual priced
interruption, compact conflict recovery, natural finish, real checks and
complete measured usage. Previous failed attempts remain unchanged and are not
observations in this new comparison. No ordinary Work Leaf control is added.

## Six observations and fixed comparison

Run-data root: `runs/on-off-20260917-r2/`.

1. Start `on-01`, `on-02`, `on-03` concurrently with all nine switches true.
2. After that wave ends, start `off-01`, `off-02`, `off-03` concurrently with
   C08,C13,C14,C15,C16,C17,C20,C25,C38 explicitly false.

Exactly six complete-workflow attempts; no automatic replacements, extra pilots
or tuning between observations. A failed attempt remains failed. The earlier
small verification is not a seventh effect-size observation.

Input is `benchmarks/work-leaf.json`, SHA256
`beace51ce596f9c5afb6329d0a132e7dddf716b24b47c321b41dcd15c3aa613e`, starting
commit `c92a0b7060a36eac6db2d869b85e589a7a9480f9`. Each run has a separate
checkout. Keep the same three feature requests and sequential implementation,
independent review, repair/re-review, final plan/accept and one final commit per
feature. Keep all required checks and exact frozen external scoring fixtures.
No artificial conflict is inserted; enabling C08 does not prove it operated.

Both groups use Codex 0.154.0, GPT-5.5/xhigh, existing ChatGPT login and
`CARGO_BUILD_JOBS=4`. No API keys/credits, copied credentials or provider/model
substitution. The non-generating preflight and actual configuration readbacks
must match qualification. All author instruction combinations remain identical
to the previous code; no current supervisor instructions enter measured prompts.

The repaired C25 waits for usage covering the requested operation before
discretionary interruption. It does not cancel an unpriced intermediate model
response merely because output resumes or a short grace expires. This timing
differs explicitly from the retained failed batch. C25 remains enabled in the
on group and its actual interruption events must be reported. All other factor
definitions, host operations and workflow stages remain fixed.

## Limits and live accounting gate

Each run keeps the preceding prospective ceilings: 5,400 seconds (90 minutes),
60,000,000 observed raw tokens, 600 agent turns; host commands at most 300
seconds within the remaining run limit. These are stopping ceilings, not usage
targets. In-flight or delayed usage can overshoot an observed-token tripwire.
No ceiling is extended after launch. Final passive usage collection can take
up to five seconds; operator and safety cancellations retain incomplete tails.

The runner rejects a returned incomplete measurement before further host work
or another agent turn. Observe all six folders with `python3 -m lab.monitor`
every 15 seconds; retain its current snapshot and complete sample history.
The operator checks live coverage gaps, counter warnings, process ownership,
stages, limits and resources, updating root `ephemeral-note.md` within 60 seconds.
A common setup/authentication/accounting/source-integrity failure stops unsafe
further generation. Use SIGINT only against verified owned runner PIDs so usage
draining and retained result publication run. Preserve all prior outcomes.
An unfavorable measured total alone does not stop the approved six-run study.

## Analysis and stopping point

The [retained original protocol](../on-off-20260917/PROTOCOL.md) owns the
unchanged input, final checks, frozen feature scorer, raw-token definition and
comparison rules. Post-run provider-free scoring uses separate final-result
clones only after generation ends; no model repair follows a scoring failure.

Verify complete final results, all source/configuration pins, thread ownership,
cumulative usage and late coverage for all six. If all six qualify, report every
raw total, each three-run arithmetic mean and range, and
`100 * (mean_off - mean_on) / mean_off`. Raw is input plus output; cached input
and reasoning are not added again. No successful-subset percentage is presented
as the complete three-versus-three comparison when an observation is missing.

Roughly 50% is an expectation, not an acceptance target. A smaller, absent or
reversed difference is a result. The old 18.545M reproduction and 36.116M Direct
mean are descriptive references only. These on-first/off-second groups are not
randomized, and do not assign savings to individual switches.

Stop after the six retained outcomes, local scoring/accounting verification and
the result report. Do not restart the old Work Leaf research ledger or launch
additional unapproved generation.

## Frozen program SHA256

| File | SHA256 |
| --- | --- |
| `lab/__init__.py` | `cd5de7ee4472c1ef8bada6b3b56d56cee36d93dbfab9195d2dcfc0c7d7be13a1` |
| `lab/__main__.py` | `0271f5c7bfd985a08c353e0b6e12002bbbabb9a0997bfff879492273f288f1df` |
| `lab/config.py` | `0c7c7f6c4446843187f23e819b616bd5ee7197be58aac7d1ffb06ea6d416be16` |
| `lab/host.py` | `a81595b8b0742557ea4f4e478fc2dd7813fbfd1d926ebd6da40b20c9d4167f2b` |
| `lab/monitor.py` | `2009e3400ee428d82f0290588c96d8f92b7f66b9f5018054149b1072a69d2e8c` |
| `lab/provider.py` | `ac76a6a74a864dbe843812e025a34bce93f242a0724edda121f52bddf1141f20` |
| `lab/workflow.py` | `c24441f5713f35b3a1ce97b95ed8ca35a274d37197d7b86b7cd8f930dd7946a6` |
