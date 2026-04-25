"""Phase 1.8 README sync collector tests."""

from __future__ import annotations

import json
import unittest

from _helpers import tmp_project, write_file
from collectors.readme import collect_readme_sync


class TestReadmeAbsent(unittest.TestCase):
    def test_no_readme(self):
        with tmp_project() as root:
            r = collect_readme_sync(root)
            self.assertFalse(r.data["root"]["exists"])
            self.assertFalse(r.data["submodules"]["aria"]["exists"])


class TestVersionExtraction(unittest.TestCase):
    def test_bold_version_header(self):
        with tmp_project() as root:
            write_file(
                root / "README.md",
                "# Project\n\n**Version**: v1.3.0\n",
            )
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.3.0")

    def test_chinese_version_header(self):
        with tmp_project() as root:
            write_file(root / "README.md", "**版本**: 1.4.0\n")
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.4.0")

    def test_no_version_in_readme(self):
        with tmp_project() as root:
            write_file(root / "README.md", "# No version tag here\n")
            r = collect_readme_sync(root)
            self.assertIsNone(r.data["root"]["version"])


class TestVersionPatternBlockquote(unittest.TestCase):
    """v1.17.1 regression suite for _VERSION_PAT blockquote-prefix bug.

    Latent since v1.16.0: pattern `^\\s*\\*\\*` did not match `> **Version**:`
    blockquote prefix used in actual aria/README.md and root README.md.
    Smoke benchmark missed it because eval-3 only checked field-presence,
    not field truthiness (version_match=None silently passed).

    Fix: regex changed to `^>?\\s*\\*\\*` (consistent with architecture.py).
    """

    def test_blockquote_version_match_aria_submodule(self):
        """Actual aria/README.md format: '> **Version**: 1.17.0 | ...'"""
        with tmp_project() as root:
            write_file(
                root / "aria" / "README.md",
                "> **Version**: 1.17.0 | **Released**: 2026-04-25\n",
            )
            write_file(
                root / "aria" / ".claude-plugin" / "plugin.json",
                json.dumps({"version": "1.17.0"}),
            )
            r = collect_readme_sync(root)
            self.assertEqual(
                r.data["submodules"]["aria"]["readme_version"], "1.17.0"
            )
            self.assertTrue(r.data["submodules"]["aria"]["version_match"])

    def test_blockquote_version_mismatch_detected(self):
        """Blockquote form with mismatched version must still flag drift."""
        with tmp_project() as root:
            write_file(root / "aria" / "README.md", "> **Version**: 1.16.0\n")
            write_file(
                root / "aria" / ".claude-plugin" / "plugin.json",
                json.dumps({"version": "1.17.0"}),
            )
            r = collect_readme_sync(root)
            self.assertEqual(
                r.data["submodules"]["aria"]["readme_version"], "1.16.0"
            )
            self.assertFalse(r.data["submodules"]["aria"]["version_match"])

    def test_no_prefix_version_still_matches(self):
        """Regression baseline: bare bold form must continue to work."""
        with tmp_project() as root:
            write_file(root / "README.md", "**Version**: 1.5.0\n")
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.5.0")

    def test_blockquote_with_v_prefix(self):
        """Blockquote + v-prefix combined: `> **Version**: v1.17.0`."""
        with tmp_project() as root:
            write_file(root / "README.md", "> **Version**: v1.17.0\n")
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.17.0")

    def test_blockquote_chinese_key(self):
        """Blockquote + Chinese key: `> **版本**: 1.17.0`."""
        with tmp_project() as root:
            write_file(root / "README.md", "> **版本**: 1.17.0\n")
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.17.0")

    def test_smoke_false_pass_guard(self):
        """Field-presence-only assertion would have hidden v1.17.0 latent bug.
        This test asserts truthiness (not None) of version_match when both
        sides exist. Catches the smoke-benchmark eval-3 false-pass pattern."""
        with tmp_project() as root:
            write_file(root / "aria" / "README.md", "> **Version**: 1.17.0\n")
            write_file(
                root / "aria" / ".claude-plugin" / "plugin.json",
                json.dumps({"version": "1.17.0"}),
            )
            r = collect_readme_sync(root)
            aria_data = r.data["submodules"]["aria"]
            self.assertIsNotNone(
                aria_data["readme_version"],
                "readme_version must not be None for blockquote format",
            )
            self.assertIsNotNone(
                aria_data["version_match"],
                "version_match None means one side failed to parse",
            )


class TestAriaSubmoduleVersionMatch(unittest.TestCase):
    def test_matching_versions(self):
        with tmp_project() as root:
            write_file(
                root / "aria" / ".claude-plugin" / "plugin.json",
                json.dumps({"version": "1.16.0"}),
            )
            write_file(root / "aria" / "README.md", "**Version**: 1.16.0\n")
            r = collect_readme_sync(root)
            self.assertTrue(r.data["submodules"]["aria"]["version_match"])

    def test_mismatched_versions(self):
        with tmp_project() as root:
            write_file(
                root / "aria" / ".claude-plugin" / "plugin.json",
                json.dumps({"version": "1.17.0"}),
            )
            write_file(root / "aria" / "README.md", "**Version**: 1.16.0\n")
            r = collect_readme_sync(root)
            self.assertFalse(r.data["submodules"]["aria"]["version_match"])

    def test_missing_plugin_json(self):
        with tmp_project() as root:
            write_file(root / "aria" / "README.md", "**Version**: 1.16.0\n")
            r = collect_readme_sync(root)
            self.assertIsNone(r.data["submodules"]["aria"]["version_match"])

    def test_malformed_plugin_json(self):
        with tmp_project() as root:
            write_file(root / "aria" / ".claude-plugin" / "plugin.json", "not json")
            r = collect_readme_sync(root)
            self.assertEqual(len(r.errors), 1)


class TestRegexHardeningHeading(unittest.TestCase):
    """Spec `state-scanner-collector-regex-hardening` (2026-04-25): heading
    prefix support for `## Version: v1.2.3` form (no bold)."""

    def test_heading_prefix_version(self):
        with tmp_project() as root:
            write_file(root / "README.md", "## Version: 1.2.3\n")
            r = collect_readme_sync(root)
            self.assertEqual(r.data["root"]["version"], "1.2.3")


if __name__ == "__main__":
    unittest.main()
