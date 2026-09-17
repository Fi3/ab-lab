# Incomplete comparison: missing usage after interruption

## Result

**No all-on versus all-off percentage is available.** Three all-on workflows
started concurrently at 17:18:08 UTC on 2026-09-17. The operator stopped the
group at 18:17:04 UTC after discovering missing usage reports in two workflows.
The three all-off workflows were not started. No attempt is replaced and no
partial result is advertised as a complete benchmark.

| Attempt | Observed raw tokens | Completed responses lacking final-message usage coverage | Final state |
| --- | ---: | ---: | --- |
| on-01 | 14,911,977 | 23 | Operator-stopped during third-feature review |
| on-02 | 13,932,504 | 0 | Operator-stopped during third-feature repair |
| on-03 | 12,962,583 | 44 | Operator-stopped during third-feature implementation |
| off-01, off-02, off-03 | Not run | Not applicable | Withheld after common accounting failure |

The recorded sum is **41,807,064 raw tokens**: input plus output, with cached
input included only once. This is an incomplete observed amount, not the total
tokens actually consumed. Each final operator cancellation also leaves one
unfinished response. Those three final responses are separate from the 67
earlier completed responses with missing coverage. Each on attempt lasted
about 59 minutes. None reached its declared time/token/turn ceiling.

The expected roughly 50% saving is neither confirmed nor disproved by this
failed comparison. This result does not calculate any correction to the older
Work Leaf experiments.

## Exact failure and evidence

The interruption setting is C25: stop generating after receiving a complete
request for the external host, then execute that operation and return its result.
In `lab/provider.py`, `Codex.turn` recognizes the request in a completed agent
message. A later `item/started` or output event marks generation as resumed.
`InterruptGate.reason` returns `output_resumed` immediately, before its
one-second grace expires. Completion of an individual message is not completion
of the whole response's token reporting.

- **66 missing-coverage responses** ended with a host request in an intermediate
  `commentary` message. Cancellation followed that message after **0.45–12.53
  milliseconds**, with reason `output_resumed`. Sixty-four received no fresh
  counter update anywhere in that turn. Two had earlier priced work, but no
  fresh report covering the final host-request message.
- **One further response** ended with a `final_answer` message, was interrupted
  after **1,003 milliseconds** with reason `grace_expired`, and still lacked
  final-message usage coverage. Therefore merely imposing the full one-second
  wait is not yet a demonstrated complete repair.
- The normal one-second post-completion drain did not recover those missing
  values. Later native history also retains missing or unchanged values.

Concrete example: on-01's slash-command author thread
`01a0b07c-204d-7693-8f2d-096a311362cc` has **23 native token events and zero
numeric token events**; every event has `info: null`. Its first host request is
`@standalone run -- rg --files`, in an intermediate message. The immediately
following reasoning-start event triggers cancellation. No transport token
notification prices any of the 23 responses. Their cost is not zero.

All 17 saved native conversation histories were checked. Every available final
native counter matches the transport counter already counted; none supplies an
additional total. The inspected message metadata contains turn identity and
message timing/type information, not a substitute numeric usage value. There
is no exact recovery from the inspected saved records.

The [official app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes turn interruption and thread usage notifications separately. It does
not establish that a completed intermediate message has a fresh usage report.
The numbers and event ordering above come from the actual local records, not
from an assumed documentation guarantee.

## Why the stop happened late

The runner recorded missing-response flags but did not halt the workflow when
they appeared. The live observer checked total-counter resets and terminal
failures; it did not display those per-response flags. Consequently the earlier
progress updates saying no errors were recorded described an insufficient
check. The operator found the coverage issue at about 18:15 UTC and stopped the
group after confirming it in transport records. Monitoring should have exposed
this earlier; continuing until that point was an operator/monitoring failure.

The three runner identities were verified before SIGINT. Their cancellation
paths drained available late usage and wrote terminal results. All owned runner
and provider processes exited. The read-only observer also stopped. The
all-off group did not start against unqualified all-on measurements.

## Checks and retained material

- Independent transport summation exactly matches each recorded total and every
  recorded per-thread counter. No counter decrease or unowned charged thread
  is found. Matching sums do not recover absent prices.
- All three non-switch configuration fingerprints match. All frozen program
  and benchmark hashes still match admission. The login remains the existing
  ChatGPT subscription; no API credit or credential copy is used.
- Both first and second feature review loops completed in all three workflows.
  There is no completed final integration/check sequence. The frozen external
  feature scorer is not run against a partial checkout or a substitute base.
- All 35 existing automated tests pass after the stop. They do not establish
  valid accounting in this failed real-agent scenario. Program behavior has
  not been repaired or silently changed during the comparison.
- [Detailed accounting evidence](ACCOUNTING-DETAILS.json) contains per-response
  flags, interruption timings, conversation identities, native-history hashes
  and counter comparisons. [Initial audit](ACCOUNTING-AUDIT.json) is retained.
- Raw checkouts, prompts, responses, operations, terminal results and the entire
  monitoring history remain under `runs/on-off-20260917/`. Root
  `ephemeral-note.md` retains the activity chronology and current state.

Reproduce the local accounting audit without model generation, using a fresh
output filename:

```sh
python3 experiments/on-off-20260917/audit_accounting.py \
  runs/on-off-20260917/on-01 \
  runs/on-off-20260917/on-02 \
  runs/on-off-20260917/on-03 \
  --output /tmp/agent-lab-accounting-recheck.json
```

## Required next decision

The standalone tool is **not validated for this full token comparison**.
Before another expensive batch: reproduce the observed intermediate-message
and one-second missing-report cases in a small check; repair request/usage
handling and the missing-coverage stop/monitor path; then verify actual complete
usage using a small subscription-backed scenario. A repair must not silently
disable C25, change the model, or alter unrelated factors to manufacture a pass.

The stopped attempts remain failed observations. Resuming the requested
three-versus-three study requires replacement all-on observations and a new
prospective comparison admission with identical code for both groups. The
frozen six-attempt protocol does not authorize automatic replacements or extra
real-agent diagnostics. No such additional generation has been started.
