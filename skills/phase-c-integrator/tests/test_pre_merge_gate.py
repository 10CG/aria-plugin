"""Tests for pre_merge_gate.py (Phase C.2.4) — v1.31.0+ CI backend abstraction.

Covers original Spec T4.2 cases (a)-(f) plus enabled/fallback paths, refactored
to mock the new ci_backends layer (AetherBackend / GitHubActionsBackend) instead
of the removed module-level helpers (detect_aether / verify_aether_in_flight_flag
/ _query_aether). 21 existing test methods preserved with semantic-equivalent
assertions; 16 new test methods added for v1.31.0 contract (Hard Constraints
#3 #7 #8 #9 #10 #11 + AC-2 AC-3 AC-4 AC-5).

Uses unittest.mock to stub backend methods; no real aether/gh calls are made.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import warnings
from unittest import mock

# Add scripts/ to path for direct module import.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import pre_merge_gate as gate  # noqa: E402
from ci_backends import (  # noqa: E402
    AetherBackend,
    AetherQueryError,
    CIStatus,
    GitHubActionsBackend,
    InFlightStatus,
    cached_probe,
    reset_probe_cache,
)
from ci_backends.aether import AETHER_CLI_MIN_SHA  # noqa: E402


def _aether_payload(runs: list[dict]) -> str:
    return json.dumps(
        {
            "status": "ok",
            "data": {"filters": {}, "repo": "10CG/Aria", "runs": runs},
        }
    )


class _ProbeCacheResetMixin:
    """Mixin: reset probe cache before and after each test for isolation
    (Hard Constraint #11 Option B + AC-7 test isolation).
    """

    def setUp(self) -> None:  # type: ignore[override]
        super().setUp()
        reset_probe_cache()

    def tearDown(self) -> None:  # type: ignore[override]
        reset_probe_cache()
        super().tearDown()


# ═══════════════════════════════════════════════════════════════════════════
# ComputeVerdictTests (4 methods) — preserved from v1.30.0 with new dict
# signature (Hard Constraint #10).
# ═══════════════════════════════════════════════════════════════════════════


class ComputeVerdictTests(unittest.TestCase):
    """Pure function tests — no mocking required.

    Signature change v1.31.0+ (Hard Constraint #10): compute_verdict now
    returns a full output dict (was: returned str). Tests extract verdict via
    `out["verdict"]`. backend_name defaults to "aether-ci-cli" preserving
    backward-compat behavior for old code paths.
    """

    def test_passing_no_in_flight_green(self) -> None:
        out = gate.compute_verdict([], "passing")
        self.assertEqual(out["verdict"], gate.VERDICT_GREEN)
        self.assertEqual(out["primitive_used"], "aether-ci-cli")  # default backend_name
        self.assertEqual(out["primitive_version_sha"], AETHER_CLI_MIN_SHA)

    def test_passing_with_in_flight_wait(self) -> None:
        out = gate.compute_verdict([{"run_id": 1}], "passing")
        self.assertEqual(out["verdict"], gate.VERDICT_WAIT)

    def test_failing_routes_fail(self) -> None:
        # PR failing always wins, regardless of main in-flight state.
        self.assertEqual(gate.compute_verdict([], "failing")["verdict"], gate.VERDICT_FAIL)
        self.assertEqual(
            gate.compute_verdict([{"run_id": 1}], "failing")["verdict"], gate.VERDICT_FAIL
        )

    def test_pending_routes_wait(self) -> None:
        self.assertEqual(gate.compute_verdict([], "pending")["verdict"], gate.VERDICT_WAIT)


# ═══════════════════════════════════════════════════════════════════════════
# TranslateInFlightRunTests (3 methods) — moved to AetherBackend (Rev1 §A.2
# responsibility table).
# ═══════════════════════════════════════════════════════════════════════════


class TranslateInFlightRunTests(unittest.TestCase):
    """Migrated from pre_merge_gate._translate_in_flight_run to AetherBackend._translate_in_flight_run (staticmethod)."""

    def test_iso_8601_started_at_parsed(self) -> None:
        run = {
            "id": 3161,
            "branch": "main",
            "started_at": "2026-05-09T12:45:00Z",
        }
        out = AetherBackend._translate_in_flight_run(run)
        self.assertEqual(out["run_id"], 3161)
        self.assertEqual(out["branch"], "main")
        self.assertEqual(out["started_at"], "2026-05-09T12:45:00Z")
        self.assertIsInstance(out["elapsed_seconds"], int)
        self.assertGreaterEqual(out["elapsed_seconds"], 0)

    def test_malformed_started_at_falls_back_to_zero(self) -> None:
        run = {"id": 1, "branch": "main", "started_at": "not-a-date"}
        out = AetherBackend._translate_in_flight_run(run)
        self.assertEqual(out["elapsed_seconds"], 0)

    def test_missing_fields_default_safe(self) -> None:
        out = AetherBackend._translate_in_flight_run({})
        self.assertEqual(out["run_id"], 0)
        self.assertEqual(out["branch"], "")
        self.assertEqual(out["started_at"], "")


# ═══════════════════════════════════════════════════════════════════════════
# GateCheckTests (7 methods) — mocks AetherBackend instead of detect_aether
# helpers. Preserves all 7 case names from v1.30.0.
# ═══════════════════════════════════════════════════════════════════════════


class GateCheckTests(_ProbeCacheResetMixin, unittest.TestCase):
    """End-to-end gate_check with mocked AetherBackend.

    Mock target collapse (R1 substance convergence M-1):
      old `detect_aether`           → `AetherBackend.probe` (classmethod patch)
      old `verify_aether_in_flight_flag` → `AetherBackend.precheck` (returns (True, ""))
      old `_query_aether`           → `AetherBackend.query_pr_ci` + `.query_branch_in_flight`
    """

    def _make_aether_backend_mock(
        self,
        main_runs: list[dict] | None = None,
        pr_state: str = "passing",
        precheck: tuple[bool, str] = (True, ""),
    ):
        """Build a mock AetherBackend instance returning specified states."""
        mock_backend = mock.MagicMock(spec=AetherBackend)
        mock_backend.name = "aether-ci-cli"
        mock_backend.precheck.return_value = precheck
        mock_backend.query_branch_in_flight.return_value = InFlightStatus(
            runs=main_runs or [],
            checked_at="2026-05-28T13:00:00Z",
        )
        mock_backend.query_pr_ci.return_value = CIStatus(
            state=pr_state,
            checked_at="2026-05-28T13:00:00Z",
        )
        return mock_backend

    def test_case_a_green(self) -> None:
        # main 无 in-flight + PR CI passing
        mock_backend = self._make_aether_backend_mock(main_runs=[], pr_state="passing")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["pr_ci_status"], "passing")
        self.assertEqual(out["in_flight_runs"], [])
        self.assertEqual(out["primitive_used"], "aether-ci-cli")

    def test_case_b_wait_with_translated_runs(self) -> None:
        # main 有 in-flight + PR CI passing → verdict=wait + in_flight_runs[] translated
        translated_run = {
            "run_id": 3161,
            "branch": "main",
            "started_at": "2026-05-09T12:45:00Z",
            "elapsed_seconds": 999,
        }
        mock_backend = self._make_aether_backend_mock(
            main_runs=[translated_run], pr_state="passing"
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "wait")
        self.assertEqual(out["pr_ci_status"], "passing")
        self.assertEqual(len(out["in_flight_runs"]), 1)
        self.assertEqual(out["in_flight_runs"][0]["run_id"], 3161)
        self.assertEqual(out["in_flight_runs"][0]["branch"], "main")
        self.assertEqual(out["in_flight_runs"][0]["started_at"], "2026-05-09T12:45:00Z")
        self.assertIn("elapsed_seconds", out["in_flight_runs"][0])

    def test_case_c_failing_routes_fail_regardless_of_main(self) -> None:
        # PR CI failing → verdict=fail (无论 main in-flight)
        mock_backend = self._make_aether_backend_mock(
            main_runs=[{"run_id": 1, "branch": "main", "started_at": "2026-05-09T12:00:00Z", "elapsed_seconds": 100}],
            pr_state="failing",
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertEqual(out["pr_ci_status"], "failing")

    def test_case_d_pending_routes_wait(self) -> None:
        # PR CI pending → verdict=wait
        mock_backend = self._make_aether_backend_mock(main_runs=[], pr_state="pending")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "wait")
        self.assertEqual(out["pr_ci_status"], "pending")

    def test_case_e_malformed_aether_main_leg_routes_fail(self) -> None:
        # primitive 异常 (main leg first) → fail verdict + raw_message 含错误信息
        mock_backend = mock.MagicMock(spec=AetherBackend)
        mock_backend.name = "aether-ci-cli"
        mock_backend.precheck.return_value = (True, "")
        mock_backend.query_branch_in_flight.side_effect = AetherQueryError(
            "main in-flight query failed: malformed JSON from aether: line 1 col 1"
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("malformed", out["raw_message"])
        self.assertEqual(out["pr_ci_status"], "pending")
        self.assertIn("main in-flight query failed", out["raw_message"])

    def test_case_e2_malformed_aether_pr_leg_routes_fail(self) -> None:
        """R2 patch (CR-M2): cover the PR-leg failure path.

        With Rev1.1 order (main in-flight FIRST then PR), main leg succeeds
        then PR leg fails.
        """
        mock_backend = mock.MagicMock(spec=AetherBackend)
        mock_backend.name = "aether-ci-cli"
        mock_backend.precheck.return_value = (True, "")
        mock_backend.query_branch_in_flight.return_value = InFlightStatus(runs=[])
        mock_backend.query_pr_ci.side_effect = AetherQueryError(
            "PR CI status query failed: PR query timed out"
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("PR CI status query failed", out["raw_message"])
        self.assertIn("PR query timed out", out["raw_message"])

    def test_case_f_outdated_binary_fails_fast(self) -> None:
        # aether --help 无 --in-flight (precheck fails) → fail-fast + 提示升级
        mock_backend = mock.MagicMock(spec=AetherBackend)
        mock_backend.name = "aether-ci-cli"
        mock_backend.precheck.return_value = (
            False,
            f"aether binary at /usr/local/bin/aether lacks --in-flight flag; "
            f"upgrade to aether-cli >= commit {AETHER_CLI_MIN_SHA} (2026-05-06)",
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("--in-flight", out["raw_message"])
        self.assertIn(AETHER_CLI_MIN_SHA, out["raw_message"])
        # query_* should NOT be called when precheck fails.
        mock_backend.query_branch_in_flight.assert_not_called()
        mock_backend.query_pr_ci.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# FallbackTests (3 methods) — backend-agnostic naming (no_ci_fallback).
# Old config key `no_aether_fallback` still works via alias (covered by
# TestAliasKeyPath below).
# ═══════════════════════════════════════════════════════════════════════════


class FallbackTests(_ProbeCacheResetMixin, unittest.TestCase):
    def test_disabled_skips_to_green(self) -> None:
        with mock.patch.object(gate, "resolve_ci_backend") as m_resolve:
            out = gate.gate_check(pr_branch="feat/x", config={"enabled": False})
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["primitive_used"], "manual")
        self.assertIn("enabled=false", out["raw_message"])
        self.assertIn("skipped", out["raw_message"])
        # Backend resolution should not be attempted when disabled.
        m_resolve.assert_not_called()

    def test_no_backend_skip_with_warning(self) -> None:
        with mock.patch.object(gate, "resolve_ci_backend", return_value=None):
            out = gate.gate_check(
                pr_branch="feat/x",
                config={"no_ci_fallback": "skip_with_warning"},
            )
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["primitive_used"], "manual")
        self.assertIn("no CI backend available", out["raw_message"])

    def test_no_backend_abort(self) -> None:
        with mock.patch.object(gate, "resolve_ci_backend", return_value=None):
            out = gate.gate_check(
                pr_branch="feat/x",
                config={"no_ci_fallback": "abort"},
            )
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("no CI backend available", out["raw_message"])


# ═══════════════════════════════════════════════════════════════════════════
# NormalizePrCiStatusTests (4 methods) — moved to AetherBackend (Rev1 §A.2).
# ═══════════════════════════════════════════════════════════════════════════


class NormalizePrCiStatusTests(unittest.TestCase):
    """Migrated from pre_merge_gate._normalize_pr_ci_status to AetherBackend._normalize_pr_ci_status (staticmethod)."""

    def test_known_pass_statuses(self) -> None:
        for s in ("success", "passing", "passed", "completed"):
            self.assertEqual(AetherBackend._normalize_pr_ci_status([{"status": s}]), "passing")

    def test_known_fail_statuses(self) -> None:
        for s in ("failure", "failing", "failed", "error", "cancelled"):
            self.assertEqual(AetherBackend._normalize_pr_ci_status([{"status": s}]), "failing")

    def test_unknown_status_defaults_pending(self) -> None:
        self.assertEqual(AetherBackend._normalize_pr_ci_status([{"status": "running"}]), "pending")
        self.assertEqual(AetherBackend._normalize_pr_ci_status([{}]), "pending")

    def test_empty_runs_pending(self) -> None:
        self.assertEqual(AetherBackend._normalize_pr_ci_status([]), "pending")


# ═══════════════════════════════════════════════════════════════════════════
# NEW Test Classes (v1.31.0+ — Hard Constraints #3 #7 #8 #9 #10 #11)
# Per tasks.md T-tests 3.7-3.14.
# ═══════════════════════════════════════════════════════════════════════════


class TestGHAStubAbortNotSkip(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #7 — GHA stub NIE MUST propagate (abort), NOT route to no_ci_fallback.

    Critical safety: if `gh` is installed but project uses Aether, GHA stub probe
    succeeds and query raises NIE. If NIE were caught and routed to skip_with_warning,
    Rule #8 mechanism would be silently downgraded.
    """

    def test_gha_query_pr_ci_nie_propagates(self) -> None:
        # AC-2.5: NIE message body assertion (R1 tech F-01 Critical fix)
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: False)), \
             mock.patch.object(GitHubActionsBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            with self.assertRaises(NotImplementedError) as ctx:
                gate.gate_check(pr_branch="feat/x")
            msg = str(ctx.exception)
            self.assertIn("GHA backend probe succeeded but", msg)
            self.assertIn("PR welcome", msg)

    def test_gha_query_branch_in_flight_nie_propagates(self) -> None:
        # Force backend instantiation with GHA only (test query_branch_in_flight is called first per Rev1.1 order)
        mock_backend = GitHubActionsBackend()
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            with self.assertRaises(NotImplementedError) as ctx:
                gate.gate_check(pr_branch="feat/x")
            msg = str(ctx.exception)
            # query_branch_in_flight is called first per Rev1.1 query order
            self.assertIn("query_branch_in_flight", msg)
            self.assertIn("PR welcome", msg)

    def test_gha_nie_not_caught_by_no_ci_fallback(self) -> None:
        # Even with no_ci_fallback=skip_with_warning, NIE must NOT be silently caught.
        mock_backend = GitHubActionsBackend()
        with mock.patch.object(gate, "resolve_ci_backend", return_value=mock_backend):
            with self.assertRaises(NotImplementedError):
                gate.gate_check(
                    pr_branch="feat/x",
                    config={"no_ci_fallback": "skip_with_warning"},
                )


class TestAliasKeyPath(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #3 — old config keys still work with deprecation warning.

    AC-3.4: deprecation warning string MUST contain exact expected text (prevents
    silent rot if message wording drifts).
    """

    def test_old_key_no_aether_fallback_translated(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = gate._normalize_config({"no_aether_fallback": "abort"})
        self.assertEqual(cfg.get("no_ci_fallback"), "abort")
        self.assertNotIn("no_aether_fallback", cfg)
        self.assertEqual(len(w), 1)
        self.assertTrue(issubclass(w[0].category, DeprecationWarning))
        # AC-3.4 message body assertion
        msg = str(w[0].message)
        self.assertIn("`no_aether_fallback` is deprecated", msg)
        self.assertIn("use `no_ci_fallback`", msg)
        self.assertIn("will be removed in v2.0", msg)

    def test_old_key_primitive_preference_translated_with_value_reshape(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = gate._normalize_config({"primitive_preference": ["aether-ci-cli", "foo"]})
        self.assertEqual(cfg.get("ci_backends"), [{"name": "aether-ci-cli"}, {"name": "foo"}])
        self.assertNotIn("primitive_preference", cfg)
        self.assertEqual(len(w), 1)
        msg = str(w[0].message)
        self.assertIn("`primitive_preference` is deprecated", msg)
        self.assertIn("use `ci_backends`", msg)
        self.assertIn("will be removed in v2.0", msg)

    def test_old_key_primitive_preference_empty_list_preserves_disable(self) -> None:
        """Edge case: old primitive_preference=[] should translate to ci_backends=[]
        preserving the explicit-disable semantic per Rev1 _translate_value comment."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            cfg = gate._normalize_config({"primitive_preference": []})
        self.assertEqual(cfg.get("ci_backends"), [])


class TestBothKeysPresentNewWins(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #9 — when old + new keys both present, new wins."""

    def test_both_keys_new_wins(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = gate._normalize_config({
                "no_aether_fallback": "abort",  # old
                "no_ci_fallback": "skip_with_warning",  # new
            })
        self.assertEqual(cfg.get("no_ci_fallback"), "skip_with_warning")
        self.assertNotIn("no_aether_fallback", cfg)
        # Warning should mention both_keys_present
        both_present_warnings = [wi for wi in w if "both_keys_present" in str(wi.message)]
        self.assertEqual(len(both_present_warnings), 1)
        msg = str(both_present_warnings[0].message)
        self.assertIn("ignoring `no_aether_fallback`", msg)
        self.assertIn("using `no_ci_fallback`", msg)


class TestBackendRegistry(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #8 + AC-4 — static registry, list-order precedence."""

    def test_missing_ci_backends_auto_detects(self) -> None:
        # Default config (no ci_backends key) → auto-detect via BACKENDS order
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            backend = gate.resolve_ci_backend({})
        self.assertIsInstance(backend, AetherBackend)

    def test_explicit_empty_ci_backends_disables(self) -> None:
        # AC-4.5: [] = explicit disable (returns None even if Aether is installed)
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            backend = gate.resolve_ci_backend({"ci_backends": []})
        self.assertIsNone(backend)

    def test_explicit_config_order_respected(self) -> None:
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)), \
             mock.patch.object(GitHubActionsBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            # User explicit: GHA first
            backend = gate.resolve_ci_backend({
                "ci_backends": [{"name": "github-actions"}, {"name": "aether-ci-cli"}]
            })
        self.assertIsInstance(backend, GitHubActionsBackend)

    def test_unknown_name_skipped(self) -> None:
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            backend = gate.resolve_ci_backend({
                "ci_backends": [{"name": "unknown-backend"}, {"name": "aether-ci-cli"}]
            })
        self.assertIsInstance(backend, AetherBackend)

    def test_aether_takes_precedence_when_both_probe_true(self) -> None:
        # AC-4.3: auto-detect respects BACKENDS list order (Aether first)
        with mock.patch.object(AetherBackend, "probe", classmethod(lambda cls: True)), \
             mock.patch.object(GitHubActionsBackend, "probe", classmethod(lambda cls: True)):
            reset_probe_cache()
            backend = gate.resolve_ci_backend({})  # auto-detect
        self.assertIsInstance(backend, AetherBackend)


class TestNormalizeConfigSequencing(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #9 — alias translation runs BEFORE merge."""

    def test_normalize_user_config_before_default_merge(self) -> None:
        """Hard Constraint #9 sequencing: normalize USER config first, then merge default.

        If normalize ran AFTER merge with DEFAULT_CONFIG, the default's new
        `no_ci_fallback: "skip_with_warning"` would shadow user's translated
        old key value (both-keys-present new-wins would discard user intent).
        Fix: user config is normalized BEFORE merging with default.

        End-to-end verification via gate_check + mocked backend:
        user passes only old `no_aether_fallback: "abort"` → behavior matches
        new `no_ci_fallback: "abort"` (gate FAILs with abort message).
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with mock.patch.object(gate, "resolve_ci_backend", return_value=None):
                out = gate.gate_check(
                    pr_branch="feat/x",
                    config={"no_aether_fallback": "abort"},  # only old key
                )
        # If sequencing were wrong, out["verdict"] would be "green" (default skip).
        # Correct sequencing: user's old key translates first, abort wins.
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("abort", out["raw_message"])

    def test_normalize_idempotent_on_new_keys_only(self) -> None:
        # Calling normalize on a config with only new keys is a no-op (no warning).
        cfg_input = {"no_ci_fallback": "abort", "ci_backends": [{"name": "aether-ci-cli"}]}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg_out = gate._normalize_config(cfg_input)
        # No deprecation warnings since no old keys present
        deprecation_warnings = [wi for wi in w if issubclass(wi.category, DeprecationWarning)]
        self.assertEqual(len(deprecation_warnings), 0)
        # Config unchanged
        self.assertEqual(cfg_out.get("no_ci_fallback"), "abort")
        self.assertEqual(cfg_out.get("ci_backends"), [{"name": "aether-ci-cli"}])


class TestProbeCacheIsolation(_ProbeCacheResetMixin, unittest.TestCase):
    """Hard Constraint #11 — Option B module-level cache + reset_probe_cache().

    Verifies probe is called once per backend per reset cycle (not cached
    across test methods due to setUp/tearDown reset).
    """

    def test_cached_probe_calls_probe_once_within_cycle(self) -> None:
        call_count = {"n": 0}
        def counting_probe(cls):
            call_count["n"] += 1
            return True

        with mock.patch.object(AetherBackend, "probe", classmethod(counting_probe)):
            reset_probe_cache()
            r1 = cached_probe(AetherBackend)
            r2 = cached_probe(AetherBackend)
            r3 = cached_probe(AetherBackend)
        self.assertTrue(r1 and r2 and r3)
        self.assertEqual(call_count["n"], 1, "probe should only be called once due to caching")

    def test_reset_probe_cache_invalidates(self) -> None:
        call_count = {"n": 0}
        def counting_probe(cls):
            call_count["n"] += 1
            return True

        with mock.patch.object(AetherBackend, "probe", classmethod(counting_probe)):
            reset_probe_cache()
            cached_probe(AetherBackend)
            reset_probe_cache()  # invalidate
            cached_probe(AetherBackend)
        self.assertEqual(call_count["n"], 2, "probe should be called twice after reset")


if __name__ == "__main__":
    unittest.main()
