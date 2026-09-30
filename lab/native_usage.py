"""Read numeric response receipts from one owned Codex rollout.

The app-server's cumulative counters can omit compaction responses. Native
``thread_token_usage`` counters include them; these totals replace, rather than
add to, the matching app-server totals. Root paths come from owned thread
creation; native child paths also require a matching parent and fork boundary.
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

    def __init__(self, path, thread_id, cwd, *, parent_thread_id=None):
        self.path = Path(path)
        self.thread_id = thread_id
        self.cwd = Path(cwd).resolve()
        self.parent_thread_id = parent_thread_id
        self.session_id = thread_id
        self.turn_contexts = {}
        self.plans = set()
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
        self._own_start_line = None
        self._inherited_threads = set()
        self._inherited_turns = set()
        self._expected_ancestor = parent_thread_id

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
        if self.parent_thread_id is not None:
            if self._child_event(kind, payload):
                return
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

    def _child_metadata(self, payload, thread_id, parent_thread_id):
        if not isinstance(payload, dict) or payload.get("id") != thread_id:
            raise ValueError("native session identity does not match owned child ancestry")
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or Path(cwd).resolve() != self.cwd:
            raise ValueError("native session workspace does not match owned thread")
        session_id = payload.get("session_id", thread_id)
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("native child has no session identity")
        if parent_thread_id is not None:
            if (not isinstance(parent_thread_id, str) or not parent_thread_id or
                    parent_thread_id == thread_id or
                    payload.get("parent_thread_id") != parent_thread_id or
                    payload.get("forked_from_id") != parent_thread_id):
                raise ValueError("native child parent identity mismatch")
            source = payload.get("source")
            if source is not None:
                if not isinstance(source, dict):
                    raise ValueError("invalid native child source parent identity")
                subagent = source.get("subagent")
                spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
                if not isinstance(spawn, dict) or spawn.get("parent_thread_id") != parent_thread_id:
                    raise ValueError("native child source parent identity mismatch")
        elif session_id != thread_id:
            raise ValueError("native ancestor session identity mismatch")
        return session_id

    def _child_event(self, kind, payload):
        """Bound inherited history using the fork's record ordinal, never counters.

        A fork prepends its own metadata to the copied history. The ordinal is
        zero-based within the following records, so only that bounded prefix can
        carry ancestor identities. Appending another turn cannot reopen it.
        """
        if self._own_start_line is None:
            if self.line != 1 or kind != "session_meta":
                raise ValueError("native child must begin with owned session metadata")
            self.session_id = self._child_metadata(payload, self.thread_id, self.parent_thread_id)
            ordinal = payload.get("subagent_history_start_ordinal")
            if type(ordinal) is not int or ordinal < 1:
                raise ValueError("native child has no valid inherited history boundary")
            self._own_start_line = ordinal + 2
            return True
        if self.line < self._own_start_line:
            if kind == "session_meta":
                ancestor = self._expected_ancestor
                if ancestor is None or ancestor in self._inherited_threads or ancestor == self.thread_id:
                    raise ValueError("unexpected native inherited session metadata")
                parent = payload.get("parent_thread_id") if isinstance(payload, dict) else None
                session_id = self._child_metadata(payload, ancestor, parent)
                if session_id != self.session_id:
                    raise ValueError("native ancestor session identity mismatch")
                self._inherited_threads.add(ancestor)
                self._expected_ancestor = parent
            else:
                if self._expected_ancestor is not None:
                    raise ValueError("native inherited history lacks parent session metadata")
                if kind == "token_usage_record":
                    self._inherited_receipt(payload)
                elif kind == "compacted" and isinstance(payload, dict):
                    embedded = payload.get("latest_token_usage_record")
                    if embedded is not None:
                        self._inherited_receipt(embedded)
                elif isinstance(payload, dict) and (kind == "turn_context" or
                        (kind == "event_msg" and payload.get("type") == "task_started")):
                    turn_id = payload.get("turn_id")
                    if isinstance(turn_id, str):
                        self._inherited_turns.add(turn_id)
            if self.line == self._own_start_line - 1:
                if self._expected_ancestor is not None:
                    raise ValueError("native inherited history lacks ancestor session metadata")
                self.validated = True
            return True
        if kind == "session_meta":
            session_id = self._child_metadata(payload, self.thread_id, self.parent_thread_id)
            if (session_id != self.session_id or
                    type(payload.get("subagent_history_start_ordinal")) is not int or
                    payload.get("subagent_history_start_ordinal") != self._own_start_line - 2):
                raise ValueError("native child session identity or history boundary changed")
            return True
        if kind == "turn_context":
            if not isinstance(payload, dict):
                raise ValueError("invalid native child turn context")
            turn_id, cwd = payload.get("turn_id"), payload.get("cwd")
            if (not isinstance(turn_id, str) or not turn_id or turn_id in self._inherited_turns or
                    not isinstance(cwd, str) or Path(cwd).resolve() != self.cwd or
                    payload.get("thread_id", self.thread_id) != self.thread_id or
                    payload.get("session_id", self.session_id) != self.session_id):
                raise ValueError("native child turn context identity or workspace mismatch")
            context = {key: payload.get(key) for key in ("model", "effort")}
            if any(not isinstance(value, str) or not value for value in context.values()):
                raise ValueError("native child turn context lacks model or effort")
            if turn_id in self.turn_contexts and self.turn_contexts[turn_id] != context:
                raise ValueError("conflicting native child turn context")
            self.turn_contexts[turn_id] = context
        elif kind == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
            limits = payload.get("rate_limits")
            plan = limits.get("plan_type") if isinstance(limits, dict) else None
            if isinstance(plan, str) and plan:
                self.plans.add(plan)
        return False

    def _inherited_receipt(self, payload):
        if (not isinstance(payload, dict) or
                not isinstance(payload.get("thread_id"), str) or
                payload.get("thread_id") not in self._inherited_threads or
                payload.get("session_id", self.session_id) != self.session_id):
            raise ValueError("foreign thread in native inherited response receipt")
        turn_id = payload.get("turn_id")
        if isinstance(turn_id, str):
            self._inherited_turns.add(turn_id)

    def _response(self, payload, source, new):
        if not isinstance(payload, dict):
            raise ValueError("invalid native response receipt")
        if (payload.get("thread_id") != self.thread_id or
                payload.get("session_id", self.session_id) != self.session_id):
            raise ValueError("foreign thread in native response receipt")
        response_id, turn_id = payload.get("response_id"), payload.get("turn_id")
        if not all(isinstance(value, str) and value for value in (response_id, turn_id)):
            raise ValueError("native response receipt lacks response_id or turn_id")
        if turn_id in self._inherited_turns:
            raise ValueError("native child receipt uses an inherited turn identity")
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
        result = {"path": str(self.path), "thread_id": self.thread_id,
                "cwd": str(self.cwd), "validated": self.validated,
                "complete_bytes": self.offset, "complete_lines": self.line,
                "complete_prefix_sha256": self._hash.hexdigest(),
                "thread_totals": self.totals,
                "responses": list(self.responses.values()),
                "compactions": list(self.compactions.values()),
                "missing_compactions": sorted(self.missing_compactions),
                "errors": list(self.errors)}
        if self.parent_thread_id is not None:
            result.update(parent_thread_id=self.parent_thread_id, session_id=self.session_id,
                          own_start_line=self._own_start_line,
                          turn_contexts=dict(self.turn_contexts), plans=sorted(self.plans))
        return result
