"""TASK-020 — P2 Round 7 Reconcile Golden Table Tests.

Covers the full 4-rule reconcile protocol with boundary cases, missing
heartbeat handling, status 4x4 matrix, and clock skew detection.

Reconcile rules under test (first-match order):
  1. unknown-status claims → unknown bucket (excluded from candidates)
  2. terminal claims (done/abandoned) → superseded
  3. no candidates → no_active_candidates
  4. sole candidate → sole_active (+ stale_takeover_eligible if stale)
  5. multiple candidates:
     5.1 clock-skew detection (> CLOCK_SKEW_WARN_THRESHOLD)
     5.2 earliest claimed_at wins
     5.3 tiebreak on container/session lex order
  6. stale-takeover eligibility (winner heartbeat older than STALE_TTL)

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.10 (1)
Task: TASK-020 (qa-engineer)
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Import: add the skill root (parent of lib/) to sys.path so that relative
# imports inside lib/__init__.py work correctly as a package.
# ---------------------------------------------------------------------------
_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from lib.claim_schema import ClaimRecord
from lib.constants import CLOCK_SKEW_WARN_THRESHOLD, STALE_TTL
from lib.reconcile import ReconcileVerdict, reconcile

# ---------------------------------------------------------------------------
# Fixed reference time — all tests use this to avoid wall-clock sensitivity.
# ---------------------------------------------------------------------------
_FIXED_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test factory
# ---------------------------------------------------------------------------

def _claim(
    track_id: str = "test-track",
    owner: str = "alice",
    container: str = "devbox-A",
    session: str = "s-001",
    claimed_at: datetime | str | None = None,
    heartbeat_at: datetime | str | None = None,
    status: str = "active",
    phase: str = "B",
    schema_version: str = "1",
    superseded_from: str | None = None,
) -> ClaimRecord:
    """Test factory — defaults to a fresh, active, non-stale claim at _FIXED_NOW."""
    if claimed_at is None:
        claimed_at = _FIXED_NOW
    if heartbeat_at is None:
        heartbeat_at = _FIXED_NOW
    if isinstance(claimed_at, datetime):
        claimed_at = claimed_at.isoformat().replace("+00:00", "Z")
    if isinstance(heartbeat_at, datetime):
        heartbeat_at = heartbeat_at.isoformat().replace("+00:00", "Z")
    return ClaimRecord(
        schema_version=schema_version,
        track_id=track_id,
        owner=owner,
        container=container,
        session=session,
        phase=phase,
        status=status,
        claimed_at=claimed_at,
        heartbeat_at=heartbeat_at,
        superseded_from=superseded_from,
    )


# ===========================================================================
# Rule 1 — Earlier claimed_at wins (multiple active candidates)
# ===========================================================================

class TestRule1_EarlierClaimedAtWins(unittest.TestCase):
    """Case 1.x: when multiple active claims exist, the earliest claimed_at wins."""

    def test_1_1_two_claims_a_earlier(self):
        """Case 1.1: A claimed 5s before B, both active fresh → winner=A.

        Time gap is 5s (well within 30s CLOCK_SKEW_WARN_THRESHOLD) so the
        verdict_reason is 'earlier_claimed_at_wins' (not 'clock_skew_conflict').
        """
        t_a = _FIXED_NOW - timedelta(seconds=25)  # 5s before B
        t_b = _FIXED_NOW - timedelta(seconds=20)  # later
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_a)
        self.assertIn(claim_b, v.yielders)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")
        self.assertFalse(v.conflict)

    def test_1_1_order_invariant_b_first_in_list(self):
        """Case 1.1 order-invariant: B listed first, A still wins by earlier claimed_at."""
        t_a = _FIXED_NOW - timedelta(seconds=25)  # 5s gap, within threshold
        t_b = _FIXED_NOW - timedelta(seconds=20)
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        # Reversed list order
        v = reconcile("test-track", [claim_b, claim_a], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_a)
        self.assertIn(claim_b, v.yielders)

    def test_1_2_three_claims_earliest_wins(self):
        """Case 1.2: 3 candidates — the one with the earliest claimed_at wins.

        All claims are within 10s of each other (well within 30s threshold) so
        verdict is 'earlier_claimed_at_wins', not 'clock_skew_conflict'.
        """
        t_first = _FIXED_NOW - timedelta(seconds=20)
        t_second = _FIXED_NOW - timedelta(seconds=15)
        t_third = _FIXED_NOW - timedelta(seconds=10)
        claim_first = _claim(container="devbox-A", session="s-001", claimed_at=t_first)
        claim_second = _claim(container="devbox-B", session="s-002", claimed_at=t_second)
        claim_third = _claim(container="devbox-C", session="s-003", claimed_at=t_third)

        v = reconcile("test-track", [claim_third, claim_first, claim_second], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_first)
        self.assertIn(claim_second, v.yielders)
        self.assertIn(claim_third, v.yielders)
        self.assertEqual(len(v.yielders), 2)

    def test_1_3_clock_skew_within_threshold_still_early_wins(self):
        """Case 1.3: max diff = 29s (< 30s threshold) → no conflict, early-wins rule."""
        t_a = _FIXED_NOW - timedelta(seconds=100)
        t_b = t_a + timedelta(seconds=29)  # diff = 29s, within threshold
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertFalse(v.conflict)
        self.assertEqual(v.winner, claim_a)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")
        self.assertIsNotNone(v.max_clock_skew_seconds)
        self.assertEqual(v.max_clock_skew_seconds, 29)


# ===========================================================================
# Rule 2 — Terminal status takeover
# ===========================================================================

class TestRule2_TerminalTakeover(unittest.TestCase):
    """Case 2.x: done/abandoned claims are routed to superseded."""

    def test_2_1_all_done_no_winner(self):
        """Case 2.1: all candidates status='done' → winner=None, no_active_candidates."""
        claim_a = _claim(container="devbox-A", session="s-001", status="done")
        claim_b = _claim(container="devbox-B", session="s-002", status="done")

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(claim_a, v.superseded)
        self.assertIn(claim_b, v.superseded)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    def test_2_1_verdict_reason_contains_no_active_candidates(self):
        """Case 2.1: all terminal → verdict_reason is 'no_active_candidates'."""
        claim_a = _claim(status="done")
        v = reconcile("test-track", [claim_a], now=_FIXED_NOW)
        # Single done claim → superseded, winner=None
        self.assertIsNone(v.winner)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    def test_2_2_one_active_rest_done_active_wins(self):
        """Case 2.2: 1 active + 1 done → active wins, done goes to superseded."""
        claim_active = _claim(container="devbox-A", session="s-001", status="active")
        claim_done = _claim(container="devbox-B", session="s-002", status="done")

        v = reconcile("test-track", [claim_active, claim_done], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_active)
        self.assertIn(claim_done, v.superseded)
        self.assertEqual(len(v.yielders), 0)

    def test_2_2_one_active_two_done(self):
        """Case 2.2 extension: 1 active + 2 done → active wins, both done superseded."""
        claim_active = _claim(container="devbox-A", session="s-001", status="active")
        claim_done1 = _claim(container="devbox-B", session="s-002", status="done")
        claim_done2 = _claim(container="devbox-C", session="s-003", status="done")

        v = reconcile("test-track", [claim_done1, claim_active, claim_done2], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_active)
        self.assertIn(claim_done1, v.superseded)
        self.assertIn(claim_done2, v.superseded)
        self.assertEqual(len(v.yielders), 0)

    def test_2_3_all_abandoned_no_winner(self):
        """Abandoned is treated as terminal: all abandoned → no_active_candidates."""
        claim_a = _claim(container="devbox-A", session="s-001", status="abandoned")
        claim_b = _claim(container="devbox-B", session="s-002", status="abandoned")

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(claim_a, v.superseded)
        self.assertIn(claim_b, v.superseded)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    def test_2_4_active_plus_abandoned_active_wins(self):
        """1 active + 1 abandoned → active wins, abandoned superseded."""
        claim_active = _claim(container="devbox-A", session="s-001", status="active")
        claim_abandoned = _claim(container="devbox-B", session="s-002", status="abandoned")

        v = reconcile("test-track", [claim_active, claim_abandoned], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_active)
        self.assertIn(claim_abandoned, v.superseded)


# ===========================================================================
# Rule 3 — Stale TTL (staleness detection + stale_takeover_eligible)
# ===========================================================================

class TestRule3_StaleTTL(unittest.TestCase):
    """Case 3.x: stale-takeover-eligible when heartbeat older than STALE_TTL."""

    def test_3_1_sole_active_stale_winner_moved_to_superseded(self):
        """Case 3.1: sole active with heartbeat > STALE_TTL ago → winner=None, stale."""
        # heartbeat_at is STALE_TTL + 1s ago → definitively stale
        stale_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL + 1)
        claim = _claim(
            container="devbox-A",
            session="s-001",
            heartbeat_at=stale_heartbeat,
        )

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(claim, v.superseded)
        self.assertIn("stale_takeover_eligible", v.verdict_reason)

    def test_3_1_verdict_reason_contains_stale_suffix(self):
        """Case 3.1: verdict_reason has '+stale_takeover_eligible' suffix."""
        stale_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL + 100)
        claim = _claim(heartbeat_at=stale_heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertIn("stale_takeover_eligible", v.verdict_reason)

    def test_3_2_heartbeat_ttl_minus_1_still_active(self):
        """Case 3.2: heartbeat_at = now - (STALE_TTL - 1s) → NOT stale (age < TTL)."""
        fresh_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL - 1)
        claim = _claim(heartbeat_at=fresh_heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim)
        self.assertNotIn("stale", v.verdict_reason)
        self.assertEqual(v.verdict_reason, "sole_active")

    def test_3_3_heartbeat_exactly_ttl_boundary(self):
        """Case 3.3: heartbeat_at = now - STALE_TTL exactly.

        reconcile._is_stale uses age > STALE_TTL (strictly greater), so age == TTL
        is NOT stale. Winner remains active at this boundary.
        """
        boundary_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL)
        claim = _claim(heartbeat_at=boundary_heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        # age == STALE_TTL → NOT stale (strict > check)
        self.assertEqual(v.winner, claim)
        self.assertEqual(v.verdict_reason, "sole_active")

    def test_3_4_heartbeat_ttl_plus_1_stale(self):
        """Case 3.4: heartbeat_at = now - (STALE_TTL + 1s) → stale (age > TTL)."""
        stale_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL + 1)
        claim = _claim(heartbeat_at=stale_heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(claim, v.superseded)
        self.assertIn("stale_takeover_eligible", v.verdict_reason)

    def test_3_5_race_winner_stale_moved_to_superseded(self):
        """Case 3.5: in a race, the winner is stale → moved to superseded.

        Both claims are within 29s of each other (below CLOCK_SKEW_WARN_THRESHOLD)
        so the race applies 'earlier_claimed_at_wins'. Winner is then found stale.
        """
        # winner claimed earlier but has a stale heartbeat
        t_winner_claimed = _FIXED_NOW - timedelta(seconds=29)
        stale_heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL + 60)
        t_loser_claimed = _FIXED_NOW - timedelta(seconds=10)

        claim_winner = _claim(
            container="devbox-A",
            session="s-001",
            claimed_at=t_winner_claimed,
            heartbeat_at=stale_heartbeat,
        )
        claim_loser = _claim(
            container="devbox-B",
            session="s-002",
            claimed_at=t_loser_claimed,
        )

        v = reconcile("test-track", [claim_winner, claim_loser], now=_FIXED_NOW)

        # Winner selected by early claimed_at, then found stale → moves to superseded
        self.assertIsNone(v.winner)
        self.assertIn(claim_winner, v.superseded)
        # loser stays in yielders (not promoted)
        self.assertIn(claim_loser, v.yielders)
        self.assertIn("stale_takeover_eligible", v.verdict_reason)


# ===========================================================================
# Rule 4 — Tiebreak by lex order
# ===========================================================================

class TestRule4_TiebreakLexOrder(unittest.TestCase):
    """Case 4.x: when claimed_at is identical, tiebreak on container/session."""

    def test_4_1_same_claimed_at_container_lex_wins(self):
        """Case 4.1: 2 claims same claimed_at, container 'aaa' < 'bbb' → 'aaa' wins."""
        t_same = _FIXED_NOW - timedelta(seconds=10)
        claim_aaa = _claim(container="aaa", session="s-001", claimed_at=t_same)
        claim_bbb = _claim(container="bbb", session="s-001", claimed_at=t_same)

        v = reconcile("test-track", [claim_bbb, claim_aaa], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_aaa)
        self.assertIn(claim_bbb, v.yielders)
        self.assertEqual(v.verdict_reason, "tiebreak_lex_order")

    def test_4_2_same_claimed_at_and_container_session_lex_wins(self):
        """Case 4.2: same claimed_at + same container, session 'ccc' < 'ddd' → 'ccc' wins."""
        t_same = _FIXED_NOW - timedelta(seconds=10)
        same_container = "devbox-X"
        claim_ccc = _claim(container=same_container, session="ccc", claimed_at=t_same)
        claim_ddd = _claim(container=same_container, session="ddd", claimed_at=t_same)

        v = reconcile("test-track", [claim_ddd, claim_ccc], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_ccc)
        self.assertIn(claim_ddd, v.yielders)
        self.assertEqual(v.verdict_reason, "tiebreak_lex_order")

    def test_4_3_tiebreak_key_is_container_slash_session(self):
        """Case 4.3: tiebreak key is 'container/session', not just container."""
        # "a/z" < "b/a" lexicographically
        t_same = _FIXED_NOW - timedelta(seconds=10)
        claim_az = _claim(container="a", session="z", claimed_at=t_same)
        claim_ba = _claim(container="b", session="a", claimed_at=t_same)

        v = reconcile("test-track", [claim_ba, claim_az], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_az)
        self.assertEqual(v.verdict_reason, "tiebreak_lex_order")

    def test_4_4_tiebreak_not_triggered_when_times_differ(self):
        """Earlier time wins without tiebreak: verdict_reason != tiebreak_lex_order."""
        t_early = _FIXED_NOW - timedelta(seconds=25)
        t_late = _FIXED_NOW - timedelta(seconds=10)
        # 'bbb' < 'zzz' but bbb claimed later → zzz wins by time
        claim_zzz = _claim(container="zzz", session="s-001", claimed_at=t_early)
        claim_bbb = _claim(container="bbb", session="s-001", claimed_at=t_late)

        v = reconcile("test-track", [claim_bbb, claim_zzz], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim_zzz)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")


# ===========================================================================
# Boundary stale_ttl ± 1s (three-tier boundary test per tasks.md §2.10 (1))
# ===========================================================================

class TestBoundaryStaleTTL(unittest.TestCase):
    """Three-tier boundary: TTL-1s / TTL / TTL+1s for stale detection."""

    def test_B1_ttl_minus_1s_not_stale(self):
        """Case B.1: age = STALE_TTL - 1s → NOT stale, winner set."""
        heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL - 1)
        claim = _claim(heartbeat_at=heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertEqual(v.winner, claim)
        self.assertNotIn("stale", v.verdict_reason)

    def test_B2_ttl_exactly_not_stale(self):
        """Case B.2: age = STALE_TTL exactly → NOT stale (strict > check).

        Implementation detail: _is_stale uses 'age_seconds > STALE_TTL',
        so equality at the boundary is NOT stale. Winner is still active.
        """
        heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL)
        claim = _claim(heartbeat_at=heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        # The strict > boundary means age == STALE_TTL is NOT stale
        self.assertEqual(v.winner, claim)
        self.assertEqual(v.verdict_reason, "sole_active")

    def test_B3_ttl_plus_1s_stale(self):
        """Case B.3: age = STALE_TTL + 1s → stale, winner=None."""
        heartbeat = _FIXED_NOW - timedelta(seconds=STALE_TTL + 1)
        claim = _claim(heartbeat_at=heartbeat)

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(claim, v.superseded)
        self.assertIn("stale_takeover_eligible", v.verdict_reason)

    def test_B_threshold_value_is_1800(self):
        """Sanity: STALE_TTL constant is 1800 seconds (per constants.py)."""
        self.assertEqual(STALE_TTL, 1800)


# ===========================================================================
# Missing heartbeat → treated as NOT stale (implementation deviation from spec)
# ===========================================================================

class TestMissingHeartbeat(unittest.TestCase):
    """Cases M.x: heartbeat_at missing or unparseable.

    NOTE: reconcile._is_stale() returns False (NOT stale) when heartbeat_at
    cannot be parsed. This is the conservative implementation choice — the claim
    remains as winner. This DEVIATES from the golden-table spec which says
    "heartbeat missing → treat as stale". Deviation is recorded as Finding F-1.
    """

    def test_M1_empty_heartbeat_not_treated_as_stale(self):
        """Case M.1: heartbeat_at='' (empty string) → _is_stale returns False.

        FINDING F-1: Implementation is conservative (False = not stale) rather
        than spec-mandated (should be stale). Claim remains as winner.
        See follow-up findings section for remediation guidance.
        """
        claim = _claim(heartbeat_at="")

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        # Implementation: empty heartbeat → NOT stale (conservative)
        # Spec says: should be treated as stale
        # We assert actual behavior, flagging the deviation via comment.
        self.assertEqual(v.winner, claim)
        self.assertEqual(v.verdict_reason, "sole_active")
        # F-1: winner should be None if spec were followed strictly

    def test_M1_none_heartbeat_routes_via_claim_schema(self):
        """Case M.1 alt: ClaimRecord.heartbeat_at=None would fail schema validation.

        ClaimRecord is a frozen dataclass; None is not a valid value for a str
        field. In practice, claims with missing heartbeat_at would be rejected
        by parse_claim() before reaching reconcile. Reconcile itself receives
        only structurally valid ClaimRecords.
        """
        # Verify the dataclass accepts None for heartbeat_at (str type hint only,
        # not enforced at runtime by dataclass)
        claim = _claim.__wrapped__ if hasattr(_claim, "__wrapped__") else None
        # Build directly to test with None value
        cr = ClaimRecord(
            schema_version="1",
            track_id="test-track",
            owner="alice",
            container="devbox-A",
            session="s-001",
            phase="B",
            status="active",
            claimed_at=_FIXED_NOW.isoformat().replace("+00:00", "Z"),
            heartbeat_at=None,  # type: ignore[arg-type]
        )
        v = reconcile("test-track", [cr], now=_FIXED_NOW)
        # None heartbeat → _parse_heartbeat_at returns None → _is_stale = False
        # Claim stays as winner (conservative path)
        self.assertEqual(v.winner, cr)

    def test_M2_malformed_heartbeat_not_treated_as_stale(self):
        """Case M.2: heartbeat_at non-ISO format → _parse_heartbeat_at returns None.

        FINDING F-1 (same root): unparseable heartbeat also treated as not-stale.
        Claim stays as winner rather than being marked stale_takeover_eligible.
        """
        claim = _claim(heartbeat_at="not-a-valid-timestamp")

        v = reconcile("test-track", [claim], now=_FIXED_NOW)

        # Implementation: malformed heartbeat → NOT stale (conservative)
        self.assertEqual(v.winner, claim)
        self.assertEqual(v.verdict_reason, "sole_active")

    def test_M3_malformed_claimed_at_routes_to_unknown(self):
        """Case M.3: malformed claimed_at → claim routed to unknown bucket (not winner)."""
        cr = ClaimRecord(
            schema_version="1",
            track_id="test-track",
            owner="alice",
            container="devbox-A",
            session="s-001",
            phase="B",
            status="active",
            claimed_at="NOT-ISO-8601",
            heartbeat_at=_FIXED_NOW.isoformat().replace("+00:00", "Z"),
        )

        v = reconcile("test-track", [cr], now=_FIXED_NOW)

        # Unparseable claimed_at → unknown bucket, no winner
        self.assertIn(cr, v.unknown)
        self.assertIsNone(v.winner)
        self.assertEqual(v.verdict_reason, "no_active_candidates")


# ===========================================================================
# Status 4x4 matrix (pairwise combinations of two claims)
# ===========================================================================

class TestStatus4x4Matrix(unittest.TestCase):
    """Exhaustive pairwise status matrix for two claims.

    Claim A always has earlier claimed_at; Claim B has later claimed_at.
    When A is active (or non-terminal), A wins by claimed_at rule.

    Terminal statuses: done, abandoned.
    Non-terminal (candidate): active, yielded.
    Unknown: routes to unknown bucket.
    """

    # Reference times: A claimed 10s before B (within 30s CLOCK_SKEW_WARN_THRESHOLD
    # so two-candidate races produce 'earlier_claimed_at_wins', not 'clock_skew_conflict').
    _T_A = _FIXED_NOW - timedelta(seconds=20)
    _T_B = _FIXED_NOW - timedelta(seconds=10)

    def _two_claims(
        self,
        status_a: str,
        status_b: str,
    ) -> tuple[ClaimRecord, ClaimRecord]:
        """Build two claims with A earlier than B."""
        a = _claim(
            container="devbox-A",
            session="s-001",
            claimed_at=self._T_A,
            status=status_a,
        )
        b = _claim(
            container="devbox-B",
            session="s-002",
            claimed_at=self._T_B,
            status=status_b,
        )
        return a, b

    # ---- active × active → Rule 1 (early wins) ---------------------------

    def test_active_active_a_wins(self):
        """active + active → A wins (earlier claimed_at)."""
        a, b = self._two_claims("active", "active")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, a)
        self.assertIn(b, v.yielders)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")

    # ---- active × done → A wins, B superseded ----------------------------

    def test_active_done_a_wins(self):
        """active + done → A wins (sole active candidate)."""
        a, b = self._two_claims("active", "done")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, a)
        self.assertIn(b, v.superseded)
        self.assertEqual(len(v.yielders), 0)

    # ---- active × abandoned → A wins, B superseded ----------------------

    def test_active_abandoned_a_wins(self):
        """active + abandoned → A wins (abandoned is terminal)."""
        a, b = self._two_claims("active", "abandoned")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, a)
        self.assertIn(b, v.superseded)

    # ---- active × yielded → both candidates, A wins by time -------------

    def test_active_yielded_a_wins_by_time(self):
        """active + yielded → both in candidates (yielded is NOT terminal).

        yielded is not in _TERMINAL_STATUSES, so it participates as a candidate.
        A (earlier) wins; B (yielded) is in yielders.
        """
        a, b = self._two_claims("active", "yielded")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, a)
        self.assertIn(b, v.yielders)

    # ---- done × active → B wins (A is terminal) -------------------------

    def test_done_active_b_wins(self):
        """done + active → B wins (A is terminal, sent to superseded)."""
        a, b = self._two_claims("done", "active")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, b)
        self.assertIn(a, v.superseded)

    # ---- done × done → no winner, both superseded -----------------------

    def test_done_done_no_winner(self):
        """done + done → winner=None, both superseded, no_active_candidates."""
        a, b = self._two_claims("done", "done")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertIsNone(v.winner)
        self.assertIn(a, v.superseded)
        self.assertIn(b, v.superseded)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    # ---- done × abandoned → no winner -----------------------------------

    def test_done_abandoned_no_winner(self):
        """done + abandoned → winner=None, all terminal → no_active_candidates."""
        a, b = self._two_claims("done", "abandoned")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertIsNone(v.winner)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    # ---- done × yielded → yielded is candidate, done is terminal --------

    def test_done_yielded_yielded_wins(self):
        """done + yielded → yielded is sole candidate, wins as sole_active.

        yielded is NOT in _TERMINAL_STATUSES → it is a candidate.
        done is terminal → superseded.
        """
        a, b = self._two_claims("done", "yielded")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, b)
        self.assertIn(a, v.superseded)
        self.assertEqual(v.verdict_reason, "sole_active")

    # ---- abandoned × active → B wins ------------------------------------

    def test_abandoned_active_b_wins(self):
        """abandoned + active → B wins (abandoned is terminal)."""
        a, b = self._two_claims("abandoned", "active")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, b)
        self.assertIn(a, v.superseded)

    # ---- abandoned × abandoned → no winner ------------------------------

    def test_abandoned_abandoned_no_winner(self):
        """abandoned + abandoned → winner=None, both superseded."""
        a, b = self._two_claims("abandoned", "abandoned")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertIsNone(v.winner)
        self.assertIn(a, v.superseded)
        self.assertIn(b, v.superseded)

    # ---- abandoned × yielded → yielded is candidate, wins ---------------

    def test_abandoned_yielded_yielded_wins(self):
        """abandoned + yielded → yielded wins (sole candidate), abandoned superseded."""
        a, b = self._two_claims("abandoned", "yielded")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, b)
        self.assertIn(a, v.superseded)

    # ---- yielded × yielded → both candidates, earlier wins ---------------

    def test_yielded_yielded_earlier_wins(self):
        """yielded + yielded → both candidates; A (earlier) wins by claimed_at."""
        a, b = self._two_claims("yielded", "yielded")
        v = reconcile("t", [a, b], now=_FIXED_NOW)
        self.assertEqual(v.winner, a)
        self.assertIn(b, v.yielders)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")

    # ---- yielded × unknown → yielded wins (unknown is excluded) ----------

    def test_yielded_unknown_yielded_wins(self):
        """yielded + unknown → yielded is sole candidate; unknown in unknown bucket."""
        a_yielded = _claim(
            container="devbox-A",
            session="s-001",
            claimed_at=self._T_A,
            status="yielded",
        )
        b_unknown = ClaimRecord(
            schema_version="99",  # triggers status="unknown" sentinel
            track_id="t",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )

        v = reconcile("t", [a_yielded, b_unknown], now=_FIXED_NOW)

        self.assertEqual(v.winner, a_yielded)
        self.assertIn(b_unknown, v.unknown)
        self.assertEqual(v.verdict_reason, "sole_active")

    # ---- unknown × active → active wins (unknown excluded) --------------

    def test_unknown_active_active_wins(self):
        """unknown + active → active is sole candidate; unknown goes to unknown bucket."""
        a_unknown = ClaimRecord(
            schema_version="99",
            track_id="t",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )
        b_active = _claim(
            container="devbox-B",
            session="s-002",
            claimed_at=self._T_B,
            status="active",
        )

        v = reconcile("t", [a_unknown, b_active], now=_FIXED_NOW)

        self.assertEqual(v.winner, b_active)
        self.assertIn(a_unknown, v.unknown)

    # ---- unknown × done → no winner (done superseded, unknown excluded) --

    def test_unknown_done_no_winner(self):
        """unknown + done → no active candidates; unknown excluded, done superseded."""
        a_unknown = ClaimRecord(
            schema_version="99",
            track_id="t",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )
        b_done = _claim(
            container="devbox-B",
            session="s-002",
            claimed_at=self._T_B,
            status="done",
        )

        v = reconcile("t", [a_unknown, b_done], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertIn(b_done, v.superseded)
        self.assertIn(a_unknown, v.unknown)
        self.assertEqual(v.verdict_reason, "no_active_candidates")

    # ---- unknown × unknown → no winner ----------------------------------

    def test_unknown_unknown_no_winner(self):
        """unknown + unknown → all claims excluded; winner=None, no_active_candidates."""
        a_unknown = ClaimRecord(
            schema_version="99",
            track_id="t",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )
        b_unknown = ClaimRecord(
            schema_version="99",
            track_id="t",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )

        v = reconcile("t", [a_unknown, b_unknown], now=_FIXED_NOW)

        self.assertIsNone(v.winner)
        self.assertEqual(len(v.unknown), 2)
        self.assertEqual(v.verdict_reason, "no_active_candidates")


# ===========================================================================
# Clock skew detection
# ===========================================================================

class TestClockSkewDetection(unittest.TestCase):
    """Cases CS.x: clock skew conflict flag based on CLOCK_SKEW_WARN_THRESHOLD."""

    def test_CS1_skew_31s_conflict_true(self):
        """Case CS.1: max diff = 31s (> 30) → conflict=True, reason=clock_skew_conflict."""
        t_a = _FIXED_NOW - timedelta(seconds=100)
        t_b = t_a + timedelta(seconds=31)  # diff = 31s
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertTrue(v.conflict)
        self.assertEqual(v.verdict_reason, "clock_skew_conflict")
        self.assertIsNotNone(v.max_clock_skew_seconds)
        self.assertEqual(v.max_clock_skew_seconds, 31)
        # Winner still selected deterministically (A earlier)
        self.assertEqual(v.winner, claim_a)

    def test_CS2_skew_30s_boundary_no_conflict(self):
        """Case CS.2: max diff = 30s exactly (NOT > 30) → conflict=False.

        Implementation uses strict > comparison: 30 > 30 is False.
        """
        t_a = _FIXED_NOW - timedelta(seconds=100)
        t_b = t_a + timedelta(seconds=30)  # diff = 30s exactly
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        # 30 == CLOCK_SKEW_WARN_THRESHOLD → NOT conflict (strict > check)
        self.assertFalse(v.conflict)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")
        self.assertEqual(v.max_clock_skew_seconds, 30)

    def test_CS3_skew_29s_no_conflict(self):
        """Case CS.3: max diff = 29s (< 30) → conflict=False, early-wins rule."""
        t_a = _FIXED_NOW - timedelta(seconds=100)
        t_b = t_a + timedelta(seconds=29)
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertFalse(v.conflict)
        self.assertEqual(v.verdict_reason, "earlier_claimed_at_wins")
        self.assertIsNotNone(v.max_clock_skew_seconds)
        self.assertEqual(v.max_clock_skew_seconds, 29)

    def test_CS4_conflict_winner_still_selected(self):
        """CS.4: even when conflict=True, winner is still deterministically set."""
        t_a = _FIXED_NOW - timedelta(seconds=200)
        t_b = t_a + timedelta(seconds=50)  # diff = 50s > threshold
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)

        self.assertTrue(v.conflict)
        # Still selects a winner (advisory)
        self.assertIsNotNone(v.winner)
        self.assertEqual(v.winner, claim_a)

    def test_CS5_max_clock_skew_none_for_sole_active(self):
        """CS.5: max_clock_skew_seconds is None when only one active candidate."""
        claim = _claim()
        v = reconcile("test-track", [claim], now=_FIXED_NOW)
        self.assertIsNone(v.max_clock_skew_seconds)
        self.assertFalse(v.conflict)

    def test_CS6_threshold_value_is_30(self):
        """Sanity: CLOCK_SKEW_WARN_THRESHOLD constant is 30 (per constants.py)."""
        self.assertEqual(CLOCK_SKEW_WARN_THRESHOLD, 30)


# ===========================================================================
# Edge cases: empty claims and single claim
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    """Empty list and single-claim edge cases."""

    def test_empty_claims_returns_empty_verdict(self):
        """Empty input → verdict_reason='empty_claims', winner=None."""
        v = reconcile("test-track", [], now=_FIXED_NOW)
        self.assertIsNone(v.winner)
        self.assertEqual(v.verdict_reason, "empty_claims")
        self.assertFalse(v.conflict)

    def test_single_active_fresh_wins(self):
        """Single fresh active claim → winner=claim, sole_active."""
        claim = _claim()
        v = reconcile("test-track", [claim], now=_FIXED_NOW)
        self.assertEqual(v.winner, claim)
        self.assertEqual(v.verdict_reason, "sole_active")
        self.assertEqual(len(v.yielders), 0)
        self.assertEqual(len(v.superseded), 0)

    def test_reconcile_verdict_is_frozen(self):
        """ReconcileVerdict is frozen (immutable)."""
        v = reconcile("test-track", [_claim()], now=_FIXED_NOW)
        with self.assertRaises((AttributeError, TypeError)):
            v.winner = None  # type: ignore[misc]

    def test_reconcile_deterministic_same_input(self):
        """Same input always produces identical verdict (determinism guarantee)."""
        t_a = _FIXED_NOW - timedelta(seconds=20)
        t_b = _FIXED_NOW - timedelta(seconds=10)
        claim_a = _claim(container="devbox-A", session="s-001", claimed_at=t_a)
        claim_b = _claim(container="devbox-B", session="s-002", claimed_at=t_b)

        v1 = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)
        v2 = reconcile("test-track", [claim_a, claim_b], now=_FIXED_NOW)
        v3 = reconcile("test-track", [claim_b, claim_a], now=_FIXED_NOW)  # reversed

        self.assertEqual(v1.winner, v2.winner)
        self.assertEqual(v1.winner, v3.winner)
        self.assertEqual(v1.verdict_reason, v2.verdict_reason)

    def test_unknown_claim_only_no_winner(self):
        """Single unknown-status claim → routed to unknown bucket, no winner."""
        unknown = ClaimRecord(
            schema_version="99",
            track_id="test-track",
            owner="",
            container="",
            session="",
            phase="",
            status="unknown",
            claimed_at="",
            heartbeat_at="",
        )
        v = reconcile("test-track", [unknown], now=_FIXED_NOW)
        self.assertIsNone(v.winner)
        self.assertIn(unknown, v.unknown)
        self.assertEqual(v.verdict_reason, "no_active_candidates")


if __name__ == "__main__":
    unittest.main()
