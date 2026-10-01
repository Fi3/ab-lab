"""Real tool calls, ownership, results and natural completion across adapters."""
from collections import deque
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from lab.host import Fatal, save_json
from lab.loops import WorkLimitReached
from lab.provider import Pi, PiThread, Usage
import test_provider as provider_fixtures

completed, message, price = provider_fixtures.completed, provider_fixtures.message, provider_fixtures.price


TOOLS = [{"name": "host_echo", "description": "Return the provided text.",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                          "required": ["text"], "additionalProperties": False}}]


def call(call_id="c", *, thread="t", turn="u", name="host_echo", text="request"):
    return {"id": "request-" + call_id, "method": "item/tool/call", "params": {
        "threadId": thread, "turnId": turn, "callId": call_id, "namespace": None,
        "tool": name, "arguments": {"text": text}}}


class CodexHostToolTests(unittest.TestCase):
    provider = provider_fixtures.StreamTests.provider

    def register(self, provider, handler=None):
        calls = []
        def execute(name, arguments, call_id):
            calls.append((name, arguments, call_id))
            return {"success": True, "text": "actual result"}
        provider.register_host_tools("t", TOOLS, handler or execute)
        return calls

    def test_tools_execute_in_turn_and_final_prose_is_not_an_operation(self):
        p = self.provider([call(), message("Implemented and checked."), price(), completed()])
        calls = self.register(p)
        requests = []
        p.rpc = lambda method, params: requests.append((method, params)) or {"turn": {"id": "u"}}
        self.assertEqual(p.turn("t", "Do the task.", "author"), "Implemented and checked.")
        self.assertEqual(calls, [("host_echo", {"text": "request"}, "t:u:c")])
        self.assertEqual(p.sent, [{"id": "request-c", "result": {"success": True,
            "contentItems": [{"type": "inputText", "text": "actual result"}]}}])
        self.assertNotIn("outputSchema", requests[0][1])
        self.assertEqual(requests[0][1]["input"][0]["text"], "Do the task.")
        self.assertEqual(p.turns[0]["status"], "completed")
        self.assertTrue(p.report()["measurement_complete"])

    def test_duplicate_delivery_uses_actual_cached_result(self):
        p = self.provider([call(), call(), message("Done."), price(), completed()])
        calls = self.register(p)
        p.turn("t", "Task", "author")
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.sent[0], p.sent[1])

    def test_completed_tool_turn_needs_no_final_text(self):
        p = self.provider([call(), price(), completed()])
        calls = self.register(p)
        self.assertEqual(p.turn("t", "Task", "author"), "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(p.report()["measurement_complete"])

    def test_callback_work_limit_retains_receipt_and_settles_usage(self):
        p = self.provider([call(), call("late"), price(), completed("interrupted")])
        calls = []
        def stop(*args):
            calls.append(args)
            error = WorkLimitReached({"reason": "repeated_no_progress", "metric": "repeats"})
            error.completed_tool_result = {"success": True, "text": "completed operation receipt"}
            raise error
        self.register(p, stop)
        with self.assertRaisesRegex(WorkLimitReached, "repeated_no_progress"):
            p.turn("t", "Task", "author")
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.sent[0]["method"], "turn/interrupt")
        self.assertEqual(p.sent[1]["result"]["contentItems"][0]["text"], "completed operation receipt")
        self.assertFalse(p.sent[2]["result"]["success"])
        self.assertTrue(p.report()["measurement_complete"])

    def test_conflicting_id_and_unfinished_handler_are_never_replayed(self):
        p = self.provider([])
        calls = self.register(p)
        p.dispatch_host_tool("t", "u", "host_echo", {"text": "one"}, "c")
        with self.assertRaisesRegex(Fatal, "conflicting or unfinished"):
            p.dispatch_host_tool("t", "u", "host_echo", {"text": "two"}, "c")
        self.assertEqual(len(calls), 1)
        def broken(*args):
            raise Fatal("uncertain operation")
        p = self.provider([])
        self.register(p, broken)
        with self.assertRaisesRegex(Fatal, "uncertain operation"):
            p.dispatch_host_tool("t", "u", "host_echo", {}, "c")
        with self.assertRaisesRegex(Fatal, "conflicting or unfinished"):
            p.dispatch_host_tool("t", "u", "host_echo", {}, "c")

    def test_foreign_stale_and_unknown_tools_have_no_effects(self):
        p = self.provider([call("foreign", thread="other"), call("stale", turn="before"),
            call("unknown", name="other"), message("Done."), price(), completed()])
        calls = self.register(p)
        p.turn("t", "Task", "author")
        self.assertEqual(calls, [])
        self.assertEqual(len(p.sent), 3)
        self.assertTrue(all(not item["result"]["success"] for item in p.sent))

    def test_rejected_tool_result_is_delivered_and_can_be_repaired(self):
        p = self.provider([call(), message("The operation failed."), price(), completed()])
        self.register(p, lambda *args: {"success": False, "text": "stale source"})
        self.assertEqual(p.turn("t", "Task", "author"), "The operation failed.")
        self.assertEqual(p.sent[0]["result"], {"success": False,
            "contentItems": [{"type": "inputText", "text": "stale source"}]})

    def test_start_registers_installed_codex_dynamic_tool_schema(self):
        p = self.provider([])
        p.parent_threads = set()
        p.register_native_thread = lambda thread: None
        requests = []
        p.rpc = lambda method, params: requests.append((method, params)) or {"thread": {"id": "t"}}
        p.start_thread(tools=TOOLS, tool_handler=lambda *args: {"success": True, "text": "ok"})
        self.assertEqual(requests[0][1]["dynamicTools"], [{"type": "function", **TOOLS[0]}])
        self.assertIn("t", p.host_tools)

    def test_missing_final_usage_and_provider_failure_are_not_completion(self):
        for events in ([call(), price(), message("Unpriced final"), completed()],
                       [call(), message("Partial"), price(), completed("failed")],
                       [call(), message("Partial"), price(), completed("interrupted")]):
            with self.subTest(events=events):
                p = self.provider(events)
                self.register(p)
                with self.assertRaises(Fatal):
                    p.turn("t", "Task", "author")
                self.assertFalse(p.report()["measurement_complete"])


