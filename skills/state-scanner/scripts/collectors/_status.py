"""Shared Status extraction + normalization used by requirements + openspec collectors.

6 regex variants per SKILL.md Phase 1.5. R1-I7 fix: pattern 4 allows optional
Markdown heading prefix `#{1,6} ` to catch `## Status: Active`.

i18n enhancement (Spec `state-scanner-i18n-status-regex`, 2026-04-25): patterns
2/3/4 widened to accept BOTH halfwidth `:` (U+003A) and fullwidth `：` (U+FF1A)
via `[：:]` character class — fullwidth colon is the default produced by
Chinese IMEs in markdown documents. Pattern 6 (NEW) captures inline blockquote
multi-meta lines like `> **优先级**：P0 | **状态**：pending` where status is
not the first key on the line. Pattern 5 (table) already supported `[：:]`.

Lifecycle-head extraction (Spec `state-scanner-status-extraction-range`, #50,
2026-05-21): large specs write the Status field as a single-line mini-changelog
(sub-task state + archival history + blockers) that can run 1500+ chars. The
`done`/`complete` fallback in `_normalize_status` would word-boundary-match a
token buried deep in that narrative and mis-classify a still-blocked spec as
`done`. `_status_lifecycle_head` truncates the raw Status to its lifecycle-
bearing head segment (everything before the first documented separator) before
classification. `_extract_status` itself is UNCHANGED — it still returns the
full single line so `raw_status` keeps the complete narrative for display.
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

# Documented lifecycle-head separators (#50 fix, state-scanner-status-extraction-range):
#   - em-dash U+2014 / en-dash U+2013, with optional surrounding whitespace
#     (`\s*` both sides) — covers spaceless `delivered—blocked` variants
#   - ASCII hyphen REQUIRING whitespace on both sides (`\s-\s`) — a tolerated
#     narrative separator; the mandatory spaces prevent mis-cutting word-internal
#     hyphens like `PR-A` or dates `2026-05-09`
#   - half/full-width semicolon `;` `；`, full-width period `。`
# Deliberately EXCLUDED: comma `,` (lifecycle phrases like `Approved, revised`
# must survive) and ASCII period `.` (would mis-cut version strings like `v2.0`).
_STATUS_HEAD_SEPARATOR_RE = re.compile(r"\s*[—–]\s*|\s-\s|[;；。]")

# Char-cap backstop: legitimate lifecycle-head segments in the Aria/nexus corpus
# measure < ~90 chars; 200 gives ~2x headroom. The cap only fires when the head
# contains NO documented separator at all (pathological token-free long openers).
_STATUS_HEAD_MAX_CHARS = 200


def _extract_status(text: str) -> str | None:
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


def _status_lifecycle_head(raw: str | None) -> tuple[str, bool]:
    """Return ``(lifecycle-bearing head segment, truncated_by_cap)``.

    Truncates ``raw`` at the first documented separator (see
    ``_STATUS_HEAD_SEPARATOR_RE``); if the resulting head still exceeds
    ``_STATUS_HEAD_MAX_CHARS`` it is hard-cut and ``truncated_by_cap`` is True.

    None-safe: ``raw is None`` → ``("", False)``. This guard is REQUIRED because
    ``_status_field_overlong`` calls this helper directly on a collector path
    where ``_extract_status`` may have returned ``None``.

    `_extract_status` is intentionally NOT changed — it still returns the full
    single-line raw Status so the snapshot `raw_status` field keeps the complete
    narrative for human display. Truncation here is for lifecycle classification
    only. See Spec `state-scanner-status-extraction-range` (Forgejo aria-plugin
    #50) for the full design rationale.
    """
    if raw is None:
        return "", False
    m = _STATUS_HEAD_SEPARATOR_RE.search(raw)
    head = (raw[: m.start()] if m else raw).strip()
    truncated = False
    if len(head) > _STATUS_HEAD_MAX_CHARS:
        head = head[:_STATUS_HEAD_MAX_CHARS]
        truncated = True
    return head, truncated


def _status_field_overlong(raw: str | None) -> bool:
    """True when the Status head segment hit the char-cap (no separator + overlong).

    Thin predicate over `_status_lifecycle_head` so collectors can emit a
    `status_field_truncated` soft_error without touching `_normalize_status`
    (whose `(raw) -> str` signature is contract-frozen for 21 regression tests).
    """
    return _status_lifecycle_head(raw)[1]


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
      2. Transitional family (#73 — implementation-complete / -done phrases)
      3. Pending family (draft / pending / placeholder)
      4. In-progress family (multi-word + i18n; literal substring is unambiguous)
      5. approved (BEFORE implemented — "Approved (Implemented by PR-A)" → approved)
      6. implemented (also delivered / shipped — #50 fix, all → implemented)
      7. reviewed / active / ready
      8. done / complete — LAST fallback (prevents the original #101 substring shadow)

    Classification operates on the lifecycle-head segment only (`_status_lifecycle_head`,
    #50 fix) — narrative after the first documented separator does NOT participate,
    so a `done` token buried in a long mini-changelog Status cannot shadow the head.
    The `(raw) -> str` signature is unchanged.

    Word-boundary matching via `_has_token` roots out the entire substring-shadow
    bug class (#101 primary + secondary). Multi-word phrases use literal substring
    because they cannot be ambiguous within Status strings.

    See:
      - Forgejo Aria #101 (substring shadow) + aria-plugin #50 (extraction range)
      - openspec/archive/2026-05-13-aria-issue-101-status-normalize/
      - openspec/changes/state-scanner-status-extraction-range/ (#50 fix proposal)
    """
    if raw is None:
        return "unknown"
    head, _ = _status_lifecycle_head(raw)  # #50 fix: classify on lifecycle head only
    low = head.lower()

    # Terminal states first (irreversible lifecycle endpoints)
    if _has_token(low, "archived"):
        return "archived"
    if _has_token(low, "deprecated"):
        return "deprecated"

    # Transitional family (#73 fix, 2026-05-20): hyphenated multi-word phrases
    # semantically equivalent to `implemented` (post-merge, awaiting verify/archive).
    # MUST precede the Pending family — strings like "Implementation-Complete-Pending-Obs"
    # also contain a `pending` token (word-boundary match on `pending-obs`) and would
    # otherwise mis-route to `pending`, which downstream breaks requirements.py:56
    # priority_items surface (filters status ∈ {in_progress, ready, pending}).
    # See openspec/archive/2026-05-20-state-scanner-bugfix-locale-and-transitional-status/
    # for full rationale + Aria #73 history.
    for phrase in ("implementation-complete", "implementation-done"):
        if phrase in low:
            return "implemented"

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
    # implemented family (#101 fix Bug 2: implemented was missing from dict;
    # #50 fix: delivered / shipped are synonyms — post-merge work that is delivered)
    if (
        _has_token(low, "implemented")
        or _has_token(low, "delivered")
        or _has_token(low, "shipped")
    ):
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
