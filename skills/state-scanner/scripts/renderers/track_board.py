"""Multi-track coordination board renderer (TASK-005, extended in TASK-017).

Consumes the ``tracks_multibranch`` and ``coordination_fetch`` snapshot keys
produced by TASK-004 (handoff_multibranch.py) and TASK-007 (coordination_fetch.py)
and renders an ASCII table for display in the state-scanner Phase 1 output.

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

Collision detection (TASK-017 upgrade — reconcile-based):
    Primary path (P2): reconcile_all() from lib/reconcile.py drives detection.
      - cross-owner collision (≥2 distinct owners): 🔴 strong warning
      - self-multi-container collision (same owner, ≥2 containers): 🟡 soft hint
      - clock skew conflict (ReconcileVerdict.conflict=True): ⚠ 时钟偏移 line
    Fallback path (P1 basic, if ClaimRecord construction fails):
      Same track_id with ≥2 distinct owner_container values → ⚠ COLLISION line.

Spec:  openspec/changes/multi-terminal-coordination/tasks.md §2.7
Task:  TASK-017 (backend-architect); extends TASK-005 P1
Deps:  TASK-004 (tracks_multibranch), TASK-007 (coordination_fetch),
       TASK-015 (reconcile / ReconcileVerdict)
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
        _RECONCILE_AVAILABLE = True
    except ImportError:
        # Last resort: lib package still not importable (very unusual environment).
        # Fall back to a local-only constants import (no reconcile capability).
        _LIB_DIR = str(_Path(__file__).resolve().parent.parent.parent / "lib")
        if _LIB_DIR not in _sys.path:
            _sys.path.insert(0, _LIB_DIR)
        from constants import HEARTBEAT_INTERVAL, STALE_TTL  # type: ignore[import]
        CLOCK_SKEW_WARN_THRESHOLD = 30  # local sentinel — lib unavailable
        _RECONCILE_AVAILABLE = False

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
# Collision detection — TASK-017 upgrade
# ---------------------------------------------------------------------------


def _split_owner_container(owner_container: str) -> tuple[str, str, str]:
    """Split an owner_container string into (owner, container, session).

    Expected format: "owner/container/session" (3 parts).
    Handles shorter / malformed strings gracefully by filling missing parts
    with empty-string sentinels so callers can still reason about owner.

    Examples:
        "hikari/devbox-A/s-7f3a"  → ("hikari", "devbox-A", "s-7f3a")
        "devbox-A/sess-001"       → ("", "devbox-A", "sess-001")   # 2-part
        "solo"                    → ("", "", "solo")                # 1-part
        ""                        → ("", "", "")
    """
    parts = (owner_container or "").split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        # Two-part: treat as container/session (owner unknown)
        return "", parts[0], parts[1]
    # One-part or empty
    return "", "", parts[0] if parts else ""


def _track_to_claim_record(track: dict) -> "ClaimRecord":
    """Approximate a Layer H track dict as a ClaimRecord placeholder for reconcile.

    Layer H data (handoff frontmatter) lacks independent heartbeat_at; we use
    updated_at as a near-approximation for both claimed_at and heartbeat_at.
    This is intentionally lossy — the reconcile result is advisory/visual only.

    P2 note: when true Layer L ClaimRecords are available from read_claims(),
    the board should bypass this function and feed them directly to reconcile_all.

    Raises ValueError if required fields are missing/unparseable — caller must
    catch and fall back to the basic collision detector.
    """
    if not _RECONCILE_AVAILABLE:
        raise ValueError("reconcile module not available")

    owner_container = track.get("owner_container") or ""
    owner, container, session = _split_owner_container(owner_container)

    track_id = track.get("track_id") or ""
    if not track_id:
        raise ValueError("track_id missing")

    updated_at = track.get("updated_at") or ""
    if not updated_at:
        raise ValueError("updated_at missing — cannot approximate claimed_at")

    # Validate that updated_at is parseable ISO 8601 (reconcile requires this)
    try:
        from datetime import datetime as _dt
        _dt.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"updated_at not valid ISO 8601: {updated_at!r}") from exc

    # Map track status to a ClaimRecord-compatible status value.
    # Layer H "legacy" → treat as "active" (Layer L has no "legacy" status).
    status_raw = (track.get("status") or "active").lower().strip()
    if status_raw in ("active", "legacy"):
        status = "active"
    elif status_raw == "done":
        status = "done"
    elif status_raw == "abandoned":
        # ClaimRecord STATUS_WRITABLE only has active/yielded/done; map abandoned→done
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


def _classify_collision(
    claims: "list[ClaimRecord]",
) -> tuple[str, str]:
    """Classify a set of active claims for the same track_id.

    Returns (collision_kind, severity_emoji):
        collision_kind: 'cross_owner' | 'self_multi_container' | 'none'
        severity_emoji: '🔴' | '🟡' | ''

    Logic (per session-handoff.md §2.3.5):
        cross_owner          → ≥2 distinct owner values across active claims
        self_multi_container → same owner, ≥2 distinct container values
        none                 → ≤1 active claim or all same owner+container
    """
    active = [c for c in claims if c.status not in ("done", "abandoned")]
    if len(active) < 2:
        return "none", ""

    owners = {c.owner for c in active}
    if len(owners) >= 2:
        return "cross_owner", "🔴"

    containers = {c.container for c in active}
    if len(containers) >= 2:
        return "self_multi_container", "🟡"

    return "none", ""


def _render_collision_lines(
    verdicts: "dict[str, ReconcileVerdict]",
    tracks_by_track_id: "dict[str, list[dict]]",
) -> list[str]:
    """Render COLLISION and clock-skew warning lines from reconcile verdicts.

    One line per track with a real collision (yielders present).
    An additional ⚠ 时钟偏移 line is appended when verdict.conflict=True.

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
            oc_by_key[(o, c, s)] = oc

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
        else:
            # Fallback: collision detected by reconcile but classification unclear
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

        # Clock-skew line (appended after the collision line for the same track)
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
    # Collidable = all tracks with a real owner_container (not "unknown"), so
    # that done/abandoned tracks that are still on the same track_id (potential
    # race artifacts) participate in the verdict.  However, a track whose only
    # contribution is a terminal-status claim won't produce yielders in reconcile,
    # so the net effect is: terminal-only tracks → no collision line.
    all_collidable = [
        t for t in tracks
        if (t.get("owner_container") or "unknown") != "unknown"
    ]

    collision_lines: list[str] = []
    reconcile_used = False

    if _RECONCILE_AVAILABLE and all_collidable:
        # Attempt P2 reconcile-based path.
        # Build ClaimRecord placeholders; if any track fails construction, fall
        # back entirely to P1 basic detection for the whole board.
        try:
            claim_records = [_track_to_claim_record(t) for t in all_collidable]

            # Build a parallel index: track_id → list of original track dicts
            # (used by _render_collision_lines to reconstruct human-readable labels).
            tracks_by_tid: dict[str, list[dict]] = {}
            for t in all_collidable:
                tid = t.get("track_id") or ""
                if tid:
                    tracks_by_tid.setdefault(tid, []).append(t)

            verdicts = reconcile_all(claim_records, now=now)
            collision_lines = _render_collision_lines(verdicts, tracks_by_tid)
            reconcile_used = True
        except Exception:  # noqa: BLE001 — defensive: any failure → fallback
            reconcile_used = False

    if not reconcile_used:
        # P1 fallback: basic collision detection (no reconcile, no clock-skew)
        collision_lines = _detect_collisions(all_collidable)

    for cl in collision_lines:
        lines.append(cl)

    return "\n".join(lines)
