# Verification

## Typed host delivery and review receipt settlement — 2026-09-29

The completed verification is retained under
`runs/review-settlement-verification-20260928`. The original `p012-7` run and
the subsequent v2 verification run remain unchanged. This section extends the
earlier typed-host verification below; its statement that no full rerun had
been performed describes that earlier verification only.

The typed-host fix reproduced the original checkpoint 4 command/prose loop
before introducing a closed JSON operation schema and exact conversion to the
existing host protocol. A subsequent full model run got through checkpoint 5
implementation, but exposed a separate failure: the hard 90-second review
conclusion limit cancelled the first in-flight response before it had an owned
numeric receipt. The last reported counters still belonged to the prior turn.
That was an unpriced cancelled response, not evidence of a delayed receipt.

Policy `bounded-feature-review-v3` deliberately changes the time-limit behavior:
a review time threshold can wait up to 600 seconds for the current response's
accounted boundary. It retains the first timeout, requires fresh owned usage,
and gives hard token/global limits and provider errors precedence. A hard-stopped
review remains unapproved even if verdict text arrives while settling. Missing
receipts remain terminal. This is a versioned policy change, not an unchanged-v2
control or a retry of the original upstream policy refusal.

Verification against the frozen implementation includes:

- **437 framework tests passed in 110.218 seconds**, including 25 focused Codex
  and Pi settlement tests and real workflow continuation checks. Pre-fix failure
  evidence is retained separately. Tests from a temporarily restricted session
  failed on its outer filesystem/socket sandbox; the final unrestricted suite
  passed. The interrupted and restricted logs were preserved.
- A fresh installed-Codex review crossed a deliberately short one-second hard
  review threshold and finished with **13,386 raw tokens**, independently
  reconciled with owned native receipts. Its retained `NO_FINDINGS` text remained
  ineligible for approval. No refused request was replayed.
- The full five-checkpoint model run completed implementation attempts,
  integration, final checks, quality measurements, and all upstream evaluations
  in **6,793.917 seconds**. Its **12,808,554 raw / 10,814,976 cached input tokens**
  reconcile exactly with **220 unique owned native receipts**, including five
  compactions, across 130 turns and 11 threads. All 111 delivered typed host
  operations preserve the requested fields; one structured turn was quarantined
  at its token limit. There are no nested model costs.
- The frozen full-run audit and the settlement supplement both passed independently. They
  verify all 25 runner source hashes, declared policy/settings, preserved prior
  artifacts, final checks, six captured source trees and grades. The supplement
  also exercises 4 positive and 29 negative offline controls. The retained
  effective-config digests differ from the prior run; the unlogged private
  config values cannot be reconstructed, so the audit does not attribute that
  difference. Retained request settings and pinned runtime inputs agree.

There was no malformed outer host-operation loop or upstream policy rejection
in this completed run. This establishes observed non-recurrence; it does not
establish a general guarantee about future provider policy decisions. Review
time settlement was exercised twice, including token-threshold preemption with
complete accounting. Other checkpoint stops retained their real token limits
and unapproved outcomes.

The generated solution is **not a benchmark solve**. Upstream grades are
**13/13, 25/25, 43/47, 70/75, and 95/104** for checkpoints 1–5, and **95/104** for
final assembly. All evaluations completed without infrastructure failure.
Checkpoints 3–5 remain `needs_attention`; the final workflow records
`execution_status: completed`, `measurement_complete: true`, and `solved: false`.
Passing framework audits must not be presented as passing solution grades.

Primary records are `full-run-audit.json`, `full-run-settlement-audit.json`,
`full-benchmark/result.json`, `full-tests-unrestricted.log`, and
`independent-live-audit.json` in the verification directory. Separate reports
reproduce the rejected patch ambiguities and verify compaction trigger inputs;
neither investigation found a stale-source or cumulative-context-counter defect
in the examined cases.

### Separate repaired searcher — 2026-09-29

After inspecting the completed grades, a separate checkout was cloned from the
final generated commit `a3a50b6e870fffee3ce45672e567982bb395ac62` under
`runs/code-search-repair-20260929/checkout`. The original autonomous run and all
its checkpoint grades remain unchanged. This is an explicitly post-run repair,
not an uncontaminated autonomous benchmark solve.

Synthetic tests reproduced the missing/extra semicolon ranges, absent optional
capture output, escaped Python dollar identifier, Go EOF call parsing and Go
interface declaration range failures before changes. The repair preserves
explicit statement terminators, keeps whole-element captures inside their match
ranges, normalizes Go EOF parsing without changing original coordinates, and
selects complete named interfaces. Compatibility decisions to omit empty
`captures` and tolerate escaped dollar-prefixed Python identifiers are documented:
the evaluator expectations are not fully consistent with the literal public
schema/valid-Python requirement. No upstream test or grade was changed.

Independent review found two additional semicolon cases. Both were reproduced,
fixed and rechecked. The final repaired source passes **43 local tests** and
**104/104 unchanged upstream tests**, including all earlier regression tests.
The upstream bridge and pytest both exited zero; no infrastructure failure
occurred. Evaluation `evaluation-02` grades the final seven-file `repair-02`
snapshot. `solution-repair.patch` was applied to a temporary copy of the original
commit and reconstructed every final source hash exactly.
`independent-repair-02-verification.json` independently confirms all 104 actual
passed cases, identical test collection/runtime, seven evaluated source hashes,
unchanged evaluator/test Git blobs, and preservation of original results.

Repair evidence, independent review, immutable snapshots, patch and evaluation
receipts are retained in `runs/code-search-repair-20260929`. These passing repaired
artifact results do not replace the original run's `95/104` final grade or its
unapproved checkpoint outcomes.

## Review conclusion recovery and installed benchmark checks — 2026-09-27

The v1 review cap stopped `scb-code-search-all-on-p012-4` during checkpoint 3's
first review at **527,738 raw tokens**, with **zero repairs**. This was budget
exhaustion, not evidence of a convergence loop. The v1 tests below verified
cancellation but did not establish that immediate termination was appropriate.

Policy `bounded-feature-review-v2` makes the ordinary 500,000-token / 300-second
review threshold request one conclusion from the same reviewer. The conclusion
is bounded by 200,000 additional raw tokens, 90 seconds, and the remaining
feature/global budgets. A completed, fully accounted verdict is retained;
findings enter normal repairs. `INCOMPLETE_REVIEW` never becomes approval.
Actual repetitions, repair limits and hard feature/global budgets still stop
work. Ordinary interrupted reviews are no longer labelled final reviews.

Completed verification is retained under
`runs/review-wrapup-verification-20260927`:

- **355 framework tests passed** in **98.884 seconds**, including the exact
  twelve-response usage sequence from the failed first review, completed-verdict
  races, same-thread conclusion and repair, missing usage, hard conclusion limits,
  feature-budget precedence, honest incomplete verdicts, both provider streams,
  and the existing compaction, isolation, batch and grading checks.
- Installed Codex exercised interruption followed by a same-thread conclusion.
  One check returned approval (**25,496 raw tokens**); a check deliberately stopped
  before any independent inspection returned `INCOMPLETE_REVIEW` with approval
  unset (**26,286 raw tokens**). Both totals equal independently summed owned
  native response receipts. Verification fixtures remained unchanged. These tiny
  threshold checks exercise transport behavior, not default-budget calibration.
- The real one-checkpoint smoke workflow completed implementation, three reviews,
  two repairs, integration, final checks, quality measurements, and upstream
  grading. The reviewed checkpoint passed **13/13**, and final assembly passed
  **13/13**, with **1,664,167 raw tokens** and complete accounting. This is a solve
  of the selected one-checkpoint scope.
- The installed upstream evaluator passed unchanged reference snapshots for all
  five checkpoints: **13/13, 25/25, 47/47, 75/75, 104/104**. These are separate
  evaluator controls, not the generated full benchmark's results.

The full five-checkpoint model run in `full-benchmark` used the prior model,
factors and global limits: GPT-5.5/xhigh, all factors, P0/P1/P2,
15 million raw tokens, 10,800 seconds, 1,000 turns, and skipped linearization.
Its checkpoint 3 review 3 reached **534,946 raw tokens**. The same reviewer
returned concrete findings in a bounded conclusion costing **98,889 tokens**.
The run ended `needs_attention` with unresolved matcher defects; checkpoints 1
and 2 passed **13/13** and **25/25**, while checkpoints 3–5 remained ungraded.
The total was **3,720,660 raw tokens**, completely accounted, in **2,143.502
seconds**. This is not a solve of the five-checkpoint task.

