"""A1.4 tests for scripts/lib/spec_complete.py — archive-completeness-gate (#134)
+ #95 TG-5 tests for the tri-state gate_result() extension (archive-gate-runtime-reality).

Covers (DEC-20260609-001 契约 A, tasks.md A1.4):
- 判定真值表: 全 normalized-state × {tasks.md 有/无 × 全[x]/有[ ]}
- carry-forward 子类 (gap(b)): 全[x] 但含 defer 注释 → complete=False
- "多入口对同一 spec 一致 verdict" 不变量
- CLI/import 一致性 fixture: subprocess 跑 thin CLI 解析 stdout JSON vs
  import 直调, 断言 diff==0 (complete / incomplete / no-proposal 三类, AC-1)
- fail-soft (A1.3): proposal.md 缺失/spec_dir 不存在 → complete=False 不 crash

Covers (#95 TG-5, DEC-20260704-003, detailed-tasks.yaml TASK-018~023):
- TASK-018: C-block golden 负例 (Layer L `phase1_gate`) + complete=true∧block
  combo + 4 类正控 (代码引用/集成面/dynamic-dispatch/通用路径调用) + 正控5
  (未分类形态 fail-toward-warn) — 见 ``TestGateResultGoldenNegativeLayerL`` /
  ``TestGateResultSyntheticDeadCodeAnchor`` / ``TestGateResultPositiveControlsSynthetic``
  / ``TestSymbolWithoutPythonDefinitionWarnsNotBlocks``.
- TASK-019: N≥8 已归档正常 spec 语料 C-block 全 0 例 — 见
  ``TestCFalseBlockBoundedCorpus`` (真树 dogfood, Rule #6).
- TASK-020: C-warn + unverified_claims + ack 解耦 — 见
  ``TestCWarnUnverifiedClaimsAckDecoupling``.
- TASK-021: fail-soft 降级路径 (符号提取/引用核验/产物抽验/tasks.md 解析) — 见
  ``TestCFailSoftDegradationPaths``.
- TASK-022: D payload (lib 侧) 单一 owner/marker/幂等/headless — 见
  ``TestDPayloadLibLevel``.
- TASK-023: tri-state ``gate_result()`` schema 契约 — 见
  ``TestGateResultTriStateSchema``.

Covers (runtime-probe-archive-gate-integration TASK-012, #95 follow-up A,
detailed-tasks.yaml parent 3.2): ``gate_result()`` 对 proposal.md frontmatter
``runtime_probe:`` 声明的折入集成测试 —— 无声明零动作 (SC-1 兜底) / pass 内存
态折入 (SC-2) / 四形态 warn 折入 + block 组合不降不升 (SC-3) / skipped 静默
(SC-4) / 声明无效 (文本层+值层) + IO 边界 (SC-5) / 探针异常全兜底 (SC-6) — 见
``TestRuntimeProbeFold*`` 系列 class (与 unit 层 ``test_runtime_probe.py``
互补: 那边钉 ``probe()``/``validate_descriptor()`` 自身契约, 这里钉它们被
``gate_result()`` 折入后的编排行为)。

真树 dogfood 语料 (TASK-018/019) 依赖 Aria **元仓库**的 openspec/archive/
(而非 aria-plugin 自身仓库 —— aria/ 是 Aria 的 git submodule, 两者 openspec/
目录是分开的, 见 CLAUDE.md 规则 #5)。当 aria-plugin 独立于 Aria 元仓库跑测试
时 (如仅 clone aria-plugin 自身仓库), 该语料目录不存在 —— 相关测试用
``_require_meta_archive()`` 优雅 skip, 不静默通过也不硬失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
import spec_complete  # noqa: E402 — module object needed for unittest.mock.patch targets
from spec_complete import (  # noqa: E402
    _build_d_payload,
    _find_project_root,
    _iter_task_items,
    _line_has_integration_keyword,
    _symbol_has_python_definition,
    classify_artifact_claim,
    classify_symbol_liveness,
    extract_claim_symbols,
    gate_result,
    is_spec_complete,
)

# ---------------------------------------------------------------------------
# #95 TG-5: real-tree (Aria meta-repo) dogfood corpus location.
#
# tests/test_spec_complete.py lives at aria/skills/state-scanner/tests/ inside
# the aria-plugin repo (a submodule of the Aria meta-repo). `parents[4]` walks
# up: tests -> state-scanner -> skills -> aria -> <Aria meta-repo root>, where
# the *outer* project's openspec/archive/ (not aria/openspec/, which is empty
# — aria-plugin itself carries no OpenSpec changes of its own, see CLAUDE.md
# Rule #5) holds the real archived specs used as golden/corpus fixtures below.
# ---------------------------------------------------------------------------
_ARIA_META_ROOT = Path(__file__).resolve().parents[4]
_META_ARCHIVE_ROOT = _ARIA_META_ROOT / "openspec" / "archive"


def _require_meta_archive() -> Path:
    """Return the Aria meta-repo's openspec/archive/ dir, or skip the test.

    Skips (not fails, not silently passes) when this test suite is exercised
    outside the Aria meta-repo checkout (e.g. aria-plugin cloned standalone),
    where the real-tree dogfood corpus referenced by TASK-018/019 does not
    exist on disk.
    """
    if not _META_ARCHIVE_ROOT.is_dir():
        raise unittest.SkipTest(
            f"real-tree dogfood corpus not found at {_META_ARCHIVE_ROOT} "
            "(expected when aria-plugin is tested outside the Aria meta-repo checkout)"
        )
    return _META_ARCHIVE_ROOT


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


def make_gate_spec(
    root: Path,
    tasks_md: str | None = None,
    detailed_tasks_yaml: str | None = None,
    spec_id: str = "gate-test-spec",
    status: str = "Approved",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Build a self-contained mini-project for ``gate_result()`` tests (#95 TG-5).

    Unlike ``make_spec`` (which only needs a single spec dir for #134's
    ``is_spec_complete``), ``gate_result``'s C-gate symbol-liveness check
    greps the whole **project root** (``_find_project_root`` resolves it by
    walking up from spec_dir looking for the ``openspec`` path segment — here,
    ``root``) — so ``extra_files`` lets a test plant arbitrary production
    files (real code, SKILL.md, hooks.json, shell scripts, ...) alongside the
    spec dir for the liveness grep to actually see.
    """
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(spec_dir / "proposal.md", f"# {spec_id}\n\n> **Status**: {status}\n\n## Why\ntest\n")
    if tasks_md is not None:
        write_file(spec_dir / "tasks.md", tasks_md)
    if detailed_tasks_yaml is not None:
        write_file(spec_dir / "detailed-tasks.yaml", detailed_tasks_yaml)
    for rel_path, content in (extra_files or {}).items():
        write_file(root / rel_path, content)
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


# =============================================================================
# #95 TG-5 — gate_result() tri-state tests (TASK-018~023)
# =============================================================================


