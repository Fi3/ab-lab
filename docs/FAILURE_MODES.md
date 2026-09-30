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

- **Execution:** did every feature receive review approval and final assembly
  finish, or did the workflow stop incomplete?
- **Benchmark correctness:** did authoritative evaluation pass, fail, or not run?
- **Review:** approved, findings, or incomplete; completion alone is not approval.
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
| Agent turn ends with no source changes | Observe normal harness completion and capture the actual workspace state. | Send the assigned requirements and existing result to independent review if review is enabled. No synthetic completion marker or empty commit is required to establish that the turn ended. | Completed author attempt; review/evaluation establish whether the task was already satisfied. |
| Review returns malformed or incomplete verdict | Preserve reviewer response and source identity. Validate verdict separately from review transport completion. | Incomplete evidence is not approval. Format correction, if configured, must not start a new code-changing repair loop or invent findings. | Review incomplete; any continuation must retain that fact. |
| Codex spawns a native subagent before its first usage receipt | Track the child through its owned parent spawn, turn events, and validated fork history. Preserve pending lifecycle and receipt state separately from token totals. | Allow parent host commands while the child runs. Wait for child completion before accepting the parent stage, within the existing budgets. Exclude inherited parent history and merge duplicate transport/native counters once. | Pending usage during execution is normal; an aborted child or missing terminal usage cannot certify a completed stage. |
| Reviewer finds a real issue | Preserve the exact finding, affected requirement, reviewed tree, and priority. | Supply findings for an explicitly configured repair round. Do not add unrelated coding advice or unspecified requirements. | Review findings; subsequent repaired trees require their own review result. |
| Reviewer or evaluator unexpectedly writes source | Compare the protected submission snapshot or workspace before and after. Save the mutation as evidence rather than silently accepting it. | Grade a disposable copy. Do not treat an altered submission as the author's original solution. | Runner/evaluator custody failure if protected source changed. |
| Explicit feature/review cap, repair limit, or whole-run limit | Enforce against recorded counters and elapsed time outside the prompt; record threshold, observed value, and stop scope. By default only whole-run time/token/turn limits apply; stage time/token and repair-count caps are opt-in. | Retain actual source and stop the workflow. Local review/loop stops capture the stopped checkpoint for grading; whole-run stops grade already captured snapshots and leave the active uncaptured checkpoint ungraded. Do not start later checkpoints or integration, prompt the agent to hurry, or ask the reviewer for an unsupported conclusion. | Execution incomplete; unresolved checkpoint is not approved. |
| Apparent operation loop | Compare completed operation inputs, outputs, and relevant state, not just repeated command text. Polling and rerunning a test after edits can be legitimate progress. | Bound demonstrably unchanged repetition according to the recorded policy. Preserve the operations that established the decision. | Loop stop with evidence; distinguish it from a task failure or an ordinary polling operation. |
| Battery loss, process crash, or external signal | On restart, reconcile the durable run manifest, operation journal, provider sessions, owned child processes, source tree, and accounting receipts. | Resume only from an established boundary. An uncertain in-flight operation blocks automatic replay; completed operations return saved results. Never reset retained work merely to obtain a clean tree. | External interruption until reconciliation completes; resumption must not invent prior completion. |
| Evaluator unavailable, timeout, invalid JSON, or zero collected tests | Preserve preflight identity, command/exit result, logs, test inventory, and cleanup receipt. | Run preflight before model work; grading retries use an immutable snapshot and separately owned disposable environment. Reap only this run's evaluator resources. | Evaluator infrastructure error; no pass rate inferred from absent tests. |
| Evaluator reports assertion failures with a valid inventory | Preserve authoritative test counts, collection identity, snapshot commit/tree, and runtime identity. | Record results without feeding hidden evaluation fixtures into the author conversation. Subsequent evaluation must name the snapshot it graded. | Benchmark failed; workflow can still be complete. |
| Integration changes a previously reviewed solution | Capture separate pre-integration and final snapshots and their independent grades. | Preserve the requested integration behavior, with its own source/commit receipts and checks. | Final score and checkpoint scores remain distinct; prior approval does not transfer to an unreviewed tree. |

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
- Identical polling with changing output and checks repeated after source edits
  do not trigger a loop solely because command text repeats.
- A hard reviewer limit produces an incomplete review without another
- Native child startup before the first token receipt does not block a parent
  host command. Child usage remains subject to the global budget; parent
  completion waits for successful child completion and its own receipts. Forked
  parent history and repeated counters do not add charges. Saved traces can be
  replayed without generation using `tests/replay_native_children.py`; output
  must be outside the original run directories. Runs without native children
  retain their previous totals and completion decisions.
  conclusion/coaching prompt.
- Evaluator assertion failures, infrastructure failures, timeout, and empty
  collection retain distinct outcomes and do not mutate the graded snapshot.
- Official upstream SCB prompts are rendered byte-for-byte by the pinned
  upstream renderer. The record identifies its template, renderer, raw specs,
  and rendered prompts. Fresh-thread history concatenates those original
  prompts without local coding instructions or hidden evaluator content.

Complete Codex and Pi benchmark runs are final integration evidence. Report
their execution status, checkpoint/final correctness, selected factors, workflow
and transport version, and accounting completeness separately. Run artifacts
remain outside source commits.
