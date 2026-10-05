# Native baseline

`--preset native` forwards the benchmark requests to the selected harness with
all Cs off, zero runner review rounds and no runner repetition detector. Explicit
`--on`, `--max-review-loops` or `--loop-policy` arguments change those defaults and
are recorded. The final integration agent and history linearization have been
removed from every preset; there is no replacement model stage.

```sh
python3 -m lab run benchmarks/scb-code-search.json \
  --out runs/native-baseline --harness codex --model gpt-5.5 --effort xhigh \
  --preset native --seconds 10800 --max-raw 15000000 --max-turns 1000 \
  --scb-check .venv/bin/scb-check
```

Use `--harness pi` for Pi. Choose fresh output paths and identical explicit
limits/model settings for matched comparisons. `--compaction-tokens N` sets the
harness compaction threshold for every preset, including native; it must be a
positive integer and defaults to `131072`. The requested threshold is recorded
and must match for comparisons. A harness that cannot enforce it stops before
generation. The old `--skip-linearization`
option is removed, not retained as a no-op.

Add `--pi-vanilla` for a Pi baseline without installed or project customizations:

```sh
python3 -m lab run benchmarks/scb-code-search.json \
  --out runs/pi-vanilla --harness pi --preset native --pi-vanilla \
  --model gpt-5.5 --effort xhigh \
  --seconds 10800 --max-raw 15000000 --max-turns 1000
```

This flag is independent of the preset and also works with `--preset all`.
It disables discovered extensions, skills, prompt templates, themes, and
context files, including repository `AGENTS.md` and `CLAUDE.md`. Custom
`SYSTEM.md`/`APPEND_SYSTEM.md`, project settings, installed global settings,
and custom model catalogs are ignored. Pi retains its built-in system prompt
and the benchmark's explicit extension for sandboxing, accounting, and role
tools. Authentication is copied to private state; explicit model, effort,
compaction settings, and run limits still apply. Plans, manifests, provider
fingerprints, and single/batch results record the mode. With native delegation,
children inherit the clean global Pi home; child CLI options still belong to
the harness.

`--pi-vanilla` is a lab option implemented using supported Pi switches; the
pinned Pi 0.87.1 CLI does not provide a built-in `--vanilla` switch. Use
`python3 -m lab doctor --harness pi --native --pi-vanilla --out runs/pi-vanilla-doctor`
to check startup without a model request.

## Audit findings and changes

| Previously imposed behavior | Current behavior |
| --- | --- |
| An extra agent planned and executed final integration | No model generation after the last author/repair. Configured checks and independent grading run on the recorded submission. |
| Native left six Cs enabled and defaulted to three reviews | All Cs off, zero external reviews; explicit overrides remain possible. |
| Codex collaboration and apps disabled in native | Native preserves installed harness settings; C17 host ownership still disables delegation. |
| Pi extensions disabled and tools restricted to a fixed list | Native preserves extension discovery and normal tools inside a process sandbox. Read-only roles keep their restrictions. |
| Child model/effort forced to match the parent | Native records child identities; configured specialist models are allowed. |
| Native stopped by the runner repetition heuristic | Disabled by default for this preset; whole-run limits remain. |
| Runner forced early compaction and output recovery in native | The harness uses the requested `--compaction-tokens` threshold; native adds no runner-triggered compaction or synthetic retry prompt. |

Pi has no built-in subagent tool. Installed extensions or delegated CLI commands
provide that capability. Preserving extension discovery allows it; the runner
does not install a new agent implementation into Pi.

## Remaining differences from launching the harness yourself

- The runner selects the requested model and effort and requires the configured
  subscription login. It removes API-key fallback credentials.
- The runner applies and verifies the requested compaction threshold, including
  the default `131072`, instead of inheriting a different installed setting.
- Work occurs in an isolated checkout with explicit filesystem permissions and
  network access. Global time/token/turn limits and process cleanup apply.
- Harnesses run through their programmatic transports. Session and child usage
  receipts must reconcile; missing accounting stops a measured run rather than
  being recorded as zero. This is not unrestricted access to every remote model
  service an arbitrary extension could call.
- Session resumption is limited to this run's histories. Explicit Codex session
  IDs/names and `--last` can find owned CLI sessions across private homes; an
  interactive history picker sees only its selected private home.
- The runner records uncommitted files in Git at checkpoint boundaries for
  immutable snapshots. This affects visible history, but adds no author prompt
  or code changes. Author-created commits are preserved.
- SlopCodeBench uses its pinned upstream renderer and fresh checkpoint context.
  The pinned upstream runner itself calls `finish_checkpoint(reset_context=True)`;
  this is benchmark behavior, not an extra integration/review stage. Previously
  revealed requirements remain in the cumulative checkpoint request.
- `scb-check` and independent benchmark evaluation remain outside agent context.
  Quality-checker failures stop the measured run and their wall time counts
  toward the global deadline. No hidden evaluator results enter author prompts.

Native therefore means normal harness coding/delegation behavior within a
measured, isolated experiment. The workflow and effective provider policy
versions are recorded so these runs cannot be silently pooled with older ones.

## Historical correction

`python3 -m lab.exclude_integration FILE... --apply --report PATH` adds a derived
comparison view to saved results. It preserves original actual usage and outcomes.
Only reconciled integration usage is deducted; pre-integration correctness needs
a verified final checkpoint snapshot and matching quality measurement.

The audit covers 31 records in 23 files (28 distinct runs): 4 complete
corrections, 4 usage-only corrections, 11 without sufficient attribution, and 12
that never reached integration. The detailed audit is retained at
`runs/integration-exclusion-audit.json`. Original consumed tokens remain visible
in `summarize.py`; unavailable time/final checks are not invented. Old subagent
restrictions and prompts cannot be undone by subtracting integration tokens.
`lab report` preserves the correction evidence. `lab compare` and `lab interaction`
use the corrected view and still require proven successful, comparable runs;
they cannot reuse an integrated success to certify the earlier submission.