class TestGateResultGoldenNegativeLayerL(unittest.TestCase):
    """TASK-018: Layer L 活标本 ``phase1_gate`` —— **随现实演化**。

    2026-07-04 起草时 phase1_gate 是死代码 (写好却零生产接线), 本 gate 会 block。
    **2026-07-05: 双子星 DEC-20260704-002 (aria-plugin v1.52.0) 把 phase1_gate 接活
    了** (Layer L advisory 接线 run_gate → coordination_probe 生产调用)。故本 gate
    现**正确地不再 block** —— 恰是设计意图: 死代码被真正接线后, gate 自动 un-block
    (gate 追踪运行现实, 非静态勾选)。block 行为契约由自包含合成 fixture
    ``TestGateResultSyntheticDeadCodeAnchor`` 独立钉死 (不依赖真实语料漂移 —— 该 anchor
    测试的 docstring 早已预言此漂移)。
    """

    def setUp(self):
        archive_root = _require_meta_archive()
        self.spec_dir = archive_root / "2026-05-20-multi-terminal-coordination"
        if not self.spec_dir.is_dir():
            self.skipTest(f"golden fixture spec dir missing: {self.spec_dir}")

    def test_phase1_gate_now_wired_by_dec002_no_longer_blocks(self):
        # DEC-002 接活 phase1_gate → 不再是死代码 → gate 不 block (verdict∈{pass,warn})。
        # 这演示 gate 的核心价值: 一旦死代码被真接线, 完成声称即属实, gate 放行。
        result = gate_result(self.spec_dir)
        self.assertNotEqual(
            result["verdict"], "block",
            "phase1_gate 已被 DEC-002 接活, gate 不应再判其死代码; "
            f"若仍 block 说明接线未被识别: {result.get('blocking_reasons')}",
        )

    def test_complete_true_and_block_combo_synthetic(self):
        """PP-R1 qa fix: ``complete`` (#134 checkbox 存在性) 与 ``verdict`` (C 属实性)
        正交 —— tasks.md 全 [x] (complete=true) 的 spec 仍可被 C 判死代码 block。
        用自包含合成 fixture (real phase1_gate 已被 DEC-002 接活, 不再适合演示 block)。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 9.1 集成 `orphan_gate` 到 orchestrator (死代码, 应 block)\n",
                '  - id: TASK-901\n    parent: "9.1"\n    deliverables: ["lib/orphan_gate.py"]\n',
                spec_id="synthetic-complete-block-combo",
                extra_files={
                    "lib/orphan_gate.py": "def orphan_gate():\n    pass\n",
                    "README.md": "orphan_gate 仅此散文提及, 从未被生产调用。\n",
                },
            )
            result = gate_result(spec_dir)
            self.assertTrue(
                result["complete"], f"tasks 全[x] 应 complete=True: {result['complete_reason']}"
            )
            self.assertEqual(result["verdict"], "block")


class TestGateResultSyntheticDeadCodeAnchor(unittest.TestCase):
    """TASK-018 补充: 与真实 Layer L golden 负例平行的、完全自包含的死代码
    block 锚点 —— 不依赖 Aria 元仓库真实归档语料随时间漂移 (若未来
    ``phase1_gate`` 意外获得一处真实生产引用, golden 负例测试会失效; 本合成
    fixture 独立钉死 block 行为契约)。
    """

    def test_synthetic_dead_symbol_blocks(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 9.1 集成 `dead_symbol` 到 orchestrator (死代码模拟, 应 block)\n",
                '  - id: TASK-900\n    parent: "9.1"\n    deliverables: ["lib/dead_symbol.py"]\n',
                spec_id="synthetic-dead-code",
                extra_files={
                    "lib/dead_symbol.py": "def dead_symbol():\n    pass\n",
                    "README.md": "dead_symbol is only mentioned here in prose, never called.\n",
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "block")
            self.assertTrue(any("dead_symbol" in r for r in result["blocking_reasons"]))


class TestGateResultPositiveControlsSynthetic(unittest.TestCase):
    """TASK-018 正控 1-5 (proposal §What Changes 1 + Success Criteria): 4 类
    alive 形态 + 1 类未分类 fail-toward-warn 形态, 各构造一个自包含 fixture
    (``tmp_project`` — 无 git 初始化, ``classify_symbol_liveness`` 的
    ``_grep_symbol_occurrences`` 探测非-git 目录时会 fallback 到 plain
    ``grep -r`` 而非 ``git grep``, 已亲验行为等价), 钉死"不误 block"契约,
    独立于真实归档语料的漂移 (真实语料覆盖见 ``TestCFalseBlockBoundedCorpus``)。
    """

    def test_positive_control_1_real_code_reference(self):
        """(i) 代码引用: 真实 import + 调用 (`from lib.foo_bar import foo_bar` +
        `foo_bar()`)."""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 1.1 集成 `foo_bar` 到 orchestrator (真实 import + 调用)\n",
                '  - id: TASK-100\n    parent: "1.1"\n    deliverables: ["lib/foo_bar.py"]\n',
                spec_id="ctrl1-code-reference",
                extra_files={
                    "lib/foo_bar.py": "def foo_bar():\n    return 42\n",
                    "orchestrator.py": "from lib.foo_bar import foo_bar\n\nfoo_bar()\n",
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["blocking_reasons"], [])

    def test_positive_control_2_skill_md_bash_integration(self):
        """(iii) aria-plugin 集成面 pt1: SKILL.md 内 Bash 代码块真调用该脚本
        (无 .py import)."""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 2.1 集成 `baz_tool` 到 skill (无 .py import, 只 SKILL.md Bash 调用)\n",
                '  - id: TASK-200\n    parent: "2.1"\n    deliverables: ["scripts/baz_tool.py"]\n',
                spec_id="ctrl2-skill-md-bash",
                extra_files={
                    "scripts/baz_tool.py": "def main():\n    pass\n",
                    "aria/skills/demo-skill/SKILL.md": (
                        "# Demo\n\n```bash\npython3 scripts/baz_tool.py --now\n```\n"
                    ),
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["blocking_reasons"], [])

    def test_positive_control_2b_hooks_json_registration(self):
        """(iii) aria-plugin 集成面 pt2: hooks.json 内注册该 hook (无 .py import)."""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 2.2 集成 `qux_hook` 到 hooks.json (无 .py import, 仅 hook 注册)\n",
                '  - id: TASK-201\n    parent: "2.2"\n    deliverables: ["hooks/qux_hook.py"]\n',
                spec_id="ctrl2b-hooks-json",
                extra_files={
                    "hooks/qux_hook.py": "def handler():\n    pass\n",
                    "hooks.json": (
                        '{"hooks": {"PreToolUse": [{"command": "python3 hooks/qux_hook.py"}]}}\n'
                    ),
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["blocking_reasons"], [])

    def test_positive_control_3_dynamic_dispatch(self):
        """(ii) dynamic-dispatch: `getattr(module, "qux_handler")` (无静态 import)."""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 3.1 集成 `qux_handler` 经 getattr 反射调用 (dynamic dispatch, 无静态 import)\n",
                '  - id: TASK-300\n    parent: "3.1"\n    deliverables: ["handlers/qux_handler.py"]\n',
                spec_id="ctrl3-dynamic-dispatch",
                extra_files={
                    "handlers/qux_handler.py": "def run():\n    pass\n",
                    "dispatcher.py": (
                        "import importlib\n\n"
                        "module = importlib.import_module('handlers')\n"
                        'handler = getattr(module, "qux_handler")\n'
                        "handler()\n"
                    ),
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["blocking_reasons"], [])

    def test_positive_control_4_generic_shell_path_call(self):
        """(iv) 通用调用面: shell 脚本按字面整脚本路径调用 (无 .py import),
        proposal 例子原型 (`m6-phase-b-gate-check.sh`)."""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 4.1 集成 `quux_script` 经 shell 脚本调用 (无 .py import, 仅 shell 按路径调用)\n",
                '  - id: TASK-400\n    parent: "4.1"\n    deliverables: ["tools/quux_script.py"]\n',
                spec_id="ctrl4-generic-path-call",
                extra_files={
                    "tools/quux_script.py": "def main():\n    pass\n",
                    ".aria/scripts/run_quux.sh": "#!/bin/bash\npython3 tools/quux_script.py\n",
                },
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["blocking_reasons"], [])

    def test_positive_control_5_unclassified_form_fails_toward_warn(self):
        """正控 5: 未分类 wiring 形态 (出现但不落入任一 alive/prose 清单, 如
        `except ambiguous_symbol:` 裸引用无调用/属性/赋值/import 形态) →
        必须降级 warn, 绝不 hard-block (fail-toward-warn 契约)。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 5.1 集成 `ambiguous_symbol` 到 module (未分类引用形态, 应降级 warn 非 block)\n",
                '  - id: TASK-500\n    parent: "5.1"\n    deliverables: ["lib/ambiguous_symbol.py"]\n',
                spec_id="ctrl5-unclassified-warn",
                extra_files={
                    "lib/ambiguous_symbol.py": "def ambiguous_symbol():\n    pass\n",
                    "consumer.py": "try:\n    risky_call()\nexcept ambiguous_symbol:\n    pass\n",
                },
            )
            result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertEqual(result["verdict"], "warn")
            self.assertTrue(
                any("ambiguous_symbol" in w for w in result["warnings"]),
                f"expected a warning naming ambiguous_symbol: {result['warnings']}",
            )


class TestSymbolWithoutPythonDefinitionWarnsNotBlocks(unittest.TestCase):
    """主控亲验新增 fix (``_symbol_has_python_definition``): markdown/prompt-only
    skill 的纯 documented-convention 符号 (无任何 .py 定义, 如 audit-drift-guard
    的 ``drift_warning``) —— 无 Python 定义则符号根本不是"代码", 不可能是死代码,
    必须 fail-toward-warn 而非 block (否则误伤大量非代码类完成声称, 击穿 SC
    "既有正常归档零影响")。
    """

    def test_real_archived_markdown_only_symbol_warns(self):
        archive_root = _require_meta_archive()
        spec_dir = archive_root / "2026-06-11-audit-drift-guard"
        if not spec_dir.is_dir():
            self.skipTest(f"reference spec dir missing: {spec_dir}")
        result = gate_result(spec_dir)
        self.assertNotEqual(result["verdict"], "block")
        self.assertEqual(result["verdict"], "warn")
        self.assertTrue(
            any("drift_warning" in w for w in result["warnings"]),
            f"expected a warning naming drift_warning: {result['warnings']}",
        )

    def test_symbol_has_python_definition_false_for_markdown_only_symbol(self):
        """直接单元锚定 ``_symbol_has_python_definition`` 契约 (不依赖真实归档
        语料漂移): 无 definition_paths + 生产出现里无 def/class 语句 + 无同名
        .py 模块文件 → False。"""
        with tmp_project() as root:
            write_file(root / "SKILL.md", "# Demo\n\n约定: `prompt_only_concept` 是……\n")
            occurrences = [("SKILL.md", 3, "约定: `prompt_only_concept` 是……")]
            self.assertFalse(
                _symbol_has_python_definition("prompt_only_concept", root, set(), occurrences)
            )

    def test_symbol_has_python_definition_true_when_def_statement_present(self):
        with tmp_project() as root:
            write_file(root / "lib" / "mod.py", "def real_symbol():\n    pass\n")
            occurrences = [("lib/mod.py", 1, "def real_symbol():")]
            self.assertTrue(_symbol_has_python_definition("real_symbol", root, set(), occurrences))


# ---------------------------------------------------------------------------
# TASK-019: C 误报有界 + 判别力 — N≥8 真实归档语料
# ---------------------------------------------------------------------------

