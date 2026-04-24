"""Phase 0 — Interrupt recovery collector."""

from __future__ import annotations

import json
from pathlib import Path

from ._common import CollectorResult
from .git import _current_branch


def collect_interrupt_state(project_root: Path) -> CollectorResult:
    """Read .aria/workflow-state.json and report interrupt status.

    Output shape:
      {
        "present": bool,
        "status": "none" | "in_progress" | "suspended" | "failed" | "corrupted",
        "branch_anchor_match": bool | null,
        "session_age_seconds": int | null,
        "raw": {...} | null
      }
    """
    r = CollectorResult()
    state_file = project_root / ".aria" / "workflow-state.json"

    if not state_file.exists():
        r.data = {
            "present": False,
            "status": "none",
            "branch_anchor_match": None,
            "session_age_seconds": None,
            "raw": None,
        }
        return r

    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.soft_error("workflow_state_corrupted", str(e))
        r.data = {
            "present": True,
            "status": "corrupted",
            "branch_anchor_match": None,
            "session_age_seconds": None,
            "raw": None,
        }
        return r

    anchor_branch = (raw.get("git_anchor") or {}).get("branch")
    current_branch = _current_branch(project_root)
    branch_match = (
        (anchor_branch == current_branch) if (anchor_branch and current_branch) else None
    )

    r.data = {
        "present": True,
        "status": raw.get("status", "in_progress"),
        "branch_anchor_match": branch_match,
        "session_age_seconds": None,  # T1.2 defers session-age calc to later patch
        "raw": raw,
    }
    return r
