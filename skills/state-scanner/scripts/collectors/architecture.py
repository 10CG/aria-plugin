"""Phase 1.7 — Architecture status collector.

Regex hardening (Spec `state-scanner-collector-regex-hardening`, 2026-04-25):
- 3 field-extractor patterns widened to accept BOTH halfwidth `:` (U+003A)
  and fullwidth `：` (U+FF1A) via `[：:]` character class — fullwidth is the
  default produced by Chinese IMEs in markdown documents.
- Optional heading prefix `(?:#{1,6}\\s+)?` allows `## Status: Active` form
  alongside the existing `**Status**: Active` and `> **Status**: Active`.
- Pattern is `^(?:#{1,6}\\s+)?\\s*>?\\s*\\*\\*<KEY>\\*\\*[：:]\\s*<VAL>` —
  the union of: optional heading + optional blockquote + bold key + dual colon.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._common import CollectorResult

_ARCH_STATUS_PAT = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Status(?:\*\*)?[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ARCH_LAST_UPD = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Last Updated(?:\*\*)?[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ARCH_PRD = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Parent PRD(?:\*\*)?[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_PRD_PLACEHOLDER_MARKERS = {
    "tbd", "pending", "(pending)", "(tbd)", "n/a", "todo", "(todo)", "placeholder",
    "待填写", "待定", "未定",
}


def _is_real_prd_reference(parent_prd: str | None) -> bool:
    """Reject placeholder strings as chain_valid=True (audit IMP-2).

    A real PRD reference must be non-empty and not a known placeholder token.
    File-existence verification is deferred (filename vs markdown link variance).
    """
    if not parent_prd:
        return False
    low = parent_prd.strip().lower()
    if low in _PRD_PLACEHOLDER_MARKERS:
        return False
    return True


def collect_architecture(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    arch_file = project_root / "docs" / "architecture" / "system-architecture.md"
    if not arch_file.is_file():
        r.data = {
            "exists": False,
            "path": None,
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "chain_valid": None,
        }
        return r

    try:
        text = arch_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("arch_read_failed", str(e))
        r.data = {
            "exists": True,
            "path": str(arch_file.relative_to(project_root)),
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "chain_valid": None,
        }
        return r

    def _first(p: re.Pattern[str]) -> str | None:
        m = p.search(text)
        return m.group(1).strip() if m else None

    status = _first(_ARCH_STATUS_PAT)
    last_upd = _first(_ARCH_LAST_UPD)
    parent_prd = _first(_ARCH_PRD)
    chain_valid = _is_real_prd_reference(parent_prd)

    r.data = {
        "exists": True,
        "path": str(arch_file.relative_to(project_root)),
        "status": status,
        "last_updated": last_upd,
        "parent_prd": parent_prd,
        "chain_valid": chain_valid,
    }
    return r
