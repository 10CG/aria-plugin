"""Phase 1 (main spec stale-refs-false-parity) — F1′/F4′ predicate RED tests.

RED-first (tasks §2, 2.15 self-falsification gate): these assert the CORRECT
post-implementation behavior of the F1′ dual-role predicates and the F4′
overall_parity decision table. They target functions that increment 4 will add to
collectors/multi_remote.py; until then every test here is RED (AttributeError —
the function does not exist yet). Increment 4 turns them GREEN.

Predicate contracts fixed here (so implementation + test agree):
  _evidence_eligible(fetched_at: datetime|None, now: datetime, window_s: int) -> bool
  _exemption_eligible(fetched_at, now, generation_fetched, scan_generation,
                      k_eff, hard_cap_s, consecutive_unverified) -> bool
  _evidence_grade(evidence_eligible: bool, exemption_eligible: bool) -> str
  _benign_unknown(parity, reason, evidence_eligible: bool) -> bool
  _blocking_unknown(parity, reason, evidence_eligible: bool) -> bool
  _has_unreachable_remote(fetch_ok: str) -> bool
  _overall_parity(enforced_entries: list[dict], gitlink_integrity: list[dict], k_eff: int) -> bool
    (k_eff added Phase 2A/F10″ for _gitlink_blocking's D18 threshold; these
    tests pass gitlink_integrity=[] throughout so k_eff's value is a no-op
    here — a literal placeholder int is passed to satisfy the signature.)

fetched_at / now are tz-aware UTC datetimes (produced by _common.scan_now()).
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collectors import multi_remote as mr  # type: ignore  # noqa: E402

NOW = datetime(2026, 7, 17, 15, 0, 0, tzinfo=timezone.utc)
WIN = 3600           # evidence_window_seconds (1h)
HARD = 7 * 86400     # hard_cap_seconds (7d)


class TestEvidenceEligible(unittest.TestCase):
    """证据资格(r) — D15′ ∃ side, world-time fresh; None / negative age → False."""

    def test_fresh_within_window(self):
        self.assertTrue(mr._evidence_eligible(NOW - timedelta(minutes=50), NOW, WIN))

    def test_stale_beyond_window(self):
        self.assertFalse(mr._evidence_eligible(NOW - timedelta(hours=2), NOW, WIN))

    def test_none_fetched_at_false(self):
        self.assertFalse(mr._evidence_eligible(None, NOW, WIN))

    def test_negative_wall_clock_age_fail_closed(self):
        # R9-M3: clock rollback / NTP jump → fetched_at in the future → treat as null
        self.assertFalse(mr._evidence_eligible(NOW + timedelta(minutes=5), NOW, WIN))

    def test_exact_window_boundary_inclusive(self):
        self.assertTrue(mr._evidence_eligible(NOW - timedelta(seconds=WIN), NOW, WIN))


class TestExemptionEligible(unittest.TestCase):
    """豁免资格(r) — D15′+D18 downgrade side. Any missing/out-of-range input → False."""

    def _call(self, **kw):
        base = dict(
            fetched_at=NOW - timedelta(days=1),
            now=NOW,
            generation_fetched=5,
            scan_generation=6,   # generation_age = 1
            k_eff=4,
            hard_cap_s=HARD,
            consecutive_unverified=0,
        )
        base.update(kw)
        return mr._exemption_eligible(
            base["fetched_at"], base["now"], base["generation_fetched"],
            base["scan_generation"], base["k_eff"], base["hard_cap_s"],
            base["consecutive_unverified"],
        )

    def test_within_all_bounds_true(self):
        self.assertTrue(self._call())

    def test_none_fetched_at_false(self):
        self.assertFalse(self._call(fetched_at=None))

    def test_beyond_hard_cap_false(self):
        self.assertFalse(self._call(fetched_at=NOW - timedelta(days=8)))

    def test_generation_age_beyond_k_eff_false(self):
        self.assertFalse(self._call(generation_fetched=1, scan_generation=6))  # age=5 > k_eff 4

    def test_negative_generation_age_clamp_false(self):
        # RM-6b: lost-update rollback → generation_age < 0 → treat as null
        self.assertFalse(self._call(generation_fetched=8, scan_generation=6))

    def test_consecutive_unverified_at_k_eff_false(self):
        # D18: consecutive_unverified >= k_eff ⇒ exemption expires
        self.assertFalse(self._call(consecutive_unverified=4))

    def test_generation_fetched_none_false(self):
        self.assertFalse(self._call(generation_fetched=None))


class TestEvidenceGradePartition(unittest.TestCase):
    """D20 three-tier FULL PARTITION — the R8 11th-recurrence overlap cell.

    Guards must be mutually exclusive AND cover the whole (E,X) domain. The
    structural guarantee is a single if/elif/else: exactly one branch per call.
    """

    def test_truth_table_all_four_cells(self):
        self.assertEqual(mr._evidence_grade(True, True), "fresh")
        self.assertEqual(mr._evidence_grade(True, False), "fresh")   # E∧¬X — E wins
        self.assertEqual(mr._evidence_grade(False, True), "stale_unverified")
        self.assertEqual(mr._evidence_grade(False, False), "expired")

    def test_total_function_always_one_of_three(self):
        grades = {mr._evidence_grade(E, X) for E in (True, False) for X in (True, False)}
        self.assertTrue(grades <= {"fresh", "stale_unverified", "expired"})
        # all three tiers are reachable (no tier is dead)
        self.assertEqual(grades, {"fresh", "stale_unverified", "expired"})


class TestHasUnreachableRemote(unittest.TestCase):
    """P2: reads fetch_ok three-state ONLY; not_attempted ≠ unreachable (zero enum)."""

    def test_false_is_unreachable(self):
        self.assertTrue(mr._has_unreachable_remote("false"))

    def test_not_attempted_not_unreachable(self):
        # deadline-cut / backoff leg: "we didn't ask" ≠ "we can't reach"
        self.assertFalse(mr._has_unreachable_remote("not_attempted"))

    def test_true_not_unreachable(self):
        self.assertFalse(mr._has_unreachable_remote("true"))


class TestBlockingUnknownComplement(unittest.TestCase):
    """P2 core self-falsification: _blocking_unknown MUST be the strict complement
    of _benign_unknown, never a positive enumeration. The fail-open escapees below
    are exactly what a `reason in {whitelist}` implementation would MISS."""

    def test_benign_unconditional_reasons(self):
        for reason in ("detached_head", "shallow_clone", "remote_branch_missing"):
            self.assertTrue(mr._benign_unknown("unknown", reason, False), reason)
            self.assertFalse(mr._blocking_unknown("unknown", reason, False), reason)

    def test_no_local_tracking_ref_gated_by_evidence(self):
        # fresh evidence → benign; not-fresh → blocking (assertion "really unpublished"
        # needs world-time-fresh evidence)
        self.assertTrue(mr._benign_unknown("unknown", "no_local_tracking_ref", True))
        self.assertFalse(mr._blocking_unknown("unknown", "no_local_tracking_ref", True))
        self.assertFalse(mr._benign_unknown("unknown", "no_local_tracking_ref", False))
        self.assertTrue(mr._blocking_unknown("unknown", "no_local_tracking_ref", False))

    def test_fail_open_escapees_all_blocked(self):
        # the complement MUST block every non-whitelisted reason, incl. code paths
        # that leave reason=None and Spec B classifier catch-all values
        for reason in (
            None, "parse_error", "rev_list_failed", "rev_list_parse_failed",
            "other", "git_error", "permission_denied", "timeout", "network",
        ):
            self.assertFalse(mr._benign_unknown("unknown", reason, False), reason)
            self.assertTrue(mr._blocking_unknown("unknown", reason, False), reason)

    def test_non_unknown_parity_is_not_blocking_unknown(self):
        self.assertFalse(mr._blocking_unknown("equal", None, True))
        self.assertFalse(mr._blocking_unknown("behind", None, True))


class TestOverallParityFreshEvidence(unittest.TestCase):
    """F4′ v8: ∃ side requires parity==equal AND evidence_grade==fresh. A
    stale_unverified equal keeps parity==equal (never rewritten) so a naive
    parity==equal-only ∃ check would resurrect the founding 14h-stale-equal
    accident. gitlink_integrity=[] is the Phase 1 placeholder (vacuous-true ∀)."""

    def test_stale_unverified_equal_is_not_positive_evidence(self):
        entries = [{"parity": "equal", "evidence_grade": "stale_unverified", "reason": None}]
        self.assertFalse(mr._overall_parity(entries, [], 3))

    def test_fresh_equal_is_positive_evidence(self):
        entries = [{"parity": "equal", "evidence_grade": "fresh", "reason": None}]
        self.assertTrue(mr._overall_parity(entries, [], 3))

    def test_empty_enforced_set_is_false_not_vacuous_true(self):
        self.assertFalse(mr._overall_parity([], [], 3))

    def test_behind_leg_blocks_even_with_fresh_equal_elsewhere(self):
        entries = [
            {"parity": "equal", "evidence_grade": "fresh", "reason": None},
            {"parity": "behind", "evidence_grade": "fresh", "reason": None},
        ]
        self.assertFalse(mr._overall_parity(entries, [], 3))

    def test_ahead_leg_does_not_block(self):
        entries = [
            {"parity": "equal", "evidence_grade": "fresh", "reason": None},
            {"parity": "ahead", "evidence_grade": "fresh", "reason": None},
        ]
        self.assertTrue(mr._overall_parity(entries, [], 3))

    def test_blocking_unknown_leg_blocks(self):
        entries = [
            {"parity": "equal", "evidence_grade": "fresh", "reason": None},
            {"parity": "unknown", "evidence_grade": "expired", "reason": "parse_error"},
        ]
        self.assertFalse(mr._overall_parity(entries, [], 3))

    def test_benign_unknown_leg_does_not_block(self):
        entries = [
            {"parity": "equal", "evidence_grade": "fresh", "reason": None},
            {"parity": "unknown", "evidence_grade": "expired", "reason": "detached_head"},
        ]
        self.assertTrue(mr._overall_parity(entries, [], 3))


if __name__ == "__main__":
    unittest.main()
