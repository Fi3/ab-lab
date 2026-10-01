# Runner failure contract

The benchmark measures a harness under selected conditions. An unsuccessful
operation is evidence, not permission to replace the task, add coding advice,
discard source, or describe an unfinished attempt as successful. The runner owns
execution limits, operation records, snapshots, and result classification.

This document defines the behavior to verify. A row in this matrix is not proof
that its recovery path has passed: the corresponding fault-injection tests and
saved full-run results provide that evidence. Workflow and transport versions,
factor settings, upstream revisions, and prompt provenance belong in every run's
metadata so results from different contracts are distinguishable. C25 and the
printed-command transport have been removed; there is no legacy execution mode.

## Outcomes are independent

- **Execution:** did every feature complete its configured implementation and
  review/repair sequence and deterministic final checks finish, or did the workflow stop
  incomplete?
- **Benchmark correctness:** did authoritative evaluation pass, fail, or not run?
- **Review:** approved, findings, incomplete, skipped, or an unreviewed final
  repair; completion alone is not approval.
- **Accounting:** complete or incomplete; missing usage is never estimated as zero.
- **Failure owner:** agent, runner, provider, evaluator, or external interruption.

A workflow can finish normally with a failing benchmark score. A runner error
cannot establish a benchmark failure. An interrupted response cannot establish
that no tools ran. These distinctions must survive checkpoint stopping and
final result aggregation.

## Detection, preservation, recovery, and outcome

