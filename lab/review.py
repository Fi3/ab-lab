"""Priority-labelled reviews and the configured repair threshold."""
import re


PRIORITIES = ("P0", "P1", "P2", "P3")
DEFAULT_PRIORITIES = PRIORITIES[:3]
_FINDING = re.compile(r"^(?:[-*+]|\d+[.)])\s+\[(P[0-3])\]\s+(\S.*)$")


def normalize_priorities(value):
    """Canonicalize a nonempty comma-separated string or sequence."""
    values = value.split(",") if isinstance(value, str) else value
    try:
        values = tuple(item.strip().upper() for item in values)
    except (AttributeError, TypeError):
        raise ValueError("review priorities must be a nonempty set of P0, P1, P2, P3") from None
    if not values or any(item not in PRIORITIES for item in values):
        raise ValueError("review priorities must be a nonempty set of P0, P1, P2, P3")
    return tuple(priority for priority in PRIORITIES if priority in values)


def parse_review(reply, priorities=DEFAULT_PRIORITIES):
    """Retain advisory findings without treating malformed replies as approval."""
    priorities = normalize_priorities(priorities)
    lines = reply.splitlines()
    markers = [(i, line.strip()) for i, line in enumerate(lines)
               if line.strip() in ("NO_FINDINGS", "FINDINGS", "INCOMPLETE_REVIEW")]
    if len(markers) != 1:
        raise ValueError("review needs exactly one NO_FINDINGS, FINDINGS or INCOMPLETE_REVIEW marker; malformed review is not approval")
    index, marker = markers[0]
    if any(line.strip() for line in lines[:index]):
        raise ValueError("review must start with its NO_FINDINGS, FINDINGS or INCOMPLETE_REVIEW marker")
    body = lines[index+1:]
    if marker == "INCOMPLETE_REVIEW":
        reason = "\n".join(body).strip()
        if not reason:
            raise ValueError("INCOMPLETE_REVIEW requires an explanation")
        return {"approved": None, "blocking_findings": [], "advisory_findings": [], "incomplete_reason": reason}
    findings = []
    if marker == "NO_FINDINGS":
        if any(re.search(r"\[P\d+\]", line) or re.match(r"\s*(?:[-*+]|\d+[.)])\s", line)
               for line in body):
            raise ValueError("NO_FINDINGS cannot include findings")
    else:
        for line in body:
            if not line.strip():
                continue
            match = _FINDING.fullmatch(line.lstrip())
            if match:
                findings.append({"priority": match[1], "text": match[2]})
            elif re.match(r"\s*(?:[-*+]|\d+[.)])\s+\[", line):
                raise ValueError("review finding has an invalid priority label or empty description")
            elif findings and line[:1].isspace():
                findings[-1]["text"] += "\n" + line
            else:
                raise ValueError("each review finding must start with '- [P0|P1|P2|P3] text'; indent continuation lines")
        if not findings:
            raise ValueError("FINDINGS must include at least one priority-labelled finding")
    blocking = [item for item in findings if item["priority"] in priorities]
    advisory = [item for item in findings if item["priority"] not in priorities]
    return {"approved": not blocking, "blocking_findings": blocking, "advisory_findings": advisory}


def review_clean(reply, priorities=DEFAULT_PRIORITIES):
    return parse_review(reply, priorities)["approved"]


def format_findings(findings):
    return "FINDINGS\n" + "\n".join(f"- [{item['priority']}] {item['text']}" for item in findings)


def review_instructions(priorities=DEFAULT_PRIORITIES):
    selected = ", ".join(normalize_priorities(priorities))
    return f"""Assign each finding a priority based on demonstrated impact:
P0: critical blocker requiring immediate correction.
P1: high-impact defect that breaks essential required behavior.
P2: concrete functional defect, regression, or substantial maintainability problem with explained impact.
P3: low-impact nit, cosmetic preference, or optional improvement.
For each finding identify the affected requirement or code behavior, a reproducer or concrete evidence, and the impact. Missing tests must cover a concrete behavioral risk; do not invent requirements or demand unspecified invalid-input handling. Significant duplication or complexity can be P2 when its maintenance impact is demonstrated.
Report findings at all priorities. Only {selected} trigger repairs; all other priorities are advisory. Do not inflate a priority to make a finding block. Recheck earlier blocking findings and inspect repairs for regressions.
Start with exactly one standalone marker NO_FINDINGS if there are no findings at any priority, otherwise FINDINGS. If you cannot reach a supported verdict, use INCOMPLETE_REVIEW followed by the specific missing evidence; an incomplete review is never approval.
After FINDINGS, use one top-level bullet per finding in this exact format: - [P2] description. Use its actual P0/P1/P2/P3 label, indent continuation lines, and include no other prose. Advisory-only reviews must still use FINDINGS; the runner decides whether repairs are required."""


def conclusion_prompt(priorities=DEFAULT_PRIORITIES):
    return ("The runner reached the review exploration threshold. Conclude this same review now using "
            "the evidence already collected. Do not start new tools, tests, searches, edits or delegation. "
            "Return the concrete findings you have established, applying the unchanged requirements and "
            "priorities. Do not approve because time or tokens are limited. If the available evidence "
            "cannot support a verdict, return INCOMPLETE_REVIEW and explain what remains unverified.\n\n" +
            review_instructions(priorities))
