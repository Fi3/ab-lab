# Agent Behavior Lab

Compare coding-agent harnesses and selected behavior conditions on the same
benchmark. The runner records implementation, independent review, repairs,
benchmark grades, and token accounting. It does not assume that
an enabled condition improves quality or reduces work.

[SWE-Milestone projects](docs/SWE_MILESTONE.md) can be imported and run separately
with the existing runner. The adapter adds independent grading and per-milestone
code-quality measurements after a run.

The current workflow is `benchmark-native-delegation-no-integration-v5`. There are **eight
active factors**. C25 and the old printed-command protocol have been removed;
there is no legacy execution mode. Historical run artifacts remain historical
evidence and are not directly interchangeable with current runs.

## Agent requests and tools

The implementation prompt contains the benchmark request and the enabled
factor instructions. It does not add generic coding, testing, documentation,
worktree, or budget coaching. Repair prompts add the review findings, and
recovery prompts report the state needed to continue. Harness-provided system
instructions and repository instructions still apply.

With **C17 on**, the agent calls actual tools registered with its harness:

| Tool | Behavior |
| --- | --- |
| `host_read` | Return complete current file text. |
| `host_edit` | Apply a patch and commit the resulting source changes. |
| `host_run` | Execute a command and report its actual output, exit status, and source changes. |

Codex receives dynamic tools through its app-server connection. Pi receives
registered tools through its SDK connection. The host owns the Git index and
history in this condition; native tools remain available for read-only
inspection.

Commands do not declare which files they might write. The runner records actual
tracked changes, new source files, deletions, and executable-bit changes after
execution. It commits source effects even when the command returns a failure,
so the next action can use the real state. Ignored build artifacts remain
ignored. The command sandbox denies writes to the host-owned Git metadata;
the runner publishes source changes after execution. Unsupported source objects
stop execution with their actual state retained.

Tool requests and results are journaled by call identity. A repeated completed
call returns its recorded result without executing again. A call whose effects
may have occurred but whose final receipt is missing stops for inspection; an
arbitrary shell command cannot be assumed safe to replay after a crash.

With **C17 off**, the agent uses native editing and execution tools. The runner
records its actual files at the stage boundary, without requiring the agent to
make a commit. Both modes use normal harness completion. There is no required
completion token, final JSON object, ban on prose, or instruction to print a
command for the runner to parse.

Native tools still use configured filesystem permissions. Native mode means
native harness tools, not unrestricted access to the laptop. Execution uses the
isolated checkout, permitted run-owned paths, and temporary storage. The shared
execution policy permits network access. Independent reviewers have read-only
access to the submission and writable temporary space. Their `review_run` tool
runs checks in fresh writable copies of the reviewed commit. Changing tracked
source in a copy invalidates that check; the submission remains unchanged.
Pi hides native edit/write tools from read-only roles. These restrictions are recorded
experimental conditions, independent of whether evaluation uses Docker.

Reviewers submit structured findings through `submit_review`, bound to the
current round and commit. Invalid arguments receive tool feedback; missing or
incomplete verdicts cannot approve a feature. The runner applies the configured
priority threshold to the submitted findings. Final prose is not parsed as a verdict.

## Workflow and failure handling

Each feature gets a fresh author conversation and, when enabled, an independent
reviewer conversation. `--max-review-loops N` sets the maximum number of reviews
per feature and defaults to **3** with `--preset all`, or **0** with
`--preset native`. After the initial implementation,
each review with blocking findings is followed by an author repair. After the
Nth repair, the workflow continues to the next feature without another review.
An approving review ends the loop sooner. `--max-review-loops 0` skips feature
review and proceeds after implementation.

The default blocking priorities are P0, P1, and P2; P3 findings remain advisory.
An empty diff is reviewed against the requested behavior and does not imply
approval. Reaching the review allowance is normal workflow completion, but the
final repair remains unreviewed and is not recorded as approved. Independent
benchmark evaluation determines correctness.

After feature attempts, the runner executes the configured final checks and
independent evaluation against the final author submission. There is no final
integration agent, plan/accept exchange, repair stage, or history linearization.
The runner preserves author commits and records uncommitted source at checkpoint
boundaries so every evaluation has an immutable source identity.

Limits are enforced outside agent prompts. By default, author and reviewer
work share the explicitly selected whole-run time, token, and turn limits.
There is no separate feature token cap or review token/time cap. Default
feature policy:

