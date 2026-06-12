"""coordination_fetch collector — two-fetch resilience unit tests.

Forgejo Aria #141 (软错误①) / aria-plugin #75 — v1.46.0.

Before this Spec the collector had NO dedicated unit test (only the render-side
degraded board in test_p1_layer_h.py).  These tests cover the two-fetch split:
Fetch 1 (branch heads, load-bearing) + Fetch 2 (coordination ref, benign-absent
tolerant), via the 7 scenarios (a)-(g) from the proposal's TG-B matrix.

Mocking strategy (mirrors test_sync_mocked.py): patch `coordination_fetch._run`
with an argv-dispatching fake; the MagicMock records call_args_list so we can
assert Fetch 2 short-circuits when Fetch 1 fails.  Stdlib-only (unittest), <1s.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _helpers import tmp_project
from collectors.coordination_fetch import (
    _is_benign_coordination_absent,
    collect_coordination_fetch,
)

# Exact argv each fetch builds (remote defaults to "origin").
FETCH1 = ["git", "fetch", "origin", "--no-tags", "+refs/heads/*:refs/remotes/origin/*"]
FETCH2 = ["git", "fetch", "origin", "--no-tags", "refs/aria/coordination"]

# Canonical git wording when a requested concrete ref is absent on the remote.
BENIGN_STDERR = "fatal: couldn't find remote ref refs/aria/coordination"
NETWORK_STDERR = "fatal: unable to access: Could not resolve host: example.invalid"


def _make_run(table: dict[tuple[str, ...], tuple[int, str, str]]):
    """Build a fake `_run` dispatching on the git argv tuple → (rc, stdout, stderr)."""

    def fake(cmd, cwd, timeout=5):  # signature matches collectors._common._run
        return table.get(tuple(cmd), (1, "", f"unmocked: {' '.join(cmd)}"))

    return fake


def _write_cache(project_root: Path, age_seconds: int, coordination_ref_present) -> None:
    """Pre-seed the TTL cache with a last_fetch_at `age_seconds` in the past."""
    cache_dir = project_root / ".aria" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    iso = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat(timespec="seconds")
    payload = {
        "last_fetch_at": iso,
        "refs": [FETCH1[-1]],
        "coordination_ref_present": coordination_ref_present,
    }
    (cache_dir / "coordination-fetch.json").write_text(json.dumps(payload), encoding="utf-8")


def _called_argvs(m) -> list[list[str]]:
    """Extract the cmd list from each recorded _run call."""
    return [c.args[0] if c.args else c.kwargs.get("cmd") for c in m.call_args_list]


def _errors(r) -> set[str]:
    return {e["error"] for e in r.errors}


class TestBenignGate(unittest.TestCase):
    """`_is_benign_coordination_absent` triple-AND gate (OQ4)."""

    def test_benign_true_all_three(self):
        self.assertTrue(_is_benign_coordination_absent(128, BENIGN_STDERR))

    def test_not_benign_wrong_ref_name(self):
        # has "couldn't find remote ref" but for a DIFFERENT ref → not benign
        self.assertFalse(
            _is_benign_coordination_absent(128, "fatal: couldn't find remote ref refs/heads/other")
        )

    def test_not_benign_rc_not_128(self):
        self.assertFalse(_is_benign_coordination_absent(124, BENIGN_STDERR))

    def test_not_benign_missing_wording(self):
        # rc=128 + coordination ref in text but NOT the "couldn't find" wording
        self.assertFalse(
            _is_benign_coordination_absent(128, "fatal: unable to connect refs/aria/coordination")
        )


class TestTwoFetchScenarios(unittest.TestCase):
    """Proposal TG-B matrix (a)-(g)."""

    def test_a_coordination_absent_is_benign(self):
        """(a) Fetch1 ok + Fetch2 benign-absent → success, present=False, NO soft_error."""
        table = {tuple(FETCH1): (0, "", ""), tuple(FETCH2): (128, "", BENIGN_STDERR)}
        with tmp_project() as proj:
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)):
                r = collect_coordination_fetch(proj)
        self.assertTrue(r.data["success"])
        self.assertIs(r.data["coordination_ref_present"], False)
        self.assertFalse(r.data["degraded"])
        self.assertEqual(r.errors, [], "benign absence must NOT raise a soft_error")
        self.assertNotIn("refs/aria/coordination", r.data["refs_fetched"])

    def test_b_coordination_present(self):
        """(b) Fetch1 ok + Fetch2 ok → present=True, refs_fetched includes coordination."""
        table = {tuple(FETCH1): (0, "", ""), tuple(FETCH2): (0, "", "")}
        with tmp_project() as proj:
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)):
                r = collect_coordination_fetch(proj)
        self.assertTrue(r.data["success"])
        self.assertIs(r.data["coordination_ref_present"], True)
        self.assertIn("refs/aria/coordination", r.data["refs_fetched"])
        self.assertEqual(r.errors, [])

    def test_c_fetch1_fail_with_stale_cache_degrades(self):
        """(c) Fetch1 fail + stale cache → degraded; degraded soft_error kept; present read back."""
        table = {tuple(FETCH1): (128, "", NETWORK_STDERR), tuple(FETCH2): (0, "", "")}
        with tmp_project() as proj:
            _write_cache(proj, age_seconds=600, coordination_ref_present=True)
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)) as m:
                r = collect_coordination_fetch(proj)
        self.assertFalse(r.data["success"])
        self.assertTrue(r.data["degraded"])
        # TASK-007 degraded soft_error preserved (R2 code-reviewer)
        self.assertIn("coordination_fetch_degraded", _errors(r))
        self.assertIn("coordination_fetch_failed", _errors(r))
        # coordination_ref_present read back from stale cache, not None (R2 qa)
        self.assertIs(r.data["coordination_ref_present"], True)
        # short-circuit: Fetch 2 must NOT run when Fetch 1 fails
        self.assertNotIn(FETCH2, _called_argvs(m))

    def test_d_fetch1_fail_no_cache_short_circuits(self):
        """(d) Fetch1 fail + no cache → present=None, Fetch2 _run NOT called (short-circuit)."""
        table = {tuple(FETCH1): (128, "", NETWORK_STDERR), tuple(FETCH2): (0, "", "")}
        with tmp_project() as proj:
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)) as m:
                r = collect_coordination_fetch(proj)
        self.assertFalse(r.data["success"])
        self.assertFalse(r.data["degraded"])
        self.assertIsNone(r.data["coordination_ref_present"])
        self.assertIn("coordination_fetch_failed", _errors(r))
        called = _called_argvs(m)
        self.assertIn(FETCH1, called)
        self.assertNotIn(FETCH2, called)
        self.assertEqual(len(called), 1, "exactly one fetch (Fetch 1) before short-circuit")

    def test_e_fetch2_nonbenign_failure_surfaces(self):
        """(e) Fetch1 ok + Fetch2 non-benign (timeout) → success stays True, present=None, soft_error."""
        table = {tuple(FETCH1): (0, "", ""), tuple(FETCH2): (124, "", "")}  # rc=124 timeout
        with tmp_project() as proj:
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)):
                r = collect_coordination_fetch(proj)
        self.assertTrue(r.data["success"], "Fetch 1 ok → success stays True")
        self.assertIsNone(r.data["coordination_ref_present"])
        self.assertIn("coordination_ref_fetch_failed", _errors(r))
        self.assertFalse(r.data["degraded"])

    def test_f_benign_negative_wrong_ref_not_swallowed(self):
        """(f) Fetch2 rc=128 + "couldn't find" but WRONG ref → NOT benign → soft_error."""
        wrong = "fatal: couldn't find remote ref refs/heads/feature"
        table = {tuple(FETCH1): (0, "", ""), tuple(FETCH2): (128, "", wrong)}
        with tmp_project() as proj:
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)):
                r = collect_coordination_fetch(proj)
        # not benign → must surface, not silently set present=False
        self.assertIsNone(r.data["coordination_ref_present"])
        self.assertIn("coordination_ref_fetch_failed", _errors(r))

    def test_g_ttl_cache_hit_no_fetch_stable_field(self):
        """(g) Fresh cache → no _run at all + coordination_ref_present read back (stable)."""
        table = {tuple(FETCH1): (0, "", ""), tuple(FETCH2): (0, "", "")}
        with tmp_project() as proj:
            _write_cache(proj, age_seconds=5, coordination_ref_present=False)
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run(table)) as m:
                r1 = collect_coordination_fetch(proj)
                r2 = collect_coordination_fetch(proj)
        self.assertTrue(r1.data["cached"])
        self.assertEqual(m.call_count, 0, "fresh TTL cache → no fetch subprocess at all")
        # field read back from cache, stable across consecutive cache-hit runs
        self.assertIs(r1.data["coordination_ref_present"], False)
        self.assertEqual(
            r1.data["coordination_ref_present"], r2.data["coordination_ref_present"]
        )

    def test_legacy_cache_without_field_reads_none(self):
        """Backward-compat: a pre-v1.46.0 cache (no coordination_ref_present key) → None on hit."""
        with tmp_project() as proj:
            cache_dir = proj / ".aria" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            iso = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
            # legacy payload: only last_fetch_at + refs, NO coordination_ref_present
            (cache_dir / "coordination-fetch.json").write_text(
                json.dumps({"last_fetch_at": iso, "refs": []}), encoding="utf-8"
            )
            with mock.patch("collectors.coordination_fetch._run", side_effect=_make_run({})):
                r = collect_coordination_fetch(proj)
        self.assertTrue(r.data["cached"])
        self.assertIsNone(r.data["coordination_ref_present"])


if __name__ == "__main__":
    unittest.main()
