# Agent Behavior Lab

A tool to compare harness/model/settings across different benchmarks.

The tool is call a runner and than an evaluator. The runner will run the bench in a fixed env and
then the evaluator will execute the bench specific tests on the results and also run slope code
rate.

The tool execute the bench using a patch/review loop. To better control it we force the benched
harness to not spawn reviews subagents but only the runner can do it.

This is an example of a run:

```sh
python3 -m lab run ./benchmarks/swe-milestone-scikit-learn-light.json \
                --out runs/bench33 \
                --harness codex \
                --model gpt-6-luna \
                --effort xhigh \
                --preset all --off C08,C16,C17  \
                --review-priorities P0,P1 \
                --seconds 14400 \
                --max-raw 50000000 \
                --max-turns 100 \
                --max-review-loops 3 \
                --parallel 4
```
For example the above command will run the scikitlive bench usin codex with gpt-6-luna xhigh. It
will allow a max of 3 review loops and only P0 and P1 issue will be fixed. It add a safety net, so
after either 4 hours of running, 50M tot token used, or 100 turns the runner will stop. The run
result will be saved in `./runs/bench33`. The last option tell the runner that we want to run 4
instance of the same bench.
The above command also instruct the runner to run the bench with specific condition in
particular all conditions but C08,C16,C17.

Reviewers receive no issue description or author evidence by default. Add
`--review-issue-description` to include both. This also applies to `plan` and
parallel runs.

In order to have a baseline `--preset native` can be used. This will remove all runner interventions
and run the harness in native mode without limitation (for example can spwan all the sub-agent
that want). Of course when native mode is one there is not a patch/review loop enforced or and
condition enforced.

For Pi, add `--harness pi --pi-vanilla` to run without installed or project
customizations. This works with both `--preset all` and `--preset native`:
`all` still applies the runner's conditions and review loop; `native` retains
its usual baseline workflow. Vanilla disables discovered extensions, skills,
prompt templates, themes, and context files (including repository `AGENTS.md`
and `CLAUDE.md`). It ignores custom system prompts and project settings, and
uses clean private global settings with authentication and the runner's explicit
model, effort, and compaction configuration. The required benchmark extension
still supplies sandboxing, accounting, and any configured host/review tools.
The mode is recorded in plans and results. `--pi-vanilla` is also available for
`plan` and `doctor`, and requires `--harness pi`.

The output is very big so in order to read it `summarize.py` can be used. For example:
```sh
./summarize.py runs/bench11/result.json
```
An example of an output of the summarizer is [here](summarize_example.md)

## Why

I want to use this bench to drive build of an agent that use the patch/review loops and minimise the
uncached-token/out-quality metrics. (I'm thinking at a nvim plugin for ui and a pi
plugin for the engine but still have to look into it)

Another nice thing about it is to see which task should be executed with what, we a can
generalize over specific task's categories.

## Preserving evaluation and existing results

**Keep evaluation tests and scoring unchanged.** Benchmark comparisons must use
the same pinned grading tests, assertions, fixtures, parameterization, and test
selection. Do not change already committed lab verification tests. Changing these
inputs invalidates results measured against the changed evaluation definition.

**Do not introduce any other change that invalidates existing results.** Preserve
historical result files and their recorded inputs. Changes to benchmark requests,
task order, baseline revisions, grading rules, quality metrics, token accounting,
execution policy, or environment identities must not silently reinterpret old
results or present different experiments as comparable. Keep explicitly requested
new benchmark variants and their results separate from existing definitions.

If the request or its effect on existing results is unclear, ask the user before
changing benchmark definitions, runner behavior, evaluation, or comparison
conditions. If a change that would invalidate existing results is strictly
necessary, prepare a concrete, reviewable proposal, identify the affected tests
and historical results, and
explain why the change is unavoidable. **Explicit human permission MUST be asked
for and received before applying that change.** Passing tests, convenience, or an
agent's judgment do not replace permission. Preserve the original evidence after
approval and record the resulting boundary between comparable result versions.