| Setting | Default |
| --- | ---: |
| Reviews per feature (`--max-review-loops`) | 3 for all; 0 for native |
| Feature observed raw tokens | No separate cap |
| Per-review observed raw tokens | No separate cap |
| Per-review wall time | No separate cap |
| Review receipt settlement allowance | 600 seconds |
| Repeated failed-operation cycle threshold | 3 for all; disabled for native |

A configured review token or time cap stops the workflow; it does not start
another generation asking for a conclusion or advance to the next feature. The
settlement allowance lets an already in-flight response
supply its accounting receipt. It does not grant approval to a late verdict,
and global or token limits can end settlement sooner. Observed-token limits can
overshoot while usage arrives and cancellation takes effect; they are not
hard billing caps.

Repeated reads and successful polling are not treated as failed-operation
loops. Repeated failing operations with unchanged state, repeated rejected
source trees, repeated blocking findings, and exhausted explicit feature limits
can produce `needs_attention`. A stopped author may receive one final review
when configured and when both the review allowance and remaining limits permit it.

Completed features proceed after approval, the configured review/repair rounds,
or implementation when reviews are disabled. An unfinished review, failed repair,
or safety guard still stops the workflow as incomplete; exhausting the review
allowance does not bypass these failures. For a local review/loop
stop, SlopCodeBench retains and independently grades the stopped snapshot;
later checkpoints and final evaluation remain unrun. Whole-run or provider stops
retain the checkout and grade already captured snapshots; an uncaptured active
checkpoint remains ungraded. A provider refusal,
unreconciled interruption, missing accounting, or infrastructure failure is
reported separately; it is not approval or a successful benchmark result.

See [the failure-mode contract](docs/FAILURE_MODES.md) for detection, retained
state, retry rules, and outcome ownership. A new invocation requires a fresh
output directory. There is no automatic resume of an interrupted run and no
silent replacement run.

Use `--loop-policy policy.json` to override known policy fields. These are the
defaults; optional stage caps accept a positive integer instead of `null`:

```json
{
  "max_feature_raw": null,
  "max_review_raw": null,
  "max_review_seconds": null,
  "max_review_settle_seconds": 600,
  "repeat_limit": 3,
  "final_review": true
}
```

`--max-review-loops` is a separate CLI option and is recorded in plans, run
manifests, batch configurations, and results. `--no-loop-detection` disables the
feature stopping policy while retaining the review allowance and global
wall-time, token, and turn limits. Native defaults to this disabled policy unless
`--loop-policy` is explicitly supplied. Policy version
`bounded-review-loops-v6` is recorded in results. If both feature and review
token caps are explicitly configured, a final review reserve is taken from
the feature budget when `final_review` is enabled.

## Setup and a first run

The Python runner uses the standard library. It requires Git, an installed
Codex binary with an existing ChatGPT subscription login, and a separately
installed `scb-check` executable. Pi runs additionally require an installed Pi
harness and its SDK. API-key authentication is rejected; there is no API-credit
fallback.

With **C17 off**, delegation follows the native harness configuration. Codex
collaboration and configured apps are available; Pi keeps normal tools and
extension discovery inside a process sandbox. Pi delegation depends on the
installed extensions or CLI usage; Pi has no built-in subagent tool. Owned child
sessions contribute to usage and global budgets, and may use their own configured
models and effort. With **C17 on**, delegation is disabled to preserve host
ownership of edits and commands. This policy follows the condition, not the model.
See [delegation and accounting](docs/nested-verification.md) and the
[native baseline audit](docs/NATIVE_BASELINE.md).

Policy versions and effective settings are recorded in provider metadata.
Historical runs retain the restrictions under which they actually ran; removing
integration accounting does not turn them into native baseline runs.

Install the quality checker in an environment with Python 3.12 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install scb-check==0.2.0
python3 -m unittest discover -s tests -v
python3 -m lab factors
python3 -m lab doctor --out runs/login-check
```

`doctor` checks configuration and authentication without model generation.
Every output directory shown here must be new.

Initialize the small example source repository once:

```sh
git -C examples/tiny-project init
git -C examples/tiny-project add .
git -C examples/tiny-project -c user.name='Agent Behavior Lab' -c user.email='lab@example.invalid' commit -m 'Initial example'
python3 -m lab plan benchmarks/example.json
```

Run with explicit global limits and a harness:

```sh
python3 -m lab run benchmarks/example.json \
  --harness codex --out runs/example-codex \
  --seconds 1800 --max-raw 3000000 --max-turns 100 \
  --scb-check .venv/bin/scb-check
