import json
import unittest

from lab.context import AUTO_COMPACT_TOKENS, CONTEXT_POLICY, OutputGuard, validate_compaction_tokens
from lab.host import MAX_FINAL_BYTES


class CompactionTests(unittest.TestCase):
    def test_positive_compaction_threshold_is_preserved(self):
        self.assertEqual(AUTO_COMPACT_TOKENS, 131072)
        for value in (32000, 131072, 200000):
            self.assertEqual(validate_compaction_tokens(value), value)

    def test_invalid_compaction_thresholds_are_rejected(self):
        for value in (None, 0, -1, True, False, "128000", 128000.0, {}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_compaction_tokens(value)

    def test_policy_is_serializable_and_message_limit_matches_host(self):
        self.assertEqual(json.loads(json.dumps(CONTEXT_POLICY)), CONTEXT_POLICY)
        self.assertEqual(CONTEXT_POLICY["max_agent_message_bytes"], MAX_FINAL_BYTES)
        self.assertEqual(CONTEXT_POLICY["auto_compact_tokens"], AUTO_COMPACT_TOKENS)
        self.assertEqual(CONTEXT_POLICY["version"], 6)
        self.assertEqual(CONTEXT_POLICY["max_repeated_character_chars"], 1024)


class OutputGuardTests(unittest.TestCase):
    def test_replacement_threshold_survives_chunk_boundaries(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "\ufffd" * 100))
        self.assertIsNone(guard.observe("a", " \n\ufffd" * 27))
        self.assertEqual(guard.observe("a", "\ufffd"), "replacement_character_flood")
        self.assertEqual(guard.observe("a", "Readable text"), "replacement_character_flood")

    def test_replacement_ratio_uses_sliding_window_and_exact_boundary(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "xy" * 1024))
        self.assertIsNone(guard.observe("a", "\ufffd" * 128 + " " * 1715))
        self.assertEqual(guard.observe("a", " "), "replacement_character_flood")

        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "x" * 15 + "\ufffd" * 128 + " " * 6))
        self.assertEqual(guard.observe("a", " "), "replacement_character_flood")

    def test_suspicious_run_inside_one_delta_cannot_be_hidden_by_safe_suffix(self):
        for payload, reason in (("\ufffd" * 128, "replacement_character_flood"),
                                (" " * 8192, "trailing_whitespace"),
                                ("A" * 1024, "repeated_character_flood")):
            with self.subTest(reason=reason):
                self.assertEqual(OutputGuard().observe("a", payload + "safe" * 2048), reason)

    def test_whitespace_threshold_spans_chunks_and_resets_on_text(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "prefix" + " \t\n\r" * 2047 + " \t\n"))
        self.assertEqual(guard.observe("a", "\u2003"), "trailing_whitespace")

        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", " " * 8191))
        self.assertIsNone(guard.observe("a", "x"))
        self.assertIsNone(guard.observe("a", " " * 8191))

    def test_repetition_threshold_counts_characters_across_chunk_boundaries(self):
        for char in ("A", "é", "🙂"):
            with self.subTest(char=char):
                guard = OutputGuard()
                self.assertIsNone(guard.observe("a", char * 1023))
                self.assertEqual(guard.observe("a", char), "repeated_character_flood")
                self.assertEqual(guard.observe("a", "ordinary text"), "repeated_character_flood")
                self.assertEqual(guard._items["a"].repeated_characters, 1024)
                self.assertEqual(guard._items["a"].last_character, char)
                self.assertLessEqual(len(guard._items["a"].window), 2048)

    def test_repetition_counter_resets_on_other_characters_and_whitespace(self):
        for separator in ("B", "é", "🙂", " ", "\t", "\n", "\u2003"):
            with self.subTest(separator=separator):
                guard = OutputGuard()
                self.assertIsNone(guard.observe("a", "A" * 1023))
                self.assertIsNone(guard.observe("a", separator))
                self.assertIsNone(guard.observe("a", "A" * 1023))
                self.assertEqual(guard.observe("a", "A"), "repeated_character_flood")

    def test_repetition_is_independent_per_item_and_finish_releases_it(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "A" * 1023))
        self.assertIsNone(guard.observe("b", "A"))
        self.assertIsNone(guard.finish("b", "A"))
        self.assertEqual(guard.observe("a", "A"), "repeated_character_flood")
        self.assertEqual(guard.finish("a", "A" * 1024), "repeated_character_flood")
        self.assertFalse(guard._items)
        self.assertIsNone(guard.observe("a", "A"))

    def test_interleaved_items_have_independent_state_and_finish_releases_it(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "\ufffd" * 127))
        self.assertIsNone(guard.observe("b", "\ufffd"))
        self.assertIsNone(guard.finish("b", "\ufffd"))
        self.assertEqual(guard.observe("a", "\ufffd"), "replacement_character_flood")
        self.assertEqual(guard.finish("a", "\ufffd" * 128), "replacement_character_flood")
        self.assertFalse(guard._items)
        self.assertIsNone(guard.observe("a", "A fresh item."))

    def test_large_code_unicode_and_replacement_literals_remain_valid(self):
        guard = OutputGuard()
        line = 'const replacement = "\ufffd"; // café Ελληνικά 日本語 🙂\n'
        text = line * 12000
        for index in range(0, len(text), 193):
            self.assertIsNone(guard.observe("code", text[index:index + 193]))
        self.assertLessEqual(len(guard._items["code"].window), 2048)
        self.assertIsNone(guard.finish("code", text))
        self.assertIsNone(OutputGuard().finish("a", "\ufffd" * 127 + " " * 1000))
        self.assertIsNone(OutputGuard().finish("b", "Readable code: " * 200 + "\ufffd" * 128))

    def test_completed_only_messages_receive_all_guards_even_after_empty_deltas(self):
        for text, reason in (("\ufffd" * 128, "replacement_character_flood"),
                             (" " * 8192, "trailing_whitespace"),
                             ("A" * 1024, "repeated_character_flood"),
                             ("x" * (MAX_FINAL_BYTES + 1), "agent_message_bytes")):
            with self.subTest(reason=reason):
                guard = OutputGuard()
                self.assertIsNone(guard.observe("a", ""))
                self.assertEqual(guard.finish("a", text), reason)
                self.assertFalse(guard._items)

    def test_byte_limit_counts_utf8_and_allows_exact_host_limit(self):
        guard = OutputGuard()
        text = "🙂🙃" * (MAX_FINAL_BYTES // 8)
        self.assertIsNone(guard.observe("a", text))
        self.assertEqual(guard.observe("a", "x"), "agent_message_bytes")
        self.assertIsNone(OutputGuard().finish("b", text))

    def test_completed_stream_is_not_counted_twice(self):
        guard = OutputGuard()
        text = "éè" * (MAX_FINAL_BYTES // 8 + 1)
        self.assertIsNone(guard.observe("a", text))
        self.assertIsNone(guard.finish("a", text))
        self.assertFalse(guard._items)

    def test_completed_text_is_checked_when_only_some_deltas_arrived(self):
        guard = OutputGuard()
        self.assertIsNone(guard.observe("a", "partial prefix"))
        self.assertEqual(guard.finish("a", "partial prefix" + "\ufffd\n" * 1024),
                         "replacement_character_flood")
        self.assertFalse(guard._items)


if __name__ == "__main__":
    unittest.main()
