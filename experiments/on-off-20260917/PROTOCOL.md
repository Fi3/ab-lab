# Six-workflow all-on versus all-off validation

## Authority and question

User instruction: “do 3 in parallel with everyhitng on and 3 in parallel with
everything off. I expect to see soemthing around 50% token usage diff”.

Exactly six complete-workflow attempts are admitted: on-01, on-02 and on-03
concurrently, followed by off-01, off-02 and off-03 concurrently. There are no
extra pilots, ordinary Work Leaf controls, automatic replacements or reruns.
The earlier small implementation checks are not observations in this batch.

The question is whether all nine enabled behaviors in the standalone tool give
roughly the earlier token reduction, compared with all nine disabled behaviors,
on the original coding tasks. A result near 50% is an expectation to test, not a
success criterion imposed on the data. A smaller, absent or reversed difference
is reportable. This is validation of the separate tool, not a restart or silent
extension of Work Leaf's closed-out causal-allocation task ledger.

## Fixed input and changed settings

Input: `benchmarks/work-leaf.json`, SHA256
`beace51ce596f9c5afb6329d0a132e7dddf716b24b47c321b41dcd15c3aa613e`.
Starting commit: `c92a0b7060a36eac6db2d869b85e589a7a9480f9`.
The three original requests concern text selection, slash-command routing and
the review-completion prompt. Each run has its own clone and output directory.

All-on sets C08, C13, C14, C15, C16, C17, C20, C25 and C38 to true.
All-off sets all nine to false explicitly; `--preset native` alone is not all-off.
The definitions are those in the README and frozen runner source. The joint
change includes edit ownership/tools and instructions, not only prompt wording.

Both settings preserve feature order; implementation and tests; independent
review; same-author repair and same-reviewer recheck; final integration planning
and acceptance; one final commit per feature; and the three Rust final checks.
The benchmark checkout contains the starting commit's own instructions, not
today's supervising research instructions. No extra changed-file fixture is
injected. C08 is enabled in the on group but only applies if its actual
outdated-file/rejected-edit condition occurs; event counts and representations
will be reported rather than pretending every switch necessarily operated.

Both use Codex CLI 0.154.0, GPT-5.5/xhigh, the same local app-server transport and
the existing ChatGPT subscription. No API keys/credits, credential copying,
provider changes or temporary authentication homes. Non-generating readback:
`runs/on-off-20260917/preflight/subscription-001/provider.json`; effective config
SHA256 `3398a4ddf498ad5c24906081499dadabf9398e5065cf7ece5d6d3e6a1439c3d8`.
Any effective-configuration difference between admitted runs remains visible.

Run environment: `CARGO_BUILD_JOBS=4` in both groups to limit concurrent Rust
compilation. Rust 1.95.0 / Cargo 1.95.0. Final required commands are
`cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`,
and `cargo test --all-targets --all-features`. The program code is identical
throughout the six observations. Documentation-only progress updates are allowed.

## Limits and monitoring

Each workflow has the same prospective ceilings: 5,400 seconds (90 minutes),
60,000,000 observed raw tokens and 600 agent turns. These are safety ceilings,
not spending targets or promises of completion. An in-flight response or delayed
usage can overshoot the observed-token limit. The fixed elapsed-time/turn
limits are independent fallbacks. Host commands keep their existing 300-second
ceiling within the remaining whole-run time. No limit is extended after launch.

The runner interrupts and drains usage at its limit. The operator retains its
tool-session handle and records each process identity. An operator stop uses
SIGINT against the exact owned runner, allowing its existing cancellation path
to retain late usage and close the provider. Monitor at most 60 seconds apart:
alive/completed state, current stage, reported usage, errors and disk capacity.
Record status in root `ephemeral-note.md`. Do not inspect outputs to tune an
admitted configuration or selectively discard an expensive result.

