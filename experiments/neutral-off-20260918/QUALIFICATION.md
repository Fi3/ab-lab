# Neutral OFF instruction verification

Scope: the user's requested C13/C14/C15/C16 bug fix in the standalone tool.
Disabled switches contribute no opposite instruction. With C16 disabled, native
editing tools remain unrestricted by that switch and the external host accepts
either of its supported patch formats. Other factors, permissions, subscription
authentication, usage handling and review/integration are unchanged.
Historical runs and Work Leaf's closed research ledger are outside this repair.

## Local acceptance gates

The regression test runs before implementation: four disabled policy blocks
unexpectedly contain instructions, a structured host edit is rejected with C16
off, and both compact/full conflict refreshes fail for that format. The selected
three test methods report seven failing assertions. The same checks pass after
repair, together with rejection/retry atomicity, path safety, all sixteen
instruction combinations under both execution modes, repository-rule retention
and the complete two-feature author/review/repair/integration sequence.

The complete suite passes 84 tests. The enabled author policies retain their
pre-repair SHA-256 hashes in both host and native execution. No existing test is
removed or changed. The command-line factor descriptions and no-generation
plan output must agree with the rendered author instructions.

## Prospective real-agent checks

Exactly two tiny author checks are selected, one native and one host-managed,
using `tests/real_neutral_off.py`. Each receives the actual `author_prompt` with
C13/C14/C15/C16 disabled. The existing tiny Python fixture supplies ordinary
repository instructions. The task adds `negate(value)` with positive, negative
and zero tests and preserves `identity`. No edit format or opposite OFF policy
is specified by the verifier. The agent must commit clean source, return the
normal completion marker, pass its tests and pass independent value assertions.

Each check permits at most 180 seconds and 150,000 observed raw tokens. The
native path permits one author turn; the host path permits eight operation/result
turns. Both use GPT-5.5/xhigh through the existing ChatGPT subscription, with
configuration/authentication and Git-write checks before generation. The two
checks may run concurrently in separate owned repositories. Each admission pins
the source hashes, settings and limits before generation.

Stop each check on completion, failure, incomplete accounting or its limit;
retain every outcome. The existing provider drains late usage after interruption.
There is no automatic replacement or extra benchmark admission. These are
implementation checks, not a token-saving comparison. Local tests cover stale
edits, correction and malformed requests without additional paid conversations.

Full benchmarks, independent review and final integration are not repeated by
these small author-path checks. Their unchanged sequence is covered by the local
workflow regression; no savings or whole-benchmark completion claim follows.