## Conditions

Conditions are switches that let you compare agent behavior on the same
benchmark. Some conditions change how the runner uses tools and applies edits.
Other conditions add instructions to the author agent's prompt. An instruction
specifies the requested behavior. It does not guarantee that the agent follows
that instruction. Benchmark results show whether a condition improves quality
or decreases token use.

This section uses these terms:

- **Author agent:** The agent that writes and corrects the code. It also runs
  checks on its changes.
- **Review agent:** The agent that examines the submitted code and reports
  defects. It must not change the submitted code.
- **Runner:** The software that controls the benchmark run. It starts the
  author agent and any configured review agent. When a review requires
  corrections, the runner sends the reported defects to the author agent.
- **Host tools:** The runner's tools for file reads, source edits, and commands.
- **Native tools:** The tools that the agent's harness supplies. The harness is
  the software that runs the agent.
- **Focused check:** A check that directly tests the changed code.
- **Diff:** A text representation of the differences between two file versions.

Use `--preset all` to enable all eight conditions. Use `--preset native` to
disable all eight conditions. This preset also disables feature reviews and
loop detection by default.

Use `--off` and `--on` with condition IDs separated by commas to change
individual conditions. For example, `--preset all --off C13,C14` enables all
conditions except C13 and C14. C08 requires C17. To use native editing tools,
disable both conditions with `--off C08,C17`.

### C08

C08 controls the file information that the host returns after it rejects an
edit because the context does not match. Context is the source text that an
edit uses to identify where a change belongs. C08 requires C17 because this
condition uses the host editing tools.

#### Enabled

If a file changed after the host supplied its complete contents, the rejection
response includes a diff. The diff compares the version supplied to the author
agent with the current version.

For example, one function changes after the author agent reads a large file.
The response shows the changed function and the surrounding context. The
author agent can use this information to correct the proposed edit. It does
not need to receive the complete file again.

C08 changes the information in the response. The host still applies the same
checks before it accepts an edit.

#### Disabled

For the same changed file, the response includes the complete current contents
instead of a diff. The author agent receives this text before it tries the
edit again.

The following rules apply with either setting:

- If the host has not supplied a previous file version, it uses the same
  fallback response.
- If the file has not changed, the response reports that fact.
- If the diff is unavailable or too large, the author agent must use
  `host_read` to read the current file.

### C13

C13 adds instructions about the checks that the author agent runs when it
writes or corrects code.

#### Enabled

The runner instructs the author agent to start with focused checks. If a check
fails, the author agent must correct the cause and run the applicable checks
again. The instructions also permit checks across features when necessary to
complete the work correctly.

For example, a parser change can start with that parser's unit tests. A change
to a shared interface can require checks across several components.

With host tools enabled, each accepted edit includes an additional
instruction. It tells the author agent to run at most one applicable focused
check for that accepted work. Further checks and edits are permitted for
actual failures or incomplete requirements.

#### Disabled

The runner adds no instruction to prefer focused checks. It also adds no
instruction to limit checks after an accepted edit. The author agent selects
its checks from the task, repository instructions, and harness behavior.

The author agent can still run tests. Review agents can still request
corrections. The configured final checks and independent benchmark evaluation
still apply.

### C14

C14 adds instructions about related source changes in the same edit.

#### Enabled

The runner instructs the author agent to submit related code and focused tests
together when the required test sequence permits this. One edit can include
several files and several changed regions.

For example, one edit can add a function and its unit tests. The author agent
does not have to put the complete feature in one edit. It must still follow
the required test sequence.

#### Disabled

The runner adds no instruction to group changes. The author agent can submit
related code and tests together or in separate edits. The task and the agent's
usual procedure determine this choice.

The available editing tools stay the same. The author agent must still
complete the assigned work.

### C15

C15 controls whether the runner replaces a requirement to run a test and show
a failure before implementation starts.

#### Enabled

The runner instructs the author agent to design the required tests first. The
author agent does not have to run those tests before implementation only to
show a failure.