# 已归档正常 spec (排除 golden 负例 multi-terminal-coordination), 2026-07 主控
# 挑选, 覆盖正控 1 (code_reference) / 2 (aria_plugin_integration) / 4
# (generic_path_call) 各 ≥1 (由 test_corpus_covers_alive_categories 显式核验)。
# 正控 3 (dynamic-dispatch) 在探索性全量扫描 (117 归档 spec) 中未天然出现于
# 任一 tasks.md 集成声称 —— 由 TestGateResultPositiveControlsSynthetic 的合成
# fixture 单独锚定, 非本语料职责 (如实记录, 非隐瞒缺口)。
_KNOWN_NORMAL_ARCHIVE_IDS = (
    "2025-12-19-clarify-phase-a-task-pipeline",
    "2025-12-23-git-commit-convention",
    "2026-02-05-tdd-strictness-enhancement",
    "2026-04-25-state-scanner-mechanical",
    "2026-05-06-aria-2.0-m3-cycle-close-glm-routing-recovery",
    "2026-05-13-aria-issue-101-status-normalize",
    "2026-05-31-concurrent-session-upm-safety",
    "2026-06-10-aria-archive-completeness-gate",
    "2026-06-11-audit-drift-guard",
    "2026-06-19-tdd-enforcer-security-commit-separation",
)


class TestCFalseBlockBoundedCorpus(unittest.TestCase):
    """TASK-019: C 误报有界 + 判别力 —— N≥8 已归档正常 spec 语料, C-block 全
    0 例 (falsifiable, 非"零误报"绝对声称; proposal SC 明确要求"列具体 N 个")。

    真树 dogfood (Rule #6): 直接对 Aria 元仓库现有 openspec/archive/ 语料跑
    ``gate_result()``, 而非合成 fixture。

    NOTE (维护指引): 若本测试因未来新归档 spec 意外报 block 而失败 —— 先判断
    这是 (a) 该新 spec 真的死代码声称 (归档流程本该拦, 需人工加逃生舱或修
    tasks.md 措辞) 还是 (b) lib 误判 (报告 TG-1 owner 复核, 不要自行改 lib 或
    静默从 corpus 里删除该 id 来让测试通过)。
    """

    def setUp(self):
        self.archive_root = _require_meta_archive()

    def test_named_corpus_zero_false_block(self):
        blocked = []
        for spec_id in _KNOWN_NORMAL_ARCHIVE_IDS:
            spec_dir = self.archive_root / spec_id
            self.assertTrue(spec_dir.is_dir(), f"corpus fixture drift: {spec_id} no longer archived")
            result = gate_result(spec_dir)
            if result["verdict"] == "block":
                blocked.append((spec_id, result["blocking_reasons"]))
        self.assertEqual(blocked, [], f"false C-block(s) in normal-spec corpus: {blocked}")

    def test_corpus_covers_alive_categories(self):
        """正控 1/2/4 (code_reference / aria_plugin_integration /
        generic_path_call) 在 named corpus 里各至少出现一次 (防
        vacuous-pass: 若语料恰好全是"pass"只因为压根没有可核验符号,
        N≥8 断言就是空洞的)。"""
        seen_categories: set[str] = set()
        for spec_id in _KNOWN_NORMAL_ARCHIVE_IDS:
            spec_dir = self.archive_root / spec_id
            tasks_path = spec_dir / "tasks.md"
            if not tasks_path.is_file():
                continue
            tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace")
            project_root = _find_project_root(spec_dir) or spec_dir.parent
            for item in _iter_task_items(tasks_text):
                if not (item["checked"] and _line_has_integration_keyword(item["line"])):
                    continue
                extraction = extract_claim_symbols(spec_dir, item)
                if not extraction["extractable"]:
                    continue
                def_by_symbol = extraction.get("definition_paths_by_symbol", {})
                for symbol in extraction["symbols"]:
                    liveness = classify_symbol_liveness(
                        symbol, project_root, def_by_symbol.get(symbol, set())
                    )
                    seen_categories.update(liveness["alive_categories"])
        self.assertTrue(
            {"code_reference", "aria_plugin_integration", "generic_path_call"} <= seen_categories,
            f"corpus no longer exercises expected alive categories: got {seen_categories}",
        )

    def test_full_archive_sweep_only_golden_blocks(self):
        """真树 dogfood 全量不变量: 排除 golden 负例
        (multi-terminal-coordination) 外, Aria 元仓库当前**全部**已归档 spec
        (含 tasks.md 的) 跑 gate 应 0 block (2026-07 主控全量 sweep 实测口径:
        117 归档 spec 中仅 golden 1 个 block)。"""
        golden_id = "2026-05-20-multi-terminal-coordination"
        unexpected_blocks = []
        scanned = 0
        for spec_dir in sorted(self.archive_root.iterdir()):
            if not spec_dir.is_dir() or spec_dir.name == golden_id:
                continue
            if not (spec_dir / "tasks.md").is_file():
                continue
            scanned += 1
            result = gate_result(spec_dir)
            if result["verdict"] == "block":
                unexpected_blocks.append((spec_dir.name, result["blocking_reasons"]))
        self.assertGreaterEqual(
            scanned, 8, "expected the archive corpus to have at least N>=8 tasks.md-bearing specs"
        )
        self.assertEqual(unexpected_blocks, [], f"unexpected C-block(s) beyond golden: {unexpected_blocks}")


# ---------------------------------------------------------------------------
# TASK-020: C-warn + unverified_claims + ack 解耦
# ---------------------------------------------------------------------------


class TestCWarnUnverifiedClaimsAckDecoupling(unittest.TestCase):
    """TASK-020: 无产物的 dogfood/benchmark 声称 → warn + unverified_claims;
    D payload 无论是否 ack 都携带该项 (ack 解耦, proposal §What Changes 2 R2
    F3-fix) —— lib 层 ``gate_result``/``_build_d_payload`` 根本不接受 ack
    参数, "无论是否 ack" 的落地就是: lib 侧行为对 ack 完全无感知, 每次调用都
    无条件产出同样的 unverified_claims + d_payload (ack 是 SKILL.md/Bash 侧的
    交互记录, 不是 lib 的前置条件)。
    """

    def _spec_with_unlinked_dogfood_claim(self, root: Path) -> Path:
        return make_gate_spec(
            root,
            "# Tasks\n\n- [x] 6.1 dogfood 验证: 承载 ≥1 真实场景跑通 (无可链接产物路径)\n",
            spec_id="ctrl-warn-artifact",
        )

    def test_no_artifact_claim_warns_with_unverified_claims(self):
        with tmp_project() as root:
            spec_dir = self._spec_with_unlinked_dogfood_claim(root)
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            self.assertTrue(result["unverified_claims"])
            self.assertTrue(any("dogfood" in c["claim"] for c in result["unverified_claims"]))

    def test_ack_decoupling_d_payload_always_carries_unverified_claim_both_calls(self):
        """模拟 "ack=True" 与 "ack=False" 两条分支各自独立调用 gate_result (lib
        层无 ack 形参, 两次调用本身就是对两条分支的模拟): 结果必须完全一致且
        都含被 warn 项 —— 证明 D 兜底不依赖任何 ack 状态。"""
        with tmp_project() as root:
            spec_dir = self._spec_with_unlinked_dogfood_claim(root)
            result_ack_false = gate_result(spec_dir)  # 模拟未 ack 分支 (无额外操作)
            result_ack_true = gate_result(spec_dir)  # 模拟已 ack 分支 (调用方另记人工确认, lib 无感知)
            self.assertIsNotNone(result_ack_false["d_payload"])
            self.assertIsNotNone(result_ack_true["d_payload"])
            self.assertEqual(result_ack_false["d_payload"], result_ack_true["d_payload"])
            for payload in (result_ack_false["d_payload"], result_ack_true["d_payload"]):
                self.assertTrue(any("dogfood" in c["claim"] for c in payload["unverified_claims"]))


# ---------------------------------------------------------------------------
# TASK-021: fail-soft 降级路径
# ---------------------------------------------------------------------------


