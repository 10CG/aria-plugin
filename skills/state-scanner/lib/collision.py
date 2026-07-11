"""Layer L — Collision classification (TASK-000, concurrent-session-upm-safety #133).

Single source of truth for collision classification across multi-branch handoff
tracks.  Promotes the formerly renderer-local helpers (``_split_owner_container``,
``_track_to_claim_record``, ``_classify_collision``) out of
``scripts/renderers/track_board.py`` into ``lib/`` so that both the renderer AND
the ``handoff_multibranch`` collector consume one implementation — eliminating the
phantom-field divergence root cause (sister R1 C1: ``collision_type`` /
``has_collision`` were documented but never implemented).

Public API:
    classify(tracks, *, now=None) -> dict
        Aggregate collision summary across ALL track_ids in a tracks list.
        Returns {"kind": "none"|"cross_owner"|"self_multi_container",
                 "groups": list[list[str]]}
        - kind:   most-severe collision kind across all tracks
                  (cross_owner > self_multi_container > none).
        - groups: one entry per colliding track_id; each entry is the sorted list
                  of distinct owner_container strings participating in that
                  collision.  Empty list when kind == "none".

    Shared helpers (relocated from track_board.py, behaviour-identical):
        split_owner_container(s) -> (owner, container, session)
        track_to_claim_record(track) -> ClaimRecord   (may raise ValueError)
        classify_claims(claims) -> (kind, severity_emoji)

ADVISORY-ONLY CONTRACT (concurrent-session-upm-safety proposal §0 / AC-0):
    The persisted ``tracks_multibranch.collision`` summary produced via this
    module is *advisory*.  It is built from a deliberately lossy approximation
    (Layer H handoff frontmatter lacks an independent heartbeat_at; updated_at
    doubles as claimed_at + heartbeat_at via track_to_claim_record).  Downstream
    consumers MUST treat ``collision`` as a surface/visibility signal only and
    MUST NOT use it as a gating input (no hard lock, no auto-enable) — per
    DEC-20260519-001 advisory-over-hardlock.

Spec:  openspec/changes/concurrent-session-upm-safety/ (TASK-000)
Deps:  lib/claim_schema.py (ClaimRecord), lib/reconcile.py (reconcile_all)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .claim_schema import ClaimRecord
from .reconcile import reconcile_all

# Collision kind severity ordering (higher index == more severe).
# Used to escalate the aggregate ``kind`` across multiple colliding tracks.
_KIND_SEVERITY: dict[str, int] = {
    "none": 0,
    "self_multi_container": 1,
    "cross_owner": 2,
}


# ---------------------------------------------------------------------------
# Shared helpers (relocated verbatim from track_board.py — behaviour-identical)
# ---------------------------------------------------------------------------


def split_owner_container(owner_container: str) -> tuple[str, str, str]:
    """Split an owner_container string into (owner, container, session).

    Expected format: "owner/container/session" (3 parts).
    Handles shorter / malformed strings gracefully by filling missing parts
    with empty-string sentinels so callers can still reason about owner.

    Examples:
        "hikari/devbox-A/s-7f3a"  -> ("hikari", "devbox-A", "s-7f3a")
        "devbox-A/sess-001"       -> ("", "devbox-A", "sess-001")   # 2-part
        "solo"                    -> ("", "", "solo")               # 1-part
        ""                        -> ("", "", "")
    """
    parts = (owner_container or "").split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        # Two-part: treat as container/session (owner unknown)
        return "", parts[0], parts[1]
    # One-part or empty
    return "", "", parts[0] if parts else ""


def track_to_claim_record(track: dict) -> ClaimRecord:
    """Approximate a Layer H track dict as a ClaimRecord placeholder for reconcile.

    Layer H data (handoff frontmatter) lacks independent heartbeat_at; we use
    updated_at as a near-approximation for both claimed_at and heartbeat_at.
    This is intentionally lossy — the reconcile result is advisory/visual only.

    Raises ValueError if required fields are missing/unparseable — caller must
    catch and skip the offending track (fail-soft, advisory).
    """
    owner_container = track.get("owner_container") or ""
    owner, container, session = split_owner_container(owner_container)

    track_id = track.get("track_id") or ""
    if not track_id:
        raise ValueError("track_id missing")

    updated_at = track.get("updated_at") or ""
    if not updated_at:
        raise ValueError("updated_at missing — cannot approximate claimed_at")

    # Validate that updated_at is parseable ISO 8601 (reconcile requires this)
    try:
        datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"updated_at not valid ISO 8601: {updated_at!r}") from exc

    # Map track status to a ClaimRecord-compatible status value.
    # Layer H "legacy" -> treat as "active" (Layer L has no "legacy" status).
    status_raw = (track.get("status") or "active").lower().strip()
    if status_raw in ("active", "legacy"):
        status = "active"
    elif status_raw == "done":
        status = "done"
    elif status_raw == "abandoned":
        # ClaimRecord STATUS_WRITABLE only has active/yielded/done; map abandoned->done
        # so reconcile routes it to superseded (terminal bucket) correctly.
        status = "done"
    else:
        status = "active"

    phase = track.get("phase") or ""

    return ClaimRecord(
        schema_version="1",
        track_id=track_id,
        owner=owner or "unknown",
        container=container or "unknown",
        session=session or "unknown",
        phase=phase,
        status=status,
        claimed_at=updated_at,
        heartbeat_at=updated_at,
        superseded_from=None,
    )


def classify_claims(claims: "list[ClaimRecord]") -> tuple[str, str]:
    """Classify a set of active claims for the same track_id.

    Returns (collision_kind, severity_emoji):
        collision_kind: 'cross_owner' | 'self_multi_container' | 'none'
        severity_emoji: 'RED' | 'YELLOW' | ''  (render-only; never persisted)

    Logic (per session-handoff.md §2.3.5):
        cross_owner          -> >=2 distinct owner values across active claims
        self_multi_container -> same owner, >=2 distinct container values
        none                 -> <=1 active claim or all same owner+container
                                (self-serial: same (owner,container) -> none)
    """
    active = [c for c in claims if c.status not in ("done", "abandoned")]
    if len(active) < 2:
        return "none", ""

    owners = {c.owner for c in active}
    if len(owners) >= 2:
        return "cross_owner", "\U0001F534"  # 🔴

    containers = {c.container for c in active}
    if len(containers) >= 2:
        return "self_multi_container", "\U0001F7E1"  # 🟡

    return "none", ""


# ---------------------------------------------------------------------------
# Part B1 — linked_issue semantic-overlap advisory
# (coordination-claim-lifecycle-and-overlap; bypasses reconcile_all's
#  track_id grouping, which by design cannot see "same issue, two names")
# ---------------------------------------------------------------------------


def linked_issue_overlaps(
    claims: "list[ClaimRecord]",
    own_track_id: str,
    own_linked_issue: Optional[str],
) -> "list[dict]":
    """Detect active claims sharing our linked_issue under a DIFFERENT track_id.

    Defect (b) mitigation: track_id collision detection is exact-string only
    (``reconcile_all`` groups by track_id), so two sessions naming the same
    work differently (e.g. ``secret-guard-bash3-multiline-hardening`` vs
    ``carry-secretguard-fieldparse-anchor``) never collide.  When both claims
    carry the same ``linked_issue``, this function surfaces the overlap.

    ADVISORY-ONLY: the result is a warning list for the orchestration layer /
    CLI JSON (additive key).  It never feeds winner determination and never
    blocks — per DEC-20260519-001 advisory-over-hardlock.

    Args:
        claims:            All ClaimRecords (e.g. from read_claims()).
        own_track_id:      This session's normalized track_id (excluded from
                           matching — same track_id is the ordinary collision
                           path, already handled by reconcile).
        own_linked_issue:  This session's linked_issue.  None/empty → no
                           overlap possible → always [].

    Returns:
        One dict per overlapping claim, sorted by (track_id, owner, container):
        ``{"track_id", "owner", "container", "session", "status",
           "linked_issue", "claimed_at"}``
    """
    if not own_linked_issue:
        return []

    _TERMINAL = ("done", "abandoned", "unknown")
    out: "list[dict]" = []
    for c in claims or []:
        if c.status in _TERMINAL:
            continue
        if not getattr(c, "linked_issue", None):
            continue
        if c.linked_issue != own_linked_issue:
            continue
        if c.track_id == own_track_id:
            continue  # same-name collision — reconcile's job, not ours
        out.append(
            {
                "track_id": c.track_id,
                "owner": c.owner,
                "container": c.container,
                "session": c.session,
                "status": c.status,
                "linked_issue": c.linked_issue,
                "claimed_at": c.claimed_at,
            }
        )
    out.sort(key=lambda d: (d["track_id"], d["owner"], d["container"]))
    return out


# ---------------------------------------------------------------------------
# Public aggregate API — persisted as tracks_multibranch.collision (TASK-000)
# ---------------------------------------------------------------------------


def classify(tracks: "list[dict]", *, now: Optional[datetime] = None) -> dict:
    """Aggregate collision classification across all track_ids.

    This is the persisted-summary entry point.  The collector
    (handoff_multibranch.py) calls it and stores the result under
    ``tracks_multibranch.collision`` (additive field, schema-bumped).

    Pipeline (real, not "extract a function" — sister R1 C1):
        tracks[]
          -> track_to_claim_record(t)   [lossy; ValueError-skipped, fail-soft]
          -> reconcile_all(records)      [per-track_id ReconcileVerdict]
          -> classify_claims(active)     [per-track collision kind]
          -> aggregate {kind, groups}

    Args:
        tracks: list of track dicts from collect_handoff_multibranch
                (each: track_id / owner_container / phase / status / updated_at).
        now:    reference UTC datetime forwarded to reconcile_all; defaults to
                reconcile_all's own default (datetime.now(timezone.utc)).

    Returns:
        {"kind": "none"|"cross_owner"|"self_multi_container",
         "groups": list[list[str]]}

        - render-only severity emoji from classify_claims is DROPPED here
          (never persisted).
        - groups: one sorted member-list per colliding track_id; each member is
          the original owner_container string of an active (non-terminal) claim.
        - ADVISORY-ONLY: never use as a gating input (see module docstring).

    Never raises — any per-track conversion failure is skipped (fail-soft).
    """
    # Only tracks with a real owner_container can collide; "unknown" (legacy /
    # missing frontmatter) cannot be attributed to an owner, so they are excluded
    # from collision attribution (matches track_board.all_collidable filter).
    collidable = [
        t for t in (tracks or [])
        if (t.get("owner_container") or "unknown") != "unknown"
    ]
    if not collidable:
        return {"kind": "none", "groups": []}

    # Build ClaimRecords (fail-soft: skip any track that cannot be approximated)
    # alongside a parallel index track_id -> [(ClaimRecord, original_oc), ...]
    # so we can label groups with the faithful original owner_container strings.
    records: list[ClaimRecord] = []
    oc_by_tid_key: dict[str, dict[tuple[str, str, str], str]] = {}
    for t in collidable:
        try:
            rec = track_to_claim_record(t)
        except ValueError:
            continue
        records.append(rec)
        key = (rec.owner, rec.container, rec.session)
        oc_by_tid_key.setdefault(rec.track_id, {})[key] = (
            t.get("owner_container") or f"{rec.owner}/{rec.container}/{rec.session}"
        )

    if not records:
        return {"kind": "none", "groups": []}

    verdicts = reconcile_all(records, now=now)

    overall_kind = "none"
    groups: list[list[str]] = []

    _TERMINAL = ("done", "abandoned")
    for tid in sorted(verdicts.keys()):
        verdict = verdicts[tid]

        # Active (non-terminal) candidates for this track_id.
        #   - yielders: always active candidates
        #   - winner:   the selected candidate (None when stale-takeover-eligible)
        #   - superseded: terminal claims (done/abandoned) PLUS the stale winner
        #     when reconcile demoted it (rule 6). We must recover that stale
        #     winner — it is a non-terminal contender — or a 2-claim collision
        #     where the winner is stale would mis-classify as "none".
        # classify_claims re-filters terminal internally, so including all of
        # superseded would be safe too, but we filter here to keep groups clean.
        active_claims: list[ClaimRecord] = list(verdict.yielders)
        if verdict.winner is not None:
            active_claims.append(verdict.winner)
        active_claims.extend(
            c for c in verdict.superseded if c.status not in _TERMINAL
        )

        kind, _ = classify_claims(active_claims)  # render-only emoji dropped
        if kind == "none":
            continue

        # Group members = faithful original owner_container strings of the
        # active claims (fall back to reconstructed owner/container/session).
        label_map = oc_by_tid_key.get(tid, {})
        members = sorted({
            label_map.get((c.owner, c.container, c.session))
            or f"{c.owner}/{c.container}/{c.session}"
            for c in active_claims
        })
        groups.append(members)

        if _KIND_SEVERITY[kind] > _KIND_SEVERITY[overall_kind]:
            overall_kind = kind

    return {"kind": overall_kind, "groups": groups}
