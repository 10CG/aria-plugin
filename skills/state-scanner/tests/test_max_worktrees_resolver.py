"""OpenSpec cross-worktree-handoff-discovery (#139) — tests for the 3-layer
`resolve_max_worktrees_scanned()` resolver in `_common.py`.

Mirrors `test_max_branches_resolver.py` structure (the sibling #71 resolver),
but with worktree-specific env/config keys and a lower default (8 vs 20). Same
int-domain footguns: bad strings, bool-is-int trap, non-positive, float, and
the warn-only upper bound (R2 N-5: "int 域 fail-soft 对齐 #71").

Rule #6 substitute (deterministic resolver): unit tests + the collector's
cap-application path test in test_handoff_worktrees.py + dogfood.
"""

from __future__ import annotations

import os
import unittest

from _helpers import tmp_project, write_file, make_config
from collectors._common import (
    _DEFAULT_MAX_WORKTREES,
    _MAX_WORKTREES_UPPER_BOUND,
    ARIA_WORKTREE_MAX_SCANNED_ENV,
    _parse_env_max_worktrees,
    _read_config_max_worktrees,
    resolve_max_worktrees_scanned,
)

_LOGGER = "state-scanner.scan"


def _cfg(max_worktrees) -> dict:
    """Build a config dict carrying state_scanner.worktree_scan.max_worktrees."""
    return {"state_scanner": {"worktree_scan": {"max_worktrees": max_worktrees}}}


class _EnvIsolationMixin:
    """Pop ARIA_WORKTREE_MAX_SCANNED for the duration of each test."""

    def setUp(self):
        self._saved_env = os.environ.pop(ARIA_WORKTREE_MAX_SCANNED_ENV, None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = self._saved_env
        else:
            os.environ.pop(ARIA_WORKTREE_MAX_SCANNED_ENV, None)


class TestEnvLayer(_EnvIsolationMixin, unittest.TestCase):
    def test_env_override_simple(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "5"
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), 5)

    def test_env_with_surrounding_whitespace(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "  6  "
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), 6)

    def test_env_empty_falls_through_to_default(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = ""
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_env_zero_falls_through(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "0"
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_env_negative_falls_through(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "-3"
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_env_non_numeric_falls_through(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "lots"
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_env_float_string_falls_through(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "4.5"
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_env_zero_falls_through_to_config_not_default(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "0"
        with tmp_project() as p:
            make_config(p, _cfg(12))
            self.assertEqual(resolve_max_worktrees_scanned(p), 12)


class TestConfigLayer(_EnvIsolationMixin, unittest.TestCase):
    def test_config_override_simple(self):
        with tmp_project() as p:
            make_config(p, _cfg(11))
            self.assertEqual(resolve_max_worktrees_scanned(p), 11)

    def test_config_missing_file_falls_through(self):
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_malformed_json_falls_through(self):
        with tmp_project() as p:
            write_file(p / ".aria" / "config.json", "not json {{{")
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_string_value_rejected(self):
        with tmp_project() as p:
            make_config(p, _cfg("9"))
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_float_value_rejected(self):
        with tmp_project() as p:
            make_config(p, _cfg(9.5))
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_bool_true_rejected(self):
        # bool is an int subclass — must be rejected, else True→1.
        with tmp_project() as p:
            make_config(p, _cfg(True))
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_zero_falls_through(self):
        with tmp_project() as p:
            make_config(p, _cfg(0))
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)

    def test_config_no_worktree_scan_key_falls_through(self):
        with tmp_project() as p:
            make_config(p, {"state_scanner": {"confidence_threshold": 90}})
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)


class TestPrecedenceAndDefault(_EnvIsolationMixin, unittest.TestCase):
    def test_default_no_env_no_config(self):
        with tmp_project() as p:
            self.assertEqual(resolve_max_worktrees_scanned(p), _DEFAULT_MAX_WORKTREES)
            self.assertEqual(_DEFAULT_MAX_WORKTREES, 8)

    def test_env_beats_config(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "2"
        with tmp_project() as p:
            make_config(p, _cfg(50))
            self.assertEqual(resolve_max_worktrees_scanned(p), 2)

    def test_returns_int_not_bool(self):
        with tmp_project() as p:
            result = resolve_max_worktrees_scanned(p)
            self.assertIsInstance(result, int)
            self.assertNotIsInstance(result, bool)


class TestUpperBound(_EnvIsolationMixin, unittest.TestCase):
    """Warn-only + honor user value — never clamp (mirrors #71 OQ3)."""

    def test_env_at_bound_no_warning(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = str(_MAX_WORKTREES_UPPER_BOUND)
        with tmp_project() as p:
            with self.assertNoLogs(_LOGGER, level="WARNING"):
                self.assertEqual(
                    resolve_max_worktrees_scanned(p), _MAX_WORKTREES_UPPER_BOUND
                )

    def test_env_over_bound_honored_with_warning(self):
        over = _MAX_WORKTREES_UPPER_BOUND + 1
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = str(over)
        with tmp_project() as p:
            with self.assertLogs(_LOGGER, level="WARNING") as cm:
                result = resolve_max_worktrees_scanned(p)
            self.assertEqual(result, over)  # honored, NOT clamped
            self.assertTrue(
                any("exceeds recommended upper bound" in m for m in cm.output)
            )

    def test_config_over_bound_honored_with_warning(self):
        over = _MAX_WORKTREES_UPPER_BOUND + 20
        with tmp_project() as p:
            make_config(p, _cfg(over))
            with self.assertLogs(_LOGGER, level="WARNING"):
                self.assertEqual(resolve_max_worktrees_scanned(p), over)


class TestLayerParsersDirect(_EnvIsolationMixin, unittest.TestCase):
    def test_parse_env_valid(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "7"
        self.assertEqual(_parse_env_max_worktrees(), 7)

    def test_parse_env_invalid_returns_none(self):
        os.environ[ARIA_WORKTREE_MAX_SCANNED_ENV] = "nope"
        self.assertIsNone(_parse_env_max_worktrees())

    def test_parse_env_unset_returns_none(self):
        self.assertIsNone(_parse_env_max_worktrees())

    def test_read_config_valid_int(self):
        with tmp_project() as p:
            make_config(p, _cfg(13))
            self.assertEqual(_read_config_max_worktrees(p), 13)

    def test_read_config_bool_returns_none(self):
        with tmp_project() as p:
            make_config(p, _cfg(False))
            self.assertIsNone(_read_config_max_worktrees(p))


if __name__ == "__main__":
    unittest.main()
