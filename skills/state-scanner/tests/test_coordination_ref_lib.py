"""lib/coordination_ref.py — direct unit tests for the F1 #61/#143 parity fix (v1.46.3).

The lib has its OWN `_run` (separate from collectors/_common._run); the #61 (UTF-8
crash-safe) + #143 (LC_ALL=C locale) hardenings landed only on the collector one until
this Spec. These tests hit the REAL changed code path (NOT the boundary-mock used by
test_failure_injection, which mocks fetch_coordination_ref wholesale):

  C1 — `_run` injects LC_ALL=C + encoding/errors (env-assertion, host-locale-agnostic).
  C2 — `fetch_coordination_ref` benign-absent classification (real triple-AND, _run mocked).
  C3 — `_run` is UTF-8 crash-safe on non-UTF-8 bytes (real subprocess decode path).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_SKILL_ROOT = Path(__file__).resolve().parent.parent  # .../state-scanner/
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import lib.coordination_ref as cr  # noqa: E402
from lib.coordination_ref import _run, fetch_coordination_ref  # noqa: E402

BENIGN_STDERR = "fatal: couldn't find remote ref refs/aria/coordination"


class TestRunLocaleAndEncodingParity(unittest.TestCase):
    """C1 — lib `_run` injects LC_ALL=C + encoding="utf-8" + errors="replace".

    Falsifiable regardless of host locale (mock intercepts before dispatch) — closes
    the parallel-_run gap (#143 fix only touched collectors/_common._run).
    """

    def _capture_run(self):
        captured: dict = {}

        class _FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake(*_args, **kwargs):
            captured.update(kwargs)
            return _FakeCompleted()

        return captured, _fake

    def test_run_injects_lc_all_c_and_encoding(self):
        captured, fake = self._capture_run()
        with mock.patch("lib.coordination_ref.subprocess.run", side_effect=fake):
            _run(["git", "status"], cwd=Path("."))
        env = captured.get("env")
        self.assertIsNotNone(env, "_run must pass env=")
        assert env is not None  # type-narrow
        self.assertEqual(env.get("LC_ALL"), "C", "LC_ALL must be forced to C")
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")
        self.assertTrue(captured.get("capture_output"))
        self.assertTrue(captured.get("text"))
        # os.environ preserved (superset)
        import os
        for k in os.environ:
            self.assertIn(k, env, f"os.environ key {k!r} must survive")

    def test_extra_env_coexists_with_lc_all_c(self):
        """extra_env (GIT_INDEX_FILE) must be present AND LC_ALL stays C (LC_ALL pinned last)."""
        captured, fake = self._capture_run()
        with mock.patch("lib.coordination_ref.subprocess.run", side_effect=fake):
            _run(["git", "status"], cwd=Path("."), extra_env={"GIT_INDEX_FILE": "/tmp/x.idx"})
        env = captured.get("env")
        assert env is not None
        self.assertEqual(env.get("GIT_INDEX_FILE"), "/tmp/x.idx", "extra_env must be merged")
        self.assertEqual(env.get("LC_ALL"), "C", "LC_ALL must NOT be overridable by extra_env")


class TestFetchCoordinationRefBenignAbsent(unittest.TestCase):
    """C2 — fetch_coordination_ref benign-absent classification (real path, _run mocked)."""

    def _call(self, rc: int, stderr: str):
        # Mock the internal _run (return rc/stderr) + _resolve_ref (ref absent → "").
        with mock.patch.object(cr, "_run", return_value=(rc, "", stderr)):
            with mock.patch.object(cr, "_resolve_ref", return_value=""):
                return fetch_coordination_ref(Path("/tmp"), remote="origin")

    def test_benign_absent_is_success(self):
        """rc=128 + "couldn't find remote ref <our-ref>" → success, no error_kind."""
        r = self._call(128, BENIGN_STDERR)
        self.assertTrue(r.success)
        self.assertIsNone(r.error_kind)
        self.assertFalse(r.ref_updated)

    def test_non_benign_rc128_is_fetch_failed(self):
        """rc=128 WITHOUT the 'couldn't find remote ref' wording → fetch_failed (not benign)."""
        r = self._call(128, "fatal: the remote end hung up unexpectedly: some transport error")
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, "fetch_failed")

    def test_couldnt_find_but_wrong_ref_not_benign(self):
        """'couldn't find remote ref' for a DIFFERENT ref must NOT be swallowed as benign."""
        r = self._call(128, "fatal: couldn't find remote ref refs/heads/some-feature")
        self.assertFalse(r.success, "wrong ref name must not pass the benign gate")
        self.assertEqual(r.error_kind, "fetch_failed")

    def test_auth_failure_still_classified(self):
        """Regression: a genuine auth failure must still classify as auth_failed (not benign)."""
        r = self._call(128, "fatal: Authentication failed for 'https://...'")
        self.assertFalse(r.success)
        self.assertEqual(r.error_kind, "auth_failed")


class TestRunUtf8CrashSafe(unittest.TestCase):
    """C3 — lib `_run` must not raise UnicodeDecodeError on non-UTF-8 bytes (#61 parity).

    Real subprocess decode path (NOT mocked — mocking would bypass errors='replace')."""

    def test_invalid_bytes_replaced_not_raised(self):
        rc, stdout, _ = _run(
            [sys.executable, "-c",
             "import sys; sys.stdout.buffer.write(b'ok\\xff\\xfebad'); sys.stdout.flush()"],
            cwd=Path("."),
        )
        # No UnicodeDecodeError escaped; invalid bytes became U+FFFD (errors='replace').
        self.assertEqual(rc, 0)
        self.assertIn("ok", stdout)
        self.assertIn("�", stdout, "invalid bytes must be replaced, not crash")


if __name__ == "__main__":
    unittest.main()
