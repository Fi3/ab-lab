"""Validate the complete mining suite and its retained runtime evidence."""
import json
from pathlib import Path
import re

from benchmarks.dmnd_mining_blocks import block_context, expected_solution


SCENARIOS = (
    "non_jd_mining", "jd_mining", "demand_share_ok", "target_change",
    "new_chain_tip", "upstream_disconnect", "two_pool_endpoints", "multiple_miners",
    "invalid_token", "reject_next_submit", "reject_next_declaration",
    "pause_and_resume_responses", "unknown_sv1_job", "duplicate_sv1_share",
    "malformed_sv1_submit", "environment_configuration_mining", "toml_configuration_mining",
)
POOL_TEST = "support::pool::tests::stalled_response_flush_keeps_messages_and_controls_responsive"
TESTS = (*SCENARIOS, POOL_TEST)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PANIC = re.compile(r"panicked at|fatal runtime error|segmentation fault|stack overflow|"
                   r"AddressSanitizer|UndefinedBehaviorSanitizer|assertion .* failed", re.I)
ERROR = re.compile(r"\b(?:ERROR|FATAL)\b|(?:^|\s)(?:error|fatal):|"
                   r"JSON decode failed|Stratum connection failed")
EVENTS = {"Connected", "Setup", "SetupRejected", "ChannelOpened", "JobPublished", "TipChanged",
          "TargetChanged", "TokenAllocated", "MissingTransactionsRequested", "DeclarationRegistered",
          "DeclarationRejected", "CustomJobRegistered", "CustomJobRejected", "ShareAccepted",
          "ShareRejected", "Disconnected", "Error"}
REJECTIONS = {
    "invalid_token": {("SetupRejected", "invalid-token")},
    "reject_next_submit": {("ShareRejected", "forced-rejection")},
    "reject_next_declaration": {("DeclarationRejected", "forced-rejection")},
    "duplicate_sv1_share": {("ShareRejected", "duplicate-share")},
    "new_chain_tip": {("ShareRejected", "stale-share"), ("ShareRejected", "invalid-job-id")},
}
# Only messages caused by the scenario's specified invalid operation belong here.
# Numeric identifiers vary; message text and originating modules remain exact.
EXPECTED_LOGS = {
    "reject_next_submit": (
        r"dmnd_client::translator::upstream::upstream: Pool rejected share with error code forced-rejection",
        r"roles_logic_sv2::handlers::mining: Received SubmitSharesError with error code forced-rejection",),
    "duplicate_sv1_share": (
        r"dmnd_client::translator::upstream::upstream: Pool rejected share with error code duplicate-share",
        r"roles_logic_sv2::handlers::mining: Received SubmitSharesError with error code duplicate-share",),
    "reject_next_declaration": (
        r"roles_logic_sv2::handlers::job_declaration: Received DeclareMiningJobError, error code: invalid-mining-job-token",
        r"dmnd_client::jd_client::job_declarator: Job is not verified: DeclareMiningJobError \{ request_id: [0-9]+, "
        + re.escape("error_code: Owned(" + str(list(b"invalid-mining-job-token"))
                    + "), error_details: Owned([]) }"),
        r"dmnd_client::jd_client::job_declarator: Job is not verified: DeclareMiningJobError \{ request_id: [0-9]+, "
        + re.escape("error_code: LegacyB0255(InnerOwned { len: 24, data: "
                    + b"invalid-mining-job-token".hex()
                    + " }, PhantomData<&[u8]>), error_details: LegacyB064K(InnerOwned { len: 0, data:  }, PhantomData<&[u8]>) }")),
    "unknown_sv1_job": (
        r"dmnd_client::translator::downstream::downstream: Share rejected: can not find job with id 4294967295",
        r"dmnd_client::translator::downstream::downstream: Downstream [0-9]+: rejected invalid mining\.submit without disconnecting downstream: invalid extranonce2 length: expected [0-9]+, got 1",),
    "malformed_sv1_submit": (
        r'dmnd_client::translator::downstream::downstream: Downstream [0-9]+: rejected invalid mining\.submit without disconnecting downstream: failed to parse mining\.submit after InvalidSubmission: WrongArgs\(Array \[String\("malformed-worker"\)\]\)',),
    "new_chain_tip": (
        r"dmnd_client::translator::upstream::upstream: Pool rejected share with error code (?:stale-share|invalid-job-id)",
        r"dmnd_client::translator::downstream::downstream: Share rejected: can not find job with id [0-9]+",),
}
RECOVERY_LOGS = {
    "proxy.log": (
        r"dmnd_client::minin_pool_connection: Failed to receive msg from Pool",
        r"dmnd_client::translator::upstream::upstream: Failed to receive message",
        r'dmnd_client: "\[Pool\(Down\)\]" is DOWN\. Reinitializing proxy\.\.\.',
    ),
    "miner-0.log": (
        r"\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\] Stratum connection failed: "
        r"Failed to connect to 127\.0\.0\.1 port [0-9]+ after [0-9]+ ms: Couldn't connect to server",
    ),
}
TARGET_LOGS = (
    r"roles_logic_sv2::handlers::mining: Received SubmitSharesError with error code difficulty-too-low",
    r"dmnd_client::translator::upstream::upstream: Pool rejected share with error code difficulty-too-low",
)
TP_SHA256 = "ddd607846084923bc13459dc7f1257576c0f019730336935351857f0a7891f68"
# The pinned TP calls all message classifiers before dispatch. Its mining
# classifier logs these valid template message types before successful parsing.
# The source revisions and verification are recorded in README.
TP_DISPATCH_LOGS = (r"roles_logic_sv2::parsers: Invalid message type: (?:112|115)",)
INGRESS_CLOSED = "dmnd_client::ingress::sv1_ingress: Upstream dropped trying to receive"
TP_CLOSED = re.compile(r"demand_sv2_connection::noise_connection_tokio: Disconnected from client "
                       r"while reading : early eof - (127\.0\.0\.1:[0-9]+)")