For example, the author agent can define the expected behavior and test cases
first. It can then change the code and run the tests.

This instruction takes precedence over rules in `AGENTS.md` that require a
failing test before implementation. Required test coverage still applies. The author agent must still examine
actual failures and check the completed code.

#### Disabled

The runner adds no instruction to replace the required test sequence.
Repository and harness instructions determine the sequence of tests and
implementation.

If those instructions require a failing test before a correction, that
requirement still applies. Disabling C15 does not add this requirement when
it does not exist.

### C16

C16 controls the requested format for source edits.

#### Enabled

With C17 enabled, the runner instructs the author agent to use the structured
patch format. This format includes these elements:

- `*** Begin Patch` at the start.
- Explicit `*** Add File:`, `*** Update File:`, or `*** Delete File:` entries
  with file paths.
- `@@` change blocks with context that matches the source exactly.
- `*** End Patch` at the end.

The host checks the format and the context before it applies the edit. It does
not estimate where the change belongs.

With C17 disabled, the runner instructs the author agent to prefer the native
structured patch tool that its harness supplies.

#### Disabled

The runner adds no instruction about the edit format. With C17 enabled, the
host accepts its structured patch format or a supported standard unified diff.
The host checks both formats before it applies changes. It still requires
exact context matches.

With C17 disabled, the author agent uses the native editing tools and follows
their rules.

### C17

C17 determines which software applies source edits, runs author agent
commands, and records source changes in Git.

#### Enabled

The author agent uses `host_read`, `host_edit`, and `host_run`. The host applies
accepted patches and commits the resulting source changes.

The host also records and commits source changes that commands produce. This
includes changes from a failed command. The host reports the actual command
output and exit status.

The host controls the Git index and history. Native tools remain available
for inspection, but they must not change the source. The author agent cannot
start other agents in this mode. The runner starts any configured independent
review agent.

#### Disabled

The author agent uses its harness's native editing and command tools. The
native harness configuration determines whether the author agent can start
other agents.

The runner saves the source in a commit at each stage boundary. This creates
a checkpoint even if the author agent did not create a commit.

File system permissions and limits for the complete run still apply. The
review configuration separately determines whether the runner starts review
agents. Disabling C17 alone does not disable those reviews.

C08 must also be disabled because it requires host tools.

### C20

C20 adds instructions about the next action after an operation finishes.

#### Enabled

The runner instructs the author agent to select its next action from the
actual operation results. The author agent must not repeat accepted work. It
must not use missing output as evidence of success.

With host tools enabled, command responses also include this instruction.

For example, a failed test requires the author agent to examine the failure.
A short response to a successful edit does not require the author agent to
submit that edit again. The author agent selects the next action.

#### Disabled

The runner omits this instruction from the prompt and host command responses.
Those responses still report the actual output, exit status, and recorded
source changes.

The author agent uses its existing instructions to interpret these results.
The criteria for success stay the same. Command responses still report
failures.

### C38

C38 adds instructions about when the author agent ends its turn.

#### Enabled

The runner instructs the author agent to end its turn when the assigned work
and applicable checks are complete. The runner starts any configured
independent review.

The instruction tells the author agent to avoid extra work based only on
assumptions and additional exchanges only to report progress. With host tools
enabled, accepted edits and command results also include completion reminders.

The author agent must still correct actual failures and complete unfinished
requirements before it ends its turn.

#### Disabled

The runner adds no completion instruction or related tool reminders. The
author agent uses the task, harness instructions, and repository instructions
to decide when to end its turn.

The same run limits, review configuration, final checks, and benchmark
evaluation still apply. The criteria for the submitted work stay the same.

## Patch review loop

The patch review loop separates code changes from code review. The author
agent writes and corrects the code. The review agent examines the submitted
code and reports defects. The runner controls the sequence.

For each feature, the runner uses this procedure:

1. Save the starting commit and start a new author conversation.
2. Send the feature request and enabled condition instructions to the author
   agent. The author agent changes the code and runs the applicable checks.