```

Replace `--harness codex` with `--harness pi` to use Pi. Both default to model
`gpt-5.5` and effort `xhigh`; choose explicitly with `--model` and `--effort`.
The limits above are example settings, not a guarantee that a task will finish.

## Choosing conditions

| Factor | Enabled behavior | Disabled behavior |
| --- | --- | --- |
| C08 | Conflict refresh uses a diff against previously delivered text. | Return complete changed-file text. |
| C13 | Ask for focused author validation, with broad validation when needed. | No added validation instruction. |
| C14 | Ask to submit related implementation and tests together. | No added grouping instruction. |
| C15 | Design required tests first; no mandatory deliberately failing execution. | No test-order override. |
| C16 | Ask for exact-context structured patches. | No added edit-format instruction. |
| C17 | Host tools own source edits, command effects, and commits. | Native tools; runner captures stage source. |
| C20 | Add guidance to choose the next action from actual operation results. | Results contain facts without that guidance. |
| C38 | Add reminders to finish once required work and checks are complete. | No added completion reminder. |

All eight factors default on with `--preset all`. `--preset native` turns
**all eight off**, defaults to zero external reviews, and disables the runner
loop detector. C08 requires C17. Use `--off` and `--on`
with comma-separated factor IDs:

```sh
python3 -m lab plan benchmarks/example.json --off C13,C14,C15,C16
python3 -m lab plan benchmarks/example.json --preset native
python3 -m lab plan benchmarks/example.json --off C08,C13,C14,C15,C16,C17,C20,C38
```

C25 is no longer accepted. Its old intervention interrupted generation after a
printed host request; actual tool calls supply their own execution boundary.

## Benchmarks and SlopCodeBench

A local benchmark specifies a local Git repository, revision, feature requests,
and explicit final checks. Paths are relative to its JSON file:

```json
{
  "name": "example",
  "repo": "../examples/tiny-project",
  "revision": "HEAD",
  "features": [
    {"id": "negate", "request": "Implement negate(value) and cover positive, negative and zero values with tests."}
  ],
  "checks": ["python3 -m unittest discover -s tests -v"]
}
```

Put task requirements in the feature request. The runner does not prepend a
separate local instruction block. Removed configuration fields `instructions`
and `defer_documentation` are rejected rather than silently ignored. A configured `after_read` fixture can apply a
declared intervening source change for C08 experiments; it requires C17.

Benchmarks own their evaluation. The registrations in
`benchmarks/evaluators.py` connect a benchmark's JSON section to its adapter;
the runner uses the same lifecycle for each adapter. Existing Work Leaf and
other plain definitions keep their declared final checks. SlopCodeBench's
`slopcodebench` section and SWE-Milestone's `swe_milestone` section additionally
select independent grading, which runs automatically after every model session
has closed. The `lab run` command, harness interfaces, prompts and review
allowances are unchanged. See [the evaluator contract](docs/BENCHMARK_EVALUATION.md).

The seven [SWE-Milestone projects](docs/SWE_MILESTONE.md) run separately using
`benchmarks/swe-milestone-PROJECT.json`. A single `lab run` invocation implements
the tasks, executes public checks, grades saved submissions, and records
per-milestone quality. Set up the project's source and evaluator environment
before the first run. Evaluator readiness is checked before model execution.

Set up the pinned SlopCodeBench evaluator with Docker and `uv` available:

```sh
python3 -m lab.slopcodebench setup
python3 -m lab plan benchmarks/scb-code-search.json
python3 -m lab run benchmarks/scb-code-search.json \
  --harness codex --out runs/code-search-current \
  --seconds 7200 --max-raw 16000000 --max-turns 250 \
  --scb-check .venv/bin/scb-check
