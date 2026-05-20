"""Layer L coordination constants — shared across all containers/implementations.

Every implementation that participates in multi-terminal coordination MUST
import from this file rather than redefining these values locally.  Divergent
local copies create the "constants dual-source" risk identified in Finding #3
(P1 audit Round 6).

References
----------
per multi-terminal-coordination tasks.md §2.8 + DEC-20260519-001 #4
    (eager claim acquisition + second-level acceptance window)
per session-handoff.md §2.3
    (frontmatter / claim field semantics)

Per Finding #3 (P1 closeout Round 6 audit), this file is the SINGLE SOURCE OF
TRUTH for Layer L heartbeat/stale/clock-skew thresholds introduced in P2.
Downstream P1 modules (track_board.py, latest_md_writer.py) were migrated to
import from here in TASK-018.
"""

# ---------------------------------------------------------------------------
# Heartbeat & staleness
# ---------------------------------------------------------------------------

# Heartbeat interval: a live claim refreshes heartbeat_at every 10 minutes.
# Phase transitions also trigger an immediate heartbeat write (outside the
# scheduled interval).
HEARTBEAT_INTERVAL: int = 600  # seconds

# Stale TTL: a claim whose heartbeat_at is older than this threshold is
# considered stale and eligible for reconcile take-over.
# Invariant: STALE_TTL == 3 * HEARTBEAT_INTERVAL.
# A claim must miss at least 3 consecutive heartbeat windows before being
# treated as abandoned — this provides tolerance for transient git push
# latency and brief network partitions.
STALE_TTL: int = 1800  # seconds

# ---------------------------------------------------------------------------
# Clock skew
# ---------------------------------------------------------------------------

# Clock-skew warning threshold: when two claims on the same track_id have
# claimed_at timestamps that differ by more than this value (in seconds),
# the track board renders a ⚠ clock-skew indicator and reconcile downgrades
# its verdict to CONFLICT rather than applying the "earliest wins" rule.
# 30 s matches NTP sync tolerance on typical developer machines.
CLOCK_SKEW_WARN_THRESHOLD: int = 30  # seconds

# ---------------------------------------------------------------------------
# Archive / GC
# ---------------------------------------------------------------------------

# Archive retention period: status='done' claims are retained in the active
# claims/ tree for this many days before gc.archive_done_claims() moves them
# to archive/<YYYY-MM>/.  The 7-day window gives operators time to inspect
# recently completed sessions before they are archived.
ARCHIVE_RETENTION_DAYS: int = 7  # days

# ---------------------------------------------------------------------------
# Informational (no enforcement)
# ---------------------------------------------------------------------------

# Coordination ref write-pressure estimate (documentation only — no hard limit).
# Each active session generates roughly 20-30 ref pushes per day:
#   - scheduled heartbeat writes (one per HEARTBEAT_INTERVAL)
#   - phase transition writes (acquire/heartbeat on transition/release)
# git orphan-ref write cost is negligible; this constant is present solely so
# capacity estimates are reproducible from code rather than from comments.
# Value is NOT used in any runtime logic.
_ESTIMATED_PUSHES_PER_SESSION_PER_DAY: int = 25  # informational only
