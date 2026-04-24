"""Shared Status extraction + normalization used by requirements + openspec collectors.

5 regex variants per SKILL.md Phase 1.5. R1-I7 fix: pattern 4 allows optional
Markdown heading prefix `#{1,6} ` to catch `## Status: Active`.
"""

from __future__ import annotations

import re

_STATUS_PATTERNS = [
    re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*状态\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^>\s*\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(?:#{1,6}\s+)?Status:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|", re.IGNORECASE | re.MULTILINE),
]


def _extract_status(text: str) -> str | None:
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


def _normalize_status(raw: str | None) -> str:
    """Normalize Status string to OpenSpec-aligned lifecycle states.

    Preserves semantic distinction between Draft / Reviewed / Approved / In Progress
    / Done / Active / Deprecated / Archived (R1-I5). `ready` is for User Stories
    with explicit `ready` marker only.
    """
    if raw is None:
        return "unknown"
    low = raw.lower()
    for token in ("archived",):
        if token in low:
            return "archived"
    for token in ("deprecated",):
        if token in low:
            return "deprecated"
    for token in ("done", "complete"):
        if token in low:
            return "done"
    for token in ("in progress", "in_progress", "in-progress", "进行中"):
        if token in low:
            return "in_progress"
    if "approved" in low:
        return "approved"
    if "reviewed" in low:
        return "reviewed"
    if "active" in low:
        return "active"
    if "ready" in low:
        return "ready"
    for token in ("draft", "pending", "placeholder"):
        if token in low:
            return "pending"
    return "unknown"
