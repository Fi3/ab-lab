"""Check allocation and wire-format evidence from an independent Rust test."""
import hashlib
import json
from pathlib import Path
import re
import struct

from benchmarks.dmnd_mining_logs import ANSI, ERROR, PANIC


TEST_TARGET = "lab_sri_performance"
BINARY_NAME = "lab-sri-performance"
HARNESS = Path(__file__).with_suffix(".rs")
SCHEMA = "dmnd-sri-performance/v1"
SIZE_ITERATIONS = 10_000
WIRE_ITERATIONS = 256
MARKER = "LAB_SRI_PERFORMANCE "


def install_harness(context):
    path = Path(context) / "tests" / (TEST_TARGET + ".rs")
    if path.exists():
        raise ValueError("The submission already contains the independent performance test")
    source = HARNESS.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    return {"target": TEST_TARGET, "sha256": hashlib.sha256(source).hexdigest()}


def expected_evidence():
    job = (struct.pack("<II", 1, 1) + b"\x01" + struct.pack("<II", 1, 0x20000000)
           + bytes([1, 12]) + bytes([1]) * 384 + struct.pack("<H", 100) + bytes([1]) * 100
           + struct.pack("<H", 500) + bytes([2]) * 500)
    share = struct.pack("<IIIIII", 7, 8, 9, 10, 11, 0x20000000) + bytes([28]) + bytes([12]) * 28
    frames = []
    for payload, kind in ((job, 0x1f), (share, 0x1b)):
        frames.append(bytes([0, 128, kind]) + len(payload).to_bytes(3, "little") + payload)
    lengths = {"job_bytes": len(job), "share_bytes": len(share),
               "job_frame_bytes": len(frames[0]), "share_frame_bytes": len(frames[1])}
    return {"schema": SCHEMA, "size_iterations": SIZE_ITERATIONS, "wire_iterations": WIRE_ITERATIONS,
            "size_allocations": 0, "size_checksum": sum(lengths.values()) * SIZE_ITERATIONS,
            **lengths, "wire_sha256": hashlib.sha256(b"".join(frames) * WIRE_ITERATIONS).hexdigest()}


def validate_performance(stdout, stderr):
    text = ANSI.sub("", stdout)
    errors = []
    if re.findall(r"^running ([0-9]+) test(?:s)?$", text, re.M) != ["1"]:
        errors.append("The performance suite must run exactly one test")
    if re.findall(r"^test (\S+) \.\.\. (?:LAB_SRI_PERFORMANCE [^\n]+\n)?(\S+)$", text, re.M) != [(TEST_TARGET, "ok")]:
        errors.append("The independent performance test did not pass")
    totals = re.findall(r"^test result: (.+)$", text, re.M)
    if len(totals) != 1 or not re.fullmatch(
            r"ok\. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in [0-9.]+s", totals[0]):
        errors.append("The performance suite totals are missing or incomplete")
    for name, content in (("stdout", stdout), ("stderr", stderr)):
        for number, line in enumerate(ANSI.sub("", content).splitlines(), 1):
            if ERROR.search(line) or PANIC.search(line):
                errors.append(f"performance {name}:{number}: {line}")
    matches = re.findall(re.escape(MARKER) + r"([^\n]+)", text)
    evidence = None
    if len(matches) != 1:
        errors.append("The performance evidence must occur exactly once")
    else:
        try:
            evidence = json.loads(matches[0])
            expected = expected_evidence()
            if not isinstance(evidence, dict) or set(evidence) != set(expected):
                raise ValueError("The performance evidence fields changed")
            for key, value in expected.items():
                if type(evidence[key]) is not type(value) or evidence[key] != value:
                    errors.append(f"Performance evidence {key} must equal {value}; found {evidence[key]}")
        except (ValueError, TypeError) as error:
            errors.append(str(error))
    return {"passed": not errors, "errors": errors, "evidence": evidence,
            "scope": "Zero heap allocations for message and frame size queries; exact serialized bytes"}