class TestCFailSoftDegradationPaths(unittest.TestCase):
    """TASK-021: 全部新增判定 (符号提取/引用核验/产物抽验/tasks.md 解析) 的
    降级路径 — 异常 → 放行 (不 block) + soft_error 记录, 从不因此崩溃或误
    block。分两层锚定:

    (a) 各纯函数自身的 fail-soft (``extract_claim_symbols`` /
        ``classify_symbol_liveness`` / ``classify_artifact_claim`` 的独立
        try/except, 每个来源互相隔离);
    (b) ``gate_result`` 编排层对每个子判定调用点的兜底 try/except (即便子
        函数自己没接住的意外异常, 编排层外层也不能因此 block/crash)。
    """

    # ---- (a) 纯函数自身 fail-soft ----

    def test_extract_claim_symbols_detailed_tasks_source_isolated_failure(self):
        """detailed-tasks.yaml 源 (TASK-002 三源之一) 解析异常 → 该源
        soft_error 记录, 但 tasks_inline 源 (同一 claim line 内的 backtick
        identifier) 独立生效, 不被拖累 (每个来源 fail-soft 互相隔离)。"""
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "failsoft-extract-isolated"
            write_file(
                spec_dir / "detailed-tasks.yaml",
                '  - id: TASK-1\n    parent: "1.1"\n    deliverables: ["lib/foo.py"]\n',
            )
            claim = {"parent_id": "1.1", "line": "集成 `foo` 到 module"}
            with patch(
                "spec_complete._extract_deliverables_for_parent", side_effect=RuntimeError("boom")
            ):
                extraction = extract_claim_symbols(spec_dir, claim)
            self.assertTrue(
                any("detailed-tasks.yaml extraction failed" in e for e in extraction["soft_errors"])
            )
            self.assertIn("foo", extraction["symbols"])

    def test_classify_symbol_liveness_grep_failure_is_ambiguous_not_dead(self):
        """proposal §What Changes 1: "grep 失败 → status='ambiguous' + soft_error"
        (放行, 不 block —— 与"未分类形态"同归宿)。"""
        with tmp_project() as root:
            with patch(
                "spec_complete._grep_symbol_occurrences", side_effect=RuntimeError("grep exploded")
            ):
                result = classify_symbol_liveness("whatever_symbol", root, set())
            self.assertEqual(result["status"], "ambiguous")
            self.assertIsNotNone(result["soft_error"])

    def test_classify_artifact_claim_internal_exception_is_soft_error(self):
        """TASK-006 产物抽验的全 fail-soft 兜底: 内部任何异常 (此处经
        ``_find_project_root`` 触发) 都不抛出, 只降级 verified=False +
        soft_error 标注。"""
        with tmp_project() as root:
            with patch(
                "spec_complete._find_project_root", side_effect=RuntimeError("root lookup exploded")
            ):
                result = classify_artifact_claim("dogfood 验证 xyz", root, None)
            self.assertFalse(result["verified"])
            self.assertIn("soft_error", result["reason"])

    # ---- (b) gate_result 编排层兜底 ----

    def _integration_claim_spec(self, root: Path) -> Path:
        return make_gate_spec(
            root,
            "# Tasks\n\n- [x] 1.1 集成 `foo_bar` 到 orchestrator\n",
            '  - id: TASK-1\n    parent: "1.1"\n    deliverables: ["lib/foo_bar.py"]\n',
            spec_id="failsoft-gate-level",
            extra_files={
                "lib/foo_bar.py": "def foo_bar():\n    return 1\n",
                "orchestrator.py": "from lib.foo_bar import foo_bar\nfoo_bar()\n",
            },
        )

    def test_gate_result_symbol_extraction_exception_does_not_block(self):
        with tmp_project() as root:
            spec_dir = self._integration_claim_spec(root)
            with patch("spec_complete.extract_claim_symbols", side_effect=RuntimeError("boom")):
                result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertTrue(any("symbol extraction failed" in e for e in result["soft_errors"]))

    def test_gate_result_liveness_check_exception_does_not_block(self):
        with tmp_project() as root:
            spec_dir = self._integration_claim_spec(root)
            with patch("spec_complete.classify_symbol_liveness", side_effect=RuntimeError("boom")):
                result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertTrue(any("liveness check failed" in e for e in result["soft_errors"]))

    def test_gate_result_artifact_claim_check_exception_does_not_block(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root, "# Tasks\n\n- [x] 6.1 dogfood 验证跑通\n", spec_id="failsoft-artifact-gate-level"
            )
            with patch("spec_complete._check_artifact_claims", side_effect=RuntimeError("boom")):
                result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertTrue(any("artifact claim check failed" in e for e in result["soft_errors"]))

    def test_gate_result_checkbox_parse_exception_does_not_crash(self):
        with tmp_project() as root:
            spec_dir = self._integration_claim_spec(root)
            with patch("spec_complete._iter_task_items", side_effect=RuntimeError("boom")):
                result = gate_result(spec_dir)  # 不应抛异常
            self.assertNotEqual(result["verdict"], "block")
            self.assertTrue(any("checkbox parse failed" in e for e in result["soft_errors"]))

    def test_gate_result_deferred_item_extraction_exception_does_not_block(self):
        with tmp_project() as root:
            spec_dir = self._integration_claim_spec(root)
            with patch(
                "spec_complete._extract_deferred_or_unchecked_items", side_effect=RuntimeError("boom")
            ):
                result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertTrue(any("deferred item extraction failed" in e for e in result["soft_errors"]))

    def test_gate_result_d_payload_build_exception_yields_none_not_block(self):
        with tmp_project() as root:
            spec_dir = self._integration_claim_spec(root)
            with patch("spec_complete._build_d_payload", side_effect=RuntimeError("boom")):
                result = gate_result(spec_dir)
            self.assertNotEqual(result["verdict"], "block")
            self.assertIsNone(result["d_payload"])
            self.assertTrue(any("D payload build failed" in e for e in result["soft_errors"]))


# ---------------------------------------------------------------------------
# TASK-022: D payload (lib 侧)
# ---------------------------------------------------------------------------


