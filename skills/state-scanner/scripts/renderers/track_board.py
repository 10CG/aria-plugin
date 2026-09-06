"""Multi-track coordination board renderer (TASK-005, extended in TASK-017).

Consumes the ``tracks_multibranch``, ``coordination_fetch``, and (Phase 1
increment 5, F3′) ``remote_refresh`` snapshot keys — produced by TASK-004
(handoff_multibranch.py), TASK-007 (coordination_fetch.py, now a pure legacy-
schema derivation), and Phase 0.5 (remote_refresh.py) respectively — and
renders an ASCII table for display in the state-scanner Phase 1 output.

Public API:
    render_track_board(snapshot: dict, now: datetime | None = None) -> str

Input:  full scan.py snapshot dict (dict with any collector keys)
Output: rendered multi-line string (no trailing newline)

Column definitions:
    TRACK        — track_id (truncated to MAX_TRACK_ID_LEN with ellipsis)
    OWNER/容器/会话 — owner_container field (e.g. "hikari/devbox-A/s-7f3a")
    PHASE        — frontmatter phase; "—" when absent
    HANDOFF      — date portion of updated_at or filename stem; "—" when absent
    LAST-PING    — relative age from updated_at ("Xm ago" / "Xh ago" / "Xd ago")
    STATUS       — freshness status with colour emoji OR done/legacy marker

Freshness thresholds (imported from lib/constants.py — TASK-018 Finding #3 migration):
    HEARTBEAT_INTERVAL = 600   s  (10 min) → 🟢 active
    STALE_TTL          = 1800  s  (30 min) → 🟡 stale? 待确认 (between intervals)
    ≥ STALE_TTL                            → 🔴 abandoned? 可接管

Status precedence (overrides freshness):
    frontmatter status == "done"      → collapsed into --- Done (N) --- section
    frontmatter status == "abandoned" → collapsed into --- Abandoned (N) --- section
    frontmatter status == "legacy"    → 🟡 legacy (no freshness calc)
    frontmatter status == "active"    → use freshness colour
    (anything else / missing)         → use freshness colour

Offline/cache indicators:
    coordination_fetch.degraded == True → red-bar line at top of output
    coordination_fetch.cached == True + not degraded → "(缓存于 Xs 前)" hint line
    errors[] has "coordination_ref_fetch_failed" + not degraded → yellow advisory
      "⚠ 协调 ref 未取到 ..." (F5 #144: Fetch 2 failed non-benign while branch view
      fresh — half-silent failure the all-green board would otherwise hide)
    remote_refresh (".", "origin") leg fetch_ok == "not_attempted" + not degraded
      → "⚠ 未刷新 ..." advisory (Phase 1 increment 5, task 3.14 hidden cell: a
      deadline/backoff-cut leg is neither a failure (red) nor silently fresh)

Collision detection (TASK-017 upgrade — reconcile-based):
    Primary path (P2): reconcile_all() from lib/reconcile.py drives detection.
      - cross-owner collision (≥2 distinct owners): 🔴 strong warning
      - self-multi-container collision (same owner, ≥2 containers): 🟡 soft hint
      - clock skew conflict (ReconcileVerdict.conflict=True): ⚠ 时钟偏移 line
    Fallback path (P1 basic, only if the reconcile machinery itself is
    unavailable or raises — NOT triggered by one malformed track anymore,
    see #155 round 2 note below):
      Same track_id with ≥2 distinct owner_container values → ⚠ COLLISION line
      (status-blind — this path predates terminal-status filtering).
    Input (aria-plugin#155, round 2): BOTH paths above are fed
      ``dedupe_latest_per_track_container(tracks)`` (imported from
      collectors.handoff_multibranch — same function the collector itself
      uses to build ``tracks_multibranch.collision``), not the raw ``tracks``
      list, so the board and the collector's persisted summary always agree.
      Also round 2: ClaimRecord construction (P2 path) is now fail-soft PER
      TRACK (mirrors lib/collision.py::classify()'s own per-item skip) — one
      track with a malformed field (e.g. bad updated_at) no longer discards
      the reconcile-based verdict for every OTHER track and silently
      degrades the WHOLE board to the cruder P1 fallback; only a genuinely
      board-wide failure (reconcile_all itself raising, or the lib import
      being unavailable) falls back to P1.

Spec:  openspec/changes/multi-terminal-coordination/tasks.md §2.7
Task:  TASK-017 (backend-architect); extends TASK-005 P1
Deps:  TASK-004 (tracks_multibranch), TASK-007 (coordination_fetch),
       TASK-015 (reconcile / ReconcileVerdict)

aria-plugin#155 (backend-architect, fix/issue-batch-149-151-155-134, round 2):
COLLISION computation now dedupes its input via the shared
``dedupe_latest_per_track_container`` before building ``all_collidable`` —
fixes a round-1-review minor finding that this renderer still computed off
the undeduped ``tracks[]`` and could diverge from the collector's fixed
output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Coordination thresholds — imported from the single source of truth.
# (Finding #3 migration: TASK-018 replaced the former P1 local constants with
# this import.  See aria/skills/state-scanner/lib/constants.py.)
#
# Import strategy: track_board.py is loaded in two different contexts:
#   (a) Via test harness: scripts/ is on sys.path, so "renderers" is a
#       top-level package — relative import "..lib" would cross above the
#       top-level package and fail.
#   (b) Via scan.py / proper package install: full package hierarchy available.
# We use a try/except to handle both cases cleanly.
# ---------------------------------------------------------------------------

try:
    from ..lib.constants import HEARTBEAT_INTERVAL, STALE_TTL, CLOCK_SKEW_WARN_THRESHOLD
    from ..lib.claim_schema import ClaimRecord
    from ..lib.reconcile import reconcile_all, ReconcileVerdict
    # Collision helpers: single source of truth in lib/collision.py (TASK-000 #133).
    # The renderer no longer keeps a private copy — both renderer and the
    # handoff_multibranch collector consume the same classification logic.
    from ..lib.collision import (
        split_owner_container as _split_owner_container,
        track_to_claim_record as _track_to_claim_record,
        classify_claims as _classify_collision,
        identity_drift_advisories as _identity_drift_advisories,
        filter_layer_h_fresh as _filter_layer_h_fresh,
    )
    _RECONCILE_AVAILABLE = True
except ImportError:
    # Fallback: inject the state-scanner root (parent of lib/) into sys.path so
    # that "lib" is importable as a package (preserving relative imports inside it).
    # This path is:  scripts/renderers/../../..  →  state-scanner/
    # Note: adding lib/ itself would break lib's internal relative imports.
    import sys as _sys
    from pathlib import Path as _Path
    _SS_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
    if _SS_ROOT not in _sys.path:
        _sys.path.insert(0, _SS_ROOT)
    # Also add scripts/ so that top-level "renderers" package remains importable
    # (already done by the test harness, but explicit here for robustness).
    _SCRIPTS_DIR = str(_Path(__file__).resolve().parent.parent)
    if _SCRIPTS_DIR not in _sys.path:
        _sys.path.insert(0, _SCRIPTS_DIR)
    try:
        from lib.constants import HEARTBEAT_INTERVAL, STALE_TTL, CLOCK_SKEW_WARN_THRESHOLD  # type: ignore[import]
        from lib.claim_schema import ClaimRecord  # type: ignore[import]
        from lib.reconcile import reconcile_all, ReconcileVerdict  # type: ignore[import]
        from lib.collision import (  # type: ignore[import]
            split_owner_container as _split_owner_container,
            track_to_claim_record as _track_to_claim_record,
            classify_claims as _classify_collision,
            identity_drift_advisories as _identity_drift_advisories,
            filter_layer_h_fresh as _filter_layer_h_fresh,
        )
        _RECONCILE_AVAILABLE = True
    except ImportError:
        # Last resort: lib package still not importable (very unusual environment).
        # Fall back to a local-only constants import (no reconcile capability).
        _LIB_DIR = str(_Path(__file__).resolve().parent.parent.parent / "lib")
        if _LIB_DIR not in _sys.path:
            _sys.path.insert(0, _LIB_DIR)
        from constants import HEARTBEAT_INTERVAL, STALE_TTL  # type: ignore[import]
        CLOCK_SKEW_WARN_THRESHOLD = 30  # local sentinel — lib unavailable
        # lib.collision could not be imported (it uses relative imports that need
        # the lib package). Bind the names so module-level references stay valid;
        # they are only ever *called* on the reconcile-available path, which is
        # disabled here, so the basic _detect_collisions fallback is used instead.
        _split_owner_container = None  # type: ignore[assignment]
        _track_to_claim_record = None  # type: ignore[assignment]
        _classify_collision = None  # type: ignore[assignment]
        _identity_drift_advisories = None  # type: ignore[assignment]
        _filter_layer_h_fresh = None  # type: ignore[assignment]
        _RECONCILE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Collision-classification-input dedupe (aria-plugin#155, round 2).
#
# Shared with the handoff_multibranch collector (single source of truth —
# imported verbatim, never re-implemented here) so that render_track_board's
# COLLISION lines and the collector's persisted tracks_multibranch.collision
# always agree on the SAME snapshot. Before this fix the renderer fed the
# raw, undeduped tracks[] straight into collidability/reconcile, so a track
# with stale "status: active" historical handoff rows (see
# handoff_multibranch.py's own module docstring for the bug this guards
# against) could still show a phantom "⚠ COLLISION" line on the board even
# after the collector itself had already stopped reporting a collision for
# that same track — a divergence flagged in round-1 review.
#
# No dependency on lib/ here: unlike ``lib`` (two same-named packages exist
# in this skill — see the ladder above and aria-plugin#134), ``collectors``
# exists in exactly ONE place (scripts/collectors/), so a plain two-level
# fallback is enough; it fails soft to None (never crashes renderer import)
# so a missing dedupe helper degrades the board to its pre-#155 behaviour
# rather than breaking the whole module.
# ---------------------------------------------------------------------------
try:
    from ..collectors.handoff_multibranch import (
        dedupe_latest_per_track_container as _dedupe_tracks_for_collision,
    )
except ImportError:
    try:
        from collectors.handoff_multibranch import (  # type: ignore[import]
            dedupe_latest_per_track_container as _dedupe_tracks_for_collision,
        )
    except ImportError:
        _dedupe_tracks_for_collision = None  # type: ignore[assignment]

# Maximum characters for the TRACK column before truncation.
MAX_TRACK_ID_LEN: int = 40

# Sentinel for missing / None field values in rendered output.
MISSING: str = "—"

# Column widths (fixed for alignment).
# OWNER col is 24 (not 22) to give a 2-char visual gap when owner is exactly
# "owner/container/session" length; keeps PHASE readable without separator chars.
_COL_TRACK: int = 30
_COL_OWNER: int = 24
_COL_PHASE: int = 7
_COL_HANDOFF: int = 14
_COL_PING: int = 10
_COL_STATUS: int = 22


# ---------------------------------------------------------------------------
# Helpers — time / formatting
# ---------------------------------------------------------------------------


def _parse_utc(iso: str | None) -> Optional[datetime]:
    """Parse an ISO 8601 string to a UTC-aware datetime; return None on failure."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _relative_age(dt: Optional[datetime], now: datetime) -> str:
    """Return a human-readable relative age string like '3m ago' or '2d ago'.

    Returns MISSING when dt is None.
    """
    if dt is None:
        return MISSING
    delta_s = int((now - dt).total_seconds())
    if delta_s < 0:
        # Clock skew: future timestamp — show 0m ago rather than negative
        return "0m ago"
    if delta_s < 3600:
        return f"{delta_s // 60}m ago"
    if delta_s < 86400:
        return f"{delta_s // 3600}h ago"
    return f"{delta_s // 86400}d ago"


