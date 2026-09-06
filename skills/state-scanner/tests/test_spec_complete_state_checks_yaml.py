#!/usr/bin/env python3
"""`.aria/state-checks.yaml` 是运行时调用面, 不是声明性元数据 (2026-09-06).

**症状**: 母 Spec `a1-entry-claim-duplicate-work-guard` 的 D.2 归档闸门报
``verdict=block``, 唯一 blocking reason 是
``symbol 'coordination_probe' has zero production semantic reference
(dead-code-on-arrival)`` —— 而 ``coordination_probe.py`` 每次 ``/state-scanner``
跑 Phase 1.11 都被真实执行 (custom check ``coordination-gate-invocation``,
本仓 ``.aria/state-checks.yaml`` 的 ``command:`` 字段), 且该 check 当日为 pass。

**根因** (逐层读源码): ``.aria/state-checks.yaml`` 三个判据都不命中 ——
``_is_hooks_or_config_path`` 只认 ``hooks.json`` 与 ``.aria/config.json``
(注释明写 Deliberately NARROW); ``_is_ci_workflow_path`` 只认 ``/.github/`` 与
``/.forgejo/``; 于是落进「非 CI yaml = 声明意图非运行时调用面」被归为 prose。
而 ``coordination_probe.py`` 文件存在 ⇒ ``_symbol_has_python_definition`` 为 True
⇒ 不走「无 Python 定义 → fail-toward-warn」的降级分支 ⇒ 「有定义 ∧ 零生产引用」
= 高置信 dead-code → block。

**处置**: 把 ``.aria/state-checks.yaml`` 认作注册面。它与已在白名单里的
``hooks.json`` / ``.aria/config.json`` 是同一性质 —— **声明式注册 + 运行时真执行**;
区别于 ``detailed-tasks.yaml`` 那类「声明意图, 不能自证已引用」的规划元数据。
判据仍要求**字面脚本路径**匹配 (``_literal_script_path_match``), 所以仅在 yaml 里
提一句符号名不会被误判 alive。

**极性说明**: 本改动方向是 dead(block) → alive, 即**只减少 block 不增加**。
「只提名字不给路径」仍不算 alive (由 ``test_mere_mention_without_script_path_is_not_alive``
钉住), 所以不会把真死代码放行。

每条测试的「它怎么会红」写在各自 docstring 里 (memory `test-claims-vs-verifies`)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

# `_helpers` 已把 scripts/ 放进 sys.path —— 不要再插一次 position 0 (与
# test_spec_complete_json_branch / _yaml_branch 同款注意事项)。
_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import (  # noqa: E402
    _classify_file_occurrence,
    classify_symbol_liveness,
)

_SYMBOL = "coordination_probe"

# 本仓 `.aria/state-checks.yaml` 里那条 check 的最小忠实复现 —— 承重成分是
# `command:` 里的**字面脚本路径**, 而不是 name 里的符号名。
_STATE_CHECKS = (
    "checks:\n"
    '  - name: "coordination-gate-invocation"\n'
    '    severity: "warning"\n'
    "    command: |\n"
    "      python3 aria/skills/state-scanner/scripts/coordination_probe.py .\n"
    '    fix: "跑一次 Phase B 入口认领"\n'
)

# 负控: 同一文件只提符号名、不含脚本路径 —— 必须仍判 not alive。
_STATE_CHECKS_NAME_ONLY = (
    "checks:\n"
    '  - name: "coordination-gate-invocation"\n'
    '    severity: "warning"\n'
    '    fix: "见 coordination_probe 的说明"\n'
)


def _project_with(root, rel_path, text, with_definition=True):
    write_file(root / rel_path, text)
    if with_definition:
        write_file(
            root / "aria/skills/state-scanner/scripts/coordination_probe.py",
            # 自身含符号名 —— 忠实于真实文件 (`coordination_probe.py:85` 的注释)。
            # 承重: 缺了它该文件不进 occurrences, `_symbol_has_python_definition` 的
            # (c)「存在名为 SYMBOL.py 的模块文件」支不命中, 基线只会红在 ambiguous
            # 而复现不出真实的 dead/block (2026-09-06 首版夹具就是这么写的, 三态亲跑抓到)。
            "# coordination_probe: Layer L 运行时探针\n\ndef main():\n    return 0\n",
        )
    return root


class TestStateChecksYamlIsRuntimeCallSurface(unittest.TestCase):
    def test_state_checks_yaml_with_script_path_is_alive(self):
        """怎么会红: 修复前 `.aria/state-checks.yaml` 落「非 CI yaml」支被判 prose,
        alive=False。修复后按注册面处理 ⇒ alive=True。"""
        with tmp_project() as root:
            rel = ".aria/state-checks.yaml"
            _project_with(root, rel, _STATE_CHECKS)
            got = _classify_file_occurrence(rel, root, _SYMBOL, set())
            self.assertTrue(got["alive"], f"应判 alive (运行时调用面): {got}")
            self.assertFalse(got["prose"], f"不应归 prose: {got}")

    def test_symbol_liveness_is_alive_not_dead(self):
        """怎么会红: 修复前该符号「有 Python 定义 ∧ 全部出现均非 alive」⇒ status=dead
        ⇒ 上游把它写成 blocking_reason。修复后应为 alive。"""
        with tmp_project() as root:
            _project_with(root, ".aria/state-checks.yaml", _STATE_CHECKS)
            got = classify_symbol_liveness(_SYMBOL, root, set())
            self.assertEqual(
                got["status"], "alive",
                f"应 alive 而非 {got['status']}; unclassified={got.get('unclassified_files')}",
            )

    def test_mere_mention_without_script_path_is_not_alive(self):
        """负控 —— 怎么会红: 若把改法写成「只要路径是 state-checks.yaml 就 alive」,
        这条会变绿失败。判据必须仍要求字面脚本路径。"""
        with tmp_project() as root:
            rel = ".aria/state-checks.yaml"
            _project_with(root, rel, _STATE_CHECKS_NAME_ONLY)
            got = _classify_file_occurrence(rel, root, _SYMBOL, set())
            self.assertFalse(got["alive"], f"只提名字不给脚本路径, 不应算 alive: {got}")

    def test_other_non_ci_yaml_still_not_alive(self):
        """负控 —— 怎么会红: 若把改法写成「所有 yaml 都算调用面」, 这条会变绿失败。
        `detailed-tasks.yaml` 那类规划元数据必须维持原判 (声明意图不能自证已引用)。"""
        with tmp_project() as root:
            rel = "openspec/changes/x/detailed-tasks.yaml"
            _project_with(
                root, rel,
                "tasks:\n  - id: TASK-001\n    deliverables:\n"
                "      - aria/skills/state-scanner/scripts/coordination_probe.py\n",
            )
            got = _classify_file_occurrence(rel, root, _SYMBOL, set())
            self.assertFalse(got["alive"], f"规划元数据不应算调用面: {got}")


if __name__ == "__main__":
    unittest.main()
