"""Recognize a valid block notification that the fixed pool does not handle."""
from datetime import datetime
import json
import re


def _records(text, module):
    pattern = re.compile(r"(\S+)\s+(?:INFO|DEBUG) " + re.escape(module) + r": (.*)")
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if match:
            yield datetime.fromisoformat(match[1].replace("Z", "+00:00")), match[2]


def _bytes(value):
    if re.fullmatch(r'"[0-9a-f]*"', value):
        return bytes.fromhex(value[1:-1])
    old = re.fullmatch(r"Owned\((\[(?:[0-9]+(?:, [0-9]+)*)?\])\)", value)
    if old:
        return bytes(json.loads(old[1]))
    new = re.fullmatch(r"Legacy(?:B032|U256)\(InnerOwned \{ len: ([0-9]+), data: ([0-9a-f]*) "
                       r"\}, PhantomData<&\[u8\]>\)", value)
    if new and int(new[1]) * 2 == len(new[2]):
        return bytes.fromhex(new[2])
    raise ValueError("unknown block notification byte format")


def _solution(message):
    match = re.fullmatch(
        r"unsupported JD message: SubmitSolution\(SubmitSolutionJd \{ extranonce: (.+), "
        r"prev_hash: (.+), ntime: ([0-9]+), nonce: ([0-9]+), nbits: ([0-9]+), version: ([0-9]+) \}\)",
        message)
    if not match:
        return None
    extranonce, previous = _bytes(match[1]), _bytes(match[2])
    values = dict(zip(("ntime", "nonce", "nbits", "version"), map(int, match.group(3, 4, 5, 6))))
    if len(extranonce) != 32 or len(previous) != 32 or any(value >= 2**32 for value in values.values()):
        return None
    return {"extranonce": extranonce, "previous": previous, **values}


def _target(bits):
    exponent, mantissa = bits >> 24, bits & 0x7fffff
    if bits & 0x800000 or not mantissa or exponent > 32:
        return 0
    return mantissa << (8 * (exponent - 3)) if exponent >= 3 else mantissa >> (8 * (3 - exponent))


def _checked_blocks(text):
    checked, target = None, None
    for timestamp, message in _records(text, "roles_logic_sv2::channel_logic::channel_factory"):
        match = re.fullmatch(r"Checking target for share Extended\(SubmitSharesExtended \{ "
            r"channel_id: [0-9]+, sequence_number: [0-9]+, job_id: [0-9]+, nonce: ([0-9]+), "
            r"ntime: ([0-9]+), version: ([0-9]+), extranonce(?:_prefix)?: (.+) \}\)", message)
        if match:
            checked = {"nonce": int(match[1]), "ntime": int(match[2]), "version": int(match[3]),
                       "extranonce": _bytes(match[4]), "time": timestamp}
            target = None
        match = re.fullmatch(r"Bitcoin target : ([0-9a-f]{64})", message)
        if match:
            target = int(match[1], 16)
        match = re.fullmatch(r"Share hash meet bitcoin target: ([0-9a-f]{64})", message)
        if match and checked and target and 0 <= (timestamp - checked["time"]).total_seconds() <= 1:
            if 0 < int(match[1], 16) <= target:
                yield {**checked, "hash": match[1], "target": target, "time": timestamp}


def _accepted_blocks(text):
    height = None
    for timestamp, message in _records(text, "tp_simulator"):
        started = re.search(r"\binitial_height=([0-9]+)\b", message)
        if message.startswith("tp-simulator started ") and started:
            height = int(started[1]) + 1
        published = re.fullmatch(r"Publishing non-future template [0-9]+ at height ([0-9]+)", message)
        if published:
            height = int(published[1])
        accepted = re.fullmatch(r"Accepted (VirtualMining|RpcSubmitBlock|Sv2SubmitSolution) block "
                                r"at height ([0-9]+) and activated template ([0-9]+)", message)
        if accepted:
            if accepted[1] == "Sv2SubmitSolution" and int(accepted[2]) == height and int(accepted[3]) > 0:
                yield {"time": timestamp, "height": height, "template": int(accepted[3])}
            height = int(accepted[2]) + 1


def block_context(proxy_log, tp_log):
    """The caller must verify the TP binary and complete scenario evidence."""
    return {"checked": list(_checked_blocks(proxy_log)), "accepted": list(_accepted_blocks(tp_log))}


def expected_solution(rows, index, context):
    """Require matching submission, target, accepted block, and subsequent tip.

    The pinned TP validates the full block. Its acceptance and the pool's new
    tip provide independent evidence; this function does not rebuild a block.
    """
    value = rows[index]["event"]["Error"]
    if value.get("source") != "pool" or not context:
        return None
    try:
        solution = _solution(value.get("message", ""))
        if not solution:
            return None
        prior = [row["event"]["TipChanged"]["prev_hash"] for row in rows[:index]
                 if "TipChanged" in row["event"]]
        if not prior or bytes(prior[-1]) != solution["previous"]:
            return None
        for checked in context["checked"]:
            if (any(checked[key] != solution[key] for key in ("nonce", "ntime", "version"))
                    or checked["target"] != _target(solution["nbits"])
                    or not checked["extranonce"] or not solution["extranonce"].endswith(checked["extranonce"])):
                continue
            block_hash = list(bytes.fromhex(checked["hash"])[::-1])
            if not any(row["event"].get("TipChanged", {}).get("prev_hash") == block_hash for row in rows[index + 1:]):
                continue
            for accepted in context["accepted"]:
                if 0 <= (accepted["time"] - checked["time"]).total_seconds() <= 5:
                    return {"reason": "valid JD block notification accepted by the pinned TP",
                            "block_hash": checked["hash"], "nonce": solution["nonce"],
                            "height": accepted["height"], "activated_template": accepted["template"]}
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    return None
