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


class TestI18nStatusRegex(unittest.TestCase):
    """Spec: state-scanner-i18n-status-regex (2026-04-25).

    Cross-project T8 Kairos validation surfaced that Chinese markdown habit
    (fullwidth colon `：` + inline blockquote multi-meta) was not covered by
    the original 5 patterns. Pattern 2/3/4 widened to `[：:]`; pattern 6
    added for inline blockquote multi-meta.
    """

    def test_fullwidth_colon_bold_status_cn(self):
        """Pattern 3 widened: `**状态**：pending` (fullwidth colon)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-100.md",
                "# US-100\n\n**状态**：pending\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "pending")
            self.assertEqual(r.data["stories"]["items"][0]["raw_status"], "pending")

    def test_inline_blockquote_multi_meta_kairos_us009(self):
        """Pattern 6 added: real-world Kairos US-009 sample.

        This is the regression case T8.2 surfaced — verifies it now resolves.
        """
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-009-tts-voice-clone.md",
                "# US-009: TTS 语音克隆\n\n"
                "> **优先级**：P0 | **里程碑**：M3 | **状态**：pending\n\n"
                "## 用户故事\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "pending")
            self.assertEqual(r.data["stories"]["items"][0]["raw_status"], "pending")

    def test_inline_blockquote_status_at_end(self):
        """Pattern 6: status as last meta key."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-101.md",
                "> **A**: 1 | **状态**: done\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "done")

    def test_inline_blockquote_status_in_middle_english(self):
        """Pattern 6: English Status mid-line, halfwidth colon."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-102.md",
                "> **A**: 1 | **Status**: in progress | **B**: 2\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "in_progress")

    def test_negative_prose_mention_not_matched(self):
        """Pattern 6 must NOT match prose containing the word 状态 outside blockquote bold."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "user-stories" / "US-103.md",
                "# US-103\n\n## 用户故事\n\n用户期望知道当前状态：可能 pending 状态.\n",
            )
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["items"][0]["status"], "unknown")
            self.assertIsNone(r.data["stories"]["items"][0]["raw_status"])


if __name__ == "__main__":
    unittest.main()
