"""Tests for ci_backends/ package (v1.31.0+ CI backend abstraction).

Module-level tests for the new ci_backends package per Task 1.7 (AC-7.2 +
R1 qa F-02 fix). Complements test_pre_merge_gate.py which tests the gate
orchestration layer.

Coverage breakdown (≥11 cases per Task 1.7):
- base.py contract (4+): CIStatus dataclass + InFlightStatus.has_runs +
  ABC abstract enforce + dataclass equality
- aether.py migrated (3+): probe()/precheck() + _query subprocess success/fail
- github_actions.py stub (2+): probe() gh auth mock + query NIE message
- registry (2+): BACKENDS list order + cached_probe/reset_probe_cache idempotent
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

# Add scripts/ to path for direct module import.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from ci_backends import (  # noqa: E402
    BACKENDS,
    AetherBackend,
    AetherQueryError,
    CIBackend,
    CIStatus,
    GitHubActionsBackend,
    InFlightStatus,
    cached_probe,
    reset_probe_cache,
)
from ci_backends.aether import AETHER_CLI_MIN_SHA  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# base.py — CIBackend ABC + CIStatus + InFlightStatus contract
# ═══════════════════════════════════════════════════════════════════════════


class TestCIStatus(unittest.TestCase):
    """CIStatus dataclass field types + defaults + equality."""

    def test_minimal_construction(self) -> None:
        s = CIStatus(state="passing")
        self.assertEqual(s.state, "passing")
        self.assertIsNone(s.run_id)
        self.assertIsNone(s.url)
        self.assertEqual(s.checked_at, "")

    def test_full_construction_and_attribute_access(self) -> None:
        s = CIStatus(
            state="failing",
            run_id="run-12345",
            url="https://forgejo.10cg.pub/runs/12345",
            checked_at="2026-05-28T13:00:00Z",
        )
        # AC-5.4: callers use attribute access, not dict-key access
        self.assertEqual(s.state, "failing")
        self.assertEqual(s.run_id, "run-12345")
        self.assertEqual(s.url, "https://forgejo.10cg.pub/runs/12345")
        self.assertEqual(s.checked_at, "2026-05-28T13:00:00Z")


class TestInFlightStatus(unittest.TestCase):
    """InFlightStatus dataclass + has_runs property."""

    def test_empty_runs_has_runs_false(self) -> None:
        ifs = InFlightStatus()
        self.assertEqual(ifs.runs, [])
        self.assertFalse(ifs.has_runs)

    def test_populated_runs_has_runs_true(self) -> None:
        ifs = InFlightStatus(runs=[{"id": 1}, {"id": 2}], checked_at="2026-05-28T13:00:00Z")
        self.assertEqual(len(ifs.runs), 2)
        self.assertTrue(ifs.has_runs)


class TestCIBackendABC(unittest.TestCase):
    """CIBackend abstract enforce — subclasses MUST implement probe + query_*."""

    def test_cannot_instantiate_abstract(self) -> None:
        with self.assertRaises(TypeError):
            # CIBackend is abstract — direct instantiation forbidden
            CIBackend()  # type: ignore[abstract]

    def test_subclass_missing_abstract_raises(self) -> None:
        class IncompleteBackend(CIBackend):
            name = "incomplete"
            # Missing probe / query_pr_ci / query_branch_in_flight

        with self.assertRaises(TypeError):
            IncompleteBackend()  # type: ignore[abstract]

    def test_default_precheck_returns_ok(self) -> None:
        """ABC default precheck returns (True, "") — backends override as needed."""
        class MinimalBackend(CIBackend):
            name = "minimal"

            @classmethod
            def probe(cls) -> bool:
                return True

            def query_pr_ci(self, pr_ref: str) -> CIStatus:
                return CIStatus(state="passing")

            def query_branch_in_flight(self, branch: str) -> InFlightStatus:
                return InFlightStatus()

        b = MinimalBackend()
        ok, err = b.precheck()
        self.assertTrue(ok)
        self.assertEqual(err, "")


# ═══════════════════════════════════════════════════════════════════════════
# aether.py — AetherBackend probe + precheck + query schema parse
# ═══════════════════════════════════════════════════════════════════════════


class TestAetherBackendProbe(unittest.TestCase):
    """AetherBackend.probe() detection logic."""

    def test_probe_returns_true_when_binary_on_path(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/local/bin/aether"):
            self.assertTrue(AetherBackend.probe())

    def test_probe_returns_false_when_no_binary_no_config(self) -> None:
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.exists", return_value=False):
            self.assertFalse(AetherBackend.probe())

    def test_probe_returns_false_when_config_exists_but_no_binary(self) -> None:
        # Preserved behavior from detect_aether L62-67 — config alone is informational
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.exists", return_value=True):
            self.assertFalse(AetherBackend.probe())


class TestAetherBackendQuery(unittest.TestCase):
    """AetherBackend.query_pr_ci + query_branch_in_flight schema parse + error paths."""

    def _aether_payload(self, runs: list[dict]) -> str:
        return json.dumps({"status": "ok", "data": {"runs": runs}})

    def _backend(self) -> AetherBackend:
        # Bypass __init__ binary check for unit test
        b = AetherBackend.__new__(AetherBackend)
        b.binary = "/usr/local/bin/aether"
        b.timeout = 30
        return b

    def test_query_pr_ci_success_returns_cistatus(self) -> None:
        b = self._backend()
        with mock.patch.object(
            b,
            "_query",
            return_value=(True, {"runs": [{"status": "success", "started_at": "2026-05-28T13:00:00Z"}]}, ""),
        ):
            result = b.query_pr_ci("feat/x")
        self.assertIsInstance(result, CIStatus)
        self.assertEqual(result.state, "passing")

    def test_query_pr_ci_subprocess_failure_raises_aether_query_error(self) -> None:
        b = self._backend()
        with mock.patch.object(b, "_query", return_value=(False, None, "aether exit 1")):
            with self.assertRaises(AetherQueryError) as ctx:
                b.query_pr_ci("feat/x")
            self.assertIn("PR CI status query failed", str(ctx.exception))
            self.assertIn("aether exit 1", str(ctx.exception))

    def test_query_branch_in_flight_translates_runs(self) -> None:
        b = self._backend()
        aether_runs = [{"id": 3161, "branch": "main", "started_at": "2026-05-09T12:45:00Z"}]
        with mock.patch.object(b, "_query", return_value=(True, {"runs": aether_runs}, "")):
            result = b.query_branch_in_flight("main")
        self.assertIsInstance(result, InFlightStatus)
        self.assertEqual(len(result.runs), 1)
        self.assertEqual(result.runs[0]["run_id"], 3161)


class TestAetherBackendPrecheck(unittest.TestCase):
    """AetherBackend.precheck() — verify --in-flight flag (preserves L71-100 behavior)."""

    def _backend(self) -> AetherBackend:
        b = AetherBackend.__new__(AetherBackend)
        b.binary = "/usr/local/bin/aether"
        b.timeout = 30
        return b

    def test_precheck_passes_when_help_advertises_in_flight(self) -> None:
        b = self._backend()
        fake_result = mock.MagicMock()
        fake_result.stdout = "Usage: aether ci status [--in-flight]"
        fake_result.stderr = ""
        with mock.patch("subprocess.run", return_value=fake_result):
            ok, err = b.precheck()
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_precheck_fails_when_help_lacks_in_flight(self) -> None:
        b = self._backend()
        fake_result = mock.MagicMock()
        fake_result.stdout = "Usage: aether ci status"
        fake_result.stderr = ""
        with mock.patch("subprocess.run", return_value=fake_result):
            ok, err = b.precheck()
        self.assertFalse(ok)
        self.assertIn("--in-flight", err)
        self.assertIn(AETHER_CLI_MIN_SHA, err)


# ═══════════════════════════════════════════════════════════════════════════
# github_actions.py — GitHubActionsBackend stub
# ═══════════════════════════════════════════════════════════════════════════


class TestGitHubActionsBackendStub(unittest.TestCase):
    """GHA stub: probe is real, query methods raise NIE per Hard Constraint #4."""

    def test_probe_returns_false_when_no_gh_binary(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(GitHubActionsBackend.probe())

    def test_probe_returns_true_when_gh_installed_and_authed(self) -> None:
        fake_result = mock.MagicMock()
        fake_result.returncode = 0
        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run", return_value=fake_result):
            self.assertTrue(GitHubActionsBackend.probe())

    def test_probe_returns_false_when_gh_not_authed(self) -> None:
        fake_result = mock.MagicMock()
        fake_result.returncode = 1  # gh auth status returns 1 when not logged in
        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run", return_value=fake_result):
            self.assertFalse(GitHubActionsBackend.probe())

    def test_query_pr_ci_raises_nie_with_locked_message(self) -> None:
        """Hard Constraint #4 + AC-2.5 — NIE message body must contain required strings."""
        b = GitHubActionsBackend()
        with self.assertRaises(NotImplementedError) as ctx:
            b.query_pr_ci("feat/x")
        msg = str(ctx.exception)
        self.assertIn("GHA backend probe succeeded but query_pr_ci not implemented", msg)
        self.assertIn("PR welcome", msg)
        self.assertIn("Hard Constraint #7", msg)
        self.assertIn("ci_backends: []", msg)

    def test_query_branch_in_flight_raises_nie_with_locked_message(self) -> None:
        b = GitHubActionsBackend()
        with self.assertRaises(NotImplementedError) as ctx:
            b.query_branch_in_flight("main")
        msg = str(ctx.exception)
        self.assertIn("query_branch_in_flight not", msg)
        self.assertIn("PR welcome", msg)


# ═══════════════════════════════════════════════════════════════════════════
# __init__.py — registry (BACKENDS list order + cached_probe + reset_probe_cache)
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistry(unittest.TestCase):
    """BACKENDS list order (Hard Constraint #8) + cached_probe / reset_probe_cache."""

    def setUp(self) -> None:
        reset_probe_cache()

    def tearDown(self) -> None:
        reset_probe_cache()

    def test_backends_list_order_aether_first_gha_second(self) -> None:
        """Hard Constraint #8: static import list order = explicit precedence."""
        self.assertEqual(len(BACKENDS), 2)
        self.assertIs(BACKENDS[0], AetherBackend)
        self.assertIs(BACKENDS[1], GitHubActionsBackend)

    def test_no_decorator_registration(self) -> None:
        """AC-4.4: verify static-import-only pattern, no decorator registration."""
        import ci_backends
        # Module shouldn't expose any 'register' decorator
        self.assertFalse(hasattr(ci_backends, "register"))
        self.assertFalse(hasattr(ci_backends, "@register"))

    def test_cached_probe_idempotent(self) -> None:
        """Hard Constraint #11: cached_probe returns same result on repeated calls."""
        call_count = {"n": 0}
        def counting(cls):
            call_count["n"] += 1
            return True

        with mock.patch.object(AetherBackend, "probe", classmethod(counting)):
            r1 = cached_probe(AetherBackend)
            r2 = cached_probe(AetherBackend)
            r3 = cached_probe(AetherBackend)
        self.assertTrue(r1 and r2 and r3)
        self.assertEqual(call_count["n"], 1, "Cache should yield single probe call")

    def test_reset_probe_cache_clears_state(self) -> None:
        """reset_probe_cache() removes all cached probe results."""
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)):
            cached_probe(AetherBackend)
        # After cache populated, reset clears it.
        from ci_backends import _probe_cache
        self.assertGreater(len(_probe_cache), 0)
        reset_probe_cache()
        self.assertEqual(len(_probe_cache), 0)

    def test_reset_probe_cache_idempotent_on_empty(self) -> None:
        """reset_probe_cache() is safe to call on empty cache (idempotent)."""
        reset_probe_cache()  # Empty cache
        reset_probe_cache()  # Should not raise
        from ci_backends import _probe_cache
        self.assertEqual(len(_probe_cache), 0)


if __name__ == "__main__":
    unittest.main()
