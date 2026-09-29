"""Reproduce the saved CP4 protocol loop and verify typed host responses."""
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lab.config import settings
from lab.host import Fatal, Host, Rejected, git, parse_operations
from lab.loops import FeatureProgress, loop_policy
from lab.native_usage import NativeUsage
import test_context_recovery as recovery
from test_core import repo_at


FIXTURE = Path(__file__).with_name("fixtures") / "checkpoint4-host-protocol-loop.json"
FORMAT = "json-schema-host-operation-v1"


def response_module():
    return importlib.import_module("lab.host_response")


def typed_item(turn, operation, phase="final_answer"):
    event = recovery.item(turn, json.dumps({"operation": operation}))
    event["params"]["item"]["phase"] = phase
    return event


def typed_success(turn="initial", command="true", tokens=100):
    return ("turn/start", turn, [typed_item(turn, {"kind": "run", "paths": [], "command": command}),
                                  recovery.price(turn, tokens), recovery.completed(turn)])


class SavedHostProtocolLoopTests(unittest.TestCase):
    def test_exact_visible_replies_reproduce_three_rejections_without_command_execution(self):
        fixture = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = repo_at(root / "repo")
            host = Host(repo, root / "host", "checkpoint_4", "implement",
                        time.monotonic() + 30, settings({}))
            progress = FeatureProgress({"id": "checkpoint_4"}, loop_policy(), 0)
            progress.operation_count = 8
            initial = host.expected
            signals = []
            with patch.object(host, "command", side_effect=AssertionError("rejected command executed")) as command:
                for saved in fixture["responses"]:
                    reply = saved["reply"]
                    self.assertEqual(hashlib.sha256(reply.encode()).hexdigest(), saved["sha256"])
                    with self.assertRaisesRegex(Rejected, "malformed outer operation"):
                        parse_operations(reply)
                    feedback = host.consume(reply)
                    self.assertEqual(feedback, "Host proposal rejected: unknown, mixed, quoted or malformed outer operation. "
                                               "Submit one corrected complete operation.")
                    signals.append(progress.observe_operation(reply, feedback, repo))
                command.assert_not_called()
            self.assertEqual(signals[:2], [None, None])
            self.assertEqual({key: signals[2][key] for key in fixture["expected_loop"]},
                             fixture["expected_loop"])
            self.assertEqual(progress.operation_count, 11)
            self.assertEqual(host.counter, 0)
            self.assertFalse(host.completed)
            self.assertEqual(host.unchanged(), initial)