That live run also exposed a redundant final review: the ordinary author
allowance was already exhausted and the source had just been rejected. The
final guard now retains that verdict immediately and does not count a repair
that never started. If an actual repair stops with the same previously rejected
tree, it likewise does not buy another review. Changed code still gets its
reserved final review. Two new regression cases fail before this correction
and pass afterwards. Replaying the full run's recorded stage costs and verdict
signatures through the real workflow/Git/host code stops after review 3's
conclusion, at **2,692,026 feature tokens**, with **two actual repairs** and no
fourth review. This replay is not a new model run or a promised saving on a
future nondeterministic run. The full and smoke model runs precede this final
stop-condition correction; their original artifacts and source hashes remain
unchanged. Historical run results and generated solutions are preserved.

After the final correction, the complete 355-test suite passed again. An
installed-Codex check against the final source was interrupted before its verdict,
then returned approval in the same thread's conclusion, with **26,146 raw
tokens** matching independent native receipts. `native-wrapup-final/result.json`
records source hashes matching the final runner. The independent accounting
audit also reconciles all **91 responses** in the full model run and **61
responses** in the smoke run exactly; neither has missing usage or compactions.
`verification.json` records these results and the precise source-version scope.

## Bounded feature loops and review handoffs — 2026-09-27 (v1, superseded above)

Features now stop on repeated rejected source trees, repeated blocking findings,
repeating host-operation cycles, repair-attempt limits, or feature/review budgets.
Budget exhaustion and repetition are recorded as different trigger kinds.
Author stops can receive one bounded final review of clean, committed code.
Approval permits continuation with the flag retained; otherwise the workflow
ends as `needs_attention`, with later dependent features blocked and an owned
handoff packet containing source, requirements, findings and evidence paths.
Independent batch repetitions still proceed. No stronger model is automatically
invoked, and a stopped attempt is never recorded as reviewer approval.

The full `python3 -m unittest discover -s tests -q` suite passed **341 tests** in
**93.068 seconds**. New workflow tests use scripted provider responses with real
Git operations and shell commands: repeated reads, two-operation cycles,
unchanged/revisited trees, persistent findings despite changing code, successful
last repairs, final-review approval/rejection/failure, pending edits, dirty native
work, usage overshoot and independent batch continuation. Stream tests enforce
limits inside both Codex and Pi turns while retaining late numeric usage. The
recorded native compaction fixture verifies that compaction consumes the feature
budget and cannot trigger a further generation after exhausting it.

The initial run inside the outer workspace sandbox encountered **15 permission
failures** in existing sandbox-integration checks. The approved rerun outside
that outer sandbox passed all tests. Both outcomes are retained under
`runs/loop-stop-verification-20260927`, alongside source hashes and trace replay.

Applying the default token policy to the saved `scb-code-search-all-on-p012-3`
usage receipts first reaches the review allowance during **checkpoint 3 review
3**, at **3,358,308 run tokens / 2,308,066 feature tokens**. With token caps
excluded, the saved review/tree sequence reaches the three-repair limit after
**review 4**. These are deterministic replays of historical observations, not a
new model run, a promised saving, or a claim that the feature would pass.
Historical benchmark artifacts and generated solutions were not modified.

## Real Codex compaction accounting and test execution — 2026-09-26

The earlier recovery tests used synthetic compaction events whose app-server
counters increased. That missed the installed Codex behavior: compaction
completes and reduces context, but its numeric cost appears in the owned native
rollout while app-server cumulative counters stay unchanged. The framework
incorrectly rejected that successful compaction as unpriced. This section
supersedes the earlier mock-only verification for compaction accounting.

The original `p012-2` event sequence is retained as a sanitized regression
fixture. Its final compaction costs **112,416 tokens**, despite unchanged
app-server counters. Reading all six exact owned native histories also finds
the four earlier automatic compactions: the five omitted costs total **643,382
tokens**, bringing the observed parent total to **10,338,351**. Historical run
results were not rewritten.

Parent accounting now reconciles native and app-server totals with separate
baselines, deduplicates response IDs, and requires native evidence for both
compaction and subsequent ordinary responses. It waits for delayed file writes,
preserves provenance, enforces the budget before another generation request,
and stops when evidence or the owned rollout path is missing. Monitor and
continuation retain these totals and baselines.

Actual installed-Codex checks, using `codex-cli 0.157.1`, GPT-5.5/xhigh and the
existing ChatGPT subscription:

- `runs/real-compaction-before-live-20260926` reproduced the exact accounting
  failure in **14.15 seconds**. A completed compaction's **11,216 tokens** were
  absent from the old framework total.
- `runs/real-compaction-final-20260926` passed manual and automatic compaction,
  continued each same conversation, retained its marker and pending review
  requirement, and executed **two real unittest cases per scenario** through
  `Host.consume` and the provider's command environment. Each command has an
  exit-zero receipt. Both compactions are correlated to native response IDs;
  the complete **175,993 raw / 86,272 cached** token totals exactly match an
  independent sum of unique native receipts. The test took **33.79 seconds**,
  made five turns, and its recorded framework source hashes match the final
  implementation. No fixture source or Git state changed.
- `runs/real-scb-execution-20260926` exercised the installed upstream evaluator
  without model generation: checkpoint 1 **13/13**, checkpoint 2 including prior
  regression tests **25/25**, and a deliberately broken submission **0/13** as
  expected. All three evaluations completed without infrastructure failure.

The final `python3 -m unittest discover -s tests -q` run passed **316 tests** in
**78.510 seconds**. Coverage includes the recorded compaction sequence, automatic
compaction followed by unpriced output, delayed/missing receipts, budget races,
duplicate receipts, monitor totals, resume baselines and the live verifier's
repeated artifact writes. Syntax checks and `git diff --check` pass. An earlier
live verifier rerun exposed an exclusive-write bug in its own receipt snapshot;
that bug has an offline regression and was fixed before the passing final run.

The bounded integration test is `tests/real_compaction.py --scenario both`.
This verifies framework execution and accounting; the complete five-checkpoint
code-search benchmark was not rerun, and its matcher review findings remain a
separate implementation problem.

## Codex context compaction and runaway-output recovery — 2026-09-26

Codex threads now cap automatic compaction at 131,072 tokens, preserving a
lower configured threshold. A preflight uses recent context usage plus the
incoming prompt's UTF-8 byte bound to request manual compaction at the lower
of that cap and 60% of the reported window. Cumulative usage counters are
never treated as context size or reset by compaction.

Streamed assistant output is checked for replacement-character floods,
excessive consecutive whitespace, the host's 4 MiB message ceiling and a
ten-minute per-message streaming limit. Failed output never reaches the host.
One priced context/output failure can compact and continue on the same thread
without replaying the original request. Compaction waits for its actual item
and turn lifecycle, retains artifacts and usage, and consumes the original
limits. Missing usage, unrelated errors and failed/exhausted recovery still
stop. C25's discretionary interruption waits while native compaction is active.

All **287 tests** pass with `python3 -m unittest discover -s tests -q`
(78.624 seconds). New coverage includes 13 context/stream guard tests,
18 provider recovery/event-order/accounting tests and three monitor tests.
The provider tests exercise buffered and late events, compaction costs,
bounded recovery, native permissions, original-request replay prevention,
partial-output cancellation and late budget exhaustion. Existing review
priority and workflow tests remain passing. Syntax and `git diff --check`
checks pass. The installed Codex protocol schema includes the used
`thread/compact/start` request, and CLI planning preserves GPT-5.5/xhigh,
P0/P1/P2 and skipped linearization without generation.

A read-only replay of turn 103 from `scb-code-search-all-on-p012-1` trips the
replacement-character guard after **23.226 seconds**, 3,298 characters and
1,204 deltas (transport line 39,731). The original turn streamed for about
38 minutes before failing. This replay verifies detection, not a live retry
or benchmark completion. No model generation or full benchmark was launched;
the saved failed run is unchanged.

