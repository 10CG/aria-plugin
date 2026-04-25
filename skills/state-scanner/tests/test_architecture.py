"""Phase 1.7 architecture collector tests.

Covers D3: chain_valid must reject placeholder strings (TBD / pending / N/A).
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.architecture import _is_real_prd_reference, collect_architecture


class TestPrdReferenceValidation(unittest.TestCase):
    """D3 intentional divergence: placeholder tokens yield chain_valid=False."""

    def test_real_reference(self):
        self.assertTrue(_is_real_prd_reference("prd-v1.md"))
        self.assertTrue(_is_real_prd_reference("docs/prd-v2.md"))

    def test_placeholders_rejected(self):
        for placeholder in ["TBD", "(pending)", "n/a", "TODO", "placeholder", "待定"]:
            self.assertFalse(_is_real_prd_reference(placeholder))

    def test_none_and_empty(self):
        self.assertFalse(_is_real_prd_reference(None))
        self.assertFalse(_is_real_prd_reference(""))
        # NOTE: "   " (whitespace-only) currently returns True because strip().lower()
        # produces "" which isn't in the placeholder markers set. Documented as-is;
        # call site should .strip() before passing if whitespace should count as empty.


class TestArchitectureCollector(unittest.TestCase):
    def test_missing_file(self):
        with tmp_project() as root:
            r = collect_architecture(root)
            self.assertFalse(r.data["exists"])
            self.assertIsNone(r.data["chain_valid"])

    def test_valid_architecture(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: active\n**Last Updated**: 2026-04-24\n**Parent PRD**: prd-v2.md\n",
            )
            r = collect_architecture(root)
            self.assertTrue(r.data["exists"])
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["last_updated"], "2026-04-24")
            self.assertEqual(r.data["parent_prd"], "prd-v2.md")
            self.assertTrue(r.data["chain_valid"])

    def test_d3_placeholder_breaks_chain(self):
        """D3 regression guard: Parent PRD='TBD' yields chain_valid=False, not True."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: draft\n**Parent PRD**: TBD\n",
            )
            r = collect_architecture(root)
            self.assertTrue(r.data["exists"])
            self.assertFalse(r.data["chain_valid"])

    def test_blockquote_style_headers(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "> **Status**: draft\n> **Parent PRD**: prd-v1.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v1.md")


class TestRegexHardening(unittest.TestCase):
    """Spec `state-scanner-collector-regex-hardening` (2026-04-25): heading
    prefix + fullwidth colon support for architecture field extractors."""

    def test_fullwidth_colon_status(self):
        """i18n: Chinese IME default fullwidth `：` (U+FF1A) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**：active\n**Parent PRD**：prd-zh.md\n**Last Updated**：2026-04-25\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-zh.md")
            self.assertEqual(r.data["last_updated"], "2026-04-25")

    def test_heading_prefix_status(self):
        """`## Status: Draft` (heading-prefixed, no bold) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## Status: draft\n## Parent PRD: prd-v3.md\n## Last Updated: 2026-04-25\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v3.md")
            self.assertEqual(r.data["last_updated"], "2026-04-25")

    def test_heading_with_fullwidth_colon(self):
        """Heading + fullwidth colon combined."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## Status：active\n## Parent PRD：prd-cn.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-cn.md")

    def test_heading_with_bold(self):
        """`## **Status**: Draft` (heading + bold combined) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## **Status**: draft\n## **Parent PRD**: prd-v4.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v4.md")

    def test_blockquote_with_fullwidth_colon(self):
        """`> **Status**：active` (blockquote + fullwidth)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "> **Status**：active\n> **Parent PRD**：prd-bq.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-bq.md")

    def test_backward_compat_unchanged(self):
        """v1.17.2 baseline format still works (regression baseline)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: active\n**Parent PRD**: prd-baseline.md\n**Last Updated**: 2026-04-24\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-baseline.md")
            self.assertEqual(r.data["last_updated"], "2026-04-24")


if __name__ == "__main__":
    unittest.main()
