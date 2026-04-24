"""Phase 1.10 audit collector tests."""

from __future__ import annotations

import os
import time
import unittest

from _helpers import make_audit_report, tmp_project, write_file
from collectors.audit import collect_audit


class TestAuditAbsent(unittest.TestCase):
    def test_no_audit_dir(self):
        with tmp_project() as root:
            r = collect_audit(root)
            self.assertIsNone(r.data["enabled"])
            self.assertIsNone(r.data["last_audit"])

    def test_empty_audit_dir(self):
        with tmp_project() as root:
            (root / ".aria" / "audit-reports").mkdir(parents=True)
            r = collect_audit(root)
            self.assertTrue(r.data["enabled"])
            self.assertIsNone(r.data["last_audit"])


class TestAuditFrontmatter(unittest.TestCase):
    def test_simple_frontmatter_parsing(self):
        with tmp_project() as root:
            make_audit_report(
                root,
                checkpoint="post_spec",
                verdict="PASS",
                converged=True,
                timestamp="2026-04-24T1000Z",
            )
            r = collect_audit(root)
            self.assertEqual(r.data["last_audit"]["checkpoint"], "post_spec")
            self.assertEqual(r.data["last_audit"]["verdict"], "PASS")
            # R1-I6: boolean coercion
            self.assertIs(r.data["last_audit"]["converged"], True)

    def test_r1_i6_boolean_coercion(self):
        """R1-I6 regression: 'false' string must coerce to False, not stay 'false'."""
        with tmp_project() as root:
            make_audit_report(root, "pre_merge", "FAIL", converged=False)
            r = collect_audit(root)
            self.assertIs(r.data["last_audit"]["converged"], False)


class TestAuditLatestSelection(unittest.TestCase):
    def test_picks_most_recent_by_mtime(self):
        with tmp_project() as root:
            old = make_audit_report(
                root, "post_spec", "OLD", timestamp="2026-01-01T0000Z"
            )
            # Force old mtime
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            make_audit_report(root, "pre_merge", "LATEST", timestamp="2026-04-24T1000Z")
            r = collect_audit(root)
            self.assertEqual(r.data["last_audit"]["verdict"], "LATEST")


class TestAuditMalformed(unittest.TestCase):
    def test_no_frontmatter(self):
        with tmp_project() as root:
            write_file(
                root / ".aria" / "audit-reports" / "2026-04-24-report.md",
                "# Just a heading\nno frontmatter\n",
            )
            r = collect_audit(root)
            # Still returns last_audit, but fields are None
            self.assertIsNone(r.data["last_audit"]["checkpoint"])


if __name__ == "__main__":
    unittest.main()
