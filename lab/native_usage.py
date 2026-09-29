"""Read numeric response receipts from one owned Codex rollout.

The app-server's cumulative counters can omit compaction responses. Native
``thread_token_usage`` counters include them; these totals replace, rather than
add to, the matching app-server totals. Only the exact path returned when the
owned thread was created is admitted here.
"""
import hashlib
import json
import os
from pathlib import Path


def _tokens(value):
    if not isinstance(value, dict):
        raise ValueError("missing numeric token usage")
    result = tuple(value.get(key) for key in
                   ("input_tokens", "output_tokens", "cached_input_tokens"))
    if any(type(n) is not int or n < 0 for n in result):
        raise ValueError("invalid numeric token usage")
    if result[2] > result[0] or result[0] + result[1] <= 0:
        raise ValueError("inconsistent numeric token usage")
    if "total_tokens" in value and (
            type(value["total_tokens"]) is not int or
            value["total_tokens"] != result[0] + result[1]):
        raise ValueError("inconsistent total_tokens")
    return result


class NativeUsage:
    """Incrementally validate complete JSONL records without reading other sessions."""

    def __init__(self, path, thread_id, cwd):
        self.path = Path(path)
        self.thread_id = thread_id
        self.cwd = Path(cwd).resolve()
        self.totals = None
        self.responses = {}
        self.compactions = {}
        self.missing_compactions = set()
        self.errors = []
        self.validated = False
        self.offset = 0
        self.line = 0
        self._identity = None
        self._hash = hashlib.sha256()

    def refresh(self):
        """Return new response evidence; incomplete final lines wait for a later call."""
        new = []
        if self.errors:
            return new
        try:
            with self.path.open("rb") as source:
                # fstat binds identity and size to the opened file, not a path race.
                status = os.fstat(source.fileno())
                identity = status.st_dev, status.st_ino
                if self._identity not in (None, identity) or status.st_size < self.offset:
                    raise ValueError("native rollout was replaced or truncated")
                self._identity = identity
                source.seek(self.offset)
                while raw := source.readline():
                    if not raw.endswith(b"\n"):
                        break
                    provenance = {"line": self.line + 1, "offset": self.offset,
                                  "sha256": hashlib.sha256(raw).hexdigest()}
                    self.offset += len(raw)
                    self.line += 1
                    self._hash.update(raw)
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError("native rollout record is not an object")
                    provenance["type"] = event.get("type")
                    self._event(event, provenance, new)
        except FileNotFoundError:
            if self._identity is not None:
                self.errors.append("owned native rollout disappeared")
        except (OSError, UnicodeError, ValueError) as exc:
            self.errors.append(f"native rollout line {self.line}: {exc}")
        return new

    def _event(self, event, source, new):
        kind, payload = event.get("type"), event.get("payload")
        if kind == "session_meta":
            if not isinstance(payload, dict) or payload.get("id") != self.thread_id:
                raise ValueError("native session identity does not match owned thread")
            session_id = payload.get("session_id", self.thread_id)
            cwd = payload.get("cwd")
            if (session_id != self.thread_id or not isinstance(cwd, str) or
                    Path(cwd).resolve() != self.cwd):
                raise ValueError("native session workspace or session_id does not match owned thread")
            self.validated = True
            return
        if kind not in ("token_usage_record", "compacted"):
            return
        if not self.validated:
            raise ValueError("native usage precedes validated session metadata")
        if kind == "token_usage_record":
            self._response(payload, source, new)
            return
        if not isinstance(payload, dict):
            raise ValueError("invalid native compaction record")
        response_id = payload.get("compaction_response_id")
        if not isinstance(response_id, str) or not response_id:
            raise ValueError("native compaction has no response identity")
        embedded = payload.get("latest_token_usage_record")
        if embedded is not None:
            if not isinstance(embedded, dict) or embedded.get("response_id") != response_id:
                raise ValueError("native compaction response identity mismatch")
            self._response(embedded, source, new)
        receipt = self.responses.get(response_id)
        existing = self.compactions.get(response_id)
        if existing is None:
            self.compactions[response_id] = {
                "response_id": response_id,
                "turn_id": receipt["turn_id"] if receipt else None,
                "sources": [source],
            }
        else:
            existing["sources"].append(source)
        if receipt is None:
            self.missing_compactions.add(response_id)

    def _response(self, payload, source, new):
        if not isinstance(payload, dict):
            raise ValueError("invalid native response receipt")
        if (payload.get("thread_id") != self.thread_id or
                payload.get("session_id", self.thread_id) != self.thread_id):
            raise ValueError("foreign thread in native response receipt")
        response_id, turn_id = payload.get("response_id"), payload.get("turn_id")
        if not all(isinstance(value, str) and value for value in (response_id, turn_id)):
            raise ValueError("native response receipt lacks response_id or turn_id")
        usage = _tokens(payload.get("usage"))
        total = _tokens(payload.get("thread_token_usage"))
        prior = self.responses.get(response_id)
        if prior is not None:
            if prior["payload"] != payload:
                raise ValueError("conflicting duplicate native response receipt")
            prior["sources"].append(source)
            return
        minimum = tuple(a + b for a, b in zip(self.totals or (0, 0, 0), usage))
        if any(a < b for a, b in zip(total, minimum)):
            raise ValueError("native cumulative counters do not cover the new response")
        receipt = {"response_id": response_id, "turn_id": turn_id,
                   "usage": usage, "thread_totals": total,
                   "payload": payload, "sources": [source]}
        self.responses[response_id] = receipt
        self.totals = total
        if response_id in self.compactions:
            self.compactions[response_id]["turn_id"] = turn_id
            self.missing_compactions.discard(response_id)
        new.append(receipt)

    def completed_compactions(self, turn_id):
        """Receipts correlated to an actual compacted marker in this exact turn."""
        return [self.responses[response_id] for response_id, marker in self.compactions.items()
                if marker["turn_id"] == turn_id and response_id in self.responses]

    def report(self):
        return {"path": str(self.path), "thread_id": self.thread_id,
                "cwd": str(self.cwd), "validated": self.validated,
                "complete_bytes": self.offset, "complete_lines": self.line,
                "complete_prefix_sha256": self._hash.hexdigest(),
                "thread_totals": self.totals,
                "responses": list(self.responses.values()),
                "compactions": list(self.compactions.values()),
                "missing_compactions": sorted(self.missing_compactions),
                "errors": list(self.errors)}
