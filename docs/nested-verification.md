# Nested Codex verification

A benchmarked program can launch its own Codex call during a test. That call
belongs to the benchmark's token total even when the test closes the program
before Codex finishes.

`lab/nested.py::CommandEnvironment` supplies a run-local launcher. It pins the
existing ChatGPT login, model and reasoning setting. `lab/child_process.py`
places the actual CLI call under a separate supervisor. The caller receives its
normal live output and exit status, but killing the caller or closing its output
pipe cannot destroy the CLI's output destination. The supervisor writes stdout,
stderr, the request and a terminal receipt to
`provider/commands/children/call-*/`.

`Codex.settle_children` waits for these calls at operation boundaries and before
another model response. It then requires the independently saved native session
history to contain complete turn and usage records. CLI output is retained for
inspection; it is not added on top of the native token counters. Resumed calls
still share one cumulative conversation counter.

Waiting uses the workflow's existing deadline and observed-token limit. It does
not extend the run budget or launch a replacement response. Workflow shutdown
cancels remaining supervisors; timeouts, incomplete receipts and missing usage
remain failures, not zero-token results. Usage already generated is never
refunded. An old failed run's missing usage is not reconstructed by this repair.

The supervisor inherits the caller's environment, stdin and OS restrictions;
it grants no extra sandbox access. Its artifacts require write access. Native
read-only commands cannot use this mechanism to bypass restrictions on local
Codex state or artifact writes. Subscription keys are not copied and API-key
environment variables remain excluded. Factor prompts and the Pi backend do
not use a different policy because of this supervisor.

The provider identity records `same-model-subscription-supervised-native-history-v2`.
The comparison guard therefore distinguishes this lifecycle policy from older
runs. Process receipts appear under `usage.nested.processes`; native histories
remain the source of token totals.

Each status scan is linear in the number of saved child calls. Repeated scans
over a growing number of calls can have quadratic cumulative bookkeeping cost;
this small local supervisor is not an unbounded process-history service.

## Verification

Run local tests with `python3 -m unittest discover -s tests -v`.
`tests/test_nested_shutdown.py` covers caller-group termination, closed pipes,
ordinary input/output/exit preservation, subscription/model restrictions,
deadline and owner cancellation, concurrent children, missing receipts and
blocking further model work on missing usage.

The explicit real-agent check is:

```sh
python3 tests/real_nested_shutdown.py --out runs/unique-shutdown-check
```

It uses the existing subscription for one short read-only response, kills the
caller's process group after generation starts, and compares final CLI usage
with the separate native history. It allows 180 seconds and 100,000 observed
raw tokens, creates no parent model response and never retries automatically.
This tests shutdown/accounting, not the complete benchmark or token savings.