3. Save the resulting source in Git. With C17 enabled, the host commits source
   changes. With C17 disabled, the runner also saves uncommitted source at
   stage boundaries.
4. Start an independent review conversation if reviews are enabled. The review
   agent examines changes from the feature's starting commit to the current
   commit. It can run checks in a temporary copy. It must not change the
   submitted code.
5. Receive the review findings through `submit_review`. The runner determines
   approval from the findings and configured priorities.
6. If the review reports defects that require corrections, send those defects
   to the same author conversation. The author agent corrects the code.
7. Repeat the review after corrections if another review is permitted. Use
   the same review conversation for subsequent reviews of that feature.

A complete review with no blocking findings ends the loop. A blocking finding
is a defect with a priority selected by `--review-priorities`. The default
priorities are P0, P1, and P2. P3 findings are advisory by default. A review
must check the requested behavior even when the author agent made no changes.

`--max-review-loops N` permits at most N reviews per feature. The default is
3 with `--preset all` and 0 with `--preset native`. A value of 0 disables
feature reviews.

After each review with blocking findings, the author agent corrects the code
if the applicable limits permit further work. After corrections from the last
permitted review, the runner continues to the next feature. It records those
corrections without review approval. For example, a limit of 3 permits three
reviews and up to three correction attempts. The third correction attempt
receives no further review.

An incomplete review, failed correction attempt, or applicable stopping rule
can stop the workflow. Reaching the review limit alone permits the workflow
to continue. The runner retains source and recorded results when work stops.

After the feature sequence, the runner measures source quality and runs the
benchmark's final checks. Configured independent grading runs after the model
sessions close. Grading results do not enter the author and review loop.
Review approval and successful public checks do not replace independent
grading.

## Bench definition

A benchmark is a JSON file. It identifies the starting source, requested
features, and final checks. The source must be an existing local Git
repository. The runner resolves the requested revision to a commit before
model execution.

Personal benchmark definitions can remain local; they do not need to be
committed to this repository. Pass their JSON file path to `lab plan` or
`lab run`.

### Define a local benchmark

Create a JSON file with these fields:

| Field | Required content |
| --- | --- |
| `name` | A nonempty benchmark name. |
| `repo` | The path to the local source repository. Relative paths start from the JSON file's directory. |
| `revision` | The starting Git revision. Use a commit ID to keep the baseline fixed. |
| `features` | A nonempty list of feature requests. The runner executes them in list order. |
| `features[].id` | A unique ID. Start with a letter or digit. Use only letters, digits, underscores, and hyphens. |
| `features[].request` | A nonempty description of the required behavior and tests. |
| `checks` | A nonempty list of shell commands for final checks. |

For example, save this definition as `benchmarks/my-example.json`:

```json
{
  "name": "my-example",
  "repo": "../examples/tiny-project",
  "revision": "HEAD",
  "features": [
    {
      "id": "negate",
      "request": "Add negate(value) to numbers_demo.py. Return the negative of value. Add tests for positive, negative, and zero values."
    }
  ],
  "checks": ["python3 -m unittest discover -s tests -v"]
}
```

`lab run` initializes the bundled example source as a separate Git repository
and creates its first commit when needed. Custom source repositories must
already exist. To inspect the definition and selected settings, run:

```sh
python3 -m lab plan benchmarks/my-example.json
```

To execute it, use a new output directory and specify the required limits:

```sh
python3 -m lab run benchmarks/my-example.json \
  --harness codex --out runs/my-example \
  --seconds 1800 --max-raw 3000000 --max-turns 100
```

These limits are example values. They do not guarantee completion. Code
changes from each feature remain available to subsequent features.

### Optional benchmark fields

`after_read` defines a source change that the runner applies after a specified
host read. It contains exactly `path` and `command`. The path must identify a
source file relative to the repository. This option requires C17 and supports
C08 conflict experiments.

