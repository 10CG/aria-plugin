"""A1.4 tests for scripts/lib/spec_complete.py — archive-completeness-gate (#134).

Covers (DEC-20260609-001 契约 A, tasks.md A1.4):
- 判定真值表: 全 normalized-state × {tasks.md 有/无 × 全[x]/有[ ]}
- carry-forward 子类 (gap(b)): 全[x] 但含 defer 注释 → complete=False
- "多入口对同一 spec 一致 verdict" 不变量
- CLI/import 一致性 fixture: subprocess 跑 thin CLI 解析 stdout JSON vs
  import 直调, 断言 diff==0 (complete / incomplete / no-proposal 三类, AC-1)
- fail-soft (A1.3): proposal.md 缺失/spec_dir 不存在 → complete=False 不 crash
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file
from collectors._status import _normalize_status

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_SPEC_COMPLETE_PY = _SCRIPTS_DIR / "lib" / "spec_complete.py"

# Deliberately NOT `from lib.spec_complete import ...`: the top-level name
# `lib` resolves to state-scanner/lib (skill root, a regular package with
# __init__.py) once handoff_multibranch.py inserts _SS_ROOT onto sys.path —
# which shadows scripts/lib. Import the bare module via the scripts/lib dir
# instead (same mechanism as collectors/openspec.py's fallback branch).
_LIB_DIR = str(_SCRIPTS_DIR / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import is_spec_complete  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture vocabulary
# ---------------------------------------------------------------------------

# normalized-state → raw Status string that _normalize_status maps onto it.
# `unknown` uses the real block-flip raw value (`DEFERRED`, 2026-06-09) — the
# motivating live specimen for the gate.
RAW_BY_STATE = {
    "done": "Done",
    "approved": "Approved",
    "implemented": "Implemented",
    "reviewed": "Reviewed",
    "active": "Active",
    "ready": "Ready",
    "pending": "Draft",
    "in_progress": "In Progress",
    "archived": "Archived",
    "deprecated": "Deprecated",
    "unknown": "DEFERRED",
}

TASKS_ALL_CHECKED = "# Tasks\n\n- [x] task one\n- [x] task two\n"
TASKS_HAS_UNCHECKED = "# Tasks\n\n- [x] task one\n- [ ] task two\n"
TASKS_CHECKED_WITH_DEFER = (
    "# Tasks\n\n"
    "- [x] task one [deferred to v1.43.0: infra-gated]\n"
    "- [x] task two\n"
)
TASKS_NO_CHECKBOXES = "# Tasks\n\nprose only, no checkbox list.\n"


def make_spec(
    root: Path,
    raw_status: str | None,
    tasks: str | None = None,
    spec_id: str = "test-spec",
) -> Path:
    """Create openspec/changes/<id>/ with proposal.md (+ optional tasks.md)."""
    spec_dir = root / "openspec" / "changes" / spec_id
    status_line = f"> **Status**: {raw_status}\n\n" if raw_status is not None else ""
    write_file(spec_dir / "proposal.md", f"# {spec_id}\n\n{status_line}## Why\ntest\n")
    if tasks is not None:
        write_file(spec_dir / "tasks.md", tasks)
    return spec_dir


def run_cli(spec_dir: Path) -> tuple[int, dict]:
    """Run the thin CLI; return (exit_code, parsed stdout JSON)."""
    p = subprocess.run(
        [sys.executable, str(_SPEC_COMPLETE_PY), str(spec_dir)],
        capture_output=True,
        text=True,
    )
    return p.returncode, json.loads(p.stdout)


# ---------------------------------------------------------------------------
# Truth table: 全 normalized-state × {tasks.md 有/无 × 全[x]/有[ ]}
# ---------------------------------------------------------------------------


class TestFixtureStatusMappingGuard(unittest.TestCase):
    """Guard: RAW_BY_STATE must keep mapping onto the intended normalized states.

    If _normalize_status's codomain/classification drifts, this fails FIRST
    with a precise message instead of the truth-table tests failing opaquely.
    """

    def test_raw_fixture_normalizes_to_expected_state(self):
        for expected, raw in RAW_BY_STATE.items():
            self.assertEqual(
                _normalize_status(raw),
                expected,
                f"fixture drift: raw {raw!r} no longer normalizes to {expected!r}",
            )


class TestTruthTable(unittest.TestCase):
    def test_tasks_absent_verdict_by_status_only(self):
        """tasks.md absent → complete iff normalized=='done' (绝非 vacuously True)."""
        for state, raw in RAW_BY_STATE.items():
            with tmp_project() as root:
                spec_dir = make_spec(root, raw, tasks=None)
                verdict = is_spec_complete(spec_dir)
                self.assertEqual(
                    verdict["complete"],
                    state == "done",
                    f"state={state}: {verdict['reason']}",
                )

    def test_tasks_all_checked_complete_for_every_state(self):
        """左析取: tasks.md 全[x] 无注释 → complete=True (与 Status 无关)."""
        for state, raw in RAW_BY_STATE.items():
            with tmp_project() as root:
                spec_dir = make_spec(root, raw, tasks=TASKS_ALL_CHECKED)
                verdict = is_spec_complete(spec_dir)
                self.assertTrue(
                    verdict["complete"], f"state={state}: {verdict['reason']}"
                )

    def test_tasks_has_unchecked_verdict_by_status_only(self):
        """有 open [ ] → tasks 分支不放行, 仅 Status=='done' 可救."""
        for state, raw in RAW_BY_STATE.items():
            with tmp_project() as root:
                spec_dir = make_spec(root, raw, tasks=TASKS_HAS_UNCHECKED)
                verdict = is_spec_complete(spec_dir)
                self.assertEqual(
                    verdict["complete"],
                    state == "done",
                    f"state={state}: {verdict['reason']}",
                )

    def test_no_status_line_tasks_absent_incomplete(self):
        """proposal 无 Status 行 (→ unknown) + 无 tasks.md → incomplete."""
        with tmp_project() as root:
            spec_dir = make_spec(root, raw_status=None, tasks=None)
            verdict = is_spec_complete(spec_dir)
            self.assertFalse(verdict["complete"])
            self.assertIn("unknown", verdict["reason"])

    def test_implemented_never_complete_dec_d2(self):
        """`implemented` 不算 complete (DEC §3 D2 rationale 硬编码)."""
        with tmp_project() as root:
            spec_dir = make_spec(root, "Implemented", tasks=TASKS_HAS_UNCHECKED)
            verdict = is_spec_complete(spec_dir)
            self.assertFalse(verdict["complete"])
            self.assertIn("DEC-20260609-001", verdict["reason"])


class TestTasksEdgeCases(unittest.TestCase):
    def test_tasks_zero_checkboxes_falls_to_status_branch(self):
        """tasks.md 存在但 0 checkbox → tasks 分支不可验证 (防 vacuous truth)."""
        with tmp_project() as root:
            spec_dir = make_spec(root, "Approved", tasks=TASKS_NO_CHECKBOXES)
            self.assertFalse(is_spec_complete(spec_dir)["complete"])
        with tmp_project() as root:
            spec_dir = make_spec(root, "Done", tasks=TASKS_NO_CHECKBOXES)
            self.assertTrue(is_spec_complete(spec_dir)["complete"])

    def test_tilde_marker_counts_as_unchecked(self):
        """非 x/X 标记 (如 `[~]`) 视为未完成 — gate 宁紧勿松."""
        with tmp_project() as root:
            spec_dir = make_spec(
                root, "Approved", tasks="# T\n\n- [x] a\n- [~] b in flight\n"
            )
            verdict = is_spec_complete(spec_dir)
            self.assertFalse(verdict["complete"])
            self.assertIn("unchecked", verdict["reason"])


# ---------------------------------------------------------------------------
# Carry-forward 子类 (gap(b))
# ---------------------------------------------------------------------------


class TestCarryForwardSubclass(unittest.TestCase):
    def test_all_checked_with_defer_annotation_blocks(self):
        """全[x] 但含 inline defer 注释 → 左析取不放行 (非 done 状态全 False)."""
        for state, raw in RAW_BY_STATE.items():
            if state == "done":
                continue
            with tmp_project() as root:
                spec_dir = make_spec(root, raw, tasks=TASKS_CHECKED_WITH_DEFER)
                verdict = is_spec_complete(spec_dir)
                self.assertFalse(
                    verdict["complete"], f"state={state}: {verdict['reason']}"
                )
                self.assertIn("carry-forward", verdict["reason"])

    def test_defer_annotation_with_done_status_passes_via_status_branch(self):
        """右析取独立: Status=='done' 时 carry-forward 注释不再拦截."""
        with tmp_project() as root:
            spec_dir = make_spec(root, "Done", tasks=TASKS_CHECKED_WITH_DEFER)
            self.assertTrue(is_spec_complete(spec_dir)["complete"])

    def test_carry_forwarded_word_not_matched(self):
        """词边界: `carry-forwarded` 子串延伸不触发 (复用同一 regex SOT)."""
        tasks = "# T\n\n- [x] a (carry-forwarded from v1.40.0 history note)\n"
        with tmp_project() as root:
            spec_dir = make_spec(root, "Approved", tasks=tasks)
            self.assertTrue(is_spec_complete(spec_dir)["complete"])


# ---------------------------------------------------------------------------
# fail-soft (A1.3)
# ---------------------------------------------------------------------------


class TestFailSoft(unittest.TestCase):
    def test_missing_proposal_md(self):
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "no-proposal"
            spec_dir.mkdir(parents=True)
            verdict = is_spec_complete(spec_dir)
            self.assertFalse(verdict["complete"])
            self.assertIn("proposal.md", verdict["reason"])

    def test_nonexistent_spec_dir(self):
        with tmp_project() as root:
            verdict = is_spec_complete(root / "does" / "not" / "exist")
            self.assertFalse(verdict["complete"])
            self.assertIn("proposal.md", verdict["reason"])

    def test_verdict_shape_invariant(self):
        """所有路径返回 {complete: bool, reason: str} 双键 dict."""
        with tmp_project() as root:
            for spec_dir in (
                make_spec(root, "Done", tasks=TASKS_ALL_CHECKED, spec_id="a"),
                make_spec(root, "Approved", tasks=None, spec_id="b"),
                root / "missing",
            ):
                verdict = is_spec_complete(spec_dir)
                self.assertEqual(set(verdict), {"complete", "reason"})
                self.assertIsInstance(verdict["complete"], bool)
                self.assertIsInstance(verdict["reason"], str)
                self.assertTrue(verdict["reason"])


# ---------------------------------------------------------------------------
# 多入口一致 verdict 不变量 + CLI/import 一致性 (AC-1)
# ---------------------------------------------------------------------------


class TestCliImportConsistency(unittest.TestCase):
    """Thin CLI (Bash 入口) 与 import 直调对同一 spec_dir 必须 verdict diff==0.

    三类输入 (A1.4): complete / incomplete / no-proposal。锚 AC-1 的
    "SKILL.md Bash 调与 collector import 调同一 SOT" 不变量。
    """

    def _assert_cli_matches_import(self, spec_dir: Path, expect_exit: int):
        import_verdict = is_spec_complete(spec_dir)
        exit_code, cli_verdict = run_cli(spec_dir)
        self.assertEqual(cli_verdict, import_verdict, "CLI vs import verdict drift")
        self.assertEqual(exit_code, expect_exit)

    def test_complete_spec(self):
        with tmp_project() as root:
            spec_dir = make_spec(root, "Approved", tasks=TASKS_ALL_CHECKED)
            self._assert_cli_matches_import(spec_dir, expect_exit=0)

    def test_incomplete_spec(self):
        with tmp_project() as root:
            spec_dir = make_spec(root, "Approved", tasks=TASKS_HAS_UNCHECKED)
            self._assert_cli_matches_import(spec_dir, expect_exit=1)

    def test_no_proposal_spec(self):
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "empty"
            spec_dir.mkdir(parents=True)
            self._assert_cli_matches_import(spec_dir, expect_exit=1)

    def test_cli_usage_error_exit_2(self):
        """无参数 → exit 2 + stdout 仍是可解析 JSON (CLI 永远输出 JSON)."""
        p = subprocess.run(
            [sys.executable, str(_SPEC_COMPLETE_PY)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 2)
        verdict = json.loads(p.stdout)
        self.assertFalse(verdict["complete"])

    def test_repeated_calls_deterministic(self):
        """同一 spec_dir 重复调用 (import×2 + CLI×1) verdict 完全一致."""
        with tmp_project() as root:
            spec_dir = make_spec(root, "DEFERRED", tasks=None)
            v1 = is_spec_complete(spec_dir)
            v2 = is_spec_complete(spec_dir)
            _, v3 = run_cli(spec_dir)
            self.assertEqual(v1, v2)
            self.assertEqual(v1, v3)


if __name__ == "__main__":
    unittest.main()