```

SlopCodeBench prompts come from its pinned upstream `just-solve.jinja` template
and upstream renderer. The upstream setup requirements, including virtualenv
and dependency instructions, are preserved. We do not add our own Python
version, entrypoint, testing, or dependency coaching. Earlier official rendered
requests are concatenated for a fresh checkpoint conversation so prior
requirements remain available; future checkpoints are not disclosed early.

Prompt provenance records dataset and evaluator revisions, raw specification
hashes, rendered prompt hashes, template and renderer hashes, and cumulative
request hashes. Fidelity is to the upstream renderer: its canary removal and
entrypoint substitution are recorded transformations, not silently asserted
byte identity to raw specifications.

Independent evaluation uses retained checkpoint snapshots after model sessions
have closed. Hidden evaluator tests and results are not fed back into the
author/review/repair loop. The final author snapshot is also evaluated against the complete test sequence.
The `scb-check` quality measurements are separate from benchmark correctness:
its findings can be present on a correctly functioning submission.

## Results and comparisons

Run artifacts live under the supplied output directory:

- `manifest.json`: benchmark identity, source hashes, factors, harness/model,
  permissions, workflow version, and limits.
- `result.json`: stage outcomes, reviews, checks, checkpoint grades, failures,
  token accounting, and final summary.
- `before-evaluation.json`: immutable workflow result before independent grading.
  `result.json` adds the normalized `evaluation` verdict and the adapter's full report;
  `summarize.py` displays these with the existing workflow and quality results.
- `checkout/`: retained source and commits.
- `provider/`: prompts, transport events, responses, and accounting evidence.
- Feature host directories: tool journals and actual execution receipts.
- `slopcodebench/`: captured checkpoint/final snapshots and evaluator evidence.
- `attention/`: retained state and findings for stopped feature attempts.

`runs/`, `.benchmarks/`, and `.venv/` are ignored by Git. Do not commit generated
run directories. Keep only intentionally selected, compact reports outside
those directories when retaining an experiment permanently.

For SlopCodeBench, read execution and correctness separately:

| Field | Meaning |
| --- | --- |
| `execution_status` | Whether all checkpoints completed their configured review/repair sequence and final checks completed. |
| `status` | Overall workflow outcome, including reviews and evaluation. |
| `max_review_loops` | Maximum reviews per feature; zero disables feature review. |
| `checkpoints[].status` | `approved`, `review_limit_reached`, or `review_skipped` for completed feature attempts; stopped attempts retain their failure status. |
| `checkpoints[].review_approved` | Approval of the recorded final feature state; `null` when that state was not reviewed. |
| `slopcodebench.checkpoints` | Independent grade for each recorded checkpoint snapshot. |
| `slopcodebench.final` | Independent grade for the final author snapshot. |
| `slopcodebench.solved` | Benchmark success from its evaluation, not a completion inference. |
| `failure.origin` | Component associated with a terminal execution failure, when present. |
| `usage.measurement_complete` | Whether required accounting evidence was captured. |

A completed execution with failed tests is a completed experiment with an
unsuccessful submission. Two passing checkpoints out of five are not a passed
full benchmark. A failed infrastructure run with partial usage is not evidence
of token savings. Read the retained stage and failure evidence before assigning
a cause; component attribution does not replace diagnosis.

Raw tokens include input and output; cached input is included once in input,
and reasoning already included in output is not added again. Owned compaction
and child-process usage are retained. Missing coverage stays explicit and blocks
further measured work instead of being counted as zero.

```sh
python3 -m lab report runs/example-codex/result.json
python3 summarize.py runs/example-codex/result.json
python3 -m lab compare runs/reference/result.json runs/changed/result.json
```

Historical results can receive an evidence-based integration exclusion:

```sh
python3 -m lab.exclude_integration runs/OLD/result.json --apply --report runs/exclusion-audit.json
```

This attaches derived metadata and preserves original usage, outcomes and source.
`summarize.py` displays comparison tokens alongside actual consumed tokens. It
uses the verified last checkpoint and before-integration quality measurement
when available; missing child attribution, snapshots, time or final checks are
reported as unavailable. It never makes an old restricted run a native baseline.
Omit `--apply` to inspect the proposed correction without writing results.

`compare` requires successful, completely measured workflows with matching
non-factor settings. Source version, prompt provenance, model, harness,
benchmark revision, policies, review allowance, and limits
can change the experiment. Rerun comparison cells under the same current runner instead of
claiming a model or factor effect from old and new runner versions.

`--repeat N --parallel P` runs N independent repetitions with at most P active
workflows. Without `--repeat`, `--parallel P` also selects P repetitions. Each
repetition has its own checkout and limits. Four matched cells can be inspected
with `python3 -m lab interaction neither.json a.json b.json both.json`; observed
interaction is not proof that individual savings add together.

The optional live probes under `tests/real_*.py` make model calls only when run
explicitly. Offline tests and probe fault injections exercise distinct failure
boundaries; neither substitutes for a completed real benchmark on each harness.
Historical experiment reports describe the versions and limitations they
actually tested.

The [host-tools verification report](docs/HOST_TOOLS_VERIFICATION.md) records
the earlier protocol reproductions and benchmark executions. Those runs used
the previous stop-and-continue policy; their completed execution status does
not establish completed review/repair for every checkpoint.

The [review-completion verification report](docs/REVIEW_COMPLETION_VERIFICATION.md)
records the earlier approval-gate contract's limit regressions, end-to-end smoke
runs, and full-benchmark attempts, including their unresolved outcomes. Those
historical outcomes do not verify the current bounded-review contract.
