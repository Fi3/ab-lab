# Git-qualified all-on versus all-off comparison

Prospective admission: 2026-09-17 20:37 UTC, before model generation.

## User authority and required small check

The user replies, “yes if it pass restart the check!”, to the proposed real-agent
Git-history rewrite check limited to four minutes and 200,000 observed raw tokens.
This admits one such check, followed only on success by the requested three
all-on and three all-off full workflows. The two earlier failed batches remain
unchanged. Their source, costs and outcomes are not combined with these results.
Work Leaf's closed research ledger and product remain outside this work.

The one small check is `tests/real_integration.py`, output
`runs/on-off-20260917-r3/real-integration-001`. It reuses a separate clone of the
already-reviewed tiny two-feature source, adds a verifier-owned empty commit,
then requires a real agent to plan and collapse history to two feature commits.
It does not repeat author or reviewer work. Bounds: 240 seconds, 200,000 observed
raw tokens, two turns, GPT-5.5/xhigh and the existing ChatGPT subscription.
The input source and previous results must remain unchanged. No replacement
check or silent limit extension is admitted.

Advance requires an actual changed HEAD, exactly two final non-merge commits,
clean source, passing Python tests, complete usage, zero missing response counts
and zero counter warnings. A shape-only pass or unchanged history is insufficient.
An in-flight response may overshoot the observed-token tripwire; retain it.
If this gate fails, retain and diagnose the failure locally; do not start the
conditionally admitted full workflows.

## Six full workflows after the gate passes

Fresh run root: `runs/on-off-20260917-r3/`.
Start on-01/on-02/on-03 concurrently, then off-01/off-02/off-03 concurrently
after the first wave ends. All-on enables C08,C13,C14,C15,C16,C17,C20,C25,C38;
all-off explicitly disables all nine. Exactly six attempts, no automatic
replacements, source changes, tuning, extra controls or model substitution.

Input `benchmarks/work-leaf.json` has SHA256
`beace51ce596f9c5afb6329d0a132e7dddf716b24b47c321b41dcd15c3aa613e`;
base commit `c92a0b7060a36eac6db2d869b85e589a7a9480f9`. Each separate clone
performs the same three feature requests, implementation, independent review,
same-author repairs, same-reviewer rechecks, final integration plan/accept and
one final commit per feature. Final checks are `cargo fmt --check`,
`cargo clippy --all-targets --all-features -- -D warnings` and
`cargo test --all-targets --all-features`. No artificial edit conflict is added.
No current supervisor instruction enters measured benchmark prompts.

Both groups use Codex 0.154.0, GPT-5.5/xhigh, the existing ChatGPT login and
`CARGO_BUILD_JOBS=4`. Expected non-generating configuration hash:
`3398a4ddf498ad5c24906081499dadabf9398e5065cf7ece5d6d3e6a1439c3d8`.
No API keys/credits, credential copying, alternate authentication home or provider.
Per workflow: 5,400 seconds, 60,000,000 observed raw tokens, 600 turns. Host
commands retain the 300-second ceiling within the total remaining time.
No post-launch extension. Passive final usage collection lasts up to five seconds.

The Git repair grants native writable turns access to their own clone's `.git`,
not any parent or other checkout. A zero-generation Git index-write preflight
precedes each workflow's first model turn. Read-only roles remain read-only.
The previously verified accounting repair waits for usage covering the host
request before discretionary interruption; unpriced intermediate messages are
not cut solely on output resumption or elapsed grace. That explicit C25 timing
is shared by both groups' identical program; the switch enables it only on.

Start the 15-second non-generating observer with the first wave. Keep owned
process/session identities and current status in root `ephemeral-note.md`.
Review coverage gaps, counters, processes, limits and resource availability at
most 60 seconds apart. A confirmed common setup, authentication, accounting or
source-integrity defect stops unsafe generation. Use SIGINT only for verified
owned runners and retain drained usage/partial results. A high token total,
ordinary repair round or unfavorable result is not a common setup failure.

## Analysis and endpoint

Use the same frozen provider-free feature scorer from the
[original protocol](../on-off-20260917/PROTOCOL.md), in separate final-source
clones after generation ends. No model repair or repeat follows a scoring failure.
Independently audit every transport/native-history total, owned conversation,
complete-response coverage, source pin and non-factor configuration fingerprint.
Report actual compact-conflict and interruption events, not just enabled switches.

Only if all six qualify, report every raw total, each three-run mean/range and
`100 * (mean_off - mean_on) / mean_off`. Raw means input plus output, cached input
included once; do not add reasoning separately. Include review, repair and final
integration. Failed/missing observations are not discarded or valued at zero.
No successful-subset mean is the requested complete three-versus-three result.
Roughly 50% is an expectation, not an acceptance target. On-first/off-second
order is not randomized; three observations per group do not establish each
individual switch's contribution. Earlier 18.545M/36.116M references are only
descriptive, not extra observations or this comparison's denominator.

Stop after six retained outcomes, scoring, accounting audit and the result report.
No old research restart or additional unapproved generation follows.

## Frozen source hashes

Source commit before supervising records: `f88f455` (repair in `5849501`).

| File | SHA256 |
| --- | --- |
| `lab/__init__.py` | `cd5de7ee4472c1ef8bada6b3b56d56cee36d93dbfab9195d2dcfc0c7d7be13a1` |
| `lab/__main__.py` | `0271f5c7bfd985a08c353e0b6e12002bbbabb9a0997bfff879492273f288f1df` |
| `lab/config.py` | `0c7c7f6c4446843187f23e819b616bd5ee7197be58aac7d1ffb06ea6d416be16` |
| `lab/host.py` | `a81595b8b0742557ea4f4e478fc2dd7813fbfd1d926ebd6da40b20c9d4167f2b` |
| `lab/monitor.py` | `2009e3400ee428d82f0290588c96d8f92b7f66b9f5018054149b1072a69d2e8c` |
| `lab/provider.py` | `a83a9708d41bd7cd28253f287ba8f2530ed1cba06cd970566b0a12c6bcca7bf3` |
| `lab/workflow.py` | `65f95a64172cb15e9a19621668af87c25a6876af5973beabf2fd8f1cb34675cd` |
| `tests/real_integration.py` | `bdef5f4460565a3648ed63f522aec98553a6ae3f985071e693d4e9a5fc19b667` |