PROBE_EOF = {"early eof", 'SV2 connection: Io(Custom { kind: UnexpectedEof, error: "early eof" })'}
BRIDGE_CLOSED = "dmnd_client::translator::proxy::bridge: Failed to receive ordered upstream work"
BRIDGE_STARTED = "dmnd_client::translator::proxy::bridge: Starting ordered upstream work handler"
POOL_RESTART = 'dmnd_client: "[Pool(Down)]" is DOWN. Reinitializing proxy...'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(path):
    _require(path.is_file() and not path.is_symlink(), "missing regular file: " + path.name)
    return path.read_text(encoding="utf-8")


def _json(path):
    return json.loads(_text(path))


def _journal(path):
    rows = [json.loads(line) for line in _text(path).splitlines()]
    _require(bool(rows), "empty event journal: " + path.name)
    return rows


def _suite(stdout):
    text = ANSI.sub("", stdout)
    _require(re.findall(r"^running ([0-9]+) tests$", text, re.M) == ["18"],
             "suite must run exactly 18 tests")
    rows = re.findall(r"^test (\S+) \.\.\. (\S+)$", text, re.M)
    _require(sorted(rows) == sorted((name, "ok") for name in TESTS),
             "suite results do not contain exactly the 18 required passing tests")
    totals = re.findall(r"^test result: (.+)$", text, re.M)
    _require(len(totals) == 1 and re.fullmatch(
        r"ok\. 18 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in [0-9.]+s",
        totals[0]), "suite totals are missing, incomplete, or failed")


def _bridge_shutdown(lines):
    # Dropping upstream tasks during failover can close this channel before
    # the old bridge task is cancelled. Require the complete restart interval.
    positions = {message: [] for message in (BRIDGE_CLOSED, BRIDGE_STARTED, POOL_RESTART)}
    for number, line in enumerate(lines, 1):
        message = re.split(r"\b(?:DEBUG|INFO|WARN|ERROR|FATAL)\b\s*", line, maxsplit=1)[-1].strip()
        if message in positions:
            positions[message].append(number)
    closed, started, restart = (positions[name] for name in (BRIDGE_CLOSED, BRIDGE_STARTED, POOL_RESTART))
    if (len(closed) == len(restart) == 1 and len(started) == 2
            and started[0] < restart[0] < closed[0] < started[1]):
        return closed[0]
    return None


