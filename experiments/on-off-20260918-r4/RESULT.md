# Six-run validation result

All admitted model execution, external feature checks and accounting audits are
finished. **The requested complete three-all-on versus three-all-off validation
is not achieved.** Two all-off workflows exhaust their 90-minute active-time
allowance before finishing. No approximately 50% three-versus-three reduction
is established by this batch.

All-on means all nine configurable behaviors are enabled; all-off disables all
nine. A workflow includes all three coding tasks, independent reviews and
repairs, final integration and repository checks. Raw tokens are input plus
output, with cached input counted once. Parent and command-launched child
conversations are both included.

## Retained outcomes

| Workflow | Recorded raw tokens | Original endpoint | External feature checks |
| --- | ---: | --- | --- |
| All-on 1 | 25,673,000 | All stages and repository checks pass | 2/3 |
| All-on 2 | 22,490,575 | All agent stages finish; final host test fails | Not scored under the frozen failed-workflow rule |
| All-on 3 | 26,119,875 | All stages and repository checks pass | 2/3 |
| All-off 1, continued | 40,043,900 observed | Time limit during final integration planning | Not scored: unfinished |
| All-off 2, continued | 37,167,934 observed; final response price missing | Time limit during third-feature implementation | Not scored: unfinished |
| All-off 3, continued | 42,177,372 | All stages and repository checks pass | 3/3 |

All three all-on results are reused without new model work. The earlier r3
all-on attempts were not complete; the current r4 results above are not rerun.
Each all-off continuation retains its original first-feature work and costs.
The earlier parser-failure records remain intact; they are not additional
independent observations or extra charges in these cumulative totals.

All-on 2's failed test is
`terminal_app_does_not_run_project_required_checks_outside_agent`, which expected
`launch reply` in a terminal frame. One focused repeat and one complete test-suite
repeat both pass on the **same unchanged source commit**
`b7b296edafaa0fb132279fde4666236efd097a5b`, using no model calls. This shows the
failure does not reproduce in that diagnostic. It does not erase the original
failure or silently turn its original result into a pass.

The external tests are unchanged checks supplied outside the coding agents'
own tests. Both complete all-on workflows pass visual selection and slash
routing, but fail completion behavior. All-on 1 does not display the required
completion question in the test's selected chat. All-on 3 does not show the
required visible closure after `yes`. All-off 3 passes all three checks. No
generated benchmark source is repaired after these scores.

## What the numbers do and do not say

The three all-on executions average **24,761,150 raw tokens**. The **one** complete
all-off workflow uses **42,177,372**. Thus the former is **41.2928% lower** than
that single all-off result:

`100 × (42,177,372 − 24,761,150) / 42,177,372`.

This is a descriptive comparison of those recorded costs, **not the requested
three-versus-three result**. It includes the all-on run with the original host
test failure. It does not average the unfinished all-off costs into completed
workflow costs, establish equal quality, allocate individual behavior effects,
or prove or disprove the earlier Work Leaf result. The expected approximately
50% reduction is not an acceptance target and does not justify rerunning an
unfavorable result.

Total observed generation in these six observations is **193,672,656 raw**,
including the saved first-feature work once. One interrupted response's price
is missing. Earlier failed batches and small qualifications remain separate.

## Accounting and recovery evidence

The independent audit reproduces every observed total from original plus
continuation transport records and native parent/child histories. It verifies
the archived pre-continuation native prefixes, source bundles, prior-result
hashes, preserved factors and original allocations. There is no model/effort,
subscription-plan, parent/child overlap or recorded-counter discrepancy.

All-off 2 has one interrupted parent response without a subsequent fresh price;
its two diagnostic flags describe that same response, not two missing responses.
All-off 1's last delivered message does have a later price and the independent
record audit finds no missing returned count. Its runner still conservatively
marks the interrupted planning turn incomplete. Neither run finishes the full
workflow, irrespective of this accounting distinction. Missing usage is not zero.

