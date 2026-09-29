"""Constrained Codex response format for the existing host operation protocol."""
import json
import shlex

from .host import MAX_FINAL_BYTES, Rejected, parse_operations


HOST_RESPONSE_FORMAT = "json-schema-host-operation-v1"
HOST_RESPONSE_INSTRUCTIONS = (
    "Host response format for this turn: return one JSON object matching the supplied "
    "output schema. This replaces only the @standalone text envelope: choose one "
    "operation with kind read, run, edit, discard, or done and its corresponding "
    "fields. Put the shell command in command, declared write paths in paths, and "
    "the complete patch in patch, without @standalone markers. Paths, commands, and "
    "reasons must each be single-line strings. A done operation has only kind. "
    "Return the operation as your final response and wait for the host result. "
    "All task requirements, patch-format rules, permissions, pending-change rules, "
    "checks, and completion requirements remain in force."
)

_LINE = {"type": "string", "pattern": r"^[^\r\n\u0000]+$"}
_FIELDS = {
    "read": {"path": _LINE},
    "run": {"paths": {"type": "array", "items": _LINE}, "command": _LINE},
    "edit": {"reason": _LINE, "patch": {"type": "string"}},
    "discard": {"reason": _LINE},
    "done": {},
}
HOST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"anyOf": [
            {"type": "object",
             "properties": {"kind": {"type": "string", "enum": [kind]}, **fields},
             "required": ["kind", *fields], "additionalProperties": False}
            for kind, fields in _FIELDS.items()
        ]},
    },
    "required": ["operation"],
    "additionalProperties": False,
}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _line(value, *, path=False):
    if (not isinstance(value, str) or not value or (not path and not value.strip())
            or any(c in value for c in "\r\n\x00")):
        raise ValueError("host operation fields require nonempty single-line strings")
    return value


def decode_host_response(text):
    """Validate the whole response, then preserve the existing host grammar."""
    try:
        if len(text.encode("utf-8")) > MAX_FINAL_BYTES:
            raise ValueError("host response exceeds 4 MiB")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid host response encoding or nesting") from exc
    if not isinstance(value, dict) or set(value) != {"operation"}:
        raise ValueError("host response requires exactly one operation object")
    op = value["operation"]
    if not isinstance(op, dict) or not isinstance(op.get("kind"), str):
        raise ValueError("host operation requires a kind")
    kind = op["kind"]
    if kind not in _FIELDS or set(op) != {"kind", *_FIELDS[kind]}:
        raise ValueError("unknown host operation or unexpected fields")
    for name in _FIELDS[kind]:
        if name not in ("paths", "patch"):
            _line(op[name], path=name == "path")
    if kind == "read":
        expected = (kind, op["path"])
        directive = "@standalone read " + shlex.quote(op["path"])
    elif kind == "run":
        paths = op["paths"]
        if not isinstance(paths, list):
            raise ValueError("host run paths must be an array")
        for path in paths:
            _line(path, path=True)
        expected = (kind, paths, op["command"])
        # The legacy parser locates a literal " -- " before shell-unquoting.
        # Escape every character so even a path named "--" or "a -- b"
        # cannot be mistaken for the command separator.
        declared = " ".join("".join("\\" + char for char in path) for path in paths)
        directive = "@standalone run " + (declared + " " if declared else "") + "-- " + op["command"]
    elif kind == "edit":
        if not isinstance(op["patch"], str) or not op["patch"] or "\x00" in op["patch"]:
            raise ValueError("host edit patch must be a nonempty string without NUL")
        expected = (kind, op["reason"], op["patch"].replace("\r\n", "\n"))
        directive = "@standalone edit " + op["reason"] + "\n" + op["patch"] + "\n@standalone end"
    elif kind == "discard":
        expected = (kind, op["reason"])
        directive = "@standalone discard " + op["reason"]
    else:
        expected = (kind,)
        directive = "@standalone done"
    try:
        if parse_operations(directive) != [expected]:
            raise ValueError("host operation cannot be represented without changing its meaning")
    except (Rejected, UnicodeError) as exc:
        raise ValueError("host operation cannot be represented by the host protocol") from exc
    return directive
