"""Phase 1.5 requirements (PRD + US) collector tests."""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.requirements import collect_requirements


class TestRequirementsAbsent(unittest.TestCase):
    def test_missing_requirements_dir(self):
        with tmp_project() as root:
            r = collect_requirements(root)
            self.assertFalse(r.data["configured"])
            self.assertEqual(r.data["prd"], [])
            self.assertEqual(r.data["stories"]["total"], 0)


class TestPrdScanning(unittest.TestCase):
    def test_prd_with_approved_status(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "prd-v1.md",
                "# PRD\n\n**Status**: Approved\n",
            )
            r = collect_requirements(root)
            self.assertEqual(len(r.data["prd"]), 1)
            self.assertEqual(r.data["prd"][0]["status"], "approved")

    def test_multiple_prds_sorted(self):
        with tmp_project() as root:
            write_file(root / "docs" / "requirements" / "prd-a.md", "**Status**: Draft\n")
            write_file(root / "docs" / "requirements" / "prd-b.md", "**Status**: Done\n")
            r = collect_requirements(root)
            paths = [p["path"] for p in r.data["prd"]]
            self.assertEqual(len(paths), 2)


class TestUserStories(unittest.TestCase):
    def test_user_stories_counted_by_status(self):
        """R2-TL-3: by_status is open-ended, reflects only observed states."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "prd-v1.md",
                "**Status**: Approved\n",
            )
            for sid, st in [
                ("US-001", "Done"),
                ("US-002", "Done"),
                ("US-003", "In Progress"),
                ("US-004", "Draft"),
            ]:
                write_file(
                    root / "docs" / "requirements" / "user-stories" / f"{sid}.md",
                    f"**Status**: {st}\n",
                )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["total"], 4)
            bs = r.data["stories"]["by_status"]
            self.assertEqual(bs.get("done"), 2)
            self.assertEqual(bs.get("in_progress"), 1)
            self.assertEqual(bs.get("pending"), 1)

    def test_r3_ba1_open_ended_by_status(self):
        """R3-BA1: Only observed statuses appear; no pre-seeded zeros."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-001.md",
                "**Status**: Approved\n",
            )
            r = collect_requirements(root)
            bs = r.data["stories"]["by_status"]
            # Only 'approved' observed; no 'ready', 'pending', 'done' keys
            self.assertEqual(list(bs.keys()), ["approved"])

    def test_unparseable_status_marked_unknown(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-999.md",
                "# A story without any Status header\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
