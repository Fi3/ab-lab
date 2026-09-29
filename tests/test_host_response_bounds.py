"""Bound constrained output before a runaway string requires cancellation."""
import json
import unittest

from lab.host import parse_operations
from lab import host_response as response
from lab.host import Fatal
import test_context_recovery as recovery
from test_host_response import typed_item, typed_success


class HostResponseBoundsTests(unittest.TestCase):
    def test_schema_bounds_every_free_string_and_array(self):
        def visit(schema):
            if schema.get("type") == "string" and "enum" not in schema:
                self.assertIsInstance(schema.get("maxLength"), int)
                self.assertGreater(schema["maxLength"], 0)
            if schema.get("type") == "array":
                self.assertIsInstance(schema.get("maxItems"), int)
                self.assertGreater(schema["maxItems"], 0)
                visit(schema["items"])
            for prop in schema.get("properties", {}).values():
                visit(prop)
            for branch in schema.get("anyOf", []):
                visit(branch)

        visit(response.HOST_OUTPUT_SCHEMA)

    def test_local_decoder_rejects_overlong_fields_and_path_arrays(self):
        for kind, fields in response._FIELDS.items():
            for name, schema in fields.items():
                if schema["type"] == "array":
                    invalid = [["a"] * (schema.get("maxItems", 16) + 1),
                               ["a" * (schema["items"].get("maxLength", 4096) + 1)]]
                else:
                    invalid = ["a" * (schema.get("maxLength", 32768) + 1)]
                for value in invalid:
                    operation = {"kind": kind, **{key: ([] if prop["type"] == "array" else "valid")
                                                 for key, prop in fields.items()}}
                    operation[name] = value
                    with self.subTest(kind=kind, field=name), self.assertRaisesRegex(ValueError, "limit"):
                        response.decode_host_response(json.dumps({"operation": operation}))

    def test_unicode_at_command_boundary_roundtrips_without_byte_truncation(self):
        limit = response._FIELDS["run"]["command"]["maxLength"]
        command = "echo " + ("é🙂ab" * limit)[:limit - 5]
        paths = [f"file-{i}.py" for i in range(response._FIELDS["run"]["paths"]["maxItems"])]
        result = response.decode_host_response(json.dumps({"operation": {
            "kind": "run", "paths": paths, "command": command}}))
        self.assertEqual(parse_operations(result), [("run", paths, command)])

    def test_patch_at_boundary_preserves_newlines(self):
        limit = response._FIELDS["edit"]["patch"]["maxLength"]
        prefix = "*** Begin Patch\n*** Add File: data.txt\n+"
        suffix = "\n*** End Patch"
        body = prefix + ("abcd" * limit)[:limit - len(prefix) - len(suffix)] + suffix
        result = response.decode_host_response(json.dumps({"operation": {
            "kind": "edit", "reason": "Add data", "patch": body}}))
        self.assertEqual(parse_operations(result), [("edit", "Add data", body)])


class BoundedFloodRecoveryTests(unittest.TestCase):
    provider = recovery.ContextRecoveryTests.provider

    def test_escaped_character_flood_requires_fresh_usage_before_recovery(self):
        for char in ("A", "🙂"):
            for fresh in (False, True):
                with self.subTest(char=char, fresh=fresh):
                    rejected = typed_item("initial", {
                        "kind": "run", "paths": [], "command": char * 2048})
                    # typed_item JSON-escapes non-ASCII text; force the same
                    # representation for ASCII A so neither raw JSON string
                    # contains 1,024 identical consecutive characters.
                    text = rejected["params"]["item"]["text"]
                    rejected["params"]["item"]["text"] = text.replace("A", "\\u0041")
                    stages = [("turn/start", "initial", [rejected,
                        recovery.price("initial", 100), recovery.completed("initial")])]
                    if fresh:
                        stages.extend([recovery.compaction(), typed_success("retry", tokens=300)])
                    provider = self.provider(stages)
                    provider.host_response_format = response.HOST_RESPONSE_FORMAT
                    if fresh:
                        result = provider.turn("thread", "Continue.", "author", host_request=True)
                        self.assertEqual(result, "@standalone run -- true")
                        self.assertEqual(provider.usage.raw, 310)
                        self.assertTrue(provider.report()["measurement_complete"])
                        self.assertEqual([method for method, _ in provider.requests],
                                         ["turn/start", "thread/compact/start", "turn/start"])
                    else:
                        provider.usage.observe_tokens("thread", 100, 10)
                        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
                            provider.turn("thread", "Continue.", "author", host_request=True)
                        self.assertFalse(provider.report()["measurement_complete"])
                        self.assertEqual([method for method, _ in provider.requests], ["turn/start"])
                    self.assertEqual(provider.turns[0]["error"], "repeated_character_flood")
                    self.assertEqual(provider.turns[0]["output_guard"]["reason"],
                                     "repeated_character_flood")
                    self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())

    def test_completed_bounded_flood_is_priced_quarantined_and_retried_once(self):
        rejected = typed_item("initial", {"kind": "run", "paths": [], "command": "A" * 8192})
        provider = self.provider([("turn/start", "initial", [rejected,
            recovery.price("initial", 100), recovery.completed("initial")]),
            recovery.compaction(), typed_success("retry", tokens=300)])
        provider.host_response_format = response.HOST_RESPONSE_FORMAT
        result = provider.turn("thread", "Continue the task.", "author", host_request=True)
        self.assertEqual(result, "@standalone run -- true")
        self.assertTrue(provider.report()["measurement_complete"])
        self.assertEqual(provider.usage.raw, 310)
        self.assertEqual(provider.turns[0]["error"], "repeated_character_flood")
        self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())
        self.assertEqual([method for method, _ in provider.requests],
                         ["turn/start", "thread/compact/start", "turn/start"])

    def test_bounded_flood_with_only_old_usage_still_cannot_authorize_recovery(self):
        rejected = typed_item("initial", {"kind": "run", "paths": [], "command": "A" * 8192})
        provider = self.provider([("turn/start", "initial", [rejected,
            recovery.price("initial", 100), recovery.completed("initial")])])
        provider.usage.observe_tokens("thread", 100, 10)
        provider.host_response_format = response.HOST_RESPONSE_FORMAT
        with self.assertRaisesRegex(Fatal, "incomplete token measurement"):
            provider.turn("thread", "Continue the task.", "author", host_request=True)
        self.assertEqual([method for method, _ in provider.requests], ["turn/start"])
        self.assertFalse(provider.report()["measurement_complete"])
        self.assertFalse((provider.artifacts / "turn-0001/host-operation.txt").exists())


if __name__ == "__main__":
    unittest.main()