| Failure mode | Detection and preserved evidence | Safe recovery | Required outcome |
| --- | --- | --- | --- |
| Invalid tool arguments or an invalid patch | Validate before executing. Record original arguments, precise error, and unchanged source identity. | Return the error as a tool result. The agent may issue a corrected call. Do not instruct it to restart the task. | Recoverable operation failure; no infrastructure failure unless valid input was rejected. |
| Valid operation rejected by runner | Reproduce against documented tool schema and accepted patch grammar. Preserve request and exact rejection. | Fix the runner and replay the reproducer offline. Do not spend an agent repair round trying to explain a hidden rule. | Runner failure, never attributed to task correctness. |
| Patch context is stale | Compare exact requested context with current content and record the conflicting file identity. | Return current evidence; C08 controls whether eligible conflict information is a diff or full text. Do not partially apply a rejected patch. | Recoverable operation failure; subsequent corrected calls are separate operations. |
| Command exits nonzero | Record exit code, output, changed paths, source state, and command identity. | Return actual output. Keep changes made before failure; the agent decides the next action. | Agent operation failure unless an identified runner/environment fault caused it. |
| Command creates or changes files, permissions, or deletes files | Compare actual workspace state before and after execution, including nonignored new files and file modes. | Preserve and publish actual source changes under the selected host-ownership condition. Do not require predicted paths or a second patch that replays the command's changes. | Normal operation if execution succeeded; partial work if it failed. |
| Command times out or is cancelled after changing files | Record process identity, timeout/cancellation cause, output so far, and final observed source state. | Reap owned processes before assessing state. Return the partial-execution result; do not blindly repeat the command. | Operation interrupted, with partial work retained. |
| Repeated tool call identifier | Check the persistent operation record and exact arguments before execution. | Return a durable completed receipt for identical calls. Refuse mismatched arguments under the same identity. An already-running call is observed, not launched again. | One execution at most for each accepted call identity. |
| Execution completed but result was not delivered | Distinguish operation completion from result delivery in the journal; preserve receipt, output, source identity, and commit identity. | Deliver the saved result. Do not re-execute. If completion cannot be established, stop for reconciliation rather than guessing. | Recoverable delivery failure, or incomplete execution status when evidence is insufficient. |
| Provider disconnect before or during a response | Record provider request/turn identity, terminal event if available, native tool events, host-operation receipts, and usage receipts. | Reconnect/reconcile the same owned turn where supported. Retry only when prior execution state is known; an unresolved in-flight turn cannot be replaced speculatively. | Provider interruption; task correctness remains independent. |
| Upstream policy rejection, including `Invalid prompt` | Save the provider's original error, rejected request identity, and any accounting receipt without classifying from a missing final response. | Do not repeatedly resubmit or rewrite the benchmark to evade the rejection. Retain work and stop the workflow; later checkpoints remain unrun. | Provider rejection, not an agent benchmark failure and not evidence that a local protocol repair failed. |
| Provider response/output limit or context overflow | Record the actual provider limit error, partial output, operation acceptance state, and usage. | Native compaction or supported recovery may continue the same task. Already executed native/host tools must not be replayed. | Recoverable provider limit only with established state and accounting; otherwise incomplete. |
| Missing, late, malformed, or duplicated usage | Reconcile request identities and authoritative receipts; retain unmatched records and raw provider events. | Accept late receipts for their original request; deduplicate by identity. Do not infer usage from a token estimate or count a duplicate twice. | Accounting incomplete until reconciled; never a fully measured run while coverage is missing. |
| Agent creates another model session | With C17 off, preserve harness delegation and record owned child lifecycle, model identity, and usage. With C17 on, disable collaboration and deny installed harness launchers to preserve host ownership. | Native child work stays inside the same filesystem/global-budget limits. Await accounting completion; missing receipts cannot be treated as zero. | Supported native delegation or a documented C17 denial; unaccounted work makes measurement incomplete. |
| Agent turn ends with no source changes | Observe normal harness completion and capture the actual workspace state. | Send the assigned requirements and existing result to independent review if review is enabled. No synthetic completion marker or empty commit is required to establish that the turn ended. | Completed author attempt; review/evaluation establish whether the task was already satisfied. |
| Review submits invalid arguments or ends without a verdict | Validate `submit_review` against its schema and current round/commit identity. Preserve accepted structured findings and the settled reviewer turn separately. | Invalid calls receive corrective tool feedback. Missing or explicitly incomplete verdicts remain incomplete; final prose cannot supply approval. | Approval requires an accepted complete verdict for the unchanged current target and a settled turn. |
| Reviewer finds a real issue | Preserve the exact finding, affected requirement, reviewed tree, and priority. | Supply blocking findings for the author repair following that review. Do not add unrelated coding advice or unspecified requirements. Re-review only while the configured review allowance remains. | Review findings; approval of a repaired tree requires its own review result. |
| Configured review allowance is reached | Record `max_review_loops`, completed reviews, repairs, and the final source identity. The all preset defaults to three reviews per feature; native defaults to zero, which skips review. | After the Nth blocking review, complete its author repair and continue without an extra review. Early approval ends the sequence sooner. Safety guards, provider failures, and whole-run budgets still apply. | Normal feature completion with `review_limit_reached` or `review_skipped`; the final unreviewed state has no review approval. Benchmark correctness remains independently evaluated. |
| Reviewer or evaluator unexpectedly writes source | Deny reviewer writes to the submission and compare its snapshot before and after. `review_run` records commands in disposable copies and detects tracked source changes there. | Allow build output and temporary tests in a copy. A check that changes tracked source is invalid; grade the original immutable snapshot. | Runner/evaluator custody failure if protected source changed; no evidence from an altered copy is certified as validation of the original. |
| Host command attempts to modify runner-owned Git metadata | Deny Git metadata writes in the command sandbox; retain command output and status. Check authoritative state before runner publication. | The runner may publish actual source changes after execution. Do not grant the command index/history access to resolve its error. | Ordinary failed command when denied; a changed protected index/history is an enforcement failure. |
| Explicit feature/review token or time cap, or whole-run limit | Enforce against recorded counters and elapsed time outside the prompt; record threshold, observed value, and stop scope. By default only whole-run time/token/turn limits apply; stage time/token caps are opt-in. | Retain actual source and stop the workflow. Local review/loop stops capture the stopped checkpoint for grading; whole-run stops grade already captured snapshots and leave the active uncaptured checkpoint ungraded. Do not start later checkpoints, prompt the agent to hurry, or ask the reviewer for an unsupported conclusion. | Execution incomplete; unresolved checkpoint is not approved. |
| Apparent operation loop | Compare completed operation inputs, outputs, and relevant state, not just repeated command text. Polling and rerunning a test after edits can be legitimate progress. | Bound demonstrably unchanged repetition according to the recorded policy. Preserve the operations that established the decision. | Loop stop with evidence; distinguish it from a task failure or an ordinary polling operation. |
| Battery loss, process crash, or external signal | On restart, reconcile the durable run manifest, operation journal, provider sessions, owned child processes, source tree, and accounting receipts. | Resume only from an established boundary. An uncertain in-flight operation blocks automatic replay; completed operations return saved results. Never reset retained work merely to obtain a clean tree. | External interruption until reconciliation completes; resumption must not invent prior completion. |
| Evaluator unavailable, timeout, invalid JSON, or zero collected tests | Preserve preflight identity, command/exit result, logs, test inventory, and cleanup receipt. | Run preflight before model work; grading retries use an immutable snapshot and separately owned disposable environment. Reap only this run's evaluator resources. | Evaluator infrastructure error; no pass rate inferred from absent tests. |
| Evaluator reports assertion failures with a valid inventory | Preserve authoritative test counts, collection identity, snapshot commit/tree, and runtime identity. | Record results without feeding hidden evaluation fixtures into the author conversation. Subsequent evaluation must name the snapshot it graded. | Benchmark failed; workflow can still be complete. |
| A configured final check changes submitted source or Git history | Compare source, index and commit identity before and after. No model runs after the last author/repair. | Preserve evidence and reject the mutation; evaluate only the recorded author snapshot. | Invalid final check or custody failure, never an extra repair opportunity. |

