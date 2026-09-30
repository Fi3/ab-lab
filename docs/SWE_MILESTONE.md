# SWE-Milestone projects

`benchmarks/swe_milestone.py` imports [SWE-Milestone](https://github.com/DeepCommit-ai/SWE-Milestone)
into the existing benchmark JSON format. Each project is prepared and run
separately. **No runner changes are required.**

| Project argument | Release range | Tasks | Graded tasks |
| --- | --- | ---: | ---: |
| `ripgrep` | 14.1.1 → 15.0.0 | 13 | 11 |
| `dubbo` | 3.3.3 → 3.3.6 | 13 | 12 |
| `element-web` | 1.11.95 → 1.11.97 | 18 | 18 |
| `navidrome` | 0.57.0 → 0.58.0 | 9 | 9 |
| `nushell` | 0.106.0 → 0.108.0 | 13 | 13 |
| `scikit-learn` | 1.5.2 → 1.6.0 | 12 | 12 |
| `go-zero` | 1.6.0 → 1.9.3 | 23 | 23 |

This is a **lab adaptation**, not an official leaderboard run. Upstream lets an
agent choose available tasks in a continuous session inside its prepared
container. Here, the lab controls author sessions, reviews, factors and final
integration. Tasks follow a fixed, deterministic topological order: strong
dependencies first, including `additional_dependencies.csv`, with milestone ID
as the tie-breaker. Weak edges do not constrain execution, matching upstream's
default unlocking policy. Code carries forward between tasks.

## Prepare one project

From this repository, with Git, Docker and Python 3.10 or newer available:

```bash
python3 benchmarks/swe_milestone.py list
python3 benchmarks/swe_milestone.py prepare ripgrep
```

Preparation downloads the pinned harness and dataset, then pulls **only the
selected project's starting image**. It exports the prepared source and its
reachable Git history, excluding future refs. It writes:

```text
.benchmarks/swe-milestone-projects/ripgrep/
  benchmark.json       # ordinary lab benchmark, with verbatim upstream SRS text
  import.json          # task mapping, grading eligibility, pins and input hashes
  repo/                # starting repository
  repo_config.yaml     # frozen official grading configuration
  runtime_policy.yaml  # frozen official grading environment policy
```

Task selection follows the release's selected list, or all milestones when the
release has no selection file. Ungraded tasks remain in the sequence; they are
excluded only from the correctness denominator. Dots in milestone IDs become
underscores in lab feature IDs; grading retains the original IDs.

Preparation does not launch a model, modify runner code, or install project
toolchains on the host. Docker images can be large. Dataset downloads, exported
repositories and generated benchmark files are under the already ignored
`.benchmarks/` directory.

## Run with the existing runner

For example, replacing `MODEL_ID` with the model being tested:

```bash
python3 -m lab run .benchmarks/swe-milestone-projects/ripgrep/benchmark.json \
  --out runs/milestone-ripgrep-1 \
  --harness codex --model MODEL_ID --effort xhigh \
  --preset all --max-review-loops 3 --skip-linearization \
  --seconds 10800 --max-raw 15000000 --max-turns 1000 \
  --scb-check .venv/bin/scb-check
```

Use the same imported configuration, execution environment and budgets when
comparing models or factors. `--skip-linearization` keeps the original feature
history easy to inspect. Preserve the run's `checkout/` and checkpoint receipts
until grading completes.

**Author commands execute in the lab's normal host environment.** Exporting
source from a Docker image does not move the coding harness into that image.
The host needs the project's compiler, package manager, dependencies and native
libraries: Rust/Cargo and PCRE2 for Ripgrep; Java/Maven for Dubbo; Node/Yarn for
Element; Go/Node for Navidrome; Rust for Nushell; a compatible Python/Cython
build environment for scikit-learn; Go for go-zero. This difference from the
upstream execution environment must be recorded in comparisons.
The frozen runtime policy controls the independent grader only; it does not
apply upstream's network quarantine to the author.

The catalog supplies public build checks for integration. To choose a different
public check, pass `--check 'COMMAND'` during preparation (repeatable). The
runner's existing 300-second per-command ceiling still applies. Changing checks
changes the experimental configuration. Successful public builds and reviewer
approval **do not establish SWE-Milestone correctness**.

## Grade saved commits and measure code evolution

Set up a separate environment for the official evaluator:

```bash
python3 -m venv .benchmarks/swe-milestone-venv
.benchmarks/swe-milestone-venv/bin/python -m pip install \
  -r benchmarks/swe-milestone-requirements.txt

.benchmarks/swe-milestone-venv/bin/python benchmarks/swe_milestone.py evaluate \
  ripgrep runs/milestone-ripgrep-1 --scb-check .venv/bin/scb-check
```

This command runs **after** the lab finishes. It does not call a model or send
grader findings back to an author. It:

1. Verifies the imported inputs and each saved checkpoint's request and commit.
2. Measures each milestone's committed tree with `scb-check` in a disposable
   checkout, including ungraded milestones.
3. Builds source snapshots using the pinned upstream source filters, build
   manifest rules and integrity sidecars. Hidden tests remain evaluator-owned.
4. Pulls the required milestone images by their published digest and invokes
   the unmodified official evaluator. It uses the release's filtered verdict
   when available, preserving the underlying reports and test counts.
5. Grades every graded milestone against the recorded final assembly commit
   too. An identical commit already graded for that milestone reuses its result.

The normal runner already records before/after implementation and assembly
quality. The adapter adds the missing per-milestone measurements. Final grading
uses the commit in `scb-check/after_assembly/result.json`, never whatever happens
to be checked out when grading is requested.

Results go to `RUN/swe-milestone/result.json`, with detailed logs, source
snapshots and grader reports beside it. This is separate from `RUN/result.json`:
the existing `summarize.py` describes the lab workflow and does not read the new
correctness report. Consult both. No existing result is rewritten.

`solved` requires every graded checkpoint and final-assembly evaluation to pass,
with all milestone quality measurements complete. Missing checkpoints, missing
final assembly or grader errors leave the report incomplete. Failed tests are
preserved as failures. Exit codes are 0 for solved, 1 for completed but unsolved,
and 2 for incomplete or an adapter/grader error.

For a small grading check, use `--milestone ORIGINAL_ID` (repeatable). The full
denominator remains visible, and a partial selection cannot claim completion.
`--seconds N` limits each evaluator invocation (default 3600); image download
time is separate. A rerun requires a new `--out DIRECTORY`, preserving earlier
evidence. Grading is sequential and only uses images for the selected project.

## Release and verification

The adapter supports one pinned release, with no compatibility modes:

- Dataset: [v1.0.2](https://huggingface.co/datasets/DeepCommit-ai/SWE-Milestone-data),
  commit `3500478e740d42583277c2658aa7729eb36e10f4`.
- Harness: commit `17a8f1593e172e26b36cea15e2b30fb9536c93f5`.
- Images: the harness's `manifests/digests-v1.0.2.tsv`.

The upstream harness and dataset are MIT licensed; their notices stay with the
downloaded repositories. Specifications are imported locally, not vendored into
this repository.

Offline adapter tests:

```bash
python3 -m unittest discover -s tests -p test_swe_milestone.py -v
```

Implementation verification also loaded all seven task sequences and exercised
the real Ripgrep evaluator with an unchanged baseline and an upstream reference
implementation. These were adapter fixtures, **not model benchmark runs**.