A benchmark can select one independent evaluator. Use `slopcodebench` for
SlopCodeBench or `swe_milestone` for SWE-Milestone. SlopCodeBench supplies its
feature requests from the pinned dataset. Do not add a separate `features`
list to a SlopCodeBench definition. SWE-Milestone definitions include their
imported feature requests.

For a local SWE-Milestone variant that adds repository tooling, use
`swe_milestone.repository_additions` to declare the added files or directories:

```json
"swe_milestone": {
  "project": "scikit-learn",
  "seconds": 3600,
  "repository_additions": ["AGENTS.md", ".project-tools"]
}
```

Set the benchmark's `revision` to a local commit directly after the project's
pinned baseline. That commit must contain only new regular files under the
declared paths; existing files must be unchanged. This validates the starting
repository before authoring. The original task requests, grading baseline,
and pinned evaluation tests remain unchanged. Without this optional field,
SWE-Milestone continues to require its original starting revision.

The runner rejects unknown fields. See the
[evaluator contract](docs/BENCHMARK_EVALUATION.md) for evaluator configuration
and result handling.

### Available benchmarks

The following runnable definitions are in `benchmarks/`:

| Definition | Requested work |
| --- | --- |
| [example.json](benchmarks/example.json) | Add clamp and parity functions to a small Python project. |
| [conflict-example.json](benchmarks/conflict-example.json) | Add an increment function after a declared source change. Requires C17. |
| [work-leaf.json](benchmarks/work-leaf.json) | Add visual selection, command routing, and review completion behavior. Requires the specified local Work Leaf repository. |
| [scb-code-search.json](benchmarks/scb-code-search.json) | Complete the SlopCodeBench code search problem. |
| [scb-code-search-smoke.json](benchmarks/scb-code-search-smoke.json) | Complete only the first code search checkpoint. |
| [scb-log-query.json](benchmarks/scb-log-query.json) | Complete the SlopCodeBench log query problem. |
| [scb-config-service.json](benchmarks/scb-config-service.json) | Complete the SlopCodeBench configuration service problem. |
| [swe-milestone-ripgrep.json](benchmarks/swe-milestone-ripgrep.json) | Complete the imported Ripgrep milestones. |
| [swe-milestone-dubbo.json](benchmarks/swe-milestone-dubbo.json) | Complete the imported Dubbo milestones. |
| [swe-milestone-element-web.json](benchmarks/swe-milestone-element-web.json) | Complete the imported Element Web milestones. |
| [swe-milestone-navidrome.json](benchmarks/swe-milestone-navidrome.json) | Complete the imported Navidrome milestones. |
| [swe-milestone-nushell.json](benchmarks/swe-milestone-nushell.json) | Complete the imported Nushell milestones. |
| [swe-milestone-scikit-learn.json](benchmarks/swe-milestone-scikit-learn.json) | Complete all imported scikit-learn milestones. |
| [swe-milestone-scikit-learn-light.json](benchmarks/swe-milestone-scikit-learn-light.json) | Complete the first three scikit-learn milestones: M06, M11, and M12.1. |
| [swe-milestone-go-zero.json](benchmarks/swe-milestone-go-zero.json) | Complete the imported go-zero milestones. |

`swe-milestone-projects.json` is a preparation catalog, not a runnable benchmark.

`lab run` prepares SlopCodeBench automatically. To prepare it separately, run:

```sh
python3 -m lab.slopcodebench setup
```

`lab run` also prepares the selected SWE-Milestone project and its evaluator
automatically. See [SWE-Milestone setup](docs/SWE_MILESTONE.md) for separate
preparation commands. Work Leaf requires an existing local checkout at the
path and revision declared in its definition; the runner cannot download a
custom repository whose definition has no remote URL.

## Supported harness
For now I support only codex (is the one that I use mostly) and PI is the one that I was to use to
build my custom agent.

## Execution env
The execution env is pinned and defined in executors for reproducible runs.

The executor is a Docker container for Linux x86-64. The public build inputs
are in `executors/`. The default profile is `executors/default.json`.

