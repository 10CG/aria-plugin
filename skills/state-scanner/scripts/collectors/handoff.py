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
- latest_source: str | None — "pointer" (latest.md target) | "mtime" (fallback)
  | None (no canonical files / stat failed). H5 fix: pointer is the
  human-maintained semantic "latest"; mtime only wins when pointer is
  absent/unparseable/stale.
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

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._common import CollectorResult

# ─── TASK-009 (b): frontmatter-aware helper ──────────────────────────────────
# Added for OpenSpec `multi-terminal-coordination` (v1.22.x+).
# TASK-004 (state-scanner Phase 1 cross-branch track rebuild) will consume
# `parse_handoff_frontmatter` to parse all remote docs/handoff/*.md and
# reconstruct the multi-track dashboard.
# THIS HELPER IS ADDITIVE — it does NOT modify collect_handoff() main flow.
# ─────────────────────────────────────────────────────────────────────────────

# Required frontmatter fields per §2.3.1 schema.
# Any subset with fewer than all 5 keys present is treated as incomplete
# (legacy fallback per §2.3.4).
_FRONTMATTER_REQUIRED_KEYS = frozenset(
    {"track-id", "owner-container", "phase", "status", "updated-at"}
)

# Matches the opening and closing `---` fence of a YAML frontmatter block
# positioned at the very top of the file (first line must be `---`).
_FRONTMATTER_RE = re.compile(
    r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)",
    re.DOTALL,
)


def parse_handoff_frontmatter(content: str) -> Optional[dict]:
    """Parse machine-readable YAML frontmatter from a session handoff doc.

    Implements the §2.3.1 schema defined in
    ``standards/conventions/session-handoff.md §2.3.1`` (v1.1.0, added by
    OpenSpec ``multi-terminal-coordination``).

    The frontmatter block must be the very first thing in the file:

    .. code-block:: yaml

        ---
        track-id: multi-terminal-coordination
        owner-container: creationhikari/devbox-A
        phase: A.2
        status: active
        updated-at: 2026-05-19T22:31:13Z
        ---

    Args:
        content: Full text of the handoff document (already read from disk).

    Returns:
        A ``dict`` with exactly the 5 required keys when the frontmatter is
        present **and** structurally complete::

            {
                "track-id": str,
                "owner-container": str,
                "phase": str,
                "status": str,
                "updated-at": str,
            }

        Returns ``None`` in all failure / legacy-doc scenarios:

        * No ``---`` frontmatter fence at the top of the file (legacy doc
          written before v1.1.0 — graceful ``legacy`` fallback per §2.3.4).
        * YAML parsing failure (``yaml.YAMLError`` or ``ImportError``).
        * Parsed result is not a ``dict`` (e.g. a bare YAML scalar).
        * One or more of the 5 required keys is absent from the parsed dict
          (schema incomplete — treated same as no frontmatter per §2.3.4).
        * Any required field value is not a plain string (type error).

    Callers (TASK-004) must handle ``None`` as the ``legacy`` track signal
    and fall back to mtime + filename parsing, consistent with the H5
    ``feedback_handoff_mtime_vs_pointer_divergence`` pattern.

    Examples::

        # Legacy handoff doc without frontmatter → None
        >>> parse_handoff_frontmatter("# Aria — Session Handoff\\n\\n## §0 ...\\n")
        None

        # Well-formed frontmatter → dict
        >>> doc = (
        ...     "---\\n"
        ...     "track-id: multi-terminal-coordination\\n"
        ...     "owner-container: creationhikari/devbox-A\\n"
        ...     "phase: A.2\\n"
        ...     "status: active\\n"
        ...     "updated-at: 2026-05-19T22:31:13Z\\n"
        ...     "---\\n"
        ...     "\\n"
        ...     "# Aria — Session Handoff\\n"
        ... )
        >>> result = parse_handoff_frontmatter(doc)
        >>> result == {
        ...     "track-id": "multi-terminal-coordination",
        ...     "owner-container": "creationhikari/devbox-A",
        ...     "phase": "A.2",
        ...     "status": "active",
        ...     "updated-at": "2026-05-19T22:31:13Z",
        ... }
        True
    """
    if not content:
        return None

    m = _FRONTMATTER_RE.match(content)
    if not m:
        # No frontmatter fence at the top → legacy doc, return None per §2.3.4.
        return None

    raw_yaml = m.group(1)

    try:
        import yaml  # lazy import — stdlib not available; yaml is optional dep
        parsed = yaml.safe_load(raw_yaml)
    except Exception:
        # YAML parse failure or yaml not installed → treat as malformed legacy.
        return None

    if not isinstance(parsed, dict):
        # Bare scalar / list YAML at frontmatter position — not a valid schema.
        return None

    # Verify all 5 required keys are present (§2.3.1 "必含 ✅").
    if not _FRONTMATTER_REQUIRED_KEYS.issubset(parsed.keys()):
        return None

    # Verify every required value is a plain string (type guard for downstream).
    result: dict = {}
    for key in _FRONTMATTER_REQUIRED_KEYS:
        val = parsed[key]
        if not isinstance(val, str):
            # YAML might coerce e.g. `status: true` → bool; reject silently.
            return None
        result[key] = val

    return result

