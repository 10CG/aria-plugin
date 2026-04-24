"""Phase 1.4 UPM state collector tests.

Covers D4: YAML `key: |` block scalars return None (not literal '|').
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.upm import _extract_yaml_scalar, collect_upm_state


class TestYamlScalarExtraction(unittest.TestCase):
    def test_simple_key_value(self):
        block = "current_phase: Phase4\ncurrent_cycle: Cycle9\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "Phase4")

    def test_colon_in_value_preserved(self):
        """First-colon partition: `key: M1: Layer 2` → value = 'M1: Layer 2'."""
        block = "current_phase: M1: Layer 2\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "M1: Layer 2")

    def test_inline_comment_stripped(self):
        block = "active_module: mobile # note\n"
        self.assertEqual(_extract_yaml_scalar(block, "active_module"), "mobile")

    def test_quoted_value(self):
        block = 'active_module: "mobile"\n'
        self.assertEqual(_extract_yaml_scalar(block, "active_module"), "mobile")

    def test_d4_block_scalar_returns_none(self):
        """D4 intentional divergence: `key: |` must return None, not literal '|'."""
        block = "description: |\n  multi-line\n  content\n"
        self.assertIsNone(_extract_yaml_scalar(block, "description"))

    def test_d4_other_block_markers(self):
        for marker in [">", "|-", ">-", "|+", ">+"]:
            block = f"k: {marker}\n"
            self.assertIsNone(
                _extract_yaml_scalar(block, "k"),
                msg=f"marker {marker!r}",
            )

    def test_missing_key_returns_none(self):
        self.assertIsNone(_extract_yaml_scalar("foo: bar\n", "missing"))

    def test_comments_and_blanks_skipped(self):
        block = "# comment\n\ncurrent_phase: X\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "X")


class TestUpmCollector(unittest.TestCase):
    def test_no_upm_file(self):
        with tmp_project() as root:
            r = collect_upm_state(root)
            self.assertFalse(r.data["configured"])
            self.assertIsNone(r.data["current_phase"])

    def test_html_comment_block(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                """# UPM

<!-- UPMv2-STATE
current_phase: Phase4
current_cycle: Cycle9
active_module: mobile
-->
""",
            )
            r = collect_upm_state(root)
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["current_phase"], "Phase4")
            self.assertEqual(r.data["active_module"], "mobile")

    def test_fenced_yaml_block(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                """# UPM

```yaml
UPMv2-STATE:
current_phase: PhaseA
current_cycle: C1
active_module: backend
```
""",
            )
            r = collect_upm_state(root)
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["current_phase"], "PhaseA")


if __name__ == "__main__":
    unittest.main()