def _scan_log(text, name, scenario, expected, errors, context=None):
    context, counts, closed = context or {}, {}, set()
    lines = ANSI.sub("", text).splitlines()
    bridge_shutdown = (_bridge_shutdown(lines) if name == "proxy.log" and scenario == "two_pool_endpoints"
                       and context.get("recovered") else None)
    for number, line in enumerate(lines, 1):
        if not (PANIC.search(line) or ERROR.search(line)):
            continue
        message = re.split(r"\b(?:ERROR|FATAL)\b\s*", line, maxsplit=1)[-1].strip()
        patterns = EXPECTED_LOGS.get(scenario, ()) if name == "proxy.log" else ()
        if name == "proxy.log" and scenario == "target_change" and context.get("target_rejections"):
            patterns += TARGET_LOGS
        if context.get("recovered") and scenario in ("upstream_disconnect", "two_pool_endpoints"):
            patterns += RECOVERY_LOGS.get(name, ())
            if scenario == "two_pool_endpoints" and name == "proxy.log":
                patterns += (r"dmnd_client::router: Failed to get mining setup latencies for: 127\.0\.0\.1:[0-9]+",)
        if name == "tp.log" and context.get("pinned_tp"):
            patterns += TP_DISPATCH_LOGS
            if context.get("blocks"):
                patterns += (r"roles_logic_sv2::parsers: Invalid message type: 118",)
        matched = next((pattern for pattern in patterns if re.fullmatch(pattern, message)), None)
        allowed = matched is not None
        if message == BRIDGE_CLOSED:
            allowed = number == bridge_shutdown
        if matched in RECOVERY_LOGS.get(name, ()):
            counts[matched] = counts.get(matched, 0) + 1
            allowed = counts[matched] <= 1
        if matched in TARGET_LOGS:
            counts[matched] = counts.get(matched, 0) + 1
            allowed = counts[matched] <= context.get("target_rejections", 0)
        if message == "roles_logic_sv2::parsers: Invalid message type: 118":
            counts[message] = counts.get(message, 0) + 1
            allowed = allowed and counts[message] <= context.get("blocks", 0)
        if name == "proxy.log" and message == INGRESS_CLOSED:
            counts[message] = counts.get(message, 0) + 1
            allowed = counts[message] <= context.get("ingress_closes", 0)
        tp_close = TP_CLOSED.fullmatch(message) if name == "tp.log" else None
        if tp_close and context.get("pinned_tp"):
            address = tp_close.group(1)
            allowed = address not in closed and len(closed) < context["tp_clients"]
            closed.add(address)
        allowed = allowed and not PANIC.search(line)
        location = f"{scenario}/{name}:{number}" if scenario else f"{name}:{number}"
        if allowed:
            expected.append({"location": location, "message": line})
        else:
            errors.append(f"{location}: {line}")


def _probe_closed(rows, index, scenario):
    if scenario != "two_pool_endpoints" or not 0 < index < len(rows) - 1:
        return False
    value = rows[index]["event"]["Error"]
    match = re.fullmatch(r"peer ([0-9]+)", value.get("source", ""))
    if not match or value.get("message") not in PROBE_EOF:
        return False
    peer = int(match[1])
    before = rows[index - 1].get("event", {}).get("Disconnected", {})
    after = rows[index + 1].get("event", {}).get("Connected", {})
    if before.get("peer") != peer - 1 or after.get("peer") != peer + 1:
        return False
    previous = [row.get("event", {}) for row in rows[:index]]
    opened = any(event.get("ChannelOpened", {}).get("channel", {}).get("peer") == peer - 1
                 for event in previous)
    mined = any(event.get("ShareAccepted", {}).get("key", {}).get("peer") == peer - 1
                for event in previous)
    if not opened or mined:
        return False
    for row in rows:
        for event in row.get("event", {}).values():
            if (event.get("peer") == peer or event.get("channel", {}).get("peer") == peer
                    or event.get("key", {}).get("peer") == peer):
                return False
    return True


