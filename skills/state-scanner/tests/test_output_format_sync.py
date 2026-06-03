"""OpenSpec state-scanner-output-cap-hardening (#72, v1.38.0) — automated
sync-check guarding the canonical output-block set against drift between
SKILL.md (the compact field skeleton) and references/output-formats.md (the
detailed per-scenario source).

Root-cause-recurrence guard: v1.32.0 progressive-disclosure refactor moved the
field-level skeleton out of SKILL.md into the reference, so the two could drift
(a block renamed / dropped on one side only) with nothing to catch it. This
test turns "format completeness" into a deterministic assertion — the dimension
the v1.32.0 AB run failed to cover (per proposal Problem 1 / Rule #6 substitute).

Canonical decision (TG-A.0 reconcile, OQ4 locked 2026-06-03): the canonical set
is the 10 CORE top-level blocks below. README 同步 / Forgejo 配置 / 插件依赖 /
Skill-AB are CONDITIONAL sub-blocks (shown only in relevant scenarios), NOT
separate canonical top-level blocks. All 10 canonical headers are confirmed
present somewhere in output-formats.md, so no rewrite of that file is needed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_OUTPUT_FORMATS_MD = _SKILL_DIR / "references" / "output-formats.md"

# Exact header strings (emoji + name). Copied byte-for-byte from both docs so
# the assertion catches emoji/variation-selector drift as well as renames.
CANONICAL_BLOCKS: tuple[str, ...] = (
    "📍 当前状态",
    "📊 变更分析",
    "📄 需求状态",
    "🏗️ 架构状态",
    "📋 OpenSpec 状态",
    "🛡️ 审计状态",
    "🔧 自定义检查",
    "🔄 同步状态",
    "🎫 Open Issues",
    "🎯 推荐工作流",
)


class TestCanonicalBlockSync(unittest.TestCase):
    """The 10 canonical block headers must appear in BOTH docs (no drift)."""

    @classmethod
    def setUpClass(cls):
        cls.skill_text = _SKILL_MD.read_text(encoding="utf-8")
        cls.formats_text = _OUTPUT_FORMATS_MD.read_text(encoding="utf-8")

    def test_skill_md_exists(self):
        self.assertTrue(_SKILL_MD.is_file(), f"missing {_SKILL_MD}")

    def test_output_formats_md_exists(self):
        self.assertTrue(
            _OUTPUT_FORMATS_MD.is_file(), f"missing {_OUTPUT_FORMATS_MD}"
        )

    def test_all_canonical_blocks_in_skill_md(self):
        missing = [b for b in CANONICAL_BLOCKS if b not in self.skill_text]
        self.assertEqual(
            missing,
            [],
            f"SKILL.md skeleton missing canonical block(s): {missing}. "
            "Add the field skeleton entry or reconcile the canonical set.",
        )

    def test_all_canonical_blocks_in_output_formats_md(self):
        missing = [b for b in CANONICAL_BLOCKS if b not in self.formats_text]
        self.assertEqual(
            missing,
            [],
            f"output-formats.md missing canonical block(s): {missing}. "
            "A block was renamed/dropped on one side only — reconcile drift.",
        )

    def test_skill_md_declares_block_count(self):
        """SKILL.md states '10 个 canonical 区块' — keep the count honest."""
        self.assertEqual(len(CANONICAL_BLOCKS), 10)
        self.assertIn(
            f"{len(CANONICAL_BLOCKS)} 个 canonical 区块",
            self.skill_text,
            "SKILL.md declared block count drifted from CANONICAL_BLOCKS length.",
        )

    def test_skill_md_skeleton_has_field_separator(self):
        """Each canonical block in the skeleton must carry field-level guidance
        (a ' — ' field list), not just a bare name — the #72 root fix."""
        for block in CANONICAL_BLOCKS:
            idx = self.skill_text.find(block)
            self.assertNotEqual(idx, -1, f"{block} absent from SKILL.md")
            # The line containing the header should also contain the ' — ' field
            # separator (em-dash) introducing key fields.
            line_end = self.skill_text.find("\n", idx)
            line = self.skill_text[idx:line_end if line_end != -1 else None]
            self.assertIn(
                " — ",
                line,
                f"canonical block '{block}' has no field skeleton "
                "(' — fields...') on its line in SKILL.md (#72 field-drift fix).",
            )


if __name__ == "__main__":
    unittest.main()
