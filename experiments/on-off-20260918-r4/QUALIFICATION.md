# Nested-call and unchanged-feature qualification

The second tiny workflow passes in **263.54 seconds** with **352,201 raw tokens**:
330,274 from twelve parent turns and 21,927 from one child conversation's launch
and resume. Output: `runs/on-off-20260918-r4/real-nested-002/`.

- The real author inspects the existing parity function and tests, executes the
  launch/resume check and finishes without source changes. Shell representation
  errors and their recovery remain in its cost; the original multiline command
  was not directly compatible with the host's single-line operation format.
- Child `01a0b189-1917-74e2-bbdc-2861945663c8` records GPT-5.5/xhigh and Pro.
  Launch costs 10,945 raw; the resumed cumulative counter is 21,927, so the
  additional resume cost is 10,982—not another 21,927. Both exact replies pass.
- Independent review approves the complete existing feature. Final integration
  creates verification-only empty commit `acfeed3104f35728292d5c36332f91d43311ec8e`.
  All ten Python tests pass, the final clone is clean, and the original source
  is unchanged. The one-feature history contract passes without invented edits.
- All parent turns have complete final-message coverage. The child has two
  completed, priced turns. The live observer includes its usage during the run.

After the run ends, two additional failing regressions identify missing handling
of native assistant `response_item` records and rejection of an explicit API/unknown
plan label. The observational parser repair follows those failures; saved real
launch/resume replay still gives exactly 21,927 with the final assistant message
before its price. No model prompt, command environment or previous run is changed.
The full **59-test** suite passes in 20.974 seconds. These two checks affect
record validation, not agent behavior; their real-record replay requires no
additional generated response.

## Retained earlier qualification outcomes

`real-nested-001` fails at 143,950 raw parent tokens before any child response:
invalid option placement, followed by an unexpected output file. Its result and
checkout remain unchanged. It does not qualify the path.

`environment-probe-001` catches shell startup restoring an API-key variable;
an additional failing regression precedes the environment-hook fix.
`environment-probe-002` passes using the actual native command executor, with
the guarded path and no inherited API-key variables. Both generate zero tokens.

`native-child-001` preserves an actual native-sandbox limitation: nested Codex
fails to initialize local state before a thread starts, reporting read-only
filesystem. It generates zero child tokens and is **not** a successful native
real-agent smoke. The one non-generating `codex doctor` check confirms stored
ChatGPT authentication and reachable service. No permissions, global config or
auth home are changed. Host-run child launch/resume is the successfully verified
generation path, and the restricted native path remains explicit in the protocol.

The existing actual Git-history-rewrite and priced-interruption qualifications
remain valid. This tiny workflow verifies functional/measurement boundaries;
its cost is not a token-saving observation. The full six-run comparison follows
only with identical frozen repairs and settings in both groups.
