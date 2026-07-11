"""Claim lifecycle operations — acquire / heartbeat / release.

This module provides the three public lifecycle functions that a session uses
to manage its own ClaimRecord on the coordination orphan ref.

Lifecycle transitions
---------------------

    acquire_claim()   — status: (none) → active
    heartbeat()       — status: active → active  (heartbeat_at updated)
    release_claim()   — status: active → done | yielded | abandoned

All three functions follow the same fail-soft contract: on any error the
returned AcquireResult has success=False and a short, non-secret error token
in the ``error`` field.  No exception is raised to the caller.

Rule #7 compliance
------------------
All subprocess I/O is routed through coordination_ref primitives which already
enforce capture_output=True.  This module contains no subprocess calls of its
own.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.8
Task: TASK-018 (P2 Round 4)
Deps: TASK-010 (claim_schema.py)
      TASK-011 (identity.py)
      TASK-013 (coordination_ref.write_claim / read_claims)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from .claim_schema import ClaimRecord, SCHEMA_VERSION_CURRENT
from .coordination_ref import write_claim, read_claims, WriteClaimResult
from .identity import Identity, get_identity
from .track_id import derive_track_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class AcquireResult(NamedTuple):
    """Outcome of an acquire_claim / heartbeat / release_claim call.

    Fields
    ------
    success : bool
        True when the claim was written to the coordination ref successfully.
    record : ClaimRecord | None
        The ClaimRecord that was written on success; None on failure.
    error : str | None
        Short, non-secret error token on failure; None on success.
        Possible values: "identity_error", "write_failed", "claim_not_found",
        "invalid_status".
    """

    success: bool
    record: Optional[ClaimRecord]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """Format a datetime as a UTC ISO 8601 string at seconds precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_identity(identity: Optional[Identity], repo_path: Optional[Path]) -> Optional[Identity]:
    """Return the provided identity or attempt to derive one automatically."""
    if identity is not None:
        return identity
    try:
        return get_identity()
    except Exception as exc:
        logger.warning("claim_lifecycle: get_identity() failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def acquire_claim(
    track_id: str,
    phase: str,
    identity: Optional[Identity] = None,
    repo_path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> AcquireResult:
    """Construct a new active ClaimRecord and write it to the coordination ref.

    Both ``claimed_at`` and ``heartbeat_at`` are set to ``now`` for a freshly
    acquired claim (they diverge only after subsequent heartbeat() calls).

    Parameters
    ----------
    track_id:
        The deterministic work identifier for the track being claimed
        (typically produced by lib/track_id.py::derive_track_id).
    phase:
        Ten-step-cycle phase string at acquisition time (e.g. ``"B.2"``).
    identity:
        Caller-supplied Identity.  When None, ``get_identity()`` is called
        automatically.  Callers should supply an explicit identity in tests to
        avoid touching the real ``~/.aria/container-id``.
    repo_path:
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
    now:
        Reference UTC time for both ``claimed_at`` and ``heartbeat_at``.
        Defaults to ``datetime.now(UTC)``.  Inject in tests for determinism.

    Returns
    -------
    AcquireResult
        On failure: ``success=False, record=None, error=<token>``.
    """
    resolved = _resolve_identity(identity, repo_path)
    if resolved is None:
        return AcquireResult(success=False, record=None, error="identity_error")

    ts = now if now is not None else _utc_now()
    ts_str = _iso(ts)

    record = ClaimRecord(
        schema_version=SCHEMA_VERSION_CURRENT,
        track_id=track_id,
        owner=resolved.owner,
        container=resolved.container_id,
        session=resolved.session_id,
        phase=phase,
        status="active",
        claimed_at=ts_str,
        heartbeat_at=ts_str,
        superseded_from=None,
    )

    result: WriteClaimResult = write_claim(record, repo_path)
    if not result.success:
        logger.warning(
            "claim_lifecycle.acquire_claim: write_claim failed: error=%s",
            result.error,
        )
        return AcquireResult(success=False, record=None, error=result.error or "write_failed")

    logger.info(
        "claim_lifecycle.acquire_claim: acquired track=%s phase=%s container=%s session=%s",
        track_id,
        phase,
        resolved.container_id,
        resolved.session_id,
    )
    return AcquireResult(success=True, record=record, error=None)


def heartbeat(
    track_id: str,
    identity: Optional[Identity] = None,
    repo_path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> AcquireResult:
    """Refresh the ``heartbeat_at`` timestamp of this session's existing claim.

    Mechanism:
    1. ``read_claims()`` — fetch all current claim records.
    2. Locate the record matching this session's ``(container_id, session_id)``.
    3. Build an updated record with ``heartbeat_at=now`` (all other fields
       preserved, including ``claimed_at`` and ``phase``).
    4. ``write_claim()`` — overwrite the claim file in the ref.

    Parameters
    ----------
    track_id:
        The track the claim was acquired for.  Used only for log context;
        the actual claim is matched by ``(container_id, session_id)`` because
        those are the path components in the coordination ref tree.
    identity:
        Caller-supplied Identity.  When None, ``get_identity()`` is called.
        Note: ``get_identity()`` generates a *fresh* session_id on each call,
        which would NOT match the original claim.  Callers must supply the
        same Identity instance used in ``acquire_claim()`` when calling
        heartbeat() in production code.
    repo_path:
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
    now:
        Reference UTC time for the new ``heartbeat_at``.  Defaults to
        ``datetime.now(UTC)``.

    Returns
    -------
    AcquireResult
        ``error='claim_not_found'`` when no matching record exists.
    """
    resolved = _resolve_identity(identity, repo_path)
    if resolved is None:
        return AcquireResult(success=False, record=None, error="identity_error")

    read_result = read_claims(repo_path)
    if not read_result.ref_exists:
        return AcquireResult(success=False, record=None, error="claim_not_found")

    # Locate the record owned by this (container_id, session_id) pair.
    existing: Optional[ClaimRecord] = None
    for rec in read_result.claims:
        if rec.container == resolved.container_id and rec.session == resolved.session_id:
            existing = rec
            break

    if existing is None:
        logger.warning(
            "claim_lifecycle.heartbeat: no claim found for container=%s session=%s",
            resolved.container_id,
            resolved.session_id,
        )
        return AcquireResult(success=False, record=None, error="claim_not_found")

    ts = now if now is not None else _utc_now()
    ts_str = _iso(ts)

    # Rebuild the record with an updated heartbeat_at; claimed_at is preserved.
    updated = ClaimRecord(
        schema_version=existing.schema_version,
        track_id=existing.track_id,
        owner=existing.owner,
        container=existing.container,
        session=existing.session,
        phase=existing.phase,
        status=existing.status,
        claimed_at=existing.claimed_at,       # immutable
        heartbeat_at=ts_str,                  # updated
        superseded_from=existing.superseded_from,
    )

    result: WriteClaimResult = write_claim(updated, repo_path)
    if not result.success:
        logger.warning(
            "claim_lifecycle.heartbeat: write_claim failed: error=%s", result.error
        )
        return AcquireResult(success=False, record=None, error=result.error or "write_failed")

    logger.info(
        "claim_lifecycle.heartbeat: refreshed track=%s container=%s session=%s",
        track_id,
        resolved.container_id,
        resolved.session_id,
    )
    return AcquireResult(success=True, record=updated, error=None)


def release_claim(
    track_id: str,
    status: str = "done",
    identity: Optional[Identity] = None,
    repo_path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> AcquireResult:
    """Mark this session's claim as a terminal status.

    Terminal statuses: ``'done'``, ``'yielded'``, ``'abandoned'``.  After
    release, ``gc.archive_done_claims()`` will move ``status='done'`` records
    to ``archive/<YYYY-MM>/`` after ``ARCHIVE_RETENTION_DAYS`` days.

    Mechanism:
    1. ``read_claims()`` — fetch current claim records.
    2. Locate the record for this ``(container_id, session_id)``.
    3. Build an updated record with ``status=<status>`` and
       ``heartbeat_at=now`` (final timestamp).
    4. ``write_claim()`` — overwrite the file.

    Parameters
    ----------
    track_id:
        Track identifier (used for log context only).
    status:
        One of ``'done'``, ``'yielded'``, ``'abandoned'``.  Defaults to
        ``'done'``.  Passing any other value returns
        ``AcquireResult(success=False, error='invalid_status')``.
    identity:
        Must be the same Identity instance used at ``acquire_claim()`` time
        so that the correct ``(container_id, session_id)`` is located.
    repo_path:
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
    now:
        Reference UTC time for the final ``heartbeat_at``.

    Returns
    -------
    AcquireResult
        ``error='invalid_status'`` for unsupported status values.
        ``error='claim_not_found'`` when no matching record exists.
    """
    _TERMINAL_STATUSES = frozenset({"done", "yielded", "abandoned"})
    if status not in _TERMINAL_STATUSES:
        return AcquireResult(success=False, record=None, error="invalid_status")

    resolved = _resolve_identity(identity, repo_path)
    if resolved is None:
        return AcquireResult(success=False, record=None, error="identity_error")

    read_result = read_claims(repo_path)
    if not read_result.ref_exists:
        return AcquireResult(success=False, record=None, error="claim_not_found")

    existing: Optional[ClaimRecord] = None
    for rec in read_result.claims:
        if rec.container == resolved.container_id and rec.session == resolved.session_id:
            existing = rec
            break

    if existing is None:
        logger.warning(
            "claim_lifecycle.release_claim: no claim found for container=%s session=%s",
            resolved.container_id,
            resolved.session_id,
        )
        return AcquireResult(success=False, record=None, error="claim_not_found")

    ts = now if now is not None else _utc_now()
    ts_str = _iso(ts)

    released = ClaimRecord(
        schema_version=existing.schema_version,
        track_id=existing.track_id,
        owner=existing.owner,
        container=existing.container,
        session=existing.session,
        phase=existing.phase,
        status=status,
        claimed_at=existing.claimed_at,       # immutable
        heartbeat_at=ts_str,                  # final timestamp
        superseded_from=existing.superseded_from,
    )

    result: WriteClaimResult = write_claim(released, repo_path)
    if not result.success:
        logger.warning(
            "claim_lifecycle.release_claim: write_claim failed: error=%s", result.error
        )
        return AcquireResult(success=False, record=None, error=result.error or "write_failed")

    logger.info(
        "claim_lifecycle.release_claim: released track=%s status=%s container=%s session=%s",
        track_id,
        status,
        resolved.container_id,
        resolved.session_id,
    )
    return AcquireResult(success=True, record=released, error=None)


def release_claim_by_track(
    raw_track_id: str,
    status: str = "done",
    identity: Optional[Identity] = None,
    repo_path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> AcquireResult:
    """Release THIS container's active claim for a track, located by track_id.

    Defect (c) fix (coordination-claim-lifecycle-and-overlap): ``release_claim``
    locates by ``(container, session)``, but a later ship/close invocation
    (phase-d-closer, on cycle completion) runs with a FRESH ``session_id`` and
    cannot match the original acquiring session — so claims never got released
    and accumulated as ``active`` forever. The ship context DOES know the
    ``track_id`` (the carry-id being closed), so this variant locates by
    ``(normalized track_id, container)`` and ignores session.

    ``raw_track_id`` is normalized via ``derive_track_id`` (same as acquire), so
    the caller passes the raw carry-id. If several active claims match (same
    container re-claimed a track across sessions), the EARLIEST ``claimed_at``
    is released (deterministic, matches reconcile's earliest-wins). Fail-soft:
    ``claim_not_found`` when no active match exists (already released / never
    claimed — both benign at ship time).
    """
    _TERMINAL_STATUSES = frozenset({"done", "yielded", "abandoned"})
    if status not in _TERMINAL_STATUSES:
        return AcquireResult(success=False, record=None, error="invalid_status")

    resolved = _resolve_identity(identity, repo_path)
    if resolved is None:
        return AcquireResult(success=False, record=None, error="identity_error")

    norm = derive_track_id(raw_track_id)

    read_result = read_claims(repo_path)
    if not read_result.ref_exists:
        return AcquireResult(success=False, record=None, error="claim_not_found")

    matches = [
        rec
        for rec in read_result.claims
        if rec.container == resolved.container_id
        and rec.track_id == norm
        and rec.status == "active"
    ]
    if not matches:
        return AcquireResult(success=False, record=None, error="claim_not_found")

    # deterministic: earliest claimed_at (lexical ISO-8601 sort is chronological)
    existing = sorted(matches, key=lambda r: r.claimed_at)[0]

    ts_str = _iso(now if now is not None else _utc_now())
    released = ClaimRecord(
        schema_version=existing.schema_version,
        track_id=existing.track_id,
        owner=existing.owner,
        container=existing.container,
        session=existing.session,
        phase=existing.phase,
        status=status,
        claimed_at=existing.claimed_at,
        heartbeat_at=ts_str,
        superseded_from=existing.superseded_from,
    )
    result: WriteClaimResult = write_claim(released, repo_path)
    if not result.success:
        return AcquireResult(success=False, record=None, error=result.error or "write_failed")
    logger.info(
        "claim_lifecycle.release_claim_by_track: released track=%s status=%s container=%s",
        norm,
        status,
        resolved.container_id,
    )
    return AcquireResult(success=True, record=released, error=None)
