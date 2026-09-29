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


if __name__ == "__main__":
    unittest.main()
