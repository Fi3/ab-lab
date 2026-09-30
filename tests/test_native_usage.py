import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lab.native_usage import NativeUsage


def tokens(input_tokens, output_tokens, cached=0):
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "cached_input_tokens": cached, "total_tokens": input_tokens + output_tokens}


def receipt(response="response-1", turn="turn-1", usage=None, total=None):
    usage = tokens(100, 10, 50) if usage is None else usage
    return {"thread_id": "owned", "session_id": "owned", "turn_id": turn,
            "response_id": response, "usage": usage,
            "thread_token_usage": usage if total is None else total}


class NativeUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.path = self.cwd / "owned.jsonl"
        self.reader = NativeUsage(self.path, "owned", self.cwd)
        self.append("session_meta", {"id": "owned", "cwd": str(self.cwd)})

    def append(self, kind, payload):
        with self.path.open("ab") as f:
            f.write((json.dumps({"type": kind, "payload": payload}) + "\n").encode())

    def test_deduplicates_embedded_compaction_receipt_and_retains_provenance(self):
        r = receipt()
        self.append("token_usage_record", r)
        self.append("compacted", {"compaction_response_id": "response-1",
                                  "latest_token_usage_record": r})
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertEqual(self.reader.totals, (100, 10, 50))
        self.assertEqual(len(self.reader.completed_compactions("turn-1")), 1)
        self.assertFalse(self.reader.completed_compactions("other"))
        report = self.reader.report()
        self.assertEqual(report["complete_prefix_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(report["complete_bytes"], self.path.stat().st_size)
        self.assertEqual([s["line"] for s in report["responses"][0]["sources"]], [2, 3])
        self.assertEqual(report["responses"][0]["payload"], r)
        self.assertEqual(self.reader.refresh(), [])
        self.assertFalse(self.reader.errors)

    def test_compaction_receipt_then_normal_response_uses_true_cumulative_totals(self):
        self.append("compacted", {"compaction_response_id": "response-1",
                                  "latest_token_usage_record": receipt(total=tokens(1000, 200, 800))})
        self.append("token_usage_record", receipt("response-2", "turn-2", tokens(50, 5, 20), tokens(1050, 205, 820)))
        self.reader.refresh()
        self.assertEqual(self.reader.totals, (1050, 205, 820))
        self.assertFalse(self.reader.errors)

    def test_partial_final_line_is_not_parsed_or_hashed_until_completed(self):
        raw = json.dumps({"type": "token_usage_record", "payload": receipt()}).encode()
        before = self.path.read_bytes()
        with self.path.open("ab") as f:
            f.write(raw[:30])
        self.assertEqual(self.reader.refresh(), [])
        self.assertEqual(self.reader.offset, len(before))
        self.assertIsNone(self.reader.totals)
        with self.path.open("ab") as f:
            f.write(raw[30:] + b"\n")
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertFalse(self.reader.errors)

    def test_missing_receipt_is_pending_until_correlated_record_arrives(self):
        self.append("compacted", {"compaction_response_id": "response-1"})
        self.reader.refresh()
        self.assertEqual(self.reader.missing_compactions, {"response-1"})
        self.assertFalse(self.reader.completed_compactions("turn-1"))
        self.append("token_usage_record", receipt())
        self.reader.refresh()
        self.assertFalse(self.reader.missing_compactions)
        self.assertEqual(len(self.reader.completed_compactions("turn-1")), 1)

    def test_duplicate_dedicated_receipt_is_charged_once(self):
        self.append("token_usage_record", receipt())
        self.append("token_usage_record", receipt())
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertEqual(self.reader.totals, (100, 10, 50))
        self.assertFalse(self.reader.errors)

    def test_conflicting_duplicate_is_rejected(self):
        self.append("token_usage_record", receipt())
        self.append("token_usage_record", receipt(usage=tokens(101, 10, 50)))
        self.reader.refresh()
        self.assertIn("conflicting duplicate", self.reader.errors[0])
        self.assertEqual(self.reader.totals, (100, 10, 50))

    def test_foreign_session_workspace_and_usage_are_rejected(self):
        cases = [
            ("session_meta", {"id": "foreign", "cwd": str(self.cwd)}),
            ("session_meta", {"id": "owned", "cwd": str(self.cwd / "other")}),
            ("session_meta", {"id": "owned", "session_id": "foreign", "cwd": str(self.cwd)}),
            ("token_usage_record", {**receipt(), "thread_id": "foreign"}),
            ("token_usage_record", {**receipt(), "session_id": "foreign"}),
        ]
        for kind, payload in cases:
            with self.subTest(kind=kind, payload=payload):
                self.path.write_text("")
                self.append("session_meta", {"id": "owned", "cwd": str(self.cwd)})
                self.append(kind, payload)
                reader = NativeUsage(self.path, "owned", self.cwd)
                reader.refresh()
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)

    def test_invalid_numeric_fields_and_identity_are_rejected(self):
        invalid = [None, True, -1, 0.5, "100"]
        cases = []
        for field in ("input_tokens", "output_tokens", "cached_input_tokens"):
            for value in invalid:
                r = receipt()
                r["usage"] = {**r["usage"], field: value}
                cases.append(r)
        cases.extend([receipt(usage=tokens(100, 10, 101)), receipt(usage=tokens(0, 0)),
                      receipt(response=""), receipt(turn=""),
                      {**receipt(), "thread_token_usage": None},
                      receipt(usage={**tokens(100, 10), "total_tokens": 999})])
        for r in cases:
            with self.subTest(receipt=r):
                self.path.write_text("")
                self.append("session_meta", {"id": "owned", "cwd": str(self.cwd)})
                self.append("token_usage_record", r)
                reader = NativeUsage(self.path, "owned", self.cwd)
                reader.refresh()
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)

    def test_cumulative_counters_must_cover_new_unique_responses(self):
        self.append("token_usage_record", receipt())
        self.append("token_usage_record", receipt("response-2", usage=tokens(20, 2), total=tokens(110, 12, 50)))
        self.reader.refresh()
        self.assertTrue(self.reader.errors)
        self.assertEqual(self.reader.totals, (100, 10, 50))

    def test_compaction_marker_must_match_embedded_response(self):
        self.append("compacted", {"compaction_response_id": "other", "latest_token_usage_record": receipt()})
        self.reader.refresh()
        self.assertTrue(self.reader.errors)
        self.assertIsNone(self.reader.totals)

    def test_missing_path_can_arrive_later_but_existing_file_cannot_disappear(self):
        path = self.cwd / "delayed.jsonl"
        reader = NativeUsage(path, "owned", self.cwd)
        self.assertEqual(reader.refresh(), [])
        self.assertFalse(reader.errors)
        path.write_bytes(self.path.read_bytes())
        reader.refresh()
        self.assertTrue(reader.validated)
        path.unlink()
        reader.refresh()
        self.assertTrue(reader.errors)

    def test_truncated_or_replaced_source_is_rejected(self):
        self.reader.refresh()
        self.path.write_bytes(b"")
        self.reader.refresh()
        self.assertIn("truncated", self.reader.errors[0])

    def test_replaced_inode_is_rejected_even_when_bytes_are_identical(self):
        self.reader.refresh()
        replacement = self.cwd / "replacement.jsonl"
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        self.reader.refresh()
        self.assertIn("replaced", self.reader.errors[0])

    def test_malformed_complete_line_and_unvalidated_usage_fail_closed(self):
        for raw in (b"{not json}\n", b"\xff\n", b"[]\n",
                    (json.dumps({"type": "token_usage_record", "payload": receipt()}) + "\n").encode()):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                reader = NativeUsage(self.path, "owned", self.cwd)
                reader.refresh()
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)


class NativeChildUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.path = self.cwd / "child.jsonl"
        self.reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")

    def append(self, kind, payload):
        with self.path.open("ab") as f:
            f.write((json.dumps({"type": kind, "payload": payload}) + "\n").encode())

    def metadata(self, inherited=1, **changes):
        return {"id": "owned", "session_id": "parent", "cwd": str(self.cwd),
                "parent_thread_id": "parent", "forked_from_id": "parent",
                "subagent_history_start_ordinal": inherited, **changes}

    def prefix(self, records=()):
        self.append("session_meta", self.metadata(1 + len(records)))
        self.append("session_meta", {"id": "parent", "cwd": str(self.cwd)})
        for kind, payload in records:
            self.append(kind, payload)

    def own_receipt(self, **changes):
        return {**receipt(**changes), "session_id": "parent"}

    def context(self, turn="turn-1", **changes):
        return {"turn_id": turn, "cwd": str(self.cwd), "model": "admitted-model",
                "effort": "xhigh", **changes}

    def test_inherited_parent_receipts_contexts_plans_and_compactions_are_ignored(self):
        inherited = {**receipt(turn="parent-turn", total=tokens(9999, 999, 9000)),
                     "thread_id": "parent", "session_id": "parent"}
        self.prefix([
            ("turn_context", self.context("parent-turn", model="parent-model")),
            ("token_usage_record", inherited),
            ("compacted", {"compaction_response_id": "response-1", "latest_token_usage_record": inherited}),
            ("compacted", {"compaction_response_id": "missing-parent-receipt"}),
            ("event_msg", {"type": "token_count", "info": None, "rate_limits": {"plan_type": "api"}}),
        ])
        self.append("turn_context", self.context())
        own = self.own_receipt()
        self.append("token_usage_record", own)
        self.append("token_usage_record", own)
        self.append("compacted", {"compaction_response_id": "response-1", "latest_token_usage_record": own})
        self.append("event_msg", {"type": "token_count", "info": None, "rate_limits": {"plan_type": "pro"}})
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertTrue(self.reader.validated)
        self.assertEqual(self.reader.totals, (100, 10, 50))
        self.assertEqual(self.reader.turn_contexts, {"turn-1": {"model": "admitted-model", "effort": "xhigh"}})
        self.assertEqual(self.reader.plans, {"pro"})
        self.assertEqual(len(self.reader.completed_compactions("turn-1")), 1)
        self.assertFalse(self.reader.missing_compactions)
        self.assertFalse(self.reader.errors)
        report = self.reader.report()
        self.assertEqual(report["parent_thread_id"], "parent")
        self.assertEqual(report["session_id"], "parent")
        self.assertEqual(report["own_start_line"], 8)
        self.assertEqual(report["complete_prefix_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual([s["line"] for s in report["responses"][0]["sources"]], [9, 10, 11])

    def test_incomplete_inherited_prefix_waits_and_resume_counts_only_new_receipts(self):
        self.append("session_meta", self.metadata(2))
        self.append("session_meta", {"id": "parent", "cwd": str(self.cwd)})
        self.assertEqual(self.reader.refresh(), [])
        self.assertFalse(self.reader.validated)
        self.append("turn_context", self.context("parent-turn"))
        self.append("turn_context", self.context())
        self.append("token_usage_record", self.own_receipt())
        self.assertEqual(len(self.reader.refresh()), 1)
        self.append("event_msg", {"type": "task_complete", "turn_id": "turn-1"})
        self.append("turn_context", self.context("turn-2"))
        self.append("token_usage_record", self.own_receipt(
            response="response-2", turn="turn-2", usage=tokens(50, 5), total=tokens(150, 15, 50)))
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertEqual(self.reader.refresh(), [])
        self.assertEqual(self.reader.totals, (150, 15, 50))
        self.assertEqual(set(self.reader.turn_contexts), {"turn-1", "turn-2"})
        self.assertFalse(self.reader.errors)

    def test_nested_ancestry_keeps_root_session_identity_without_charging_ancestors(self):
        self.append("session_meta", self.metadata(4, session_id="root"))
        self.append("session_meta", self.metadata(2, id="parent", session_id="root",
                                                  parent_thread_id="root", forked_from_id="root"))
        self.append("session_meta", {"id": "root", "session_id": "root", "cwd": str(self.cwd)})
        for ancestor in ("root", "parent"):
            self.append("token_usage_record", {**receipt(turn=ancestor + "-turn"),
                                                "thread_id": ancestor, "session_id": "root"})
        self.append("token_usage_record", {**receipt(), "session_id": "root"})
        self.assertEqual(len(self.reader.refresh()), 1)
        self.assertEqual(self.reader.totals, (100, 10, 50))
        self.assertEqual(self.reader.session_id, "root")
        self.assertFalse(self.reader.errors)

    def test_missing_invalid_or_inconsistent_fork_identity_fails_closed(self):
        cases = [
            {"subagent_history_start_ordinal": value} for value in (None, True, -1, 0, 1.5, "1")
        ] + [
            {"id": "foreign"}, {"parent_thread_id": "foreign"},
            {"forked_from_id": "foreign"}, {"session_id": "foreign"},
            {"cwd": str(self.cwd / "other")},
            {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "foreign"}}}},
            {"source": {"subagent": []}},
            {"source": "vscode"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.path.write_text("")
                self.append("session_meta", self.metadata(**changes))
                self.append("session_meta", {"id": "parent", "cwd": str(self.cwd)})
                self.append("token_usage_record", self.own_receipt())
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(reader.refresh(), [])
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)

    def test_foreign_or_owned_receipts_cannot_hide_in_inherited_prefix(self):
        for thread, session in (("foreign", "parent"), ("owned", "parent"),
                                ("parent", "foreign"), ([], "parent")):
            for kind in ("token_usage_record", "compacted"):
                with self.subTest(thread=thread, session=session, kind=kind):
                    self.path.write_text("")
                    r = {**receipt(), "thread_id": thread, "session_id": session}
                    payload = r if kind == "token_usage_record" else {
                        "compaction_response_id": r["response_id"], "latest_token_usage_record": r}
                    self.prefix([(kind, payload)])
                    reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                    self.assertEqual(reader.refresh(), [])
                    self.assertTrue(reader.errors)
                    self.assertIsNone(reader.totals)

    def test_ancestor_evidence_after_boundary_is_rejected(self):
        cases = [
            ("session_meta", {"id": "parent", "cwd": str(self.cwd)}),
            ("token_usage_record", {**receipt(), "thread_id": "parent", "session_id": "parent"}),
            ("token_usage_record", {**receipt(), "session_id": "foreign"}),
            ("token_usage_record", self.own_receipt(turn="parent-turn")),
            ("turn_context", self.context("parent-turn")),
            ("turn_context", self.context(thread_id="parent")),
            ("session_meta", self.metadata(50)),
        ]
        for kind, payload in cases:
            with self.subTest(kind=kind, payload=payload):
                self.path.write_text("")
                self.prefix([("turn_context", self.context("parent-turn"))])
                self.append(kind, payload)
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(reader.refresh(), [])
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)

    def test_prefix_must_begin_with_exact_parent_and_finish_its_ancestry(self):
        for payload in ({"id": "foreign", "cwd": str(self.cwd)},
                        self.metadata(1, id="parent", session_id="root", parent_thread_id="root", forked_from_id="root")):
            with self.subTest(payload=payload):
                self.path.write_text("")
                self.append("session_meta", self.metadata(session_id=payload.get("session_id", "parent")))
                self.append("session_meta", payload)
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(reader.refresh(), [])
                self.assertTrue(reader.errors)
                self.assertFalse(reader.validated)

    def test_missing_boundary_or_metadata_cannot_be_inferred_from_usage(self):
        for metadata in (None, {key: value for key, value in self.metadata().items()
                                if key != "subagent_history_start_ordinal"}):
            with self.subTest(metadata=metadata):
                self.path.write_text("")
                if metadata:
                    self.append("session_meta", metadata)
                self.append("token_usage_record", self.own_receipt())
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(reader.refresh(), [])
                self.assertTrue(reader.errors)
                self.assertIsNone(reader.totals)

    def test_own_turn_context_requires_stable_model_effort_and_workspace(self):
        for context in (self.context(model=None), self.context(effort="other"),
                        self.context(cwd=str(self.cwd / "foreign")),
                        self.context(session_id="foreign")):
            with self.subTest(context=context):
                self.path.write_text("")
                self.prefix()
                self.append("turn_context", self.context())
                self.append("turn_context", context)
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(reader.refresh(), [])
                self.assertTrue(reader.errors)

    def test_own_receipts_retain_numeric_and_duplicate_validation(self):
        cases = [self.own_receipt(usage=tokens(101, 10, 50)),
                 self.own_receipt(response="response-2", total=tokens(100, 10, 50)),
                 self.own_receipt(response="response-2", usage=tokens(-1, 10))]
        for r in cases:
            with self.subTest(receipt=r):
                self.path.write_text("")
                self.prefix()
                self.append("token_usage_record", self.own_receipt())
                self.append("token_usage_record", r)
                reader = NativeUsage(self.path, "owned", self.cwd, parent_thread_id="parent")
                self.assertEqual(len(reader.refresh()), 1)
                self.assertTrue(reader.errors)
                self.assertEqual(reader.totals, (100, 10, 50))


if __name__ == "__main__":
    unittest.main()
