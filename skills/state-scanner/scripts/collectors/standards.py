"""Phase 1.9 — standards submodule presence collector."""

from __future__ import annotations

from pathlib import Path

from ._common import CollectorResult


def collect_standards(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    gitmodules = project_root / ".gitmodules"
    standards_dir = project_root / "standards"

    if not gitmodules.exists():
        r.data = {"registered": False, "initialized": False}
        return r

    try:
        text = gitmodules.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("gitmodules_read_failed", str(e))
        r.data = {"registered": False, "initialized": False}
        return r

    registered = "path = standards" in text or "path=standards" in text
    initialized = (
        standards_dir.is_dir() and any(standards_dir.iterdir()) if standards_dir.exists() else False
    )
    r.data = {"registered": registered, "initialized": initialized}
    return r
