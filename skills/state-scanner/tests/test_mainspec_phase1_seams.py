"""Phase 1 (main spec stale-refs-false-parity) — F3′ deterministic test seams.

Covers the four seams added to collectors/_common.py that the remote_refresh
collector and F1′/F4′ predicates depend on:
  - scan_now()            — ARIA_SCAN_NOW clock injection (fail-soft)
  - is_scan_offline()     — ARIA_SCAN_OFFLINE gate (9.7 stability freeze)
  - fetch_budget_override() — ARIA_SCAN_FETCH_BUDGET leg-cap test seam
  - resolve_remote_host() — Rule #7 SAFE hostname resolver (NEVER emits creds)

These are prerequisite infra; they land GREEN (unit-tested directly), unlike the
P2-P5 acceptance red-tests which gate the not-yet-written collector/predicates.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collectors import _common  # type: ignore  # noqa: E402


class TestScanNow(unittest.TestCase):
    def test_unset_returns_real_utc_now(self):
        with mock.patch.dict(_common.os.environ, {}, clear=False):
            _common.os.environ.pop(_common.ARIA_SCAN_NOW_ENV, None)
            now = _common.scan_now()
        self.assertIsInstance(now, datetime)
        self.assertIsNotNone(now.tzinfo)  # tz-aware

    def test_iso_override_with_offset_parsed(self):
        with mock.patch.dict(
            _common.os.environ, {_common.ARIA_SCAN_NOW_ENV: "2026-07-17T15:00:00+00:00"}
        ):
            now = _common.scan_now()
        self.assertEqual(now, datetime(2026, 7, 17, 15, 0, 0, tzinfo=timezone.utc))

    def test_naive_override_treated_as_utc(self):
        with mock.patch.dict(
            _common.os.environ, {_common.ARIA_SCAN_NOW_ENV: "2026-07-17T15:00:00"}
        ):
            now = _common.scan_now()
        self.assertEqual(now.tzinfo, timezone.utc)
        self.assertEqual(now.hour, 15)

    def test_unparseable_override_falls_back_soft(self):
        # fail-soft: a malformed override must NOT crash — falls back to real clock
        with mock.patch.dict(
            _common.os.environ, {_common.ARIA_SCAN_NOW_ENV: "not-a-date"}
        ):
            now = _common.scan_now()
        self.assertIsInstance(now, datetime)
        self.assertIsNotNone(now.tzinfo)


class TestIsScanOffline(unittest.TestCase):
    def test_unset_is_online(self):
        with mock.patch.dict(_common.os.environ, {}, clear=False):
            _common.os.environ.pop(_common.ARIA_SCAN_OFFLINE_ENV, None)
            self.assertFalse(_common.is_scan_offline())

    def test_truthy_values_offline(self):
        for v in ("1", "true", "TRUE", "yes", "on", " On "):
            with mock.patch.dict(_common.os.environ, {_common.ARIA_SCAN_OFFLINE_ENV: v}):
                self.assertTrue(_common.is_scan_offline(), v)

    def test_falsey_values_online(self):
        for v in ("0", "false", "no", "off", ""):
            with mock.patch.dict(_common.os.environ, {_common.ARIA_SCAN_OFFLINE_ENV: v}):
                self.assertFalse(_common.is_scan_offline(), v)


class TestFetchBudgetOverride(unittest.TestCase):
    def test_unset_none(self):
        with mock.patch.dict(_common.os.environ, {}, clear=False):
            _common.os.environ.pop(_common.ARIA_SCAN_FETCH_BUDGET_ENV, None)
            self.assertIsNone(_common.fetch_budget_override())

    def test_positive_int(self):
        with mock.patch.dict(_common.os.environ, {_common.ARIA_SCAN_FETCH_BUDGET_ENV: "3"}):
            self.assertEqual(_common.fetch_budget_override(), 3)

    def test_zero_and_negative_none(self):
        for v in ("0", "-1"):
            with mock.patch.dict(
                _common.os.environ, {_common.ARIA_SCAN_FETCH_BUDGET_ENV: v}
            ):
                self.assertIsNone(_common.fetch_budget_override(), v)

    def test_non_numeric_none(self):
        with mock.patch.dict(_common.os.environ, {_common.ARIA_SCAN_FETCH_BUDGET_ENV: "x"}):
            self.assertIsNone(_common.fetch_budget_override())


class TestResolveRemoteHost(unittest.TestCase):
    """Rule #7 is the load-bearing property here: a credential embedded in an
    HTTPS remote URL must NEVER appear in the returned value."""

    def _patch_run(self, url: str, rc: int = 0):
        return mock.patch.object(_common, "_run", return_value=(rc, url + "\n", ""))

    def test_https_plain(self):
        with self._patch_run("https://github.com/10CG/Aria.git"):
            self.assertEqual(
                _common.resolve_remote_host(Path("/x"), "github"), "github.com"
            )

    def test_ssh_scheme(self):
        with self._patch_run("ssh://git@forgejo.10cg.pub:22/10CG/Aria.git"):
            self.assertEqual(
                _common.resolve_remote_host(Path("/x"), "origin"), "forgejo.10cg.pub"
            )

    def test_scp_like(self):
        with self._patch_run("git@github.com:10CG/Aria.git"):
            self.assertEqual(
                _common.resolve_remote_host(Path("/x"), "github"), "github.com"
            )

    def test_rule7_https_with_embedded_credential_never_leaks(self):
        url = "https://x-token-auth:FAKETOKEN123@github.com/10CG/Aria.git"
        with self._patch_run(url):
            host = _common.resolve_remote_host(Path("/x"), "github")
        self.assertEqual(host, "github.com")
        # the load-bearing assertion: the token must not survive anywhere in output
        self.assertNotIn("FAKETOKEN123", host or "")
        self.assertNotIn("x-token-auth", host or "")

    def test_scp_like_with_user_never_leaks_user(self):
        # scp-like with a userinfo-ish token-bearing user segment
        with self._patch_run("SECRETUSER@forgejo.10cg.pub:10CG/Aria.git"):
            host = _common.resolve_remote_host(Path("/x"), "origin")
        self.assertEqual(host, "forgejo.10cg.pub")
        self.assertNotIn("SECRETUSER", host or "")

    def test_rc_nonzero_returns_none(self):
        with self._patch_run("whatever", rc=1):
            self.assertIsNone(_common.resolve_remote_host(Path("/x"), "origin"))

    def test_empty_output_returns_none(self):
        with mock.patch.object(_common, "_run", return_value=(0, "\n", "")):
            self.assertIsNone(_common.resolve_remote_host(Path("/x"), "origin"))


if __name__ == "__main__":
    unittest.main()