class PiHostToolTests(unittest.TestCase):
    def provider(self, events):
        from types import SimpleNamespace
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = object.__new__(Pi)
        p.artifacts = Path(tmp.name)
        p.turns, p.missing_turns, p.usage = [], [], Usage()
        p.max_turns, p.max_raw, p.deadline = 10, 100000, time.monotonic() + 30
        p.prepare_turn = lambda *args: None
        p.sent_messages = []
        stream = deque(events)
        thread = SimpleNamespace(send=p.sent_messages.append,
            incoming=lambda timeout: stream.popleft() if stream else None,
            rpc=lambda message, timeout=5: {"success": True, "data": {"tokens": {
                "input": 100, "output": 20, "cacheRead": 5}}})
        thread.policy = p.artifacts / "policy.json"
        thread.request_journal = p.artifacts / "requests.jsonl"
        save_json(thread.policy, {})
        p.threads = {"t1": thread}
        return p

    def test_bridge_calls_share_handler_and_preserve_natural_completion(self):
        request = {"type": "lab_host_tool_call", "threadId": "t1", "turnId": "turn-0001",
                   "callId": "c", "tool": "host_echo", "arguments": {"text": "hello"}}
        p = self.provider([request, request, {"type": "message_end", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Finished normally."}],
            "usage": {"input": 100, "output": 20, "cacheRead": 5}}}, {"type": "agent_settled"}])
        th = p.threads["t1"]
        calls, responses = [], []
        def handler(*args):
            calls.append(args)
            return {"success": True, "text": "actual result"}
        p.register_host_tools("t1", TOOLS, handler)
        th.host_result = lambda *args: responses.append(args)
        self.assertEqual(p.turn("t1", "Task", "author"), "Finished normally.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "t1:turn-0001:c")
        self.assertEqual(responses[0], responses[1])
        self.assertTrue(p.report()["measurement_complete"])

    def test_pi_model_error_is_not_a_successful_handoff(self):
        p = self.provider([{"type": "message_end", "message": {"role": "assistant",
            "stopReason": "error", "errorMessage": "provider failed", "content": [],
            "usage": {"input": 100, "output": 20, "cacheRead": 5}}}, {"type": "agent_settled"}])
        with self.assertRaisesRegex(Fatal, "provider failed"):
            p.turn("t1", "Task", "author")
        self.assertEqual(p.turns[0]["status"], "failed")

    def test_completed_pi_turn_needs_no_final_text(self):
        p = self.provider([{"type": "message_end", "message": {"role": "assistant",
            "content": [], "usage": {"input": 100, "output": 20, "cacheRead": 5}}},
            {"type": "agent_settled"}])
        self.assertEqual(p.turn("t1", "Task", "author"), "")
        self.assertTrue(p.report()["measurement_complete"])

    def test_callback_work_limit_settles_pi_usage_without_another_operation(self):
        request = {"type": "lab_host_tool_call", "threadId": "t1", "turnId": "turn-0001",
                   "callId": "c", "tool": "host_echo", "arguments": {"text": "hello"}}
        p = self.provider([request, {**request, "callId": "late"}, {"type": "message_end", "message": {
            "role": "assistant", "content": [], "usage": {"input": 100, "output": 20, "cacheRead": 5}}},
            {"type": "agent_settled"}])
        thread = p.threads["t1"]
        calls, responses = [], []
        def stop(*args):
            calls.append(args)
            raise WorkLimitReached({"reason": "repeated_no_progress", "metric": "repeats"})
        p.register_host_tools("t1", TOOLS, stop)
        thread.host_result = lambda *args: responses.append(args)
        with self.assertRaisesRegex(WorkLimitReached, "repeated_no_progress"):
            p.turn("t1", "Task", "author")
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.sent_messages[-1], {"type": "abort"})
        self.assertTrue(all(not result[1]["success"] for result in responses))
        self.assertTrue(p.report()["measurement_complete"])

    def test_new_pi_thread_allows_registered_tools(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        p = self.provider([])
        p.executable, p.model, p.effort = "pi", "model", "xhigh"
        p.stderr = None
        p.repo, p.command_env = p.artifacts, {}
        p.sessions_dir = p.artifacts / "sessions"
        p.sessions_dir.mkdir()
        p.sandbox = SimpleNamespace(configure=lambda *args, **kwargs: None, module="file:///sdk.js")
        with patch("lab.provider.PiThread", return_value=SimpleNamespace()) as constructor:
            p.new_thread("t", tools=TOOLS)
        argv = constructor.call_args.args[1]
        self.assertIn("host_echo", argv[argv.index("--tools") + 1].split(","))
        self.assertEqual(constructor.call_args.kwargs["host_tools"], TOOLS)

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_real_pipe_bridge_registers_tools_and_round_trips_results(self):
        bridge = Path(__file__).resolve().parents[1] / "lab/pi_host_tools.mjs"
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            save_json(root / "tools.json", TOOLS)
            save_json(root / "policy.json", {"turn_id": "turn"})
            script = (f"import {{registerHostTools}} from {json.dumps(bridge.as_uri())};\n"
                      "let tool; registerHostTools({registerTool(t) {tool=t;}});\n"
                      "const result=await tool.execute('call', {text:'hello'});\n"
                      "console.log(JSON.stringify({type:'tested',result})); process.exit(0);\n")
            env = {**os.environ, "AGENT_LAB_PI_HOST_TOOLS": str(root / "tools.json"),
                   "AGENT_LAB_PI_POLICY": str(root / "policy.json")}
            with (root / "stderr").open("w") as stderr:
                thread = PiThread("thread", ["node", "--input-type=module", "-e", script],
                                  root, env, stderr, lambda *args: None, host_tools=TOOLS)
                try:
                    request = thread.incoming(5)
                    self.assertEqual(request["type"], "lab_host_tool_call")
                    self.assertEqual(request["arguments"], {"text": "hello"})
                    self.assertEqual(request["turnId"], "turn")
                    thread.host_result("call", {"success": True, "text": "actual receipt"})
                    result = thread.incoming(5)
                    self.assertEqual(result["result"]["content"], [{"type": "text", "text": "actual receipt"}])
                finally:
                    thread.close()


if __name__ == "__main__":
    unittest.main()
