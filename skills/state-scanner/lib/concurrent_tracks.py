"""Concurrent active claim counter for Design A worktree triggering.

Scans refs/aria/coordination for all active claims belonging to the current
container and returns a result indicating whether a worktree is needed.

Design A trigger rule (multi-terminal-coordination proposal §What/Design A):
    active_count >= 2  →  needs_worktree=True
    active_count <= 1  →  needs_worktree=False

Tasks: TASK-023 (P3 Round 1)
Spec:  openspec/changes/multi-terminal-coordination/tasks.md §3.1
Deps:  TASK-013 (read_claims — coordination_ref.py)
       TASK-011 (get_container_id — identity.py)
       TASK-010 (ClaimRecord / STATUS_ENUM — claim_schema.py)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .coordination_ref import read_claims
from .identity import get_container_id

logger = logging.getLogger(__name__)

# The only status value that counts as "occupying" a track on this container.
# "yielded" = voluntarily paused; "done" = terminal; "unknown" = unreadable schema.
# "legacy" is not a real STATUS_ENUM value — absent from claim_schema.STATUS_ENUM;
# kept only in comments for clarity.
_ACTIVE_STATUS: str = "active"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConcurrentTracksResult:
    """Outcome of a single :func:`count_concurrent_tracks` call.

    Fields
    ------
    container_id : str
        The container identity that was queried.  Empty string when
        ``get_container_id()`` failed and no explicit override was given.
    active_count : int
        Number of claims under this container with ``status="active"``.
    active_track_ids : tuple[str, ...]
        The ``track_id`` values of those active claims, in iteration order.
        Empty tuple when ``active_count == 0``.
    needs_worktree : bool
        True when ``active_count >= 2`` (Design A trigger point).
        Always False on any error path (conservative default).
    error : str | None
        Short error token when something prevented a reliable count.
        None on full success (including the zero-claims case).
        Possible values:
          ``"container_id_unavailable"``  — get_container_id() returned empty
          ``"read_claims_failed:<token>"`` — coordination_ref.read_claims error
    """

    container_id: str
    active_count: int
    active_track_ids: tuple  # tuple[str, ...] — kept unparameterised for py3.8
    needs_worktree: bool
    error: Optional[str]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_concurrent_tracks(
    repo_path: Optional[Path] = None,
    container_id: Optional[str] = None,
) -> ConcurrentTracksResult:
    """Scan refs/aria/coordination for this container's active claim count.

    Reads all claim files from the coordination orphan ref and filters to
    those whose ``container`` field matches *container_id* and whose
    ``status`` is exactly ``"active"``.

    Active status semantics
    -----------------------
    Only ``status="active"`` claims are counted.  Excluded:
      - ``"yielded"``  — session has voluntarily paused the track
      - ``"done"``     — terminal state; track is finished
      - ``"unknown"``  — unrecognised schema version; semantics undefined

    Conservative failure behaviour
    -------------------------------
    Any error (container_id unavailable, read_claims hard failure) causes the
    function to return ``needs_worktree=False`` with a populated ``error``
    field.  Callers should treat an error result as "unable to determine" and
    fall back to single-terminal mode rather than blocking the user.

    Parameters
    ----------
    repo_path : Path | None
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
        Pass a ``tmp_path`` in tests to keep operations hermetic.
    container_id : str | None
        Override the container identity used for filtering.  When None the
        value is obtained from :func:`~.identity.get_container_id`.
        Inject in unit tests to avoid touching ``~/.aria/container-id``.

    Returns
    -------
    ConcurrentTracksResult
        See the dataclass docstring for field semantics.

    Examples
    --------
    Single active claim (no worktree needed)::

        result = count_concurrent_tracks(repo_path=tmp_path, container_id="devbox-A")
        assert result.active_count == 1
        assert result.needs_worktree is False

    Two concurrent active claims (worktree trigger)::

        result = count_concurrent_tracks(repo_path=tmp_path, container_id="devbox-A")
        assert result.active_count == 2
        assert result.needs_worktree is True
    """
    # ── Step 1: resolve container identity ───────────────────────────────────
    if container_id is None:
        container_id = get_container_id()

    if not container_id:
        logger.warning(
            "concurrent_tracks.count_concurrent_tracks: "
            "get_container_id() returned empty string"
        )
        return ConcurrentTracksResult(
            container_id="",
            active_count=0,
            active_track_ids=(),
            needs_worktree=False,
            error="container_id_unavailable",
        )

    # ── Step 2: read all claims from the coordination ref ────────────────────
    # include_archive=False: archived (done) claims are irrelevant here.
    # ref_exists=False is not an error — treated as 0 active claims.
    try:
        read_result = read_claims(
            repo_path if repo_path is not None else Path.cwd(),
            include_archive=False,
        )
    except Exception as exc:  # defensive: read_claims should not raise
        err_token = f"read_claims_failed:{type(exc).__name__}"
        logger.warning(
            "concurrent_tracks.count_concurrent_tracks: unexpected exception "
            "from read_claims: %s",
            exc,
        )
        return ConcurrentTracksResult(
            container_id=container_id,
            active_count=0,
            active_track_ids=(),
            needs_worktree=False,
            error=err_token,
        )

    # ref not bootstrapped yet — treat as 0 active claims, no error.
    if not read_result.ref_exists:
        logger.debug(
            "concurrent_tracks.count_concurrent_tracks: "
            "coordination ref does not exist; active_count=0 for container=%s",
            container_id,
        )
        return ConcurrentTracksResult(
            container_id=container_id,
            active_count=0,
            active_track_ids=(),
            needs_worktree=False,
            error=None,
        )

    # Propagate hard read errors (e.g. ls_tree_failed) as a warning but do not
    # abort — partial results are still usable.
    if read_result.errors:
        logger.warning(
            "concurrent_tracks.count_concurrent_tracks: "
            "read_claims reported %d error(s): %s",
            len(read_result.errors),
            read_result.errors[:3],  # cap log volume
        )

    # ── Step 3: filter to this container's active claims ─────────────────────
    active_track_ids = [
        c.track_id
        for c in read_result.claims
        if c.container == container_id and c.status == _ACTIVE_STATUS
    ]
    active_count = len(active_track_ids)

    logger.debug(
        "concurrent_tracks.count_concurrent_tracks: "
        "container=%s active_count=%d needs_worktree=%s",
        container_id,
        active_count,
        active_count >= 2,
    )

    return ConcurrentTracksResult(
        container_id=container_id,
        active_count=active_count,
        active_track_ids=tuple(active_track_ids),
        needs_worktree=active_count >= 2,
        error=None,
    )