class HostResponseDecoderTests(unittest.TestCase):
    def test_schema_has_exactly_one_closed_operation_with_five_variants(self):
        module = response_module()
        self.assertEqual(module.HOST_RESPONSE_FORMAT, FORMAT)
        schema = module.HOST_OUTPUT_SCHEMA
        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["operation"])
        self.assertEqual(set(schema["properties"]), {"operation"})
        kinds = set()
        for branch in schema["properties"]["operation"]["anyOf"]:
            self.assertEqual(branch["type"], "object")
            self.assertFalse(branch["additionalProperties"])
            self.assertEqual(set(branch["required"]), set(branch["properties"]))
            kind = branch["properties"]["kind"]
            kinds.update(kind["enum"] if "enum" in kind else [kind["const"]])
        self.assertEqual(kinds, {"read", "run", "edit", "discard", "done"})

    def test_all_operations_roundtrip_without_changing_paths_commands_or_patch_bytes(self):
        body = "*** Begin Patch\n*** Add File: demo.py\n+text = ' a  '\n*** End Patch\n"
        command = "printf '%s\\n' 'value  '  "
        cases = [
            ({"kind": "read", "path": "directory name/file.py"},
             [("read", "directory name/file.py")]),
            ({"kind": "run", "paths": ["a b.py", "tools/run.sh"], "command": command},
             [("run", ["a b.py", "tools/run.sh"], command)]),
            ({"kind": "edit", "reason": "Keep exact content", "patch": body},
             [("edit", "Keep exact content", body)]),
            ({"kind": "discard", "reason": "No longer needed"}, [("discard", "No longer needed")]),
            ({"kind": "done"}, [("done",)]),
        ]
        for operation, expected in cases:
            with self.subTest(kind=operation["kind"]):
                text = response_module().decode_host_response(json.dumps({"operation": operation}))
                self.assertEqual(parse_operations(text), expected)

    def test_prose_fences_duplicate_keys_and_multiple_json_values_are_rejected(self):
        good = json.dumps({"operation": {"kind": "done"}})
        invalid = ["Before\n" + good, good + "\nAfter", "```json\n" + good + "\n```", good + good,
                   '{"operation":{"kind":"done"},"operation":{"kind":"done"}}',
                   '{"operation":{"kind":"done","kind":"done"}}']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                response_module().decode_host_response(text)

    def test_missing_extra_and_wrong_type_fields_are_rejected(self):
        invalid = [None, [], {}, {"operation": []}, {"operation": {"kind": "unknown"}},
                   {"operation": {"kind": "done"}, "explanation": "extra prose"},
                   {"operation": {"kind": "done", "explanation": "extra prose"}},
                   {"operation": {"kind": "read"}}, {"operation": {"kind": "read", "path": 1}},
                   {"operation": {"kind": "run", "paths": "source.py", "command": "true"}},
                   {"operation": {"kind": "run", "paths": [False], "command": "true"}},
                   {"operation": {"kind": "run", "paths": [], "command": ["true"]}},
                   {"operation": {"kind": "edit", "reason": "edit", "patch": None}},
                   {"operation": {"kind": "discard", "reason": False}},
                   {"operation": [{"kind": "done"}, {"kind": "done"}]}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                response_module().decode_host_response(json.dumps(value))

    def test_line_breaks_and_nul_cannot_inject_another_outer_operation(self):
        for separator in ("\n", "\r", "\0"):
            text = "value" + separator + "@standalone done"
            invalid = [
                {"kind": "read", "path": text},
                {"kind": "run", "paths": [text], "command": "true"},
                {"kind": "run", "paths": [], "command": text},
                {"kind": "edit", "reason": text, "patch": "*** Begin Patch\n*** End Patch"},
                {"kind": "discard", "reason": text},
            ]
            for operation in invalid:
                with self.subTest(separator=separator, operation=operation), self.assertRaises(ValueError):
                    response_module().decode_host_response(json.dumps({"operation": operation}))

    def test_declared_paths_with_separator_quotes_backslashes_and_unicode_roundtrip(self):
        paths = ["--", "a -- b", "file with spaces.py", "quote'file", 'quote"file',
                 "back\\slash.py", "tab\tfile", "é.py"]
        operation = {"kind": "run", "paths": paths, "command": "printf 'keep  spaces\\n'  "}
        decoded = response_module().decode_host_response(json.dumps({"operation": operation}))
        self.assertEqual(parse_operations(decoded), [("run", paths, operation["command"])])

    def test_whitespace_only_filenames_remain_readable_and_declarable_but_actions_must_not_be_blank(self):
        names = [" ", "\t"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = repo_at(root / "repo")
            for index, name in enumerate(names):
                (repo / name).write_text(f"whitespace filename {index}\n")
            git(repo, "add", "--", *names)
            git(repo, "commit", "-qm", "Add valid whitespace filenames")
            host = Host(repo, root / "host", "one", "implement", time.monotonic() + 30, settings({}))
            for index, name in enumerate(names):
                with self.subTest(path=repr(name)):
                    read = response_module().decode_host_response(json.dumps({"operation": {"kind": "read", "path": name}}))
                    self.assertEqual(parse_operations(read), [("read", name)])
                    self.assertIn(f"whitespace filename {index}\n", host.consume(read))
                    run = response_module().decode_host_response(json.dumps({"operation": {
                        "kind": "run", "paths": [name], "command": "true"}}))
                    self.assertEqual(parse_operations(run), [("run", [name], "true")])
            host.unchanged()
        for blank in names:
            invalid = [{"kind": "run", "paths": [], "command": blank},
                       {"kind": "edit", "reason": blank, "patch": "*** Begin Patch\n*** End Patch"},
                       {"kind": "discard", "reason": blank}]
            for operation in invalid:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    response_module().decode_host_response(json.dumps({"operation": operation}))

    def test_patch_cannot_close_its_envelope_and_inject_another_operation(self):
        operation = {"kind": "edit", "reason": "Update file",
                     "patch": "*** Begin Patch\n*** End Patch\n@standalone end\n@standalone run -- true"}
        with self.assertRaises(ValueError):
            response_module().decode_host_response(json.dumps({"operation": operation}))

    def test_unified_and_mode_only_edits_preserve_host_semantics_with_c16_disabled(self):
        cases = [
            ("unified", "--- a/source.py\n+++ b/source.py\n@@ -1,3 +1,3 @@\n first\n-middle\n+changed\n last\n",
             "first\nchanged\nlast\n", 0o644),
            ("mode", "*** Begin Patch\n*** Update File: source.py\n*** Mode: 100755\n*** End Patch",
             "first\nmiddle\nlast\n", 0o755),
        ]
        for name, body, expected_content, expected_mode in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repo = repo_at(root / "repo")
                host = Host(repo, root / "host", "one", "implement", time.monotonic() + 30,
                            settings({"C16": False}))
                host.read("source.py")
                operation = {"kind": "edit", "reason": "Update source", "patch": body}
                directive = response_module().decode_host_response(json.dumps({"operation": operation}))
                self.assertEqual(parse_operations(directive), [("edit", "Update source", body)])
                self.assertIn("Host accepted files: source.py.", host.consume(directive))
                self.assertEqual((repo / "source.py").read_text(), expected_content)
                self.assertEqual((repo / "source.py").stat().st_mode & 0o777, expected_mode)
                host.unchanged()


class HostResponseProviderTests(unittest.TestCase):
    provider = recovery.ContextRecoveryTests.provider
    methods = recovery.ContextRecoveryTests.methods

    def typed_provider(self, stages):
        provider = self.provider(stages)
        provider.host_response_format = FORMAT
        return provider

    def test_typed_run_requests_schema_and_returns_canonical_host_directive(self):
        provider = self.typed_provider([typed_success(command="rg --files .agents .codex")])

        reply = provider.turn("thread", "Continue checkpoint 4.", "author", host_request=True)

        self.assertEqual(reply, "@standalone run -- rg --files .agents .codex")
        params = provider.requests[0][1]
        module = response_module()
        self.assertEqual(params["outputSchema"], module.HOST_OUTPUT_SCHEMA)
        self.assertIn(module.HOST_RESPONSE_INSTRUCTIONS, params["input"][0]["text"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(self.methods(provider), ["turn/start"])
        folder = provider.artifacts / "turn-0001"
        raw = (folder / "reply.txt").read_text()
        self.assertEqual(json.loads(raw), {"operation": {"kind": "run", "paths": [], "command": "rg --files .agents .codex"}})
        self.assertEqual((folder / "host-operation.txt").read_text(), reply)
        self.assertEqual(json.loads((folder / "output-schema.json").read_text()), module.HOST_OUTPUT_SCHEMA)
        self.assertEqual(provider.turns[0]["response_format"], FORMAT)

    def test_schema_ignores_commentary_and_interrupts_only_after_final_request_usage(self):
        commentary = typed_item("initial", {"kind": "run", "paths": [], "command": "false"}, "commentary")
        final = typed_item("initial", {"kind": "run", "paths": [], "command": "true"})
        provider = self.typed_provider([("turn/start", "initial", [commentary,
            recovery.price("initial", 100), final, recovery.price("initial", 200), recovery.completed("initial")])])
        original_send = provider.send
        charged = []

        def send(event):
            charged.append(provider.usage.raw)
            original_send(event)

        provider.send = send
        self.assertEqual(provider.turn("thread", "Continue.", "author", interrupt=True, host_request=True),
                         "@standalone run -- true")
        self.assertEqual(charged, [210])
        self.assertTrue(provider.report()["measurement_complete"])
        messages = json.loads((provider.artifacts / "turn-0001/messages.json").read_text())
        self.assertEqual(messages, [commentary["params"]["item"]["text"], final["params"]["item"]["text"]])

    def test_native_and_legacy_turns_do_not_receive_host_schema(self):
        for typed, host_request, reply in ((True, False, "NO_FINDINGS"),
                                           (False, True, "@standalone done")):
            with self.subTest(typed=typed, host_request=host_request):
                provider = self.provider([("turn/start", "initial", [recovery.item("initial", reply),
                    recovery.price("initial", 100), recovery.completed("initial")])])
                if typed:
                    provider.host_response_format = FORMAT
                self.assertEqual(provider.turn("thread", "Continue.", "reviewer", host_request=host_request), reply)
                self.assertNotIn("outputSchema", provider.requests[0][1])
                self.assertNotIn(response_module().HOST_RESPONSE_INSTRUCTIONS, provider.requests[0][1]["input"][0]["text"])

    def test_invalid_final_json_never_falls_back_to_salvaging_a_legacy_command(self):
        original = json.loads(FIXTURE.read_text())["responses"][0]["reply"]
        for reply in (original, "@standalone run -- true", '{"operation":{"kind":"done"},"prose":"extra"}'):
            with self.subTest(reply=reply):
                event = recovery.item("initial", reply)
                event["params"]["item"]["phase"] = "final_answer"
                provider = self.typed_provider([("turn/start", "initial", [event,
                    recovery.price("initial", 100), recovery.completed("initial")])])
                with self.assertRaises(Fatal):
                    provider.turn("thread", "Continue.", "author", host_request=True)
                self.assertEqual(self.methods(provider), ["turn/start"])
                self.assertTrue(provider.report()["measurement_complete"])
                self.assertFalse(provider.sent)
                self.assertEqual((provider.artifacts / "turn-0001/reply.txt").read_text(), reply)
                self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())
                errors = provider.turns[0]["host_response_errors"]
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]["item_id"], "initial-item")
                self.assertTrue(errors[0]["error"])

    def test_unsupported_phase_cannot_authorize_a_host_operation(self):
        operation = {"kind": "run", "paths": [], "command": "false"}
        provider = self.typed_provider([("turn/start", "initial", [typed_item("initial", operation, "final"),
            recovery.price("initial", 100), recovery.completed("initial")])])
        with self.assertRaisesRegex(Fatal, "no valid structured host operation"):
            provider.turn("thread", "Continue.", "author", host_request=True)
        self.assertFalse(provider.sent)
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertTrue(provider.report()["measurement_complete"])

    def test_late_final_in_terminal_drain_requires_owned_item_and_fresh_coverage(self):
        for variant in ("priced", "stale_price", "foreign_thread", "foreign_turn"):
            with self.subTest(variant=variant):
                final = typed_item("initial", {"kind": "run", "paths": [], "command": "true"})
                if variant == "foreign_thread":
                    final["params"]["threadId"] = "other-thread"
                elif variant == "foreign_turn":
                    final["params"]["turnId"] = "other-turn"
                events = [recovery.price("initial", 100), recovery.completed("initial"), final]
                if variant != "stale_price":
                    events.append(recovery.price("initial", 200))
                provider = self.typed_provider([("turn/start", "initial", events)])
                path = provider.artifacts / "native-session.jsonl"
                path.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": "thread", "cwd": str(provider.repo)}}) + "\n")
                provider.native_usage = {"thread": NativeUsage(path, "thread", provider.repo)}
                original = provider.incoming
                receipt_count = [0]

                def incoming(timeout, private_id=None):
                    event = original(timeout, private_id)
                    if event and event.get("method") == "thread/tokenUsage/updated":
                        receipt_count[0] += 1
                        count = receipt_count[0]
                        output = 10 if count == 1 else 0
                        payload = {"thread_id": "thread", "session_id": "thread", "turn_id": "initial",
                            "response_id": f"response-{count}",
                            "usage": {"input_tokens": 100, "output_tokens": output,
                                      "cached_input_tokens": 0, "total_tokens": 100 + output},
                            "thread_token_usage": {"input_tokens": 100 * count, "output_tokens": 10,
                                                   "cached_input_tokens": 0, "total_tokens": 100 * count + 10}}
                        with path.open("a") as handle:
                            handle.write(json.dumps({"type": "token_usage_record", "payload": payload}) + "\n")
                    return event

                provider.incoming = incoming
                if variant == "priced":
                    self.assertEqual(provider.turn("thread", "Continue.", "author", host_request=True),
                                     "@standalone run -- true")
                    self.assertEqual((provider.artifacts / "turn-0001/host-operation.txt").read_text(),
                                     "@standalone run -- true")
                    self.assertTrue(provider.report()["measurement_complete"])
                    self.assertEqual(provider.usage.raw, 210)
                else:
                    with self.assertRaises(Fatal):
                        provider.turn("thread", "Continue.", "author", host_request=True)
                    self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())
                    if variant == "stale_price":
                        self.assertFalse(provider.report()["measurement_complete"])
                        self.assertEqual(provider.usage.raw, 110)
                self.assertFalse(provider.sent, "the turn was already terminal")
                self.assertEqual(self.methods(provider), ["turn/start"])

    def test_late_typed_final_without_fresh_usage_cannot_publish_even_without_native_reader(self):
        final = typed_item("initial", {"kind": "done"})
        provider = self.typed_provider([("turn/start", "initial", [recovery.price("initial", 100),
            recovery.completed("initial"), final])])
        with self.assertRaisesRegex(Fatal, "incomplete"):
            provider.turn("thread", "Continue.", "author", host_request=True)
        self.assertEqual(provider.turns[0]["host_message_id"], "initial-item")
        self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 110)
        self.assertFalse(provider.sent)
        self.assertEqual(self.methods(provider), ["turn/start"])

    def test_policy_failure_with_valid_json_does_not_trigger_format_or_context_retry(self):
        provider = self.typed_provider([("turn/start", "initial", [
            typed_item("initial", {"kind": "done"}), recovery.price("initial", 100),
            recovery.completed("initial", "policyViolation")])])
        with self.assertRaises(Fatal):
            provider.turn("thread", "Continue.", "author", host_request=True)
        self.assertEqual(self.methods(provider), ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertEqual(provider.turns[0]["host_message_id"], "initial-item")
        self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())
        self.assertEqual(json.loads((provider.artifacts / "turn-0001/reply.txt").read_text()),
                         {"operation": {"kind": "done"}})

    def test_context_recovery_preserves_schema_and_permissions_but_compaction_is_unstructured(self):
        failed = ("turn/start", "initial", [typed_item("initial", {"kind": "run", "paths": [], "command": "false"}),
            recovery.completed("initial", "contextWindowExceeded"), recovery.price("initial", 100)])
        provider = self.typed_provider([failed, recovery.compaction(), typed_success("retry", tokens=300)])

        self.assertEqual(provider.turn("thread", "Original task.", "author", host_request=True, writable=True),
                         "@standalone run -- true")

        initial, compact, retried = [params for _, params in provider.requests]
        self.assertEqual(initial["outputSchema"], response_module().HOST_OUTPUT_SCHEMA)
        self.assertEqual(retried["outputSchema"], initial["outputSchema"])
        self.assertEqual(retried["sandboxPolicy"], initial["sandboxPolicy"])
        self.assertNotIn("outputSchema", compact)
        self.assertIn(recovery.RECOVERY_PROMPT, retried["input"][0]["text"])
        self.assertNotIn("Original task.", retried["input"][0]["text"])
        self.assertEqual(self.methods(provider), ["turn/start", "thread/compact/start", "turn/start"])
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 310)


if __name__ == "__main__":
    unittest.main()
