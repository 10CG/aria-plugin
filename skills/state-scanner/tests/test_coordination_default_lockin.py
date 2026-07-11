"""Part A1 lock-in (coordination-claim-lifecycle-and-overlap).

`state_scanner.coordination.enabled` 的默认值没有 python 解析点 —— config-loader
SKILL.md 就是默认值 SOT, AI 编排层按文档解析。因此 default 翻转 (false→true) 的
lock-in 测试落在文档层: 机械断言 SOT 及其引用文档不回退 (精神同 memory
feedback_default_value_flip_needs_lock_in_test: 改默认值必须配断言新默认的测试)。
"""
import re

import unittest
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]  # aria/skills/


def _read(rel: str) -> str:
    return (_SKILLS / rel).read_text(encoding="utf-8")


class TestCoordinationEnabledDefaultLockin(unittest.TestCase):
    def test_config_loader_sot_default_true(self):
        text = _read("config-loader/SKILL.md")
        # 提取 state_scanner.coordination.enabled 块 (到下一个非缩进行/键为止)
        m = re.search(
            r"state_scanner\.coordination\.enabled:\n((?:[ \t]+.*\n)+)", text
        )
        self.assertIsNotNone(m, "coordination.enabled 键从 config-loader SOT 消失")
        block = m.group(1)
        self.assertIn(
            "default: true",
            block,
            "Part A1 默认翻转回退: coordination.enabled 默认必须是 true (opt-out)",
        )
        self.assertNotIn("default: false", block)

    def test_no_stale_default_false_wording(self):
        """引用文档不得残留「默认 false / opt-in」旧措辞 (针对 coordination.enabled)."""
        for rel in (
            "state-scanner/SKILL.md",
            "state-scanner/references/layer-l-integration.md",
        ):
            text = _read(rel)
            for line in text.splitlines():
                if "coordination.enabled" not in line:
                    continue
                # 「默认 false→true」是变更叙述, 不算残留 — 负向断言排除 →
                self.assertNotRegex(
                    line,
                    r"默认\s*`?false`?(?!\s*→|→)",
                    f"{rel} 残留 coordination.enabled 默认 false 旧措辞: {line!r}",
                )

    def test_phase_b_require_claim_present(self):
        """A1-2: Phase B 入口两个 skill 都必须带 REQUIRE claim 步骤."""
        self.assertIn("B.0 - REQUIRE claim", _read("phase-b-developer/SKILL.md"))
        self.assertIn("REQUIRE claim", _read("branch-manager/SKILL.md"))

    def test_phase_d_release_wiring_present(self):
        """Part C-5: phase-d-closer 必须带 D.2b claim 释放接线."""
        text = _read("phase-d-closer/SKILL.md")
        self.assertIn("D.2b", text)
        self.assertIn("release_gate.py", text)


if __name__ == "__main__":
    unittest.main()