## Configurable blocking review priorities — 2026-09-26

`plan` and `run` accept `--review-priorities P0,P1,P2` (the default).
Independent reviewers label every finding P0 through P3. Only selected
priorities are sent to the author for repair; other findings remain advisory
in the result's per-round review records. Selected findings still require
repair and independent re-review. Final integration and checks remain active.
Invalid or missing finding labels cannot silently approve a checkpoint.

Priorities are canonicalized and retained in plans, manifests, results, batch
worker configuration and comparison invariants. Native continuation inherits
saved priorities and rejects changes to them. Reviewer instructions require
concrete evidence and impact; repairs request focused coverage and reuse of
test structure.

All **253 tests** pass with `python3 -m unittest discover -s tests -q`
(77.100 seconds), including 16 priority tests. These exercise the actual
workflow with fake providers: default blockers, advisory-only approval,
selected-priority changes, mixed-review filtering, malformed/indented labels,
retained decisions, CLI and batch propagation, and continuation settings.
Code-search CLI plans confirm five checkpoints, all nine factors and skipped
linearization with both the default and custom priority sets.
`git diff --check` passes. No live model benchmark was launched.

## Executable-bit publication and recovery — 2026-09-26

The all-ON code-search run with linearization skipped stopped at checkpoint 1
because its final command declared only cache directories while also running
`chmod +x code_search.py`. Four local tests passed and the command exited zero;
only the file mode changed, from 0644 to 0755. Source bytes were identical.
Structured host patches previously could not publish executable-bit changes,
even if the chmod target had been correctly declared.

Add/Update patches now accept optional `*** Mode: 100644` or
`*** Mode: 100755` metadata, including mode-only updates. Successful commands
whose only undeclared effects are exact 0644/0755 changes to regular files have
those modes restored and retained as pending edits. Completion remains blocked
until the author explicitly publishes or discards them. Content changes, Git
state changes, other permission changes, timeout and cancellation still fail
closed. Receipts retain the original violation and identify recovered paths.

All **237 tests** pass with `python3 -m unittest discover -s tests -q`, including
18 new file-mode regressions. `git diff --check` passes. CLI plan still selects
all five checkpoints, all nine factors, GPT-5.5/xhigh and skipped linearization.

`runs/scb-mode-recovery-replay-1` replays the exact saved failing command in an
isolated checkout through the real Codex command sandbox. Its four local tests
pass; the executable-bit change is restored and retained as pending; DONE is
rejected until a structured mode edit commits it; the checkout then completes
cleanly. The original failed run and checkout are unchanged. The upstream
evaluator also passes **13/13** checkpoint 1 tests against that retained source
with its executable mode published. This separate grade is explicitly marked
unreviewed and does not replace the failed run or establish a completed
five-checkpoint result. No model responses were generated for this verification.

## Budget termination and partial results — 2026-09-25

No workflow change was required. New provider regressions exercise both time and
token exhaustion during a live-shaped response stream: the runner sends one
interrupt, retains late usage, records the budget reason and partial reply, and
raises before a pending host directive can execute. All six provider tests pass.

A new SlopCodeBench regression stops after an accepted edit in either the first
or second checkpoint. It verifies retained code/commits, saved partial results,
provider shutdown, no final-integration calls, and grading only the already
reviewed checkpoint. All 17 adapter tests pass. The saved live budget-stop result
still renders its partial 1/5 score and 13/13 checkpoint grade with the ordinary
summary command. `git diff --check` passes. No new model run was launched.

## One-checkpoint SlopCodeBench smoke definition — 2026-09-25

`benchmarks/scb-code-search-smoke.json` selects the first checkpoint using the
optional `slopcodebench.checkpoint_limit`. It keeps the usual review/repair loop,
final integration, quality phases and upstream grading of the reviewed checkpoint
and final assembly. The recorded limit and distinct benchmark name identify the
reduced scope; a passing smoke result is not a full code-search solve. Definitions
without a limit continue to select all upstream checkpoints.

All **217 tests** pass. Three new checks validate strict prefix bounds, unchanged
default behavior, and a complete single-checkpoint workflow with a fake provider:
same-thread repairs/re-review, one final commit, all quality phases, both external
grades targeting the selected checkpoint, and no later requirements in prompts.
CLI plan resolves one checkpoint with all factors enabled. All previous benchmark
definitions retain their feature counts; compilation and `git diff --check` pass.

No new live model run was launched for this configuration change. In the earlier
live run below, checkpoint 1 through review and quality measurement took 591.13
seconds and 685,320 observed raw tokens. The smoke command allows 3,600 seconds and
3,000,000 tokens to leave room for variation and final integration. Its complete
live duration has not yet been measured.

## Codex read-only startup repair — 2026-09-25

The first live SlopCodeBench attempt failed before model generation with Codex
0.157.0's `failed to load workspace requirements`. Our custom read-only permission
profile supplied its selector only through `thread/start`. Codex reloads retained
configuration before a model request without that typed override, so the profile
definition also needs `default_permissions`. The shared sandbox configuration now
persists that selector; filesystem and network permissions are unchanged.

The real local sandbox regression in `tests/test_execution_permissions.py` replays
the retained configuration without the separate profile argument. It checks source
reads, networking and denied writes. Removing only `default_permissions` reproduces
`config defines [permissions] profiles but does not set default_permissions`.

`runs/scb-startup-diagnostic-1` preserves the reproduced startup failure.
`runs/scb-startup-diagnostic-2/result.json` records successful live GPT-5.5/xhigh
turns in read-only mode and after switching the same thread to writable mode:
22,621 observed raw tokens, complete accounting. These prompts deliberately used
no tools, so they establish model startup, not native-write or benchmark completion.
`runs/scb-startup-write-transition-1/result.json` additionally confirms an actual
native file write in the same thread after a read-only planning turn: 34,446
observed raw tokens with complete accounting.

All **214 tests** pass with `python3 -m unittest discover -s tests -q`.
Python compilation, CLI help, all three SlopCodeBench definitions, the existing
Work Leaf definition, and `git diff --check` also pass.

The full live command was then run with the user's original limits and switches:

```sh
python3 -m lab run benchmarks/scb-code-search.json \
  --out runs/scb-code-search-verified-1 --harness codex \
  --seconds 3600 --max-raw 1000000 --max-turns 240 \
  --scb-check .venv/bin/scb-check
```

It completed checkpoint 1's implementation, review/repair/re-review, snapshot and
quality measurement, then reached the observed-token limit during checkpoint 2's
review. After provider shutdown, upstream correctness grading passed **13/13**
tests for the preserved checkpoint 1 submission. The result retains `failed` /
`incomplete`, not a five-checkpoint solve: 1,000,242 observed raw tokens, complete
accounting, 826.58 seconds. The startup error did not recur. This verifies real
agent execution and partial-run grading; final integration and checkpoints 2–5
are not established by this budget-limited run. Its artifacts and the original
failed attempt remain separate and unchanged.

## SlopCodeBench adapter — 2026-09-25

The optional adapter loads pinned upstream checkpoint specifications into ordinary
features and retains the existing author/reviewer/repair/final-integration loop.
Independent correctness grading runs after provider shutdown against preserved
reviewed snapshots and the assembled source. Old benchmark definitions, summary
tables, harness/switch options, and comparison requirements remain supported.

`python3 -m unittest discover -s tests -q` passes all **213 tests**. The additions
cover native and mediated workflows, same-thread review repairs, cumulative
requirements, pin validation, empty-project quality, partial failures, grading
after shutdown, immutable snapshots, regression/core/isolated results, evaluator
errors, bounded timeouts, interruption during grading and cleanup, batch option
preservation, comparison identities, idempotent setup, and optional reporting.
`git diff --check` passes.

The real upstream evaluator was installed with its frozen dependency lock using
Python 3.12, and its Docker image was built. The no-generation check in
[tests/real_slopcodebench.py](tests/real_slopcodebench.py) verified:

| Submission | Independent tests | Outcome |
| --- | --- | --- |
| Code-search checkpoint 1 reference | 13/13 | Passed |
| Deliberately broken code-search submission | 0/13 | Failed as expected |
| Code-search checkpoint 2 reference, including regression | 25/25 | Passed |
| Configuration-service checkpoint 1 reference | 47/47 | Passed |
| Log-query checkpoint 1 reference | 134/134 | Passed |

