"""Phase 1.15 — Session-handoff doc collector.

Surfaces the latest `docs/handoff/*.md` (canonical location per
`standards/conventions/session-handoff.md`) so state-scanner Phase 2
recommendation can prompt AI to read it before generating advice.

Additionally detects misplaced files under `.aria/handoff/*.md` (forbidden
location) — this is Layer 2 of the 5-layer defense-in-depth against handoff
dir drift. See OpenSpec `aria-ten-step-session-handoff-stage` proposal §Why.

This module is **frontmatter-aware** via the additive helper
``parse_handoff_frontmatter()`` (TASK-009 b, multi-terminal-coordination v1.22.x+).
The helper parses the machine-readable YAML frontmatter schema (§2.3.1, 5 fields:
``track-id`` / ``owner-container`` / ``phase`` / ``status`` / ``updated-at``)
from a handoff doc string.  The main ``collect_handoff()`` flow is **not modified**
— it returns the same ``handoff`` snapshot fields as before (schema 1.0, backward
compatible).  The helper is consumed by ``collectors/handoff_multibranch.py``
(TASK-004) to reconstruct the multi-track dashboard from cross-branch fetched docs.

Field shape (additive top-level `handoff` key in snapshot, schema 1.0):
- exists: bool — whether canonical dir has any .md file
- latest_path: str | None — relative path of the resolved latest .md
- latest_filename: str | None — basename of latest_path
- last_modified_iso: str | None — UTC ISO 8601 of the selected doc's arbitration key (Aria#218)
- age_hours: float | None — (time.time() - arbitration key epoch) / 3600
- latest_source: str | None — "pointer" (latest.md target) | "frontmatter" (updated-at key) | "mtime" (fallback)
  | None (no canonical files / stat failed). H5 fix: pointer is the
  human-maintained semantic "latest"; mtime only wins when pointer is
  absent/unparseable/stale.
- latest_frontmatter_missing: bool — additive (#137, v1.43.0+); True when the
  resolved latest doc lacks §2.3.1 frontmatter (legacy → board owner=unknown);
  False when exists=False or stat failed (not applicable)
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
- `handoff_pointer_target_missing` — stale latest.md pointer (H5, pre-existing)
- `handoff_frontmatter_missing` — resolved latest doc lacks frontmatter (#137, v1.43.0+)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
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
        * Frontmatter body is empty or contains a line without ``:``.
        * One or more of the 5 required keys is absent from the parsed dict
          (schema incomplete — treated same as no frontmatter per §2.3.4).
        * Any required field value is not a plain string (type error).

    Implementation note: prior to v1.30.2 this used PyYAML (``yaml.safe_load``);
    fix for Forgejo aria-plugin #57 Finding 2 replaced PyYAML with a stdlib
    parser (`_parse_simple_yaml_frontmatter`) because PyYAML is not installed
    in fresh Claude Code sandboxes and the plugin had no install hook.

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
    parsed = _parse_simple_yaml_frontmatter(raw_yaml)
    if parsed is None:
        # Parse failure → treat as malformed legacy.
        return None

    # Verify all 5 required keys are present (§2.3.1 "必含 ✅").
    if not _FRONTMATTER_REQUIRED_KEYS.issubset(parsed.keys()):
        return None

    # All values from the stdlib parser are already strings (no datetime coercion
    # needed, unlike yaml.safe_load which auto-parses ISO timestamps to datetime
    # objects and caused a v1.22.0 zero-day production bug). Verify type defensively.
    result: dict = {}
    for key in _FRONTMATTER_REQUIRED_KEYS:
        val = parsed[key]
        if not isinstance(val, str):
            return None
        result[key] = val

    return result


def _parse_simple_yaml_frontmatter(raw: str) -> Optional[dict]:
    """Stdlib-only parser for the §2.3.1 5-field session-handoff frontmatter schema.

    Replaces the PyYAML dependency (fix for Forgejo aria-plugin #57 Finding 2,
    2026-05-28). PyYAML is not present in fresh Claude Code sandboxes (`pip` /
    `pip3` also absent — only `uv`), so PyYAML-dependent code paths produced
    100% legacy-fallback in `handoff_multibranch` collector, defeating the
    purpose of Layer H multi-terminal coordination.

    **Scope**: only handles flat ``key: value`` pairs with string-typed scalar
    values (the §2.3.1 schema requires exactly 5 such fields). Does **not**
    support nested mappings, multi-line strings (``|`` / ``>``), flow-style
    sequences, anchors, or any other YAML feature. This is deliberate — the
    schema is intentionally minimal so a 20-line stdlib parser suffices.

    Args:
        raw: The text between the opening and closing ``---`` fence (without
            the fence markers themselves).

    Returns:
        A ``dict`` of {key: str-value} entries, or ``None`` if parsing fails
        (empty input / line without ``:`` / empty key or value).

    Notes:
        - Values are returned as raw strings (no datetime / bool / int coercion);
          ISO 8601 timestamps stay as strings (avoiding the v1.22.0 datetime
          coercion zero-day bug).
        - Surrounding single or double quotes are stripped (``"value"`` and
          ``'value'`` both yield ``value``).
        - Lines starting with ``#`` are comments (ignored).
        - Blank lines are ignored.
    """
    if not raw or not raw.strip():
        return None

    result: dict = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Split on the *first* ':' (ISO timestamps contain colons in the time
        # portion, e.g. `updated-at: 2026-05-19T22:31:13Z` — only split once).
        if ":" not in stripped:
            return None
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip matching surrounding quotes (single or double).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key or not value:
            return None
        result[key] = value

    return result if result else None

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


@dataclass
class _LatestResolution:
    """Result of resolving the latest handoff doc in one canonical dir.

    Pure resolution output — ``_resolve_latest`` does NOT emit soft errors
    itself; it returns ``signals`` for the caller to emit. This lets the SAME
    helper serve both ``collect_handoff`` (current-tree framing — raw message)
    and the cross-worktree collector (#139 ``handoff_worktrees.py``, which
    prefixes messages with the worktree path). See OpenSpec
    ``cross-worktree-handoff-discovery`` §What Changes #1 (R2 N-3).
    """

    latest: Optional[Path]            # resolved latest doc; None if stat failed
    latest_source: Optional[str]      # "pointer" | "frontmatter" | "mtime" | None
    last_modified_iso: Optional[str]
    age_hours: Optional[float]
    mtime_epoch: Optional[float]      # raw st_mtime of latest (legacy-row input for handoff_worktrees; NOT the #218 arbitration key)
    stat_failed: bool
    # (soft_error_kind, message) pairs for the caller to emit as it sees fit.
    signals: list = field(default_factory=list)


def _parse_updated_at_epoch(value):
    """Parse an ISO-8601 ``updated-at`` to epoch seconds; None on failure.

    Compatible with both ``Z`` and ``+HH:MM`` offset forms WITHOUT relying on
    Python 3.11's ``fromisoformat`` ``Z`` support (the plugin sandbox has no
    Python-version floor — R2 N-4/I-3). Naive timestamps are assumed UTC.
    (Relocated from handoff_worktrees.py by Aria#218 — the base-layer resolver
    needs the same arbitration key; worktrees now imports it from here.)
    """
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _resolve_latest(
    canonical: Path, canonical_files: list[Path]
) -> _LatestResolution:
    """Resolve the latest handoff doc: pointer → per-file arbitration key.

    Given a NON-empty list of candidate ``.md`` files (caller guarantees
    non-empty — empty dir is handled before this point), return the resolved
    latest doc (``latest.md`` pointer target if it names a present file, else
    max by per-file arbitration key) plus key-derived iso/age, and any soft-error signals
    encountered along the way (stat failure, stale pointer).

    The caller decides whether/how to emit ``signals``: ``collect_handoff`` emits
    them verbatim (current-tree), while the cross-worktree collector prefixes the
    message with its worktree path (R2 N-3). This is also the mechanism that keeps
    ``collect_handoff`` behaviour byte-for-byte identical post-refactor.

    Arbitration key (Aria#218 — mtime is not content time: checkout / rebase /
    worktree-create rewrite it): frontmatter ``updated-at`` epoch when
    parseable, else mtime — the same key ``handoff_worktrees`` arbitrates on
    (``cmp_key_source``). ``latest_source`` ∈ "pointer" | "frontmatter" |
    "mtime". The result's ``mtime`` field stays the REAL mtime of the selected
    doc (handoff_worktrees consumes it for legacy rows). Does NOT scan
    directories (the caller passes ``canonical_files``).
    """
    signals: list = []
    # Cache stat() results once (B-M1 fix — migrated with the helper to preserve
    # collect_handoff behaviour; was calling stat() twice per file otherwise).
    try:
        mtimes = {p: p.stat().st_mtime for p in canonical_files}
    except OSError as e:
        signals.append(("handoff_stat_failed", str(e)))
        return _LatestResolution(None, None, None, None, None, True, signals)

    # Arbitration key per file (Aria#218): frontmatter updated-at epoch when
    # parseable, else mtime. Same semantics as handoff_worktrees cmp_key_source
    # (legacy doc → mtime key; malformed updated-at → honest mtime key).
    keys = {}
    key_sources = {}
    for p in canonical_files:
        ua = None
        try:
            fm = parse_handoff_frontmatter(
                p.read_text(encoding="utf-8", errors="replace")
            )
            ua = (fm or {}).get("updated-at")
        except OSError:
            ua = None
        epoch = _parse_updated_at_epoch(ua) if ua else None
        if epoch is not None:
            keys[p] = epoch
            key_sources[p] = "frontmatter"
        else:
            keys[p] = mtimes[p]
            key_sources[p] = "mtime"

    # H5 fix: prefer the latest.md pointer target (human-maintained semantic
    # "Latest") over any file-derived key. key-max only wins when the pointer
    # is absent / unparseable / targets a missing file.
    key_latest = max(canonical_files, key=lambda p: keys[p])
    latest = key_latest
    latest_source = key_sources[key_latest]

    pointer_target = _parse_latest_pointer(canonical)
    if pointer_target and pointer_target != POINTER_FILENAME:
        by_name = {p.name: p for p in canonical_files}
        resolved = by_name.get(pointer_target)
        if resolved is not None:
            latest = resolved
            latest_source = "pointer"
        # pointer target not among canonical files (stale pointer) → keep
        # mtime fallback; signal for L3/AI awareness (caller emits).
        else:
            signals.append(
                (
                    "handoff_pointer_target_missing",
                    f"latest.md points to '{pointer_target}' but it is absent "
                    f"in {CANONICAL_DIR}; fell back to key latest "
                    f"'{key_latest.name}'",
                )
            )

    # iso/age derive from the selected doc's arbitration key (Aria#218: a
    # checkout-rewritten mtime must not read as fresh; when the doc carries
    # updated-at, that content time is the honest "how old is this" answer).
    sel_epoch = keys[latest]
    age_hours = round((time.time() - sel_epoch) / 3600, 2)
    last_mod_iso = datetime.fromtimestamp(sel_epoch, tz=timezone.utc).isoformat(
        timespec="seconds"
    )
    return _LatestResolution(
        latest, latest_source, last_mod_iso, age_hours, mtimes[latest], False, signals
    )


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
            # additive (#137, v1.43.0+): no resolved latest doc → not applicable
            "latest_frontmatter_missing": False,
        }
        return r

    # Resolve the latest doc via the shared H5 pointer→mtime helper (#139:
    # _resolve_latest is also consumed by the cross-worktree collector).
    resolution = _resolve_latest(canonical, canonical_files)
    # Emit signals verbatim (current-tree framing). The cross-worktree collector
    # (#139) prefixes these with its worktree path instead (R2 N-3).
    for kind, msg in resolution.signals:
        r.soft_error(kind, msg)

    if resolution.stat_failed or resolution.latest is None:
        r.data = {
            "exists": True,
            "latest_path": None,
            "latest_filename": None,
            "last_modified_iso": None,
            "age_hours": None,
            "latest_source": None,
            "misplaced_files": misplaced,
            "canonical_dir": CANONICAL_DIR,
            # additive (#137, v1.43.0+): no resolved latest doc → not applicable
            "latest_frontmatter_missing": False,
        }
        return r

    latest = resolution.latest

    # #137 (handoff-frontmatter-enforcement, v1.43.0+): frontmatter content
    # enforcement on the RESOLVED latest doc — applies to both latest_source
    # paths (pointer AND mtime fallback; the mtime path is exactly the ad-hoc
    # handoff scenario from the SilkNode 2026-05-31 incident). Missing
    # frontmatter silently degrades the multi-track board to owner=unknown,
    # so surface it. read_text failure → silent skip (fail-soft, never blocks
    # collect_handoff return).
    latest_frontmatter_missing = False
    try:
        latest_content = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        latest_content = None
    if latest_content is not None and parse_handoff_frontmatter(latest_content) is None:
        latest_frontmatter_missing = True
        r.soft_error(
            "handoff_frontmatter_missing",
            f"{latest.name}: latest handoff lacks \u00a72.3.1 frontmatter "
            "\u2014 multi-track board will show owner=unknown",
        )

    r.data = {
        "exists": True,
        "latest_path": str(latest.relative_to(project_root)),
        "latest_filename": latest.name,
        "last_modified_iso": resolution.last_modified_iso,
        "age_hours": resolution.age_hours,
        "latest_source": resolution.latest_source,  # "pointer" | "frontmatter" | "mtime" (H5 + #218)
        # additive (#137, v1.43.0+): True when resolved latest doc lacks
        # §2.3.1 frontmatter (legacy → board shows owner=unknown)
        "latest_frontmatter_missing": latest_frontmatter_missing,
        "misplaced_files": misplaced,
        "canonical_dir": CANONICAL_DIR,
    }
    return r
