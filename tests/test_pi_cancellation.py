"""A pre-dispatch cancellation receipt never covers an in-flight response."""
from collections import deque
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

from lab.host import Fatal
from lab.loops import FeatureProgress, WorkLimitReached, loop_policy
from lab.provider import PiCancellationReceipts, Usage
import test_pi_review_settlement as fixtures
from test_pi_review_settlement import message_end, message_start


class PiCancellationTests(unittest.TestCase):
    provider = fixtures.PiReviewSettlementTests.provider
    stop = fixtures.PiReviewSettlementTests.stop

    def replay(self, *, receipt=True, unpriced=False, mutate=None, incomplete=False,
               duplicate=False, duplicate_journal=False):
        # Exact retained numeric tail: 499,341 before the final 38,209-token
        # response. A 300s time limit is settling when that response crosses
        # the unchanged 500,000-token review cap at 313s.
        provider = self.provider([(1, message_start()),
            (2, message_end((485010, 14331, 436224))),
            (295, message_start()), (313, message_end((37265, 944, 36352)))],
            review_seconds=300)
        provider.usage = Usage()
        progress = FeatureProgress({"id": "generic-fixture"}, loop_policy({
            "max_feature_raw": 3_000_000, "max_review_raw": 500_000,
            "max_review_seconds": 300}), 0)
        provider.work_limits = progress.limits(0, reviewing=True)
        journal = provider.artifacts / "pi-review-requests.jsonl"
        proof = {"type": "request_not_dispatched", "receipt_id": str(uuid.uuid4()),
                 "thread_id": "pi-review", "turn_id": "turn-0001", "provider": "fixture",
                 "model": "fixture-model", "api": "fixture-api", "reason": "already_aborted_before_prepare"}
        error = {"role": "assistant", "content": [], "provider": "fixture", "model": "fixture-model",
                 "api": "fixture-api", "stopReason": "error", "timestamp": 1790713693112,
                 "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                 "errorMessage": PiCancellationReceipts.prefix + proof["receipt_id"]}
        if mutate:
            mutate(proof, error)
        original_send = provider.threads["pi-review"].send

        def send(event):
            original_send(event)
            if event["type"] != "abort":
                return
            if receipt:
                journal.write_text((json.dumps(proof) + "\n") * (2 if duplicate_journal else 1))
            events = []
            if unpriced:
                events += [message_start(), {"type": "message_update", "assistantMessageEvent": {
                    "type": "thinking_delta", "delta": "unpriced"}}]
            events += [{"type": kind, "message": copy.deepcopy(error)}
                       for kind in ("message_start", "message_end", "turn_end")]
            if incomplete:
                events.pop()
            if duplicate:
                events += copy.deepcopy(events)
            events += [{"type": "agent_settled"}]
            self.events = deque((self.now + (i+1)*0.01, value) for i, value in enumerate(events))
        provider.threads["pi-review"].send = send
        return provider

    def test_receipt_backed_cancelled_next_request_preserves_fully_priced_boundary(self):
        provider = self.replay()
        error = self.stop(provider)
        self.assertEqual(error.signal["reason"], "review_token_limit")
        self.assertEqual(provider.usage.raw, 537550)
        row = provider.turns[-1]
        self.assertEqual(row["work_limit_settlement"]["trigger"]["reason"], "review_time_limit")
        self.assertEqual(row["work_limit_settlement"]["outcome"], "hard_limit")
        self.assertEqual(row["cancelled_requests"][0]["events"], ["message_start", "message_end", "turn_end"])
        self.assertTrue(provider.report()["measurement_complete"])

    def test_owned_receipt_never_covers_an_earlier_unpriced_response(self):
        provider = self.replay(unpriced=True)
        self.stop(provider)
        self.assertEqual(provider.usage.raw, 537550)
        self.assertFalse(provider.report()["measurement_complete"])

    def test_unreceipted_native_empty_abort_remains_incomplete(self):
        provider = self.replay(receipt=False,
            mutate=lambda _proof, error: error.update(errorMessage="This operation was aborted"))
        self.stop(provider)
        self.assertFalse(provider.report()["measurement_complete"])

    def test_forged_foreign_duplicate_or_nonempty_receipt_is_rejected(self):
        cases = [dict(receipt=False), dict(duplicate=True), dict(duplicate_journal=True),
                 dict(mutate=lambda proof, _error: proof.update(turn_id="earlier-turn")),
                 dict(mutate=lambda proof, _error: proof.update(thread_id="foreign")),
                 dict(mutate=lambda _proof, error: error.update(content=[{"type": "text", "text": "unpriced"}])),
                 dict(mutate=lambda _proof, error: error.update(responseId="response-was-dispatched")),
                 dict(mutate=lambda _proof, error: error.update(usage={"input": 1, "output": 0}))]
        for case in cases:
            with self.subTest(case=case):
                provider = self.replay(**case)
                error = self.stop(provider, Fatal)
                self.assertNotIsInstance(error, WorkLimitReached)
                self.assertFalse(provider.report()["measurement_complete"])

    def test_incomplete_synthetic_lifecycle_is_not_accepted(self):
        provider = self.replay(incomplete=True)
        self.stop(provider)
        self.assertFalse(provider.report()["measurement_complete"])

    @unittest.skipUnless(shutil.which("node") and shutil.which("pi"), "Installed Node/Pi SDK required")
    def test_installed_runtime_cancellation_never_calls_provider_or_auth(self):
        sdk = next(parent / "dist/index.js" for parent in Path(shutil.which("pi")).resolve().parents
                   if (parent / "package.json").is_file()
                   and json.loads((parent / "package.json").read_text()).get("name", "").endswith("/pi-coding-agent"))
        guard = Path(__file__).resolve().parents[1] / "lab/pi_usage.mjs"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "policy.json").write_text(json.dumps({"turn_id": "turn-1"}))
            script = f"""
import {{ModelRuntime}} from {json.dumps(sdk.as_uri())};
import {{installRequestGuard}} from {json.dumps(guard.as_uri())};
const runtime = Object.create(ModelRuntime.prototype);
let prepared = 0;
runtime.prepareRequest = async function(model, options) {{
  prepared++; return {{model, options, provider: {{streamSimple() {{throw new Error('unexpected provider call');}}}}}};
}};
installRequestGuard(runtime, process.argv[1], process.argv[2], 'owned-thread');
const model = {{id:'fixture-model', provider:'fixture', api:'fixture-api'}};
const controller = new AbortController();
await runtime.prepareRequest(model, {{signal:controller.signal}});
controller.abort();
const response = await runtime.streamSimple(model, {{messages:[]}}, {{signal:controller.signal}}).result();
console.log(JSON.stringify({{prepared, response}}));
"""
            result = subprocess.run(["node", "--input-type=module", "-e", script,
                str(root / "policy.json"), str(root / "requests.jsonl")],
                text=True, capture_output=True, timeout=15, check=True)
            payload = json.loads(result.stdout)
            receipt = json.loads((root / "requests.jsonl").read_text())
            self.assertEqual(payload["prepared"], 1, "only the uncancelled call may delegate")
            self.assertEqual(payload["response"]["errorMessage"], PiCancellationReceipts.prefix + receipt["receipt_id"])
            self.assertEqual(payload["response"]["content"], [])
            self.assertEqual(payload["response"]["usage"]["totalTokens"], 0)
            self.assertEqual(receipt["thread_id"], "owned-thread")
            self.assertEqual(receipt["turn_id"], "turn-1")


if __name__ == "__main__":
    unittest.main()
