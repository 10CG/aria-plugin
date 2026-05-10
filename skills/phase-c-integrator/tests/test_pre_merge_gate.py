"""Tests for pre_merge_gate.py (Phase C.2.4).

Covers Spec T4.2 cases (a)-(f) plus enabled/no_aether fallback paths.
Uses unittest.mock to stub subprocess + detection functions; no real
aether calls are made.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

# Add scripts/ to path for direct module import.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import pre_merge_gate as gate  # noqa: E402


def _aether_payload(runs: list[dict]) -> str:
    return json.dumps(
        {
            "status": "ok",
            "data": {"filters": {}, "repo": "10CG/Aria", "runs": runs},
        }
    )


class ComputeVerdictTests(unittest.TestCase):
    """Pure function tests — no mocking required."""

    def test_passing_no_in_flight_green(self) -> None:
        self.assertEqual(gate.compute_verdict([], "passing"), gate.VERDICT_GREEN)

    def test_passing_with_in_flight_wait(self) -> None:
        self.assertEqual(
            gate.compute_verdict([{"run_id": 1}], "passing"), gate.VERDICT_WAIT
        )

    def test_failing_routes_fail(self) -> None:
        # PR failing always wins, regardless of main in-flight state.
        self.assertEqual(gate.compute_verdict([], "failing"), gate.VERDICT_FAIL)
        self.assertEqual(
            gate.compute_verdict([{"run_id": 1}], "failing"), gate.VERDICT_FAIL
        )

    def test_pending_routes_wait(self) -> None:
        self.assertEqual(gate.compute_verdict([], "pending"), gate.VERDICT_WAIT)


class TranslateInFlightRunTests(unittest.TestCase):
    def test_iso_8601_started_at_parsed(self) -> None:
        run = {
            "id": 3161,
            "branch": "main",
            "started_at": "2026-05-09T12:45:00Z",
        }
        out = gate._translate_in_flight_run(run)
        self.assertEqual(out["run_id"], 3161)
        self.assertEqual(out["branch"], "main")
        self.assertEqual(out["started_at"], "2026-05-09T12:45:00Z")
        # elapsed_seconds is non-negative integer (depends on wall clock).
        self.assertIsInstance(out["elapsed_seconds"], int)
        self.assertGreaterEqual(out["elapsed_seconds"], 0)

    def test_malformed_started_at_falls_back_to_zero(self) -> None:
        run = {"id": 1, "branch": "main", "started_at": "not-a-date"}
        out = gate._translate_in_flight_run(run)
        self.assertEqual(out["elapsed_seconds"], 0)

    def test_missing_fields_default_safe(self) -> None:
        out = gate._translate_in_flight_run({})
        self.assertEqual(out["run_id"], 0)
        self.assertEqual(out["branch"], "")
        self.assertEqual(out["started_at"], "")


class GateCheckTests(unittest.TestCase):
    """End-to-end gate_check with mocked subprocess + detection."""

    def _mock_query(
        self,
        main_runs: list[dict],
        pr_runs: list[dict],
    ):
        """Build a side_effect that returns main_runs first, pr_runs second."""

        def fake_query(binary, branch, in_flight_only, timeout):
            if in_flight_only:
                return True, {"runs": main_runs}, ""
            return True, {"runs": pr_runs}, ""

        return fake_query

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_a_green(self, m_query, *_unused) -> None:
        # main 无 in-flight + PR CI passing
        m_query.side_effect = self._mock_query(
            main_runs=[],
            pr_runs=[{"status": "success"}],
        )
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["pr_ci_status"], "passing")
        self.assertEqual(out["in_flight_runs"], [])
        self.assertEqual(out["primitive_used"], "aether-ci-cli")

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_b_wait_with_translated_runs(self, m_query, *_unused) -> None:
        # main 有 in-flight + PR CI passing → verdict=wait + in_flight_runs[] translated
        m_query.side_effect = self._mock_query(
            main_runs=[
                {"id": 3161, "branch": "main", "started_at": "2026-05-09T12:45:00Z"},
            ],
            pr_runs=[{"status": "success"}],
        )
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "wait")
        self.assertEqual(out["pr_ci_status"], "passing")
        self.assertEqual(len(out["in_flight_runs"]), 1)
        translated = out["in_flight_runs"][0]
        self.assertEqual(translated["run_id"], 3161)
        self.assertEqual(translated["branch"], "main")
        self.assertEqual(translated["started_at"], "2026-05-09T12:45:00Z")
        self.assertIn("elapsed_seconds", translated)

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_c_failing_routes_fail_regardless_of_main(self, m_query, *_unused) -> None:
        # PR CI failing → verdict=fail (无论 main in-flight)
        m_query.side_effect = self._mock_query(
            main_runs=[{"id": 1, "branch": "main", "started_at": "2026-05-09T12:00:00Z"}],
            pr_runs=[{"status": "failure"}],
        )
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertEqual(out["pr_ci_status"], "failing")

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_d_pending_routes_wait(self, m_query, *_unused) -> None:
        # PR CI pending → verdict=wait
        m_query.side_effect = self._mock_query(
            main_runs=[],
            pr_runs=[{"status": "running"}],  # unknown status → pending
        )
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "wait")
        self.assertEqual(out["pr_ci_status"], "pending")

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_e_malformed_aether_main_leg_routes_fail(self, m_query, *_unused) -> None:
        # primitive 异常 (main leg first) → fail verdict + raw_message 含错误信息
        m_query.side_effect = [
            (False, None, "malformed JSON from aether: line 1 col 1"),
        ]
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("malformed", out["raw_message"])
        self.assertEqual(out["pr_ci_status"], "pending")
        self.assertIn("main in-flight query failed", out["raw_message"])

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=True)
    @mock.patch.object(gate, "_query_aether")
    def test_case_e2_malformed_aether_pr_leg_routes_fail(self, m_query, *_unused) -> None:
        """R2 patch (CR-M2): cover the PR-leg failure path.

        Without this test, test_case_e exits early on the first _query_aether
        call (main-leg failure) and never reaches the second call. This test
        succeeds the main leg then fails the PR leg, exercising the second
        `if not pr_ok` branch in gate_check.
        """
        m_query.side_effect = [
            (True, {"runs": []}, ""),  # main leg succeeds
            (False, None, "PR query timed out"),  # PR leg fails
        ]
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("PR CI status query failed", out["raw_message"])
        self.assertIn("PR query timed out", out["raw_message"])

    @mock.patch.object(gate, "detect_aether", return_value=(True, "/usr/local/bin/aether"))
    @mock.patch.object(gate, "verify_aether_in_flight_flag", return_value=False)
    def test_case_f_outdated_binary_fails_fast(self, *_unused) -> None:
        # aether --help 无 --in-flight → fail-fast + 提示升级
        out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("--in-flight", out["raw_message"])
        self.assertIn(gate.AETHER_CLI_MIN_SHA, out["raw_message"])


class FallbackTests(unittest.TestCase):
    @mock.patch.object(gate, "detect_aether")
    def test_disabled_skips_to_green(self, m_detect) -> None:
        out = gate.gate_check(pr_branch="feat/x", config={"enabled": False})
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["primitive_used"], "manual")
        # raw_message is the string "pre_merge_gate.enabled=false; gate skipped".
        self.assertIn("enabled=false", out["raw_message"])
        self.assertIn("skipped", out["raw_message"])
        # Detection should not be attempted when disabled.
        m_detect.assert_not_called()

    @mock.patch.object(gate, "detect_aether", return_value=(False, None))
    def test_no_aether_skip_with_warning(self, *_unused) -> None:
        out = gate.gate_check(
            pr_branch="feat/x",
            config={"no_aether_fallback": "skip_with_warning"},
        )
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["primitive_used"], "manual")
        self.assertIn("not available", out["raw_message"])

    @mock.patch.object(gate, "detect_aether", return_value=(False, None))
    def test_no_aether_abort(self, *_unused) -> None:
        out = gate.gate_check(
            pr_branch="feat/x",
            config={"no_aether_fallback": "abort"},
        )
        self.assertEqual(out["verdict"], "fail")
        self.assertIn("not available", out["raw_message"])


class NormalizePrCiStatusTests(unittest.TestCase):
    def test_known_pass_statuses(self) -> None:
        for s in ("success", "passing", "passed", "completed"):
            self.assertEqual(gate._normalize_pr_ci_status([{"status": s}]), "passing")

    def test_known_fail_statuses(self) -> None:
        for s in ("failure", "failing", "failed", "error", "cancelled"):
            self.assertEqual(gate._normalize_pr_ci_status([{"status": s}]), "failing")

    def test_unknown_status_defaults_pending(self) -> None:
        self.assertEqual(gate._normalize_pr_ci_status([{"status": "running"}]), "pending")
        self.assertEqual(gate._normalize_pr_ci_status([{}]), "pending")

    def test_empty_runs_pending(self) -> None:
        self.assertEqual(gate._normalize_pr_ci_status([]), "pending")


if __name__ == "__main__":
    unittest.main()
