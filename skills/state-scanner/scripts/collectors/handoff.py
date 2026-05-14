"""Phase 1.15 — Session-handoff doc collector.

Surfaces the latest `docs/handoff/*.md` (canonical location per
`standards/conventions/session-handoff.md`) so state-scanner Phase 2
recommendation can prompt AI to read it before generating advice.

Additionally detects misplaced files under `.aria/handoff/*.md` (forbidden
location) — this is Layer 2 of the 5-layer defense-in-depth against handoff
dir drift. See OpenSpec `aria-ten-step-session-handoff-stage` proposal §Why.

Field shape (additive top-level `handoff` key in snapshot, schema 1.0):
- exists: bool — whether canonical dir has any .md file
- latest_path: str | None — relative path to newest .md by mtime
- latest_filename: str | None — basename of latest_path
- last_modified_iso: str | None — UTC ISO 8601 of latest mtime
- age_hours: float | None — (time.time() - mtime) / 3600
- misplaced_files: list[str] — relative paths under .aria/handoff/*.md
- canonical_dir: str — always "docs/handoff/" (for AI display)

`age_hours` uses `time.time()` not `datetime.now()` to avoid timezone/DST
pitfalls. mtime is filesystem-native UTC seconds-since-epoch.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ._common import CollectorResult

CANONICAL_DIR = "docs/handoff/"
FORBIDDEN_DIR = ".aria/handoff/"


def _scan_md_files(directory: Path) -> list[Path]:
    """Return all .md files directly in directory (non-recursive), defensively.

    Skips files whose names cannot be decoded as UTF-8 (non-UTF-8 filenames
    on the filesystem); these are extremely rare but possible on Linux.
    """
    if not directory.is_dir():
        return []
    out: list[Path] = []
    try:
        for entry in directory.iterdir():
            try:
                # Trigger UnicodeDecodeError for non-UTF-8 filenames before mtime call
                _ = entry.name.encode("utf-8")
            except UnicodeError:
                continue
            if entry.is_file() and entry.suffix == ".md":
                out.append(entry)
    except OSError:
        return []
    return out


def collect_handoff(project_root: Path) -> CollectorResult:
    r = CollectorResult()

    canonical = project_root / "docs" / "handoff"
    forbidden = project_root / ".aria" / "handoff"

    canonical_files = _scan_md_files(canonical)
    forbidden_files = _scan_md_files(forbidden)

    misplaced = sorted(
        str(p.relative_to(project_root)) for p in forbidden_files
    )

    if not canonical_files:
        r.data = {
            "exists": False,
            "latest_path": None,
            "latest_filename": None,
            "last_modified_iso": None,
            "age_hours": None,
            "misplaced_files": misplaced,
            "canonical_dir": CANONICAL_DIR,
        }
        return r

    try:
        latest = max(canonical_files, key=lambda p: p.stat().st_mtime)
        mtime = latest.stat().st_mtime
    except OSError as e:
        r.soft_error("handoff_stat_failed", str(e))
        r.data = {
            "exists": True,
            "latest_path": None,
            "latest_filename": None,
            "last_modified_iso": None,
            "age_hours": None,
            "misplaced_files": misplaced,
            "canonical_dir": CANONICAL_DIR,
        }
        return r

    age_hours = (time.time() - mtime) / 3600
    last_mod_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(
        timespec="seconds"
    )

    r.data = {
        "exists": True,
        "latest_path": str(latest.relative_to(project_root)),
        "latest_filename": latest.name,
        "last_modified_iso": last_mod_iso,
        "age_hours": round(age_hours, 2),
        "misplaced_files": misplaced,
        "canonical_dir": CANONICAL_DIR,
    }
    return r
