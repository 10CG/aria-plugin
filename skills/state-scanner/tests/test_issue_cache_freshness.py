"""Spec C — issue_cache_freshness_probe tests (AC-1..AC-5b + A1 fetch-health).

Tests the pure ``evaluate(repo)`` of issue_cache_freshness_probe.py: it reads the
PREVIOUS .aria/state-snapshot.json (lag-1) and returns (verdict, message) with
verdict in {"ok", "stale", "skip"}. The CLI (main) maps skip → "##SKIP##" stdout
marker + exit 0 (B1); collectors/custom_checks.py maps that marker to a "skip"
status (see test_custom_checks.py::TestSkipStatus).

A1 (review-driven): the PRIMARY staleness signal is a MISSING fetched_at while
issue_scan is enabled (persistent fetch failure → green-void the Δ-only check
missed). A transient fetch_error WITH fresh fetched_at is NOT stale (AC-2
orthogonality). The Δ upper bound is a secondary guard.

Anti-empty-green (AC-2): every "healthy → OK" fixture is paired with a
"same axis truly faulty → STALE" sibling.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import issue_cache_freshness_probe as probe  # type: ignore[import]  # noqa: E402
from issue_cache_freshness_probe import evaluate  # type: ignore[import]  # noqa: E402

_CFG_ENABLED = {"state_scanner": {"issue_scan": {"enabled": True, "cache_ttl_seconds": 900}}}
_OMIT = object()


def _setup(root, *, config=None, snapshot=_OMIT):
    """Write .aria/config.json (+ optional state-snapshot.json) under root."""
    write_file(root / ".aria" / "config.json", json.dumps(config if config is not None else _CFG_ENABLED))
    if snapshot is not _OMIT:
        raw = snapshot if isinstance(snapshot, str) else json.dumps(snapshot)
        write_file(root / ".aria" / "state-snapshot.json", raw)


def _snap(generated_at, fetched_at, **issue_extra):
    iss = {"fetched_at": fetched_at, "source": "live", "fetch_error": None}
    iss.update(issue_extra)
    return {"generated_at": generated_at, "issue_status": iss}


class TestHealthyAndStaleDelta(unittest.TestCase):
    def test_ac1_healthy_previous_snapshot_ok(self):
        # Δ=+600s (cache-hit within TTL); no dependence on issues.json mtime.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:10:00Z", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "ok")

    def test_ac3_negative_delta_live_fetch_ok(self):
        # fetched_at LATER than generated_at (Δ=-8s) = live fetch = healthiest.
        # No lower bound (the retracted v1 lower bound must not resurface).
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:00:00Z", "2026-07-15T12:00:08Z"))
            self.assertEqual(evaluate(root)[0], "ok")

    def test_ac3_single_ttl_edge_ok(self):
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:15:00Z", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "ok")

    def test_delta_boundary_exact_2x_ttl_ok(self):
        # Δ=1800s exactly (<=). Secondary Δ guard boundary.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:30:00Z", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "ok")

    def test_delta_just_over_2x_ttl_stale(self):
        # Δ=1801s (>1800). Secondary-guard dual — catches flipped comparator / wrong unit.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:30:01Z", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "stale")


class TestFetchHealthA1(unittest.TestCase):
    """A1: missing fetched_at (persistent fetch breakage) → STALE, not green-void."""

    def test_missing_fetched_at_is_stale(self):
        # issue_scan enabled, previous scan's fetch broke → fetched_at=None,
        # fetch_error set, source unavailable. Must STALE (was SKIP green-void).
        with tmp_project() as root:
            snap = {
                "generated_at": "2026-07-15T12:00:00Z",
                "issue_status": {"fetched_at": None, "source": "unavailable", "fetch_error": "auth_failed"},
            }
            _setup(root, snapshot=snap)
            verdict, msg = evaluate(root)
            self.assertEqual(verdict, "stale", msg)
            self.assertIn("STALE", msg)

    def test_transient_fetch_error_with_fresh_fetched_at_is_ok(self):
        # AC-2 orthogonality: fetch_error set BUT fetched_at still fresh (cache
        # survived one failed refresh) → OK, NOT stale. Guards against A1
        # over-firing on transient errors.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:05:00Z", "2026-07-15T12:00:00Z", fetch_error="rate_limited"))
            self.assertEqual(evaluate(root)[0], "ok")

    def test_missing_fetched_at_not_a_skip(self):
        # Dual: a present-but-broken issue_status (fetched_at None) must be STALE,
        # never SKIP — that green-void is exactly what A1 fixes.
        with tmp_project() as root:
            _setup(root, snapshot={"generated_at": "2026-07-15T12:00:00Z", "issue_status": {"fetched_at": None}})
            self.assertEqual(evaluate(root)[0], "stale")


class TestSkipStates(unittest.TestCase):
    def test_ac5b_skip_no_previous_snapshot(self):
        with tmp_project() as root:
            _setup(root)  # snapshot omitted
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_skip_missing_generated_at(self):
        # Migration: adopter upgraded aria-plugin, previous snapshot from old scan.py
        # has no generated_at → SKIP, NOT FAIL (else every upgrade first-run reds).
        with tmp_project() as root:
            _setup(root, snapshot={"issue_status": {"fetched_at": "2026-07-15T12:00:00Z"}})
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_skip_issue_status_absent(self):
        # issue_scan was disabled in the previous scan → issue_status key omitted
        # entirely (scan.py maps disabled → None). Genuine no-data → SKIP.
        with tmp_project() as root:
            _setup(root, snapshot={"generated_at": "2026-07-15T12:00:00Z"})
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_skip_non_dict_issue_status_does_not_crash(self):
        # Review R-b1: hand-edited non-dict issue_status must SKIP, not crash.
        with tmp_project() as root:
            _setup(root, snapshot={"generated_at": "2026-07-15T12:00:00Z", "issue_status": "broken"})
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_skip_corrupt_json(self):
        with tmp_project() as root:
            _setup(root, snapshot='{"generated_at": "trunc')
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_skip_unparseable_timestamp(self):
        with tmp_project() as root:
            _setup(root, snapshot=_snap("not-a-date", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "skip")

    def test_ac5b_healthy_previous_is_not_skip(self):
        # Negation pin: a healthy previous snapshot must be ok/stale, never SKIP.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:10:00Z", "2026-07-15T12:00:00Z"))
            self.assertIn(evaluate(root)[0], ("ok", "stale"))


class TestConfigPaths(unittest.TestCase):
    def test_disabled_is_ok(self):
        with tmp_project() as root:
            _setup(root, config={"state_scanner": {"issue_scan": {"enabled": False}}})
            verdict, msg = evaluate(root)
            self.assertEqual(verdict, "ok")
            self.assertIn("disabled", msg)

    def test_config_unreadable_is_skip(self):
        with tmp_project() as root:  # no config
            self.assertEqual(evaluate(root)[0], "skip")

    def test_custom_ttl_widens_secondary_window(self):
        # cache_ttl_seconds=1800 → 2×TTL=3600; Δ=3000s that would be stale at 900 → ok.
        cfg = {"state_scanner": {"issue_scan": {"enabled": True, "cache_ttl_seconds": 1800}}}
        with tmp_project() as root:
            _setup(root, config=cfg, snapshot=_snap("2026-07-15T12:50:00Z", "2026-07-15T12:00:00Z"))
            self.assertEqual(evaluate(root)[0], "ok")


class TestCliContractB1(unittest.TestCase):
    """B1: skip → '##SKIP##' stdout marker + exit 0; ok → exit 0; stale → exit 1."""

    def test_skip_prints_marker_exit_0(self):
        import io
        from contextlib import redirect_stdout
        with tmp_project() as root:
            _setup(root)  # no snapshot → skip
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = probe.main([str(root)])
            self.assertEqual(rc, 0)
            self.assertTrue(buf.getvalue().splitlines()[0].startswith(probe.SKIP_MARKER))

    def test_ok_exit_0_no_marker(self):
        import io
        from contextlib import redirect_stdout
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:10:00Z", "2026-07-15T12:00:00Z"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = probe.main([str(root)])
            self.assertEqual(rc, 0)
            self.assertFalse(buf.getvalue().startswith(probe.SKIP_MARKER))

    def test_stale_exit_1(self):
        import io
        from contextlib import redirect_stdout
        with tmp_project() as root:
            _setup(root, snapshot={"generated_at": "2026-07-15T12:00:00Z", "issue_status": {"fetched_at": None}})
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = probe.main([str(root)])
            self.assertEqual(rc, 1)

    def test_output_deterministic_no_delta_digits(self):
        # AC-4: bucketed output, no embedded Δ seconds → two evaluations identical.
        with tmp_project() as root:
            _setup(root, snapshot=_snap("2026-07-15T12:10:00Z", "2026-07-15T12:00:00Z"))
            _, m1 = evaluate(root)
            _, m2 = evaluate(root)
            self.assertEqual(m1, m2)
            self.assertNotRegex(m1, r"\d+s")


if __name__ == "__main__":
    unittest.main()
