# Agent Behavior Lab

A small Python command-line tool for studying agent workflows. It ports the
external host used for **J04**, the non-Work-Leaf reproduction, and exposes its
seven policy mechanisms plus **C08** (compact conflict updates) and **C25**
(bounded generation before host feedback).

Requires Python 3.11+, Git, Codex and an existing ChatGPT subscription login.
No Python dependencies, API keys, Work Leaf runtime, services or dashboard.

## Fixed workflow

For each feature, in order:

1. Implement and test, using one persistent author conversation.
2. Review in a separate conversation.
3. If there are findings, repair in the original author conversation and review
   again in the original reviewer conversation. Continue until review is clean.

After **all** features: a separate agent proposes an integration plan; the host
accepts it; that same agent produces **one final commit per feature**, including
repairs and required documentation. Final checks run against the result.
Here “compact” means this commit-history cleanup, not conversation summarization.

Every run uses a separate Git clone at a resolved commit. The source checkout is
not edited. Checkouts, reviewed history, prompts, raw events, operation receipts,
failures and costs remain in the run directory. There are no automatic retries,
replacement runs, controls, or extra experimental observations.

## Start small

```sh
python3 -m unittest discover -s tests -v
python3 -m lab factors
python3 -m lab doctor --out runs/login-check
```

The doctor checks subscription authentication/configuration without generation.
Initialize the included tiny example as its own benchmark repository:

```sh
git -C examples/tiny-project init
git -C examples/tiny-project add .
git -C examples/tiny-project -c user.name=Research -c user.email=research@example.invalid commit -m 'ADD tiny benchmark starting point'
python3 -m lab plan benchmarks/example.json
python3 -m lab run benchmarks/example.json --out runs/example-all \
  --seconds 600 --max-raw 300000 --max-turns 24
```

`plan` shows the effective factors and author instructions without starting an
agent. `run` always requires a fresh output directory and explicit limits.
Use a recorded, approved experiment plan before spending subscription capacity.
Observe all outcomes; screen cheaply before repetitions. Wall time and turn
limits also apply when token telemetry is missing. An observed-token threshold
can overshoot while a response is in flight; it is not a hard billing cap.

## Switches

`--off C08,C25` disables both; `--on C08` enables one. All are on by default.
“On” selects the J04/compact/bounded behavior, **not a claim it saves tokens**.
These are operational definitions; the original hypotheses sometimes overlapped.

| Switch | On | Off |
| --- | --- | --- |
| C08 | After a rejected edit, send a diff from the last delivered file snapshot | Send that changed file's complete current text |
| C13 | Focus author validation; defer broad checks to integration | Request broader author validation too |
| C14 | Group related implementation/tests where test order permits | Request separate implementation/test edits |
| C15 | No mandatory artificial failing-test execution | Require an actually failing test before implementation |
| C16 | Exact-context structured patches | Standard unified diffs |
| C17 | Host applies and commits edits, executes checks, reports real results | Agent edits, checks and commits using native tools |
| C20 | Include next-action guidance after host command results | Return factual command results without that guidance |
| C25 | Interrupt at a complete host request, with usage grace | Wait for natural turn completion before executing the request |
| C38 | Explicit guidance to hand over when required work is ready | Omit the extra finishing reminders |

`--preset j04` starts with C08/C25 off and the seven J04 mechanisms on.
`--preset native` also turns C17 off. Native mode still has independent review,
repairs and final integration; it is **not** the old Direct benchmark.

Important constraints:

- C17 off requires C08/C25 off: native edits do not pass through this host's
  conflict or interruption path. Unsupported combinations fail before generation.
  C17 is a declared edit-ownership/tool-access package, not an isolated feedback
  wording switch. C16 remains a native editing-format instruction; C20 retains
  its launch guidance but has no host-result insertion in native mode.
- C15 off requires tests to run before implementation, even with C14 on. C14 then
  groups compatible later work. These are intentionally interacting policies.
- Instruction switches express a policy, not forced compliance. Actual behavior
  must be checked in transcripts. Only executable host events are counted as
  mechanism activations; a configured switch is not a measured effect.
- C08 needs a genuinely outdated edit and previously delivered full file text.
  `@standalone read path` records that text. Native inspection is allowed, but is
  not falsely treated as a recorded full snapshot. First reads, unchanged files
  and oversized/unavailable diffs have the **same fallback in both conditions**.
  Initial automatic full text is limited to 8 KiB and automatic diffs to 48 KiB,
  matching Work Leaf. Larger automatic updates report omission; an explicit read
  can fetch the needed full text. An author's accepted edit invalidates its old
  read snapshot, just as in Work Leaf. A run with no applicable conflict does not
  test C08. Sequential features generally offer fewer conflict opportunities than
  concurrent Work Leaf features; do not interpret that absence as zero effect.
