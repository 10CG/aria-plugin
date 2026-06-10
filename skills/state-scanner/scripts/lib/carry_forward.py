"""Inline carry-forward / defer annotation extraction — single regex SOT.

Physically moved from ``collectors/openspec.py`` (archive-completeness-gate
#134, A1.1b, DEC-20260609-001) so that ``lib/spec_complete.py`` can reuse the
SAME regex without creating a spec_complete ↔ openspec circular import.
``collectors/openspec.py`` re-imports both names from here, so the pattern
stays single-sourced (gap(b) closure must not double-write the regex).
"""

from __future__ import annotations

import re

_CARRY_FORWARD_RE = re.compile(
    r"\[(?:carry-forward|TODO|defer(?:red)?|known[ -]gap|PASS-with-note)\b[\s\S]*?\]"
)


def _extract_carry_forward_annotations(tasks_md_content: str) -> list[str]:
    """Extract inline carry-forward / TODO / defer / known-gap / PASS-with-note annotations.

    Pattern: r'\\[(?:carry-forward|TODO|defer(?:red)?|known[ -]gap|PASS-with-note)\\b[\\s\\S]*?\\]'
    - Positional anchoring: token group must touch opening '['
    - Token-end \\b blocks substring extension (carry-forwarded → not matched)
    - [\\s\\S]*? non-greedy cross-line capture
    - Multi-line normalization: \\r\\n + \\n + \\r → single space

    Returns raw matches preserving order of appearance. Non-greedy stop at first ']'.
    """
    raw_matches = _CARRY_FORWARD_RE.findall(tasks_md_content)
    return [
        m.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        for m in raw_matches
    ]
