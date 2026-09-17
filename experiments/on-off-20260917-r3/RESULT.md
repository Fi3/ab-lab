# Third comparison: untracked nested generation

The required small real-agent Git rewrite **passed**. Three all-on workflows
started concurrently at 20:41:26 UTC on 2026-09-17. The full comparison is
**not complete**: one workflow failed its no-commit gate, and the other two were
stopped at 21:11:31 after discovery of a shared accounting/isolation defect.
The three all-off workflows remain unstarted. No saving percentage follows.

| Run | Runner raw tokens | Recovered nested raw | Observed sum | Outcome |
| --- | ---: | ---: | ---: | --- |
| on-01 | 9,950,855 | 0 | 9,950,855 | Stopped during second-feature review; one incomplete cancellation tail |
| on-02 | 5,413,894 | 167,250 | 5,581,144 | Second-feature completion produced no commit |
| on-03 | 5,643,268 | 0 | 5,643,268 | Stopped during second-feature implementation; one incomplete cancellation tail |
| off-01, off-02, off-03 | — | — | — | Not started |

Observed sum: **21,175,267 raw tokens**, including recovered nested usage.
The unknown cancellation tails are not treated as zero. These are failed/partial
attempts, not complete benchmark costs. All processes are stopped.

## Git qualification remains valid

[Qualification](QUALIFICATION.md) verifies an actual native-agent rewrite from
three disposable input commits to two feature commits, ten passing tests, clean
source, unchanged original checkout and two completely measured turns. Transport
lasts 119.86 seconds and usage is 191,320 raw, within the 240-second/200k limits.
That repaired Git path works; it is not this batch's failure. This separate
functional check is not an effect-size observation.

## Exact accounting and model-isolation failure

On-02 requests a separate `codex exec` launch and `codex exec resume` to check
agent-command behavior. The frozen starting source's AGENTS.md requires real
agent verification, so this is a relevant path. The call chain is
`lab/workflow.py::run` → `Host.consume` → `Host.command` → `execute_child`.

The separate process's conversation never enters the main provider's
`Usage.observe` charged-thread table. Thus `measurement_complete=true` establishes
parent-provider coverage only, not whole-workflow coverage. The live observer
and earlier transport audit share that blind spot.

The child ID is `01a0b132-e18a-7141-a50f-ca926accbd7c`. Its seven saved response
charges total **167,250 raw**, absent from the runner's 5,413,894. Both child
turn contexts specify **GPT-6 Astra / max**, not the admitted **GPT-5.5 / xhigh**.
This is an actual non-target model difference, not an inference from a command.

Evidence: `runs/on-off-20260917-r3/on-02/slash-routing-host/operation-0002/`
and [NESTED-USAGE-AUDIT.json](NESTED-USAGE-AUDIT.json). The reproducible
[read-only query](audit_nested_calls.py) scans native histories dated 2026-09-17
for the exact three owned checkout directories: ten parent conversations and
one child. It finds no other conversation under those exact directories; this
is not a claim about unrelated/unlinked paths. Native command-event inspection
finds no additional direct Codex launch.

The first CLI total is 17,591 raw. The second is 167,250 **including the first**.
Adding them gives the incorrect 184,841 announced during initial inspection.
The distinct response charges are 17,591, 18,183, 19,420, 20,024, 23,760, 31,814
and 36,458. They sum to 167,250 and match the final cumulative counter exactly.
This corrects that initial double count; no saved run or reported counter changes.

## Authentication evidence and protection gap

All child usage records report plan type `pro`. A non-generating login check
reports ChatGPT. There is no evidence of API billing here. The main provider
additionally forces ChatGPT authentication and strips API credentials. However,
`Host.command` inherits the supervisor environment without that sanitization.
A presence-only check finds an inherited OPENAI_API_KEY; its value is never
printed, copied or used by the supervisor. The recursion marker blocks another
invocation of this Python runner, not a raw Codex command. Child execution lacks
the main provider's model, authentication and accounting controls.

The OpenAI Docs skill guided this check. The
[official authentication documentation](https://learn.chatgpt.com/docs/auth)
describes ChatGPT/API-key sign-in and login-status inspection; the
[environment-variable documentation](https://learn.chatgpt.com/docs/config-file/environment-variables)
describes noninteractive overrides. Documentation alone cannot prove a past
charge; the child's actual Pro-plan records are the relevant saved evidence.
No API request or model response is generated for this diagnosis.

## Why on-02 produced no commit

Its second-feature author runs four existing slash-command tests, which pass,
then the launch/resume check, then sends `@standalone done`. The host event log
contains no edit proposal or accepted commit. `workflow.run` raises
`initial implementation produced no commit` before independent review starts.

The starting commit already contains slash routing and focused tests:
`tests/terminal_app.rs::terminal_app_slash_command_from_chat_view_sends_agent_command`,
`terminal_app_sends_spawned_codex_slash_command_as_raw_command`, the UI-harness
slash-command test, and the Codex raw-resume test. The saved source diff for
`src/codex.rs`, `src/workspace.rs` and `tests/terminal_app.rs` against the starting
commit is empty. Existing code and passing tests support an already-present-code
path; they do not prove the complete request correct, because independent review
never ran. The runner requires a new commit even on that completion path.

## Preserved evidence and next step

All measured source/input hashes and three parent configuration fingerprints
match admission. The [parent audit](PARENT-TRANSPORT-AUDIT.json) reconciles all
ten parent histories and counters. There are no earlier missing returned counts;
only the two safety cancellations are incomplete. Its no-unowned-charged-thread
assertion cannot detect an entirely unobserved child. Source stays frozen.
No partial-source feature score or successful-subset percentage replaces 3-vs-3.

Before more full runs, a small qualification must cover child launch **and
resume**, actual child model/subscription settings, complete child accounting
without duplicate charges, and an already-satisfied feature's completion path.
Silently forbidding required real verification or forcing meaningless edits
would change the measured work. The current source remains unmodified and
unqualified for these paths. No further generated diagnostic, resumed observation
or replacement is admitted. All reviewed work and outcomes remain retained;
another blind six-run restart is not the recommended next action.

Saved-data replay reproduces the audit exactly except its timestamp. All 49
existing unit tests pass in 20.373 seconds; compilation and whitespace checks
pass. Those checks do not cover the discovered boundaries or qualify another
full run. The 21:12 local-only recovery ends at 21:24, before its 15-minute limit.
