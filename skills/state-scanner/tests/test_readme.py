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


if __name__ == "__main__":
    unittest.main()
