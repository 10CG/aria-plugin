"""Main spec (stale-refs-false-parity) Phase 0 (prereq) tests.

Phase 0 lands zero-behavior-change foundations: F5′ enforced_set resolution (pure,
inert until Phase 1 F4′), sync_freshness.* config keys, and the D16
predicate-domain-table.md skeleton. These tests pin those foundations.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collectors.multi_remote import resolve_enforced_remotes  # type: ignore  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULTS = _ROOT.parent / "config-loader" / "DEFAULTS.json"
_PRED_TABLE = _ROOT / "references" / "predicate-domain-table.md"


class TestResolveEnforcedRemotes(unittest.TestCase):
    def test_nonempty_allowlist_intersects_actual(self):
        enforced, no_matching = resolve_enforced_remotes(
            ["origin", "github"], ["origin", "github", "backup"]
        )
        self.assertEqual(enforced, ["origin", "github"])
        self.assertEqual(no_matching, [])

    def test_configured_absent_goes_to_no_matching_not_ghost_leg(self):
        enforced, no_matching = resolve_enforced_remotes(
            ["origin", "gone"], ["origin", "github"]
        )
        self.assertEqual(enforced, ["origin"])
        self.assertEqual(no_matching, ["gone"])  # not fetched as a ghost fail leg

    def test_empty_list_is_auto_discover_NOT_empty_set(self):
        # 🔴 F5′ trap: [] must mean "all remotes", never "check nothing".
        enforced, no_matching = resolve_enforced_remotes([], ["origin", "github"])
        self.assertEqual(enforced, ["origin", "github"])
        self.assertEqual(no_matching, [])
        self.assertNotEqual(enforced, [])  # the regression this guards against

    def test_none_is_auto_discover(self):
        enforced, _ = resolve_enforced_remotes(None, ["origin", "github"])
        self.assertEqual(enforced, ["origin", "github"])

    def test_read_only_excluded_in_both_modes(self):
        # auto-discover minus read_only
        enforced, _ = resolve_enforced_remotes(None, ["origin", "ro"], read_only=("ro",))
        self.assertEqual(enforced, ["origin"])
        # allowlist minus read_only
        enforced2, _ = resolve_enforced_remotes(["origin", "ro"], ["origin", "ro"], read_only=("ro",))
        self.assertEqual(enforced2, ["origin"])

    def test_order_follows_actual_not_configured(self):
        enforced, _ = resolve_enforced_remotes(["github", "origin"], ["origin", "github"])
        self.assertEqual(enforced, ["origin", "github"])  # actual order


class TestSyncFreshnessDefaults(unittest.TestCase):
    def test_defaults_has_sync_freshness_keys(self):
        d = json.loads(_DEFAULTS.read_text(encoding="utf-8"))
        sf = d["state_scanner"]["sync_freshness"]
        self.assertEqual(sf["evidence_window_seconds"], 3600)
        self.assertEqual(sf["hard_cap_days"], 7)
        self.assertEqual(sf["k_min"], 3)


class TestD16PredicateTableSkeleton(unittest.TestCase):
    def test_table_exists_and_registers_phase0_predicate(self):
        self.assertTrue(_PRED_TABLE.is_file(), "D16 predicate-domain-table.md missing")
        text = _PRED_TABLE.read_text(encoding="utf-8")
        # Phase 0 live predicate registered
        self.assertIn("resolve_enforced_remotes", text)
        # retired predicates section present (lock test #4 target grows in Phase 1)
        self.assertIn("可信(r)", text)
        self.assertIn("freshness_window", text)
        # the lock-test contract is documented for later phases
        self.assertIn("Total partition", text)


if __name__ == "__main__":
    unittest.main()
