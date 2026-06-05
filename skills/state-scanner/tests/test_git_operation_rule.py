"""Aria #135 TG-B — structural existence test for the git_operation_in_progress
recommendation rule. Prose AI behavior (stage-2 degrade) is verified by dogfood;
this locks the *structural* contract: the rule row exists and references the
collector field, so progressive-disclosure refactors can't silently drop it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_RULES_MAIN = _SKILL_ROOT / "RECOMMENDATION_RULES.md"
_RULES_ADVANCED = _SKILL_ROOT / "references" / "rules" / "advanced-rules.md"


class TestGitOperationRule(unittest.TestCase):
    def setUp(self):
        self.main = _RULES_MAIN.read_text(encoding="utf-8")
        self.advanced = _RULES_ADVANCED.read_text(encoding="utf-8")

    def test_rule_id_in_overview_table(self):
        self.assertIn("`git_operation_in_progress`", self.main)

    def test_trigger_references_collector_field(self):
        # The rule MUST key off the TG-A collector field, not a re-derived signal.
        self.assertIn("git.git_operation_in_progress.operation", self.main)

    def test_has_conflicts_escalation_documented(self):
        # B4 (R2 qa): the rule wording must escalate on conflicts.
        self.assertIn("has_conflicts", self.main)

    def test_detail_block_in_advanced_rules(self):
        self.assertIn("git_operation_in_progress", self.advanced)
        self.assertIn("git.git_operation_in_progress.operation", self.advanced)

    def test_orthogonal_to_interrupt_status(self):
        # Spec invariant: rule must not claim to mutate interrupt.status.
        self.assertIn("正交", self.advanced)


if __name__ == "__main__":
    unittest.main()
