"""Phase 1.9 standards submodule presence collector tests."""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.standards import collect_standards


class TestStandardsCollector(unittest.TestCase):
    def test_no_gitmodules(self):
        with tmp_project() as root:
            r = collect_standards(root)
            self.assertFalse(r.data["registered"])
            self.assertFalse(r.data["initialized"])

    def test_registered_but_not_initialized(self):
        with tmp_project() as root:
            write_file(
                root / ".gitmodules",
                """[submodule "standards"]
\tpath = standards
\turl = https://example.com/standards.git
""",
            )
            r = collect_standards(root)
            self.assertTrue(r.data["registered"])
            self.assertFalse(r.data["initialized"])

    def test_initialized(self):
        with tmp_project() as root:
            write_file(
                root / ".gitmodules",
                """[submodule "standards"]
\tpath = standards
\turl = https://example.com/standards.git
""",
            )
            write_file(root / "standards" / "README.md", "# standards\n")
            r = collect_standards(root)
            self.assertTrue(r.data["registered"])
            self.assertTrue(r.data["initialized"])

    def test_other_submodule_not_confused_as_standards(self):
        with tmp_project() as root:
            write_file(
                root / ".gitmodules",
                """[submodule "aria"]
\tpath = aria
\turl = https://example.com/aria.git
""",
            )
            r = collect_standards(root)
            self.assertFalse(r.data["registered"])


if __name__ == "__main__":
    unittest.main()
