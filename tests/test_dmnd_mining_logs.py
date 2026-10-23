"""A green test footer cannot hide missing mining evidence or runtime errors."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.dmnd_mining_logs import POOL_TEST, REJECTIONS, SCENARIOS, TESTS, TP_SHA256, validate_mining


def write_json(path, data):
    path.write_text(json.dumps(data))


def write_journal(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class MiningEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stdout = ("running 18 tests\n" + "".join(f"test {name} ... ok\n" for name in TESTS)
                       + "test result: ok. 18 passed; 0 failed; 0 ignored; 0 measured; "
                       "0 filtered out; finished in 1.00s\n")
        for name in SCENARIOS:
            self.scenario(name)

    def scenario(self, name):
        folder = self.folder(name)
        folder.mkdir()
        miners = 0 if name == "invalid_token" else 2 if name == "multiple_miners" else 1
        write_json(folder / "configuration.json", {
            "miner_count": miners, "jd": name in ("jd_mining", "reject_next_declaration")})
        for process in ("tp", "proxy", *(f"miner-{i}" for i in range(miners))):
            (folder / f"{process}.log").write_text("INFO process ready\n")
            write_json(folder / f"{process}-process.json", {
                "binary": {"sha256": "a" * 64}, "args": [], "env": {}, "cwd": "/workspace"})
        pools = []
        for index in range(2 if name == "two_pool_endpoints" else 1):
            events = ([{"Connected": {"peer": index}}] if name == "invalid_token"
                      else [{"ShareAccepted": {"key": {"peer": index}, "nonce": nonce}}
                            for nonce in range(3)])
            if name in REJECTIONS and name != "new_chain_tip":
                events.extend({kind: {"reason": reason}} for kind, reason in REJECTIONS[name])
            rows = [{"sequence": i + 1, "event": event} for i, event in enumerate(events)]
            pools.append({"accepted": sum("ShareAccepted" in event for event in events),
                          "rejected": sum("ShareRejected" in event for event in events),
                          "channels": [], "peers": [index], "events": rows})
            write_journal(folder / f"pool-{index}-events.jsonl", rows)
        self.save_pools(name, pools)
        if name == "unknown_sv1_job":
            write_json(folder / "sv1-negative.json", {"boundary": "proxy", "response": {"result": False}})
        elif name == "duplicate_sv1_share":
            write_json(folder / "duplicate-sv1.json", {"first": {"result": True}, "rejection": {
                "event": {"ShareRejected": {"reason": "duplicate-share"}}}})
        elif name == "malformed_sv1_submit":
            write_json(folder / "malformed-sv1.json", {"disconnect": "peer disconnected"})
        elif name == "new_chain_tip":
            write_json(folder / "tip-block.json", {"header": {}})
            write_json(folder / "stale-sv1.json", {"boundary": "proxy-sv1", "response": {"result": False},
                                                    "fresh_notify": {}})

    def folder(self, name="non_jd_mining"):
        return self.root / (name + "-abc123")

    def save_pools(self, name, pools):
        write_json(self.folder(name) / "summary.json", {"status": "passed", "error": None, "pools": pools,
            "accepted": sum(pool["accepted"] for pool in pools), "rejected": sum(pool["rejected"] for pool in pools)})
        write_journal(self.folder(name) / "events.jsonl", [
            {"pool": index, **row} for index, pool in enumerate(pools) for row in pool["events"]])

    def validate(self, stdout=None, stderr=""):
        return validate_mining(self.root, self.stdout if stdout is None else stdout, stderr)

    def block_scenario(self):
        name = "jd_mining"
        folder = self.folder(name)
        block_hash = "00000000" + "01" * 28
        previous = [17] * 32
        message = ("unsupported JD message: SubmitSolution(SubmitSolutionJd { extranonce: Owned("
                   + str([0] * 32) + "), prev_hash: Owned(" + str(previous)
                   + "), ntime: 100, nonce: 7, nbits: 486604799, version: 536870912 })")
        events = [{"TipChanged": {"prev_hash": previous}}, {"ShareAccepted": {}},
                  {"Error": {"source": "pool", "message": message}},
                  {"TipChanged": {"prev_hash": list(bytes.fromhex(block_hash)[::-1])}},
                  {"ShareAccepted": {}}]
        rows = [{"sequence": index + 1, "event": event} for index, event in enumerate(events)]
        pools = [{"events": rows, "accepted": 2, "rejected": 0, "channels": [], "peers": [1]}]
        self.save_pools(name, pools)
        write_journal(folder / "pool-0-events.jsonl", rows)
        proxy = ("2026-10-19T00:00:00.000Z DEBUG roles_logic_sv2::channel_logic::channel_factory: "
                 "Checking target for share Extended(SubmitSharesExtended { channel_id: 1, sequence_number: 0, "
                 "job_id: 1, nonce: 7, ntime: 100, version: 536870912, extranonce: Owned("
                 + str([0] * 28) + ") })\n"
                 "2026-10-19T00:00:00.001Z DEBUG roles_logic_sv2::channel_logic::channel_factory: "
                 "Bitcoin target : 00000000ffff0000000000000000000000000000000000000000000000000000\n"
                 "2026-10-19T00:00:00.002Z INFO roles_logic_sv2::channel_logic::channel_factory: "
                 "Share hash meet bitcoin target: " + block_hash + "\n")
        tp = ("2026-10-19T00:00:00.000Z INFO tp_simulator: tp-simulator started initial_height=288\n"
              "2026-10-19T00:00:00.009Z ERROR roles_logic_sv2::parsers: Invalid message type: 118\n"
              "2026-10-19T00:00:00.010Z INFO tp_simulator: Accepted Sv2SubmitSolution block "
              "at height 289 and activated template 2\n")
        (folder / "proxy.log").write_text(proxy)
        (folder / "tp.log").write_text(tp)
        process_path = folder / "tp-process.json"
        process = json.loads(process_path.read_text())
        process["binary"]["sha256"] = TP_SHA256
        write_json(process_path, process)
        return folder, pools, proxy, tp, block_hash

    def test_complete_suite_and_evidence_pass(self):
        result = self.validate()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["scenarios"], list(SCENARIOS))
        self.assertTrue(result["expected_diagnostics"])

    def test_valid_block_notice_needs_tp_acceptance_and_matching_later_tip(self):
        self.block_scenario()
        result = self.validate()
        self.assertTrue(result["passed"], result)
        self.assertTrue(any(item.get("block_hash") for item in result["expected_diagnostics"]))
        for mutation in ("nonce", "hash", "tip", "receipt", "height", "early_receipt", "pin"):
            with self.subTest(mutation=mutation):
                folder, pools, proxy, tp, block_hash = self.block_scenario()
                if mutation == "nonce":
                    proxy = proxy.replace("nonce: 7,", "nonce: 8,")
                elif mutation == "hash":
                    proxy = proxy.replace(block_hash, "00000000" + "02" * 28)
                elif mutation == "tip":
                    pools[0]["events"][3]["event"]["TipChanged"]["prev_hash"][0] ^= 1
                    self.save_pools("jd_mining", pools)
                    write_journal(folder / "pool-0-events.jsonl", pools[0]["events"])
                elif mutation == "receipt":
                    tp = "\n".join(tp.splitlines()[:-1]) + "\n"
                elif mutation == "height":
                    tp = tp.replace("height 289", "height 290")
                elif mutation == "early_receipt":
                    tp = tp.replace("00:00:00.010Z", "00:00:00.001Z")
                elif mutation == "pin":
                    process = json.loads((folder / "tp-process.json").read_text())
                    process["binary"]["sha256"] = "b" * 64
                    write_json(folder / "tp-process.json", process)
                (folder / "proxy.log").write_text(proxy)
                (folder / "tp.log").write_text(tp)
                self.assertFalse(self.validate()["passed"])

    def test_green_footer_does_not_replace_individual_test_results(self):
        for stdout in (self.stdout.replace(f"test {POOL_TEST} ... ok\n", ""),
                       self.stdout.replace("non_jd_mining ... ok", "non_jd_mining ... ignored"),
                       self.stdout + "test non_jd_mining ... ok\n",
                       self.stdout.replace("0 filtered out", "1 filtered out")):
            with self.subTest(stdout=stdout[-100:]):
                self.assertFalse(self.validate(stdout)["passed"])

    def test_missing_or_repeated_scenario_cannot_pass(self):
        folder = self.folder()
        folder.rename(self.root / "unrecognized-abc")
        result = self.validate()
        self.assertFalse(result["passed"])
        self.assertIn("missing scenario artifacts: non_jd_mining", result["errors"])
        (self.root / "unrecognized-abc").rename(folder)
        (self.root / "non_jd_mining-extra").mkdir()
        self.assertFalse(self.validate()["passed"])

    def test_missing_empty_or_symlinked_runtime_log_fails(self):
        log = self.folder() / "proxy.log"
        original = log.read_text()
        log.unlink()
        self.assertFalse(self.validate()["passed"])
        log.write_text("")
        self.assertFalse(self.validate()["passed"])
        log.unlink()
        target = self.root / "outside.log"
        target.write_text(original)
        log.symlink_to(target)
        self.assertFalse(self.validate()["passed"])

    def test_panics_and_errors_fail_even_when_every_summary_passes(self):
        for name, line in (("proxy.log", "thread 'worker' panicked at src/lib.rs:10: bad state"),
                           ("tp.log", "\x1b[31mERROR\x1b[0m roles_logic_sv2::parsers: Invalid message type: 112"),
                           ("miner-0.log", "ERROR unexpected transport error")):
            with self.subTest(name=name):
                path = self.folder() / name
                original = path.read_text()
                path.write_text(original + line + "\n")
                result = self.validate()
                self.assertFalse(result["passed"], result)
                self.assertTrue(any(name in error for error in result["errors"]))
                path.write_text(original)
        self.assertFalse(self.validate(stderr="thread 'worker' panicked at test.rs:3")["passed"])

    def test_expected_rejection_log_is_limited_to_its_scenario_and_process(self):
        line = ("2026-10-19T00:00:00Z ERROR dmnd_client::translator::upstream::upstream: "
                "Pool rejected share with error code forced-rejection\n")
        path = self.folder("reject_next_submit") / "proxy.log"
        path.write_text(line)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        self.assertTrue(any("location" in item for item in result["expected_diagnostics"]))
        (self.folder() / "proxy.log").write_text(line)
        self.assertFalse(self.validate()["passed"])
        (self.folder() / "proxy.log").write_text("INFO error_present=false; 0 errors\n")
        (self.folder("reject_next_submit") / "tp.log").write_text(line)
        self.assertFalse(self.validate()["passed"])

    def test_target_rejection_needs_matching_transition_and_bounded_logs(self):
        channel = {"peer": 1, "channel": 1}
        events = [
            {"ShareAccepted": {"key": {**channel, "job": 1}, "sequence_number": 0,
                               "target": [0] * 27 + [255, 255, 15, 0, 0]}},
            {"TargetChanged": {"channel": channel, "target": [0] * 27 + [255, 255, 7, 0, 0]}},
            {"ShareRejected": {"channel": channel, "job_id": 1, "sequence_number": 1,
                               "reason": "difficulty-too-low"}},
            {"ShareAccepted": {"key": {**channel, "job": 1}, "sequence_number": 2,
                               "target": [0] * 27 + [255, 255, 7, 0, 0]}},
        ]
        logs = ("ERROR roles_logic_sv2::handlers::mining: Received SubmitSharesError with error code difficulty-too-low\n"
                "ERROR dmnd_client::translator::upstream::upstream: Pool rejected share with error code difficulty-too-low\n")
        for mutation in (None, "before", "after", "channel", "job", "target", "sequence", "logs", "orphan_logs"):
            with self.subTest(mutation=mutation):
                modified = copy.deepcopy(events)
                if mutation == "before":
                    modified[1], modified[2] = modified[2], modified[1]
                elif mutation == "after":
                    modified[2], modified[3] = modified[3], modified[2]
                elif mutation == "channel":
                    modified[2]["ShareRejected"]["channel"] = {"peer": 2, "channel": 1}
                elif mutation == "job":
                    modified[2]["ShareRejected"]["job_id"] = 2
                elif mutation == "target":
                    modified[3]["ShareAccepted"]["target"][29] = 15
                elif mutation == "sequence":
                    modified[2]["ShareRejected"]["sequence_number"] = 3
                elif mutation == "orphan_logs":
                    modified.pop(2)
                rows = [{"sequence": index + 1, "event": event} for index, event in enumerate(modified)]
                pools = [{"events": rows, "accepted": 2, "rejected": int(mutation != "orphan_logs"),
                          "channels": [], "peers": [1]}]
                self.save_pools("target_change", pools)
                folder = self.folder("target_change")
                write_journal(folder / "pool-0-events.jsonl", rows)
                (folder / "proxy.log").write_text(logs * (2 if mutation == "logs" else 1))
                result = self.validate()
                self.assertEqual(result["passed"], mutation is None, result)

    def test_expected_error_text_does_not_allow_an_extra_failure(self):
        path = self.folder("reject_next_submit") / "proxy.log"
        path.write_text("ERROR dmnd_client::translator::upstream::upstream: "
                        "Pool rejected share with error code forced-rejection; unexpected failure\n")
        self.assertFalse(self.validate()["passed"])

    def test_tp_dispatch_diagnostic_needs_pinned_binary_and_complete_evidence(self):
        folder = self.folder()
        (folder / "tp.log").write_text("ERROR roles_logic_sv2::parsers: Invalid message type: 112\n")
        self.assertFalse(self.validate()["passed"])
        process_path = folder / "tp-process.json"
        process = json.loads(process_path.read_text())
        process["binary"]["sha256"] = TP_SHA256
        write_json(process_path, process)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        (folder / "tp.log").write_text("ERROR roles_logic_sv2::parsers: Invalid message type: 116\n")
        self.assertFalse(self.validate()["passed"])
        (folder / "tp.log").write_text("ERROR roles_logic_sv2::parsers: Invalid message type: 112\n")
        (folder / "events.jsonl").write_text("")
        self.assertFalse(self.validate()["passed"])

    def test_known_connection_closes_have_bounded_counts(self):
        folder = self.folder()
        ingress = "ERROR dmnd_client::ingress::sv1_ingress: Upstream dropped trying to receive\n"
        (folder / "proxy.log").write_text(ingress * 2)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        (folder / "proxy.log").write_text(ingress * 3)
        self.assertFalse(self.validate()["passed"])
        (folder / "proxy.log").write_text(ingress)
        process_path = folder / "tp-process.json"
        process = json.loads(process_path.read_text())
        process["binary"]["sha256"] = TP_SHA256
        write_json(process_path, process)
        eof = ("ERROR demand_sv2_connection::noise_connection_tokio: Disconnected from client "
               "while reading : early eof - 127.0.0.1:12345\n")
        (folder / "tp.log").write_text(eof)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        (folder / "tp.log").write_text(eof * 2)
        self.assertFalse(self.validate()["passed"])

    def test_uninitialized_jd_probe_eof_requires_exact_peer_sequence(self):
        name = "two_pool_endpoints"
        folder = self.folder(name)
        pools = json.loads((folder / "summary.json").read_text())["pools"]
        events = [
            {"Connected": {"peer": 1}},
            {"ChannelOpened": {"channel": {"peer": 1, "channel": 1}}},
            {"Disconnected": {"peer": 1}},
            {"Error": {"source": "peer 2", "message": "early eof"}},
            {"Connected": {"peer": 3}},
            {"ShareAccepted": {"key": {"peer": 3}}},
            {"ShareAccepted": {"key": {"peer": 3}}},
        ]
        rows = [{"sequence": i + 1, "event": event} for i, event in enumerate(events)]
        pools[0].update(events=rows, accepted=2)
        self.save_pools(name, pools)
        write_journal(folder / "pool-0-events.jsonl", rows)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        self.assertTrue(any(item.get("reason") == "uninitialized JD probe closed"
                            for item in result["expected_diagnostics"]))
        # The same EOF on an established peer is never a known probe close.
        rows[0]["event"]["Connected"]["peer"] = 2
        self.save_pools(name, pools)
        write_journal(folder / "pool-0-events.jsonl", rows)
        self.assertFalse(self.validate()["passed"])

    def test_exact_malformed_request_diagnostic_is_expected(self):
        line = ('ERROR dmnd_client::translator::downstream::downstream: Downstream 3: rejected invalid '
                'mining.submit without disconnecting downstream: failed to parse mining.submit '
                'after InvalidSubmission: WrongArgs(Array [String("malformed-worker")])\n')
        path = self.folder("malformed_sv1_submit") / "proxy.log"
        path.write_text(line)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        path.write_text(line.replace("malformed-worker", "unexpected-worker"))
        self.assertFalse(self.validate()["passed"])

    def test_forced_declaration_rejection_keeps_exact_protocol_reason(self):
        message = ("ERROR dmnd_client::jd_client::job_declarator: Job is not verified: "
                   "DeclareMiningJobError { request_id: 5, error_code: Owned("
                   + str(list(b"invalid-mining-job-token")) + "), error_details: Owned([]) }\n")
        path = self.folder("reject_next_declaration") / "proxy.log"
        path.write_text(message)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        path.write_text(message.replace("Owned([])", "Owned([1])"))
        self.assertFalse(self.validate()["passed"])

    def test_error_after_snapshot_in_journal_is_not_hidden(self):
        path = self.folder() / "pool-0-events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows.append({"sequence": len(rows) + 1, "event": {"Error": {
            "source": "task", "message": "worker panicked"}}})
        write_journal(path, rows)
        result = self.validate()
        self.assertFalse(result["passed"], result)
        self.assertTrue(any("pool error" in error for error in result["errors"]))

    def test_clean_journal_tail_and_reordered_failover_snapshots_pass(self):
        path = self.folder() / "pool-0-events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows.append({"sequence": len(rows) + 1, "event": {"Disconnected": {"peer": 0}}})
        write_journal(path, rows)
        name = "two_pool_endpoints"
        pools = json.loads((self.folder(name) / "summary.json").read_text())["pools"]
        self.save_pools(name, list(reversed(pools)))
        result = self.validate()
        self.assertTrue(result["passed"], result)

    def test_bridge_close_requires_single_completed_failover_interval(self):
        start = "DEBUG dmnd_client::translator::proxy::bridge: Starting ordered upstream work handler\n"
        restart = 'ERROR dmnd_client: "[Pool(Down)]" is DOWN. Reinitializing proxy...\n'
        closed = "ERROR dmnd_client::translator::proxy::bridge: Failed to receive ordered upstream work\n"
        path = self.folder("two_pool_endpoints") / "proxy.log"
        path.write_text(start + restart + closed + start)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        self.assertTrue(any("Failed to receive ordered upstream work" in item.get("message", "")
                            for item in result["expected_diagnostics"]))
        for text in (restart + closed + start, start + closed + start, start + restart + closed,
                     start + closed + restart + start, start + restart + start + closed,
                     start + restart + closed + closed + start):
            with self.subTest(log=text):
                path.write_text(text)
                self.assertFalse(self.validate()["passed"])
        path.write_text(start + restart + closed + start)
        (self.folder() / "proxy.log").write_text(start + restart + closed + start)
        self.assertFalse(self.validate()["passed"])

    def test_disconnect_diagnostics_need_recovery_after_a_mining_peer_closed(self):
        name = "upstream_disconnect"
        folder = self.folder(name)
        (folder / "proxy.log").write_text(
            "ERROR dmnd_client::translator::upstream::upstream: Failed to receive message\n")
        self.assertFalse(self.validate()["passed"])
        rows = [
            {"sequence": 1, "event": {"ShareAccepted": {"key": {"peer": 1}}}},
            {"sequence": 2, "event": {"Disconnected": {"peer": 1}}},
            {"sequence": 3, "event": {"ShareAccepted": {"key": {"peer": 2}}}},
        ]
        pools = [{"events": rows, "accepted": 2, "rejected": 0, "channels": [], "peers": [2]}]
        self.save_pools(name, pools)
        write_journal(folder / "pool-0-events.jsonl", rows)
        result = self.validate()
        self.assertTrue(result["passed"], result)
        (folder / "proxy.log").write_text(
            "ERROR dmnd_client::translator::upstream::upstream: Failed to receive unrelated message\n")
        self.assertFalse(self.validate()["passed"])

    def test_broken_event_counts_and_unknown_rejections_fail(self):
        path = self.folder() / "summary.json"
        original = json.loads(path.read_text())
        changed = copy.deepcopy(original)
        changed["accepted"] += 1
        write_json(path, changed)
        self.assertFalse(self.validate()["passed"])
        write_json(path, original)
        journal = self.folder() / "pool-0-events.jsonl"
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        rows.append({"sequence": len(rows) + 1, "event": {"ShareRejected": {"reason": "stale-share"}}})
        write_journal(journal, rows)
        self.assertFalse(self.validate()["passed"])

    def test_missing_or_invalid_negative_case_evidence_fails(self):
        path = self.folder("duplicate_sv1_share") / "duplicate-sv1.json"
        write_json(path, {"first": {"result": False}})
        self.assertFalse(self.validate()["passed"])


if __name__ == "__main__":
    unittest.main()
