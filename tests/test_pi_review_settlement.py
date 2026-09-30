"""Pi must retain elapsed-review stops until a completed usage boundary."""
from collections import deque
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from lab.host import Fatal
from lab.loops import FeatureProgress, WorkLimitReached, loop_policy
from lab.provider import Pi, Usage
from test_review_settlement import BEFORE, AFTER


def pi_tokens(values):
    return {"input": values[0]-values[2], "output": values[1],
            "cacheRead": values[2], "cacheWrite": 0}


def message_start(role="assistant", kind="message_start"):
    return {"type": kind, "message": {"role": role}}


def message_end(values=tuple(a-b for a,b in zip(AFTER, BEFORE)), text=""):
    return {"type": "message_end", "message": {"role": "assistant",
            "content": [{"type": "text", "text": text}] if text else [], "usage": pi_tokens(values)}}


class PiReviewSettlementTests(unittest.TestCase):
    def provider(self, scheduled, *, review_seconds=90, stats=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = 1000.0
        clock = patch("lab.provider.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        provider = object.__new__(Pi)
        provider.artifacts = provider.repo = Path(directory.name)
        provider.turns, provider.missing_turns = [], []
        provider.max_turns, provider.max_raw, provider.deadline = 10, 15000000, 11000.0
        provider.usage = Usage()
        provider.usage.observe_tokens("pi-review", *BEFORE)
        provider.model, provider.effort = "gpt-5.6-sol", "xhigh"
        provider.prepare_turn = lambda thread, writable: None
        provider.sent, provider.requests = [], []
        self.events = deque((1000+at, copy.deepcopy(event)) for at,event in scheduled)
        self.start = self.now
        progress = FeatureProgress({"id": "checkpoint_5"}, loop_policy({
            "max_feature_raw": 3_000_000, "max_review_raw": 500_000,
            "max_review_seconds": review_seconds}), 0)
        provider.work_limits = progress.limits(sum(BEFORE[:2]), reviewing=True)

        def send(event):
            provider.sent.append((self.now-self.start,event))
            if event["type"] == "prompt":
                self.assertEqual(sum(v["type"]=="prompt" for _,v in provider.sent),1,
                                 "no extra generation after a review stop")
            elif event["type"] == "abort":
                self.events = deque([(self.now+0.001,{"type":"agent_settled"})])

        def incoming(timeout):
            end = self.now+max(0.001,timeout)
            if not self.events or self.events[0][0]>end:
                self.now=end
                return None
            at,event=self.events.popleft()
            self.now=max(self.now,at)
            return event

        def rpc(event, timeout=5):
            provider.requests.append(event)
            self.assertEqual(event["type"],"get_session_stats")
            values = stats if stats is not None else provider.usage.totals["pi-review"]
            return {"success":True,"data":{"tokens":pi_tokens(values)}}
        policy = provider.artifacts / "pi-review-sandbox.json"
        policy.write_text("{}")
        provider.threads={"pi-review":SimpleNamespace(send=send,incoming=incoming,rpc=rpc,policy=policy)}
        return provider

    def stop(self, provider, expected=WorkLimitReached):
        with self.assertRaises(expected) as stopped:
            provider.turn("pi-review","Review the assigned requirements.","checkpoint_5-review-1",writable=True)
        self.assertEqual(sum(v["type"]=="prompt" for _,v in provider.sent),1)
        self.assertFalse((provider.artifacts/"turn-0001/host-operation.txt").exists())
        return stopped.exception

    def aborts(self, provider):
        return [at for at,event in provider.sent if event["type"]=="abort"]

    def settlement(self, provider, outcome, limit=90):
        value=provider.turns[0]["work_limit_settlement"]
        self.assertEqual(value["outcome"],outcome)
        self.assertEqual(value["settle_seconds"],600)
        self.assertGreaterEqual(value["trigger"]["observed"],limit)
        self.assertLess(value["trigger"]["observed"],limit+0.2)
        return value

    def test_default_review_finishes_beyond_previous_time_and_token_caps(self):
        provider = self.provider([(1, message_start()),
            (400, message_end((600000, 5000, 550000), text="NO_FINDINGS")),
            (400.01, {"type": "agent_settled"})])
        progress = FeatureProgress({"id": "checkpoint_5"}, loop_policy(), 0)
        provider.work_limits = progress.limits(sum(BEFORE[:2]), reviewing=True)

        reply = provider.turn("pi-review", "Review the assigned requirements.",
                              "checkpoint_5-review-1", writable=True)

        self.assertEqual(reply, "NO_FINDINGS")
        self.assertEqual(provider.usage.raw - sum(BEFORE[:2]), 605000)
        self.assertGreaterEqual(self.now - self.start, 400)
        self.assertEqual(provider.turns[0]["status"], "completed")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertFalse(self.aborts(provider))

    def test_silent_first_response_waits_for_finalized_usage_before_abort(self):
        provider=self.provider([(1,message_start()),(130,message_end())])
        error=self.stop(provider)
        self.assertEqual(error.signal["reason"],"review_time_limit")
        self.assertGreaterEqual(self.aborts(provider)[0],130)
        self.assertLess(self.aborts(provider)[0],131)
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw,sum(AFTER[:2]))
        self.assertEqual(json.loads((provider.artifacts/"turn-0001/messages.json").read_text()),[])
        self.settlement(provider,"priced_boundary")

    def test_priced_natural_verdict_remains_stopped_without_approval(self):
        provider=self.provider([(1,message_start()),(130,message_end(text="NO_FINDINGS")),
                                (130,{"type":"agent_settled"})])
        error=self.stop(provider)
        self.assertFalse(hasattr(error,"completed_reply"))
        self.assertFalse(self.aborts(provider))
        self.assertEqual(provider.turns[0]["status"],"completed")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual((provider.artifacts/"turn-0001/reply.txt").read_text(),"NO_FINDINGS")
        self.settlement(provider,"turn_completed")

    def test_next_assistant_activity_invalidates_earlier_priced_response(self):
        for kind in ("message_start","message_update"):
            with self.subTest(kind=kind):
                small=(10000,10,5000)
                remainder=tuple(a-b-c for a,b,c in zip(AFTER,BEFORE,small))
                provider=self.provider([(1,message_start()),(10,message_end(small)),
                                        (80,message_start(kind=kind)),(130,message_end(remainder))])
                self.stop(provider)
                self.assertGreaterEqual(self.aborts(provider)[0],130)
                self.assertTrue(provider.report()["measurement_complete"])
                self.settlement(provider,"priced_boundary")

    def test_stale_session_stats_do_not_cover_unpriced_following_response(self):
        provider=self.provider([(1,message_start()),(10,message_end(text="Progress")),
                                (80,message_start()),(100,{"type":"agent_settled"})])
        self.stop(provider)
        self.assertFalse(self.aborts(provider))
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertFalse(provider.turns[0]["usage_observed_after_last_message"])
        self.settlement(provider,"turn_completed")

    def test_stale_session_stats_cannot_cover_tail_even_without_elapsed_stop(self):
        provider=self.provider([(1,message_start()),(10,message_end(text="Progress")),
                                (20,message_start()),(30,{"type":"agent_settled"})])
        provider.work_limits=[]
        error=self.stop(provider,Fatal)
        self.assertNotIsInstance(error,WorkLimitReached)
        self.assertIn("incomplete Pi token measurement",str(error))
        self.assertFalse(provider.report()["measurement_complete"])

    def test_missing_first_receipt_stops_at_cap_and_retains_timeout_provenance(self):
        provider=self.provider([(1,message_start())])
        self.stop(provider,Fatal)
        self.assertGreaterEqual(self.aborts(provider)[0],690)
        self.assertLess(self.aborts(provider)[0],691)
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw,sum(BEFORE[:2]))
        self.settlement(provider,"timeout")

    def test_hard_global_deadline_preempts_settlement_even_with_stale_session_stats(self):
        provider=self.provider([(1,message_start())])
        provider.deadline=self.start+100
        self.stop(provider,Fatal)
        self.assertGreaterEqual(self.aborts(provider)[0],100)
        self.assertLess(self.aborts(provider)[0],100.2)
        self.assertFalse(provider.report()["measurement_complete"])
        self.settlement(provider,"hard_limit")

    def test_global_feature_and_review_token_caps_remain_hard(self):
        for kind in ("global","feature","review"):
            with self.subTest(kind=kind):
                provider=self.provider([(1,message_start()),(100,message_end())])
                if kind=="global":provider.max_raw=sum(BEFORE[:2])+1
                elif kind=="feature":provider.work_limits[0]["limit"]=sum(BEFORE[:2])+1
                else:provider.work_limits[-2]["limit"]=1
                error=self.stop(provider,Fatal)
                if kind=="global":self.assertNotIsInstance(error,WorkLimitReached)
                else:self.assertEqual(error.signal["reason"],"feature_token_limit" if kind=="feature" else "review_token_limit")
                self.assertGreaterEqual(self.aborts(provider)[0],100)
                self.assertLess(self.aborts(provider)[0],100.2)
                self.assertTrue(provider.report()["measurement_complete"])
                self.settlement(provider,"hard_limit")

    def test_exploration_elapsed_threshold_uses_same_receipt_settlement(self):
        provider=self.provider([(1,message_start()),(330,message_end())],review_seconds=300)
        error=self.stop(provider,WorkLimitReached)
        self.assertEqual(error.signal["reason"],"review_time_limit")
        self.assertFalse(hasattr(error, "completed_reply"))
        self.assertGreaterEqual(self.aborts(provider)[0],330)
        self.assertTrue(provider.report()["measurement_complete"])
        self.settlement(provider,"priced_boundary",limit=300)


if __name__=="__main__":
    unittest.main()