def _target_transition(rows, index, scenario):
    # The test changes the pool target before the proxy can receive SetTarget.
    # Old work can fail until the first accepted share at the new target.
    if scenario != "target_change":
        return None
    rejected = rows[index]["event"].get("ShareRejected", {})
    if rejected.get("reason") != "difficulty-too-low":
        return None
    channel = rejected.get("channel")
    changes = [(i, row["event"]["TargetChanged"]) for i, row in enumerate(rows)
               if "TargetChanged" in row["event"]]
    if len(changes) != 1:
        return None
    changed_at, changed = changes[0]
    target = [0] * 27 + [255, 255, 7, 0, 0]
    if changed_at >= index or changed.get("channel") != channel or changed.get("target") != target:
        return None
    accepted = [(i, row["event"]["ShareAccepted"]) for i, row in enumerate(rows)
                if "ShareAccepted" in row["event"]]
    before = [(i, share) for i, share in accepted if i < changed_at]
    after = [(i, share) for i, share in accepted if i > changed_at]
    if not before or not after or after[0][0] <= index:
        return None
    previous, current = before[-1][1], after[0][1]
    key = {**(channel or {}), "job": rejected.get("job_id")}
    if (previous.get("key") != key or current.get("key") != key
            or previous.get("target") != [0] * 27 + [255, 255, 15, 0, 0]
            or current.get("target") != target
            or not previous.get("sequence_number", -1) < rejected.get("sequence_number", -1)
            < current.get("sequence_number", -1)):
        return None
    return {"event": "ShareRejected", "reason": "old work during target change",
            "changed_at": changed_at + 1, "accepted_at": after[0][0] + 1}


def _events(rows, scenario, blocks=None):
    _require(isinstance(rows, list), "events must be a list")
    counts = {"ShareAccepted": 0, "ShareRejected": 0}
    rejected, diagnostics, block_hashes = set(), [], set()
    probes = 0
    for sequence, row in enumerate(rows, 1):
        _require(isinstance(row, dict) and set(row) == {"sequence", "event"}
                 and type(row["sequence"]) is int and row["sequence"] == sequence,
                 "event sequence is invalid")
        event = row["event"]
        _require(isinstance(event, dict) and len(event) == 1, "event must have one type")
        kind, value = next(iter(event.items()))
        _require(kind in EVENTS and isinstance(value, dict), "invalid event type or payload")
        if kind == "Error":
            proof = expected_solution(rows, sequence - 1, blocks)
            if _probe_closed(rows, sequence - 1, scenario):
                proof = {"reason": "uninitialized JD probe closed"}
                probes += 1
                _require(probes <= 2, "too many uninitialized JD probes")
            _require(proof, "pool error: " + json.dumps(value, sort_keys=True))
            if "block_hash" in proof:
                _require(proof["block_hash"] not in block_hashes, "duplicate JD block notification")
                block_hashes.add(proof["block_hash"])
            diagnostics.append({"sequence": sequence, **value, **proof})
        if kind in counts:
            counts[kind] += 1
        if kind.endswith("Rejected"):
            rejection = (kind, value.get("reason"))
            transition = _target_transition(rows, sequence - 1, scenario)
            _require(rejection in REJECTIONS.get(scenario, set()) or transition,
                     "unexpected rejection: " + json.dumps(event, sort_keys=True))
            if transition:
                diagnostics.append({"sequence": sequence, **transition})
            rejected.add(rejection)
    return counts, rejected, diagnostics


