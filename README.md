# Agent Behavior Lab

Measure how agent instructions and tool behavior affect token usage on coding
tasks. Run the same benchmark with different settings to investigate which
behaviors reduce work, which add work, and what happens when they are combined.

You can supply your own coding tasks, turn nine behaviors on or off, and compare
the recorded token totals. Every run keeps the same overall process:
implementation, independent code review, repairs, then final integration.
The tool measures results; it does not assume that an enabled behavior saves
tokens or promise a particular saving.

The Codex connection requires an existing ChatGPT subscription and rejects
API-key authentication. Command-launched Codex uses a run-local launcher with
the same model, reasoning setting and subscription policy. The standalone
Python runner uses only the standard library and invokes `scb-check` as a
separately installed local program. No other agent orchestrator, service or
dashboard is required.

Agent Behavior Lab uses Codex through an existing ChatGPT subscription. It does
not use API keys or API credits. It is a standalone Python command-line tool;
no other agent orchestrator, service, dashboard or third-party Python package
is required.

**Measurement limitation:** the full all-on/all-off validation is incomplete.
Interrupting after an intermediate host-request message can leave missing token
reports. Partial totals cannot establish a saving percentage. See the
[recorded failure and validation status](experiments/on-off-20260917/RESULT.md)
before starting an expensive comparison.

