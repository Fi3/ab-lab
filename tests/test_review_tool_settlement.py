"""Host tool replies must not restart generation while review usage settles."""
import unittest

from lab.loops import WorkLimitReached
from lab.review import REVIEW_TOOLS
import test_review_settlement as codex_fixture
import test_pi_review_settlement as pi_fixture


ARGUMENTS = {"review_id": "target", "status": "complete", "findings": [], "incomplete_reason": None}


class ReviewToolSettlementTests(unittest.TestCase):
    def replay(self, backend, *, callback_stop=None):
        callback = callback_stop is not None
        call_at = 89 if callback else 100
        calls, replies = [], []
        if backend == "codex":
            fixture = codex_fixture.ReviewSettlementTests()
            request = {"id": "review-tool-rpc", "method": "item/tool/call", "params": {
                "threadId": codex_fixture.THREAD, "turnId": codex_fixture.TURN,
                "callId": "verdict", "namespace": None,
                "tool": "submit_review", "arguments": ARGUMENTS}}
            provider = fixture.provider([
                (1, codex_fixture.started(), None), (call_at, request, None),
                (130, codex_fixture.price(), codex_fixture.AFTER)])
            thread = codex_fixture.THREAD
            original_send = provider.send

            def send(event):
                if "result" in event:
                    self.assertTrue(provider.sent, "tool reply would enable generation before interruption")
                    self.assertEqual(provider.sent[-1][1]["method"], "turn/interrupt")
                    replies.append((fixture.now - fixture.start, event["result"]["success"]))
                else:
                    original_send(event)

            provider.send = send
        else:
            fixture = pi_fixture.PiReviewSettlementTests()
            request = {"type": "lab_host_tool_call", "threadId": "pi-review", "turnId": "turn-0001",
                       "callId": "verdict", "tool": "submit_review", "arguments": ARGUMENTS}
            provider = fixture.provider([
                (1, pi_fixture.message_start()), (call_at, request), (130, pi_fixture.message_end())])
            thread = "pi-review"
            original_incoming = provider.threads[thread].incoming
            settled = False

            def incoming(timeout):
                nonlocal settled
                event = original_incoming(timeout)
                if event and event.get("type") == "agent_settled":
                    settled = True
                return event

            provider.threads[thread].incoming = incoming

            def host_result(call_id, result):
                self.assertEqual(provider.sent[-1][1]["type"], "abort",
                                 "tool reply would enable generation before interruption")
                self.assertTrue(settled, "the separate host reply pipe must wait for abort acknowledgement")
                replies.append((fixture.now - fixture.start, result["success"]))

            provider.threads[thread].host_result = host_result
        self.addCleanup(fixture.doCleanups)

        def handler(*arguments):
            calls.append(arguments)
            fixture.now = fixture.start + 90.01
            result = {"success": True, "text": "retained verdict"}
            if callback_stop == "raise":
                error = provider.budget_error()
                error.completed_tool_result = result
                raise error
            return result

        provider.register_host_tools(thread, REVIEW_TOOLS, handler)
        with self.assertRaises(WorkLimitReached) as stopped:
            provider.turn(thread, "Review the target", "review")
        self.assertEqual(stopped.exception.signal["reason"], "review_time_limit")
        self.assertEqual(len(calls), int(callback))
        self.assertEqual(len(replies), 1)
        self.assertGreaterEqual(replies[0][0], 130)
        self.assertLess(replies[0][0], 131)
        self.assertEqual(replies[0][1], callback)
        self.assertEqual(provider.turns[0]["work_limit_settlement"]["outcome"], "priced_boundary")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, sum(codex_fixture.AFTER[:2]))

    def test_codex_call_before_usage_waits_for_interruption_before_reply(self):
        self.replay("codex")

    def test_pi_call_before_usage_waits_for_interruption_before_reply(self):
        self.replay("pi")

    def test_codex_callback_time_stop_uses_usage_settlement(self):
        self.replay("codex", callback_stop="raise")

    def test_pi_callback_time_stop_uses_usage_settlement(self):
        self.replay("pi", callback_stop="raise")

    def test_codex_callback_finishing_after_expiry_retains_result_until_stop(self):
        self.replay("codex", callback_stop="return")

    def test_pi_callback_finishing_after_expiry_retains_result_until_stop(self):
        self.replay("pi", callback_stop="return")


if __name__ == "__main__":
    unittest.main()