class TestDPayloadLibLevel(unittest.TestCase):
    """TASK-022: D payload (lib 侧 unit) —— 单一 owner / marker 去重键格式 /
    幂等 / headless (无 ack 概念仍无条件产出)。Forgejo API 真调用/backend
    降级是 TASK-024 integration 层职责, 本类只锚定 lib 侧契约。
    """

    def test_d_payload_none_when_nothing_to_track(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(root, TASKS_ALL_CHECKED, spec_id="d-payload-clean")
            result = gate_result(spec_dir)
            self.assertIsNone(result["d_payload"])

    def test_d_payload_marker_format_and_spec_id(self):
        with tmp_project() as root:
            spec_id = "d-payload-marker-test"
            spec_dir = make_gate_spec(
                root, "# Tasks\n\n- [x] 1 done\n- [ ] 2 not done yet\n", spec_id=spec_id
            )
            result = gate_result(spec_dir)
            payload = result["d_payload"]
            self.assertIsNotNone(payload)
            self.assertEqual(payload["marker"], f"<!-- archive-tracker:{spec_id} -->")
            self.assertIn(payload["marker"], payload["body"])
            self.assertEqual(payload["spec_id"], spec_id)
            self.assertIn(spec_id, payload["body"])

    def test_d_payload_single_owner_not_a_list(self):
        """"单一 owner" 在 lib 层的落地: 每次调用只产 0 或 1 份 dict payload,
        绝非多份/list —— 真正跨归档幂等去重 (同 spec 多次归档不重复开 issue)
        是 TG-2 openspec-archive Step2 Bash 侧按 marker search-before-create
        的职责 (见 module docstring TASK-011 段), 非本 lib 职责; 本测试只锚定
        lib 侧"单一 payload 对象"契约。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root, "# Tasks\n\n- [x] 1 done\n- [ ] 2 not done yet\n", spec_id="d-payload-single-owner"
            )
            result = gate_result(spec_dir)
            self.assertIsInstance(result["d_payload"], dict)

    def test_d_payload_idempotent_across_repeated_calls(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root, "# Tasks\n\n- [x] 1 done\n- [ ] 2 not done yet\n", spec_id="d-payload-idempotent"
            )
            payload_1 = gate_result(spec_dir)["d_payload"]
            payload_2 = gate_result(spec_dir)["d_payload"]
            self.assertEqual(payload_1, payload_2)

    def test_d_payload_headless_no_ack_concept_still_produced(self):
        """headless (v2.0 Layer 2 自主归档) 默认: lib 层压根没有 ``ack`` 形参,
        ``_build_d_payload`` 无条件基于 deferred_items/unverified_claims 构建
        —— 本测试直接调用 ``_build_d_payload`` 佐证其签名/行为不依赖任何 ack
        状态。"""
        payload = _build_d_payload(
            "some-spec-id",
            deferred_items=[],
            unverified_claims=[{"claim": "x", "reason": "no artifact", "symbols": []}],
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["spec_id"], "some-spec-id")
        self.assertTrue(payload["unverified_claims"])

    def test_d_payload_deferred_items_included(self):
        deferred = [{"parent_id": "2", "line": "2 not done yet", "reason": "unchecked"}]
        payload = _build_d_payload("some-spec-id", deferred_items=deferred, unverified_claims=[])
        self.assertIsNotNone(payload)
        self.assertIn("未完成/deferred 项", payload["body"])


# ---------------------------------------------------------------------------
# TASK-023: tri-state gate_result() schema 契约
# ---------------------------------------------------------------------------


class TestGateResultTriStateSchema(unittest.TestCase):
    """TASK-023: ``gate_result()`` 契约结构断言 —— tri-state verdict + 各字段
    类型/键集合。两消费方 (openspec-archive Bash / phase-d-closer Bash) 读
    同一 JSON 的端到端一致性由 TASK-024 integration 测试验 (本文件只锚定纯
    Python 契约)。
    """

    _EXPECTED_KEYS = {
        "complete",
        "complete_reason",
        "verdict",
        "blocking_reasons",
        "warnings",
        "unverified_claims",
        "d_payload",
        "soft_errors",
    }

    def _assert_schema(self, result: dict):
        self.assertEqual(set(result), self._EXPECTED_KEYS)
        self.assertIsInstance(result["complete"], bool)
        self.assertIsInstance(result["complete_reason"], str)
        self.assertIn(result["verdict"], ("pass", "warn", "block"))
        self.assertIsInstance(result["blocking_reasons"], list)
        self.assertIsInstance(result["warnings"], list)
        self.assertIsInstance(result["unverified_claims"], list)
        for c in result["unverified_claims"]:
            self.assertEqual(set(c), {"claim", "reason", "symbols"})
        self.assertTrue(result["d_payload"] is None or isinstance(result["d_payload"], dict))
        self.assertIsInstance(result["soft_errors"], list)

    def test_schema_no_tasks_md(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(root, tasks_md=None, spec_id="schema-no-tasks")
            result = gate_result(spec_dir)
            self._assert_schema(result)
            self.assertEqual(result["verdict"], "pass")

    def test_schema_pass_verdict(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(root, TASKS_ALL_CHECKED, spec_id="schema-pass")
            result = gate_result(spec_dir)
            self._assert_schema(result)
            self.assertEqual(result["verdict"], "pass")

    def test_schema_warn_verdict(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root, "# Tasks\n\n- [x] 6.1 dogfood 验证跑通\n", spec_id="schema-warn"
            )
            result = gate_result(spec_dir)
            self._assert_schema(result)
            self.assertEqual(result["verdict"], "warn")

    def test_schema_block_verdict(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 9.1 集成 `dead_symbol_schema` 到 orchestrator\n",
                '  - id: TASK-9\n    parent: "9.1"\n    deliverables: ["lib/dead_symbol_schema.py"]\n',
                spec_id="schema-block",
                extra_files={
                    "lib/dead_symbol_schema.py": "def dead_symbol_schema():\n    pass\n",
                    "README.md": "dead_symbol_schema only mentioned here in prose.\n",
                },
            )
            result = gate_result(spec_dir)
            self._assert_schema(result)
            self.assertEqual(result["verdict"], "block")

    def test_cli_gate_mode_matches_import_and_exit_codes(self):
        with tmp_project() as root:
            pass_spec = make_gate_spec(root, TASKS_ALL_CHECKED, spec_id="cli-gate-pass")
            block_spec = make_gate_spec(
                root,
                "# Tasks\n\n- [x] 9.1 集成 `dead_symbol_cli` 到 orchestrator\n",
                '  - id: TASK-9\n    parent: "9.1"\n    deliverables: ["lib/dead_symbol_cli.py"]\n',
                spec_id="cli-gate-block",
                extra_files={
                    "lib/dead_symbol_cli.py": "def dead_symbol_cli():\n    pass\n",
                    "README.md": "dead_symbol_cli only mentioned here in prose.\n",
                },
            )
            for spec_dir, expect_exit in ((pass_spec, 0), (block_spec, 1)):
                proc = subprocess.run(
                    [sys.executable, str(_SPEC_COMPLETE_PY), "--gate", str(spec_dir)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, expect_exit)
                cli_result = json.loads(proc.stdout)
                import_result = gate_result(spec_dir)
                self.assertEqual(cli_result, import_result, "CLI --gate vs import gate_result() drift")

    def test_cli_gate_mode_usage_error_fails_toward_warn(self):
        # code-review fix (silent-failure-hunter I2, 2026-07-05): --gate 无 spec_dir 的
        # usage 错不再 fail-closed 到 block/exit2, 改 fail-toward-warn (verdict=warn, exit 0,
        # loud soft_error) —— gate 侧 wiring 错宁放行也不误 block 合法归档 (SC 零影响)。
        proc = subprocess.run(
            [sys.executable, str(_SPEC_COMPLETE_PY), "--gate"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["verdict"], "warn")
        self.assertTrue(result["soft_errors"], "usage error 应记 loud soft_error")
        # [qa M-f3] strengthen: the hardcoded fallback JSON literal (SC-1
        # "CLI 两处硬编码 fallback JSON" contract) must not carry a
        # `runtime_probe` key either — this path never reaches gate_result()
        # at all, so the key must be absent exactly like the SC-1 no-op case.
        self.assertNotIn("runtime_probe", result)

    def test_cli_gate_mode_unexpected_error_fails_toward_warn(self):
        # I1 fix: gate 意外 crash → fail-toward-warn (不 block)。用不存在路径不足以触发 crash
        # (fail-soft 到 pass), 故直接断言 usage 路径已覆盖 fail-open; crash 路径由 CLI 兜底
        # 恒 verdict∈{pass,warn} 保证 (exit 0)。此处冒烟: 坏路径不 block。
        proc = subprocess.run(
            [sys.executable, str(_SPEC_COMPLETE_PY), "--gate", "/no/such/spec/dir"],
            capture_output=True,
            text=True,
        )
        self.assertIn(proc.returncode, (0,))
        result = json.loads(proc.stdout)
        self.assertNotEqual(result["verdict"], "block")
        # [qa M-f3] strengthen: same fallback-key-absence guarantee as the
        # usage-error sibling test above — this crash-smoke path also never
        # reaches a real gate_result() JSON with a runtime_probe key.
        self.assertNotIn("runtime_probe", result)


class TestSearchAuthoritativenessNotDeadOnDegraded(unittest.TestCase):
    """C1 fix (silent-failure-hunter 2026-07-05): 搜索降级 (非 authoritative) 时不判 dead。"""

    def test_non_authoritative_search_yields_ambiguous_not_dead(self):
        # 一个本会判 dead 的符号 (有 Py 定义 + 零引用), 但把搜索标记为非 authoritative
        # → 必须降级 ambiguous (fail-toward-warn) + soft_error, 不得 dead。
        root = _ARIA_META_ROOT
        with patch.object(
            spec_complete, "_grep_symbol_occurrences", return_value=([], False)
        ), patch.object(spec_complete, "_symbol_has_python_definition", return_value=True):
            res = spec_complete.classify_symbol_liveness("phase1_gate", root, {"x/phase1_gate.py"})
        self.assertEqual(res["status"], "ambiguous")
        self.assertTrue(res["soft_error"], "降级搜索必记 soft_error")

    def test_authoritative_zero_ref_with_definition_is_dead(self):
        root = _ARIA_META_ROOT
        with patch.object(
            spec_complete, "_grep_symbol_occurrences", return_value=([], True)
        ), patch.object(spec_complete, "_symbol_has_python_definition", return_value=True):
            res = spec_complete.classify_symbol_liveness("phase1_gate", root, {"x/phase1_gate.py"})
        self.assertEqual(res["status"], "dead")


# =============================================================================
# TASK-012 (runtime-probe-archive-gate-integration, #95 follow-up A,
# detailed-tasks.yaml parent 3.2) — gate_result() runtime_probe declaration
# folding integration tests.
#
# Complements tests/test_runtime_probe.py (TASK-011, unit-level: pins
# validate_descriptor()/probe()/extract_runtime_probe()'s OWN contracts in
# isolation) — this section instead pins how spec_complete.py's
# _fold_runtime_probe_declaration()/gate_result() ORCHESTRATE those units:
# frontmatter parsing -> descriptor validation -> partition probe -> verdict
# folding -> unverified_claims/warnings double-write -> d_payload aggregation,
# end-to-end through the same gate_result() entry point every other class in
# this file already exercises.
#
# Verification bullets -> TestCase classes (TASK-012 detailed-tasks.yaml):
#   SC-1 兜底 (无声明零动作)     - TestRuntimeProbeFoldAbsentDeclaration
#   SC-2 (pass 内存态折入)       - TestRuntimeProbeFoldPass
#   SC-3 (四形态 warn 折入)      - TestRuntimeProbeFoldWarnForms
#   SC-3 (block 组合不降不升)    - TestRuntimeProbeFoldBlockCombination
#   SC-4 (skipped 静默)          - TestRuntimeProbeFoldSkipped
#   SC-5 (声明无效, 文本/值层)   - TestRuntimeProbeFoldInvalidDeclaration
#   SC-5 (IO 边界)               - TestRuntimeProbeFoldIOBoundary
#   SC-6 (fault-injection)       - TestRuntimeProbeFoldFaultInjection
#   AC-1 extension (CLI parity)  - TestRuntimeProbeFoldCliConsistency (bonus,
#                                   not an explicit TASK-012 bullet — added to
#                                   match this file's existing AC-1 CLI/import
#                                   parity standard applied to every other
#                                   verdict branch)
#
# gate_result() exposes NO clock-injection seam for the runtime_probe fold
# (_fold_runtime_probe_declaration always calls datetime.now(timezone.utc)
# internally) — unlike lib/runtime_probe.py's own probe(), which
# test_runtime_probe.py pins via an injected `now` (its `_NOW` constant).
# Fixtures here instead express telemetry recency RELATIVE to the real wall
# clock at test-execution time (`_probe_ts(days_ago)`), so pass/warn
# classification stays deterministic regardless of which calendar date the
# suite runs on (verification bullet 5: "受控 telemetry ts (相对 now 生成),
# 不依赖真实时钟绝对值").
# =============================================================================

_PROBE_PARTITION_REL = ".aria/probe-telemetry.jsonl"


def make_gate_spec_with_probe(
    root: Path,
    *,
    runtime_probe_yaml: str,
    tasks_md: str | None = None,
    detailed_tasks_yaml: str | None = None,
    spec_id: str = "probe-gate-test-spec",
    status: str = "Approved",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Like ``make_gate_spec`` but proposal.md carries a YAML frontmatter
    block (opening ``---`` line, then `runtime_probe_yaml` verbatim, then a
    closing ``---`` line and a blank line) prepended before the usual body —
    same construction ``tests/test_runtime_probe.py``'s
    ``TestOfficialExampleHermetic`` already locks against
    ``_frontmatter_block``/``extract_runtime_probe``. Keyword-only args (vs.
    ``make_gate_spec``'s positional style): ``runtime_probe_yaml`` is a new
    REQUIRED parameter, and mixing it positionally among the pre-existing
    optional ones would be an easy transcription footgun at call sites.
    """
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(
        spec_dir / "proposal.md",
        f"---\n{runtime_probe_yaml}---\n\n"
        f"# {spec_id}\n\n> **Status**: {status}\n\n## Why\ntest\n",
    )
    if tasks_md is not None:
        write_file(spec_dir / "tasks.md", tasks_md)
    if detailed_tasks_yaml is not None:
        write_file(spec_dir / "detailed-tasks.yaml", detailed_tasks_yaml)
    for rel_path, content in (extra_files or {}).items():
        write_file(root / rel_path, content)
    return spec_dir


def _runtime_probe_yaml(
    *,
    symbol: str,
    partition: str = _PROBE_PARTITION_REL,
    max_age_days: int | None = None,
    enabled_when: str | None = None,
) -> str:
    """Build a minimal ``runtime_probe:`` frontmatter body (2-space indent,
    one field per line, no trailing comments) — a parametrized sibling of
    ``test_runtime_probe.py``'s hardcoded ``_OFFICIAL_EXAMPLE_YAML`` (that one
    pins the spec's exact example text verbatim for the SC-2 hermetic lock;
    this one generates the many different descriptor shapes TASK-012's
    integration fixtures need)."""
    lines = ["runtime_probe:", f"  partition: {partition}", f"  symbol: {symbol}"]
    if max_age_days is not None:
        lines.append(f"  max_age_days: {max_age_days}")
    if enabled_when is not None:
        lines.append(f"  enabled_when: {enabled_when}")
    return "\n".join(lines) + "\n"


def _probe_ts(days_ago: float) -> str:
    """ISO-8601 UTC timestamp `days_ago` days before the REAL wall clock (see
    section header: gate_result() gives callers no clock-injection seam)."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe_prod_record(days_ago: float, **extra) -> dict:
    rec = {"ts": _probe_ts(days_ago), "source": "production"}
    rec.update(extra)
    return rec


def _write_probe_partition(root: Path, rel_path: str, records: list) -> None:
    """Write a JSONL telemetry partition. Each item is a dict (JSON-encoded)."""
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _skip_if_root() -> None:
    """A chmod-000 unreadable-partition fixture is meaningless under
    euid==0 (root bypasses POSIX permission bits) — mirrors
    test_runtime_probe.py's own guard of the same name (this file's
    one-file-only constraint means it can't be imported/shared, so it is
    re-declared locally)."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise unittest.SkipTest(
            "running as root - chmod 000 fixture would still be readable, "
            "so the unreadable-partition warn branch cannot be exercised"
        )