## Durable operation boundaries

The minimum record needed for safe execution and resumption is:

1. Run, stage, provider turn, and tool-call identities, plus exact arguments.
2. Validation outcome before launch.
3. An execution-start record written before running the operation.
4. An execution-completion receipt containing exit/error status, output artifact
   identities, workspace changes, and resulting source/commit identity.
5. Result-delivery attempts, recorded separately from execution completion.

The current transport logs a send attempt before writing to the connection. It
does not establish acknowledged delivery. Delivery can therefore remain unknown
even when the durable completion receipt establishes that execution finished.
That receipt, not the send log, is what makes replaying the saved result safe.

An operation left between start and completion is **unknown**, not implicitly
failed or safe to retry. A crash can occur after effects reach disk but before a
completion receipt does. Automatic exactly-once execution is not generally
possible for arbitrary shell commands at that boundary; safe recovery requires
reconciliation or an explicit stop. The runner must not claim a stronger guarantee.

Native harness tools also require provider evidence before recovery can assume
whether they ran. A completed model response and a completed tool operation are
different facts.

Pi can emit a local empty assistant error when cancellation prevents a new
request during preparation. The runner excludes that event from response
coverage only with a durable receipt proving that preparation/provider dispatch
was never called. Receipts are outside agent writable paths and match the
thread, turn, model, provider, and complete synthetic event sequence. Empty
errors without this proof, and any preceding unpriced response, remain
incomplete; no token count is inferred from missing output.

## Required regression and fault-injection coverage

- P012-9: a structured patch with a trailing newline after `*** End Patch` is
  valid; creating a nonignored file through a host command retains the actual
  new file and does not abort because it was absent before execution.
- A command changes a tracked file, creates another, changes executable mode,
  and then exits unsuccessfully. The retained tree and receipt show all effects.
- Delivery loss after an executed operation returns the saved receipt on replay;
  the operation's visible side effect occurs only once.
- Crash injection before launch, after launch, after filesystem effects, after
  completion recording, and after delivery distinguishes safe replay from an
  unresolved operation.
- Provider refusal, disconnect, context/output limits, and missing usage cannot
  produce approval, an invented zero-token response, or duplicate execution.
- Native delegation remains enabled/configurable with C17 off; child usage and
  compaction are included once and missing receipts block a complete measurement.
  C17 on disables and checks collaboration settings and denies installed harness
  launchers. Both harnesses enforce the shared filesystem and global budgets.
  Saved traces can be replayed without generation using
  `tests/replay_native_children.py`; output belongs outside original runs.
- Reviewers cannot modify the submission; checks can build and create temporary
  tests in a fresh copy. Invalid, stale, or missing structured verdicts cannot
  approve a feature. Host commands cannot modify Git metadata; runner publication
  still retains source changes. Pi tool availability follows role transitions.
- Identical polling with changing output and checks repeated after source edits
  do not trigger a loop solely because command text repeats.
- A hard reviewer limit produces an incomplete review without another
  conclusion/coaching prompt.
- A three-review allowance permits three blocking reviews and their three author
  repairs, then advances without a fourth review or an invented approval. Zero
  skips reviews, early approval stops sooner, and safety failures still stop.
- Evaluator assertion failures, infrastructure failures, timeout, and empty
  collection retain distinct outcomes and do not mutate the graded snapshot.
- Official upstream SCB prompts are rendered byte-for-byte by the pinned
  upstream renderer. The record identifies its template, renderer, raw specs,
  and rendered prompts. Fresh-thread history concatenates those original
  prompts without local coding instructions or hidden evaluator content.

Complete Codex and Pi benchmark runs provide end-to-end evidence. Report
their execution status, checkpoint/final correctness, selected factors, workflow
and transport version, and accounting completeness separately. Run artifacts
remain outside source commits.