- [How a benchmark runs](#how-a-benchmark-runs)
- [Quick start](#quick-start)
- [Parallel repetitions and summary tables](#parallel-repetitions-and-summary-tables)
- [Code-quality measurements](#code-quality-measurements)
- [Choosing behaviors](#choosing-behaviors)
- [Every behavior explained](#every-behavior-explained)
- [Using your own benchmark](#using-your-own-benchmark)
- [SlopCodeBench tasks](#slopcodebench-tasks)
- [Reading results and combined effects](#reading-results-and-combined-effects)
- [Optional research background](#optional-research-background)

## How a benchmark runs

A **benchmark** is a Git repository, a starting commit, a list of coding tasks
(called features), and commands that check the finished result. A **run** is one
attempt to complete that entire benchmark with a chosen set of behavior switches.

The **author** is the coding agent. The **reviewer** is a separate agent
conversation that checks the author's changes. The **host** is this local Python
program, not another model: when host-managed editing is enabled, it carries out
the author's edit and command requests and returns their actual results.

Features run **one after another, not in parallel**. For each feature:

1. An author implements the feature and its tests.
2. An independent reviewer checks the changes.
3. If the reviewer finds problems at a selected blocking priority, the same
   author repairs them and the same reviewer checks again. This continues until
   no selected findings remain, a progress/budget rule requests attention, or
   a run limit or execution failure stops the run.

Stalled attempts have a separate terminal status, **`needs_attention`**. They
are finished automated attempts, not reviewer approvals. In ordinary workflows,
later dependent features do not start; independent batch repetitions continue.
SlopCodeBench instead retains and grades each stopped attempt and proceeds to
the next cumulative checkpoint, within the global run limits. The runner does
not automatically ask another model or person to take over.

The default progress policy stops on any of these conditions:

- The same rejected source tree appears again, including a return to an earlier
  tree after intervening changes. Different commit messages do not hide a cycle.
- A blocking finding repeats in three consecutive reviews (two claimed repairs).
  Matching ignores whitespace only; it does not guess semantic similarity or
  infer progress from the number of findings.
- A cycle of one, two or three host operations repeats three times with the
  same source state and operation results. This detector applies to host-managed
  operations; native tool runs still have review and budget limits.
- Three repair attempts have each been reviewed and still have blocking findings.
- A feature reaches its token allowance, or a bounded review conclusion cannot finish.

Each feature has **3,000,000 observed raw tokens**, including author/reviewer
work, compaction and nested verification. **500,000** of those tokens are
reserved for one final review; author implementation/repair work uses at most
the other **2,500,000**. An ordinary review can use the remaining feature budget.
At **500,000 tokens or 300 seconds**, exploration stops and the same reviewer gets
one request to conclude using its existing evidence. The conclusion has a hard
**200,000 additional-token** limit and a **90-second** stop threshold, within the
remaining feature and global budgets. An already completed, fully accounted
ordinary-review verdict is retained.
The threshold alone does not flag a loop or end the feature: findings enter the
normal repair cycle, and approval allows the next checkpoint.
These are configurable policy values, not claims about the
optimal budget for every problem. Global run limits always still apply. Limits
are enforced inside both providers as well as between turns; in-flight responses
can overshoot observed-token limits before cancellation and their usage remains
charged.

Policy `bounded-feature-review-v3` gives an in-flight response up to **600 seconds**
after a review time threshold to supply its usage receipt before cancellation.
The first timeout and settlement outcome are recorded separately. New reasoning
or message activity invalidates an earlier receipt; repeated counters do not
qualify. A conclusion or final review that exceeds its time threshold remains
stopped and unapproved even if its final text arrives during settlement.
Global time/token limits and feature/review token limits preempt this wait.
Missing receipts at the end of the wait still stop further generation. This
changes v2's immediate cancellation at review time limits; it does not change
past results or grant approval because a budget expired.

When the author stops, the current clean committed code gets at most one final
independent review, with a hard 500,000-token limit and 300-second stop threshold within the reserve
and remaining global budget. An approval
allows normal progression, retaining the stop flag in the result. A rejection,
unfinished conclusion, explicitly incomplete review, dirty checkout or pending
host changes requires attention.
A review-loop stop already has a rejection and does not buy another review.
The same applies when a rejection leaves no author allowance, or a stopped
repair leaves a source tree that was already rejected: the existing verdict is
retained, without a fake repair attempt or another review of unchanged code.
Missing usage evidence or execution failures remain failures, not approvals.

`result.json` records `review_wrapups` separately from terminal `loop_flags`, the effective `loop_policy`, and (when
escalated) `attention` and `blocked_features`. Each flag links to
`attention/<feature>/event-NN/handoff.json`, with a human-readable README,
requirements, review history and a tracked-source patch. The owned checkout and
provider/host artifacts retain untracked work, operation results and test
evidence. A human or stronger model can inspect this packet without rerunning
the stalled author. Summaries show these handoffs, including flags on runs that
subsequently passed review. The CLI exits nonzero for `needs_attention`.

Use `--loop-policy policy.json` on `plan` or `run` to override selected defaults:

```json
{
  "max_feature_raw": 3000000,
  "max_repair_attempts": 3,
  "repeat_limit": 3,
  "max_review_raw": 500000,
  "max_review_seconds": 300,
  "max_review_wrapup_raw": 200000,
  "max_review_wrapup_seconds": 90,
  "max_review_settle_seconds": 600,
  "final_review": true
}
```

Set `final_review` to false to escalate immediately after an author stop.
`--no-loop-detection` disables the feature policy while retaining global limits.
Policy values and version participate in comparison matching, are forwarded to
batch workers, and are preserved by supported continuations. Compare runs using
the same policy; do not change a past run's recorded result or reclassify a
budget stop as a detected repetition loop.

`--review-priorities P0,P1,P2` selects which review findings require repairs and
block the next feature. This is the default: P0 is critical, P1 is high priority,
P2 is a meaningful defect, and P3 covers minor issues or nits. The independent
review still runs in full; findings outside the selected priorities are retained
as advisory and do not trigger another repair round. Each blocking finding must
identify the affected requirement, a concrete problem or reproducer, and its
impact. Priority selection applies to both harnesses and parallel repetitions.
It is recorded in plans, manifests, results and comparison settings; use the
same selection when comparing behavior switches.

For example, inspect a plan with only P0 and P1 findings blocking, or include
all four priorities:

```sh
python3 -m lab plan benchmarks/example.json --review-priorities P0,P1
python3 -m lab plan benchmarks/example.json --review-priorities P0,P1,P2,P3
```

The same option can be added to any `python3 -m lab run` command. Omitting it
keeps P0, P1 and P2 blocking; a nonempty comma-separated selection from P0 through
P3 is required when the option is supplied.

If the requested feature already exists, the author need not invent source
changes. The independent reviewer checks the complete requested behavior and its
tests; an empty diff is not approval. A verified unchanged feature receives an
explicit verification-only empty commit during final integration unless
`--skip-linearization` is set. It still has
an author, review, any necessary repairs and the same final checks.

Only then does the next feature begin, with a new author and reviewer. After all
features pass review, a separate integration agent proposes how to finish the
remaining work. The runner accepts that plan, and the same agent carries it out.
By default, required documentation and repairs belong with their feature, and
the final Git history has **one commit per feature**. The runner executes the benchmark's
final checks and requires a clean working directory. This history cleanup does
not mean summarizing or shortening the agent's conversation.

`--skip-linearization` preserves the reviewed commits instead of reordering or
squashing them into one commit per feature. The final integration agent still
plans and completes required documentation, validation and genuine repairs,
appending new commits only when needed. Reviews, final checks, clean-checkout
requirements and all three code-quality measurements remain enabled. The flag
works with `plan`, single runs and parallel repetitions, for both Codex and Pi.
It is recorded in the JSON and comparison settings; compare runs using the same
setting. Without the flag, the default history cleanup remains required.

The switches mainly affect the author, including review repairs. They do not
remove the independent reviews, the final integration stage, required behavior,
or the final checks. They also do not change the number or order of features.

Each new run uses a separate Git checkout containing only the chosen starting
commit and its ancestors. Later commits, unrelated branches, tags, object-store
links and remotes are not copied. The source repository is not edited. This
isolates the checkout's Git history; it is not a filesystem-wide read barrier
against deliberately opening the original repository. Existing saved runs and
explicit continuations retain their original history policy.
Prompts, responses, command output, temporary commits,
token records and failures are retained in its output directory. An invocation
starts one workflow unless explicit repetitions are requested. Repetitions run
the same benchmark and settings in separate checkouts; they do not parallelize
the feature/review sequence inside a workflow. Failed attempts are retained,
never automatically retried or replaced.

A native author's completion marker is one unquoted final `@standalone done`
line; a preceding summary is allowed. The marker does not waive clean-source,
independent-review or final-check requirements. Explicit recovery of a saved
first native response can continue at review with the original author and costs.
It requires a clean pinned checkpoint, complete prior accounting and an
exclusive continuation record; it is not an automatic retry or a general resume
of arbitrary failed stages. The original result and a reconstructible source
checkpoint remain preserved. See the [recovery verification](VERIFICATION.md).

## Quick start

Requirements: Python 3.11 or newer for the runner, Git, the Codex CLI already
configured with your ChatGPT subscription login, and the external `scb-check`
program. The runner uses only Python's standard library; `scb-check` has its own
Python 3.12+ environment and dependencies. It runs locally without a model or
API credits. Run the commands below from this repository's root directory.

For example, using a Python 3.12+ interpreter:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install scb-check==0.2.0
. .venv/bin/activate
```

Alternatively, keep your existing environment and pass
`--scb-check /absolute/path/to/scb-check` to `run`. Installation never happens
automatically during a measured workflow.

```sh
python3 -m unittest discover -s tests -v
python3 -m lab factors
python3 -m lab doctor --out runs/login-check
```

`factors` lists the behavior switches. `doctor` checks the existing subscription
login and configuration without asking a model to generate a response. Its
output directory must not already exist.

### Pi and Codex controls

Both `--harness pi` and `--harness codex` default to `gpt-5.5` with `xhigh`
reasoning. `--model` and `--effort` explicitly override those defaults; Pi's
global default model is not used. Pi requires its installed Node SDK and the
Codex CLI, and uses the `openai-codex` ChatGPT-subscription provider. Its actual
model, provider and reasoning setting are checked before generation.

The benchmark requests, factor prompts, review/repair sequence, final integration
and checks are shared. Pi's shell commands and native file operations run inside
the Codex OS sandbox: read-only for mediated authors and integration planning;
workspace writes for native authors, reviewers and accepted integration.
Reviewers may run checks that create ignored build output, but any change to
source, nonignored files, the index or history fails the review's snapshot guard.
Reviewers must report repairs for the author, not perform them. Network access,
including localhost sockets, is enabled in both read-only and writable modes.
Host-run commands and final checks use the same writable sandbox as native tests.
Writable roots include the owned checkout and its Git directory, temporary
scratch space, the run's child-call receipts and the existing Codex state directory
needed by command-launched verification agents. Other filesystem paths remain
read-only. No credentials are copied. Read-only roles do not gain these writes.
Permission changes between stages preserve the agent conversation.
Automatic Pi extensions are disabled; the
runner loads only its permission wrapper, retaining Pi's native tool definitions.
Pi's shell-output capture runs outside the command sandbox, so large outputs can
be saved to temporary logs and read back without granting commands write access.

Both harnesses use the same guarded launcher for command-launched Codex checks.
Child launch/resume uses the benchmark model and reasoning setting, contributes
to the token limit and reported total, and must finish with complete usage before
further work. With Pi, `--codex` selects the CLI used for the sandbox and children;
`--pi` selects Pi itself. Missing sandbox support or mismatched models stop the
run before generation rather than falling back to unrestricted execution.

These are controlled harness comparisons, not identical internal agent
implementations: Pi and Codex retain their own system prompts, native tools and
execution strategies. Older Pi results without the sandbox/child policy do not
have equivalent controls and their parent-only counts are not whole-workflow
token totals.

Each workflow checks native Git index-write access in its fresh clone before
asking the model to work. The check uses no model tokens and saves
`provider/git-write-preflight.json`. Writable author and integration turns may
use the shared writable scope above; reviewer checks have the same
write scope with the additional unchanged-source guard. Read-only roles stay read-only.
Provider identities record `shared-checks-network-enabled-v1`, so comparisons
distinguish these execution conditions from earlier network-restricted runs.
Token accounting is independent of this permission policy; saved historical
results remain unchanged. `doctor` checks login/configuration
only and does not refresh a repository's Git index.

For a small example, initialize the included Python project as a Git repository
once, then inspect the planned run:

```sh
git -C examples/tiny-project init
git -C examples/tiny-project add .
git -C examples/tiny-project -c user.name=Research -c user.email=research@example.invalid commit -m 'ADD tiny benchmark starting point'
python3 -m lab plan benchmarks/example.json
```

`plan` shows the benchmark, effective switches and author instructions without
starting an agent. To actually attempt the two-feature example:

```sh
python3 -m lab run benchmarks/example.json --out runs/example-all \
  --harness codex --seconds 600 --max-raw 300000 --max-turns 24
```

Only `run` spends model-generation capacity. It requires a fresh output directory
and three positive limits: elapsed seconds, observed raw tokens (input plus
output), and agent turns (requests to continue an agent conversation). These
limits are ceilings, not a promise that the benchmark will finish within them.
The defaults are GPT-5.5 with `xhigh` reasoning effort; `--model` and `--effort`
select alternatives supported by your configured backend.

Record the intended comparison and its limits before starting runs. Begin with
a small check of the idea, retain failed and partial attempts, and inspect their
behavior before paying for repetitions. The observed-token limit can overshoot
while a response is in progress or its usage report is late; it is not a hard
token cap. Time and turn limits still apply when usage reports are missing.

## Parallel repetitions and summary tables

Add `--parallel 3` to a run command to execute three copies of the same benchmark
at once. All settings, including enabled switches, model and checks, apply to
each copy. The starting Git commit is resolved once for the entire batch, even
if the source branch moves while another repetition waits to start.

```sh
python3 -m lab run benchmarks/example.json --out runs/example-parallel \
  --harness codex --seconds 600 --max-raw 300000 --max-turns 24 \
  --scb-check .venv/bin/scb-check --parallel 3
```

Use `--repeat 9 --parallel 3` for nine runs with at most three running at once.
`--repeat 3` runs three copies sequentially. Without either option, the command
keeps its single-run output format. Limits are **per run**, not per batch:
nine repetitions can consume up to nine runs' worth of subscription capacity.
Queued runs receive their own time allowance when they start.

The batch output directory must not exist. It contains:

```text
example-parallel/
  batch-input.json        shared settings, pinned commit and source hashes
  result.json             aggregate JSON containing every requested outcome
  logs/                   separate stdout/stderr for each worker
  run-001/result.json     first run, alongside its checkout and full artifacts
  run-002/result.json     second run
  run-003/result.json     third run
```

Each requested run executes once. One failure does not discard other outcomes
or add a replacement. Ctrl-C stops active workers and records queued runs as
`not_run`. Workers receive time to close their providers and retain partial
results before forced shutdown. A worker that crashes without a token report
has unknown usage, never an invented zero. The batch exits unsuccessfully if
any requested run fails or does not run. The final aggregate is also printed
as one JSON object on stdout; worker output does not interleave with it.

The root script `summarize.py` renders a Markdown table from a batch, one run,
several result files, or the JSON array printed by `lab report`:

```sh
python3 summarize.py runs/example-parallel/result.json
python3 summarize.py runs/first/result.json runs/second/result.json
python3 -m lab report runs/example-parallel/result.json | python3 summarize.py
```

With no file argument it reads JSON from stdin, so a run command can also pipe
its output directly into the script. In Bash, use `set -o pipefail` if the
pipeline's exit status must preserve a failed run; the script's own exit status
reports whether it successfully rendered the JSON.

The main table shows status, observed raw tokens, cached input, measurement
completeness, elapsed time, reviewed features and passed final checks. Reviewed
features counts reviewer approvals, not independent feature acceptance tests
or guaranteed correctness. Separate rows show all three code-quality
checkpoints. Missing values stay missing;
failed runs remain visible. The total includes known usage from failed runs.
The mean includes only passed, fully measured runs with matching settings and
says how many runs it includes. No saving percentage is inferred. Supply a
batch result or its individual results, not both: duplicate run IDs are rejected
to prevent double counting. Reading these reports starts no agents.

## Choosing behaviors

Each behavior has a short command-line ID such as `C08`. These are retained
research labels, **not prerequisites you need to learn elsewhere**. The numbers
are not consecutive because this tool includes nine selected behaviors from a
larger earlier investigation. The complete meaning of every supported ID is
below. Output files call these switches `factors`.

All nine are on by default. `--off C08,C25` turns those two off; `--on C08`
turns that one on. Both options accept comma-separated IDs and work with `plan`
and `run`. For example, inspect a plan without the extra finishing reminders:

```sh
python3 -m lab plan benchmarks/example.json --off C38
```

For instruction switches **C13, C14, C15, C16, C20 and C38**, off means no extra
instruction from that switch. It does not impose an opposite policy. Ordinary
agent behavior, repository instructions and benchmark requirements remain in
force. Operational switches C08, C17 and C25 select the execution behaviors in
the table. Neither setting promises better results or lower token usage.

| ID and detailed explanation | On | Off |
| --- | --- | --- |
| [C08: Short updates after an outdated edit](#c08-short-updates-after-an-outdated-edit) | Send the changed lines relative to text already delivered | Send the complete changed file, subject to the shared fallback rules |
| [C13 *: Focus checks during implementation](#c13-focus-checks-during-implementation) | Focus author checks; keep broad final checks | No extra validation guidance |
| [C14 *: Submit code and tests together](#c14-submit-code-and-tests-together) | Group related code and tests in one edit | No instruction about grouping or separating edits |
| [C15 *: Make the failing-test demonstration optional](#c15-make-the-failing-test-demonstration-optional) | No required failing test run before implementation | Keep the repository's and agent's normal test-order rules |
| [C16: Choose the edit format](#c16-choose-the-edit-format) | Structured exact-text patches | No format instruction; native tools remain available, or the host accepts either supported patch format |
| [C17: Let the local program carry out operations](#c17-let-the-local-program-carry-out-operations) | Host executes edits, commits and checks | Agent uses its own editing and command tools |
| [C20 *: Remind the agent how to use command results](#c20-remind-the-agent-how-to-use-command-results) | Include a next-action reminder | Omit that reminder, retaining actual results |
| [C25: Stop generation when a host request is ready](#c25-stop-generation-when-a-host-request-is-ready) | Interrupt after a complete request and a short usage-report wait | Let the turn end naturally before acting |
| [C38 *: Remind the author when to hand over](#c38-remind-the-author-when-to-hand-over) | Explicitly finish when required work and checks are done | Omit those extra finishing reminders |

Presets are starting settings; `--on` and `--off` override them:

| Preset | Starting settings |
| --- | --- |
| `--preset all` (default) | All nine on |
| `--preset j04` | C08 and C25 off; the other seven on. The name identifies an earlier experiment, explained in the optional background. |
| `--preset native` | C08, C17 and C25 off; the other six on. “Native” means the agent uses its own editing and command tools. |

C08 and C25 require host-managed operations, so C17 cannot be off while either
is on. Unsupported combinations fail before generation; the runner does not
silently change another switch. To compare who performs operations alone, keep
C08 and C25 off in both runs, then vary C17.

## Every behavior explained

Some switches change instructions, while others change the program's actions.
An instruction does not guarantee that the model follows it: inspect the saved
conversation. Likewise, a switch being enabled does not prove that the situation
it handles occurred. The possible token effects below explain **what to test**,
not measured savings or guaranteed outcomes.

### C08: Short updates after an outdated edit

This asks: **when a file changed after the agent read it, how much of that file
should it receive to repair a rejected edit?**

- **On:** send a diff, meaning the changed lines with nearby context, compared
  with the version previously delivered to the agent.
- **Off:** send the complete current file instead, when that same diff is
  available and within the shared size limit.

Example: the agent read a 2,000-line file. Another operation changed two lines,
so its proposed edit no longer matches. On sends the small update; off repeats
the whole current file. Both provide information about the real current source.

Possible token effect: the smaller update can put less text into the agent's
next input. It is not a general “make all output shorter” switch, and a diff is
not always smaller or easier for the agent to use.

The condition matters. The host must remember text actually delivered earlier,
the file must have changed, and an edit must be rejected. An ordinary agent
file inspection is not enough: `@standalone read path` asks the host for the
complete file and records that delivered version. An earlier full-file refresh
can also establish it. Once the host accepts the author's edit to that file,
it clears the old remembered version; an acceptance message alone does not count
as delivering the complete edited file.

Both settings use the same fallback rules:

- No remembered version: send the full file only if it is at most 8 KiB
  (8,192 bytes); otherwise ask the agent to request an explicit read.
- No change since the remembered version: report that it is unchanged.
- The diff is unavailable or larger than 48 KiB (49,152 bytes): ask for an
  explicit read instead of automatically sending either representation.

Those are byte limits, not token limits. The 8 KiB limit applies to a first
automatic full-file refresh, not to an explicit read or every off-setting reply.
A run with no eligible rejected edit says nothing about this switch's effect.
For a controlled opportunity to exercise it, see
[testing a file that changes after being read](#testing-a-file-that-changes-after-being-read).

### C13: Focus checks during implementation

This asks: **how much validation should the author perform before independent
review, given that full final checks still run later?**

- **On:** ask for checks focused on the current feature, leaving broad checks
  across features to final integration unless needed earlier for correctness.
  After accepting an edit, the host recommends at most one relevant focused
  validation step for that accepted work.
- **Off:** omit this checking guidance, including the host's post-edit reminder.
  Let the author follow the task and repository requirements without an added
  instruction to run either broader or narrower checks.

Example: after changing a parser, on favors its targeted parser tests during
implementation. Off leaves that choice to the normal instructions; it does not
demand another project-wide test run. The final required suite remains the same
in both cases.

Possible token effect: requesting, reading and reacting to repeated broad checks
can add conversation text and further investigation. Focused checks may avoid
some of that work. This does not mean fewer required final tests or less coverage.

The “one focused step” wording is guidance, not a hard one-command limit. Actual
failures, unfinished work and review findings still require checks and repairs.
Check the transcript to see what the author actually ran. With host-managed
operations off, the launch instruction remains, but there is no host acceptance
message to repeat the recommendation.

### C14: Submit code and tests together

This asks: **should related implementation and test changes be submitted in one
edit operation or separate operations?**

- **On:** ask the author to group related code and tests in one proposal when
  the required test order allows it. One proposal can change several files.
- **Off:** give no extra instruction about grouping or separating edits.

Example: adding a function and its unit tests can be one two-file proposal with
on. With off, the agent may still group them, or make separate edits when the
task or repository rules call for that. Separate edits are not forced.

Possible token effect: grouping can avoid extra edit requests, acceptance
messages and decisions between closely related changes. It does not remove the
tests or imply that the agent generates less implementation code.

This is not the test-order switch. With C15 off, a repository rule requiring a
failing test before implementation still applies, even with C14 on. Without
such a rule, C15 off does not introduce one. Grouping can still apply to
compatible work afterward. Both settings eventually produce the
same required one final commit per feature; this switch concerns the temporary
editing steps, not the final commit count. Grouping is an instruction, not a
guarantee that every possible change is submitted together.

### C15: Make the failing-test demonstration optional

This asks: **must the agent execute a test and observe it fail before implementing
the behavior that makes it pass?**

- **On:** design the required tests first, but do not require a separate test
  execution demonstrating the missing behavior. Implementation and tests may
  be submitted together when C14 allows it, then checked.
- **Off:** give no test-order override. Follow the repository's and agent's
  normal rules; do not introduce a mandatory failing-test demonstration.

Example: if a repository requires failing tests before implementation, off
preserves that requirement. If it has no such rule, off does not add one. On
explicitly permits implementation and tests to reach the first test run together.
A test that fails because of a broken setup is not evidence of missing behavior.

Possible token effect: an otherwise required failing run adds an execution step, its
output and decisions around it. It also prevents submitting the initial tests
and implementation together. C14 and C15 therefore can interact; their effects
should not be assumed independent. If the normal instructions already allow
tests and implementation together, this override may have little effect.

On does not mean “skip tests,” “ignore failures” or “omit regression coverage.”
The instruction explicitly overrides repository rules about this procedural
test timing, not the requirement to write and pass the necessary tests. Both
settings still require genuine failure diagnosis, review and final validation.

### C16: Choose the edit format

This asks: **how should the agent describe the file changes it wants applied?**

- **On:** use a structured patch that names each file operation and gives the
  exact old and replacement text. The host requires unambiguous text matches;
  it does not guess at a nearby match.
- **Off:** give no editing-tool or patch-format instruction. When the agent
  edits directly, it chooses its normal tools subject to repository rules.
  When the host owns edits, it accepts either structured patches or Git-style
  unified diffs inside the same edit-request protocol.

Example: with off, the agent can use its usual structured patch tool without
being told to calculate Git-style line ranges or run `git apply`. It may choose
the same format as with on. Off does not guarantee a different editing method.

Possible token effect: formats can require different amounts of text, and the
agent may make different formatting or context errors that need correction.
The two matching methods can reject different proposals, so this is not a
promise that only the number of formatting characters changes.

With C17 on, enabled C16 requires the structured format. Disabled C16 selects a
validator from the submitted patch's actual format, including when returning
changed-file information after rejection. Both validators retain path safety
and reject invalid edits without partially applying them. With C17 off, enabled
C16 prefers the native structured patch tool, while disabled C16 says nothing
about editing tools. Keep the same edit ownership when measuring the effect.

Host structured patches support `*** Mode: 100755` (executable) or
`*** Mode: 100644` (non-executable) immediately after an Add/Update File header.
A mode-only Update needs no text hunks; the host commits the permission change.
Command declarations must include paths whose permissions they change. A
successful command that only toggles regular files between 0644 and 0755, but
omits their declarations, now has those modes restored and retained as pending
changes. The agent must publish them through an explicit edit or discard them
before review. Undeclared content changes and other source/Git-state violations
remain fatal and retain the actual state for inspection.

### C17: Let the local program carry out operations

This asks: **does the author ask the host to perform edits and commands, or use
its own tools directly?**

- **On:** the author sends an edit or command request. The local Python host
  applies valid edits, makes temporary commits, runs requested checks and
  returns what actually happened. The agent's own tools are for read-only
  inspection during implementation and repair.
- **Off:** the author edits files, runs commands and creates temporary commits
  using its own tools, then hands the work over for review.

Example: with on, the author proposes a patch and receives an acceptance message
with the real commit identifier, or a rejection explaining the problem. With
off, it applies the patch and runs Git itself, receiving its normal tool results.

Possible token effect: the two approaches give the agent different editing,
commit and error-recovery work. This is a package of responsibilities and tool
permissions, not just a differently worded success message. **Both settings
receive real operation results**; off does not mean fabricated or missing feedback.

C08's conflict updates and C25's request interruption need the host request path.
They must both be off when C17 is off. To isolate C17, compare two runs where
C08 and C25 are already off, rather than comparing all-on with native mode.
The independent reviews and final integration remain present in either case.
The final integration agent uses its own tools in both settings.

### C20: Remind the agent how to use command results

This asks: **should the agent receive an explicit reminder to base its next
action on the operation result it just received?**

- **On:** include guidance to use actual results, avoid repeating accepted work
  and not assume success when results are missing. The guidance appears in the
  author's instructions and after host command results.
- **Off:** omit that particular guidance. Keep the actual command result,
  output, failure information and necessary protocol instructions.

Example: after a test command returns, on includes the reminder to choose the
next concrete action from that result. Off returns the same execution result
without this added reminder. The host has not changed whether the test passed.

Possible token effect: a reminder might prevent repeated commands or speculative
work. It also adds text to the conversation. Its net effect is something to
measure, not an automatic saving.

This is not a switch for all guidance. C13 can still guide checking and C38 can
still say when to finish, even with C20 off. Pending file changes also still need
their required handling instructions. With C17 off, the C20 launch instruction
can remain, but the host does not insert it into the agent's native tool results.

### C25: Stop generation when a host request is ready

This asks: **after the agent has supplied a complete request for the host, should
it keep generating before receiving that operation's result?**

- **On:** after recognizing a complete request in a completed agent message,
  wait for fresh usage covering that message, then interrupt further work.
  An intermediate message, continued output or elapsed time alone cannot
  trigger cancellation. The current model response may keep generating until
  its usage arrives. If the turn ends naturally first, no interruption is
  necessary. Once the turn closes, collect late usage and process the request.
- **Off:** wait for the entire agent turn to finish naturally, collect late
  usage, then process the same selected request.

Example: the agent finishes a message asking the host to run tests. On limits
further generation before the tests can actually run and their result is sent
back. Off lets the turn finish first, even if it produces more messages while
still lacking the test result.

Possible token effect: it may avoid further generation before feedback, but if
the turn would end there anyway, little or nothing may differ. Subsequent agent
behavior can also differ. **Interruption never refunds already generated
tokens.** Usage reports arriving after interruption are still collected.

A completed message does not guarantee that its numeric usage is available.
Whole-run safety limits still apply while waiting. After completion or
cancellation, collect late usage for at least one second, extending to at most
five seconds when final-message coverage is missing. If the measurement remains
incomplete, stop the workflow before another host operation or agent turn.
The [retained first-batch failure](experiments/on-off-20260917/RESULT.md) records
why a message boundary or fixed short wait is insufficient.

The trigger is a complete operation in the current agent's own completed
message, not a partial stream, quoted tool output or another conversation.
For Codex host turns, the message must be a validated structured final response;
commentary is not an operation boundary. This versioned response format is
described below under [usage and behavior records](#what-the-usage-and-behavior-records-mean).
In either setting, additional messages are retained but not executed as extra
host operations. C17 must be on. This switch does not change the subscription
login, model or underlying Codex connection between the two settings.

### C38: Remind the author when to hand over

This asks: **once the required implementation and checks are complete, how
explicitly should the author be told to stop and let the reviewer take over?**

- **On:** tell the author to hand over when its required work and relevant
  checks are done, without speculative additions or extra reporting exchanges.
  Repeat finishing guidance after accepted edits and host command results.
- **Off:** omit these extra reminders. The agent still receives its task,
  required checks and the same completion protocol.

Example: after the required code and tests are ready, on explicitly guides the
author toward review instead of another round of optional inspection or a
longer closing conversation. Off leaves that decision without these additional
reminders. Neither setting treats a passing test as permission to leave other
requirements unfinished.

Possible token effect: it may reduce work performed after a valid stopping
point. The useful evidence is what the author does after that point, not just
the number of messages in the whole run.

This differs from C13, which guides the breadth of checks, and C20, which guides
decisions from command results. They may reinforce or overlap with one another.
The completion marker `@standalone done` remains required with C38 off; turning
off the reminder does not remove the way to finish. Real failures, pending file
changes and review findings still require handling. The reviewer and final
integration agent are not skipped.

## Code-quality measurements

Every CLI `run` calls [scb-check](https://github.com/gabeorlanski/scb-check)
at three points, regardless of behavior-switch settings:

| Result key | Source measured |
| --- | --- |
| `before_changes` | The untouched starting commit, before any agent starts |
| `after_implementation` | All features after their independent reviews and repairs, before final assembly |
| `after_assembly` | The assembled work with one final commit per feature, before the runner's final test commands |

The three scores measure flagged duplication/patterns and concentration of
complexity. They **do not measure whether the requested features work**. The
functional tests and token totals remain separate. Findings are reported even
when final tests fail; an unfinished phase has `not_run`, not a zero score.

Full JSON reports appear in `result.json` under `scb_check.measurements`, in the
`run` output and in `python3 -m lab report ...`. Each measurement also retains
its commit, source-tree identifier, command, elapsed time, stdout and stderr.
The installed checker version and executable hash are recorded.

Scores are never put in agent prompts or used to demand extra repairs. A report
with findings is a completed measurement, not a failed benchmark. A missing
checker, invalid report, timeout or unexpected source modification is an error;
the run stops with its earlier evidence intact. The initial scan happens before
subscription usage. Each scan defaults to 300 seconds and must fit the overall
workflow deadline; `--scb-seconds` selects a different bound.

See [the scoring guide](SCB-CHECK.md) for metric definitions, exact commands,
supported languages, output layout and limitations. Old results without these
measurements remain unmodified; `report` displays their `scb_check` as `null`.

## Using your own benchmark

Copy [benchmarks/example.json](benchmarks/example.json) and describe your own
repository, tasks and final checks. For example, a Python project's definition
could look like this; replace the repository and task with your actual ones:

```json
{
  "name": "csv-import-example",
  "repo": "~/src/my-project",
  "revision": "main",
  "features": [
    {
      "id": "csv-import",
      "request": "Add CSV import with clear errors for malformed rows. Include tests for valid and invalid input."
    }
  ],
  "checks": ["python3 -m unittest discover -s tests -v"],
  "instructions": "Use the existing project libraries; add no dependencies.",
  "defer_documentation": true
}
```

| Field | Meaning |
| --- | --- |
| `name` | A name identifying the benchmark |
| `repo` | An existing local Git repository. `~` is supported; relative paths start at the JSON file's directory, not your shell's directory. |
| `revision` | The starting commit or Git reference. Each run records the resolved commit. Use the same fixed commit for comparisons. |
| `features` | One or more tasks, each with a unique `id` and a nonempty `request`. IDs use letters, digits, underscores or hyphens, starting with a letter or digit. |
| `checks` | One or more final shell commands that must succeed, run inside the isolated checkout |
| `instructions` | Optional instructions shared across the tasks, reviews and integration planning |
| `defer_documentation` | Optional; defaults to `true`. Leave prose/documentation edits to final integration instead of feature implementation and repair. |
| `after_read` | Optional controlled file change for conflict experiments, explained below |
| `slopcodebench` | Optional pinned SlopCodeBench task/evaluator settings; supplies `features` from the upstream problem instead of an inline list. See below. |

The runner has no hard-coded language, feature names or requirement for exactly
three tasks. Change the JSON, not the workflow code. A final check can call an
external program that scores the result; a nonzero exit fails the workflow and
the full command output is saved.

Benchmark definitions and shell commands are trusted local input. The host
checks for unexpected source, index and history changes, but it is not a
security boundary against malicious commands. Only run definitions you trust.

### Testing a file that changes after being read

C08 needs an edit based on an older file version. Sequential features may never
encounter that situation naturally. An optional `after_read` entry lets the
benchmark arrange an intervening file change without adding parallel agents:

1. The author obtains the chosen file through the host's read operation.
2. Before the author continues, the runner executes the benchmark's declared
   command once. That command changes the specified file.
3. The host commits this controlled update but retains the older text that the
   author received. If the author proposes an edit that no longer matches, the
   normal rejection and C08 refresh path can run.

See [benchmarks/conflict-example.json](benchmarks/conflict-example.json) for a
complete example. The command has a 30-second limit and may change only its
declared tracked text file, not Git state or other source. Its commit is folded
into the corresponding feature during final integration, or preserved when
`--skip-linearization` is set. This facility requires host-managed operations
(C17 on).

Use the **same** controlled update in both compared settings. It is part of the
benchmark, not an extra change secretly enabled by C08. Nothing runs unless the
JSON declares it. In the results, `fixture_executed` says whether this controlled
update ran; it does not prove that the author later submitted an outdated edit.
Inspect the saved messages and host events too. The agent may avoid the conflict.

## SlopCodeBench tasks

These optional definitions exercise building and extending a project from scratch:

| Definition | Program | Checkpoints |
| --- | --- | --- |
| [scb-code-search-smoke.json](benchmarks/scb-code-search-smoke.json) | Code-search CLI, complete workflow for the first checkpoint | 1 |
| [scb-code-search.json](benchmarks/scb-code-search.json) | Code-search CLI | 5 |
| [scb-config-service.json](benchmarks/scb-config-service.json) | Configuration HTTP API | 4 |
| [scb-log-query.json](benchmarks/scb-log-query.json) | Log-query language | 5 |

Install the pinned public [tasks](https://github.com/gabeorlanski/scb-problems)
and [evaluator](https://github.com/SprocketLab/slop-code-bench) once. This requires
Git, `uv`, and a running Docker daemon. Setup downloads Python 3.12 if needed,
installs the evaluator in its own environment, builds its Docker image, and
creates an empty starting Git repository under the ignored `.benchmarks/` directory.
It generates no model responses. `plan` and `run` never bootstrap this installation;
grading installs the submission's requirements and the upstream test dependencies
inside its disposable environment.

```sh
python3 -m lab.slopcodebench setup
python3 -m lab plan benchmarks/scb-code-search.json
python3 -m lab run benchmarks/scb-code-search.json \
  --out runs/scb-code-search --harness codex \
  --seconds 10800 --max-raw 15000000 --max-turns 400 \
  --scb-check .venv/bin/scb-check
python3 summarize.py runs/scb-code-search/result.json
```

For a smaller test, use the smoke definition. It keeps implementation, independent
review and repairs, final integration, all three quality phases, and upstream
correctness grading of both the reviewed checkpoint and the final assembly:

```sh
python3 -m lab run benchmarks/scb-code-search-smoke.json \
  --out runs/scb-code-search-smoke --harness codex \
  --model gpt-5.5 --effort xhigh --preset all \
  --seconds 3600 --max-raw 3000000 --max-turns 240 \
  --scb-check .venv/bin/scb-check
```

The optional `slopcodebench.checkpoint_limit` selects the first N checkpoints;
it must be a positive integer no greater than the task's checkpoint count.
Omitting it runs the full task. The smoke definition sets it to 1. Its result
records the limit, and `solved` applies to that selected scope. This is a complete
test of the workflow for one checkpoint, not a solve of the five-checkpoint task.
The normalized selection participates in comparison matching.

The launch interface, behavior switches, presets, harness/model selection,
repetitions, and parallelism are the same as for other benchmarks. Each checkpoint
is an ordinary feature with implementation, independent review, and repairs.
The agent keeps its own code; each fresh author/reviewer receives the current
requirements together with earlier revealed requirements. Final integration and
the JSON's ordinary final checks still run. These definitions use
`defer_documentation: false` because `requirements.txt` is an executable dependency
contract that must stay current during implementation.

The adapter saves each checkpoint's source tree before final integration can rewrite
history. After all provider sessions close, the authors' evaluator grades copies
of those snapshots and the final assembled source. Earlier snapshots remain
available even if a later step fails. Hidden-test reports never enter agent prompts,
ordinary `checks`, review repairs, or subsequent checkpoints. The upstream rules
decide which prior tests apply; intentionally superseded tests are not reintroduced.

If a workflow time, token or turn limit is reached, the runner stops agent work
and preserves `result.json`, the checkout (including accepted work in an unfinished
checkpoint), commits, logs and reviewed snapshots. Captured reviewed checkpoints
still receive upstream grading after provider shutdown; unfinished checkpoints
remain ungraded. The overall run is failed/incomplete, with the stop reason and
observed usage retained. `python3 summarize.py runs/<run>/result.json` displays these
partial results. Budget stops do not automatically resume. The token limit uses
observed counters, so an in-flight response can exceed it before cancellation.
Feature progress-policy stops end only that checkpoint's automatic repair loop.
The stopped attempt enters the checkpoint list with `status: needs_attention`,
`review_approved: false` (or `null` for an incomplete review), and no approved
`reviewed_head`. Its immutable snapshot is graded after provider shutdown, and
the next checkpoint starts with a fresh feature allowance and the earlier
unresolved findings. Applied native edits that were not committed are retained
in an explicitly labelled unapproved checkpoint commit; pending host proposals
remain in their handoff artifacts and are not silently applied. The handoff
links to the exact captured snapshot even after later checkpoints change the
checkout. This policy is recorded as `retain-grade-and-continue-v1` in the manifest
and comparison settings. Ordinary legacy workflows keep their previous stop behavior.

`execution_status: completed` means all checkpoint attempts, integration, and
final checks ran successfully. Unresolved reviews still leave the overall status
`needs_attention` and a nonzero CLI exit; they do not prevent upstream grading.
The evaluator's `status: completed` means every snapshot was graded, and
`all_tests_passed` reports their actual test outcome separately from review
approval. No stopped attempt becomes approved merely because the run continued.
Global limits, provider failures, invalid source state, and missing usage evidence
still stop execution. Integration does not reopen stopped repair loops.

`result.json` retains all existing fields and adds `slopcodebench`. Its
`workflow_status` records whether the usual agent workflow completed; `solved`
requires that workflow plus every checkpoint and final assembly to pass strict
correctness. Failing correctness or evaluator infrastructure makes the overall run
fail, so existing comparison commands cannot count incomplete work as a token
saving. Core and isolated correctness, test counts, raw evaluator reports, and
per-checkpoint quality are retained separately. Existing summary tables remain;
SCB runs add correctness tables. Empty-project initial quality is explicitly
`not_applicable`, with no fabricated zero score. The usual three quality phases
are still reported.

The usual `--seconds`, token, and turn limits apply to the agent workflow. Hidden
grading has a separate per-snapshot `slopcodebench.seconds` limit (300 by default;
600 for the HTTP pilot), plus bounded container cleanup. Total run duration includes
grading; its duration is also recorded separately. No model is used for grading.
Interrupted grading retains completed results and stops before another snapshot.

Dataset and evaluator checkouts must match the full commit hashes in the JSON
and have no local changes. Their identities, installed evaluator packages, and
Docker image identity participate in comparison matching. To use another local
installation, change the two paths in `slopcodebench` and the empty `repo` path;
relative paths start at the definition file. The optional `environment` path is
relative to the pinned evaluator. The initial adapter supports problems without
static workspace assets, including all three pilots.

The upstream evaluator resolves test and submission dependencies during grading;
those container package resolutions are not fully locked by the host evaluator's
package inventory. Pinning the task and evaluator does not freeze package registries.

This is the lab's reviewed workflow on SCBench tasks, not a reproduction of the
paper's session/environment-reset protocol. Existing agent filesystem and network
permissions are preserved: tests and future requirements are withheld from prompts
and the working checkout, but a deliberately searching agent could discover the
public dataset or the host's input manifest. This is not hardened protection against
benchmark lookup or training contamination.

## Codex context and output recovery

Codex threads use an automatic compaction threshold of at most 131,072 tokens,
preserving a lower configured threshold. Before a new request, the runner also
requests compaction when recent context plus the incoming prompt reaches that
limit or 60% of the reported context window, whichever is lower. This uses
recent context usage, not cumulative billed tokens. The prompt's UTF-8 byte
length provides a conservative estimate for this preflight check.

The runner watches streamed assistant messages for replacement-character floods,
8,192 consecutive whitespace characters, messages above 4 MiB, or a message
stream lasting over ten minutes. It quarantines suspicious output immediately;
no host command from that response executes. For whitespace or replacement floods,
it waits for the response to finish or reach a priced boundary within the existing
ten-minute streaming limit. A completed-only violation has the same ten-minute
settlement ceiling from detection. There is no earlier soft-guard cancellation
timer that could cut off the token receipt. The 4 MiB ceiling and existing run,
feature, and review budgets still interrupt immediately. Streamed assistant text
is retained in each turn's `agent-message-deltas.jsonl`, including unfinished
responses absent from `reply.txt`.

A structured context-window failure or a guarded output interruption can trigger
one compaction and continuation on the same thread.
The continuation preserves task and review requirements and asks the agent to
inspect existing tool results rather than repeat completed work.

Compaction, failed attempts and retries retain their own artifacts and count
against the run's existing time, turn and observed-token limits. Recovery requires
complete usage coverage; missing counters, unrelated failures (including terminal
provider policy errors), failed compaction and exhausted limits still stop the run.
Context policy version 4 records the bounded settlement policy in provider
identity and comparison matching. The review phase and its selected blocking
priorities are unchanged. This recovery applies to new runs; it does not resume
an already terminated run.

## Reading results and combined effects

```sh
python3 -m lab report runs/example-all/result.json
python3 -m lab compare runs/reference/result.json runs/modified/result.json
python3 -m lab interaction runs/neither/result.json runs/a-only/result.json \
  runs/b-only/result.json runs/both/result.json
```

These commands read existing files; none starts an agent. `report` can show
partial or failed attempts. `compare` and `interaction` require successful
complete workflows with no flagged usage gaps. They also require matching
settings other than the behavior switches: benchmark, starting commit, runner
code, model, reasoning effort, effective configuration and run limits.

Saved results describe the exact runner version and instructions that produced
them. Some earlier records use opposite-policy OFF instructions; those records
are not neutral-OFF measurements. Their original prompts and outcomes remain
the evidence, and must not be relabeled or pooled with different switch meanings.

Nested Codex verification inside the owned checkout is included separately in
`usage.nested` and in the total. Its model, reasoning setting, native turn
completion and usage counters are checked. Launch and resume of one conversation
share a counter; the earlier total is not added again. Contradictory command-line
model/provider overrides are rejected. A detected child mismatch or incomplete
child measurement prevents a valid comparison. Commands that deliberately bypass
the launcher, generate with another product, or generate outside the owned
checkout are unsupported; this is not a universal process/billing audit.

### Comparing two settings

The **reference** is the run you choose as the starting point for the comparison;
the **modified** run has the behavior changes you want to study. `compare` lists
the differing switches and calculates:

```text
saved tokens = reference tokens - modified tokens
reduction percent = 100 × saved tokens / reference tokens
```

For an arithmetic example, not a measured result: 100,000 reference tokens and
80,000 modified tokens means 20,000 tokens saved, or 20% of the reference.
A negative percentage means the modified run used more tokens. If several
switches changed, the result describes that group together, not each one's
individual contribution.

### Checking whether two behaviors reinforce each other

An **interaction** means the combined effect differs from adding the two
separate effects. For example, C13's focused-check guidance and C38's finishing
guidance might overlap or work better together. To examine that question, the
four inputs must differ only in those selected switches:

| Result passed to `interaction` | C13 | C38 |
| --- | --- | --- |
| `neither` | Off | Off |
| `a-only` | On | Off |
| `b-only` | Off | On |
| `both` | On | On |

Keep all other settings equal. A and B can also be two non-overlapping groups of
switches, provided the fourth run applies both groups of changes. All four
configurations must satisfy the tool's switch dependencies.

```text
total combined saving = neither tokens - both tokens
extra combined saving = a-only tokens + b-only tokens - neither tokens - both tokens
```

A positive extra combined saving means the combination saves more than the sum
of the separate observed savings. A negative value means it saves less than
that sum. The output reports token amounts; do not add percentages with different
reference totals. A single set of runs is an observation, not proof that random
variation is absent or that the same effect holds for other tasks. Repetitions
require a separate, deliberate decision; these commands do not launch them.

### What the usage and behavior records mean

**Raw tokens** means model input tokens plus model output tokens, not elapsed
time or a monetary cost. Cached input is already part of input; reasoning tokens
are already part of output. Neither is added a second time. Each increase in a
conversation's cumulative usage counter is counted once; repeated notifications
do not count as new usage.

For Codex, parent accounting also reads the exact owned rollout path returned by
the app-server. Native response receipts include compaction costs that the
app-server's cumulative counters can omit. Response IDs deduplicate receipts
embedded in compaction checkpoints. The overlapping native and app-server
totals are reconciled, not added together; their separate baselines survive
continuation. `provider/native-usage.json` retains numeric receipts and source
provenance. Manual and automatic compactions require correlated numeric
evidence, and ordinary responses wait for their native receipts before a host
command can execute. Missing evidence stops the run instead of charging zero.

The installed-Codex integration test exercises both compaction paths, continues
the same conversations, and executes fixture tests through the real framework:

```sh
python3 tests/real_compaction.py --out runs/compaction-verification --scenario both
```

Use a new output directory. This opt-in test makes bounded subscription calls
(300 seconds, 250,000 observed raw tokens, six turns) and compares accounting
against independently deduplicated native receipts. Ordinary unit-test discovery
runs the offline regressions without generating model responses.

With `--harness pi`, completed response counts are added once and reconciled
with Pi's cumulative session totals after each turn. Streaming counters may
reset between responses and are not used as conversation totals. Pi reports
uncached input, cache reads and cache writes separately; all three belong to
raw input, while `cached_input_tokens` records cache reads. Missing, invalid,
stale or decreasing session totals stop the run with incomplete measurement.
Per-turn `session_tokens` and raw transport events retain the provider's counts.

The local observer reads native Codex histories whose working directory belongs
to the run's separate checkout. Parent conversations already priced through the
main connection are excluded from child totals. Native child records retain
their source paths, model/effort, reported subscription plan and turn coverage.
The launcher and environment hooks live outside measured source. They do not
copy credentials or change the user's global Codex configuration.

Codex host-managed author turns use the app-server's per-turn
[`outputSchema`](https://learn.chatgpt.com/docs/app-server#start-a-turn) to request
one typed operation, for example
`{"operation":{"kind":"run","paths":[],"command":"python3 -m unittest"}}`.
The schema has separate fields for read, run, edit, discard and done operations;
extra fields and text outside the JSON object are rejected. The adapter validates
the complete final response and translates it into the existing host protocol,
checking that paths, command text and patch content round-trip without changing
meaning. Commentary cannot authorize an operation. Older responses with no phase
still require a fully valid JSON object. Single-line command, path and reason
requirements remain; native, reviewer, integration and Pi response formats are
unchanged.

Each typed turn retains `output-schema.json`, its actual `prompt.txt`, the raw
JSON in `reply.txt` and `messages.json`, and the delivered text in
`host-operation.txt`. The canonical operation is delivered only after all existing
usage, budget, error and permission checks. C25 acts after a validated final
operation and covering usage, instead of an unconstrained commentary directive.
The `json-schema-host-operation-v1` provider identity keeps these runs distinct
from prior protocol versions in comparisons. This format prevents exterior prose
from corrupting a conforming operation; it does not guarantee correct commands,
task completion, or acceptance by provider policy checks. Provider rejections
remain terminal and are never retried as formatting failures.

The underlying text host still accepts trailing spaces and tabs on
`@standalone done` and `@standalone end`. Patch content and command text are not
trimmed. Empty or whitespace-only trailing messages do not replace the last
substantive reply; the first accepted host request still takes precedence.
Quoted, fenced and malformed text operations remain rejected.

The opt-in live verifier exercises every typed operation with the configured
GPT-5.6-sol/xhigh subscription, real host effects and independent usage receipts:

```sh
python3 -B tests/real_host_response.py --out runs/typed-host-verification
```

Use a new output directory. This bounded fixture is not a full benchmark rerun
or a replay of a provider-rejected conversation.

Missing final usage reports and decreasing counters are flagged, not treated as
zero usage. A returned incomplete measurement stops the workflow before another
host operation or agent turn. `measurement_complete` means that the tool detected no missing
turn-end usage or counter problem. It does **not** guarantee that the provider
reported every internal response. Saved raw messages permit a deeper audit.
A response-format failure remains a failed run, but does not imply missing
usage when the completed turn already has a covering usage report.

Watch explicitly named run directories without starting an agent:

```sh
python3 -m lab.monitor runs/first runs/second runs/third --output runs/monitor
```

The observer saves a current snapshot and an append-only sample history every
15 seconds. It reports missing per-response coverage as well as counter resets
and terminal failures. It does not launch, stop or replace runs. Add `--once`
for one saved sample. Per-turn coverage is retained in `provider/coverage.jsonl`;
that journal is operator data, never additional text sent to a measured agent.

`factor_activations` records some executed host events, such as a changed-file
refresh or an accepted edit. It is not a complete checklist of instruction
compliance or a measure of token saving. In particular, C08's event includes the
actual representation used, including an omitted refresh; read that detail, not
just its count. C25 interruption reasons are in the saved turn records. For
instruction switches, inspect what the author actually did and when.

## Implementation reference

These links are for checking the descriptions against the code; they are not
required background for using the tool.

| Component | Where the behavior is defined |
| --- | --- |
| Supported switches, dependencies and author instructions | [lab/config.py](lab/config.py): `settings`, `policy_blocks`, `author_policy` |
| Conflict text, edit formats, real operation results and reminders | [lab/host.py](lab/host.py): `refresh_text`, `Host.refresh`, `plan_edit`, `plan_unified`, `Host.consume` |
| Agent connections, interruption and usage accounting | [lab/provider.py](lab/provider.py): `Codex`, `Pi`, `InterruptGate`, `Usage` |
| Nested command settings and owned child usage | [lab/nested.py](lab/nested.py): `CommandEnvironment`, `NestedUsage` |
| Explicit first-native-boundary recovery and prior-cost preservation | [lab/continuation.py](lab/continuation.py): `inspect_boundary`, `continue_native`, `restore_provider` |
| Incremental operator monitoring, including missing response coverage | [lab/monitor.py](lab/monitor.py): `sample` |
| Feature/review/repair sequence, controlled file change, integration and comparisons | [lab/workflow.py](lab/workflow.py): `run`, `after_read_fixture`, `integration_prompts`, `compare`, `interaction` |
| Commands and preset settings | [lab/__main__.py](lab/__main__.py): `main`, `factors_from` |
| Isolated repetitions, concurrency and batch outcomes | [lab/batch.py](lab/batch.py): `run_batch`, `worker` |
| Read-only summary tables | [summarize.py](summarize.py), [lab/summary.py](lab/summary.py): `records`, `render` |

[VERIFICATION.md](VERIFICATION.md) records automated and real-agent checks,
including unsuccessful attempts and the limits of what was verified.

## Optional research background

**Work Leaf** is a separate agent-orchestration project. An earlier investigation
there compared its token usage with a direct-agent workflow. **J04** was a label
for a reproduction that used an external edit-and-command host without running
Work Leaf. Agent Behavior Lab ports that host and its sequential
implementation/review/repair/final-integration process into an independent tool.
The `C` labels identify selected behaviors from that investigation; their
definitions for this tool are the sections above.

The `j04` preset selects the seven instruction/host behaviors, without C08's
compact conflict updates or C25's interruption. It is not a byte-identical replay
of the old experiment. This tool uses Codex's local app-server connection in all
settings, separates author instructions into explicit switches, and records
host-delivered file text for conflict updates. C25 off lets a turn finish
naturally; it does not recreate the earlier study's specific 120-second extended
wait. Source identities and differences are recorded in
[PROVENANCE.json](PROVENANCE.json). Do not treat new totals as interchangeable
with the earlier measurements or assign the old saving to individual switches.

[benchmarks/work-leaf.json](benchmarks/work-leaf.json) is an optional definition
using that project's original three tasks and starting commit. It includes Rust
checks but not the earlier external program that scored the requested features.
Include that scoring check before claiming the earlier benchmark's full
acceptance criteria. The `native` preset is also not a recreation of the old
direct-agent comparison: it keeps this tool's review and integration workflow.

No Work Leaf installation or knowledge of the earlier research is needed for
other benchmarks. Its product and research records remain separate.
[PLAN.md](PLAN.md) records this tool's build and placement. The provider interface
is documented in the [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).
