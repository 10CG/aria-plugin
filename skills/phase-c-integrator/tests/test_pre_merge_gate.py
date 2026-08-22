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


# v1.65.0+ (#122): 评估器打桩返回值 — decision=covered 使 gate 走既有查询路径,
# 既有测试语义零变 (SC-11), 且套件运行期间零真实 git 子进程 (SC-22/QA-3)。
_PC_COVERED_STUB = {
    "decision": "covered",
    "workflows_scanned": 1,
    "matched_workflows": [".forgejo/workflows/stub.yml"],
    "changed_files_count": 1,
    "reason": "workflow-trigger-matched",
}


class _ProbeCacheResetMixin:
    """Mixin: reset probe cache before and after each test for isolation
    (Hard Constraint #11 Option B + AC-7 test isolation).

    v1.65.0+ (#122): 同时统一 patch gate.evaluate_path_coverage (QA-3 隔离方法论)
    — 既有测试不因 path_coverage_enabled 默认 true 触发真实 git 子进程 (SC-22)。

    #137: 同一先例原样推广到 gate._verify_main_branch_exists —— 该核验对每次
    gate_check 发一次 `git ls-remote <remote> <branch>`, 实测单次 **8.7 秒**
    (SSH 到远端), 28 处打桩 backend 的既有测试都会走到它 ⇒ 不统一打桩则套件由
    1.6 秒变成分钟级, 且判决随网络可达性漂移。
    ⚠️ 打桩点是**这一处**, ⛔ 不逐条改 28 个测试 (那会把「同一形状散在 28 处」
    这个病复制一遍); 需要验真实核验的测试自行用 self.mb_verify 改返回值或
    stop 掉这个 patcher。

    #152 (TASK-005/006): 同一先例第三次推广到 gate._verify_branch_exists ——
    TASK-006 契约 (spec §2.1) 里 pr_ci_status="not_found" 分支会对 PR 分支再发
    一次 ls-remote 核验, 调用的是**新名** `_verify_branch_exists` (旧名
    `_verify_main_branch_exists` 保留为对新名的位置参数包装, 见
    OldNameWrapperTests)。基线代码里这个新名符号尚不存在 ——
    `create=True` 是必须的, 否则 setUp 里 mock.patch.object 直接抛
    AttributeError, 使整个继承本 mixin 的套件退化成 error 而非 fail (掩盖真实
    红因)。不打桩这一处的测试 (见 OldNameWrapperTests, 它刻意不继承本 mixin)
    会走真实 `git ls-remote`。
    """

    def setUp(self) -> None:  # type: ignore[override]
        super().setUp()
        reset_probe_cache()
        patcher = mock.patch.object(
            gate,
            "evaluate_path_coverage",
            return_value=dict(_PC_COVERED_STUB),
        )
        self.pc_eval = patcher.start()
        self.addCleanup(patcher.stop)
        mb_patcher = mock.patch.object(
            gate, "_verify_main_branch_exists", return_value=("ok", "")
        )
        self.mb_verify = mb_patcher.start()
        self.addCleanup(mb_patcher.stop)
        pr_patcher = mock.patch.object(
            gate, "_verify_branch_exists", return_value=("ok", ""), create=True
        )
        self.pr_verify = pr_patcher.start()
        self.addCleanup(pr_patcher.stop)

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

    def test_empty_runs_not_found(self) -> None:
        """SC-1 (aria-plugin#152): 怎么会红 —— 基线 aether.py :225-226 对空 runs
        返回 "pending"; 新契约要求区分"确实无 run" (not_found) 与"有 run 但状态
        未知" (pending)。"""
        self.assertEqual(AetherBackend._normalize_pr_ci_status([]), "not_found")


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


