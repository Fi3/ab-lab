# Agent Behavior Lab

Measure how agent instructions and tool behavior affect token usage on coding
tasks. Run the same benchmark with different settings to investigate which
behaviors reduce work, which add work, and what happens when they are combined.

You can supply your own coding tasks, turn nine behaviors on or off, and compare
the recorded token totals. Every run keeps the same overall process:
implementation, independent code review, repairs, then final integration.
The tool measures results; it does not assume that an enabled behavior saves
tokens or promise a particular saving.

Agent Behavior Lab uses Codex through an existing ChatGPT subscription. It does
not use API keys or API credits. It is a standalone Python command-line tool;
no other agent orchestrator, service, dashboard or third-party Python package
is required.

- [How a benchmark runs](#how-a-benchmark-runs)
- [Quick start](#quick-start)
- [Choosing behaviors](#choosing-behaviors)
- [Every behavior explained](#every-behavior-explained)
- [Using your own benchmark](#using-your-own-benchmark)
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
3. If the reviewer finds problems, the same author repairs them and the same
   reviewer checks again. This continues until review is clean or a run limit
   or execution failure stops the run.

Only then does the next feature begin, with a new author and reviewer. After all
features pass review, a separate integration agent proposes how to assemble the
finished work. The runner accepts that plan, and the same agent carries it out:
required documentation and repairs belong with their feature, and the final Git
history must have **one commit per feature**. The runner executes the benchmark's
final checks and requires a clean working directory. This history cleanup does
not mean summarizing or shortening the agent's conversation.

The switches mainly affect the author, including review repairs. They do not
remove the independent reviews, the final integration stage, required behavior,
or the final checks. They also do not change the number or order of features.

Each run uses a separate clone of the chosen starting commit; the source
repository is not edited. Prompts, responses, command output, temporary commits,
token records and failures are retained in its output directory. One invocation
starts one workflow. It does not automatically start comparison runs, repeat
failed attempts or replace unfavorable results.

## Quick start

Requirements: Python 3.11 or newer, Git, and the Codex CLI already configured
with your ChatGPT subscription login. Run the commands below from this
repository's root directory.

```sh
python3 -m unittest discover -s tests -v
python3 -m lab factors
python3 -m lab doctor --out runs/login-check
```

`factors` lists the behavior switches. `doctor` checks the existing subscription
login and configuration without asking a model to generate a response. Its
output directory must not already exist.

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
  --seconds 600 --max-raw 300000 --max-turns 24
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

“On” and “off” select the two behaviors in this table. They do **not** mean
“better” and “worse.” An off setting can require more work, and an on setting
can have no effect or even increase total usage.

| ID and detailed explanation | On | Off |
| --- | --- | --- |
| [C08: Short updates after an outdated edit](#c08-short-updates-after-an-outdated-edit) | Send the changed lines relative to text already delivered | Send the complete changed file, subject to the shared fallback rules |
| [C13: Focus checks during implementation](#c13-focus-checks-during-implementation) | Focus author checks; keep broad final checks | Ask for broader author checks too |
| [C14: Submit code and tests together](#c14-submit-code-and-tests-together) | Group related code and tests in one edit | Request separate edit operations |
| [C15: Make the failing-test demonstration optional](#c15-make-the-failing-test-demonstration-optional) | No required failing test run before implementation | Require tests to fail for the intended reason first |
| [C16: Choose the edit format](#c16-choose-the-edit-format) | Structured exact-text patches | Standard Git-style patches |
| [C17: Let the local program carry out operations](#c17-let-the-local-program-carry-out-operations) | Host executes edits, commits and checks | Agent uses its own editing and command tools |
| [C20: Remind the agent how to use command results](#c20-remind-the-agent-how-to-use-command-results) | Include a next-action reminder | Omit that reminder, retaining actual results |
| [C25: Stop generation when a host request is ready](#c25-stop-generation-when-a-host-request-is-ready) | Interrupt after a complete request and a short usage-report wait | Let the turn end naturally before acting |
| [C38: Remind the author when to hand over](#c38-remind-the-author-when-to-hand-over) | Explicitly finish when required work and checks are done | Omit those extra finishing reminders |

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
- **Off:** ask the author to perform broader validation too, including relevant
  regression and repository-wide checks.

Example: after changing a parser, on favors its targeted parser tests during
implementation. Off also asks the author to consider the broader project test
suite. The final required suite remains the same in both cases.

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
- **Off:** ask for test changes and implementation changes in separate edits.

Example: adding a function and its unit tests can be one two-file proposal with
on. With off, they are separate proposals, each followed by its own result.

Possible token effect: grouping can avoid extra edit requests, acceptance
messages and decisions between closely related changes. It does not remove the
tests or imply that the agent generates less implementation code.

This is not the test-order switch. If C15 is off, the agent must first submit
tests and run them to see the intended failure, even with C14 on. Grouping can
still apply to compatible work afterward. Both settings eventually produce the
same required one final commit per feature; this switch concerns the temporary
editing steps, not the final commit count. Grouping is an instruction, not a
guarantee that every possible change is submitted together.

### C15: Make the failing-test demonstration optional

This asks: **must the agent execute a test and observe it fail before implementing
the behavior that makes it pass?**

- **On:** design the required tests first, but do not require a separate test
  execution demonstrating the missing behavior. Implementation and tests may
  be submitted together when C14 allows it, then checked.
- **Off:** write the tests, run them, confirm that they fail because the requested
  behavior is missing, then implement that behavior and validate the result.

Example: for a new parser option, off requires a saved failing test run before
the option is implemented. On permits the implementation and tests to reach the
first test run together. A test that fails because of a broken test setup is not
the intended demonstration.

Possible token effect: the required failing run adds an execution step, its
output and decisions around it. It also prevents submitting the initial tests
and implementation together. C14 and C15 therefore can interact; their effects
should not be assumed independent.

On does not mean “skip tests,” “ignore failures” or “omit regression coverage.”
The instruction explicitly overrides repository rules about this procedural
test timing, not the requirement to write and pass the necessary tests. Both
settings still require genuine failure diagnosis, review and final validation.

### C16: Choose the edit format

This asks: **how should the agent describe the file changes it wants applied?**

- **On:** use a structured patch that names each file operation and gives the
  exact old and replacement text. The host requires unambiguous text matches;
  it does not guess at a nearby match.
- **Off:** use a standard Git-style patch, also called a unified diff, with
  file headers, line ranges, removed lines and added lines. The host validates
  it with Git before applying the planned changes.

Example: both formats can request the same change from `return value` to
`return value + 1`. On uses `*** Update File` and exact-text blocks; off uses
`---` / `+++` file headers and Git-style line ranges. The intended source change
can be identical even though its description differs.

Possible token effect: formats can require different amounts of text, and the
agent may make different formatting or context errors that need correction.
The two matching methods can reject different proposals, so this is not a
promise that only the number of formatting characters changes.

With C17 on, the host selects the corresponding patch validator and rejects an
invalid proposal without partially applying that rejected edit. With C17 off,
C16 is an instruction to use the corresponding native editing method; the host
is not applying or enforcing that format. Keep the same edit ownership when
trying to measure the format's effect.

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
  allow up to one second for a usage report. Interrupt sooner if fresh usage
  arrives or generation resumes; otherwise interrupt at the end of that wait.
  If the turn ends naturally first, an interruption is unnecessary. Once the
  turn closes, collect late usage and process the request.
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

The trigger is a complete operation in the current agent's own completed
message, not a partial stream, quoted tool output or another conversation.
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
declared tracked text file, not Git state or other source. Its commit must be
folded into the corresponding feature during final integration, not left as an
extra final commit. This facility requires host-managed operations (C17 on).

Use the **same** controlled update in both compared settings. It is part of the
benchmark, not an extra change secretly enabled by C08. Nothing runs unless the
JSON declares it. In the results, `fixture_executed` says whether this controlled
update ran; it does not prove that the author later submitted an outdated edit.
Inspect the saved messages and host events too. The agent may avoid the conflict.

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

Missing final usage reports and decreasing counters are flagged, not treated as
zero usage. `measurement_complete` means that the tool detected no missing
turn-end usage or counter problem. It does **not** guarantee that the provider
reported every internal response. Saved raw messages permit a deeper audit.

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
| Subscription connection, interruption and usage accounting | [lab/provider.py](lab/provider.py): `Codex`, `InterruptGate`, `Usage` |
| Feature/review/repair sequence, controlled file change, integration and comparisons | [lab/workflow.py](lab/workflow.py): `run`, `after_read_fixture`, `integration_prompts`, `compare`, `interaction` |
| Commands and preset settings | [lab/__main__.py](lab/__main__.py): `main`, `factors_from` |

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
