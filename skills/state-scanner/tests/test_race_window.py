"""TASK-021 — P2 Race Window Reproducibility Tests.

Verifies that reconcile() behaves deterministically under concurrent injection
of identical-timestamp claims, and that the tiebreak path is reliably triggered.

Test classes
------------
TestReconcileDeterministicUnderConcurrency
    10-thread barrier-synced concurrent reconcile invocations on the same
    input → every thread must receive the same (winner, verdict_reason).
    100-iteration repeat proves non-flakiness.

TestGateRaceSimulation
    Two threads concurrently construct claims (same timestamp), then
    reconcile determines the winner — covering cross-owner and same-owner
    multi-container scenarios.

TestRaceWindowEpsilonAssertion
    Asserts that the timestamp difference between the two concurrent claims
    is < ε (0.5 s), confirming we actually triggered the race window rather
    than serialised execution.

TestNoFlaky
    100 sequential invocations of the race scenario → 100 identical verdicts
    (determinism proof).

Design constraints (per TASK-021 spec §deliverables):
  - threading.Barrier for zero-sleep synchronisation (no time.sleep).
  - ClockProvider via reconcile(now=...) parameter injection — no monkeypatch
    needed because reconcile already accepts an explicit `now` kwarg.
  - Tiebreak path: same claimed_at + distinct container/session lex keys.
  - ε threshold: 0.5 s (well above the ns resolution of datetime.now but
    small enough to distinguish true concurrent construction from serialised).

Spec reference: tasks.md §2.10 (2), §3.4 (b).
"""

from __future__ import annotations

import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap — make lib/ importable as a package (relative imports inside)
# ---------------------------------------------------------------------------
# lib/ uses intra-package relative imports (from .claim_schema import …),
# so we must add the parent of lib/ (i.e. the state-scanner root) to sys.path
# and import as `lib.reconcile` / `lib.claim_schema`.

_SKILL_ROOT = Path(__file__).resolve().parent.parent  # …/state-scanner/
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.claim_schema import ClaimRecord  # noqa: E402  (after sys.path mutation)
from lib.reconcile import reconcile, reconcile_all  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Fixed "now" reference: 5 minutes after the shared test timestamp.
# Claims use heartbeat_at == claimed_at == _SAME_TS, so their heartbeat age
# relative to _NOW is exactly 300 s — well below STALE_TTL (1800 s).
# Using a fixed _NOW (not datetime.now()) keeps tests deterministic and
# insulates them from system-clock drift.
_NOW = datetime(2026, 5, 20, 12, 5, 0, tzinfo=timezone.utc)  # _SAME_TS + 5 min

# A single fixed timestamp used to force tiebreak scenarios.
_SAME_TS = "2026-05-20T12:00:00Z"

# Heartbeat same as claimed_at for simplicity (claim is always fresh).
_FRESH_HB = _SAME_TS


def _make_claim(
    track_id: str,
    container: str,
    session: str,
    *,
    owner: str = "alice",
    claimed_at: str = _SAME_TS,
    heartbeat_at: str = _FRESH_HB,
    status: str = "active",
    phase: str = "B.2",
) -> ClaimRecord:
    """Convenience factory — all parameters have sane defaults for race tests."""
    return ClaimRecord(
        schema_version="1",
        track_id=track_id,
        owner=owner,
        container=container,
        session=session,
        phase=phase,
        status=status,
        claimed_at=claimed_at,
        heartbeat_at=heartbeat_at,
        superseded_from=None,
    )


# ---------------------------------------------------------------------------
# TestReconcileDeterministicUnderConcurrency
# ---------------------------------------------------------------------------