- C25 accepts only a complete, owned assistant message, never a streamed fragment
  or a tool's quoted output. It allows up to one second for usage, interrupting
  sooner after fresh usage or resumed output. It drains the terminal event and
  late usage; already generated tokens remain charged. Later messages are saved,
  not executed as additional host operations. Off means natural completion,
  not the old study's specific 120-second extended-grace intervention.

The completion marker remains part of the transport when C38 is off. No switch
removes required tests, permits unresolved findings, or skips final validation.

## Other benchmarks

Copy an example JSON. Set a local Git `repo`, a `revision`, any nonempty list of
`features` (`id`, `request`) and final shell `checks`. Optional `instructions`
apply across features; `defer_documentation` defaults to true, like J04.
Relative repository paths resolve against the JSON file, not the current shell.

The runner knows no feature names, language, test suite or hard-coded count of
three. Only the JSON knows the benchmark. Checks can invoke an external scorer;
its nonzero exit fails the workflow and its complete output is retained. Benchmark
definitions and commands are trusted local input, not an untrusted-job sandbox.
The host checks source custody but shell commands are not an OS security boundary.

For a changed-file workload, optional `after_read: {"path": "...", "command":
"..."}` executes **once**, immediately after that file's first mediated read.
It has a 30-second ceiling and may modify only the declared tracked text file,
not Git state or other source. The host commits the fixture's actual update and
retains the agent's earlier snapshot. Normal custody checks then continue.
This models an intervening update without adding parallel feature agents.
The fixture commit belongs in final integration, not in a separate final commit.
`benchmarks/conflict-example.json` shows this independently of Work Leaf.
The exact same fixture must be used in both compared conditions; it is part of
the benchmark, **not an extra behavior secretly enabled by C08**. No hook runs
unless the benchmark declares it. Check `fixture_executed`, `factor_activations`
and host events: a model can avoid a stale proposal, so a fixture opportunity is
not a guaranteed conflict or evidence of saving.

`benchmarks/work-leaf.json` preserves the original three requests and starting
commit as an optional input. It includes Rust gates, but **does not include the
old external feature scorer**. Add that scorer as a check before claiming the
old benchmark's complete acceptance criteria. Normal Work Leaf is untouched.

## Results and interactions

```sh
python3 -m lab report runs/example-all/result.json
python3 -m lab compare runs/reference/result.json runs/modified/result.json
python3 -m lab interaction runs/neither/result.json runs/a-only/result.json \
  runs/b-only/result.json runs/both/result.json
```

`compare` reports `(reference - modified) / reference`, names the denominator,
and lists the changed factors. `interaction` requires four matching settings:
neither factor, A only, B only, both. Extra joint saving is
`A-only + B-only - neither - both`. A/B may each be a declared group of switches.
These commands analyze existing results; they never launch runs.

They reject failed workflows, flagged usage gaps and differing non-factor
settings (benchmark, commit, runner code, model, effort, effective configuration,
limits). They do not supply statistical certainty from a single observation or
assign additive shares of an old saving. Repetitions and their analysis remain
an explicit research decision.

Raw tokens are input plus output. Cached input is already included in input;
reasoning is already included in output. Each increasing thread counter is
counted once; duplicate notifications are not additional charges. Missing tails
and counter resets are flagged, never filled with zeros. `measurement_complete`
means no detected turn-tail/counter gap; it does **not** certify that the provider
priced every internal response. Raw transport is retained for stricter audits.

## Relationship to J04

This is a **port**, not a byte-identical replay of the 18.545M-token old run.
It retains the exact-context patch matcher, host command custody/output rules,
sequential feature/review/repair loop and final plan/accept workflow. The fixed
new transport is Codex's local app-server for both C25 settings; this allows real
turn interruption through the same subscription. Prompts are split into explicit
policy factors and a mediated-read operation provides C08's snapshot history.
Those differences apply across new comparisons and are documented in
[PROVENANCE.json](PROVENANCE.json). New results must not be silently pooled with
old measurements.

The interface follows the [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).
[VERIFICATION.md](VERIFICATION.md) records automated and real-agent coverage.
[PLAN.md](PLAN.md) records this extraction's state; it is separate from the old
Work Leaf investigation's counters.