def _pool_evidence(folder, scenario, summary, blocks):
    pools = summary.get("pools")
    count = 2 if scenario == "two_pool_endpoints" else 1
    _require(isinstance(pools, list) and len(pools) == count, "incorrect pool count")
    expected_names = {f"pool-{index}-events.jsonl" for index in range(count)}
    _require({path.name for path in folder.glob("pool-*-events.jsonl")} == expected_names,
             "incorrect pool journal set")
    journals = [_journal(folder / name) for name in sorted(expected_names)]
    probes = []
    for index, rows in enumerate(journals):
        _, _, found = _events(rows, scenario, blocks)
        probes.extend({"journal": f"pool-{index}-events.jsonl", **item} for item in found)
    merged, rejected, accepted_count, rejected_count = [], set(), 0, 0
    for index, pool in enumerate(pools):
        _require(isinstance(pool, dict), "invalid pool summary")
        rows = pool.get("events")
        counts, found, _ = _events(rows, scenario, blocks)
        for key, kind in (("accepted", "ShareAccepted"), ("rejected", "ShareRejected")):
            _require(type(pool.get(key)) is int and pool[key] == counts[kind],
                     "pool counts disagree with events")
        _require(isinstance(pool.get("channels"), list) and isinstance(pool.get("peers"), list),
                 "pool connections are missing")
        matching = next((i for i, journal in enumerate(journals) if journal[:len(rows)] == rows), None)
        _require(matching is not None, "pool snapshot does not match a retained journal")
        journals.pop(matching)
        merged.extend({"pool": index, **row} for row in rows)
        rejected.update(found)
        accepted_count += pool["accepted"]
        rejected_count += pool["rejected"]
    _require(_journal(folder / "events.jsonl") == merged, "merged events disagree with pool summaries")
    _require(type(summary.get("accepted")) is int and summary["accepted"] == accepted_count
             and type(summary.get("rejected")) is int and summary["rejected"] == rejected_count,
             "summary counts disagree with pool summaries")
    if scenario == "invalid_token":
        _require(accepted_count == 0 and all(not pool["channels"] for pool in pools),
                 "invalid token opened a channel or accepted a share")
    else:
        minimum = 3 if scenario == "pause_and_resume_responses" else 2
        _require(accepted_count >= minimum, "insufficient validated shares")
        if scenario == "two_pool_endpoints":
            _require(all(pool["accepted"] > 0 for pool in pools), "failover did not mine on both pools")
    if scenario in REJECTIONS and scenario != "new_chain_tip":
        _require(REJECTIONS[scenario] <= rejected, "required negative-test rejection is missing")
    return sorted(rejected), probes


def _negative_artifacts(folder, scenario):
    if scenario == "unknown_sv1_job":
        data = _json(folder / "sv1-negative.json")
        _require(data.get("boundary") == "proxy" and isinstance(data.get("response"), dict)
                 and data["response"].get("result") is not True, "unknown job was not rejected")
    elif scenario == "duplicate_sv1_share":
        data = _json(folder / "duplicate-sv1.json")
        _require(data.get("first", {}).get("result") is True
                 and data.get("rejection", {}).get("event", {}).get("ShareRejected", {}).get("reason")
                 == "duplicate-share", "duplicate share evidence is invalid")
    elif scenario == "malformed_sv1_submit":
        data = _json(folder / "malformed-sv1.json")
        _require(isinstance(data, dict) and data.get("result") is not True
                 and ("disconnect" in data or "error" in data or data.get("result") is False),
                 "malformed submission was not rejected")
    elif scenario == "new_chain_tip":
        _require(isinstance(_json(folder / "tip-block.json"), dict), "tip block is missing")
        data = _json(folder / "stale-sv1.json")
        _require(data.get("boundary") in ("pool", "proxy-bridge", "proxy-sv1")
                 and isinstance(data.get("response"), dict)
                 and isinstance(data.get("fresh_notify"), dict), "stale share evidence is missing")


def _recovered(pools):
    for pool in pools:
        accepted, disconnected = set(), set()
        for row in pool["events"]:
            event = row["event"]
            if "ShareAccepted" in event:
                peer = event["ShareAccepted"].get("key", {}).get("peer")
                if peer is not None:
                    if disconnected - {peer}:
                        return True
                    accepted.add(peer)
            elif "Disconnected" in event:
                peer = event["Disconnected"].get("peer")
                if peer in accepted:
                    disconnected.add(peer)
    return False


