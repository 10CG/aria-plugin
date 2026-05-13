"""Shared Status extraction + normalization used by requirements + openspec collectors.

6 regex variants per SKILL.md Phase 1.5. R1-I7 fix: pattern 4 allows optional
Markdown heading prefix `#{1,6} ` to catch `## Status: Active`.

i18n enhancement (Spec `state-scanner-i18n-status-regex`, 2026-04-25): patterns
2/3/4 widened to accept BOTH halfwidth `:` (U+003A) and fullwidth `：` (U+FF1A)
via `[：:]` character class — fullwidth colon is the default produced by
Chinese IMEs in markdown documents. Pattern 6 (NEW) captures inline blockquote
multi-meta lines like `> **优先级**：P0 | **状态**：pending` where status is
not the first key on the line. Pattern 5 (table) already supported `[：:]`.
"""

from __future__ import annotations

import re

_STATUS_PATTERNS = [
    re.compile(r"^\*\*Status\*\*[：:]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*状态\*\*[：:]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^>\s*\*\*Status\*\*[：:]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(?:#{1,6}\s+)?Status[：:]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|", re.IGNORECASE | re.MULTILINE),
    # Pattern 6 (i18n, 2026-04-25): inline blockquote multi-meta. Matches
    # `> ... **状态**：pending | ...` regardless of position. Bounded right
    # side by `|` separator OR end-of-line so adjacent meta keys don't bleed in.
    re.compile(
        r"^>\s*.*?\*\*(?:Status|状态)\*\*[：:]\s*([^|\n]+?)(?=\s*(?:\||$))",
        re.IGNORECASE | re.MULTILINE,
    ),
]


def _extract_status(text: str) -> str | None:
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


def _has_token(text: str, token: str) -> bool:
    """Match `token` as a whole word in `text` (word-boundary anchored).

    Prevents substring shadowing — `inactive` no longer matches `active`,
    `unimplemented` no longer matches `implemented`, `incomplete` no longer
    matches `complete`, etc. Both arguments must already be lower-cased
    by the caller.

    Fixes Forgejo Aria #101 (substring matching false positives).
    """
    return re.search(r"\b" + re.escape(token) + r"\b", text) is not None


def _normalize_status(raw: str | None) -> str:
    """Normalize Status string to OpenSpec-aligned lifecycle states.

    Priority order (refined per Forgejo Aria #101 fix, 2026-05-13):
      1. Terminal (archived / deprecated) — irreversible
      2. Pending family (draft / pending / placeholder)
      3. In-progress family (multi-word + i18n; literal substring is unambiguous)
      4. approved (BEFORE implemented — "Approved (Implemented by PR-A)" → approved)
      5. implemented (NEW lifecycle state; was missing from token dictionary)
      6. reviewed / active / ready
      7. done / complete — LAST fallback (prevents the original #101 substring shadow)

    Word-boundary matching via `_has_token` roots out the entire substring-shadow
    bug class (#101 primary + secondary). Multi-word phrases use literal substring
    because they cannot be ambiguous within Status strings.

    See:
      - Forgejo Aria #101 (root cause + manual triage)
      - openspec/archive/2026-05-13-aria-issue-101-status-normalize/ (fix proposal)
    """
    if raw is None:
        return "unknown"
    low = raw.lower()

    # Terminal states first (irreversible lifecycle endpoints)
    if _has_token(low, "archived"):
        return "archived"
    if _has_token(low, "deprecated"):
        return "deprecated"

    # Pending family
    for token in ("draft", "pending", "placeholder"):
        if _has_token(low, token):
            return "pending"

    # In-progress family (multi-word phrases + i18n — literal substring is correct
    # here because these phrases are unambiguous within Status strings)
    for phrase in ("in progress", "in_progress", "in-progress", "进行中"):
        if phrase in low:
            return "in_progress"

    # approved BEFORE implemented (#101 fix BA-M2: "Approved (Implemented by PR-A)" → approved)
    if _has_token(low, "approved"):
        return "approved"
    if _has_token(low, "implemented"):  # #101 fix Bug 2: was missing from dict
        return "implemented"
    if _has_token(low, "reviewed"):
        return "reviewed"
    if _has_token(low, "active"):
        return "active"
    if _has_token(low, "ready"):
        return "ready"

    # done/complete LAST as fallback (#101 fix Bug 1: prevents substring shadow)
    for token in ("done", "complete"):
        if _has_token(low, token):
            return "done"

    return "unknown"
