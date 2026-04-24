"""Phase 1.6 OpenSpec + shared _status collector tests.

Covers D1/D2/D5 (intentional divergences from v2.9 prose: Approved/Reviewed/
Active/Deprecated/Archived preserved as distinct states, not collapsed).
"""

from __future__ import annotations

import unittest

from _helpers import make_openspec, tmp_project, write_file
from collectors._status import _extract_status, _normalize_status
from collectors.openspec import collect_openspec


class TestStatusExtraction(unittest.TestCase):
    def test_bold_key(self):
        self.assertEqual(_extract_status("**Status**: Draft"), "Draft")

    def test_chinese_key(self):
        self.assertEqual(_extract_status("**状态**: 进行中"), "进行中")

    def test_blockquote(self):
        self.assertEqual(_extract_status("> **Status**: Approved"), "Approved")

    def test_yaml_like(self):
        self.assertEqual(_extract_status("Status: Done"), "Done")

    def test_markdown_heading_r1_i7(self):
        # R1-I7 fix: heading-prefixed Status
        self.assertEqual(_extract_status("## Status: Active"), "Active")

    def test_table_column(self):
        text = "| Field | Value |\n|-------|-------|\n| Status | Reviewed |"
        self.assertEqual(_extract_status(text), "Reviewed")

    def test_no_match(self):
        self.assertIsNone(_extract_status("no status header here"))


class TestStatusNormalization(unittest.TestCase):
    """D1-D5: Intentional divergences — preserved distinct states."""

    def test_d1_approved_preserved(self):
        # D1: Approved must NOT collapse to ready
        self.assertEqual(_normalize_status("Approved"), "approved")

    def test_d2_reviewed_preserved(self):
        # D2: Reviewed must NOT collapse to pending
        self.assertEqual(_normalize_status("Reviewed"), "reviewed")

    def test_d5_active_preserved(self):
        self.assertEqual(_normalize_status("Active"), "active")

    def test_d5_deprecated_preserved(self):
        self.assertEqual(_normalize_status("Deprecated"), "deprecated")

    def test_d5_archived_preserved(self):
        self.assertEqual(_normalize_status("Archived"), "archived")

    def test_done_family(self):
        self.assertEqual(_normalize_status("Done"), "done")
        self.assertEqual(_normalize_status("Complete"), "done")

    def test_in_progress_variants(self):
        self.assertEqual(_normalize_status("In Progress"), "in_progress")
        self.assertEqual(_normalize_status("in-progress"), "in_progress")
        self.assertEqual(_normalize_status("进行中"), "in_progress")

    def test_draft_pending_placeholder_collapse(self):
        self.assertEqual(_normalize_status("Draft"), "pending")
        self.assertEqual(_normalize_status("(pending)"), "pending")
        self.assertEqual(_normalize_status("placeholder"), "pending")

    def test_none_is_unknown(self):
        self.assertEqual(_normalize_status(None), "unknown")


class TestOpenspecCollector(unittest.TestCase):
    def test_no_openspec_dir(self):
        with tmp_project() as root:
            r = collect_openspec(root)
            self.assertFalse(r.data["configured"])
            self.assertEqual(r.data["changes"]["total"], 0)
            self.assertEqual(r.data["archive"]["total"], 0)

    def test_empty_changes_dir(self):
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            (root / "openspec" / "archive").mkdir(parents=True)
            r = collect_openspec(root)
            # 1b: empty changes/ is legitimate 'all archived' state
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["changes"]["total"], 0)

    def test_multiple_specs_varied_status(self):
        with tmp_project() as root:
            make_openspec(
                root,
                [
                    ("feature-a", "Draft"),
                    ("feature-b", "Approved"),
                    ("feature-c", "In Progress"),
                ],
            )
            r = collect_openspec(root)
            statuses = {i["id"]: i["status"] for i in r.data["changes"]["items"]}
            self.assertEqual(statuses["feature-a"], "pending")
            self.assertEqual(statuses["feature-b"], "approved")
            self.assertEqual(statuses["feature-c"], "in_progress")

    def test_done_triggers_pending_archive(self):
        with tmp_project() as root:
            make_openspec(root, [("complete-feature", "Done")])
            r = collect_openspec(root)
            self.assertEqual(len(r.data["pending_archive"]), 1)
            self.assertEqual(r.data["pending_archive"][0]["id"], "complete-feature")

    def test_archive_date_extraction(self):
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            (root / "openspec" / "archive" / "2026-04-01-my-feature").mkdir(parents=True)
            (root / "openspec" / "archive" / "no-date-format").mkdir(parents=True)
            r = collect_openspec(root)
            items = {i["feature"]: i for i in r.data["archive"]["items"]}
            self.assertEqual(items["my-feature"]["date"], "2026-04-01")
            self.assertIsNone(items["no-date-format"]["date"])

    def test_proposal_missing_skipped(self):
        with tmp_project() as root:
            # Dir exists without proposal.md — should be silently skipped
            (root / "openspec" / "changes" / "empty-dir").mkdir(parents=True)
            write_file(
                root / "openspec" / "changes" / "valid" / "proposal.md",
                "**Status**: Draft\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["changes"]["total"], 1)
            self.assertEqual(r.data["changes"]["items"][0]["id"], "valid")


if __name__ == "__main__":
    unittest.main()
