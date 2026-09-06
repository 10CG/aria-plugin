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

from datetime import datetime, timedelta, timezone
import re
import sys
from typing import Optional

from .claim_schema import ClaimRecord
from .constants import LAYER_H_ACTIVE_WINDOW_DAYS
from .reconcile import reconcile_all

# 8-char lowercase hex — the shape of ~/.aria/container-id ``uuid`` (identity.py).
_UUID8_RE = re.compile(r"^[0-9a-f]{8}$")
# Track family suffix: ``<slug>-<uuid8>`` (D-0(a), Layer H grouping only).
_FAMILY_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$")

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

    Layer H frontmatter is TWO-part ``<owner>/<container-id>`` (session-handoff.md
    §2.3.1; owner-container-identity-key-and-collision-parser SC-1).  Three or
    more segments are the legacy ``owner/container/session`` reading, kept for
    the historical rows that carried a session tag.

    Examples:
        "simonfish/bfe8285d"      -> ("simonfish", "bfe8285d", "")   # 2-part (canonical)
        "hikari/devbox-A/s-7f3a"  -> ("hikari", "devbox-A", "s-7f3a")  # 3-part (legacy)
        "solo"                    -> ("", "solo", "")                # 1-part: container only
        ""                        -> ("", "", "")

    Aria #193 root cause: the former reading treated 2-part strings as
    ``container/session`` with an unknown owner, so every real row lost its
    owner segment and the classifier could never see two owners.
    """
    parts = (owner_container or "").split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return "", parts[0] if parts else "", ""


def identity_key(owner: str, container: str) -> str:
    """Return the coordination identity key for an (owner, container) pair.

    - ``container`` is an 8-char lowercase hex uuid (``~/.aria/container-id``)
      -> the uuid alone is the identity: the same machine under two git
      identities is ONE identity (Aria #193 drift), not two.
    - otherwise (hostname era, empty, read-only-fs fallback) -> ``owner/container``
      (empty owner yields ``"/container"``), because a hostname is not unique.

    Known, documented limit: a hostname or label that happens to be 8 lowercase
    hex chars is read as a uuid (that path is itself the degraded path).
    ``owner`` values ``""`` and ``"unknown"`` are normalised to ``""`` here.
    """
    owner_n = "" if (owner or "") == "unknown" else (owner or "")
    container_n = container or ""
    if _UUID8_RE.match(container_n):
        return container_n
    return f"{owner_n}/{container_n}"


def family_track_id(track_id: str) -> str:
    """D-0(a): strip a trailing ``-<8 lowercase hex>`` from a Layer H track id.

    Pure shape rule, no corpus lookup.  Applied ONLY inside
    :func:`track_to_claim_record` (both Layer H paths — collector classify() and
    the board — go through it); Layer L claims never do, and the frontmatter
    string itself is never rewritten.
    """
    return _FAMILY_SUFFIX_RE.sub("", track_id or "")


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
    # D-0(a) family key — Layer H grouping only (see family_track_id docstring).
    track_id = family_track_id(track_id) or track_id

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
        # "abandoned" is a first-class schema status since Part C (C-1) —
        # map faithfully; reconcile treats it as terminal same as done.
        status = "abandoned"
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

    Logic (session-handoff.md §2.3.5, owner-container-identity-key D1):
        identity_keys = { identity_key(owner, container) } over active claims
        < 2 identity_keys                       -> none  (one machine, however
                                                   many owner strings / sessions)
        >= 2 identity_keys:
            attributable owners = non-empty, non-"unknown" owner strings
            >= 2 attributable owners           -> cross_owner          (🔴)
            <= 1 attributable owner            -> self_multi_container (🟡)

    There is deliberately NO "same person" inference: two different owner
    strings on two uuid containers are two commit identities -> 🔴 (the ⚪
    identity_drift_advisories explains a same-machine drift separately).
    """
    active = [c for c in claims if c.status not in ("done", "abandoned")]
    if len(active) < 2:
        return "none", ""

    keys = {identity_key(c.owner, c.container) for c in active}
    if len(keys) < 2:
        return "none", ""

    attributable = {c.owner for c in active if c.owner and c.owner != "unknown"}
    if len(attributable) >= 2:
        return "cross_owner", "\U0001F534"  # 🔴
    return "self_multi_container", "\U0001F7E1"  # 🟡


# ---------------------------------------------------------------------------
# Layer H freshness window (D-3(a)) — the ONE implementation (SC-11)
# ---------------------------------------------------------------------------


def layer_h_is_fresh(updated_at: str, *, now: Optional[datetime] = None) -> bool:
    """True when ``updated_at`` is within LAYER_H_ACTIVE_WINDOW_DAYS of ``now``.

    Unparseable / missing ``updated_at`` -> True (fail-open: the row keeps
    flowing to track_to_claim_record, which raises ValueError there and is
    skipped fail-soft — freshness must not become a second silent drop path).
    """
    ref = now if now is not None else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat((updated_at or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= ref - timedelta(days=LAYER_H_ACTIVE_WINDOW_DAYS)


def filter_layer_h_fresh(tracks: "list[dict]", *, now: Optional[datetime] = None) -> "list[dict]":
    """Drop Layer H rows older than the active window (legacy rows pass through).

    Called by BOTH the collector (before classify) and the board renderer
    (before building its collidable set) so the persisted
    ``tracks_multibranch.collision`` and the board agree on the same input.
    ``tracks`` itself is untouched.
    """
    return [
        t for t in (tracks or [])
        if t.get("status") == "legacy" or layer_h_is_fresh(t.get("updated_at") or "", now=now)
    ]


# ---------------------------------------------------------------------------
# ⚪ same-identity-multi-owner advisory (D3) — computed on PRE-dedupe rows
# ---------------------------------------------------------------------------


def identity_drift_advisories(tracks: "list[dict]") -> "list[dict]":
    """Report uuid identity_keys that appear under >= 2 attributable owners.

    Input: the collector's raw non-legacy rows (dedupe would fold exactly the
    rows this needs to see).  Cross-track, cross-branch — this is a repository-
    wide inventory of git-identity drift on one machine (Aria #193), NOT a
    collision: it never feeds ``kind``/``groups`` (session-handoff.md §2.3.5
    ``same-identity-multi-owner`` = informational ⚪).

    Returns one dict per drifting key, sorted by identity_key:
        {"identity_key": str, "owners": sorted[str], "first_seen": str, "last_seen": str}
    ``first_seen``/``last_seen`` are the min/max ``updated_at`` strings across
    the contributing rows.  Only uuid-shaped keys qualify (a hostname shared by
    two owners is two identities, see identity_key()).  Empty / "unknown"
    owners and legacy rows do not count.  Never raises.
    """
    seen: dict[str, dict] = {}
    for t in tracks or []:
        if t.get("status") == "legacy":
            continue
        owner, container, _session = split_owner_container(t.get("owner_container") or "")
        if not owner or owner == "unknown" or not _UUID8_RE.match(container or ""):
            continue
        entry = seen.setdefault(container, {"owners": set(), "stamps": []})
        entry["owners"].add(owner)
        stamp = t.get("updated_at") or ""
        if stamp:
            entry["stamps"].append(stamp)
    out: list[dict] = []
    for key in sorted(seen):
        owners = sorted(seen[key]["owners"])
        if len(owners) < 2:
            continue
        stamps = sorted(seen[key]["stamps"])
        out.append({
            "identity_key": key,
            "owners": owners,
            "first_seen": stamps[0] if stamps else "",
            "last_seen": stamps[-1] if stamps else "",
        })
    return out


# ---------------------------------------------------------------------------
# Part B1 — linked_issue semantic-overlap advisory
# (coordination-claim-lifecycle-and-overlap; bypasses reconcile_all's
#  track_id grouping, which by design cannot see "same issue, two names")
# ---------------------------------------------------------------------------


def normalize_linked_issue(value: str) -> "Optional[tuple[str, int]]":
    """Normalize a ``linked_issue`` string to its comparison key.

    Key = ``(repo_basename, number)`` where ``repo_basename`` is the last
    ``/``-segment of the part before the LAST ``#``, with every segment
    ``strip()``-ed, ``.``/``_`` translated to ``-`` inside the basename, and
    ``casefold()`` applied.  ``number`` is the decimal ``int`` of the part
    after the last ``#``.  ``org`` (anything before the basename) is NOT part
    of the key (fail-toward-reporting; see OpenSpec linked-issue-normalization).

    Returns ``None`` for every unparseable value — exactly three classes:
    (i) no ``#``; (ii) ``number_str`` not ``isascii() and isdigit()`` (or
    exceeding ``sys.get_int_max_str_digits()`` when that limit is > 0, or
    ``int()`` raising ``ValueError``); (iii) empty ``repo_basename``.
    Callers must fall back to raw-string equality on ``None`` — never treat
    ``None`` as "no match".
    """
    if not isinstance(value, str) or "#" not in value:
        return None  # (i) existence guard BEFORE any split/unpack
    left, number_str = value.rsplit("#", 1)
    left = left.strip()
    number_str = number_str.strip()
    if not (number_str.isascii() and number_str.isdigit()):
        return None  # (ii)
    limit = sys.get_int_max_str_digits()
    if limit > 0 and len(number_str) > limit:
        return None  # (ii) length bound; 0 means "unlimited"
    try:
        number = int(number_str)
    except ValueError:
        return None  # (ii)
    if "/" in left:
        repo_basename = left.rsplit("/", 1)[1].strip()
    else:
        repo_basename = left
    if not repo_basename:
        return None  # (iii)
    repo_basename = repo_basename.replace(".", "-").replace("_", "-").casefold()
    return (repo_basename, number)


def _linked_issue_matches(
    own_key: "Optional[tuple[str, int]]", own_raw: str, other_raw: str
) -> bool:
    """Rule 4/5: exact key equality when BOTH parse, else exact raw equality."""
    if own_key is not None:
        other_key = normalize_linked_issue(other_raw)
        if other_key is not None:
            return own_key == other_key
    return own_raw == other_raw


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
    carry ``linked_issue`` values that normalize to the same ``<repo>#<n>``
    key (``normalize_linked_issue``: basename casefolded with ``./_`` → ``-``,
    decimal number; ``org`` does NOT take part — fail-toward-reporting), this
    function surfaces the overlap.  Unparseable values fall back to exact
    raw-string equality.  Known limit: truncated aliases (``aria-orch`` vs
    ``aria-orchestrator``) are NOT unified.

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
    own_key = normalize_linked_issue(own_linked_issue)
    out: "list[dict]" = []
    for c in claims or []:
        if c.status in _TERMINAL:
            continue
        if not getattr(c, "linked_issue", None):
            continue
        if not _linked_issue_matches(own_key, own_linked_issue, c.linked_issue):
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
