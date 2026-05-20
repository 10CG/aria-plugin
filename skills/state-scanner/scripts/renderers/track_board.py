"""Multi-track coordination board renderer (TASK-005).

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

Collision detection (basic):
    Same track_id with ≥2 distinct owner_container values → ⚠ COLLISION line
    Full reconcile/yield is out of scope (TASK-015).

Spec:  openspec/changes/multi-terminal-coordination/tasks.md §1.5
Task:  TASK-005 (backend-architect)
Deps:  TASK-004 (tracks_multibranch snapshot key), TASK-007 (coordination_fetch key)
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
    from ..lib.constants import HEARTBEAT_INTERVAL, STALE_TTL
except ImportError:
    # Fallback: inject lib/ directory into sys.path via __file__ location.
    # This path is:  scripts/renderers/../../../lib  →  state-scanner/lib/
    import sys as _sys
    from pathlib import Path as _Path
    _LIB_DIR = str(_Path(__file__).resolve().parent.parent.parent / "lib")
    if _LIB_DIR not in _sys.path:
        _sys.path.insert(0, _LIB_DIR)
    from constants import HEARTBEAT_INTERVAL, STALE_TTL  # type: ignore[import]

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
# Collision detection
# ---------------------------------------------------------------------------


def _detect_collisions(active_tracks: list[dict]) -> list[str]:
    """Detect same track_id with ≥2 distinct owner_container values.

    Returns a list of formatted ⚠ COLLISION lines.
    Full reconcile/yield is out of scope (TASK-015).
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
        ⚠ COLLISION spec-y-redo-aux: devbox-A/s-7f3a vs devbox-B/s-1c4
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

    # ── Collision detection ───────────────────────────────────────────────────
    # Check collisions across ALL tracks (not just active), using owner_container.
    # Only tracks with real owner info (not "unknown") contribute.
    all_collidable = [
        t for t in tracks
        if (t.get("owner_container") or "unknown") != "unknown"
    ]
    collision_lines = _detect_collisions(all_collidable)
    for cl in collision_lines:
        lines.append(cl)

    return "\n".join(lines)
