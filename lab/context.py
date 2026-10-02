"""Pure context sizing and bounded-state guards for Codex agent messages."""
from collections import deque


AUTO_COMPACT_TOKENS = 131072
OUTPUT_SETTLE_SECONDS = 600
_REPLACEMENT_WINDOW_CHARS = 2048
_REPLACEMENT_MIN_CHARS = 128
_MAX_TRAILING_WHITESPACE_CHARS = 8192
_MAX_REPEATED_CHARACTER_CHARS = 1024
_MAX_AGENT_MESSAGE_BYTES = 4 * 1024 * 1024

# Persist this JSON-compatible policy alongside the provider identity so that
# compaction and cancellation thresholds remain visible in benchmark artifacts.
CONTEXT_POLICY = {
    "version": 6,
    "compaction_accounting": "owned-native-response-receipts-v1",
    "auto_compact_tokens": AUTO_COMPACT_TOKENS,
    "replacement_window_chars": _REPLACEMENT_WINDOW_CHARS,
    "replacement_min_chars": _REPLACEMENT_MIN_CHARS,
    "replacement_whitespace_fraction": 0.90,
    "max_trailing_whitespace_chars": _MAX_TRAILING_WHITESPACE_CHARS,
    "max_repeated_character_chars": _MAX_REPEATED_CHARACTER_CHARS,
    "max_agent_message_bytes": _MAX_AGENT_MESSAGE_BYTES,
    "output_settle_seconds": OUTPUT_SETTLE_SECONDS,
    "output_settlement": "quarantine-until-priced-boundary-v1",
}


def validate_compaction_tokens(value):
    if type(value) is not int or value <= 0:
        raise ValueError("compaction tokens must be a positive integer")
    return value


class _MessageState:
    __slots__ = ("window", "replacements", "blank_or_replacement", "whitespace",
                 "last_character", "repeated_characters", "bytes", "reason")

    def __init__(self):
        self.window = deque()
        self.replacements = 0
        self.blank_or_replacement = 0
        self.whitespace = 0
        self.last_character = None
        self.repeated_characters = 0
        self.bytes = 0
        self.reason = None


class OutputGuard:
    """Inspect each message independently without retaining its full text.

    Reason strings are stable identifiers: ``replacement_character_flood``,
    ``trailing_whitespace``, ``repeated_character_flood``, and
    ``agent_message_bytes``. A detected reason stays latched until ``finish``
    releases that item's state. The caller owns turn timing, interruption, and
    usage accounting.
    """

    def __init__(self):
        self._items = {}

    def observe(self, item_id, delta: str) -> str | None:
        """Check new text, including suspicious runs wholly inside one delta."""
        state = self._items.get(item_id)
        if state is not None and state.reason == "agent_message_bytes":
            return state.reason
        # Empty notifications must not suppress validation of completed text.
        if not delta:
            return None
        if state is None:
            state = self._items[item_id] = _MessageState()
        for char in delta:
            # Count UTF-8 bytes without allocating an encoded copy of a possibly
            # large delta. Unicode scalar values use one through four bytes.
            codepoint = ord(char)
            state.bytes += (1 if codepoint < 0x80 else 2 if codepoint < 0x800
                            else 3 if codepoint < 0x10000 else 4)
            if state.bytes > _MAX_AGENT_MESSAGE_BYTES:
                state.reason = "agent_message_bytes"
                return state.reason

            # A quarantined stream still has a hard size ceiling while its
            # response finishes and the provider supplies token usage.
            if state.reason is not None:
                continue

            # The window stores classifications; repetition needs only the
            # previous character, not the underlying message text.
            kind = 2 if char == "\ufffd" else 1 if char.isspace() else 0
            if len(state.window) == _REPLACEMENT_WINDOW_CHARS:
                old = state.window.popleft()
                state.replacements -= old == 2
                state.blank_or_replacement -= old != 0
            state.window.append(kind)
            state.replacements += kind == 2
            state.blank_or_replacement += kind != 0
            state.whitespace = state.whitespace + 1 if kind == 1 else 0
            if state.whitespace >= _MAX_TRAILING_WHITESPACE_CHARS:
                state.reason = "trailing_whitespace"
            if (state.replacements >= _REPLACEMENT_MIN_CHARS
                    and state.blank_or_replacement * 10 >= len(state.window) * 9):
                state.reason = "replacement_character_flood"
            if kind == 1:
                state.last_character = None
                state.repeated_characters = 0
            else:
                state.repeated_characters = (state.repeated_characters + 1
                                             if char == state.last_character else 1)
                state.last_character = char
                if state.repeated_characters >= _MAX_REPEATED_CHARACTER_CHARS and state.reason is None:
                    state.reason = "repeated_character_flood"
        return state.reason

    def finish(self, item_id, text: str) -> str | None:
        """Validate a completed-only message, or release its streamed state.

        Completed text is authoritative even when some deltas were absent.
        Validate it with fresh counters so streamed bytes are not counted twice.
        """
        state = self._items.pop(item_id, None)
        reason = self.observe(item_id, text)
        self._items.pop(item_id, None)
        if reason != "agent_message_bytes" and state is not None and state.reason is not None:
            return state.reason
        return reason