class PathCoverageGateTests(_ProbeCacheResetMixin, unittest.TestCase):
    """v1.65.0+ (#122) path coverage × gate 集成 — SC-9/10/11/12/13/15/21/22。

    评估器本体的判定逻辑在 test_path_coverage.py; 本类只测 gate 侧接线:
    跳 (a) 的因果机制 (assert_not_called, QA-2) / (b) 轴保留 / NIE 交叉不变量 /
    additive schema / 默认值锁定 / 关闭开关 / 既有套件 git 子进程卫生。
    """

    _NA_STUB = {
        "decision": "not_applicable",
        "workflows_scanned": 1,
        "matched_workflows": [],
        "changed_files_count": 2,
        "reason": "no-triggering-paths",
    }

    _OLD_KEYS = (
        "verdict",
        "pr_ci_status",
        "in_flight_runs",
        "primitive_used",
        "primitive_version_sha",
        "raw_message",
    )

    def _backend(
        self,
        main_runs: list[dict] | None = None,
        pr_state: str = "passing",
    ):
        b = mock.MagicMock(spec=AetherBackend)
        b.name = "aether-ci-cli"
        b.precheck.return_value = (True, "")
        b.query_branch_in_flight.return_value = InFlightStatus(
            runs=main_runs or [], checked_at="2026-07-31T00:00:00Z"
        )
        b.query_pr_ci.return_value = CIStatus(
            state=pr_state, checked_at="2026-07-31T00:00:00Z"
        )
        return b

    def test_sc9_not_applicable_with_inflight_waits_and_skips_pr_query(self) -> None:
        self.pc_eval.return_value = dict(self._NA_STUB)
        run = {"id": 1, "branch": "main", "started_at": "2026-07-31T00:00:00Z"}
        b = self._backend(main_runs=[run])
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "wait")
        self.assertEqual(out["pr_ci_status"], "not_applicable")
        b.query_pr_ci.assert_not_called()  # QA-2: 因果机制本身
        self.assertEqual(out["path_coverage"], self._NA_STUB)

    def test_sc10_not_applicable_clean_green_with_message(self) -> None:
        self.pc_eval.return_value = dict(self._NA_STUB)
        b = self._backend(main_runs=[])
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "green")
        self.assertEqual(out["pr_ci_status"], "not_applicable")
        self.assertTrue(out["raw_message"])  # D8 留痕非空
        self.assertIn("not_applicable", out["raw_message"])
        self.assertIn("no-triggering-paths", out["raw_message"])
        b.query_pr_ci.assert_not_called()
        self.assertEqual(out["path_coverage"], self._NA_STUB)

    def test_sc11_covered_existing_fields_identical_to_disabled(self) -> None:
        # covered (mixin 默认桩) vs 显式关闭 — 既有六键逐字段一致 (additive-only)。
        b1 = self._backend(main_runs=[], pr_state="passing")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b1):
            covered_out = gate.gate_check(pr_branch="feat/x")
        b2 = self._backend(main_runs=[], pr_state="passing")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b2):
            disabled_out = gate.gate_check(
                pr_branch="feat/x",
                config={"path_coverage_enabled": False},
            )
        for key in self._OLD_KEYS:
            self.assertEqual(covered_out[key], disabled_out[key], key)
        self.assertIn("path_coverage", covered_out)
        b1.query_pr_ci.assert_called_once()  # covered → (a) 照常查询

    def test_sc12_default_true_lock(self) -> None:
        # 默认值锁定 (unset → 评估执行): config 不含 path_coverage_enabled。
        b = self._backend()
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            gate.gate_check(pr_branch="feat/x", config={})
        self.pc_eval.assert_called_once_with(
            main_branch="main", pr_branch="feat/x"
        )

    def test_sc13_disabled_no_eval_no_key(self) -> None:
        b = self._backend()
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            out = gate.gate_check(
                pr_branch="feat/x",
                config={"path_coverage_enabled": False},
            )
        self.pc_eval.assert_not_called()
        self.assertNotIn("path_coverage", out)
        self.assertEqual(out["verdict"], "green")

    def test_sc15_schema_additive_and_early_exit_six_keys(self) -> None:
        # not_applicable 输出保留全部既有键。
        self.pc_eval.return_value = dict(self._NA_STUB)
        b = self._backend(main_runs=[])
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            out = gate.gate_check(pr_branch="feat/x")
        for key in self._OLD_KEYS:
            self.assertIn(key, out)
        # backend-query-failure 早退分支不带 path_coverage 键 (BA-6)。
        b2 = self._backend()
        b2.query_branch_in_flight.side_effect = AetherQueryError("boom")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b2):
            fail_out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(fail_out["verdict"], "fail")
        self.assertNotIn("path_coverage", fail_out)

    def test_sc21_nie_propagates_through_b_axis(self) -> None:
        # not_applicable 只免 (a); stub backend NIE 经 (b) 照常 propagate (TL-4)。
        self.pc_eval.return_value = dict(self._NA_STUB)
        b = self._backend()
        b.query_branch_in_flight.side_effect = NotImplementedError(
            "stub backend"
        )
        with mock.patch.object(gate, "resolve_ci_backend", return_value=b):
            with self.assertRaises(NotImplementedError):
                gate.gate_check(pr_branch="feat/x")

    def test_sc22_no_real_git_subprocess_in_suite(self) -> None:
        # 卫生断言 (QA-3): 评估器入口被 mixin 打桩后, 代表性 gate_check 全程
        # 不触发 path_coverage 模块的真实 git 子进程。
        import path_coverage as pc_module

        def _forbidden(*_a, **_k):  # pragma: no cover
            raise AssertionError("real git subprocess spawned in unit suite")

        with mock.patch.object(pc_module.subprocess, "run", _forbidden):
            b = self._backend(main_runs=[], pr_state="passing")
            with mock.patch.object(
                gate, "resolve_ci_backend", return_value=b
            ):
                out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], "green")

    def test_compute_verdict_explicit_not_applicable_branch(self) -> None:
        # BA-8: 显式分支单元级 — in-flight 空/非空两态 + path_coverage 透传。
        out_green = gate.compute_verdict(
            main_in_flight_runs=[],
            pr_ci_status="not_applicable",
            backend_name="aether-ci-cli",
            path_coverage=dict(self._NA_STUB),
        )
        self.assertEqual(out_green["verdict"], "green")
        self.assertTrue(out_green["raw_message"])
        self.assertEqual(out_green["path_coverage"], self._NA_STUB)
        out_wait = gate.compute_verdict(
            main_in_flight_runs=[{"id": 1}],
            pr_ci_status="not_applicable",
            backend_name="aether-ci-cli",
            path_coverage=dict(self._NA_STUB),
        )
        self.assertEqual(out_wait["verdict"], "wait")
        self.assertIn("(b)-axis", out_wait["raw_message"])


# ═══════════════════════════════════════════════════════════════════════════
# #137 — main 分支存在性核验
#
# 症状: 后端结构上无法区分「分支不存在」与「分支没有 in-flight run」, 两者都返
# InFlightStatus(runs=[]) ⇒ 判 green。本项目主干是 master 而 --main-branch 缺省
# "main" ⇒ Rule #8 的这条腿恒真, 等于不存在。
#
# ⛔ 本组**不打桩核验入口 / 不打桩 ls-remote** —— 打了就退化成恒真, 什么都没测。
# 用真实 `git ls-remote` + 受控裸仓。backend 仍打桩 (否则要么依赖本机装没装
# aether, 要么在无 backend 时走 :339 早退, 两种都测不到核验)。
# ═══════════════════════════════════════════════════════════════════════════


