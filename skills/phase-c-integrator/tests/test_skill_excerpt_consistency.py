"""Aria#257 I-1 定向 fixture (Rule #6 第三行 substitute)。

点名行为: AI 执行 §C.2.4.5 submodule gate 时的判定认知 — SKILL.md 内嵌摘录
必须反映 scripts/submodule_gate.sh 的实际判定 (v1.77.2/v1.77.3: BASE_REF
解析 + 基线不可解析 fail-loud), 不得复活 #223 修掉的「写死 origin/master +
无条件 nil-SHA PASS」认知。

为什么固定测试集测不到: ab-suite/phase-c-integrator.json 3 evals 全是
C.1/C.2 提交-冲突-推送场景; pre-merge-gate 套件 (workflow_skill_subextension)
测的是 §C.2.4 CI gate — 均无 gate 判定维度 (套件缺口已开 issue 跟踪)。

可证伪性: 回退 SKILL.md 摘录同步 (删 BASE_REF / BASELINE_REF_UNRESOLVED /
以脚本为准注, 或恢复裸 origin/master 判定) → 本测试转红。
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
GATE_SH = Path(__file__).resolve().parents[1] / "scripts" / "submodule_gate.sh"


def _c245_excerpt() -> str:
    """Extract the §C.2.4.5 section (up to the next ### heading or EOF)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.find("### C.2.4.5 Submodule Pointer Regression Gate")
    assert start != -1, "§C.2.4.5 section not found in SKILL.md"
    nxt = text.find("\n### ", start + 1)
    return text[start : nxt if nxt != -1 else None]


class TestSkillExcerptConsistency(unittest.TestCase):
    def test_excerpt_carries_baseref_semantics(self):
        excerpt = _c245_excerpt()
        self.assertIn("BASE_REF", excerpt, "摘录必须携带基线 ref 解析 (Aria#223)")
        self.assertIn(
            "BASELINE_REF_UNRESOLVED",
            excerpt,
            "摘录必须携带基线不可解析 fail-loud 语义 (Aria#223)",
        )
        self.assertIn(
            "symbolic-ref",
            excerpt,
            "摘录必须展示 origin/HEAD 解析路径 (Aria#223)",
        )
        self.assertIn(
            "remote set-head",
            excerpt,
            "摘录必须携带补救提示 (git remote set-head origin -a)",
        )

    def test_excerpt_has_no_hardcoded_baseline_judgment(self):
        # Aria#257 I-3 (review): line-family closure, not exact-string
        # enumeration — a renamed/partially-reverted line (e.g. the v1.77.2
        # original shape) must not slip past. Every gate judgment line in the
        # excerpt must reference "$BASE_REF"; a hardcoded origin/master
        # fallback TO it is legal only in the BASE_REF resolution line itself.
        excerpt = _c245_excerpt()
        import re
        judgment_lines = [
            ln for ln in excerpt.splitlines()
            if re.match(r"^(BEFORE_REMOTE|AFTER_REMOTE|MASTER_PTR)=", ln.strip())
        ]
        self.assertTrue(
            judgment_lines, "摘录未找到基线判定行族 (BEFORE/AFTER_REMOTE, MASTER_PTR)"
        )
        for ln in judgment_lines:
            self.assertIn(
                "$BASE_REF", ln,
                f"基线判定行走裸 ref 未 BASE_REF 化 (#223 形态逃逸): {ln}",
            )

    def test_excerpt_exit_codes_match_env_vs_verdict_classes(self):
        # Aria#257 I-1 (review): fetch-failure and rewrite are ENV-class exits
        # (2/3) with env remediation; exit 1 is reserved for verdict-class
        # (REGRESSION/DIVERGENT). The excerpt must not teach the old exit-1
        # shape on env failures.
        excerpt = _c245_excerpt()
        self.assertIn("exit 2", excerpt, "fetch 失败应 exit 2 (环境类)")
        self.assertIn("exit 3", excerpt, "基线 rewrite 应 exit 3 (环境类)")
        for ln in excerpt.splitlines():
            if "rewritten" in ln and "BLOCK" in ln:
                self.assertIn(
                    "$BASE_REF", ln,
                    f"rewrite 消息残留写死 origin/master: {ln}",
                )

    def test_excerpt_defers_to_script(self):
        excerpt = _c245_excerpt()
        self.assertIn(
            "submodule_gate.sh 为准",
            excerpt,
            "摘录须声明「判定以脚本为准」防双源漂移 (Aria#257 I-1)",
        )

    def test_gate_script_implements_what_excerpt_claims(self):
        script = GATE_SH.read_text(encoding="utf-8")
        # The semantics the excerpt claims must actually exist in the script
        # (excerpt↔script bidirectional consistency, not just excerpt↔claim).
        for token in (
            "BASELINE_REF_UNRESOLVED",
            "symbolic-ref --short refs/remotes/origin/HEAD",
            "BASE_REF_OK=0",
        ):
            self.assertIn(token, script, f"脚本缺摘录所声称的语义: {token}")


if __name__ == "__main__":
    unittest.main()
