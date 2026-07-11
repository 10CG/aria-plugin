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

# Sweep TTL (Part C, coordination-claim-lifecycle-and-overlap; pre-merge
# review C1): the DURABLE-abandon threshold used by gc.sweep_stale_active.
# Deliberately much longer than STALE_TTL: STALE_TTL only marks a claim
# "takeover-eligible" (advisory, reversible on next read), but the sweep
# REWRITES status=abandoned durably and the victim has no recovery path —
# and in reality NO production heartbeat loop exists (heartbeat() has zero
# production call sites; phase1_gate self-resume does not refresh either),
# so every live claim's heartbeat_at is frozen at acquire time.  A 30-minute
# sweep threshold would abandon any parallel session still working after
# 30 min (the common case) and erase it from all collision/overlap advisory
# surfaces — defeating the coordination this spec exists to protect.  24h
# comfortably exceeds real interactive session lengths while still clearing
# genuinely dead claims daily.  Revisit when a heartbeat loop ships.
SWEEP_TTL: int = 86400  # seconds (24h)

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
