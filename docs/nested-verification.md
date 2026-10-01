# Native delegation and accounting

Delegation follows C17. With C17 off, the runner preserves the harness's normal
delegation and tool configuration. With C17 on, the runner owns edits/commands
and disables agent-created sessions. This behavior is independent of model
selection. `--preset native` turns all Cs off and defaults to zero external
reviews; the runner has no final integration agent in any preset.

Codex native mode does not disable collaboration or apps. Child roles may use
configured models/effort different from their parent; actual identities and
usage are recorded. C17 verifies that both collaboration runtimes are disabled
before generation and keeps installed CLI delegation unavailable to agent tools.

Pi native mode preserves normal tools and extension discovery. Its entire
process, including loaded extension code, runs inside the shared OS filesystem
boundary. Pi does not have a built-in subagent tool: delegation comes from
installed extensions or CLI subprocesses. Read-only reviewer roles retain the
restricted tool surface and protected submission.

## State and execution

Native runs use private, temporary harness state copied from installed settings,
authentication and instruction files, with installed resources available without
granting shared-state writes. Session logs are retained under the run artifacts.
Private authentication copies are cleaned at shutdown. Config/resource identity
is recorded for comparison provenance; credentials are not included in reports.

Owned CLI subprocesses keep their own requested model and arguments. A process
supervisor preserves output and completion receipts if the initiating tool exits;
it cancels outstanding work on the run deadline or owner shutdown. Codex and Pi
CLI session persistence supplies owned usage evidence. Resume and fork selectors
can access histories created by this run; external user histories are excluded.
Aliases to the same history are counted once. Each call records its starting and
ending receipt boundaries, so an old response or a later successful resume cannot
certify a failed call. Delegated CLI working directories stay within the owned
checkout. Missing response receipts cannot establish zero-cost work or complete
accounting.

Filesystem permissions, global budgets, subscription-only authentication and
usage reconciliation remain. Native mode uses normal harness context handling;
the runner does not force early compaction or add a synthetic recovery prompt.
The runner's Git snapshot operations also execute inside the sandbox so hooks,
filters and fsmonitor commands cannot escape source permissions.

## Coverage and limits

Built-in Codex child lifecycle/history records are reconciled before another
measured parent response. Child histories appearing before spawn notifications
are excluded from generic counting until ownership is established, preventing
inherited parent usage from being counted twice. Response and owned compaction
receipts establish actual consumption. Delegated Pi CLI sessions include ordinary
responses and compaction usage.

An arbitrary third-party extension that calls an external model API without
harness session receipts is not automatically covered by this accounting. The
runner does not claim complete visibility into arbitrary remote services merely
because extension discovery is preserved. Use delegating extensions that retain
supported session evidence for measured comparisons.

## Local verification

`python3 -m unittest discover -s tests -v` runs offline regression tests and local
installed-tool probes, without model generation. Coverage includes native versus
C17 settings, role-specific tools, child lifecycle/usage, context behavior,
filesystem boundaries, and runner Git callback containment. The installed OS
sandbox probes need to run outside an enclosing sandbox that prevents their
startup.

`tests/replay_native_children.py` reads historical traces without generation.
Write replay output outside original runs. These checks validate runner behavior;
they do not claim that an unexecuted benchmark passed.
