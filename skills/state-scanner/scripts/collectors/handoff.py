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

`latest.md` (the navigation pointer file) is excluded from latest detection
to avoid surfacing the pointer instead of the actual newest handoff doc
(see QA-M2 finding in pre_merge R1 audit 2026-05-14).

Soft errors (emitted to `r.errors[]`, snapshot exit code 10):
- `handoff_canonical_scan_failed` — iterdir/permission failure on docs/handoff/
- `handoff_forbidden_scan_failed` — iterdir/permission failure on .aria/handoff/
- `handoff_stat_failed` — stat() failure on a candidate file (rare; race conditions)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ._common import CollectorResult

CANONICAL_DIR = "docs/handoff/"
FORBIDDEN_DIR = ".aria/handoff/"
POINTER_FILENAME = "latest.md"  # not a handoff doc; excluded from latest detection


class _ScanError(Exception):
    """Internal: signal that a directory scan failed (permission denied, etc.).

    Caught by `collect_handoff` to emit soft_error with directory context.
    Cannot use `r.soft_error` from `_scan_md_files` directly because the helper
    doesn't have access to the CollectorResult.
    """


def _scan_md_files(directory: Path) -> list[Path]:
    """Return handoff .md files directly in directory (non-recursive).

    Filters out the `latest.md` pointer file — it's a navigation aid, not a
    handoff document. Including it would cause mtime sort to always surface
    the pointer (which is updated on every handoff write) instead of the
    actual newest handoff doc (QA-M2 fix).

    Skips files whose names cannot be encoded as UTF-8 (non-UTF-8 filenames
    on the filesystem); these are extremely rare but possible on Linux.

    Raises `_ScanError` on iterdir/permission failure so the caller can emit
    a soft_error (QA-M1 fix — previously silent → exists=False with no error).
    """
    if not directory.is_dir():
        return []
    out: list[Path] = []
    try:
        for entry in directory.iterdir():
            try:
                _ = entry.name.encode("utf-8")
            except UnicodeError:
                continue
            if entry.is_file() and entry.suffix == ".md" and entry.name != POINTER_FILENAME:
                out.append(entry)
    except OSError as e:
        raise _ScanError(f"{directory}: {e}") from e
    return out


def collect_handoff(project_root: Path) -> CollectorResult:
    r = CollectorResult()

    canonical = project_root / "docs" / "handoff"
    forbidden = project_root / ".aria" / "handoff"

    try:
        canonical_files = _scan_md_files(canonical)
    except _ScanError as e:
        r.soft_error("handoff_canonical_scan_failed", str(e))
        canonical_files = []

    try:
        forbidden_files = _scan_md_files(forbidden)
    except _ScanError as e:
        r.soft_error("handoff_forbidden_scan_failed", str(e))
        forbidden_files = []

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

    # Cache stat() results once (B-M1 fix — was calling stat() twice per file
    # due to max(key=...) discarding the StatResult, plus a second stat() on
    # the winning path. Gratuitous TOCTOU window even though both were in
    # the same try/except block).
    try:
        mtimes = {p: p.stat().st_mtime for p in canonical_files}
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

    latest = max(canonical_files, key=lambda p: mtimes[p])
    mtime = mtimes[latest]

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