Artifacts are retained in
[runs/scb-evaluator-smoke-20260925](runs/scb-evaluator-smoke-20260925) and
[runs/scb-evaluator-pilots-20260925](runs/scb-evaluator-pilots-20260925).
Captured source hashes stayed unchanged, and no tagged evaluation containers
remained after the checks. All three new JSON definitions and the existing
example/work-leaf definitions loaded successfully. These checks generated no
benchmark-agent responses and do not establish model solve rates or token savings.

For a fresh installation, run `python3 -m lab.slopcodebench setup`, followed by
`python3 tests/real_slopcodebench.py --out runs/unique-scb-evaluator-check`.
The script's optional repeated `--case` selects individual checks.

This validates the lab adapter, not reproduction of the paper's reset protocol.
Existing filesystem/network permissions remain in force; hidden tests are kept
out of prompts and generation feedback, without hardened protection against
deliberate lookup. Upstream grading still resolves container test/submission
dependencies online. Static-asset problems are explicitly unsupported initially.

## Child-call directory ownership — 2026-09-21

Child accounting accepts only the `call-` directory namespace used by the
launcher. Unrelated directories, including sandbox metadata and directories
containing unrelated result files, do not become pending, abandoned or completed
calls. Genuine calls without a lock or receipt still fail after the startup grace.

All three new regressions fail with unfiltered directory discovery. All eight
child-liveness tests and all 189 local tests pass
(`python3 -m unittest discover -s tests -q`); the whitespace check also passes.
A read-only replay of the
saved child directory from
`runs/codex-baseline-no-linearization-20260921T142143Z` reports no child calls and
no child-accounting errors, matching its contents. The original failed result
and its 33,470 observed raw tokens remain unchanged; this replay does not complete
the benchmark or repair its incomplete measurement. No model generation or
benchmark rerun is performed. Token formulas, prompts and permissions are unchanged.

## Abandoned child supervision — 2026-09-21

The child supervisor holds an inherited filesystem lock until its result is
published. A released lock without a valid result produces an explicit error
instead of waiting for the full workflow deadline. Calls missing both lock and
result have a five-second startup grace. Token formulas, prompts and permissions
are unchanged; missing completion remains an incomplete measurement.

Four of the five focused regressions fail before the repair, including a real
operating-system process whose supervisor is killed with SIGKILL. All five pass
afterward, preserving partial output and never inventing a successful receipt.
The regressions use local test processes, not model generation. A real-agent
rerun is not performed, as requested by the user.

The interrupted benchmark is retained at
`runs/codex-baseline-no-linearization-20260921T114622Z/result.json`: 11,210,754
observed raw tokens, 10,411,904 cached input tokens, incomplete measurement,
one of three features reviewed, and no final checks executed. The checkout also
contains the second implementation, which has not received independent review.
The supervisor's disappearance is not explained by the liveness regression;
the verified repair is prompt detection and honest reporting of that loss.

## Optional commit-history cleanup — 2026-09-21

`--skip-linearization` retains reviewed commits and permits appended documentation
or validation-repair commits. Eight focused tests cover CLI routing for both
providers, parallel workers, preserved history, rejected rewrites, unchanged
features, failed final checks, comparison settings and continuation settings.
All 181 automated tests pass (`python3 -m unittest discover -s tests -q`).
The initial six tests failed because the option was unsupported. Default author
and review prompts and default integration prompt text match the committed version.

The bounded real Codex check uses GPT-5.5/xhigh with two turns, 120 seconds and
100,000 observed raw tokens. It preserves both fixture commits and writes the
required README, but stops at 101,048 observed raw tokens before committing the
README. It is an incomplete real-agent verification, not a pass; no retry is run.
Its complete usage receipt and partial checkout remain at
`runs/skip-linearization-codex-20260921-01/result.json`. Reproduction:
`python3 tests/real_skip_linearization.py --harness codex --out <new-directory>`.
No full benchmark is executed for this option's verification.

## Pi large shell-output capture — 2026-09-19

The permission wrapper keeps shell commands sandboxed and lets Pi's native
output capture persist temporary logs outside the command sandbox. Both
line-limited and byte-limited output remain readable in read-only turns.
Read-only writes, writable-scope escapes and network access are still denied;
shell quoting, native timeouts and workflow deadlines have regression coverage.

All 167 local tests pass. The large-output regression reproduces the original
read-only temporary-log crash before the fix. A real GPT-5.5/xhigh Pi conversation
executes one native `seq 1 3000` command, reads back lines 2999 and 3000 from its
full-output log, and replies `PI_LARGE_OUTPUT_OK`, with no tool errors or retries.
It uses 16,425 raw tokens with complete accounting. Evidence is retained at
`runs/pi-output-real-20260919T105546Z/verification.json` and its provider trace.
The original failed verifier receipt remains: exact text equality rejected Pi's
normal continuation footer. Checking the two requested lines and all 3,000 saved
output lines establishes success without another model call. This check verifies
tool execution, not a full-benchmark result or a token-saving claim.

## Pi permission and child-accounting controls — 2026-09-19

All 162 local tests pass. The regression checks cover child totals and budget
enforcement, incomplete child coverage, wrong models, shared CLI defaults,
permission transitions and native tool-result delivery. Non-generating checks
exercise the installed Pi tools inside the installed Codex sandbox: reads work;
read-only shell/edit/write mutations fail; checkout and Git-index writes work
when authorized; sibling and symlink escapes fail; network access fails in both
permission modes. The extension bridge test verifies actual returned tool text.

`python3 tests/real_pi_parity.py --out runs/pi-parity-real-002` passes with real
Pi 0.85.1 on `openai-codex`, model `gpt-5.5`, reasoning `xhigh`. One conversation
executes three turns: read-only, writable, then read-only again. Two attempted
read-only writes fail, the authorized edit and Git staging succeed, and Pi's bash
returns the guarded child launcher. A real Codex child launches and resumes with
the same model and reasoning setting. The combined total is 34,223 raw tokens:
12,452 Pi parent tokens plus 21,771 child tokens. Child lifecycle and usage are
complete. This bounded check does not establish full-benchmark success or a
token-efficiency ranking.

The retained first attempt, `runs/pi-parity-real-001`, uses 35,303 raw tokens and
fails because socket-backed Node stdout loses tool results under the sandbox.
Its filesystem permission and child-accounting checks execute, but missing tool
results make it invalid as end-to-end verification. Direct descriptor writes
and the non-generating bridge regression cover that failure. Neither attempt
uses Astra. Existing benchmark result files remain unchanged.

## Pi consecutive-turn accounting — 2026-09-18

All 151 local tests, Python compilation and the whitespace check pass. Eight
regression tests first expose the accounting errors, then verify per-response
counter resets, smaller subsequent responses, duplicate end events, cache
reads/writes, session-only usage and rejection of missing, malformed, stale or
decreasing session totals. Raw input includes Pi's separate cache categories.

Replaying the two recorded turns from each of the three failed Pi runs produces
complete accounting: 39,428, 14,506 and 14,919 raw tokens. Their original failed
results remain unchanged; replay does not finish the unrun benchmark work.

Three simultaneous real Pi workflows with all nine switches enabled pass on
separate tiny checkouts. Each implements and tests negation, passes independent
review, completes integration with one final commit, and passes both the test
suite and a separate behavior assertion. Pi 0.85.1 uses the configured
`openai-codex` ChatGPT-subscription provider with GPT-5.5/xhigh. Every run has
complete usage, matching an independent sum of its persisted Pi session data.

Qualification: those checks establish Pi parent-session accounting only. They
do not establish native-tool permission parity or complete child-agent usage.
The older Pi backend omitted child accounting; its original large benchmark
results must not be treated as controlled Codex comparisons or complete totals.

| Run | Turns | Raw tokens | Seconds | Result |
| --- | ---: | ---: | ---: | --- |
| 001 | 9 | 72,972 | 127.51 | Passed |
| 002 | 12 | 50,647 | 107.11 | Passed |
| 003 | 10 | 46,657 | 108.46 | Passed |

