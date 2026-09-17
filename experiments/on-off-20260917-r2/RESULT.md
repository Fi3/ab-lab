# Replacement comparison: stopped at native Git permissions

There is **no valid three-on versus three-off saving percentage**. Two all-on
workflows completed all three feature implementation/review loops, but their
final integration agents could not write Git metadata. The remaining workflow
was stopped after that shared setup failure was confirmed. All-off was not
started. These are retained failed attempts, not successful benchmarks.

| Run | Reviewed features completed | Observed raw tokens | Outcome |
| --- | ---: | ---: | --- |
| on-01 | 3 | 18,364,740 | Final history rewrite denied; reported usage complete |
| on-02 | 2 | 19,452,278 | Operator-stopped during feature 3 repair; one incomplete cancellation tail |
| on-03 | 3 | 19,340,267 | Final history rewrite denied; reported usage complete |
| off-01, off-02, off-03 | 0 | Not run | Withheld after shared setup failure |

The group ran concurrently from 19:04:41 to approximately 20:11:30 UTC on
2026-09-17. Observed usage totals **57,157,285 raw tokens**, input plus output
with cached input counted once. This excludes any unreported part of the last
operator-cancelled response; it is not a completed-workflow total. The repaired
interruption path has no earlier missing returned-response count in these runs.
All provider processes and the observer are stopped. No additional model call,
automatic replacement or off observation follows this failure.

## Exact failure

The admitted source is commit `746630e`, pinned in [PROTOCOL.md](PROTOCOL.md).
Its call chain is `lab/workflow.py::run` →
`Codex.turn(..., writable=True)` → a `workspaceWrite` sandbox whose writable
roots contain only the checkout. Git's metadata directory remains protected.
The integrator can edit ordinary files but cannot create `.git/index.lock`.
It reports the blocker without rewriting history, and the workflow then fails
its exactly-three-final-commits check. None of the runner's final Rust checks
executes after that failed structural gate.

Both failed agents actually report `Read-only file system` for the Git lock:

- `runs/on-off-20260917-r2/on-01/provider/turn-0096/reply.txt`.
- `runs/on-off-20260917-r2/on-03/provider/turn-0109/reply.txt`.

The saved native command output supports these reports; they are not an
inference from a generic final error. Ordinary feature edits worked because
the external host, outside the agent sandbox, made those commits. Native
all-off authors would also need the missing Git-write permission.

The [official permission documentation](https://learn.chatgpt.com/docs/permissions)
distinguishes writable workspace files from protected metadata directories.
Its [app-server command documentation](https://learn.chatgpt.com/docs/app-server#command-execution)
also supplies a zero-generation way to exercise the same sandbox policy.

## Why the earlier verification missed it

`runs/real-integration-001/result.json` says PASS, but its starting checkout
already has exactly the required two feature commits. Its agent reply explicitly
says that no history rewrite was needed. The old verifier checked the final
commit count and passing tests, not whether the agent could actually write Git
metadata. The output history is unchanged from its input.

That record remains untouched. It proves the inspected final shape and tests,
**not native commit/history-write capability**. The earlier broader verification
claim was wrong. This missing preflight could have been caught before the
65-minute workflows; the small accounting check did not cover it either.

## Local repair and evidence — no model generation

The retained [probe script](probe_git_permissions.py) uses Codex's actual local
`command/exec` sandbox on a separate empty Git fixture. It never starts a model
thread or turn and does not touch a benchmark checkout.

- The original policy returns exit 128, cannot create the index lock, and leaves
  HEAD unchanged.
- The same Git command with the checkout's `.git` directory explicitly writable
  returns exit 0 and creates an actual commit. Network access remains off; no
  parent directory or unrelated checkout receives write access.
- `git-command-probe-002` additionally exercises the repaired provider's real
  preflight and its actual policy helper. Both local probes use zero model turns
  and zero raw tokens. Records are under `runs/on-off-20260917-r2/`.

The repair follows these verified boundaries:

1. Writable author/integration turns allow only the owned checkout and its
   `.git` directory. Read-only authors and reviewers remain read-only.
2. Before any model generation, each fresh workflow tests native Git index-write
   access in its clean clone. Failure retains a receipt and stops immediately.
   The non-generating account/configuration `doctor` does not modify Git state.
3. The real integration fixture contains an extra disposable commit that must
   be collapsed. An unchanged history cannot pass its verifier.

Five initial regressions give two assertion failures and two missing-feature
errors before the fix; the unchanged read-only restriction test already passes.
They pass after the fix. A further positive history-collapse check covers the
acceptance side. Full Python tests and compilation are recorded in
[VERIFICATION.md](../../VERIFICATION.md).

**The stricter real-agent history-rewrite check has not been run.** The native
sandbox command is verified, but that is not a new complete agent workflow.
The repair was made only after all admitted benchmark processes stopped; the
failed records and their original source pins remain unchanged. No result
combines their old program with a silently changed off group.

## Accounting audit and retained work

[ACCOUNTING-AUDIT.json](ACCOUNTING-AUDIT.json) independently sums the saved
transport and checks all 20 native conversation histories. All available native
totals match transport, every charged conversation belongs to its runner, and
there are no counter decreases. All three non-switch comparison fingerprints
match. On-01/on-03 have no uncovered returned turn; on-02 has only its deliberate
last cancellation. Its unknown tail is not counted as zero.

The feature scoring fixtures are not run against partial or non-final source.
The full checkouts, temporary commits, completed reviews, unfinished repair,
prompts, replies, command receipts, token events and 15-second observation history
remain under `runs/on-off-20260917-r2/`. The first failed batch remains separate
under `runs/on-off-20260917/`. Neither changes Work Leaf's old research ledger.

## Continuation boundary

The approved six-attempt protocol does not authorize replacement observations
or extra generated diagnostics. A small real rewrite check is the next missing
qualification, not another whole benchmark. Before further generation, obtain
a prospective admission that preserves these failures and explicitly addresses
saved-work reuse and the interrupted response. Do not automatically discard
the completed feature work or launch another fresh six-run batch.

The expected roughly 50% reduction is neither confirmed nor disproved here.
