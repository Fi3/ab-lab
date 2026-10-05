# Rebuildable benchmark executor

`executors/` contains only public build inputs: a Dockerfile, runtime defaults,
a dated OS package source, and dependency locks. No host snapshots, personal
paths, account settings, installed user files, or image archives are required.

On a Linux x86-64 machine with Docker and Python 3.12 or newer:

```sh
python3 -m lab.executor build
python3 -m lab.executor exec executors/default.json -- python3 --version
python3 -m lab doctor --out runs/login-check --harness codex
python3 -m lab run benchmarks/example.json --harness codex \
  --out runs/example-codex --seconds 1800 --max-raw 3000000 --max-turns 100
```

`run` and `doctor` build automatically if the recipe's image is absent. The
explicit build command is optional. Docker caches the build locally. Changing
any recipe input creates a new environment identity. A failed build stops the
run; it never falls back to host execution. Build logs go to stderr.

`lab run` initializes the bundled example repository and prepares the selected
SWE-Milestone or SlopCodeBench data and evaluator before launching the workflow. Supply
your own provider login; only `auth.json` is copied into temporary runtime state.
Personal provider settings, skills, plugins and shell profiles are not imported.

The ignored `.benchmarks/` directory is not present in a fresh Git clone.
`lab run` creates the required setup automatically; `lab plan` stays read-only.
To prepare either scikit-learn definition separately, use:

```sh
python3 benchmarks/swe_milestone.py prepare scikit-learn
python3 -m venv .benchmarks/swe-milestone-venv
.benchmarks/swe-milestone-venv/bin/python -m pip install \
  -r benchmarks/swe-milestone-requirements.txt
```

This downloads the pinned benchmark inputs and prepares its separate evaluator.
For other projects, follow [SWE-Milestone setup](SWE_MILESTONE.md).
Use the default `--scb-check scb-check` inside the executor. Host paths such as
`.venv/bin/scb-check` are not mounted into the coding container.
For the default executor, the old documented `.venv/bin/scb-check` argument is
accepted as an alias for the included `scb-check` so existing run commands work.

The toolchain follows the previous host's versions: Python 3.14.7, GCC 16.2.1,
Git 2.55.0, Node 26.9.0, npm 12.0.2, ripgrep 15.2.0, uv 0.12.16, fish 4.9.3,
Rust 1.95.0, Codex 0.159.3 and Pi 0.87.1. Arch packages come from the immutable
2026-09-18 archive. The base image and Rust archive have explicit SHA-256 pins;
Node and quality-checker dependencies have integrity/hash locks. The quality
checker lives in its own virtual environment. NumPy, SciPy, Cython and pytest
are absent from the default Python, as they were on the host.

This is a public reconstruction of that toolchain, rather than a copy of the
original CachyOS installation. Package builds and some supporting libraries
differ. Earlier results remain untouched; the new environment is recorded in
new runs. It does not claim byte-for-byte equivalence with earlier runs.

The complete agent workflow runs in the executor, including native and mediated
tools, reviewers, children, builds and public checks. Only the requested Git
baseline is imported from the benchmark. Credentials and the authenticated
host grading bridge are masked from agent tools. Benchmark grading retains
its existing separate environments; its quality checker uses the pinned recipe.

Docker uses the current operator's UID/GID for writable bind mounts; no fixed
host username or repository location is required. Linux kernel, hardware,
network, model service and credentials remain external inputs. Rebuilding gives
the same pinned software environment, not a guarantee of identical model output
or timings. Nested Codex sandboxing requires Docker to permit user namespaces
and uses `seccomp=unconfined` and `systempaths=unconfined`.