The batch takes 127.59 seconds and uses 170,276 raw tokens in total. The limits
are 300 seconds, 300,000 observed raw tokens and 20 turns per workflow. Evidence
is under `runs/pi-usage-verification-20260918T215352Z`, including the input,
retained replay totals and complete batch records. This is implementation
verification, not a repetition of the original large benchmark or evidence of
a token-saving effect. Factor prompts and the Codex adapter are unchanged.

## Completion whitespace and trailing messages — 2026-09-18

All 143 local tests, Python compilation and the whitespace check pass. The nine
focused regression tests first expose the missing handling, then verify `done`
and `end` whitespace, unchanged patch/command content, empty trailing messages
including late delivery, preserved review findings, and response errors kept
separate from missing usage in both backends. Quoted and malformed operations
remain rejected. The saved failed run's exact message sequence is reproduced
without changing its retained result or generating replacement work.

One real ChatGPT-subscription call returns `@standalone done` followed by a
space and tab. The host accepts completion with complete usage: 11,156 raw
tokens in 9.24 seconds. Evidence is in
`runs/response-whitespace-smoke-20260918T203118Z`; this is a protocol check, not
a benchmark rerun. The table explicitly labels review approvals rather than
independently verified feature correctness. No factor prompts are changed.

## Parallel repetitions and result tables — 2026-09-18

All 134 local tests, Python compilation and the whitespace check pass. Three
concurrent complete workflows with a scripted agent backend verify separate
checkouts, unchanged feature/review/repair/integration order, quality checks and
one pinned starting commit. Queue tests verify the concurrency limit, retained
failures, missing usage, cancellation and unstarted repetitions. The actual
command-line worker path retains three pre-generation failures as one batch.

Summary tests cover single results, batches, report arrays, stdin, failed runs,
incomplete measurements, comparable-run averages and duplicate rejection. The
existing failed all-on report renders with its incomplete token count and two
unrun quality checkpoints preserved. These checks launch no model generation;
they are not a real-subscription parallel benchmark or a token-saving result.

## Nested caller shutdown — 2026-09-18

All 117 local tests, Python compilation and the whitespace check pass. The
regression first fails because terminating the caller's process group also
kills its nested Codex call. Separate supervision retains that call's output
until completion. The next-response guard also fails before implementation and
passes afterward. A startup/cancellation regression also verifies that a delayed
supervisor cannot launch after shutdown. [Behavior and reproducible checks](docs/nested-verification.md).

The final real-subscription shutdown check passes on the exact resulting runner
source, using GPT-5.5/xhigh and the existing Pro login. Its caller is killed
with SIGKILL during generation. The nested call finishes normally with complete
usage: 10,833 raw tokens in 5.49 seconds. The final CLI usage equals the
independent native session counter. No parent model response is generated.

Evidence is retained under `runs/nested-shutdown-20260918/real-03`,
including input/source pins and child stdout, stderr and terminal receipts.
Its `at-shutdown.json` is the immutable pre-shutdown observation: zero observed
tokens and an incomplete active call, followed by complete final usage.

Two earlier shutdown checks also pass, before the startup/cancellation guard:
`real-01` uses 10,841 raw tokens in 6.66 seconds and `real-02` uses 10,836 in
5.70 seconds. Their CLI and native totals match. All three outcomes are retained;
combined verification usage is 32,510 raw tokens. The first check's nested
thread-detail object remains a live reference until final
serialization; its captured zero-token total, pending process and incomplete
status are valid, but its embedded thread details show the later state. The
second and final checks freeze the entire observation before killing the caller.

Two non-generating sandbox probes reject temporary-file writes and local socket
connections under the read-only policy. The repair grants no extra permissions
and does not use an outside-sandbox execution service. Actual generation in
the checks above runs through the ordinary host-command path.

