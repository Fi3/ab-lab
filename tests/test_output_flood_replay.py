"""Replay the exact checkpoint-3 A flood without retaining its expanded text."""
import hashlib
import json
from pathlib import Path
import unittest

from lab.context import OutputGuard


FIXTURE = Path(__file__).with_name("fixtures") / "checkpoint3-output-flood.json"


class OutputFloodReplayTests(unittest.TestCase):
    def test_exact_retained_stream_triggers_soft_repetition_guard(self):
        fixture = json.loads(FIXTURE.read_text())
        source = fixture["provenance"]
        stream_hash, payload_hash = hashlib.sha256(), hashlib.sha256()
        guard = OutputGuard()
        reasons = set()
        count = size = 0
        for run in fixture["delta_runs"]:
            for _ in range(run["repeat"]):
                delta = run["delta"]
                row = {"item_id": fixture["item_id"], "delta": delta}
                stream_hash.update((json.dumps(row) + "\n").encode())
                payload_hash.update(delta.encode())
                count += 1
                size += len(delta.encode())
                reason = guard.observe(fixture["item_id"], delta)
                if reason:
                    reasons.add(reason)

        self.assertEqual(stream_hash.hexdigest(), source["source_sha256"])
        self.assertEqual(payload_hash.hexdigest(), source["payload_sha256"])
        self.assertEqual((count, size), (source["delta_count"], source["payload_bytes"]))
        self.assertEqual(reasons, {fixture["expected_guard"]})


if __name__ == "__main__":
    unittest.main()