def _make_bare_repo(tmpdir: str, name: str, branches: list[str]) -> str:
    """建一个受控裸仓, 只含指定分支。返回其路径。"""
    import subprocess as sp

    work = os.path.join(tmpdir, name + "-work")
    bare = os.path.join(tmpdir, name + ".git")
    os.makedirs(work)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    run = lambda *a, **k: sp.run(a, cwd=work, env=env, check=True,
                                 capture_output=True, **k)
    run("git", "init", "-q")
    with open(os.path.join(work, "f"), "w") as fh:
        fh.write("x")
    run("git", "add", "f")
    run("git", "commit", "-qm", "init")
    first = branches[0]
    run("git", "branch", "-M", first)
    for b in branches[1:]:
        run("git", "branch", b)
    sp.run(["git", "init", "--bare", "-q", bare], check=True, capture_output=True)
    run("git", "remote", "add", "origin", bare)
    for b in branches:
        run("git", "push", "-q", "origin", b)
    return bare


class MainBranchExistenceTests(unittest.TestCase):
    """#137 的承重测试组。真实 ls-remote, 受控裸仓。

    ⚠️ **刻意不继承 `_ProbeCacheResetMixin`** —— 它会统一打桩掉核验入口, 而本组
    要测的正是那个入口。这里自己做隔离: 重置 probe cache + 只打桩 path coverage。
    """

    def setUp(self) -> None:
        import tempfile

        reset_probe_cache()
        self.addCleanup(reset_probe_cache)
        p = mock.patch.object(
            gate, "evaluate_path_coverage", return_value=dict(_PC_COVERED_STUB)
        )
        p.start()
        self.addCleanup(p.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _stub_backend(self, in_flight_runs=None):
        """可解析的 backend —— 使流程越过三道早退真正走到核验。"""
        b = mock.MagicMock()
        b.name = "aether-ci-cli"
        b.probe.return_value = True
        b.precheck.return_value = (True, "")
        b.query_branch_in_flight.return_value = InFlightStatus(
            runs=in_flight_runs or []
        )
        b.query_pr_ci_status.return_value = "success"
        return b

    def _gate(self, remote: str, main_branch: str, backend=None):
        with mock.patch.object(
            gate, "resolve_ci_backend", return_value=backend or self._stub_backend()
        ):
            return gate.gate_check(
                pr_branch="feature/x", main_branch=main_branch, remote=remote
            )

    # --- 承重: bug 本体 ------------------------------------------------------

    def test_absent_main_branch_now_fails_instead_of_green(self):
        """#137 本体: 远端只有 wip/master, 传 master ⇒ 必须 fail, 不得 green。"""
        bare = _make_bare_repo(self._tmp.name, "r", ["wip/master"])
        out = self._gate(bare, "master")
        self.assertEqual(out["verdict"], "fail")
        self.assertEqual(out["gate_error"]["kind"], "main-branch-not-found")
        # raw_message 是主通道, 必须自带分支名与 remote 名 (只写 gate_error 不够)
        self.assertIn("master", out["raw_message"])
        self.assertIn(bare, out["raw_message"])

    def test_zero_hit_returns_rc0_so_exit_code_must_not_be_the_criterion(self):
        """零命中时 ls-remote 仍返 rc=0 —— 读退出码的实现会在这里判 green。"""
        bare = _make_bare_repo(self._tmp.name, "r", ["master"])
        import subprocess as sp
        probe = sp.run(["git", "ls-remote", "--heads", bare, "develop"],
                       capture_output=True)
        self.assertEqual(probe.returncode, 0)          # 前提: rc=0
        self.assertEqual(probe.stdout.strip(), b"")    # 前提: 零行输出
        out = self._gate(bare, "develop")
        self.assertEqual(out["verdict"], "fail")
        self.assertEqual(out["gate_error"]["kind"], "main-branch-not-found")

    def test_glob_pattern_must_not_count_as_a_hit(self):
        """ls-remote 把参数当 glob —— 'mast*' 会命中 master。判据须是精确比对。"""
        bare = _make_bare_repo(self._tmp.name, "r", ["master"])
        for pat in ("mast*", "m[a]ster", "maste?"):
            with self.subTest(pattern=pat):
                out = self._gate(bare, pat)
                self.assertEqual(out["verdict"], "fail", f"{pat} 被当成命中了")
                self.assertEqual(
                    out["gate_error"]["kind"], "main-branch-not-found"
                )

    # --- 负控: 不得改变正常路径判决 -----------------------------------------

    def test_existing_branch_does_not_change_the_verdict(self):
        """分支确实存在时, 核验必须放行, 判决仍由 in-flight 决定 (此处 wait)。"""
        bare = _make_bare_repo(self._tmp.name, "r", ["master"])
        backend = self._stub_backend(
            in_flight_runs=[{"run_id": "1", "branch": "master",
                             "started_at": "", "elapsed_seconds": 1}]
        )
        out = self._gate(bare, "master", backend=backend)
        self.assertEqual(out["verdict"], "wait")
        self.assertNotIn("gate_error", out)

    # --- 核验本身失败 ≠ 分支不存在 ------------------------------------------

    def test_unreachable_remote_is_verify_failed_not_not_found(self):
        """指向不存在路径的 remote ⇒ rc=128 ⇒ 核验失败, 且不得误报成「分支不存在」。"""
        out = self._gate("/tmp/does-not-exist-repo-xyz", "master")
        self.assertEqual(out["verdict"], "fail")
        self.assertEqual(out["gate_error"]["kind"], "main-branch-verify-failed")

    def test_verify_failure_is_not_retried(self):
        """rc!=0 是确定性失败, 重试只是白等 —— 断言只调用一次。"""
        with mock.patch.object(gate.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=128, stdout=b"", stderr=b"boom")
            self._gate("nope", "master")
        self.assertEqual(run.call_count, 1)

    # --- 出口净化: 孤立代理码位不得炸在 json.dumps ---------------------------

    def test_output_survives_strict_encode(self):
        """stderr 含孤立代理码位时, 返回的字符串仍须能过 encode(strict)/json。"""
        with mock.patch.object(gate.subprocess, "run") as run:
            run.return_value = mock.Mock(
                returncode=128, stdout=b"", stderr=b"fatal: \xff\xfe bad"
            )
            out = self._gate("nope", "master")
        out["raw_message"].encode("utf-8", "strict")
        out["gate_error"]["message"].encode("utf-8", "strict")
        json.dumps(out, ensure_ascii=False)

    # --- CLI 接线 ------------------------------------------------------------

    def test_cli_remote_flag_is_actually_wired(self):
        """只加 add_argument 而漏 remote=args.remote 的实现会在这里红。"""
        bare = _make_bare_repo(self._tmp.name, "r", ["wip/master"])
        with mock.patch.object(
            gate, "resolve_ci_backend", return_value=self._stub_backend()
        ), mock.patch.object(
            gate, "evaluate_path_coverage", return_value=dict(_PC_COVERED_STUB)
        ), mock.patch.object(gate.sys.stdout, "write") as w:
            rc = gate.main(["--pr-branch", "feature/x",
                            "--main-branch", "master", "--remote", bare])
        self.assertEqual(rc, 0)
        payload = json.loads("".join(c.args[0] for c in w.call_args_list))
        self.assertEqual(payload["verdict"], "fail")
        self.assertEqual(payload["gate_error"]["kind"], "main-branch-not-found")


# ═══════════════════════════════════════════════════════════════════════════
# NotFoundVerdictTests / ThresholdTests (TASK-002, aria-plugin#152) — RED
# against baseline 9e6a17c. SC-1/SC-2/SC-3/SC-4 —— "no-run-for-branch" 契约:
# pr_ci_status == "not_found" (确实零 run, 区别于 "有 run 但状态未知" 的
# pending) 必须 verdict=wait + 专属 gate_error(kind="no-run-for-branch")。
# 生产实现落在 TASK-003/006 (另一 agent), 本文件只钉规格。
# ═══════════════════════════════════════════════════════════════════════════


class NotFoundVerdictTests(unittest.TestCase):
    """SC-2/SC-4: gate.compute_verdict 对 pr_ci_status="not_found" 的裁决与
    gate_error 载荷契约 (aria-plugin#152)。纯函数测试, 不需 mixin。

    它怎么会红 (SC-2 七档): 基线 compute_verdict 的 if/elif 链没有
    pr_ci_status=="not_found" 分支 (只认 failing/error/pending/not_applicable);
    本组 main_in_flight_runs 均为 [], fallthrough 到 `else: green`。第一条断言
    `verdict == VERDICT_WAIT` 就会红 (AssertionError 'green' != 'wait'), 不是
    AttributeError。
    """

    # 档 A: 命中具名 workflow trigger, 双 matched workflow。
    _PC_A = {
        "decision": "covered",
        "reason": "workflow-trigger-matched",
        "matched_workflows": [
            ".forgejo/workflows/a.yml",
            ".forgejo/workflows/b.yml",
        ],
        "workflows_scanned": 2,
        "changed_files_count": 1,
    }
    # 档 B: workflow 文件本身被改动 (触发规则之外的另一条 covered 理由)。
    _PC_B = {
        "decision": "covered",
        "reason": "workflow-files-changed",
        "matched_workflows": [],
        "workflows_scanned": 2,
        "changed_files_count": 1,
    }
    # 档 C: 空 diff — covered 但没有 "触发匹配" 语义, 不该带 issue 引用。
    _PC_C = {
        "decision": "covered",
        "reason": "empty-diff",
        "matched_workflows": [],
        "changed_files_count": 0,
        "workflows_scanned": 0,
    }
    # 档 D: 评估器本身失败 (git diff 报错) — decision=unknown。
    _PC_D = {
        "decision": "unknown",
        "reason": "git-diff-failed: fatal: bad revision 'main...feat/x'",
        "matched_workflows": [],
        "workflows_scanned": 0,
        "changed_files_count": 0,
    }
    # 档 E: workflow YAML 解析失败 — decision=unknown。
    _PC_E = {
        "decision": "unknown",
        "reason": "workflow-parse-failed: .forgejo/workflows/x.yml",
        "matched_workflows": [],
        "workflows_scanned": 1,
        "changed_files_count": 1,
    }
    # 档 F: 评估器内部异常 — decision=unknown, 且应指引"请报 issue"。
    _PC_F = {
        "decision": "unknown",
        "reason": "internal-error: KeyError: 'on'",
        "matched_workflows": [],
        "workflows_scanned": 0,
        "changed_files_count": 0,
    }

    def _assert_common(self, out: dict) -> None:
        # 断言顺序固定: verdict 先于其余字段 (它是基线红的第一落点)。
        self.assertEqual(out["verdict"], gate.VERDICT_WAIT)
        self.assertEqual(out["pr_ci_status"], "not_found")
        self.assertIn("gate_error", out)
        self.assertEqual(out["gate_error"]["kind"], "no-run-for-branch")
        self.assertEqual(out["gate_error"]["prompt_after_observations"], 3)
        self.assertEqual(out["raw_message"], out["gate_error"]["message"])
        self.assertIn("no-run-for-branch", out["raw_message"])

    def test_sc2_seven_path_coverage_variants(self) -> None:
        """SC-2: 7 档 path_coverage (A-F 各 decision/reason 组合 + G=None) 逐档
        校验通用字段 + 档专属文案。"""
        cases = [
            ("A_trigger_matched", self._PC_A),
            ("B_files_changed", self._PC_B),
            ("C_empty_diff", self._PC_C),
            ("D_git_diff_failed", self._PC_D),
            ("E_workflow_parse_failed", self._PC_E),
            ("F_internal_error", self._PC_F),
            ("G_none", None),
        ]
        for label, pc in cases:
            with self.subTest(case=label):
                out = gate.compute_verdict([], "not_found", cfg=None, path_coverage=pc)
                self._assert_common(out)
                msg = out["raw_message"]
                if label == "A_trigger_matched":
                    self.assertIn("aria-plugin#152", msg)
                    self.assertIn(".forgejo/workflows/a.yml", msg)
                    self.assertIn(".forgejo/workflows/b.yml", msg)
                elif label == "B_files_changed":
                    self.assertIn("aria-plugin#152", msg)
                elif label == "C_empty_diff":
                    self.assertNotIn("#152", msg)
                elif label in (
                    "D_git_diff_failed",
                    "E_workflow_parse_failed",
                    "F_internal_error",
                ):
                    self.assertIn("reason=" + pc["reason"], msg)
                    if label == "F_internal_error":
                        self.assertIn("请报 issue", msg)
                elif label == "G_none":
                    self.assertIn("路径覆盖评估已关闭", msg)

    def test_sc2_trigger_matched_message(self) -> None:
        """具名非参数化用例 (档 A 单独), 供 AB catalog test_case_in_unit_tests
        绑定。断言内容与 test_sc2_seven_path_coverage_variants 的 A 档一致。"""
        out = gate.compute_verdict([], "not_found", cfg=None, path_coverage=self._PC_A)
        self._assert_common(out)
        msg = out["raw_message"]
        self.assertIn("aria-plugin#152", msg)
        self.assertIn(".forgejo/workflows/a.yml", msg)
        self.assertIn(".forgejo/workflows/b.yml", msg)

    def test_sc4_main_in_flight_still_wait_with_kind(self) -> None:
        """SC-4: main in-flight 非空时 verdict 基线已经是 wait (旧 elif
        main_in_flight_runs 分支) —— 它怎么会红: 基线该分支从不构造
        gate_error, `assertIn("gate_error", out)` 处红 (AssertionError),
        不是 verdict 处。"""
        out = gate.compute_verdict([{"run_id": 1}], "not_found")
        self.assertEqual(out["verdict"], gate.VERDICT_WAIT)
        self.assertIn("gate_error", out)
        self.assertEqual(out["gate_error"]["kind"], "no-run-for-branch")


class ThresholdTests(unittest.TestCase):
    """SC-3: gate._effective_prompt_threshold 契约 (aria-plugin#152)。

    它怎么会红: 基线模块没有 `_effective_prompt_threshold` 符号 —— 调用处
    AttributeError (符合规格「基线 AttributeError 属预期红」), 非收集期错误
    (符号只在测试方法体内被访问)。
    """

    def test_default_none_is_3(self) -> None:
        self.assertEqual(gate._effective_prompt_threshold(None), 3)

    def test_explicit_value_respected(self) -> None:
        self.assertEqual(
            gate._effective_prompt_threshold({"no_run_prompt_after_observations": 5}),
            5,
        )

    def test_invalid_values_fall_back_to_3_with_one_warning(self) -> None:
        for bad in (1, 0, "x", True):
            with self.subTest(value=bad):
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    result = gate._effective_prompt_threshold(
                        {"no_run_prompt_after_observations": bad}
                    )
                self.assertEqual(result, 3)
                self.assertEqual(len(w), 1)

    def test_missing_key_defaults_3_no_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = gate._effective_prompt_threshold({})
        self.assertEqual(result, 3)
        self.assertEqual(len(w), 0)

    def test_compute_verdict_threshold_wired_to_gate_error(self) -> None:
        """跨字段接线: 非默认阈值必须原样出现在 gate_error.prompt_after_observations
        里 (不写 gate_check 路径回显, 归 TASK-005)。它怎么会红: 基线 compute_verdict
        对 not_found 从不产出 gate_error 键 → KeyError。"""
        out = gate.compute_verdict(
            [],
            "not_found",
            cfg={"no_run_prompt_after_observations": 4},
            path_coverage=None,
        )
        self.assertEqual(out["gate_error"]["prompt_after_observations"], 4)


# ═══════════════════════════════════════════════════════════════════════════
# EarlyExitContractTests (TASK-004, aria-plugin#152) — SC-6 / SC-7 守卫。
#
# 钉基线 9e6a17c: gate_check 六个早退点的输出 schema (六键; main 核验两分支
# 例外为七键, 含 gate_error) 在生产代码变更 (TASK-003/006) 落地之前必须原样
# GREEN。守卫先于生产变更落地 —— 生产改动若破坏这份契约, 本组必须先红。
# ═══════════════════════════════════════════════════════════════════════════


class EarlyExitContractTests(_ProbeCacheResetMixin, unittest.TestCase):
    """SC-6/SC-7 守卫: 对当前基线 (9e6a17c) 必须 GREEN。

    SC-7: gate_check 六个早退点 (enabled:false / no-backend×2 / precheck 失败 /
    main 核验×2 / (b) 腿异常 / (a) 腿异常, 共八变体) 输出键集必须分别恰为
    六键 / 七键 (仅 main 核验两分支), 且所有早退分支都不带 path_coverage 键。
    SC-6: not_applicable 短路 **不是**早退点 —— 它走 compute_verdict, 带
    path_coverage 键, 且必须跳过 (a) PR CI 查询 (query_pr_ci.assert_not_called)。
    """

    _SIX_KEYS = {
        "verdict",
        "pr_ci_status",
        "in_flight_runs",
        "primitive_used",
        "primitive_version_sha",
        "raw_message",
    }
    _SEVEN_KEYS = _SIX_KEYS | {"gate_error"}

    def _ok_backend(self):
        """通过 enabled/no-backend/precheck/main-verify 四道早退, 走到查询腿的
        默认放行 backend (与 GateCheckTests._make_aether_backend_mock 同形)。"""
        b = mock.MagicMock(spec=AetherBackend)
        b.name = "aether-ci-cli"
        b.precheck.return_value = (True, "")
        b.query_branch_in_flight.return_value = InFlightStatus(runs=[])
        b.query_pr_ci.return_value = CIStatus(state="passing")
        return b

    def test_sc7_eight_early_exit_variants(self) -> None:
        def enabled_false():
            return gate.gate_check(pr_branch="feat/x", config={"enabled": False})

        def no_backend_abort():
            with mock.patch.object(gate, "resolve_ci_backend", return_value=None):
                return gate.gate_check(
                    pr_branch="feat/x", config={"no_ci_fallback": "abort"}
                )

        def no_backend_skip_with_warning():
            with mock.patch.object(gate, "resolve_ci_backend", return_value=None):
                return gate.gate_check(
                    pr_branch="feat/x",
                    config={"no_ci_fallback": "skip_with_warning"},
                )

        def precheck_fails():
            backend = self._ok_backend()
            backend.precheck.return_value = (False, "old binary")
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x")

        def main_not_found():
            self.mb_verify.return_value = ("not-found", "")
            backend = self._ok_backend()
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x")

        def main_verify_failed():
            self.mb_verify.return_value = ("verify-failed", "boom")
            backend = self._ok_backend()
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x")

        def b_leg_query_error():
            backend = self._ok_backend()
            backend.query_branch_in_flight.side_effect = AetherQueryError("x")
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x")

        def a_leg_query_error():
            backend = self._ok_backend()
            backend.query_pr_ci.side_effect = AetherQueryError("x")
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x")

        # (label, thunk, expected key set, expected gate_error.kind or None)
        cases = [
            ("1_enabled_false", enabled_false, self._SIX_KEYS, None),
            ("2_no_backend_abort", no_backend_abort, self._SIX_KEYS, None),
            (
                "3_no_backend_skip_with_warning",
                no_backend_skip_with_warning,
                self._SIX_KEYS,
                None,
            ),
            ("4_precheck_fails", precheck_fails, self._SIX_KEYS, None),
            (
                "5_main_not_found",
                main_not_found,
                self._SEVEN_KEYS,
                "main-branch-not-found",
            ),
            (
                "6_main_verify_failed",
                main_verify_failed,
                self._SEVEN_KEYS,
                "main-branch-verify-failed",
            ),
            ("7_b_leg_query_error", b_leg_query_error, self._SIX_KEYS, None),
            ("8_a_leg_query_error", a_leg_query_error, self._SIX_KEYS, None),
        ]
        for label, thunk, expected_keys, expected_kind in cases:
            with self.subTest(variant=label):
                try:
                    out = thunk()
                finally:
                    # 变体 5/6 改了 self.mb_verify 的返回值; 复位为 mixin 默认
                    # ("ok", ""), 避免串到本循环内后续变体。
                    self.mb_verify.return_value = ("ok", "")
                self.assertEqual(set(out.keys()), expected_keys, label)
                self.assertNotIn("path_coverage", out, label)
                if expected_kind is not None:
                    self.assertEqual(
                        set(out["gate_error"].keys()), {"kind", "message"}, label
                    )
                    self.assertEqual(out["gate_error"]["kind"], expected_kind, label)

    def test_sc6_not_applicable_short_circuit_is_not_an_early_exit(self) -> None:
        """not_applicable 短路: 带 path_coverage 键, 无 gate_error 键, 跳过
        (a) PR CI 查询 (因果机制断言, 非仅结果字段)。"""
        self.pc_eval.return_value = {
            "decision": "not_applicable",
            "workflows_scanned": 1,
            "matched_workflows": [],
            "changed_files_count": 2,
            "reason": "no-triggering-paths",
        }
        backend = self._ok_backend()
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(pr_branch="feat/x")
        backend.query_pr_ci.assert_not_called()
        self.assertNotIn("gate_error", out)
        self.assertIn("path_coverage", out)
        self.assertEqual(out["verdict"], "green")


# ═══════════════════════════════════════════════════════════════════════════
# GateCheckNotFoundTests / PrBranchVerifyTests / OldNameWrapperTests
# (TASK-005, aria-plugin#152) — RED against baseline e95b202 for the
# TASK-006 PR-branch existence verification + `<pr_branch>` backfill contract
# (spec §2.1):
#
#   pr_status = backend.query_pr_ci(pr_branch)
#   verify_note = ""
#   if pr_status.state == "not_found":
#       st, detail = _verify_branch_exists(pr_branch, remote=remote, timeout=...)
#       if st == "not-found":
#           → verdict=fail, gate_error.kind="pr-branch-not-found"
#       if st != "ok":
#           verify_note = " (PR 分支存在性核验失败: {detail})"
#   out = compute_verdict(...)
#   if out.get("gate_error"):
#       out["gate_error"]["message"] = message.replace("<pr_branch>", pr_branch) + verify_note
#       out["raw_message"] = out["gate_error"]["message"]
#
# TASK-006 (另一 agent) 实现生产代码; 本组只钉规格。SC-5 (占位符回填 +
# raw_message 同步 + gate_check 真接线核验调用, 非仅结果字段) / SC-10 (PR 分支
# 不存在 → verdict=fail, kind="pr-branch-not-found") / SC-3 末句 (阈值跨路径
# 一致, GUARD)。
# ═══════════════════════════════════════════════════════════════════════════


class GateCheckNotFoundTests(_ProbeCacheResetMixin, unittest.TestCase):
    """gate_check 端到端: pr_ci_status="not_found" 分支下 PR 分支核验的接线
    契约 (TASK-006, spec §2.1)。backend mock 与 GateCheckTests._make_aether_
    backend_mock 同形, 局部改名避免与那边的 fixture 撞车。"""

    def _make_backend(
        self, pr_state: str = "not_found", main_runs: list[dict] | None = None
    ):
        b = mock.MagicMock(spec=AetherBackend)
        b.name = "aether-ci-cli"
        b.precheck.return_value = (True, "")
        b.query_branch_in_flight.return_value = InFlightStatus(
            runs=main_runs or [], checked_at="2026-08-22T00:00:00Z"
        )
        b.query_pr_ci.return_value = CIStatus(
            state=pr_state, checked_at="2026-08-22T00:00:00Z"
        )
        return b

    @staticmethod
    def _pr_verify_branch_arg(call_args) -> str | None:
        """契约允许 `_verify_branch_exists(pr_branch, remote=..., timeout=...)`
        (pr_branch 位置参数) 或未来实现改用关键字 branch= —— 两种形态都接受,
        断言的是"传的分支名对不对", 不是"用了哪种传参形态"。"""
        if call_args.args:
            return call_args.args[0]
        return call_args.kwargs.get("branch")

    def test_a_enabled_calls_pr_verify_and_keeps_no_run_gate_error(self) -> None:
        """(a) 它怎么会红: 基线 gate_check 从不调用 gate._verify_branch_exists
        (TASK-006 未落地) —— self.pr_verify.assert_called_once() 处红
        (call_count==0)。verdict/pr_ci_status/gate_error.kind/path_coverage/
        六基础键这几条本身在基线已绿 (TASK-003 已把 compute_verdict 接进
        gate_check), 红点精确落在"核验是否被调用"上。"""
        backend = self._make_backend(pr_state="not_found")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], gate.VERDICT_WAIT)
        self.assertEqual(out["pr_ci_status"], "not_found")
        self.assertEqual(out["gate_error"]["kind"], "no-run-for-branch")
        self.assertIn("path_coverage", out)
        for key in (
            "verdict",
            "pr_ci_status",
            "in_flight_runs",
            "primitive_used",
            "primitive_version_sha",
            "raw_message",
        ):
            self.assertIn(key, out)
        self.pr_verify.assert_called_once()
        self.assertEqual(
            self._pr_verify_branch_arg(self.pr_verify.call_args), "feat/x"
        )

    def test_b_path_coverage_disabled_no_path_coverage_key(self) -> None:
        """(b) 可能基线已绿 (path_coverage_enabled=False 时 gate_check 从不
        调 evaluate_path_coverage, compute_verdict 早已对 path_coverage=None
        产出"路径覆盖评估已关闭"文案, TASK-003 已覆盖这条) —— 仍留作守卫:
        钉住 TASK-006 新插入的 PR 分支核验分支不会意外把 path_coverage 键
        塞回输出里。"""
        backend = self._make_backend(pr_state="not_found")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(
                pr_branch="feat/x", config={"path_coverage_enabled": False}
            )
        self.assertIn("gate_error", out)
        self.assertNotIn("path_coverage", out)
        self.assertIn("路径覆盖评估已关闭", out["gate_error"]["message"])

    def test_c1_no_placeholder_literal_and_raw_message_synced(self) -> None:
        """(c1) GUARD, 三变体 ((a) 默认 / (b) path_coverage 关闭 / (d)
        verify-failed 后缀) 逐一断言 message 不含字面 "<pr_branch>" 且
        raw_message 与 gate_error.message 同步。可能基线已绿 (基线从不产出
        该占位符字面量, TASK-003 起两字段已同步) —— 仍有守卫价值: 防止
        TASK-006 的 `.replace("<pr_branch>", ...)` 接线在某条路径漏做替换,
        让占位符裸奔到用户可见的 message/raw_message。"""
        backend = self._make_backend(pr_state="not_found")

        def _get(config=None, pr_verify_return=None):
            self.pr_verify.return_value = pr_verify_return or ("ok", "")
            with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
                return gate.gate_check(pr_branch="feat/x", config=config)

        variants = [
            ("a_enabled", None, None),
            ("b_pc_disabled", {"path_coverage_enabled": False}, None),
            ("d_verify_failed", None, ("verify-failed", "boom")),
        ]
        for label, config, pr_verify_return in variants:
            with self.subTest(variant=label):
                out = _get(config=config, pr_verify_return=pr_verify_return)
                self.assertNotIn("<pr_branch>", out["gate_error"]["message"])
                self.assertEqual(out["raw_message"], out["gate_error"]["message"])

    def test_d_verify_failed_appends_suffix_to_message(self) -> None:
        """(d) 它怎么会红: 基线从不调用 pr_verify, 其 return_value 对输出零
        影响 —— message 里不会出现 "核验失败: boom" 这个后缀, assertIn 处红
        (基线 message 就是 _no_run_gate_error 的原文, 没有追加段)。"""
        self.pr_verify.return_value = ("verify-failed", "boom")
        backend = self._make_backend(pr_state="not_found")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(pr_branch="feat/x")
        self.assertEqual(out["verdict"], gate.VERDICT_WAIT)
        self.assertEqual(out["gate_error"]["kind"], "no-run-for-branch")
        self.assertIn("核验失败: boom", out["gate_error"]["message"])
        self.assertEqual(out["raw_message"], out["gate_error"]["message"])

    def test_sc3_threshold_consistent_across_gate_check_and_compute_verdict(
        self,
    ) -> None:
        """SC-3 末句 GUARD: 已在基线绿 (TASK-003 早已把 gate_check 接到
        compute_verdict, 阈值透传跨路径一致) —— 仍留作守卫: 防止 TASK-006 在
        gate_check 里对 gate_error 做 .replace() 后处理时意外重建/覆盖整个
        字典, 连带丢了 prompt_after_observations。"""
        backend = self._make_backend(pr_state="not_found")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(
                pr_branch="feat/x",
                config={"no_run_prompt_after_observations": 4},
            )
        direct = gate.compute_verdict(
            [],
            "not_found",
            cfg={"no_run_prompt_after_observations": 4},
            path_coverage=dict(_PC_COVERED_STUB),
        )
        self.assertEqual(
            out["gate_error"]["prompt_after_observations"],
            direct["gate_error"]["prompt_after_observations"],
        )
        self.assertEqual(out["gate_error"]["prompt_after_observations"], 4)


