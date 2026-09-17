# Verification

## Prospective real-agent smoke scope — 2026-09-17

This is implementation verification, not a new saving experiment or a historical
control. No percentage will be inferred from smoke-test costs.

First perform a non-generating subscription/configuration readback. Do not copy
credentials, change the account, substitute an API key, or override CODEX_HOME.

One small two-feature workflow uses `benchmarks/example.json`, all nine mechanisms
enabled, GPT-5.5/xhigh, at most 600 seconds, 300,000 observed raw tokens and 24
turns. Preserve its checkout and every outcome under `runs/real-workflow-001`.
Success means real host edits/checks/feedback, two independent feature reviews,
final plan/accept, two final commits and passing Python tests. An unsuccessful
attempt is retained and not counted as successful verification.

One further bounded protocol verification may use at most 180 seconds, 80,000
observed raw tokens and 6 turns to exercise a stale edit, compact conflict refresh
and actual interruption. It uses a disposable fixture, not an experimental
workflow. Local failure-path tests precede it. A pre-agent setup failure stops
generation until a concrete local repair is verified; no blind retry.

Observed-token limits can overshoot on an in-flight or unreported response. Wall
time and turn ceilings are independent bounds. Interruption retains/drains late
usage and never refunds already generated tokens.

## Local results

- Initial tests failed before implementation: missing `lab` package.
- Workflow tests failed before implementation: missing `lab.workflow`.
- First implemented suites: 17 tests pass, including a two-feature workflow with
  a repair/re-review round, persistent author/reviewer identities and final squash.
- Final suite: 35 tests pass. Coverage includes both compact/full responses under
  the same declared intervening update in the actual workflow loop; malformed
  proposal recovery; the original refresh size limits and snapshot invalidation;
  missing login, token deduplication, missing tails and cancellation draining.

## Real results

- Non-generating readback: `runs/doctor-002/provider.json` confirms ChatGPT login,
  Codex 0.154.0, GPT-5.5/xhigh. No API fallback and no generation occurred.
- The first readback attempt failed before provider launch because a nested output
  directory was not created. A failing regression test reproduced that local bug;
  its verified fix precedes the second attempt.
- `runs/real-workflow-001` is the one bounded complete-workflow verification.
  Its input is a separate Git repository copied from the tiny example, defined by
  `runs/smoke.json`; no Work Leaf benchmark or old measurement is rerun.
- That attempt stopped correctly at its observed-token tripwire during integration
  planning: 309,828 observed raw, 216.76 seconds. Both features were implemented,
  tested and independently approved. Eleven host turns actually ended interrupted
  with usage retained. The failed run is unchanged; it is not a full-workflow pass.

## Remaining-stage verification scope — 2026-09-17

The missing implementation coverage is native final integration, not another
author/reviewer experiment. One separate integration-only verification clones the
exact reviewed checkout from `real-workflow-001`, performs plan/accept in one new
conversation, and checks two final commits, clean source and the complete tests.
Limit: 240 seconds, 200,000 observed raw, two turns, GPT-5.5/xhigh. No feature,
review or scientific observation is repeated. Output: `runs/real-integration-001`.
It cannot convert the earlier capped run into a complete experimental result.

## Verified real-agent outcomes

- `runs/real-protocol-001/result.json`: PASS. One real ChatGPT-backed conversation
  receives file text, encounters a controlled intervening edit, submits an outdated
  patch, receives a compact diff, corrects its patch, runs real tests through the
  host and completes. Five turns actually end interrupted; all have late/final
  usage retained. Total observed raw: 63,381.
- `runs/real-integration-001/result.json`: PASS. The exact reviewed source from the
  capped full run reaches a plan and acceptance in one new real conversation;
  history has two final commits and the Python suite passes. Total observed raw:
  128,488. There is no author/reviewer repeat.
- Total observed raw across implementation verification: 501,697. No API credits
  are used. The readback is non-generating; local tests use no model.

These records verify actual host feedback, real interruption, same-conversation
continuation, review and final integration. The uninterrupted two-feature full
smoke did **not** pass its declared budget. Do not advertise it as a completed
benchmark or derive a saving percentage from these checks. The final fixture
dispatcher and defensive failure-path fixes additionally have fail-first local
coverage; the real conflict record uses the same intervening-edit condition via
the host primitive. Individual policy compliance and every switch combination
are not claimed to have been confirmed by these smoke checks.

Work Leaf's Rust sources, tests, examples, Cargo files and architecture are
unchanged. Its product checks and old research counters are not modified by this
separate Python project. Python compilation and unittest discovery are the
applicable local checks.

## Installed-project verification — 2026-09-17

The independent project is at `/home/user/src/agent-behavior-lab`. From that
directory, all 35 unittest checks, Python compilation and the CLI help check
pass. The retained real-agent records above remain unchanged, including the
incomplete full-workflow attempt. Installation uses no additional model
generation and does not modify Work Leaf.
