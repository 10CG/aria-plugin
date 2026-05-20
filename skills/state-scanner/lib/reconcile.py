"""Layer L — Reconcile Protocol (multi-terminal-coordination TASK-015).

Implements the 4-rule, first-match reconcile protocol that determines the
authoritative winner for a given track_id when multiple claim files exist
across containers/sessions.

Design goals (per proposal §What/Layer L + DEC-20260519-001 #1/#4):
  - Purely advisory: this module never writes claims or modifies refs.
  - Deterministic: identical input → identical output across all containers.
  - Non-throwing: any parse/field error routes the offending claim to the
    ``unknown`` bucket rather than raising.
  - Stale detection only: reconcile marks a winner as "stale takeover
    eligible" but does NOT acquire the claim (that is the caller's job).

Reconcile rules (first-match, applied in order):
  1. Bucket ``status="unknown"`` claims separately; exclude from candidates.
  2. Move terminal claims (``status`` in {"done", "abandoned"}) to superseded.
  3. No candidates left → verdict "no_active_candidates".
  4. Exactly one active candidate → it wins ("sole_active").
  5. Multiple active candidates (race scenario):
     5.1 Clock-skew detection: max diff of claimed_at > CLOCK_SKEW_WARN_THRESHOLD
         → conflict=True, verdict_reason="clock_skew_conflict" (winner still
         selected by rule 5.2 for advisory purposes).
     5.2 Earliest claimed_at wins (ISO string lexicographic order == temporal
         order for UTC ISO 8601 at seconds precision).
     5.3 Tie in claimed_at → lex tiebreak on "container/session" composite key.
     5.4 yielders = candidates minus winner.
  6. Stale-takeover eligibility: if winner.heartbeat_at is older than STALE_TTL
     relative to ``now`` → winner moves to superseded, reason gets
     "+stale_takeover_eligible" suffix (caller decides whether to acquire).

Spec references:
  openspec/changes/multi-terminal-coordination/proposal.md §What/Layer L §Impact
  openspec/changes/multi-terminal-coordination/tasks.md §2.6
  docs/decisions/DEC-20260519-001-multi-terminal-coordination.md decision #4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from .claim_schema import ClaimRecord
from .constants import CLOCK_SKEW_WARN_THRESHOLD, STALE_TTL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Terminal statuses: claims in these states never hold active ownership.
# "abandoned" is not in STATUS_ENUM (claim_schema.py SCHEMA_VERSION_CURRENT=1)
# but may appear in future schema versions; we treat it as terminal here for
# forward compatibility.
# ---------------------------------------------------------------------------
_TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "abandoned"})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcileVerdict:
    """Immutable reconcile result for a single track_id.

    Fields
    ------
    track_id : str
        The track this verdict covers.
    winner : ClaimRecord | None
        The claim that should continue working (earliest claimed_at).
        None when there are no active candidates.
    yielders : tuple[ClaimRecord, ...]
        Active claims that should yield (race losers).
    superseded : tuple[ClaimRecord, ...]
        Claims in terminal status (done / abandoned) *plus* the winner if
        it has been flagged as stale-takeover-eligible (the caller decides
        whether to actually acquire).
    unknown : tuple[ClaimRecord, ...]
        Claims with status="unknown" (unrecognised schema version).
        Excluded from all rule evaluation; surfaced for diagnostics only.
    conflict : bool
        True when the max clock-skew between any two candidate claimed_at
        timestamps exceeds CLOCK_SKEW_WARN_THRESHOLD.  The board should
        render a prominent warning; the winner is still selected
        deterministically but should be treated as advisory.
    verdict_reason : str
        Short human-readable token describing the winning rule, e.g.
        "earlier_claimed_at_wins", "sole_active",
        "tiebreak_lex_order", "clock_skew_conflict",
        "no_active_candidates", "empty_claims",
        "sole_active+stale_takeover_eligible".
    max_clock_skew_seconds : int | None
        Populated (>= 0) when there are >= 2 active candidates and the
        clock-skew check fires.  None in all other cases.
    """

    track_id: str
    winner: Optional[ClaimRecord]
    yielders: tuple[ClaimRecord, ...]
    superseded: tuple[ClaimRecord, ...]
    unknown: tuple[ClaimRecord, ...]
    conflict: bool
    verdict_reason: str
    max_clock_skew_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_claimed_at(claim: ClaimRecord) -> Optional[datetime]:
    """Return a timezone-aware datetime from claim.claimed_at, or None on error.

    ISO 8601 at seconds precision with UTC offset is used by all live
    sessions (claim_schema.py validates this on write).  We still handle
    parse failure gracefully: the caller routes such claims to the unknown
    bucket rather than raising.
    """
    try:
        dt = datetime.fromisoformat(claim.claimed_at.replace("Z", "+00:00"))
        # Ensure UTC-aware for safe arithmetic
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _parse_heartbeat_at(claim: ClaimRecord) -> Optional[datetime]:
    """Return a timezone-aware datetime from claim.heartbeat_at, or None."""
    try:
        dt = datetime.fromisoformat(claim.heartbeat_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _tiebreak_key(claim: ClaimRecord) -> str:
    """Composite lex key used when claimed_at timestamps are identical."""
    return f"{claim.container}/{claim.session}"


def _is_stale(claim: ClaimRecord, now: datetime) -> bool:
    """Return True if claim.heartbeat_at is older than STALE_TTL from now."""
    heartbeat_dt = _parse_heartbeat_at(claim)
    if heartbeat_dt is None:
        # Cannot determine freshness — treat as NOT stale to be conservative.
        # The caller still has the claim in the winner slot; board can flag
        # heartbeat_at as unparseable separately.
        return False
    age_seconds = (now - heartbeat_dt).total_seconds()
    return age_seconds > STALE_TTL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reconcile(
    track_id: str,
    claims: list[ClaimRecord],
    *,
    now: datetime | None = None,
) -> ReconcileVerdict:
    """Determine the authoritative winner for all claims on a single track_id.

    Pure function — no filesystem or network access.  Deterministic across
    containers given identical input.  Never raises; malformed claims are
    routed to the ``unknown`` bucket.

    Args:
        track_id: The shared track identifier (callers must have pre-grouped).
        claims:   All ClaimRecords associated with this track_id.  May be
                  empty or contain claims from multiple containers/sessions.
        now:      Reference UTC datetime for staleness calculation.  Defaults
                  to ``datetime.now(timezone.utc)``.  Pass an explicit value
                  in tests to make assertions deterministic.

    Returns:
        ReconcileVerdict (frozen dataclass — immutable).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ---- Empty input guard -----------------------------------------------
    if not claims:
        return ReconcileVerdict(
            track_id=track_id,
            winner=None,
            yielders=(),
            superseded=(),
            unknown=(),
            conflict=False,
            verdict_reason="empty_claims",
        )

    # ---- Rule 1: bucket unknown-version claims ---------------------------
    unknown: list[ClaimRecord] = []
    parseable: list[ClaimRecord] = []

    for claim in claims:
        if claim.status == "unknown":
            unknown.append(claim)
        else:
            # Verify claimed_at is parseable; if not, treat as unknown-bucket.
            if _parse_claimed_at(claim) is None:
                logger.warning(
                    "reconcile: claimed_at unparseable for %s/%s — routing to unknown bucket",
                    claim.container,
                    claim.session,
                )
                unknown.append(claim)
            else:
                parseable.append(claim)

    # ---- Rule 2: separate terminal (done / abandoned) → superseded -------
    superseded: list[ClaimRecord] = []
    candidates: list[ClaimRecord] = []

    for claim in parseable:
        if claim.status in _TERMINAL_STATUSES:
            superseded.append(claim)
        else:
            candidates.append(claim)

    # ---- Rule 3: no active candidates ------------------------------------
    if not candidates:
        return ReconcileVerdict(
            track_id=track_id,
            winner=None,
            yielders=(),
            superseded=tuple(superseded),
            unknown=tuple(unknown),
            conflict=False,
            verdict_reason="no_active_candidates",
        )

    # ---- Rule 4: sole active candidate -----------------------------------
    if len(candidates) == 1:
        winner = candidates[0]
        reason = "sole_active"

        # Rule 6: stale-takeover eligibility check
        if _is_stale(winner, now):
            superseded.append(winner)
            reason = "sole_active+stale_takeover_eligible"
            winner = None  # no active holder; eligible for takeover

        return ReconcileVerdict(
            track_id=track_id,
            winner=winner,
            yielders=(),
            superseded=tuple(superseded),
            unknown=tuple(unknown),
            conflict=False,
            verdict_reason=reason,
        )

    # ---- Rule 5: multiple active candidates (race scenario) --------------

    # Rule 5.1: clock-skew detection
    # Compare all pairs of parsed claimed_at values; find max absolute diff.
    parsed_times: list[tuple[ClaimRecord, datetime]] = [
        (c, _parse_claimed_at(c))  # type: ignore[arg-type]  # None already filtered above
        for c in candidates
    ]
    timestamps = [dt for _, dt in parsed_times]
    max_skew_seconds: int = int(
        max(
            abs((t1 - t2).total_seconds())
            for i, t1 in enumerate(timestamps)
            for t2 in timestamps[i + 1 :]
        )
    )
    conflict = max_skew_seconds > CLOCK_SKEW_WARN_THRESHOLD

    # Rule 5.2: earliest claimed_at wins (ISO lex order == temporal order for
    # UTC ISO 8601 with seconds precision and consistent offset notation).
    # Use the actual datetime for comparison to handle "+00:00" vs "Z" variants.
    def _sort_key(pair: tuple[ClaimRecord, datetime]) -> tuple[datetime, str]:
        claim, dt = pair
        return (dt, _tiebreak_key(claim))

    parsed_times_sorted = sorted(parsed_times, key=_sort_key)

    # Rule 5.3: tiebreak — check if top-2 share the same datetime
    # (nano-second identical timestamps are rare but spec-mandated to handle)
    winner_claim, winner_dt = parsed_times_sorted[0]

    # Determine verdict_reason before stale check
    if conflict:
        reason = "clock_skew_conflict"
    else:
        # Detect whether a tiebreak was the deciding factor
        second_claim, second_dt = parsed_times_sorted[1]
        if winner_dt == second_dt:
            reason = "tiebreak_lex_order"
        else:
            reason = "earlier_claimed_at_wins"

    # Rule 5.4: yielders = candidates minus winner
    yielders: list[ClaimRecord] = [c for c, _ in parsed_times_sorted[1:]]

    # Rule 6: stale-takeover eligibility for the winner
    if _is_stale(winner_claim, now):
        superseded.append(winner_claim)
        reason = reason + "+stale_takeover_eligible"
        winner_claim_final: Optional[ClaimRecord] = None
    else:
        winner_claim_final = winner_claim

    return ReconcileVerdict(
        track_id=track_id,
        winner=winner_claim_final,
        yielders=tuple(yielders),
        superseded=tuple(superseded),
        unknown=tuple(unknown),
        conflict=conflict,
        verdict_reason=reason,
        max_clock_skew_seconds=max_skew_seconds,
    )


def reconcile_all(
    claims: list[ClaimRecord],
    *,
    now: datetime | None = None,
) -> dict[str, ReconcileVerdict]:
    """Group claims by track_id and run reconcile() on each group.

    Args:
        claims: Flat list of ClaimRecords from all tracks (e.g. from
                coordination_ref.read_claims()).  Claims with status="unknown"
                (empty track_id sentinels) are still grouped by their
                track_id field — the empty-string key receives its own verdict
                of "empty_claims" which the board can safely ignore.
        now:    Reference UTC datetime forwarded to each reconcile() call.

    Returns:
        Dict mapping track_id → ReconcileVerdict.  A track_id present in the
        input is always present in the output (no silent omissions).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    grouped: dict[str, list[ClaimRecord]] = {}
    for claim in claims:
        grouped.setdefault(claim.track_id, []).append(claim)

    return {
        track_id: reconcile(track_id, group, now=now)
        for track_id, group in grouped.items()
    }