def _assert_probe_warn_family_folded(
    tc: unittest.TestCase, result: dict, *, symbol: str, expected_outcome: str
) -> dict:
    """Shared assertion for every probe-fold outcome that lands in the "warn
    ceiling" (SC-3's 4 warn forms union SC-5's "声明无效" forms — TASK-006/007's
    ``outcome in ("warn", "invalid")`` branch is one shared code path):
    ``gate_result.runtime_probe.outcome`` matches, a probe-warn entry is
    folded into BOTH ``warnings[]`` (human-readable) AND
    ``unverified_claims[]`` (structured, shape locked to this file's other 4
    append points: ``{claim, reason, symbols}`` — PP-R1 cr "除 warnings[] 外"
    double-write fix), and that same entry flows unmodified into
    ``d_payload`` (TASK-007 D-tracker double-write reuse, zero signature
    changes). Does NOT assert on ``result["verdict"]`` itself — callers
    decide that (plain warn-form tests expect "warn"; the block-combination
    test expects "block" unchanged) since this helper's job is only the
    entry-shape/double-write contract, not the verdict-ceiling policy.
    Returns the matched ``unverified_claims`` entry so callers needing extra
    assertions (e.g. the "无法核验" invalid-declaration wording) don't have to
    re-search for it.
    """
    tc.assertIn("runtime_probe", result)
    tc.assertEqual(result["runtime_probe"]["outcome"], expected_outcome)
    claim_tag = f"runtime_probe:{symbol}" if symbol else "runtime_probe"
    matches = [c for c in result["unverified_claims"] if c["claim"] == claim_tag]
    tc.assertEqual(len(matches), 1, result["unverified_claims"])
    entry = matches[0]
    tc.assertEqual(set(entry), {"claim", "reason", "symbols"})
    tc.assertEqual(entry["symbols"], [symbol] if symbol else [])
    tc.assertTrue(entry["reason"])
    tc.assertTrue(
        any(f"runtime_probe[{symbol or '?'}]:" in w for w in result["warnings"]),
        result["warnings"],
    )
    tc.assertIsNotNone(result["d_payload"])
    tc.assertIn(entry, result["d_payload"]["unverified_claims"])
    return entry


class TestRuntimeProbeFoldAbsentDeclaration(unittest.TestCase):
    """SC-1 兜底: 无 ``runtime_probe:`` frontmatter 声明的 spec → gate_result()
    的返回 dict 里该键**整体缺席** (非 ``None`` 占位, TASK-005: "禁 `null` 占
    位")。用 plain ``make_gate_spec`` (无 frontmatter block) —— 与既有全部 60
    个测试共享的构造法, 本测试只是把"缺席"这一隐含在 schema 测试里的事实显式
    钉成 TASK-012 verification 明文要求的独立断言。
    """

    def test_no_declaration_key_absent_not_none(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec(root, TASKS_ALL_CHECKED, spec_id="probe-absent")
            result = gate_result(spec_dir)
            self.assertNotIn("runtime_probe", result)
            self.assertEqual(result["verdict"], "pass")


class TestRuntimeProbeFoldPass(unittest.TestCase):
    """SC-2 内存态: 声明 + 窗口内 production 记录 → ``gate_result.runtime_probe``
    存在且 ``count>=1``, verdict 不变, 无新增 warnings/unverified_claims (pass
    不新增 — TASK-006: conditional 字段本身就是 note)。归档文件级"pass 不落
    盘"断言归 TASK-016 E2E (test_archive_gate_integration.sh); 本 task 只锚定
    ``gate_result()`` 的纯内存契约。
    """

    def test_pass_fold_verdict_unchanged_field_present(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_pass"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-pass",
            )
            _write_probe_partition(root, _PROBE_PARTITION_REL, [_probe_prod_record(1)])
            result = gate_result(spec_dir)

            self.assertIn("runtime_probe", result)
            self.assertEqual(
                set(result["runtime_probe"]), {"outcome", "count", "reason", "symbol", "ts"}
            )
            self.assertEqual(result["runtime_probe"]["outcome"], "pass")
            # [qa M-f5] tightened from assertGreaterEqual: this fixture
            # writes exactly 1 record via _write_probe_partition above, so
            # the exact count is a deterministic, precise expectation — not
            # merely "at least 1" (which would also silently pass if the
            # scan double-counted or leaked records from elsewhere).
            self.assertEqual(result["runtime_probe"]["count"], 1)
            self.assertEqual(result["runtime_probe"]["symbol"], "probe_pass")
            datetime.fromisoformat(result["runtime_probe"]["ts"])  # ISO-8601 round-trips

            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])
            self.assertEqual(result["soft_errors"], [])


class TestRuntimeProbeFoldWarnForms(unittest.TestCase):
    """SC-3: 四种 warn 形态各一 fixture — 分区缺失 / 存在不可读 (IO error) /
    全陈旧 / 仅非生产记录。每种都必须把 verdict 从 pass 抬到 warn, 且经
    ``_assert_probe_warn_family_folded`` 钉死的双写 shape 折入
    unverified_claims[]/warnings[]/d_payload。
    """

    def test_warn_partition_missing(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_missing"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-warn-missing",
            )
            # partition 文件有意不写 —— 声明了探针但从未产出过 telemetry。
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_missing", expected_outcome="warn"
            )
            self.assertIn("missing", entry["reason"])

    def test_warn_partition_unreadable_io_error(self):
        """既有假绿 bug 修复锁定的边界 (proposal §What 2): 分区存在但读失败,
        绝不能悄悄落入 pass。"""
        _skip_if_root()
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_unreadable"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-warn-unreadable",
            )
            partition = root / _PROBE_PARTITION_REL
            _write_probe_partition(root, _PROBE_PARTITION_REL, [_probe_prod_record(1)])
            os.chmod(partition, 0o000)
            try:
                result = gate_result(spec_dir)
            finally:
                os.chmod(partition, 0o644)  # restore so tempdir cleanup can unlink it
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_unreadable", expected_outcome="warn"
            )
            self.assertIn("unreadable", entry["reason"])

    def test_warn_all_records_stale(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_stale"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-warn-stale",
            )
            _write_probe_partition(root, _PROBE_PARTITION_REL, [_probe_prod_record(20)])
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_stale", expected_outcome="warn"
            )
            self.assertIn("stale", entry["reason"])

    def test_warn_only_nonproduction_records(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_nonprod"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-warn-nonprod",
            )
            _write_probe_partition(
                root, _PROBE_PARTITION_REL, [{"ts": _probe_ts(1), "source": "harness"}]
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_nonprod", expected_outcome="warn"
            )
            self.assertIn("non-production", entry["reason"])


