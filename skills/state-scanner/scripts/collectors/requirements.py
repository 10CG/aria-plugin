"""Phase 1.5 (requirements) — PRD + User Stories collector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._common import CollectorResult
from ._status import _extract_status, _normalize_status

# G4 (state-scanner-inter-cycle-surfacing): priority_items derived view
# Status sort order: in_progress first (active work), then ready (next-up),
# then pending (queued). Other statuses excluded from priority_items.
_PRIORITY_STATUSES: dict[str, int] = {
    "in_progress": 0,
    "ready": 1,
    "pending": 2,
}
_DEFAULT_PRIORITY_ITEMS_LIMIT = 5


def _load_priority_items_limit(project_root: Path) -> int:
    """Read `.aria/config.json` → `state_scanner.priority_items_limit`.

    Missing file / missing key / malformed JSON / non-positive value → default 5.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.exists():
        return _DEFAULT_PRIORITY_ITEMS_LIMIT
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_PRIORITY_ITEMS_LIMIT
    ss = raw.get("state_scanner") or {}
    val = ss.get("priority_items_limit")
    if isinstance(val, int) and val > 0:
        return val
    return _DEFAULT_PRIORITY_ITEMS_LIMIT


def _derive_priority_items(
    story_items: list[dict[str, Any]],
    project_root: Path,
    limit: int,
) -> list[dict[str, Any]]:
    """G4: derive priority_items[] from collected story_items[].

    Per state-snapshot-schema.md §requirements.stories.priority_items:
    - Filter: status ∈ {in_progress, ready, pending}
    - Sort (3-level stable, deterministic across OS):
      1. status_order ASC (in_progress=0 < ready=1 < pending=2)
      2. file mtime DESC (most recent first)
      3. file path LEX ASC (alphabetic when status + mtime tie)
    - Slice: head N (default 5, config-driven)
    - mtime read once per selected candidate (N is small, no glob re-scan)
    """
    candidates: list[tuple[int, float, str, dict[str, Any]]] = []
    for item in story_items:
        status = item.get("status")
        if status not in _PRIORITY_STATUSES:
            continue
        rel_path = item.get("path")
        if not rel_path:
            continue
        abs_path = project_root / rel_path
        try:
            mtime = abs_path.stat().st_mtime
        except OSError:
            # File listed but stat fails (e.g., race / permission) — fail-soft:
            # treat as oldest so it sorts last within its status bucket.
            mtime = 0.0
        candidates.append(
            (
                _PRIORITY_STATUSES[status],
                -mtime,  # negate for DESC under default ASC sort
                rel_path,
                item,
            )
        )

    candidates.sort(key=lambda t: (t[0], t[1], t[2]))

    out: list[dict[str, Any]] = []
    for _order, _neg_mtime, rel_path, src in candidates[:limit]:
        out.append(
            {
                "id": src["id"],
                "status_normalized": src["status"],
                "raw_status": src.get("raw_status"),
                "priority_hint": None,  # future-extension placeholder
                "file": rel_path,
            }
        )
    return out


def collect_requirements(project_root: Path) -> CollectorResult:
    """Scan docs/requirements/ for PRD + User Stories with Status extraction.

    R2-TL-3 + R2-NF-1: `by_status` is OPEN-ENDED. Consumers must not assume any
    specific key presence. Keys are normalized lifecycle states actually observed.

    G4 (state-scanner-inter-cycle-surfacing 2026-05-09): also produces
    `stories.priority_items[]` — derived view of items[] filtered to
    in_progress/ready/pending and sorted for inter-cycle resume surfacing.
    """
    r = CollectorResult()
    req_dir = project_root / "docs" / "requirements"
    if not req_dir.is_dir():
        r.data = {
            "configured": False,
            "prd": [],
            "stories": {
                "total": 0,
                "by_status": {},
                "items": [],
                "priority_items": [],
            },
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

    limit = _load_priority_items_limit(project_root)
    priority_items = _derive_priority_items(story_items, project_root, limit)

    r.data = {
        "configured": True,
        "prd": prd_items,
        "stories": {
            "total": len(story_items),
            "by_status": by_status,
            "items": story_items,
            "priority_items": priority_items,
        },
    }
    return r
