"""coordination_fetch module — F6′ backward-compat shim unit tests
(Phase 1 increment 5, main spec state-scanner-stale-refs-false-parity).

Pre-increment-5 this module ran its OWN two-fetch network I/O with an
independent 30s TTL cache; that implementation is retired (F6′ "read法(a)":
retire + shim — see `remote_refresh.py`). All scheduling/network-fetch tests
for that behavior now live in `test_remote_refresh.py`.

This file covers what remains in `coordination_fetch.py`:
  - `TestBenignGate` — `_is_benign_coordination_absent` triple-AND gate (OQ4),
    unchanged pure-function test, retained verbatim.
  - `TestDeriveLegacyBlock` — `derive_legacy_coordination_fetch_block`'s task
    3.14 mapping formula, as a full lock truth table: 3 `fetch_ok` states ×
    stale-value-present-or-not, all three legacy output flags
    (`success`/`degraded`/`cached`) asserted per cell — including the hidden
    3rd cell (blueprint top_risks) that `test/test_coordination_fetch.py`
    pre-increment-5 could not construct: `fetch_ok=="not_attempted"` with a
    usable prior `fetched_at` must read `cached=True, degraded=False` (NOT a
    red bar — "we didn't ask" is not "we failed to reach it").
"""

from __future__ import annotations

import unittest

from collectors.coordination_fetch import (
    COORDINATION_REF,
    _is_benign_coordination_absent,
    derive_legacy_coordination_fetch_block,
)

BENIGN_STDERR = "fatal: couldn't find remote ref refs/aria/coordination"

_FETCHED_AT = "2026-07-17T12:00:00+00:00"


def _leg(
    *,
    repo: str = ".",
    remote: str = "origin",
    fetch_ok: str,
    fetched_at: str | None,
    error_kind: str | None = None,
    coordination_ref_present: bool | None = None,
) -> dict:
    return {
        "repo": repo,
        "remote": remote,
        "host": "forgejo.10cg.pub",
        "fetched_at": fetched_at,
        "fetch_ok": fetch_ok,
        "error_kind": error_kind,
        "scan_generation": 3,
        "generation_fetched": 3 if fetch_ok == "true" else 2,
        "consecutive_unverified": 0,
        "coordination_ref_present": coordination_ref_present,
    }


def _rr(*legs: dict) -> dict:
    return {"legs": list(legs), "skipped_count": 0, "skipped_remotes": []}


class TestBenignGate(unittest.TestCase):
    """`_is_benign_coordination_absent` triple-AND gate (OQ4)."""

    def test_benign_true_all_three(self):
        self.assertTrue(_is_benign_coordination_absent(128, BENIGN_STDERR))

    def test_not_benign_wrong_ref_name(self):
        self.assertFalse(
            _is_benign_coordination_absent(128, "fatal: couldn't find remote ref refs/heads/other")
        )

    def test_not_benign_rc_not_128(self):
        self.assertFalse(_is_benign_coordination_absent(124, BENIGN_STDERR))

    def test_not_benign_missing_wording(self):
        self.assertFalse(
            _is_benign_coordination_absent(128, "fatal: unable to connect refs/aria/coordination")
        )