class TestRuntimeProbeFoldSkipped(unittest.TestCase):
    """SC-4: ``enabled_when`` 开关关 → verdict 不变 + warnings **无新增** (低调
    note only — note IS the conditional ``runtime_probe`` field itself, TASK-
    006 docstring)."""

    def test_skipped_enabled_when_off_no_new_warnings(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(
                    symbol="probe_skipped",
                    enabled_when="state_scanner.coordination.enabled",
                ),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-skipped",
            )
            write_file(
                root / ".aria" / "config.json",
                json.dumps({"state_scanner": {"coordination": {"enabled": False}}}),
            )
            result = gate_result(spec_dir)
            self.assertIn("runtime_probe", result)
            self.assertEqual(result["runtime_probe"]["outcome"], "skipped")
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])

    def test_skipped_enabled_when_config_missing_no_new_warnings(self):
        """[qa I-f2] SC-4's SECOND skipped root cause, at the ORCHESTRATION
        layer (twin of test_skipped_enabled_when_off_no_new_warnings above,
        which writes a config.json with the switch explicitly off): here
        `.aria/config.json` is never written at all — `_load_config`'s
        missing_or_unreadable bucket — and must fold IDENTICALLY: declared
        (enabled_when set) + no config file → outcome=skipped, verdict
        unchanged, zero new warnings/unverified_claims/d_payload. The unit
        layer already pins this for `probe()` itself
        (test_runtime_probe.py::TestProbeSkippedAndConfigTraversal::
        test_skipped_config_file_missing) — this class pins the same
        orchestration-layer double-write ABSENCE that
        test_skipped_enabled_when_off_no_new_warnings pins for the
        switch-off root cause."""
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(
                    symbol="probe_skipped_no_config",
                    enabled_when="state_scanner.coordination.enabled",
                ),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-skipped-no-config",
            )
            # .aria/config.json intentionally never written.
            result = gate_result(spec_dir)
            self.assertIn("runtime_probe", result)
            self.assertEqual(result["runtime_probe"]["outcome"], "skipped")
            self.assertIn("missing", result["runtime_probe"]["reason"])
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])


class TestRuntimeProbeFoldInvalidDeclaration(unittest.TestCase):
    """SC-5 (声明无效 → warn 不猜): 文本层 + 值层各一形态。folded through the
    SAME warn ceiling as SC-3 — ``_fold_runtime_probe_declaration``'s
    ``outcome in ("warn", "invalid")`` branch is one shared code path;
    "runtime_probe 声明无效 — 无法核验 (cannot verify)" 前缀是唯一的文案区分
    标记, 结构化折入 shape 完全相同 (复用 ``_assert_probe_warn_family_folded``)。
    """

    def test_text_layer_invalid_flow_style_mapping_symbol_unknown(self):
        """文本层拒绝形态 (flow-style mapping, 沿用 test_runtime_probe.py 已锁
        定的同一拒绝形态) —— 声明整体解析失败, symbol 未知, claim_tag 退化为
        裸 "runtime_probe" (无悬空冒号, TASK-007 docstring)。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=(
                    "runtime_probe:\n"
                    "  partition: .aria/probe-telemetry.jsonl\n"
                    "  enabled_when: {a: b}\n"
                ),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-invalid-text-layer",
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="", expected_outcome="invalid"
            )
            self.assertIn("无法核验", entry["reason"])
            self.assertEqual(entry["claim"], "runtime_probe")

    def test_value_layer_invalid_missing_partition_symbol_known(self):
        """值层五形态之一 (缺必填 partition) —— 文本层解析成功 (symbol 键独立
        可读), 值层校验失败; claim_tag 仍带 symbol (TASK-007: "尽力从未校验的
        原始字符串里带出 symbol 供 claim 标注")。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml="runtime_probe:\n  symbol: probe_missing_partition\n",
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-invalid-value-layer",
            )
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_missing_partition", expected_outcome="invalid"
            )
            self.assertIn("无法核验", entry["reason"])
            self.assertIn("partition", entry["reason"])


class TestRuntimeProbeFoldIOBoundary(unittest.TestCase):
    """SC-5 IO 边界: proposal.md 缺失 / OSError —— 均先于任何声明解析发生
    (声明内容根本没有机会被读到), 等同"无声明零动作"但比 tasks.md 缺失先例
    更响 (TASK-005: change 目录缺 proposal.md 本身即异常) —— soft_errors 必须
    记录, key 仍整体缺席。
    """

    def test_missing_proposal_md_zero_action_plus_soft_error(self):
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "probe-io-missing-proposal"
            write_file(spec_dir / "tasks.md", TASKS_ALL_CHECKED)
            result = gate_result(spec_dir)
            self.assertNotIn("runtime_probe", result)
            self.assertTrue(
                any(
                    "proposal.md not found for runtime_probe declaration check" in e
                    for e in result["soft_errors"]
                ),
                result["soft_errors"],
            )

    def test_oserror_scoped_read_failure_zero_action_plus_soft_error(self):
        """monkeypatch ``Path.read_text`` **作用域化到本 fixture 的
        proposal.md**: 真实实现原样代理其它一切路径, 尤其 tasks.md —— 若不作
        用域化 (直接给 ``Path.read_text`` 全局塞一个恒抛异常的 side_effect),
        tasks.md 自身的读取会在 runtime_probe 检查段之前就先撞见同一个坏
        mock, 触发 ``gate_result`` 的早退分支 (`tasks.md read failed` ->
        `return result`), 本要测的分支永远走不到。"""
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_io_oserror"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-io-oserror",
            )
            proposal_path = spec_dir / "proposal.md"
            real_read_text = Path.read_text

            def _scoped_read_text(self_path, *args, **kwargs):
                if self_path == proposal_path:
                    raise OSError("simulated unreadable proposal.md (scoped fixture)")
                return real_read_text(self_path, *args, **kwargs)

            with patch.object(Path, "read_text", _scoped_read_text):
                result = gate_result(spec_dir)

            self.assertNotIn("runtime_probe", result)
            self.assertTrue(
                any(
                    "proposal.md read failed for runtime_probe declaration check" in e
                    for e in result["soft_errors"]
                ),
                result["soft_errors"],
            )


class TestRuntimeProbeFoldBlockCombination(unittest.TestCase):
    """SC-3 "block 组合": 触发静态 C-block 的死代码声称 fixture (构造法沿用
    ``TestGateResultSyntheticDeadCodeAnchor``) + 探针 warn 声明 → verdict 必须
    **仍 block**, 不因探针 warn 被降级也不被升级 (TASK-006: "已 block 保持
    block, 不降不升"; 折入代码里 ``if result["verdict"] != "block":
    result["verdict"] = "warn"`` 的 if 守卫正是本测试要钉死的行为)。两个符号
    (死代码符号 / 探针符号) 故意取不同名字, 避免探针声明文本本身意外给死代码
    符号提供一处"引用" (即便 proposal.md 是 *.md 恒归 prose 桶、理论上不会
    误判 alive, 仍不依赖这层隐性安全网)。
    """

    def test_static_block_survives_probe_warn_unchanged(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_block_combo"),
                tasks_md=(
                    "# Tasks\n\n"
                    "- [x] 9.1 集成 `probe_combo_dead_symbol` 到 orchestrator "
                    "(死代码, 应 block)\n"
                ),
                detailed_tasks_yaml=(
                    '  - id: TASK-901\n    parent: "9.1"\n'
                    '    deliverables: ["lib/probe_combo_dead_symbol.py"]\n'
                ),
                spec_id="probe-block-combo",
                extra_files={
                    "lib/probe_combo_dead_symbol.py": "def probe_combo_dead_symbol():\n    pass\n",
                    "README.md": "probe_combo_dead_symbol 仅此散文提及, 从未被生产调用。\n",
                },
            )
            # partition 文件有意不写 → 探针 outcome=warn (分区缺失形态)。
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "block")
            self.assertTrue(
                any("probe_combo_dead_symbol" in r for r in result["blocking_reasons"])
            )
            entry = _assert_probe_warn_family_folded(
                self, result, symbol="probe_block_combo", expected_outcome="warn"
            )
            self.assertIn("missing", entry["reason"])