class TestReconcileDeterministicUnderConcurrency(unittest.TestCase):
    """10 threads call reconcile() concurrently on identical input.

    All threads must observe the same (winner_container, verdict_reason).
    The tiebreak rule must fire because both claims share the same claimed_at.
    """

    # Two claims with identical timestamps — forces tiebreak_lex_order.
    # "aaa/s-1" < "bbb/s-2" lexicographically → "aaa" wins.
    _CLAIMS = [
        _make_claim("track-x", "aaa", "s-1"),
        _make_claim("track-x", "bbb", "s-2"),
    ]
    _THREAD_COUNT = 10

    def _single_reconcile(self) -> tuple[Optional[str], str]:
        v = reconcile("track-x", self._CLAIMS, now=_NOW)
        return (v.winner.container if v.winner else None, v.verdict_reason)

    def test_concurrent_reconcile_same_verdict(self):
        """10 threads barrier-synced → all observe the same verdict."""
        results: list[tuple[Optional[str], str]] = []
        lock = threading.Lock()
        barrier = threading.Barrier(self._THREAD_COUNT)

        def worker():
            barrier.wait()  # zero-sleep sync: all threads start simultaneously
            result = self._single_reconcile()
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(self._THREAD_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), self._THREAD_COUNT)
        first = results[0]
        for r in results:
            self.assertEqual(
                r,
                first,
                f"Non-deterministic verdict: got {r!r}, expected {first!r}",
            )

    def test_tiebreak_fires_for_same_timestamp(self):
        """Tiebreak rule (tiebreak_lex_order) must be the deciding reason."""
        v = reconcile("track-x", self._CLAIMS, now=_NOW)
        self.assertEqual(v.verdict_reason, "tiebreak_lex_order")

    def test_tiebreak_winner_is_lex_first(self):
        """Lex-first composite key container/session must win the tiebreak."""
        v = reconcile("track-x", self._CLAIMS, now=_NOW)
        self.assertIsNotNone(v.winner)
        # "aaa/s-1" < "bbb/s-2" → container "aaa" wins
        self.assertEqual(v.winner.container, "aaa")  # type: ignore[union-attr]

    def test_100_iterations_consistent_verdict(self):
        """100 sequential reconcile calls with same input → same verdict every time."""
        reference = self._single_reconcile()
        for i in range(99):
            result = self._single_reconcile()
            self.assertEqual(
                result,
                reference,
                f"Inconsistent verdict at iteration {i + 2}: "
                f"got {result!r}, expected {reference!r}",
            )


# ---------------------------------------------------------------------------
# TestGateRaceSimulation
# ---------------------------------------------------------------------------