| File | Purpose |
| --- | --- |
| [default.json](executors/default.json) | Defines the platform, runtime environment variables, tool paths, and quality checker path. |
| [Dockerfile](executors/Dockerfile) | Defines the base image, operating system packages, Rust toolchain, and installation steps. |
| [package.json](executors/package.json) | Selects Codex and Pi versions. |
| [package-lock.json](executors/package-lock.json) | Records exact Node package versions and integrity values. |
| [requirements.lock](executors/requirements.lock) | Records exact Python dependencies and hashes for the quality checker. |

The recipe selects an Arch Linux base image by SHA-256 digest. Operating
system packages come from the archive dated 2026-09-18. The Rust archive also
has a fixed version and SHA-256 hash. These inputs define the software
environment independently of the host's installed tools.

The container includes Python, Git, GCC, build tools, CMake, Java 17, Node,
npm, Rust, Cargo, ripgrep, fish, uv, and bubblewrap. It includes Codex 0.159.3
and Pi 1.0.0. The `scb-check` quality checker uses a separate Python virtual
environment. The default Python does not include NumPy, SciPy, Cython, or
pytest. Check the selected benchmark's dependency requirements before use.

The author agent, review agents, child agents, builds, and public checks run
in the same executor. Independent benchmark grading uses its separate
configured environment. The runner imports only the requested Git baseline
and its reachable history into the coding environment.

The executor receives authentication through temporary runtime state. The
build does not contain credentials. Personal host files and shell profiles
are not build inputs. Pi runs use the `openai` provider with a ChatGPT OAuth
login from `~/.pi/agent/auth.json` (or `$PI_CODING_AGENT_DIR/auth.json`).
Authenticate with `/login openai` in Pi 1.0.0; API keys and legacy
`openai-codex` credentials are not accepted for Pi benchmark generation.

Use Linux x86-64 with Docker and Python 3.12 or newer. To build the default
executor explicitly, run:

```sh
python3 -m lab.executor build
```

The `run` and `doctor` commands build the executor automatically if its image
is absent. Docker reuses its local build cache. A change to a recipe input
creates a new environment identity. A failed build stops execution.

Use `--executor PATH` to select another public build profile. Results record
the environment identity for comparison. Hardware, the host kernel, network,
and model service remain external inputs. Fixed software versions do not
guarantee identical model output or execution times.

See [executor details](docs/EXECUTOR.md) for build and runtime behavior.

## Args and defaults

Use `python3 -m lab COMMAND`. The tables below cover all arguments for this
entry point. Required arguments have no default. Every command accepts `-h`
or `--help` to show help and exit.

### Commands

| Command | Purpose |
| --- | --- |
| `factors` | Show each condition's enabled and disabled meanings. No additional arguments. |
| `plan` | Load a benchmark and show effective settings without model execution. |
| `run` | Execute one benchmark or a batch of repetitions. |
| `doctor` | Check authentication and harness configuration without model execution. |
| `report` | Read saved results and print report records. |
| `compare` | Compare token use in two matching, successful runs. |
| `interaction` | Compare four matching runs for two separate condition changes. |

### Arguments shared by `plan` and `run`

| Argument | Purpose | Default |
| --- | --- | --- |
| `benchmark` | Path to the benchmark JSON file. | Required. |
| `--preset all\|native` | Select the condition and workflow defaults. | `all`. |
| `--on IDS` | Enable condition IDs separated by commas. | Empty list. |
| `--off IDS` | Disable condition IDs separated by commas. | Empty list. |
| `--model ID` | Select the model for the agent. | `gpt-5.5`. |
| `--effort LEVEL` | Select `minimal`, `low`, `medium`, `high`, or `xhigh`. | `xhigh`. |
| `--compaction-tokens N` | Set the positive context token threshold for harness compaction. | `131072`. |
| `--review-priorities IDS` | Select finding priorities that require corrections. Use P0 through P3, separated by commas. | `P0,P1,P2`. |
| `--max-review-loops N` | Set the maximum reviews per feature. A value of 0 disables reviews. | 3 for `all`; 0 for `native`. |
| `--loop-policy PATH` | Read JSON overrides for feature limits, review limits, and repetition detection. | No file. Use the preset's policy. |
| `--no-loop-detection` | Disable feature stopping rules. Keep review counts and limits for the complete run. | Not selected. The `native` preset disables detection by default. |
| `--scb-check PATH` | Select the source quality checker executable. | `scb-check`. |
| `--scb-seconds N` | Set the maximum seconds per quality measurement within the workflow deadline. | `300`. |
| `--executor PATH` | Select the public executor build profile. | `executors/default.json`. |

