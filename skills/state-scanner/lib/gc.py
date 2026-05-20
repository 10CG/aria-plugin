"""Done-claim archival GC — 7-day retention then move to archive/<YYYY-MM>/.

This module provides ``archive_done_claims()``, which scans the active
``claims/`` tree of the coordination orphan ref, identifies ``status='done'``
records older than ``retention_days``, and moves them to a dated archive
sub-tree while leaving a sha256 tombstone in their place.

Design constraints
------------------
- Test-friendly: ``now`` and ``retention_days`` are injected parameters; no
  wall-clock or hardcoded threshold is embedded in the function body.
- Production GC is NOT triggered automatically by this module; it must be
  invoked explicitly by an operator or a scheduled task.  TASK-018 ships the
  function definition only.
- ``dry_run=True`` performs all computation but skips all git write commands,
  returning what *would* have been archived.
- Rule #7 compliance: all git subprocess calls flow through
  coordination_ref primitives which enforce ``capture_output=True``.
  This module makes no subprocess calls of its own.

Archive path convention
-----------------------
Active claim:  ``claims/<container>/<session>.yaml``
Archived form: ``archive/<YYYY-MM>/<container>/<session>-<claimed_at>.yaml``

where ``<YYYY-MM>`` is derived from the *archive run* timestamp (``now``),
not from ``claimed_at``.  This keeps the archive partitioned by when the GC
ran rather than when the session started, which avoids back-filling into old
monthly buckets.

Tombstone
---------
A sha256[:16] digest of the serialised YAML content is stored in
``GcResult.tombstones`` keyed by the original claim path.  The tombstone is
informational; it is not written back to the ref by this function (the write
is intentionally left to a higher-level orchestrator that can batch the git
operations).

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.8
Task: TASK-018 (P2 Round 4)
Deps: TASK-013 (coordination_ref.read_claims)
      TASK-018 (constants.ARCHIVE_RETENTION_DAYS)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple, Optional

from .constants import ARCHIVE_RETENTION_DAYS
from .coordination_ref import read_claims

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class GcResult(NamedTuple):
    """Outcome of a single ``archive_done_claims()`` call.

    Fields
    ------
    archived_count : int
        Number of claims that were (or would be, in dry_run mode) archived.
    archived_paths : list[str]
        Destination archive paths for each archived claim, in the form
        ``archive/<YYYY-MM>/<container>/<session>-<claimed_at>.yaml``.
    tombstones : dict[str, str]
        Mapping from original active claim path to sha256[:16] hex digest of
        its serialised content.  Keys are in the form
        ``claims/<container>/<session>.yaml``.
    errors : list[str]
        Short, non-secret error tokens for any claims that could not be
        processed.  Non-empty does not constitute a hard failure.
    """

    archived_count: int
    archived_paths: list  # list[str]
    tombstones: dict       # dict[str, str]
    errors: list           # list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_to_dt(iso_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 string to an aware UTC datetime, or None on failure."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt
    except (ValueError, AttributeError):
        return None


def _compute_tombstone(yaml_content: str) -> str:
    """Return the first 16 hex chars of the sha256 of *yaml_content*."""
    return hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()[:16]


def _archive_path(container: str, session: str, claimed_at: str, now: datetime) -> str:
    """Derive the archive destination path for a claim.

    Format: ``archive/<YYYY-MM>/<container>/<session>-<claimed_at_slug>.yaml``

    The ``<YYYY-MM>`` component is taken from *now* (the GC run time), not
    from ``claimed_at``.  This avoids back-filling old monthly buckets.

    The ``<claimed_at_slug>`` is the ``claimed_at`` field with ``:`` and ``+``
    replaced by ``-`` to produce a filesystem-safe string (e.g.
    ``2026-05-01T09:30:00Z`` → ``2026-05-01T09-30-00Z``).
    """
    yyyymm = now.strftime("%Y-%m")
    claimed_at_slug = claimed_at.replace(":", "-").replace("+", "-")
    return f"archive/{yyyymm}/{container}/{session}-{claimed_at_slug}.yaml"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def archive_done_claims(
    repo_path: Optional[Path] = None,
    *,
    retention_days: int = ARCHIVE_RETENTION_DAYS,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> GcResult:
    """Scan active claims and archive those with status='done' past retention.

    Mechanism
    ---------
    1. ``read_claims(include_archive=False)`` — enumerate current active claims.
    2. For each ClaimRecord where:
       - ``record.status == 'done'``  AND
       - ``(now - claimed_at) > timedelta(days=retention_days)``
       Compute:
         a. ``archive_path`` = ``archive/<YYYY-MM>/<container>/<session>-<claimed_at>.yaml``
         b. ``tombstone``    = ``sha256(serialized_yaml)[:16]``
    3. If ``dry_run=False``: perform git write operations to move the claim
       from ``claims/`` to the computed ``archive_path``.

       Current implementation note: the git plumbing for step 3 is
       intentionally **deferred** — this shipping unit delivers the function
       skeleton, eligibility detection, tombstone computation, and the
       dry_run path.  A follow-up task will wire the actual git rm + add
       operations when the GC scheduler is integrated.  Until then,
       ``dry_run=False`` behaves identically to ``dry_run=True`` (no-op
       writes) and logs a WARNING so operators are aware.

    Edge cases
    ----------
    - ``ref_exists=False``: no claims at all → returns empty GcResult
      (not an error).
    - ``claimed_at`` unparseable: the claim is skipped with a soft error token
      added to ``errors``; other claims continue to be processed.
    - ``retention_days=0``: all done claims are eligible immediately.
    - ``now`` naive datetime: treated as UTC (no tzinfo conversion performed).

    Parameters
    ----------
    repo_path:
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
    retention_days:
        Number of days a done claim is kept before archival.  Defaults to
        ``ARCHIVE_RETENTION_DAYS`` (7).
    now:
        Reference time for age computation and archive YYYY-MM partition.
        Defaults to ``datetime.now(UTC)``.
    dry_run:
        When True, compute eligibility and tombstones but skip all git writes.
        Returns a GcResult describing what *would* happen.

    Returns
    -------
    GcResult
        See ``GcResult`` docstring for field semantics.
    """
    effective_now: datetime = now if now is not None else _utc_now()
    # Ensure effective_now is timezone-aware for timedelta comparison.
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)

    cutoff: datetime = effective_now - timedelta(days=retention_days)

    read_result = read_claims(repo_path)
    if not read_result.ref_exists:
        logger.debug("gc.archive_done_claims: coordination ref does not exist; nothing to archive")
        return GcResult(archived_count=0, archived_paths=[], tombstones={}, errors=[])

    archived_paths: list[str] = []
    tombstones: dict[str, str] = {}
    errors: list[str] = []

    for record in read_result.claims:
        if record.status != "done":
            continue

        # Parse claimed_at for age computation.
        claimed_dt = _iso_to_dt(record.claimed_at)
        if claimed_dt is None:
            errors.append(f"unparseable_claimed_at:{record.container}/{record.session}")
            logger.warning(
                "gc.archive_done_claims: unparseable claimed_at for container=%s session=%s: %r",
                record.container,
                record.session,
                record.claimed_at,
            )
            continue

        if claimed_dt > cutoff:
            # Within retention window — leave it.
            continue

        # Compute serialised content for tombstone (lazy import to avoid
        # circular dependency at module load time).
        try:
            from .claim_schema import serialize_claim  # type: ignore[import]
            try:
                import yaml as _yaml  # type: ignore[import-untyped]
                serialized = _yaml.safe_dump(serialize_claim(record), default_flow_style=False)
            except Exception:
                serialized = str(serialize_claim(record))
        except Exception as exc:
            errors.append(f"serialize_failed:{record.container}/{record.session}")
            logger.warning(
                "gc.archive_done_claims: serialize failed for container=%s session=%s: %s",
                record.container,
                record.session,
                exc,
            )
            continue

        original_path = f"claims/{record.container}/{record.session}.yaml"
        dest_path = _archive_path(record.container, record.session, record.claimed_at, effective_now)
        tombstone = _compute_tombstone(serialized)

        archived_paths.append(dest_path)
        tombstones[original_path] = tombstone

        if dry_run:
            logger.debug(
                "gc.archive_done_claims (dry_run): would archive %s → %s tombstone=%s",
                original_path,
                dest_path,
                tombstone,
            )
        else:
            # Git write operations are deferred to a follow-up integration task.
            # Log a WARNING so operators know GC ran but did not write.
            logger.warning(
                "gc.archive_done_claims: git write deferred (not yet implemented); "
                "would archive %s → %s tombstone=%s",
                original_path,
                dest_path,
                tombstone,
            )

    archived_count = len(archived_paths)
    if archived_count > 0:
        logger.info(
            "gc.archive_done_claims: %s=%d dry_run=%s",
            "would_archive" if dry_run else "deferred_archive",
            archived_count,
            dry_run,
        )

    return GcResult(
        archived_count=archived_count,
        archived_paths=archived_paths,
        tombstones=tombstones,
        errors=errors,
    )