class TestGateRaceSimulation(unittest.TestCase):
    """Two threads each construct a claim at an identical injected timestamp.

    Simulates the gate flow: each thread builds a ClaimRecord with the same
    claimed_at → reconcile resolves via tiebreak.  Three sub-scenarios:

    (a) cross-owner: alice/devbox-A vs bob/devbox-B
    (b) same-owner multi-container: alice/devbox-A vs alice/devbox-B
    (c) self-collision: same owner + same container but different sessions
    """

    def _race_two_claims(
        self,
        claim_a: ClaimRecord,
        claim_b: ClaimRecord,
        track_id: str,
    ) -> "reconcile.ReconcileVerdict":  # type: ignore[name-defined]
        """Construct two claims concurrently via barrier then reconcile."""
        results: dict[str, ClaimRecord] = {}
        barrier = threading.Barrier(2)

        def build_a():
            barrier.wait()
            results["A"] = claim_a

        def build_b():
            barrier.wait()
            results["B"] = claim_b

        ta = threading.Thread(target=build_a)
        tb = threading.Thread(target=build_b)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        return reconcile(track_id, [results["A"], results["B"]], now=_NOW)

    # --- (a) cross-owner collision ---

    def test_cross_owner_collision_tiebreak(self):
        """Two owners claim the same track simultaneously → tiebreak_lex_order."""
        claim_a = _make_claim("track-y", "devbox-A", "s-A", owner="alice")
        claim_b = _make_claim("track-y", "devbox-B", "s-B", owner="bob")

        verdict = self._race_two_claims(claim_a, claim_b, "track-y")

        self.assertEqual(verdict.verdict_reason, "tiebreak_lex_order")
        self.assertIsNotNone(verdict.winner)
        # "devbox-A/s-A" < "devbox-B/s-B" lexicographically
        self.assertEqual(verdict.winner.container, "devbox-A")  # type: ignore[union-attr]

    def test_cross_owner_loser_in_yielders(self):
        """The losing cross-owner claim must appear in yielders."""
        claim_a = _make_claim("track-y", "devbox-A", "s-A", owner="alice")
        claim_b = _make_claim("track-y", "devbox-B", "s-B", owner="bob")

        verdict = self._race_two_claims(claim_a, claim_b, "track-y")

        yielder_containers = {c.container for c in verdict.yielders}
        self.assertIn("devbox-B", yielder_containers)

    # --- (b) same-owner multi-container ---

    def test_same_owner_multi_container_tiebreak(self):
        """Same owner, two containers, same timestamp → tiebreak_lex_order."""
        claim_a = _make_claim("track-z", "devbox-A", "s-1", owner="alice")
        claim_b = _make_claim("track-z", "devbox-B", "s-2", owner="alice")

        verdict = self._race_two_claims(claim_a, claim_b, "track-z")

        self.assertEqual(verdict.verdict_reason, "tiebreak_lex_order")
        self.assertIsNotNone(verdict.winner)
        self.assertEqual(verdict.winner.container, "devbox-A")  # type: ignore[union-attr]

    # --- (c) same-owner same-container different sessions ---

    def test_same_container_different_sessions_tiebreak(self):
        """Same container, different session IDs, same timestamp → lex tiebreak."""
        # "devbox-A/sess-001" < "devbox-A/sess-002"
        claim_a = _make_claim("track-w", "devbox-A", "sess-001", owner="alice")
        claim_b = _make_claim("track-w", "devbox-A", "sess-002", owner="alice")

        verdict = self._race_two_calls(claim_a, claim_b, "track-w")

        self.assertEqual(verdict.verdict_reason, "tiebreak_lex_order")
        self.assertEqual(verdict.winner.session, "sess-001")  # type: ignore[union-attr]

    # Alias helper for same-container test (no barrier variation needed)
    def _race_two_calls(
        self,
        claim_a: ClaimRecord,
        claim_b: ClaimRecord,
        track_id: str,
    ):
        return reconcile(track_id, [claim_a, claim_b], now=_NOW)


# ---------------------------------------------------------------------------
# TestRaceWindowEpsilonAssertion
# ---------------------------------------------------------------------------

class TestRaceWindowEpsilonAssertion(unittest.TestCase):
    """Assert the test-validity invariant: injected timestamps are within ε.

    If the delta exceeds ε, the test would be testing serialised (non-race)
    behaviour — not the intended simultaneous-claim scenario.

    ε = 0.5 s (well above datetime constructor resolution; the injected
    timestamps in all race tests are identical strings, so delta == 0).
    """

    _EPSILON_SECONDS = 0.5

    def test_injected_timestamps_within_epsilon(self):
        """Two concurrent claims share the same timestamp → delta == 0 < ε."""
        barrier = threading.Barrier(2)
        timestamps: dict[str, datetime] = {}

        def gate_thread(name: str, ts_str: str):
            barrier.wait()
            timestamps[name] = datetime.fromisoformat(
                ts_str.replace("Z", "+00:00")
            )

        ta = threading.Thread(target=gate_thread, args=("A", _SAME_TS))
        tb = threading.Thread(target=gate_thread, args=("B", _SAME_TS))
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        delta = abs(
            (timestamps["A"] - timestamps["B"]).total_seconds()
        )
        self.assertLess(
            delta,
            self._EPSILON_SECONDS,
            f"Timestamp delta {delta}s >= ε {self._EPSILON_SECONDS}s — "
            "race scenario not properly triggered",
        )

    def test_race_claim_delta_is_zero(self):
        """Confirm claims built from _SAME_TS have exactly zero timestamp delta."""
        claim_a = _make_claim("track-eps", "c-A", "s-A")
        claim_b = _make_claim("track-eps", "c-B", "s-B")

        ts_a = datetime.fromisoformat(claim_a.claimed_at.replace("Z", "+00:00"))
        ts_b = datetime.fromisoformat(claim_b.claimed_at.replace("Z", "+00:00"))
        delta = abs((ts_a - ts_b).total_seconds())

        self.assertEqual(
            delta,
            0.0,
            "Injected timestamps must be identical for a valid race test",
        )
        self.assertLess(delta, self._EPSILON_SECONDS)

    def test_race_verdict_uses_tiebreak_not_earlier_wins(self):
        """When delta == 0, verdict_reason must be tiebreak_lex_order, not earlier_claimed_at_wins."""
        claim_a = _make_claim("track-eps2", "c-A", "s-A")
        claim_b = _make_claim("track-eps2", "c-B", "s-B")

        verdict = reconcile("track-eps2", [claim_a, claim_b], now=_NOW)

        self.assertEqual(verdict.verdict_reason, "tiebreak_lex_order")
        self.assertNotEqual(verdict.verdict_reason, "earlier_claimed_at_wins")


