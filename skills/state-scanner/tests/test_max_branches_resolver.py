"""OpenSpec state-scanner-output-cap-hardening (#71, v1.38.0) — tests for the
3-layer `resolve_max_branches_scanned()` resolver in `_common.py` plus the
cap-application path in `handoff_multibranch.collect_handoff_multibranch`.

Structure mirrors `TestForgejoHostsResolver` in test_forgejo_config.py (the
sibling 3-layer resolver), but the value domain is `int` not `tuple[str, ...]`,
so these tests exercise int-domain footguns explicitly: bad strings, the
bool-is-int subclass trap, non-positive values, float values, and the
warn-only upper bound (OQ3 owner decision 2026-06-03 — honor user value,
never clamp).

Rule #6 substitute (deterministic/structural skill, per
feedback_deterministic_structural_skill_rule6_substitute): resolver unit tests
(this file) + cap-application monkeypatch test + dogfood.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from _helpers import tmp_project, write_file, make_config
from collectors._common import (
    _DEFAULT_MAX_BRANCHES,
    _MAX_BRANCHES_UPPER_BOUND,
    ARIA_HANDOFF_MAX_BRANCHES_ENV,
    _parse_env_max_branches,
    _read_config_max_branches,
    resolve_max_branches_scanned,
)
import collectors.handoff_multibranch as hmb

_LOGGER = "state-scanner.scan"


def _cfg(max_branches) -> dict:
    """Build a config dict carrying state_scanner.handoff_multibranch.max_branches."""
    return {"state_scanner": {"handoff_multibranch": {"max_branches": max_branches}}}


class _EnvIsolationMixin:
    """Pop ARIA_HANDOFF_MAX_BRANCHES for the duration of each test."""

    def setUp(self):
        self._saved_env = os.environ.pop(ARIA_HANDOFF_MAX_BRANCHES_ENV, None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = self._saved_env
        else:
            os.environ.pop(ARIA_HANDOFF_MAX_BRANCHES_ENV, None)


class TestEnvLayer(_EnvIsolationMixin, unittest.TestCase):
    """Layer 1 — ARIA_HANDOFF_MAX_BRANCHES env var."""

    def test_env_override_simple(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "7"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), 7)

    def test_env_with_surrounding_whitespace(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "  9  "
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), 9)

    def test_env_explicit_default_value(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "20"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), 20)

    def test_env_empty_string_falls_through_to_default(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = ""
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_whitespace_only_falls_through(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "   "
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_zero_falls_through(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "0"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_negative_falls_through(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "-5"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_non_numeric_falls_through(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "abc"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_float_string_falls_through(self):
        # "30.5" is not a valid int literal → ValueError → fall through.
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "30.5"
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_env_zero_falls_through_to_config_not_default(self):
        # env="0" must fall to the NEXT layer (config), not straight to default.
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "0"
        with tmp_project() as p:
            make_config(p, _cfg(15))
            self.assertEqual(resolve_max_branches_scanned(p), 15)


class TestConfigLayer(_EnvIsolationMixin, unittest.TestCase):
    """Layer 2 — .aria/config.json state_scanner.handoff_multibranch.max_branches."""

    def test_config_override_simple(self):
        with tmp_project() as p:
            make_config(p, _cfg(15))
            self.assertEqual(resolve_max_branches_scanned(p), 15)

    def test_config_missing_file_falls_through(self):
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_malformed_json_falls_through(self):
        with tmp_project() as p:
            write_file(p / ".aria" / "config.json", "not valid json {{{")
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_string_value_rejected(self):
        with tmp_project() as p:
            make_config(p, _cfg("30"))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_float_value_rejected(self):
        with tmp_project() as p:
            make_config(p, _cfg(30.5))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_bool_true_rejected(self):
        # bool is an int subclass — must be explicitly rejected, else True→1.
        with tmp_project() as p:
            make_config(p, _cfg(True))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_bool_false_rejected(self):
        with tmp_project() as p:
            make_config(p, _cfg(False))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_zero_falls_through(self):
        with tmp_project() as p:
            make_config(p, _cfg(0))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_negative_falls_through(self):
        with tmp_project() as p:
            make_config(p, _cfg(-3))
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_no_state_scanner_key_falls_through(self):
        with tmp_project() as p:
            make_config(p, {"workflow": {"auto_proceed": False}})
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)

    def test_config_no_handoff_multibranch_key_falls_through(self):
        with tmp_project() as p:
            make_config(p, {"state_scanner": {"confidence_threshold": 90}})
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)


class TestPrecedenceAndDefault(_EnvIsolationMixin, unittest.TestCase):
    """Cross-layer precedence + default fallback."""

    def test_default_no_env_no_config(self):
        with tmp_project() as p:
            self.assertEqual(resolve_max_branches_scanned(p), _DEFAULT_MAX_BRANCHES)
            self.assertEqual(_DEFAULT_MAX_BRANCHES, 20)

    def test_env_beats_config(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "3"
        with tmp_project() as p:
            make_config(p, _cfg(99))
            self.assertEqual(resolve_max_branches_scanned(p), 3)

    def test_returns_int_type(self):
        with tmp_project() as p:
            result = resolve_max_branches_scanned(p)
            self.assertIsInstance(result, int)
            self.assertNotIsInstance(result, bool)


class TestUpperBound(_EnvIsolationMixin, unittest.TestCase):
    """OQ3 (owner 2026-06-03): warn-only + honor user value — never clamp."""

    def test_env_at_bound_no_warning(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = str(_MAX_BRANCHES_UPPER_BOUND)
        with tmp_project() as p:
            # No warning expected at exactly the bound. assertLogs requires at
            # least one record, so assert via assertNoLogs (3.10+).
            with self.assertNoLogs(_LOGGER, level="WARNING"):
                self.assertEqual(
                    resolve_max_branches_scanned(p), _MAX_BRANCHES_UPPER_BOUND
                )

    def test_env_over_bound_honored_with_warning(self):
        over = _MAX_BRANCHES_UPPER_BOUND + 1
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = str(over)
        with tmp_project() as p:
            with self.assertLogs(_LOGGER, level="WARNING") as cm:
                result = resolve_max_branches_scanned(p)
            self.assertEqual(result, over)  # honored, NOT clamped
            self.assertTrue(
                any("exceeds recommended upper bound" in m for m in cm.output)
            )

    def test_env_far_over_bound_honored(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "1000"
        with tmp_project() as p:
            with self.assertLogs(_LOGGER, level="WARNING"):
                self.assertEqual(resolve_max_branches_scanned(p), 1000)

    def test_config_over_bound_honored_with_warning(self):
        over = _MAX_BRANCHES_UPPER_BOUND + 50
        with tmp_project() as p:
            make_config(p, _cfg(over))
            with self.assertLogs(_LOGGER, level="WARNING") as cm:
                result = resolve_max_branches_scanned(p)
            self.assertEqual(result, over)
            self.assertTrue(
                any("exceeds recommended upper bound" in m for m in cm.output)
            )

    def test_under_bound_no_warning(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "440"
        with tmp_project() as p:
            with self.assertNoLogs(_LOGGER, level="WARNING"):
                self.assertEqual(resolve_max_branches_scanned(p), 440)


class TestLayerParsersDirect(_EnvIsolationMixin, unittest.TestCase):
    """Direct unit coverage of the per-layer parser helpers."""

    def test_parse_env_valid(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "42"
        self.assertEqual(_parse_env_max_branches(), 42)

    def test_parse_env_invalid_returns_none(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "not-a-number"
        self.assertIsNone(_parse_env_max_branches())

    def test_parse_env_unset_returns_none(self):
        self.assertIsNone(_parse_env_max_branches())

    def test_read_config_missing_file_returns_none(self):
        with tmp_project() as p:
            self.assertIsNone(_read_config_max_branches(p))

    def test_read_config_valid_int(self):
        with tmp_project() as p:
            make_config(p, _cfg(33))
            self.assertEqual(_read_config_max_branches(p), 33)

    def test_read_config_bool_returns_none(self):
        with tmp_project() as p:
            make_config(p, _cfg(True))
            self.assertIsNone(_read_config_max_branches(p))


class TestCapApplicationPath(_EnvIsolationMixin, unittest.TestCase):
    """TG-B.5 — cap-application path inside collect_handoff_multibranch.

    Synthesize >cap remote branches by patching `_list_origin_branches`, and
    patch `_list_handoff_files` to return no docs so each capped branch is
    iterated cleanly (branches_scanned increments without real git calls).
    """

    def _synthetic_branches(self, n: int):
        return [f"feature/branch-{i:03d}" for i in range(n)]

    def test_cap_fires_soft_error_at_default(self):
        with tmp_project() as p:
            with mock.patch.object(
                hmb, "_list_origin_branches",
                return_value=(self._synthetic_branches(21), None),
            ), mock.patch.object(
                hmb, "_list_handoff_files", return_value=([], None)
            ):
                r = hmb.collect_handoff_multibranch(p)
            errs = {e["error"] for e in r.errors}
            self.assertIn("handoff_multibranch_branch_cap", errs)
            self.assertEqual(r.data["branches_scanned"], _DEFAULT_MAX_BRANCHES)

    def test_cap_uses_env_override(self):
        os.environ[ARIA_HANDOFF_MAX_BRANCHES_ENV] = "5"
        with tmp_project() as p:
            with mock.patch.object(
                hmb, "_list_origin_branches",
                return_value=(self._synthetic_branches(21), None),
            ), mock.patch.object(
                hmb, "_list_handoff_files", return_value=([], None)
            ):
                r = hmb.collect_handoff_multibranch(p)
            self.assertEqual(r.data["branches_scanned"], 5)
            self.assertIn(
                "handoff_multibranch_branch_cap",
                {e["error"] for e in r.errors},
            )

    def test_cap_uses_config_override(self):
        with tmp_project() as p:
            make_config(p, _cfg(25))
            with mock.patch.object(
                hmb, "_list_origin_branches",
                return_value=(self._synthetic_branches(21), None),
            ), mock.patch.object(
                hmb, "_list_handoff_files", return_value=([], None)
            ):
                r = hmb.collect_handoff_multibranch(p)
            # 21 branches < resolved cap 25 → NO cap fired, all scanned.
            self.assertEqual(r.data["branches_scanned"], 21)
            self.assertNotIn(
                "handoff_multibranch_branch_cap",
                {e["error"] for e in r.errors},
            )

    def test_no_cap_when_under_default(self):
        with tmp_project() as p:
            with mock.patch.object(
                hmb, "_list_origin_branches",
                return_value=(self._synthetic_branches(3), None),
            ), mock.patch.object(
                hmb, "_list_handoff_files", return_value=([], None)
            ):
                r = hmb.collect_handoff_multibranch(p)
            self.assertEqual(r.data["branches_scanned"], 3)
            self.assertNotIn(
                "handoff_multibranch_branch_cap",
                {e["error"] for e in r.errors},
            )


if __name__ == "__main__":
    unittest.main()