# ─────────────────────────────────────────────────────────────────────────────

CANONICAL_DIR = "docs/handoff/"
FORBIDDEN_DIR = ".aria/handoff/"
POINTER_FILENAME = "latest.md"  # not a handoff doc; excluded from latest detection

# `**Latest**: [filename](./filename) — desc` — capture the link target or the
# bracketed text. H5 fix: pointer is the human-maintained semantic "latest";
# mtime is only a fallback (a predecessor handoff edited post-hoc — closeout /
# rebase / typo fix — gets the newest mtime and would otherwise shadow the
# real latest). See memory feedback_handoff_mtime_vs_pointer_divergence.
_LATEST_POINTER_RE = re.compile(
    r"^\*\*Latest\*\*:\s*\[[^\]]+\]\(\.?/?([^)]+?)\)",
    re.MULTILINE,
)


def _parse_latest_pointer(canonical: Path) -> str | None:
    """Return the filename the docs/handoff/latest.md pointer targets, or None.

    Defensive: missing latest.md, unreadable, or unparseable → None (caller
    falls back to mtime sort).
    """
    pointer = canonical / POINTER_FILENAME
    if not pointer.is_file():
        return None
    try:
        text = pointer.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _LATEST_POINTER_RE.search(text)
    if not m:
        return None
    target = m.group(1).strip()
    # Normalize: strip any leading ./ and directory components — pointer
    # targets are siblings in the same dir.
    return Path(target).name or None


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
            "latest_source": None,
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
            "latest_source": None,
            "misplaced_files": misplaced,
            "canonical_dir": CANONICAL_DIR,
        }
        return r

    # H5 fix: prefer the latest.md pointer target (human-maintained semantic
    # "Latest") over raw mtime. mtime-max only wins when the pointer is
    # absent / unparseable / targets a missing file.
    mtime_latest = max(canonical_files, key=lambda p: mtimes[p])
    latest = mtime_latest
    latest_source = "mtime"

    pointer_target = _parse_latest_pointer(canonical)
    if pointer_target and pointer_target != POINTER_FILENAME:
        by_name = {p.name: p for p in canonical_files}
        resolved = by_name.get(pointer_target)
        if resolved is not None:
            latest = resolved
            latest_source = "pointer"
        # pointer target not among canonical files (stale pointer) → keep
        # mtime fallback; surface as soft signal for L3/AI awareness.
        else:
            r.soft_error(
                "handoff_pointer_target_missing",
                f"latest.md points to '{pointer_target}' but it is absent "
                f"in {CANONICAL_DIR}; fell back to mtime latest "
                f"'{mtime_latest.name}'",
            )

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
        "latest_source": latest_source,  # "pointer" | "mtime" (H5 transparency)
        "misplaced_files": misplaced,
        "canonical_dir": CANONICAL_DIR,
    }
    return r
