"""Phase 1.6 — OpenSpec (changes + archive) collector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult
from ._status import _extract_status, _normalize_status


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
        }
        return r

    change_items: list[dict[str, Any]] = []
    pending_archive: list[dict[str, Any]] = []
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
    }
    return r
