# Three-point scb-check implementation verification

Scope: include actual scb-check JSON measurements in the standalone runner and
report output. The checkpoints are the untouched starting commit, all reviewed
features before integration, and the assembled final history before independent
final checks. Findings are observations, not a pass/fail quality threshold.
The external program's failure, invalid JSON or mutation of the measured source
stops the workflow and preserves previous measurements. No score enters an agent
prompt, feedback or review. No Work Leaf source or research counter is in scope.

The eight initial automated tests fail before implementation: the runner has no
checker argument or phase measurements, the CLI has no checker option, and report
omits scores. They cover actual subprocess execution, exit 1 as a valid report,
missing executable, invalid JSON/metrics, checker failure, timeout, source
mutation, prompt invariance, failed final tests and older unmeasured results.
Additional coverage exercises the actual installed checker and continuation's
reuse of the original initial measurement without repeating completed authors.

External tool: scb-check 0.2.0, installed in this project's ignored `.venv`,
without global packages, credentials, model calls or API use. Source:
https://github.com/gabeorlanski/scb-check . Its Python 3.12+ requirement belongs
to this separate executable; the runner itself requires Python 3.11+.

After local checks pass, admit exactly one tiny complete subscription-backed
workflow with the real installed checker: implement and test arithmetic
negation, independent review/repair, integration plan/accept, one final feature
commit, repository tests and an independent behavior assertion. This is not a
new large benchmark, a control, or a measurement of token savings.

Preserve all prompts, decisions, factor settings, transport, model and usage
accounting. Use the five enabled instructions from the user's recent baseline;
C08/C16/C17/C25 are disabled. The model is GPT-5.5/xhigh through the existing
ChatGPT subscription. Limits are 600 seconds for the whole workflow, 600,000
observed raw tokens, 16 parent turns and 300 seconds per scoring call within
the workflow deadline. Observed usage is a tripwire, not a hard billing cap.
Source hashes and exact input are frozen in the exclusive admission record.

Stop this verification at its first terminal result. Keep failures and partial
usage; do not repeat a failed model observation automatically. Passing requires
all three real checker results pinned to the correct commits, complete usage,
clean final source, unchanged runner source and both final commands passing.
The previous large benchmark observations remain immutable and are not rerun.