class TestDeriveLegacyBlock(unittest.TestCase):
    """task 3.14 lock truth table — 3 `fetch_ok` states × stale-value presence,
    all three legacy flags (success/degraded/cached) asserted per cell."""

    # ── Row 1: fetch_ok == "true" ───────────────────────────────────────────
    def test_true_fetch_ok_success_not_degraded_not_cached(self):
        leg = _leg(fetch_ok="true", fetched_at=_FETCHED_AT, coordination_ref_present=True)
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertTrue(block["success"])
        self.assertFalse(block["degraded"])
        self.assertFalse(block["cached"])
        self.assertIsNone(block["degradation_reason"])
        self.assertIsNone(block["error_kind"])
        self.assertIsNone(block["error_msg"])
        self.assertEqual(block["last_fetch_at"], _FETCHED_AT)
        self.assertIs(block["coordination_ref_present"], True)
        self.assertIn(COORDINATION_REF, block["refs_fetched"])

    def test_true_fetch_ok_coordination_absent_benign(self):
        """Fetch1 ok + Fetch2 benign-absent: coordination_ref_present=False, no
        COORDINATION_REF in refs_fetched (mirrors pre-increment-5 scenario a)."""
        leg = _leg(fetch_ok="true", fetched_at=_FETCHED_AT, coordination_ref_present=False)
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertTrue(block["success"])
        self.assertIs(block["coordination_ref_present"], False)
        self.assertNotIn(COORDINATION_REF, block["refs_fetched"])

    # ── Row 2: fetch_ok == "false", stale value PRESENT (served_stale_cache) ──
    def test_false_fetch_ok_with_stale_value_degrades(self):
        leg = _leg(fetch_ok="false", fetched_at=_FETCHED_AT, error_kind="network")
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertFalse(block["success"])
        self.assertTrue(block["degraded"])
        self.assertTrue(block["cached"])
        self.assertEqual(block["degradation_reason"], "fetch_failed_using_stale_cache")
        self.assertEqual(block["error_kind"], "network")
        self.assertIsNotNone(block["error_msg"])
        self.assertEqual(block["last_fetch_at"], _FETCHED_AT)
        self.assertEqual(block["refs_fetched"], [])

    # ── Row 3: fetch_ok == "false", NO stale value (pure failure) ─────────────
    def test_false_fetch_ok_no_stale_value_not_degraded(self):
        leg = _leg(fetch_ok="false", fetched_at=None, error_kind="auth_403")
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertFalse(block["success"])
        self.assertFalse(block["degraded"], "no stale cache to serve → not degraded")
        self.assertFalse(block["cached"])
        self.assertIsNone(block["degradation_reason"])
        self.assertEqual(block["error_kind"], "auth_403")
        self.assertIsNotNone(block["error_msg"])
        self.assertEqual(block["last_fetch_at"], "")
        self.assertIsNone(block["coordination_ref_present"])

    # ── Row 4 (the hidden cell — blueprint top_risks): "not_attempted" WITH a
    #    usable prior fetched_at → cached=True, degraded=False (NOT a red bar). ──
    def test_not_attempted_with_stale_value_is_cached_not_degraded(self):
        leg = _leg(fetch_ok="not_attempted", fetched_at=_FETCHED_AT)
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertFalse(block["success"])
        self.assertFalse(
            block["degraded"],
            "not_attempted must NEVER satisfy degraded's fetch_ok=='false' clause",
        )
        self.assertTrue(block["cached"], "a usable prior fetched_at is being served")
        self.assertIsNone(block["degradation_reason"])
        self.assertIsNone(block["error_kind"])
        self.assertEqual(block["last_fetch_at"], _FETCHED_AT)
        self.assertEqual(block["refs_fetched"], [])

    # ── Row 5: "not_attempted" with NO prior value (never fetched at all) ─────
    def test_not_attempted_no_stale_value_not_cached(self):
        leg = _leg(fetch_ok="not_attempted", fetched_at=None)
        block = derive_legacy_coordination_fetch_block(_rr(leg))
        self.assertFalse(block["success"])
        self.assertFalse(block["degraded"])
        self.assertFalse(block["cached"])
        self.assertEqual(block["last_fetch_at"], "")
        self.assertIsNone(block["coordination_ref_present"])

    # ── Missing/absent leg (no matching (".", "origin") entry, or malformed
    #    remote_refresh_data altogether) — fail-soft default block ─────────────
    def test_missing_origin_leg_returns_empty_default(self):
        other = _leg(repo="sub", remote="origin", fetch_ok="true", fetched_at=_FETCHED_AT)
        block = derive_legacy_coordination_fetch_block(_rr(other))
        self.assertFalse(block["success"])
        self.assertFalse(block["degraded"])
        self.assertFalse(block["cached"])
        self.assertEqual(block["last_fetch_at"], "")
        self.assertEqual(block["age_seconds"], 0)
        self.assertEqual(block["refs_fetched"], [])
        self.assertIsNone(block["coordination_ref_present"])

    def test_non_origin_remote_never_yields_coordination_ref_present(self):
        """Only the (".", "origin") leg ever runs Fetch 2 — a non-origin remote
        leg for the main repo must not be picked up by the derivation (only
        exact repo=="." AND remote=="origin" matches)."""
        github_leg = _leg(remote="github", fetch_ok="true", fetched_at=_FETCHED_AT,
                           coordination_ref_present=None)
        block = derive_legacy_coordination_fetch_block(_rr(github_leg))
        # No matching (".", "origin") leg present → default empty block.
        self.assertFalse(block["success"])
        self.assertIsNone(block["coordination_ref_present"])

    def test_none_remote_refresh_data_is_fail_soft(self):
        block = derive_legacy_coordination_fetch_block(None)
        self.assertFalse(block["success"])
        self.assertFalse(block["degraded"])
        self.assertEqual(block["refs_fetched"], [])

    def test_malformed_legs_not_a_list_is_fail_soft(self):
        block = derive_legacy_coordination_fetch_block({"legs": "not-a-list"})
        self.assertFalse(block["success"])
        self.assertEqual(block["refs_fetched"], [])


if __name__ == "__main__":
    unittest.main()