class PrBranchVerifyTests(_ProbeCacheResetMixin, unittest.TestCase):
    """SC-10: PR 分支在远端确不存在时的 verdict=fail + kind=
    "pr-branch-not-found" 契约 (TASK-006, spec §2.1)。它怎么会红 (整体): 基线
    gate_check 从不调用 gate._verify_branch_exists, self.pr_verify 的
    return_value 对输出零影响 —— pr_ci_status="not_found" 一律落基线既有的
    compute_verdict wait 分支 (kind="no-run-for-branch"), 不是这里要的
    fail/"pr-branch-not-found"。"""

    def _make_backend(
        self, pr_state: str = "not_found", main_runs: list[dict] | None = None
    ):
        b = mock.MagicMock(spec=AetherBackend)
        b.name = "aether-ci-cli"
        b.precheck.return_value = (True, "")
        b.query_branch_in_flight.return_value = InFlightStatus(
            runs=main_runs or [], checked_at="2026-08-22T00:00:00Z"
        )
        b.query_pr_ci.return_value = CIStatus(
            state=pr_state, checked_at="2026-08-22T00:00:00Z"
        )
        return b

    def test_pr_branch_not_found_routes_fail(self) -> None:
        """RED: 基线第一条 assertEqual(verdict, ...) 即红 —— 基线给的是
        "wait" (kind="no-run-for-branch"), 断言要的是 "fail"
        (kind="pr-branch-not-found")。gate_error 键集断言 (仅 {"kind",
        "message"}, 无 prompt_after_observations) 在基线同样红: 基线
        gate_error 恰好带着那第三个键。两个 path_coverage 开/关变体都覆盖。"""
        self.pr_verify.return_value = ("not-found", "")
        backend = self._make_backend(pr_state="not_found")

        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out = gate.gate_check(
                pr_branch="feat/x", main_branch="master", remote="origin"
            )
        self.assertEqual(out["verdict"], gate.VERDICT_FAIL)
        self.assertEqual(out["gate_error"]["kind"], "pr-branch-not-found")
        self.assertEqual(out["raw_message"], out["gate_error"]["message"])
        self.assertIn("feat/x", out["gate_error"]["message"])
        self.assertIn("origin", out["gate_error"]["message"])
        self.assertEqual(out["pr_ci_status"], "not_found")
        self.assertIn("path_coverage", out)
        self.assertEqual(set(out["gate_error"].keys()), {"kind", "message"})

        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            out2 = gate.gate_check(
                pr_branch="feat/x",
                main_branch="master",
                remote="origin",
                config={"path_coverage_enabled": False},
            )
        self.assertEqual(out2["verdict"], gate.VERDICT_FAIL)
        self.assertNotIn("path_coverage", out2)
        self.assertEqual(set(out2["gate_error"].keys()), {"kind", "message"})

    def test_pr_ci_passing_never_triggers_pr_branch_verify(self) -> None:
        """GUARD: 基线本就绿 (pr_verify 目前在任何路径都未接线, passing 状态
        更不会碰它); TASK-006 落地后仍须只在 pr_ci_status=="not_found" 时才
        调用 —— 钉的是"仅 not_found 分支触发"这条因果关系 (assert_not_called
        为机制断言, 非仅结果字段), 防止未来实现误把核验挪到无条件调用。"""
        backend = self._make_backend(pr_state="passing")
        with mock.patch.object(gate, "resolve_ci_backend", return_value=backend):
            gate.gate_check(pr_branch="feat/x")
        self.pr_verify.assert_not_called()