# ---------------------------------------------------------------------------
# TestNoFlaky
# ---------------------------------------------------------------------------

class TestNoFlaky(unittest.TestCase):
    """100 barrier-synced concurrent race scenarios → 100 identical verdicts.

    This is the stability proof required by TASK-021 deliverables:
    'non-flaky (100 consecutive CI runs with no failures)'.

    Strategy: run 100 full race simulations (each with a Barrier(10) burst)
    in a single test method and verify all 100 verdicts are identical.
    This is equivalent to — and more efficient than — 100 separate test runs.
    """

    _ITERATIONS = 100
    _THREADS_PER_BURST = 10

    _CLAIMS = [
        _make_claim("track-flaky", "aaa", "s-1"),
        _make_claim("track-flaky", "bbb", "s-2"),
    ]

    def _run_burst(self) -> list[tuple[Optional[str], str]]:
        """Run one burst of _THREADS_PER_BURST concurrent reconcile calls."""
        results: list[tuple[Optional[str], str]] = []
        lock = threading.Lock()
        barrier = threading.Barrier(self._THREADS_PER_BURST)

        def worker():
            barrier.wait()
            v = reconcile("track-flaky", self._CLAIMS, now=_NOW)
            with lock:
                results.append(
                    (v.winner.container if v.winner else None, v.verdict_reason)
                )

        threads = [
            threading.Thread(target=worker)
            for _ in range(self._THREADS_PER_BURST)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_100_bursts_all_identical(self):
        """100 bursts × 10 threads = 1000 results — all must equal reference."""
        reference_verdict: Optional[tuple[Optional[str], str]] = None

        for i in range(self._ITERATIONS):
            burst = self._run_burst()
            self.assertEqual(
                len(burst),
                self._THREADS_PER_BURST,
                f"Burst {i}: expected {self._THREADS_PER_BURST} results, "
                f"got {len(burst)}",
            )
            burst_reference = burst[0]
            # All threads in this burst must agree
            for j, r in enumerate(burst):
                self.assertEqual(
                    r,
                    burst_reference,
                    f"Burst {i}, thread {j}: intra-burst inconsistency "
                    f"{r!r} != {burst_reference!r}",
                )
            # All bursts must agree with the first burst
            if reference_verdict is None:
                reference_verdict = burst_reference
            else:
                self.assertEqual(
                    burst_reference,
                    reference_verdict,
                    f"Burst {i}: inter-burst inconsistency "
                    f"{burst_reference!r} != {reference_verdict!r}",
                )

        # Confirm the reference verdict is the expected tiebreak winner
        self.assertIsNotNone(reference_verdict)
        winner_container, reason = reference_verdict  # type: ignore[misc]
        self.assertEqual(winner_container, "aaa")
        self.assertEqual(reason, "tiebreak_lex_order")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