The completion-marker parser accepts a unique final `@standalone done` line
after a summary. Clean source, independent review and final checks remain
required. A real subscription resume qualification reproduces **11,270 prior +
11,302 additional = 22,572 cumulative raw**, without repeating the first response.
All 70 local tests, Python compilation and whitespace validation pass. The
completed real all-off 3 workflow also exercises the repaired parser and recovery
through all remaining stages.

The continuation uses commit `196b660`; original execution uses `3f54c08`.
Measured prompt functions are structurally identical; provider, host, factor,
environment and nested-launcher modules have identical hashes. The changed
native completion acceptance and explicit recovery path remain documented,
not hidden by forcing matching comparison keys. The supervisory repair pauses
are 41.63, 23.98 and 41.57 minutes, separate from the original 90 active minutes.

Four automatically added trusted-folder entries explain the configuration-hash
difference exactly. Their recorded equivalence proof retains both hashes and
removes only redundant entries in memory. No global configuration is edited by
the recovery code, and no credential is copied. Generation uses the existing
ChatGPT subscription, Codex 0.154.0 and GPT-5.5/xhigh; no API-key generation.

## Limits and remaining work

The 90-minute active-time allocation is insufficient for two all-off workflows.
The time-limit drain is retained: about 1.15 seconds extra for all-off 1 and 5.10
seconds for all-off 2. The bound is not silently extended, and capped results
are not replaced by invented complete totals.

Native commands also retain network restrictions that external host commands
do not have. Saved all-off author commands encounter local-server permission
failures and recovery work. Native integration in all-on runs also encounters
restrictions. Consequently this broad profile comparison cannot isolate only
instruction/edit effects from command-execution restrictions. Native repair
feedback also withholds the author's detailed reply from the reviewer; all-off
1 repeats a verification-evidence exchange before recording it in a commit.
These observed differences are retained, not retrospectively repaired in the
measured runs. The on-first batch order is not randomized.

The test execution is finished; successful full validation is not. No new model
observation, automatic replacement, all-on repeat or budget extension is selected.
Completing a strict three-versus-three comparison needs a separately admitted
execution plan for the unfinished all-off work, including an explicit treatment
of all-off 2's missing price. Simply resuming it does not justify assuming that
missing charge is recovered. All existing successful work must remain reusable.

## Evidence and reproduction

- [Machine-readable result](SUMMARY.json), [original freeze](FREEZE.json),
  [continuation freeze](CONTINUATION-FREEZE.json), [recovery scope](NATIVE-CONTINUATION.md).
- `runs/on-off-20260918-r4/accounting-original.json` preserves the pre-continuation
  audit. `accounting-final.json` records the linked six-outcome audit.
- Each original and continued directory retains its manifest, result, source,
  prompts, transport, native-history links and command receipts. Continued
  directories also retain a source bundle and archived earlier native histories.
- `runs/on-off-20260918-r4/feature-scores/` contains all six scoring outcomes;
  failed or unfinished workflows retain explicit `not_scored` results.
- `runs/on-off-20260918-r4/diagnostic-on-02/` contains the two unchanged-source
  diagnostic commands, output and receipts. Its scope is [FINAL-CHECK-PLAN.json](FINAL-CHECK-PLAN.json).

Reproduce the read-only final audit with a fresh output filename:

```sh
python3 experiments/on-off-20260918-r4/audit.py \
  runs/on-off-20260918-r4/on-01 runs/on-off-20260918-r4/on-02 \
  runs/on-off-20260918-r4/on-03 runs/on-off-20260918-r4/off-01-continued \
  runs/on-off-20260918-r4/off-02-continued runs/on-off-20260918-r4/off-03-continued \
  --continuation-freeze experiments/on-off-20260918-r4/CONTINUATION-FREEZE.json \
  --output runs/on-off-20260918-r4/accounting-recheck.json
```

Raw run artifacts are retained locally under ignored `runs/`; compact results,
protocols, repaired code and regression tests are committed. The closed Work
Leaf research ledger and normal Work Leaf source are not changed by this task.