class OldNameWrapperTests(unittest.TestCase):
    """SC-10 附属契约: 旧名 gate._verify_main_branch_exists 须瘦身成对新名
    gate._verify_branch_exists(main_branch, remote, timeout) 的位置参数包装
    (TASK-006 契约倒数第二段)。刻意**不继承** _ProbeCacheResetMixin —— mixin
    对 `_verify_main_branch_exists` 的统一打桩会整个替换掉这个函数, 掩盖它
    "是否委托给新名"这件事本身; 本组要观测的正是这层委托关系, 必须调用真实
    (未被替换的) 旧名函数体。"""

    def test_old_name_delegates_to_new_name_positionally(self) -> None:
        """它怎么会红: 基线 _verify_main_branch_exists 是完整实现 (不是薄
        包装), 对不存在的 remote 名跑真实 `git ls-remote --heads
        no-such-remote-152 mb` —— 实测该调用秒级失败 (rc=128, fatal: 不是
        git repo, 不建立网络连接), 返回它自己算出的 ("verify-failed", ...),
        不等于打桩返回的 ("ok", "sentinel") —— 第一条 assertEqual 处红。"""
        with mock.patch.object(
            gate,
            "_verify_branch_exists",
            return_value=("ok", "sentinel"),
            create=True,
        ) as m:
            result = gate._verify_main_branch_exists(
                main_branch="mb", remote="no-such-remote-152", timeout=5
            )
        self.assertEqual(result, ("ok", "sentinel"))
        m.assert_called_once_with("mb", "no-such-remote-152", 5)


if __name__ == "__main__":
    unittest.main()
