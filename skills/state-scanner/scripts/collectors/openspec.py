"""Phase 1.6 — OpenSpec (changes + archive) collector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult
from ._status import _extract_status, _normalize_status

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


def collect_openspec(project_root: Path) -> CollectorResult:
    """Scan openspec/changes/ + openspec/archive/ for active + archived Specs."""
    r = CollectorResult()
    spec_root = project_root / "openspec"
    changes_dir = spec_root / "changes"
    archive_dir = spec_root / "archive"

    if not changes_dir.is_dir():
        r.data = {
            "configured": False,
            "changes": {"total": 0, "items": []},
            "archive": {"total": 0, "items": []},
            "pending_archive": [],
            "carry_forward_inventory": {
                "total": 0,
                "active_change_count": 0,
                "by_change": {},
            },
        }
        return r

    change_items: list[dict[str, Any]] = []
    pending_archive: list[dict[str, Any]] = []
    carry_forward_by_change: dict[str, dict[str, Any]] = {}
    carry_forward_total = 0
    for d in sorted(changes_dir.iterdir()):
        if not d.is_dir():
            continue
        proposal = d / "proposal.md"
        if not proposal.exists():
            continue
        try:
            raw = _extract_status(proposal.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            r.soft_error("spec_read_failed", f"{d.name}: {e}")
            continue
        st = _normalize_status(raw)
        item = {
            "id": d.name,
            "path": str(proposal.relative_to(project_root)),
            "status": st,
            "raw_status": raw,
        }
        change_items.append(item)
        if st == "done":
            pending_archive.append({"id": d.name, "reason": "Status=done still in changes/"})

        # Phase 1.6.1: scan tasks.md for inline carry-forward annotations
        tasks_file = d / "tasks.md"
        if tasks_file.is_file():
            try:
                tasks_content = tasks_file.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                r.soft_error("tasks_read_failed", f"{d.name}: {e}")
                continue
            matches = _extract_carry_forward_annotations(tasks_content)
            if matches:
                samples = [
                    (m[:80] + "...") if len(m) > 80 else m
                    for m in matches[:3]
                ]
                carry_forward_by_change[d.name] = {
                    "count": len(matches),
                    "samples": samples,
                }
                carry_forward_total += len(matches)

    archive_items: list[dict[str, Any]] = []
    if archive_dir.is_dir():
        for d in sorted(archive_dir.iterdir()):
            if not d.is_dir():
                continue
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", d.name)
            archive_items.append(
                {
                    "path": str(d.relative_to(project_root)),
                    "date": m.group(1) if m else None,
                    "feature": m.group(2) if m else d.name,
                }
            )

    r.data = {
        "configured": True,
        "changes": {"total": len(change_items), "items": change_items},
        "archive": {"total": len(archive_items), "items": archive_items},
        "pending_archive": pending_archive,
        "carry_forward_inventory": {
            "total": carry_forward_total,
            "active_change_count": len(change_items),
            "by_change": carry_forward_by_change,
        },
    }
    return r
