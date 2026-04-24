"""Phase 1.5 (requirements) — PRD + User Stories collector."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import CollectorResult
from ._status import _extract_status, _normalize_status


def collect_requirements(project_root: Path) -> CollectorResult:
    """Scan docs/requirements/ for PRD + User Stories with Status extraction.

    R2-TL-3 + R2-NF-1: `by_status` is OPEN-ENDED. Consumers must not assume any
    specific key presence. Keys are normalized lifecycle states actually observed.
    """
    r = CollectorResult()
    req_dir = project_root / "docs" / "requirements"
    if not req_dir.is_dir():
        r.data = {
            "configured": False,
            "prd": [],
            "stories": {"total": 0, "by_status": {}, "items": []},
        }
        return r

    prd_items: list[dict[str, Any]] = []
    for prd_path in sorted(req_dir.glob("prd-*.md")):
        try:
            raw = _extract_status(prd_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            r.soft_error("prd_read_failed", f"{prd_path.name}: {e}")
            continue
        prd_items.append(
            {
                "path": str(prd_path.relative_to(project_root)),
                "status": _normalize_status(raw),
                "raw_status": raw,
            }
        )

    stories_dir = req_dir / "user-stories"
    story_items: list[dict[str, Any]] = []
    # R3-BA1: do NOT pre-seed; open-ended dynamic map.
    by_status: dict[str, int] = {}
    if stories_dir.is_dir():
        for us_path in sorted(stories_dir.glob("US-*.md")):
            try:
                raw = _extract_status(us_path.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                r.soft_error("us_read_failed", f"{us_path.name}: {e}")
                continue
            st = _normalize_status(raw)
            by_status[st] = by_status.get(st, 0) + 1
            story_items.append(
                {
                    "id": us_path.stem,
                    "path": str(us_path.relative_to(project_root)),
                    "status": st,
                    "raw_status": raw,
                }
            )

    r.data = {
        "configured": True,
        "prd": prd_items,
        "stories": {
            "total": len(story_items),
            "by_status": by_status,
            "items": story_items,
        },
    }
    return r