Do not put the same condition in `--on` and `--off`. C08 requires C17.
`--loop-policy` and `--no-loop-detection` cannot be used together. A supplied
policy file replaces the preset's policy defaults with its specified values.
Unspecified fields use the standard policy defaults.

The standard policy enables detection after three repeated failed operation
cycles. Separate feature token limits, review token limits, and review time
limits are absent by default. The review receipt settlement allowance is
600 seconds. A final review after an author stop is enabled when the remaining
review count and applicable limits permit it. See
[policy fields](lab/loops.py) for the accepted JSON keys and value rules.

The compaction threshold applies to both harnesses and every preset. A
harness that cannot apply the requested threshold stops before model
execution. Default executable names resolve inside the selected executor.

### Additional arguments for `plan`

| Argument | Purpose | Default |
| --- | --- | --- |
| `--harness codex\|pi` | Select the harness shown in the plan. | `codex`. |

### Additional arguments for `run`

| Argument | Purpose | Default |
| --- | --- | --- |
| `--out PATH` | Select a new run or batch directory. The directory must not exist. | Required. |
| `--seconds N` | Set the positive time limit in seconds for each workflow. | Required. |
| `--max-raw N` | Set the positive observed token stopping limit for each workflow. | Required. |
| `--max-turns N` | Set the positive agent turn limit for each workflow. | Required. |
| `--harness codex\|pi` | Select the coding harness. | Required. |
| `--codex PATH` | Select the Codex executable, including Codex child sessions used by Pi. | `codex`. |
| `--pi PATH` | Select the Pi executable when Pi is the harness. | `pi`. |
| `--parallel N` | Set the positive maximum number of simultaneous workflows. | `1`. |
| `--repeat N` | Set the positive total number of benchmark repetitions. | The value of `--parallel`. |

Each repetition receives the same workflow limits. For example, `--parallel 2
--repeat 5` runs five repetitions with at most two active workflows. Observed
token use can exceed `--max-raw` while usage reports arrive and cancellation
takes effect. This argument is a stopping limit, not a guaranteed billing
limit.

### Arguments for `doctor`

| Argument | Purpose | Default |
| --- | --- | --- |
| `--repo PATH` | Select the repository for a direct provider check. The executor uses a temporary repository. | Current working directory. |
| `--out PATH` | Select a new directory for check results. | Required. |
| `--harness codex\|pi` | Select the harness to check. | `codex`. |
| `--codex PATH` | Select the executable for a direct Codex check. The executor uses its profile path. | `codex`. |
| `--pi PATH` | Select the executable for a direct Pi check. The executor uses Pi inside the container. | `pi`. |
| `--model ID` | Select the model configuration to check. | `gpt-5.5`. |
| `--native` | Also check native delegation configuration without model execution. | Not selected. |
| `--executor PATH` | Select the public executor build profile. | `executors/default.json`. |

### Arguments for saved results

| Command | Argument | Purpose | Default |
| --- | --- | --- | --- |
| `report` | `results` | One or more saved result files. | Required. |
| `compare` | `reference` | The reference result file. Its token use is the comparison denominator. | Required. |
| `compare` | `changed` | The result file with changed conditions. | Required. |
| `interaction` | `results` | Four result files in this order: neither change, A only, B only, both changes. | Required. |

`compare` and `interaction` require successful runs with complete token
measurements and matching settings outside the compared conditions.
