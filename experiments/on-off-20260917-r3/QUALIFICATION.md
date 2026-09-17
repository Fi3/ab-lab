# Required Git-history rewrite qualification

2026-09-17 20:37 UTC: all 49 local tests pass in 20.352 seconds. Python
compilation and whitespace checks pass. Non-generating preflight confirms
Codex 0.154.0, ChatGPT authentication, GPT-5.5/xhigh and the expected effective
configuration hash from the protocol. No provider or benchmark process remains
from either failed batch.

The saved tiny source is clean before cloning, with HEAD
`5b03b7a39ed550f4e83810ed4e6af8ad403cdcc1` and tree
`513de34c95472191fbd6faf4291e22c9601d2862`.
## Real-agent gate: PASS

2026-09-17 20:40 UTC: `runs/on-off-20260917-r3/real-integration-001/result.json`
passes, with 191,320 raw tokens and two naturally completed, fully measured turns.
There are no counter warnings, missing response counts or incomplete tails.
The agent actually replaces the three-commit input HEAD
`0ccd366ae8fc7b940be4aada0418f40ba856abfb` with final HEAD
`45cf5d40347309e3f09c90f779c3461839a055a4`. Its two final feature commits are
`47054a0f99cf00024cab8cc8be76e8d3ade1fa73` and
`45cf5d40347309e3f09c90f779c3461839a055a4`, with no merge or dirty source.
All ten tiny-project Python tests pass. The original saved source's HEAD, tree
and clean status still match the precheck values above. All frozen program and
benchmark input hashes still match the protocol. This is an actual native-agent
Git rewrite, not only a local command or an already-correct input history.

The user's conditional launch gate is satisfied. The three all-on workflows may
start concurrently, followed by the three all-off workflows on identical code.
Available memory is about 36 GiB and project-disk space about 570 GiB. The small
check is functional verification, not a seventh token-saving observation.
