# Three-point scb-check verification result

Status: **passed**, 2026-09-18. All 94 local tests pass, including ten dedicated
scoring tests. Python compilation and `git diff --check` pass. One real-agent
complete tiny workflow passes with the actual scb-check 0.2.0 executable.
The [prospective scope](PROTOCOL.md) and [machine-readable summary](SUMMARY.json)
retain the exact limits and evidence. This is implementation verification,
not an experiment estimating savings or general code-quality improvement.

## Automated checks

The initial eight test methods fail before implementation: the runner rejects
the missing `scb_check` parameter, the CLI rejects `--scb-check`, and report
omits the measurement. The completed tests verify:

- Untouched input, repaired/reviewed source and rewritten final history are
  measured in the correct order in a two-feature workflow.
- Enabled scoring leaves agent prompts, options and fake-backend usage identical.
- Findings (exit 1) remain valid measurements. Missing programs, exit 2,
  malformed JSON, missing/NaN/boolean metrics, timeout and source mutation
  cannot become successful scores or start initial model generation.
- A failed middle scan retains the first result and prevents final assembly.
  A failed final functional test retains all three completed measurements.
- CLI defaults require scoring; report includes results and shows `null` for
  older unmeasured runs. The comparison key distinguishes scored/unscored runs.
- Explicit continuation keeps the original initial measurement and does not
  repeat a completed author or mislabel modified source as the untouched input.
- The actual installed checker completes three scans in a local fake-agent
  workflow and every parsed result exactly matches its saved JSON output.

No pre-existing test is removed or modified. The relevant commands are:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q lab tests
git diff --check
```

## Actual subscription-backed workflow

Command:

```sh
python3 tests/real_scb.py --out runs/scb-check-20260918/real-01 \
  --scb-check /home/user/src/agent-behavior-lab/.venv/bin/scb-check
```

The agent implements arithmetic negation with positive, negative and zero tests.
An independent reviewer approves it. A separate integration conversation plans
and accepts final assembly. The finished repository is clean, has one final
feature commit, and passes both the repository tests and the independent
arithmetic assertion. Runner source hashes remain equal to admission.

| Measured checkpoint | Verbosity fraction | Cyclomatic erosion | Cognitive erosion | Source lines | Checker exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before changes | 0.2222222222 | 0 | 0 | 9 | 1 |
| After implementation/review | 0.1111111111 | 0 | 0 | 18 | 1 |
| After assembly | 0.1111111111 | 0 | 0 | 18 | 1 |

These fractions describe the tiny fixture only. The same two lines remain
flagged while total source lines increase; this is not evidence that a defect
was fixed. The initial commit is `e92cac33aadc10f471794245ea104a1b118c1f8d`.
The reviewed and assembled commit is
`2dcaf71ca38e175dbc5b758a8a3509aa0b370064`; the three invocations are distinct,
even though final assembly needs no source edit or history rewrite here.
The two-feature automated fixture independently covers a rewritten final history.

Cost: **273,303 raw tokens**, four completed model turns, complete token records,
zero nested generation. Whole workflow duration: **175.98 seconds**. The three
checker scans take **1.59 seconds combined** and use no model. None of the saved
model prompts contains checker results, checker stage names or score guidance.
The real run has no failed attempt or replacement. No API key/credits or previous
large-benchmark reruns are used.

Raw evidence remains in
`runs/scb-check-20260918/real-01/admission.json` and the `workflow/` directory:
`result.json`, `manifest.json`, `provider/`, `check-01/`, `check-02/`, and
`scb-check/{tool,before_changes,after_implementation,after_assembly}/`.
Each scoring directory retains the command, raw output and source identity.
Old benchmark results and Work Leaf product/research files remain unchanged.