The original hour-long failed benchmark remains unchanged and is not resumed
or repeated. Its missing final child charge remains unknown. The successful
small checks establish the repaired shutdown path, not a full-benchmark pass.
The completion/usage event assertion follows the
[official non-interactive Codex documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

## Three code-quality checkpoints — 2026-09-18

All 94 local tests, Python compilation and the whitespace check pass. The ten
scoring tests cover stage order, exact source boundaries, unchanged prompts,
findings versus execution errors, missing executables, bad reports, timeout,
source mutation, final functional-test failure, preserved initial scores during
saved-work continuation, CLI/report output and the actual scb-check executable.
The initial eight tests fail before implementation and pass afterward.

One tiny real-subscription workflow with scb-check 0.2.0 passes: implement and
test negation, independent review, integration plan/accept, one final commit,
the repository test suite and a separate behavior assertion. The three quality
reports match their saved raw JSON and commit IDs. All return exit 1 (findings),
which correctly remains a completed observation rather than a failed run.
The final two scores refer to the same source because integration requires no
additional edits in this tiny example. Source/history rewriting is separately
covered by the two-feature automated test, not claimed from this real example.

The real workflow uses 273,303 raw tokens in four completed turns, with complete
usage and no nested generation, and finishes in 175.98 seconds. The checker
runs locally with no model calls, and its output never appears in model prompts.
No previous large benchmark is repeated. Existing staged README edits remain
separate from this implementation. [Full result and evidence](experiments/scb-check-20260918/RESULT.md).

## Neutral disabled instructions — 2026-09-18

C13/C14/C15/C16 OFF leave ordinary agent/repository policy intact. All 84 local
tests pass, including fourteen regressions covering absent instructions, every
switch combination, both host edit formats, rejected/stale edits and preserved
review/repair/integration. Enabled author instructions retain their exact
pre-repair hashes. The failing-before-fix assertions and scope are documented
in the [verification result](experiments/neutral-off-20260918/RESULT.md).

Both real-subscription author checks pass: direct native edits and host-managed
edits with all four instructions disabled. Both agents implement and test the
same tiny function, commit clean source and retain complete token records.
The native agent uses its normal patch tool; the host accepts a structured patch
without a format instruction. Verification uses 196,010 raw tokens combined;
it is not a token-saving experiment or a full-benchmark rerun. Other permissions,
switches, transport and Work Leaf implementation remain outside the repair.

## Six-run endpoint — 2026-09-18

All six observations have retained terminal outcomes, including linked saved-work
continuations. The full three-versus-three token validation is **not achieved**:
two all-off workflows reach their 90-minute active-time limit before completion.
One full all-off workflow passes repository checks and all three external feature
tests at 42,177,372 raw. Two complete all-on workflows pass repository checks but
score 2/3 externally. The third all-on run's failed terminal assertion and the
full suite pass once on unchanged source, with zero additional model usage;
its original failed result remains intact. No all-on model workflow is repeated.

The final independent audit reproduces all observed totals. All-off 2 retains
one missing interrupted-response price. All-off 1 has priced recorded output,
but its interrupted integration plan and the whole workflow remain unfinished.
The ordinary comparison guard rejects the incomplete/mixed-identity group.
[Full results, exact denominators and limitations](experiments/on-off-20260918-r4/RESULT.md).

All 70 local tests and Python compilation pass. The real parent resume test and
the complete all-off workflow verify the agent-facing recovery path. The final
accounting/scoring scripts affect no agent inputs or agent workflow and generate
no model responses. No Work Leaf Rust implementation is part of these changes.

## Native completion and same-conversation recovery — 2026-09-18

All 66 local tests, Python compilation and the whitespace check pass. Seven
recovery regressions cover a summary before the final marker, malformed markers,
clean saved-source requirements, unchanged first-feature work, retained prior
costs, resumed cumulative counters and rejection of configuration differences.
The failure cases were exercised before the corresponding repair.

The real subscription resume check passes: the original conversation uses
11,270 raw tokens before resume and another 11,302 afterward, for 22,572 total.
The independent native history matches exactly. Both replies use GPT-5.5/xhigh;
the original instructions are not resent. The two active phases take 9.62
seconds combined. Evidence is under
`runs/on-off-20260918-r4/resume-qualification-001` and
`resume-qualification-002`; the first configuration-stop record remains intact.
The resume behavior follows the [official app-server documentation](https://learn.chatgpt.com/docs/app-server).

The provider configuration differs only by four automatically added trusted
folder records, each already covered by a trusted parent. Removing exactly those
records in memory reproduces the original complete configuration hash. The
actual new hash and proof remain visible; no global configuration or permission
is edited. All other differences are rejected.

The three all-on observations remain 25,673,000 / 22,490,575 / 26,119,875 raw.
The first and third pass; the second retains its original final test failure.
All three all-off first authors have complete accounting and clean committed
work, but the old parser rejects their valid final markers after a summary.
Their explicit continuations start at independent review, preserve every prior
cost and use only the remaining original allocation. Their terminal outcomes
are recorded above. [Recovery boundaries](experiments/on-off-20260918-r4/NATIVE-CONTINUATION.md).

The provider-free audit has four additional tests; all 70 local tests pass.
The audit combines original and continued transport records in order, checks
that saved native histories remain exact prefixes, and rejects changed earlier
results or benchmark factors. Measured prompt functions and the shared provider,
host, factor, environment and nested-launcher modules match across the repair.
This audit does not modify agent inputs or run any model.

## Nested processes and unchanged features — 2026-09-18

[The real tiny qualification](experiments/on-off-20260918-r4/QUALIFICATION.md)
passes: existing feature inspection, real child launch/resume, independent review,
verification-only empty final commit, clean source and all ten Python tests.
Usage is 352,201 raw in 263.54 seconds, including 21,927 child tokens counted once.
All twelve parent turns and both child turns are priced; the child's native records
show GPT-5.5/xhigh and Pro subscription. The original input remains unchanged.

All 59 local tests pass. Fail-first coverage includes unchanged-feature rejection
and repair, nested model override rejection, resumed cumulative deduplication,
shell startup credential cleanup, child inclusion in totals/resource checks,
native assistant-message tail coverage and an invalid plan label. Replaying the
actual child record through the stricter final-message parser gives the same
complete 21,927. No additional generation is needed for that observational check.

The real native-command environment probe passes with the guarded Codex path.
A native-sandbox child launch fails before agent startup because local state is
read-only; this remains a blocked real-agent smoke, not a green one. A single
non-generating doctor check confirms stored ChatGPT auth and reachable service.
No broad sandbox change or credential copy is made. The successfully generated
child verification above runs through the host-command path.

The first tiny qualification failure (143,950 raw, no child generation) remains
retained. It is not counted as successful verification. These functional checks
do not themselves establish a saving percentage; the full outcomes appear above.

Performance review flag: `NestedUsage.refresh` scans active-day candidate file
names, and `NestedUsage.report` summarizes retained child turns at each poll.
Each poll is linear in those collections, but cumulative work can become
quadratic when both the number of child calls and the number of polls grow
together. The bounded current study has few child verification calls; the
observer is not presented as a scalable all-history index. This flag concerns
the new observer, not the coding agents' measured algorithms.

## Retained third-batch failures — nested processes

The [third admitted batch](experiments/on-off-20260917-r3/RESULT.md) starts after
the stricter real Git-history rewrite passes. One author launches a separate
Codex verification process. Its 167,250 raw tokens are absent from the runner's
total; its native records specify GPT-6 Astra/max instead of the benchmark's
GPT-5.5/xhigh. Pro-plan records support subscription use, but the host command
path does not apply the main provider's credential/model/accounting controls.
Main-provider completeness is not whole-workflow completeness on this path.

The same workflow sends completion without editing the already-present slash
command code; the runner's required-new-commit gate fails before independent
review. The other two workflows stop under the common-accounting-failure rule.
Observed usage including the recovered child is 21,175,267 raw, with two
incomplete cancellation tails. Three all-off attempts remain unstarted.
All failed work is retained; no saving percentage or successful full comparison
is established. The actual Git rewrite remains a valid narrower pass.

The then-current 49 tests did not qualify nested real generation or completion without
a new commit. Required next coverage includes launch/resume child pricing,
child configuration/authentication boundaries and an already-satisfied feature.
No source repair or further generated verification is included in this closeout.

## Full-benchmark measurement status

The standalone tool does not yet have a valid three-all-on versus three-all-off
token comparison. The [first 2026-09-17 batch](experiments/on-off-20260917/RESULT.md)
retains three concurrent all-on attempts stopped after 67 completed responses
lacked final-message usage coverage. The all-off attempts were not started.
The 41,807,064 observed raw tokens are incomplete; no saving percentage follows.
The earlier small verification passes below remain retained, but did not cover
that real intermediate-message interruption failure.

The [replacement batch](experiments/on-off-20260917-r2/RESULT.md) has two
fully priced failed integration attempts and one operator-stopped third-feature
repair: 57,157,285 observed raw combined, with one incomplete cancellation tail.
Its shared failure is native Git metadata being read-only, not another earlier
missing-response problem. All-off is unstarted. The saved small integration
record below does **not** verify native Git writes: its input already had the
required final commit count and needed no rewrite.

## Native Git permission verification — 2026-09-17

The original workspace-only policy fails a real local Codex `command/exec`
commit with an index-lock read-only error. Adding only the owned clone's `.git`
directory to writable roots makes the same command create a commit. Two local
probes use zero model turns and zero raw tokens; the second exercises the actual
repaired policy helper and zero-generation preflight. Raw evidence:
`runs/on-off-20260917-r2/git-command-probe-001` and `git-command-probe-002`.

Five initial regressions run before repair: two assertions fail, two missing
methods/guards error, and the read-only restriction remains green. The repaired
tests cover exact writable roots, unchanged read-only roles, preflight failure
before any model work and rejection of a no-op integration verification. A
positive check also verifies acceptance of actual history collapse.
All 49 Python tests pass in 20.37 seconds; Python compilation and the whitespace
check pass. The two local native-sandbox probes complete in about 0.3 seconds
each. They are actual backend command checks, not model-generated workflows.

The real-agent integration verifier requires an extra disposable input commit
to be collapsed and checks that HEAD changed. It refuses an existing output
directory. The [approved stricter check](experiments/on-off-20260917-r3/QUALIFICATION.md)
passes with 191,320 raw tokens in two fully measured turns. The real agent
rewrites its three-commit input to two feature commits; all ten Python tests
pass, the source is clean, and the original reviewed checkout remains unchanged.
Native history rewriting is verified. The user's condition for another six-run
comparison is satisfied; that full token comparison is not yet complete.

## Usage-boundary repair verification — 2026-09-17

The [approved repair and replacement scope](experiments/on-off-20260917-r2/REPAIR-AND-RUN-AUTHORITY.md)
requires a priced interruption, immediate incomplete-measurement stop and visible
live coverage flags before six replacement benchmarks.

- Eight new regressions fail before repair: five assertions and three missing
  journal/observer errors. All eight pass after repair; all 43 total tests pass.
- `runs/on-off-20260917-r2/real-usage-001/result.json` passes in 37.59 seconds,
  using 76,865 raw tokens in six turns. Its first operation is an intermediate
  host-request message and an actual interruption after fresh usage arrives.
  Five turns end interrupted with `usage_received`; one finishes naturally
  with interruption disabled. Every turn has complete final-message coverage.
- The same real conversation reads a file, encounters a controlled stale edit,
  receives a compact refresh, submits an accepted correction, runs a real
  Python test and completes. No missing report, counter reset or replacement
  observation is hidden. Authentication is the existing ChatGPT subscription,
  Codex 0.154.0 / GPT-5.5/xhigh, with unchanged effective configuration.
- The observer reports the earlier failed runs' 24/1/45 coverage gaps, including
  their final operator cancellations. Local tests show missing live coverage
  without waiting for a whole-workflow result and without double counting.
- Author prompts are byte-identical for all 320 valid switch combinations.
  Review/integration instructions and host edit/feedback logic are unchanged.
  Cancellation waits for a fresh usage boundary instead of cutting an unpriced
  response at an intermediate message or elapsed grace. This is the explicit
  repaired C25 behavior, not an unchanged historical interruption policy.

These are functional and measurement checks, not evidence of a saving percentage.
The failed first batch remains unchanged. Replacement observations use separate
directories; their off group never starts after the shared Git-permission failure.

## Prospective real-agent smoke scope — 2026-09-17

This is implementation verification, not a new saving experiment or a historical
control. No percentage will be inferred from smoke-test costs.

First perform a non-generating subscription/configuration readback. Do not copy
credentials, change the account, substitute an API key, or override CODEX_HOME.

One small two-feature workflow uses `benchmarks/example.json`, all nine mechanisms
enabled, GPT-5.5/xhigh, at most 600 seconds, 300,000 observed raw tokens and 24
turns. Preserve its checkout and every outcome under `runs/real-workflow-001`.
Success means real host edits/checks/feedback, two independent feature reviews,
final plan/accept, two final commits and passing Python tests. An unsuccessful
attempt is retained and not counted as successful verification.

One further bounded protocol verification may use at most 180 seconds, 80,000
observed raw tokens and 6 turns to exercise a stale edit, compact conflict refresh
and actual interruption. It uses a disposable fixture, not an experimental
workflow. Local failure-path tests precede it. A pre-agent setup failure stops
generation until a concrete local repair is verified; no blind retry.

Observed-token limits can overshoot on an in-flight or unreported response. Wall
time and turn ceilings are independent bounds. Interruption retains/drains late
usage and never refunds already generated tokens.

## Local results

- Initial tests failed before implementation: missing `lab` package.
- Workflow tests failed before implementation: missing `lab.workflow`.
- First implemented suites: 17 tests pass, including a two-feature workflow with
  a repair/re-review round, persistent author/reviewer identities and final squash.
- Final suite: 35 tests pass. Coverage includes both compact/full responses under
  the same declared intervening update in the actual workflow loop; malformed
  proposal recovery; the original refresh size limits and snapshot invalidation;
  missing login, token deduplication, missing tails and cancellation draining.

## Real results

- Non-generating readback: `runs/doctor-002/provider.json` confirms ChatGPT login,
  Codex 0.154.0, GPT-5.5/xhigh. No API fallback and no generation occurred.
- The first readback attempt failed before provider launch because a nested output
  directory was not created. A failing regression test reproduced that local bug;
  its verified fix precedes the second attempt.
- `runs/real-workflow-001` is the one bounded complete-workflow verification.
  Its input is a separate Git repository copied from the tiny example, defined by
  `runs/smoke.json`; no Work Leaf benchmark or old measurement is rerun.
- That attempt stopped correctly at its observed-token tripwire during integration
  planning: 309,828 observed raw, 216.76 seconds. Both features were implemented,
  tested and independently approved. Eleven host turns actually ended interrupted
  with usage retained. The failed run is unchanged; it is not a full-workflow pass.

## Remaining-stage verification scope — 2026-09-17

The missing implementation coverage is native final integration, not another
author/reviewer experiment. One separate integration-only verification clones the
exact reviewed checkout from `real-workflow-001`, performs plan/accept in one new
conversation, and checks two final commits, clean source and the complete tests.
Limit: 240 seconds, 200,000 observed raw, two turns, GPT-5.5/xhigh. No feature,
review or scientific observation is repeated. Output: `runs/real-integration-001`.
It cannot convert the earlier capped run into a complete experimental result.

## Verified real-agent outcomes

- `runs/real-protocol-001/result.json`: PASS. One real ChatGPT-backed conversation
  receives file text, encounters a controlled intervening edit, submits an outdated
  patch, receives a compact diff, corrects its patch, runs real tests through the
  host and completes. Five turns actually end interrupted; all have late/final
  usage retained. Total observed raw: 63,381.
- `runs/real-integration-001/result.json`: retained shape/test PASS, not a verified
  native history rewrite. The exact reviewed source from the
  capped full run reaches a plan and acceptance in one new real conversation;
  history has two final commits and the Python suite passes. Total observed raw:
  128,488. There is no author/reviewer repeat. The input already contained those
  two commits, and the agent made no Git-history change; it did not exercise the
  permission required by the later three-feature integrations.
- Total observed raw across implementation verification: 501,697. No API credits
  are used. The readback is non-generating; local tests use no model.

These records verify actual host feedback, real interruption, same-conversation
continuation and review. Native final history rewriting is not verified by the
retained no-op integration scenario. The uninterrupted two-feature full
smoke did **not** pass its declared budget. Do not advertise it as a completed
benchmark or derive a saving percentage from these checks. The final fixture
dispatcher and defensive failure-path fixes additionally have fail-first local
coverage; the real conflict record uses the same intervening-edit condition via
the host primitive. Individual policy compliance and every switch combination
are not claimed to have been confirmed by these smoke checks.

Work Leaf's Rust sources, tests, examples, Cargo files and architecture are
unchanged. Its product checks and old research counters are not modified by this
separate Python project. Python compilation and unittest discovery are the
applicable local checks.

## Installed-project verification — 2026-09-17

The independent project is at `/home/user/src/agent-behavior-lab`. From that
directory, all 35 unittest checks, Python compilation and the CLI help check
pass. The retained real-agent records above remain unchanged, including the
incomplete full-workflow attempt. Installation uses no additional model
generation and does not modify Work Leaf.

## Full SlopCodeBench execution and compatibility — 2026-09-27

The framework now retains and grades a bounded, unresolved SlopCodeBench
checkpoint attempt and continues the later cumulative checkpoints. This policy
applies to the adapter, without problem-specific branches. Ordinary feature
workflows retain their terminal attention behavior. Global budget, provider,
integrity and incomplete-accounting failures remain terminal. Approval, completed
execution and test results are reported separately.

The final source passed **372 unittest checks**. Generic continuation fixtures
cover both harness paths, mediated/native source editing, preserved/linearized
history, rejected and incomplete reviews, local allowance resets, retained dirty
source and pending proposals, and terminal global/infrastructure failures.

The first live verification attempt exposed an automatic-compaction accounting
bug: a completed compaction notification followed the final transport usage
notification, falsely invalidating ordinary output coverage despite a complete
native receipt. A sanitized trace reproduces the original failure. Coverage now
checks ordinary messages and owned compaction receipts independently; missing
receipts, unpriced output and unfinished compactions still fail closed. The failed
attempt remains at
`runs/scb-continuation-verification-20260927/full-benchmark` without modification.

The fresh full run is
`runs/scb-continuation-verification-20260927/full-benchmark-2/result.json`.
It uses `benchmarks/scb-code-search.json`, Codex, GPT-5.5/xhigh, all factors,
P0/P1/P2 reviews, preserved history, 10,800 seconds, 15,000,000 raw tokens and
1,000 turns, with `.venv/bin/scb-check`. No generated solution was manually
repaired, and hidden grades were unavailable to all model sessions.

| Snapshot | Review outcome | Upstream tests passed |
| --- | --- | --- |
| checkpoint_1 | Approved | 13/13 |
| checkpoint_2 | Approved | 25/25 |
| checkpoint_3 | Rejected; local limit reached | 43/47 |
| checkpoint_4 | Rejected; local limit reached | 70/75 |
| checkpoint_5 | Final review stopped; approval unknown | 95/104 |
| Final integration | Earlier outcomes preserved | 95/104 |

All five checkpoint attempts, integration, final checks and all six evaluations
completed. Each local stop preserved its findings and immutable snapshot, then
continued. `execution_status` and grading status are `completed`; workflow status
is honestly `needs_attention`, `solved` is false, and the CLI exits nonzero because
the generated solution still has unresolved findings and failing tests. This is
proof of complete benchmark execution, not a claim that the model solved it.

Usage is complete: **11,670,418 raw tokens**, including **9,822,848 cached input
tokens**, in **5,621.657 seconds**. Five native compactions have complete receipts.
The completion audit verifies all snapshot/archive contents and extracted file
modes, recorded Git trees, final checks, reconciled usage, unchanged runner source
and seven historical files. Its report is
`runs/scb-continuation-verification-20260927/completion-verification.json`;
the audit can be repeated with:

```sh
python3 runs/scb-continuation-verification-20260927/verify_completion.py \
  --run runs/scb-continuation-verification-20260927/full-benchmark-2
```

A real Pi legacy workflow against the same final framework source also passed:
`runs/scb-continuation-verification-20260927/pi-legacy-smoke-final/result.json`.
It independently approved its feature, passed both final checks, retained exactly
one final commit and measured **53,229 raw tokens** in **128.597 seconds**.
This verifies the normal Pi legacy path; Pi attention continuation is covered by
the generic scripted matrix, not a separate live attention run. The complete
unit-test log is `runs/scb-continuation-verification-20260927/framework-tests-final.txt`.

## Output settlement and compatibility — 2026-09-28

The retained GPT-5.6-sol failure in `runs/scb-code-search-all-on-p012-7`
cancelled an unfinished response after 8,192 trailing whitespace characters.
Its subsequent usage notification repeated the preceding response's counters;
the owned native history contained no receipt for the cancelled response.
Continuing that historical run would have required unmeasured generation.

Context policy version 3 quarantines soft output violations immediately and
allows at most 120 seconds to reach completion or a genuinely priced boundary.
Existing hard size, streaming-time, feature, review and global limits still
take precedence. Quarantined output cannot become a host directive or a reused
review verdict. Terminal provider errors remain terminal; only structured context
errors and covered output-limit failures qualify for the existing single retry.
Per-turn streamed-text journals retain unfinished assistant output.

The final source passed **387 unittest checks** in 96.567 seconds. The new
settlement tests cover stale, missing, delayed and foreign usage; genuine native
receipt requirements; both soft guards; hard limits; terminal and transient
provider errors; late output; review-conclusion quarantine; retained artifacts;
and bounded same-thread recovery. The full suite also exercises existing Codex,
Pi, review, integration, permissions and checkpoint-continuation paths.

Live verification is retained under `runs/output-settlement-verification-20260928`:

| Check | Result | Observed raw tokens |
| --- | --- | --- |
| GPT-5.6-sol/xhigh output recovery | Same thread, three genuinely priced turns, one host execution | 37,245 |
| Codex manual and automatic compaction | Both passed with owned compaction receipts | 175,783 |
| Pi large native output and read-back | One bash call and one successful read | 16,709 |
| Complete Pi legacy workflow | Review, both final checks and integration passed | 54,833 |

The output-recovery verifier injects one local guard result into an otherwise
ordinary real model response. It does not alter model text, transport events or
usage. That response finished naturally during settlement; this check is not a
claim to reproduce natural model degeneration. Deterministic regressions exercise
interruption at a priced boundary and failure when a receipt never arrives.
The first live verifier attempt completed recovery but its reporting helper
attempted to create the same artifact twice. That attempt remains retained as
incomplete; `codex-recovery-2` is the fresh successful verification after fixing
the helper.

The installed upstream evaluator passed all five code-search reference
checkpoints (13, 25, 47, 75 and 104 tests), config-service (47 tests), and
log-query (134 tests), and correctly failed the deliberately broken code-search
submission (0/13). These are evaluator checks, not model solution scores.

`independent-live-audit.json` reparses native receipts and reconciles costs,
permissions, same-thread recovery and host execution. `pi-independent-verification.json`
independently checks the full Pi workflow. `final-source.json` records source
hashes and the preserved historical failure hashes; `framework-tests-final.txt`
contains the final unit-test log. The Pi output-only verifier has no source-hash
admission; the complete Pi workflow does.

The subsequent full GPT-5.6-sol run reproduced natural degeneration at
checkpoint 3, turn 0046. The 120-second settlement timer expired before a fresh
receipt arrived, so that trial correctly stopped with incomplete measurement.
Its first two checkpoints were approved and passed 13/13 and 25/25 tests;
the overall run is **failed**, not a successful full-run validation. It remains
at `runs/output-settlement-verification-20260928/full-benchmark/result.json`
with 2,010,381 observed raw tokens and an explicitly unmeasured final tail.

Context policy version 4 removes that premature timer: soft output settlement
uses the existing 600-second message bound. The original streaming deadline
still starts at the first message chunk; completed-only violations have a
600-second settlement ceiling from detection. Hard byte, feature, review and
global limits remain unchanged, and missing receipts still block generation.
The revised source passes **390 unittest checks**, including a genuine receipt
arriving after 130 virtual seconds and hard deadlines for both streaming and
completed-only malformed responses. V4 verification artifacts are retained in
`runs/output-settlement-verification-v4-20260928`.

The final V4 unit suite completed all **390 checks in 95.276 seconds**. Its live
Codex recovery control passed with **37,112 observed raw tokens**, and the full
Pi legacy workflow passed review, final checks and integration with **51,528
observed raw tokens**. Both have complete usage. The recovery control still uses
one locally injected guard result; it does not reproduce a natural whitespace
flood. `pi-independent-verification.json` audits the Pi result.

The full V4 GPT-5.6-sol/xhigh trial using the original run settings is **failed**,
not a successful full-run validation. Checkpoints 1 and 2 were approved and
passed 13/13 and 25/25 tests. Checkpoint 3 reached its feature token limit, retained
its unapproved 44/47 grade and continued to checkpoint 4 under the existing stop
policy. At checkpoint 4, turn 0082, the provider returned a non-retrying
`Invalid prompt` policy rejection. No further generation or compaction followed.
Checkpoints 4 and 5, final evaluation and integration remain incomplete.

This trial lasted **3,015.312 seconds** and recorded **4,633,369 observed raw
tokens**, including **4,072,704 cached input tokens**. The final rejected turn has
no numeric receipt, so these are observed costs, not a complete total. No output
guard fired during this full V4 trial; it does not demonstrate recovery from
natural degeneration. The 600-second settlement ceiling cannot guarantee a
receipt before a hard limit or provider failure.

`provider-rejection.json` retains the exact submitted user prompt, provider error
and turn identity. The provider also had earlier thread context and did not
identify a triggering phrase. `failure-verification.json` independently verifies
the three captured snapshots and grades, 116 owned native receipts including one
compaction, unchanged hashes for all 24 runner source files and four preserved
historical failure artifacts. It explicitly records incomplete execution and
measurement. The read-only audit can be repeated with:

```sh
python3 runs/output-settlement-verification-v4-20260928/verify_failure.py
```

### Typed host responses: reproduction and fix, 2026-09-28

The subsequent `scb-code-search-all-on-p012-7` failure contained two distinct
events: three identical mixed command/prose replies stopped checkpoint 4, and
an upstream policy rejection terminated checkpoint 5. The saved visible replies
from turns 0074–0076 were reproduced locally with the real `Host` and
`FeatureProgress`: all three were rejected, no command executed, source stayed
unchanged, and the third reply produced `repeated_operations` for operations
9–11. A new typed-response test failed before implementation because the
provider returned JSON verbatim instead of a usable host operation. The observed
baseline and source hashes are retained in
`runs/host-response-verification-20260928`.

Codex host-author turns now request one typed operation through `outputSchema`.
The adapter validates the complete JSON, rejects unknown/duplicate fields and
unconstrained commentary, and checks that conversion to the existing text host
preserves all operation fields. It retains raw JSON separately from the delivered
host operation. Existing patch validation, permissions, source custody, usage,
budget and provider-error gates still apply. Native, reviewer, integration, Pi
and compaction responses are not given this schema. The provider identity records
`json-schema-host-operation-v1`; C25 now selects a validated final operation.

The final broad regression suite passed **409 tests in 96.860 seconds**, including
all **19 focused tests**. Coverage includes the exact saved loop, all operation
types, separator-like and whitespace-only filenames, preserved command whitespace,
both patch formats and executable modes, message ownership/phases, late usage,
context recovery, and terminal provider-error handling. A compatibility regression
for whitespace-only filenames was reproduced before correcting the adapter; the
complete suite and live fixture were then rerun against the final source.

The fresh live GPT-5.6-sol/xhigh subscription fixture passed all seven host turns
in **34.322 seconds**, with **98,108 observed raw tokens**, **67,072 cached input
tokens**, and complete usage reconciled against native receipts. It exercised
every operation type, alternated C25 on/off, published one executable edit,
executed two host commands and one runtime check without replay, discarded a
pending source change, and left a clean checkout. Source hashes stayed unchanged
during the fixture. Raw schema requests, responses, canonical operations, host
receipts and native usage are under `live-codex-final` in the verification directory.
An independent audit verified all seven native receipts, every requested operation
field, actual host effects, and all 25 runner source hashes. The earlier successful
fixture and intermediate test results remain separately preserved.

This fixes the reproduced command/prose protocol failure. It does **not** establish
that the upstream policy rejection is resolved or that the failed benchmark now
passes. The blocked conversation was not retried, no full benchmark rerun was
performed, and provider policy errors remain terminal. The original failed run
is preserved unchanged. `verification-final.json` records the final results and
these limits explicitly; `verification.json` is the preserved intermediate report.