A common setup, authentication, accounting or source-integrity failure stops
unsafe further generation while its cause is checked locally. Outcomes already
admitted remain retained; they are not silently replaced. A completed negative
or unfavorable observation alone does not stop the approved six-run comparison.
No program-source repair occurs between groups while claiming an unchanged
comparison. New generated observations beyond these six need user direction.

## Acceptance, scoring and analysis

First use the runner's unchanged full-workflow completion and usage checks.
Retain failed and partial observations, missing usage, all stages and limits.
No successful-subset mean is advertised as the requested three-versus-three
result when any of the six required observations is incomplete or unmeasured.

For additional feature scoring, run the earlier frozen three Rust test fixtures
against a separate clone of each actual final checkout. Use the original
`quality_visual_behavior`, `quality_status_behavior` and
`quality_completion_behavior` tests without modifying their assertions. Source:
`work-leaf/bench-results/efficiency-mechanism-isolation-20260906T214448Z/phases/standalone-global-hunk-pilot-01/infrastructure/evidence/bench-results/efficiency-exact-normal-work-leaf-20260829T181318Z/scorer/fixtures`.
These are provider-free post-run checks, not instructions added to measured
agents. Do not fall back to the starting commit for a missing result. Keep any
failure separate from the user's no-quality-loss working assumption. No scoring
failure triggers an unapproved model repair or rerun.

Primary raw usage is input plus output, with cached input and reasoning not
added twice. Include authors, reviews, repairs, integration and incomplete work.
Verify cumulative counters against retained transport; flag missing/reset tails.
If all six runs qualify, report each total, each group's arithmetic mean/range,
absolute mean difference and `100 * (mean_off - mean_on) / mean_off`. With three
runs per group, distinguish observed variation from a general causal guarantee.
The fixed on-first/off-second batch order is not a randomized comparison.

Compare the new totals descriptively with the saved non-Work-Leaf reproduction
(about 18.545M raw) and original direct mean (about 36.116M raw). These old
observations are not extra controls or inputs to the new three-versus-three
percentage. The app-server transport, split instructions and current CLI differ
from the older experiment. All-off also retains this tool's review/integration
rules; it is not automatically identical to the original Direct workflow.
Matching the old percentage would support reproduction, not allocate the saving
to individual switches. A mismatch must be reported, not tuned away.

Stop after the six admitted outcomes, retained-data verification and the result
report. Do not resume the old Work Leaf research TODOs or start extra experiments.

## Prelaunch evidence and frozen program

2026-09-17 17:15 UTC: 35 automated tests pass; Python compilation passes; the
original Git commit resolves; subscription readback succeeds without generation.
Available memory is about 35 GiB and free project-disk space about 573 GiB.
Existing real-agent conflict/interruption and final integration checks are in
`VERIFICATION.md`; the earlier tiny full attempt remains incomplete.

Program SHA256 values at admission:

| File | SHA256 |
| --- | --- |
| `lab/__init__.py` | `cd5de7ee4472c1ef8bada6b3b56d56cee36d93dbfab9195d2dcfc0c7d7be13a1` |
| `lab/__main__.py` | `0271f5c7bfd985a08c353e0b6e12002bbbabb9a0997bfff879492273f288f1df` |
| `lab/config.py` | `8795d66abea96358038c9206e71cad0cfadd5b3247f678ac84d402005b089942` |
| `lab/host.py` | `a81595b8b0742557ea4f4e478fc2dd7813fbfd1d926ebd6da40b20c9d4167f2b` |
| `lab/provider.py` | `9a31e09fde35d70a2cfd770b4275762aa93e21faf3f5ae83d38b94f23ba32fcc` |
| `lab/workflow.py` | `fb95c2db7fd2a527605aea0bc6182eb15a3fc3890084a884a2dc2a364812ae11` |

Raw run data stays under `runs/on-off-20260917/`. The root progress note and this
protocol are committed independently of the Work Leaf product repository.