class TestRuntimeProbeFoldFaultInjection(unittest.TestCase):
    """SC-6: monkeypatch 探针本身 (``spec_complete._rp_probe``) 抛异常 → gate
    不 raise, verdict 从 pass 起点降级到 warn, 照常产出完整 8 键 schema 裁决
    (#95 pre-merge Critical 教训: 探针评估全链的意外异常绝不能让归档流程崩
    溃/挂起)。有意验证 TASK-008 的非对称设计: 崩溃路径**不**追加
    unverified_claims/d_payload 条目 (与 warn/invalid 折入路径不同 —— 源码
    注释: "有意不追加 ... 而非默认延伸到 D tracker"), 也**不**产出
    ``runtime_probe`` 键 (异常路径评估未完成, "exception ⇒ 无部分状态" 的
    延迟单笔写入设计, TASK-005 docstring)。
    """

    def test_probe_crash_downgrades_to_warn_full_schema_preserved(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_fault"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-fault-injection",
            )
            with patch("spec_complete._rp_probe", side_effect=RuntimeError("probe exploded")):
                result = gate_result(spec_dir)

            self.assertEqual(result["verdict"], "warn")
            self.assertNotIn("runtime_probe", result)
            self.assertTrue(
                any("runtime_probe evaluation crashed" in w for w in result["warnings"])
            )
            self.assertTrue(
                any(
                    "runtime_probe evaluation unexpected error" in e
                    for e in result["soft_errors"]
                )
            )
            # TASK-008 非对称设计: 崩溃路径不追加 unverified_claims/d_payload。
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])
            # 照常产出完整 8 键 schema (归档不 abort 无静默)。
            self.assertEqual(
                set(result),
                {
                    "complete",
                    "complete_reason",
                    "verdict",
                    "blocking_reasons",
                    "warnings",
                    "unverified_claims",
                    "d_payload",
                    "soft_errors",
                },
            )


class TestRuntimeProbeFoldCliConsistency(unittest.TestCase):
    """AC-1 (module docstring "多入口一致 verdict 不变量") 扩展到 runtime_probe
    折入路径 —— 不是 TASK-012 verification bullet 的明文条目, 而是与本文件
    既有标准对齐的补充覆盖: ``TestGateResultTriStateSchema.
    test_cli_gate_mode_matches_import_and_exit_codes`` 已经对 pass/block 两条
    既有路径钉了 CLI/import 一致性, 若新增的 runtime_probe 分支没有同等锚点,
    它就是唯一未经 subprocess 边界验证的新增 verdict 来源。
    """

    def test_cli_gate_mode_matches_import_with_probe_declaration(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_cli_parity"),
                tasks_md=TASKS_ALL_CHECKED,
                spec_id="probe-cli-parity",
            )
            _write_probe_partition(root, _PROBE_PARTITION_REL, [_probe_prod_record(1)])
            import_result = gate_result(spec_dir)
            proc = subprocess.run(
                [sys.executable, str(_SPEC_COMPLETE_PY), "--gate", str(spec_dir)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0)
            cli_result = json.loads(proc.stdout)

            # `runtime_probe.ts` 由各自进程独立调用 datetime.now(timezone.utc)
            # 产生 (import 调用 vs subprocess 调用) —— 不是共享/注入的时钟,
            # 跨 subprocess 启动边界允许相差 1 秒级, 故排除 ts 后再逐字节比较
            # 其余全部字段 (含 outcome/count/reason/symbol)。
            for result in (import_result, cli_result):
                self.assertIn("runtime_probe", result)
                datetime.fromisoformat(result["runtime_probe"]["ts"])
            import_result["runtime_probe"] = {
                k: v for k, v in import_result["runtime_probe"].items() if k != "ts"
            }
            cli_result["runtime_probe"] = {
                k: v for k, v in cli_result["runtime_probe"].items() if k != "ts"
            }
            self.assertEqual(
                cli_result,
                import_result,
                "CLI --gate vs import gate_result() drift (runtime_probe branch)",
            )


# ---------------------------------------------------------------------------
# pre-merge R1 fix-verification lock — second block-preservation guard
# [qa M-f7] + L2/proposal-only designed early-exit [SFH C-1③]
# ---------------------------------------------------------------------------


class TestRuntimeProbeFoldBlockSurvivesCrash(unittest.TestCase):
    """[qa M-f7] Second guard lock (spec_complete.py `gate_result`'s outer
    `except Exception` around `_fold_runtime_probe_declaration`, currently at
    line ~1435) — DISTINCT from the guard `TestRuntimeProbeFoldBlockCombination`
    already pins (the `if result["verdict"] != "block":` INSIDE
    `_fold_runtime_probe_declaration` itself, ~line 1236, which only fires
    when the probe cleanly resolves to a warn/invalid OUTCOME). This class
    instead pins the OUTER exception handler's own copy of the same idiom:
    when the runtime_probe fold path CRASHES (raises, rather than merely
    resolving to warn/invalid) while a static C-block dead-code verdict is
    already in effect (the C-block loop runs BEFORE the runtime_probe fold
    section in gate_result()'s pipeline), the crash handler must ALSO
    preserve "block", not downgrade it to "warn". Two independent guards,
    two independent fixtures — one is not a substitute for the other."""

    def test_static_block_survives_probe_crash_unchanged(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_crash_combo"),
                tasks_md=(
                    "# Tasks\n\n"
                    "- [x] 9.1 集成 `probe_crash_dead_symbol` 到 orchestrator "
                    "(死代码, 应 block)\n"
                ),
                detailed_tasks_yaml=(
                    '  - id: TASK-902\n    parent: "9.1"\n'
                    '    deliverables: ["lib/probe_crash_dead_symbol.py"]\n'
                ),
                spec_id="probe-block-crash-combo",
                extra_files={
                    "lib/probe_crash_dead_symbol.py": "def probe_crash_dead_symbol():\n    pass\n",
                    "README.md": "probe_crash_dead_symbol 仅此散文提及, 从未被生产调用。\n",
                },
            )
            with patch(
                "spec_complete._rp_probe",
                side_effect=RuntimeError("probe exploded (combo)"),
            ):
                result = gate_result(spec_dir)

            self.assertEqual(result["verdict"], "block")
            self.assertTrue(
                any("probe_crash_dead_symbol" in r for r in result["blocking_reasons"])
            )
            # Same TASK-008 non-addition contract as the plain fault-injection
            # test — crash path never gains a runtime_probe key or a probe
            # unverified_claims/d_payload entry, block or no block.
            self.assertNotIn("runtime_probe", result)
            self.assertTrue(
                any("runtime_probe evaluation crashed" in w for w in result["warnings"])
            )
            self.assertTrue(
                any(
                    "runtime_probe evaluation unexpected error" in e
                    for e in result["soft_errors"]
                )
            )
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])


class TestRuntimeProbeFoldL2ProposalOnlyEvaporates(unittest.TestCase):
    """[SFH C-1③] designed early-exit lock: a proposal-only (Level 2, **no
    tasks.md AND no detailed-tasks.yaml**) spec's runtime_probe declaration is
    NEVER evaluated. `gate_result()`'s bare tasks.md-absent early return fires
    BEFORE the proposal.md / runtime_probe fold section is ever reached —
    regardless of how the declaration itself would otherwise resolve.

    **Scope narrowed by aria-plugin #113 (SC-12/SC-13).** The lock now covers the
    BARE proposal-only subclass only. A tasks.md-absent spec that DOES carry
    `detailed-tasks.yaml` (task-planner path B) falls through to the fold, because
    #113's precise yaml parsing invalidates the R3 premise ("spec 结构性不完整
    ⇒ 探针无意义") for that subclass specifically — see
    tests/test_gate_yaml_probe_reach.py. This test's fixture passes neither
    source, so its assertions are unchanged (untouched guard, not a carve-out).

    This is a DESIGNED early-exit, not an accidental gap: proposal.md
    §What Changes ③ (R3 裁决) states "gate_result 两个既有早退路径 (tasks.md
    缺失/不可读) 不评估探针 (spec 结构性不完整时探针无意义, designed 行为,
    等同零动作)", and the pre-merge R1 disclosure (2026-07-08) added to the
    same section makes the L2/proposal-only case explicit: "该早退面含合法
    L2/proposal-only spec (tasks.md 合法可缺、complete 可为 true) —— 有声明
    也不评估、零痕迹". The front-matter authoring guidance in
    references/runtime-probe-declaration.md was updated alongside this test
    lock (and re-narrowed by #113 into two sub-states: no-tasks.md-AND-no-yaml
    → still zero evaluation; no-tasks.md-but-yaml-present → evaluated from
    v1.63.0). Zero trace: no `runtime_probe` key, and no
    warnings/unverified_claims/soft_errors additions of ANY kind — not even
    the ones a missing-partition declaration would normally produce at the
    unit level (twin fixture: test_runtime_probe.py::TestProbeTriState::
    test_warn_partition_missing / this file's own
    TestRuntimeProbeFoldWarnForms.test_warn_partition_missing)."""

    def test_l2_proposal_only_declaration_never_evaluated(self):
        with tmp_project() as root:
            spec_dir = make_gate_spec_with_probe(
                root,
                runtime_probe_yaml=_runtime_probe_yaml(symbol="probe_l2_evaporates"),
                tasks_md=None,  # Level 2 / proposal-only — no tasks.md at all
                spec_id="probe-l2-proposal-only",
            )
            # partition intentionally never written either — if this
            # declaration WERE evaluated, it would resolve to outcome="warn"
            # (partition missing), exactly like
            # TestRuntimeProbeFoldWarnForms.test_warn_partition_missing.
            result = gate_result(spec_dir)

            self.assertNotIn("runtime_probe", result)
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unverified_claims"], [])
            self.assertEqual(result["soft_errors"], [])
            self.assertIsNone(result["d_payload"])
            self.assertEqual(result["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