def _scenario(folder, scenario):
    summary, config = _json(folder / "summary.json"), _json(folder / "configuration.json")
    _require(isinstance(summary, dict) and summary.get("status") == "passed"
             and "error" in summary and summary["error"] is None, "scenario summary did not pass")
    miner_count = 0 if scenario == "invalid_token" else 2 if scenario == "multiple_miners" else 1
    _require(isinstance(config, dict) and config.get("miner_count") == miner_count
             and config.get("jd") is (scenario in ("jd_mining", "reject_next_declaration")),
             "scenario configuration is invalid")
    pinned_tp = False
    for name in ("tp", "proxy", *(f"miner-{index}" for index in range(miner_count))):
        process = _json(folder / f"{name}-process.json")
        _require(isinstance(process, dict) and isinstance(process.get("binary"), dict)
                 and re.fullmatch(r"[0-9a-f]{64}", process["binary"].get("sha256", ""))
                 and isinstance(process.get("args"), list) and isinstance(process.get("env"), dict)
                 and isinstance(process.get("cwd"), str), "invalid process record: " + name)
        _require(bool(_text(folder / f"{name}.log").strip()), "empty process log: " + name)
        if name == "tp":
            pinned_tp = process["binary"]["sha256"] == TP_SHA256
    blocks = (block_context(ANSI.sub("", _text(folder / "proxy.log")), ANSI.sub("", _text(folder / "tp.log")))
              if config["jd"] and pinned_tp else None)
    rejected, probes = _pool_evidence(folder, scenario, summary, blocks)
    _negative_artifacts(folder, scenario)
    scripted = scenario in ("new_chain_tip", "unknown_sv1_job", "duplicate_sv1_share", "malformed_sv1_submit")
    recovery = scenario in ("upstream_disconnect", "two_pool_endpoints")
    context = {"pinned_tp": pinned_tp,
               "blocks": sum("block_hash" in item for item in probes),
               "target_rejections": sum(item.get("event") == "ShareRejected" for item in probes),
               "tp_clients": len(summary["pools"]) + int(config["jd"]),
               "ingress_closes": int(miner_count > 0) + miner_count + int(scripted) + int(recovery),
               "recovered": _recovered(summary["pools"]) or scenario == "two_pool_endpoints"}
    return rejected, probes, context


def validate_mining(artifacts: Path, stdout: str, stderr: str) -> dict:
    """Require all tests, complete artifacts, and no unexpected runtime error."""
    artifacts = Path(artifacts)
    errors, expected, scenarios = [], [], []
    try:
        _suite(stdout)
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
    _scan_log(stdout, "stdout", None, expected, errors)
    _scan_log(stderr, "stderr", None, expected, errors)
    folders = {}
    try:
        _require(artifacts.is_dir() and not artifacts.is_symlink(), "artifact directory is missing")
        for folder in sorted(artifacts.iterdir()):
            matches = [name for name in SCENARIOS if re.fullmatch(re.escape(name) + r"-[A-Za-z0-9]+", folder.name)]
            _require(folder.is_dir() and not folder.is_symlink() and len(matches) == 1,
                     "unexpected artifact entry: " + folder.name)
            name = matches[0]
            _require(name not in folders, "duplicate scenario artifacts: " + name)
            folders[name] = folder
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    for name in SCENARIOS:
        folder = folders.get(name)
        if folder is None:
            errors.append("missing scenario artifacts: " + name)
            continue
        scenarios.append(name)
        context = {}
        try:
            rejections, probes, context = _scenario(folder, name)
            for kind, reason in rejections:
                expected.append({"scenario": name, "event": kind, "reason": reason})
            expected.extend({"scenario": name, "event": "Error", **probe} for probe in probes)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(name + ": " + str(exc))
        for path in sorted(folder.glob("*.log")):
            try:
                _scan_log(_text(path), path.name, name, expected, errors, context)
            except (OSError, ValueError) as exc:
                errors.append(name + ": " + str(exc))
    return {"passed": not errors, "errors": errors, "scenarios": scenarios,
            "expected_diagnostics": expected}