def _age_seconds(dt: Optional[datetime], now: datetime) -> Optional[int]:
    """Return integer age in seconds, or None when dt is None."""
    if dt is None:
        return None
    delta = int((now - dt).total_seconds())
    return max(delta, 0)  # clamp negative (clock skew)


def _handoff_date(updated_at: str | None) -> str:
    """Extract the YYYY-MM-DD date portion from an ISO timestamp or return MISSING."""
    if not updated_at:
        return MISSING
    # Try ISO parse first
    dt = _parse_utc(updated_at)
    if dt is not None:
        return dt.strftime("%Y-%m-%d")
    # Might be a bare date already (e.g. "2026-05-17")
    if len(updated_at) >= 10:
        return updated_at[:10]
    return MISSING


def _truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis if longer than max_len."""
    if len(s) <= max_len:
        return s
    # Leave room for '...' (3 chars)
    return s[: max(max_len - 3, 1)] + "..."


def _cell(value: str, width: int) -> str:
    """Left-justify value in a fixed-width cell, padding with spaces."""
    return value.ljust(width)


# ---------------------------------------------------------------------------
# Freshness + status classification
# ---------------------------------------------------------------------------


def _freshness_status(age_s: Optional[int]) -> str:
    """Return the STATUS string based purely on age in seconds.

    Used when frontmatter status is "active" or unknown.
    """
    if age_s is None:
        return f"{MISSING} (no timestamp)"
    if age_s < HEARTBEAT_INTERVAL:
        return "🟢 active"
    if age_s < STALE_TTL:
        return "🟡 stale? 待确认"
    return "🔴 abandoned? 可接管"


def _classify_track(track: dict, now: datetime) -> tuple[str, str]:
    """Return (partition, status_text) for a track dict.

    Partitions:
        "active"    — rendered in the main table (active / stale / abandoned by age)
        "done"      — collapsed into Done section
        "abandoned" — collapsed into Abandoned section
        "legacy"    — rendered in the main table with legacy marker
    """
    status_field = (track.get("status") or "").lower().strip()
    updated_at = track.get("updated_at") or ""

    if status_field == "done":
        return "done", "done"

    if status_field == "abandoned":
        return "abandoned", "abandoned"

    if status_field == "legacy":
        # Legacy tracks: no heartbeat signal, mark distinctly
        return "active", "🟡 legacy"

    # active or anything else → use freshness
    dt = _parse_utc(updated_at)
    age_s = _age_seconds(dt, now)
    return "active", _freshness_status(age_s)


# ---------------------------------------------------------------------------
# Collision detection — TASK-017 upgrade; helpers relocated in TASK-000 (#133)
# ---------------------------------------------------------------------------
#
# _split_owner_container / _track_to_claim_record / _classify_collision were
# promoted to lib/collision.py (single source of truth) so the renderer AND the
# handoff_multibranch collector share one implementation. They are imported at
# the top of this module (aliased to the same private names). Behaviour is
# identical; this removes the divergent private copy that was the phantom-field
# root cause (sister R1 C1). See lib/collision.py.


def _render_collision_lines(
    verdicts: "dict[str, ReconcileVerdict]",
    tracks_by_track_id: "dict[str, list[dict]]",
) -> list[str]:
    """Render COLLISION and clock-skew warning lines from reconcile verdicts.

    One line per track with a real collision — ``verdict.yielders`` non-empty
    AND ``_classify_collision`` (classify_claims) resolves the yielder+winner
    set to "cross_owner" or "self_multi_container" (round 2, #155: a "none"
    classification renders NO line — see the ``elif collision_kind ==
    "none"`` branch below — matching ``lib/collision.py::classify()``, the
    persisted-summary counterpart this must agree with).
    An additional ⚠ 时钟偏移 line is appended when verdict.conflict=True,
    regardless of collision_kind (clock skew is an independent signal).

    Note: when the reconcile winner was flagged as stale-takeover-eligible,
    ``verdict.winner`` is None but the stale winner is in ``verdict.superseded``.
    We use the owner_container strings from the original track dicts as labels
    (more human-readable than reconstructing from ClaimRecord fields).

    Line formats:
        cross-owner:
            ⚠ COLLISION cross-owner <tid>: <winner> (胜) vs <y1>, <y2> (应 yield)
        cross-owner (stale winner):
            ⚠ COLLISION cross-owner <tid>: <stale> (胜,stale) vs <y1> (应 yield)
        self-multi-container:
            ⚠ COLLISION self-multi-container <tid>: <a> vs <b> (soft hint, 可能容器迁移)
        clock skew (appended after collision line):
            ⚠ 时钟偏移 <tid>: max diff <N>s > threshold <T>s — reconcile CONFLICT
    """
    lines: list[str] = []

    for tid in sorted(verdicts.keys()):
        verdict = verdicts[tid]

        # Collect all non-terminal claims to classify collision type.
        # Yielders are always active candidates; winner may be None (stale) but
        # was an active candidate — include it for classification.
        active_claims: list = list(verdict.yielders)
        if verdict.winner:
            active_claims.append(verdict.winner)
        # aria-plugin#155 (round 2): also recover any claim reconcile moved
        # into `superseded` for a reason OTHER than a genuinely terminal
        # status — i.e. a stale-takeover-eligible winner (Rule 6) — mirroring
        # lib/collision.py::classify()'s IDENTICAL recovery, for the
        # identical documented reason there: without it, a real 2-claim
        # collision where the winner happens to be stale loses one of its
        # two active claimants (the winner drops to `superseded`, `winner`
        # becomes None) and `_classify_collision` sees only the lone
        # yielder — misclassifying a genuine self_multi_container/cross_owner
        # collision as "none". Confirmed against this project's own real
        # tracks_multibranch data (aria-submodule-gate-block-flip) — omitting
        # this recovery is exactly what made the board disagree with the
        # persisted tracks_multibranch.collision on that track.
        active_claims.extend(
            c for c in verdict.superseded if c.status not in ("done", "abandoned")
        )

        if not verdict.yielders:
            # No yielders → no collision line.
            # Still emit clock-skew line if conflict=True (defensive).
            if verdict.conflict and verdict.max_clock_skew_seconds is not None:
                display_tid = _truncate(tid, MAX_TRACK_ID_LEN)
                lines.append(
                    f"⚠ 时钟偏移 {display_tid}: "
                    f"max diff {verdict.max_clock_skew_seconds}s "
                    f"> threshold {CLOCK_SKEW_WARN_THRESHOLD}s — reconcile CONFLICT"
                )
            continue

        display_tid = _truncate(tid, MAX_TRACK_ID_LEN)

        # Use original owner_container strings as display labels (they are more
        # human-readable and already in "owner/container/session" format).
        # Build a lookup: (owner, container, session) → original owner_container str.
        oc_by_key: dict[tuple[str, str, str], str] = {}
        for t in (tracks_by_track_id.get(tid) or []):
            oc = t.get("owner_container") or "unknown"
            o, c, s = _split_owner_container(oc)
            # Normalise exactly like track_to_claim_record ("" -> "unknown") or the
            # two-part strings never match their ClaimRecord and the board echoes
            # the reconstructed "unknown/..." form (SC-4 board echo).
            oc_by_key[(o or "unknown", c or "unknown", s or "unknown")] = oc

        def _label(claim: "ClaimRecord") -> str:
            key = (claim.owner, claim.container, claim.session)
            return oc_by_key.get(key) or f"{claim.owner}/{claim.container}/{claim.session}"

        # Determine if winner was stale-flagged (winner=None in that case, but
        # the stale winner landed in superseded — find it for display).
        stale_winner_label: Optional[str] = None
        if verdict.winner is None and verdict.yielders:
            # Look for the superseded entry whose claimed_at is earliest
            # (that was the stale winner).  Simple heuristic: the superseded
            # entry with the lexicographically earliest claimed_at.
            if verdict.superseded:
                stale_claim = min(verdict.superseded, key=lambda c: c.claimed_at)
                stale_winner_label = _label(stale_claim)

        collision_kind, _severity = _classify_collision(active_claims)

        if collision_kind == "cross_owner":
            if verdict.winner:
                winner_label = _label(verdict.winner)
                winner_suffix = " (胜)"
            elif stale_winner_label:
                winner_label = stale_winner_label
                winner_suffix = " (胜,stale)"
            else:
                winner_label = "(none)"
                winner_suffix = ""
            yielder_labels = ", ".join(_label(y) for y in verdict.yielders)
            lines.append(
                f"⚠ COLLISION cross-owner {display_tid}: "
                f"{winner_label}{winner_suffix} vs {yielder_labels} (应 yield)"
            )
        elif collision_kind == "self_multi_container":
            all_labels = sorted(
                [_label(c) for c in active_claims]
                + ([stale_winner_label] if stale_winner_label and not verdict.winner else [])
            )
            # Deduplicate (stale winner may already be in active_claims analysis)
            seen: set[str] = set()
            unique_labels = [lb for lb in all_labels if not (lb in seen or seen.add(lb))]  # type: ignore[func-returns-value]
            labels_str = " vs ".join(unique_labels)
            lines.append(
                f"⚠ COLLISION self-multi-container {display_tid}: "
                f"{labels_str} (soft hint, 可能容器迁移)"
            )
        elif collision_kind == "none":
            # aria-plugin#155 (round 2): classify_claims (_classify_collision)
            # can legitimately return "none" here even though
            # verdict.yielders is non-empty — reconcile's yielders/winner
            # split does not itself apply the owner/container/terminal-status
            # filtering classify_claims does (e.g. once a stale winner drops
            # out and only one non-terminal claim remains, or two claims
            # share the same owner+container — "self-serial", not a real
            # collision). No line for this track — matches
            # lib/collision.py::classify(), which skips "none" tracks when
            # building the persisted tracks_multibranch.collision.groups.
            # (Prior code had no branch for this case and fell into the
            # `else` fallback below, which unconditionally rendered a
            # COLLISION line — the exact source of a round-1-review-caught
            # board/collector divergence on this project's own real data.)
            pass
        else:
            # Defensive fallback only: _classify_collision (classify_claims)
            # has exactly three return values ("cross_owner",
            # "self_multi_container", "none"), all handled above, so this
            # branch is unreachable in practice — kept in case a future
            # classify_claims revision adds a kind this renderer doesn't
            # know about yet, rather than silently dropping it.
            if verdict.winner:
                winner_label = _label(verdict.winner)
            elif stale_winner_label:
                winner_label = stale_winner_label
            else:
                winner_label = "(none)"
            yielder_labels = ", ".join(_label(y) for y in verdict.yielders)
            lines.append(
                f"⚠ COLLISION {display_tid}: {winner_label} vs {yielder_labels}"
            )

        # Clock-skew line (appended after the collision line for the same
        # track — independent of collision_kind: reconcile can detect clock
        # disagreement between active candidates regardless of whether
        # classify_claims later excludes them from the "official" collision
        # kind, e.g. two same-owner+container claims with skewed clocks).
        if verdict.conflict and verdict.max_clock_skew_seconds is not None:
            lines.append(
                f"⚠ 时钟偏移 {display_tid}: "
                f"max diff {verdict.max_clock_skew_seconds}s "
                f"> threshold {CLOCK_SKEW_WARN_THRESHOLD}s — reconcile CONFLICT"
            )

    return lines


def _detect_collisions(active_tracks: list[dict]) -> list[str]:
    """P1 basic collision detector: same track_id with ≥2 distinct owner_container.

    Retained as fallback when reconcile-based path fails (ClaimRecord construction
    error, or reconcile module unavailable).  Returns ⚠ COLLISION lines.
    """
    from collections import defaultdict

    owners_by_track: dict[str, set[str]] = defaultdict(set)
    for t in active_tracks:
        tid = t.get("track_id") or ""
        owner = t.get("owner_container") or "unknown"
        if tid:
            owners_by_track[tid].add(owner)

    lines: list[str] = []
    for tid, owners in sorted(owners_by_track.items()):
        if len(owners) >= 2:
            owners_sorted = sorted(owners)
            owner_str = " vs ".join(owners_sorted)
            display_tid = _truncate(tid, MAX_TRACK_ID_LEN)
            lines.append(f"⚠ COLLISION {display_tid}: {owner_str}")
    return lines


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def _render_row(track: dict, status_text: str, now: datetime) -> str:
    """Render a single table data row."""
    track_id_raw = track.get("track_id") or MISSING
    track_id = _truncate(track_id_raw, MAX_TRACK_ID_LEN)

    owner = track.get("owner_container") or MISSING
    phase = track.get("phase") or MISSING
    if phase in ("unknown", ""):
        phase = MISSING

    updated_at = track.get("updated_at") or ""
    handoff_date = _handoff_date(updated_at)

    dt = _parse_utc(updated_at)
    last_ping = _relative_age(dt, now)

    row = (
        _cell(track_id, _COL_TRACK)
        + _cell(owner, _COL_OWNER)
        + _cell(phase, _COL_PHASE)
        + _cell(handoff_date, _COL_HANDOFF)
        + _cell(last_ping, _COL_PING)
        + status_text
    )
    return row


def _render_header() -> str:
    """Return the column header row."""
    return (
        _cell("TRACK", _COL_TRACK)
        + _cell("OWNER/容器/会话", _COL_OWNER)
        + _cell("PHASE", _COL_PHASE)
        + _cell("HANDOFF", _COL_HANDOFF)
        + _cell("LAST-PING", _COL_PING)
        + "STATUS"
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def render_track_board(
    snapshot: dict,
    now: Optional[datetime] = None,
) -> str:
    """Render the multi-track coordination board from a scan.py snapshot dict.

    Args:
        snapshot: Full scan.py snapshot dict.  The renderer reads:
                  - ``snapshot["tracks_multibranch"]`` (from TASK-004)
                  - ``snapshot["coordination_fetch"]``  (from TASK-007)
        now:      UTC datetime to use as "current time" for freshness
                  calculations.  Pass a fixed value in tests for determinism.
                  Defaults to ``datetime.now(timezone.utc)``.

    Returns:
        Multi-line rendered board string.  No trailing newline.
        Never raises — all missing/malformed fields produce graceful fallback.

    Example output:
        === 多 Track 协调看板 (fetch @ 2026-05-19T09:50Z) ===
        TRACK                         OWNER/容器/会话        PHASE  HANDOFF        LAST-PING  STATUS
        spec-y-redo-aux               hikari/devbox-A/s-7f3a  B 7/9  2026-05-17     2m ago     🟢 active
        h-series-closeout             hikari/devbox-A/s-22b1  D      2026-05-18     3h ago     🟡 stale? 待确认
        m6-us026-docs                 hikari/devbox-C/s-9e0   A.1    2026-05-17     2d ago     🔴 abandoned? 可接管
        --- Done (1) ---
        --- Abandoned (0) ---
        ⚠ COLLISION cross-owner spec-y-redo-aux: hikari/devbox-A/s-7f3a (胜) vs creator/laptop/s-1c4 (应 yield)
        ⚠ COLLISION self-multi-container m6-us026-docs: hikari/devbox-A/s-7f3a vs hikari/devbox-B/s-2bc (soft hint, 可能容器迁移)
        ⚠ 时钟偏移 m6-us026-docs: max diff 87s > threshold 30s — reconcile CONFLICT
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    lines: list[str] = []

    # ── Read coordination_fetch signal (TASK-007 interface) ───────────────────
    cf: dict = snapshot.get("coordination_fetch") or {}
    degraded: bool = bool(cf.get("degraded", False))
    cached: bool = bool(cf.get("cached", False))
    last_fetch_at: str = cf.get("last_fetch_at") or ""
    age_seconds: int = int(cf.get("age_seconds") or 0)
    error_msg: str | None = cf.get("error_msg")
    degradation_reason: str | None = cf.get("degradation_reason")

    # ── Offline red-bar ───────────────────────────────────────────────────────
    if degraded:
        reason_detail = degradation_reason or error_msg or "fetch 失败"
        lines.append(
            f"⚠ 离线: 看板可能陈旧, 重复劳动风险升高 (fetch 失败 @ {reason_detail})"
        )

    # ── Cache hint (only when cached but not degraded) ────────────────────────
    elif cached:
        lines.append(f"(缓存于 {age_seconds}s 前)")

    # ── Coordination-ref fetch-failure yellow-bar (F5, Aria #144) ─────────────
    # Fetch 1 (branch heads) succeeded but Fetch 2 (coordination ref) failed
    # non-benign (network/timeout) → branch view is FRESH but the coordination
    # data may be stale. coordination_fetch emits a `coordination_ref_fetch_failed`
    # soft_error (snapshot errors[] + exit 10), but the board would otherwise
    # render all-green (success=True, degraded=False) — a half-silent failure.
    # Surface a non-blocking yellow advisory. The errors[] entry is the authoritative
    # marker (this kind fires ONLY for the Fetch-2-non-benign path). Skipped when
    # degraded (the red offline bar already signals staleness — red takes precedence).
    if not degraded and any(
        e.get("error") == "coordination_ref_fetch_failed"
        for e in (snapshot.get("errors") or [])
    ):
        lines.append(
            "⚠ 协调 ref 未取到 (网络/超时), 队友协调数据可能陈旧 (分支视图仍新鲜)"
        )

    # ── Not-refreshed advisory (F3′ Phase 1 increment 5, task 3.14 hidden cell) ──
    # `coordination_fetch.degraded`/`cached` (derived from the legacy 2-state
    # success/fail shim) CANNOT distinguish "this scan tried to fetch and
    # failed" from "this scan never got around to fetching this leg" (deadline
    # cut / backoff) — `fetch_ok=="not_attempted"` never satisfies `degraded`'s
    # `fetch_ok=="false"` clause (blueprint top_risks). Read the THREE-STATE
    # `fetch_ok` straight off the `remote_refresh` (Phase 0.5) top-level block
    # for the (".", "origin") leg to surface a third, non-red advisory.
    # Additive: `remote_refresh` is absent from pre-increment-5 snapshots/test
    # fixtures, so `rr.get("legs")` is `[]`/missing and this never fires there.
    if not degraded:
        rr: dict = snapshot.get("remote_refresh") or {}
        origin_fetch_ok: str | None = None
        for leg in rr.get("legs") or []:
            if isinstance(leg, dict) and leg.get("repo") == "." and leg.get("remote") == "origin":
                origin_fetch_ok = leg.get("fetch_ok")
                break
        if origin_fetch_ok == "not_attempted":
            lines.append(
                "⚠ 未刷新: 本次 scan 未及时 fetch 协调数据 (deadline/backoff 跳过), 数据可能不是最新"
            )

    # ── Board header ──────────────────────────────────────────────────────────
    fetch_ts = last_fetch_at[:16] + "Z" if last_fetch_at else "未知"
    lines.append(f"=== 多 Track 协调看板 (fetch @ {fetch_ts}) ===")

    # ── Read tracks_multibranch (TASK-004 interface) ──────────────────────────
    tmb: dict = snapshot.get("tracks_multibranch") or {}

    # Guard: tracks_multibranch key missing entirely
    if not tmb:
        lines.append("(no tracks data)")
        return "\n".join(lines)

    tracks: list[dict] = tmb.get("tracks") or []

    # Guard: empty tracks
    if not tracks:
        lines.append("(no active tracks)")
        return "\n".join(lines)

    # ── Classify tracks into partitions ───────────────────────────────────────
    active_rows: list[tuple[dict, str]] = []   # (track_dict, status_text)
    done_tracks: list[dict] = []
    abandoned_tracks: list[dict] = []

    for track in tracks:
        partition, status_text = _classify_track(track, now)
        if partition == "done":
            done_tracks.append(track)
        elif partition == "abandoned":
            abandoned_tracks.append(track)
        else:
            active_rows.append((track, status_text))

    # ── Sort active rows: newest (smallest age) first ─────────────────────────
    def _sort_key(item: tuple[dict, str]) -> int:
        t = item[0]
        dt = _parse_utc(t.get("updated_at") or "")
        a = _age_seconds(dt, now)
        return a if a is not None else 999_999_999

    active_rows.sort(key=_sort_key)

    # ── Render table ──────────────────────────────────────────────────────────
    lines.append(_render_header())
    lines.append("-" * (_COL_TRACK + _COL_OWNER + _COL_PHASE + _COL_HANDOFF + _COL_PING + _COL_STATUS))

    if active_rows:
        for track, status_text in active_rows:
            lines.append(_render_row(track, status_text, now))
    else:
        lines.append("(no active tracks)")

    # ── Collapsed sections ────────────────────────────────────────────────────
    lines.append(f"--- Done ({len(done_tracks)}) ---")
    lines.append(f"--- Abandoned ({len(abandoned_tracks)}) ---")

    # ── Collision detection — TASK-017 reconcile-based path with P1 fallback ────
    #
    # aria-plugin#155 (round 2): dedupe historical (track_id, owner_container)
    # rows down to the updated_at-latest one (filename tie-break — same
    # function, same semantics as the collector's own collision-classification
    # input) BEFORE computing collidability, so the board and the persisted
    # tracks_multibranch.collision agree on the same snapshot. This only
    # affects which row represents a (track_id, owner_container) pair in the
    # collision computation below — the visible table above still renders
    # every row in tracks[] (full, undeduped history).
    collision_input_tracks = (
        _dedupe_tracks_for_collision(tracks)[0]
        if _dedupe_tracks_for_collision is not None
        else tracks
    )
    # owner-container-identity-key D-3(a): same Layer H window as the collector
    # (one implementation in lib/collision — SC-11), applied after dedupe.
    if _filter_layer_h_fresh is not None:
        collision_input_tracks = _filter_layer_h_fresh(collision_input_tracks, now=now)

    # Collidable = all tracks with a real owner_container (not "unknown"), so
    # that done/abandoned tracks that are still on the same track_id (potential
    # race artifacts) participate in the verdict.  However, a track whose only
    # contribution is a terminal-status claim won't produce yielders in reconcile,
    # so the net effect is: terminal-only tracks → no collision line.
    all_collidable = [
        t for t in collision_input_tracks
        if (t.get("owner_container") or "unknown") != "unknown"
    ]

    collision_lines: list[str] = []
    reconcile_used = False

    if _RECONCILE_AVAILABLE and all_collidable:
        # Attempt P2 reconcile-based path.
        # Build ClaimRecord placeholders. aria-plugin#155 (round 2): each
        # track is converted INDEPENDENTLY (try/except per item, mirroring
        # lib/collision.py::classify()'s own fail-soft loop) rather than the
        # prior all-or-nothing list comprehension. That prior form meant ONE
        # track anywhere in the whole collidable set with a malformed field
        # (e.g. a non-ISO-8601 updated_at — real data on this repo has one:
        # a stray "2026-05-28T~14:00Z") silently discarded the ENTIRE
        # reconcile-based verdict for every OTHER track too, falling back to
        # the cruder, status-blind P1 `_detect_collisions` board-wide — while
        # the collector kept classifying fine (its own per-item fail-soft
        # skip only drops the one bad track). That divergence is exactly
        # what made the board disagree with tracks_multibranch.collision on
        # this repo's own real data even after dedupe-input parity was
        # fixed. A genuinely fatal, non-per-item failure (e.g. reconcile_all
        # itself raising) still falls through to the outer except below.
        try:
            claim_records: list["ClaimRecord"] = []
            for t in all_collidable:
                try:
                    claim_records.append(_track_to_claim_record(t))
                except ValueError:
                    continue  # fail-soft: skip only this malformed track

            # Build a parallel index: track_id → list of original track dicts
            # (used by _render_collision_lines to reconstruct human-readable labels).
            # Keyed by the ClaimRecord track_id (D-0(a) family key already
            # stripped) so the lookup matches reconcile's verdict keys.
            tracks_by_tid: dict[str, list[dict]] = {}
            for t in all_collidable:
                try:
                    tid = _track_to_claim_record(t).track_id
                except ValueError:
                    continue
                if tid:
                    tracks_by_tid.setdefault(tid, []).append(t)

            verdicts = reconcile_all(claim_records, now=now)
            collision_lines = _render_collision_lines(verdicts, tracks_by_tid)
            reconcile_used = True
        except Exception:  # noqa: BLE001 — defensive: any OTHER failure → fallback
            reconcile_used = False

    if not reconcile_used:
        # P1 fallback: basic collision detection (no reconcile, no clock-skew)
        collision_lines = _detect_collisions(all_collidable)

    for cl in collision_lines:
        lines.append(cl)

    # ⚪ same-identity-multi-owner advisories (owner-container-identity-key D3,
    # SC-10): independent data path — computed from the RAW tracks (pre-dedupe;
    # dedupe folds exactly the rows this must see), rendered after the
    # collision lines, no section at all when empty.
    if _identity_drift_advisories is not None:
        try:
            for adv in _identity_drift_advisories(tracks):
                owners = ", ".join(adv.get("owners") or [])
                lines.append(
                    f"⚪ IDENTITY-DRIFT {adv.get('identity_key')}: owners=[{owners}] "
                    f"first_seen={adv.get('first_seen') or '?'} last_seen={adv.get('last_seen') or '?'} "
                    f"(同一容器多个 git 身份, 信息级; 不计入 collision)"
                )
        except Exception:  # noqa: BLE001 — advisory must never break the board
            pass

    return "\n".join(lines)
