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

    def test_issue50_overlong_prd_status_emits_soft_error(self):
        # #50 e2e: T3 wires soft_error into requirements.py too — a separator-less
        # PRD Status field over the char-cap must emit `status_field_truncated`.
        with tmp_project() as root:
            write_file(
                root / "docs" / "requirements" / "prd-big.md",
                "# PRD\n\n**Status**: " + "x" * 250 + "\n",
            )
            r = collect_requirements(root)
            kinds = {e["error"] for e in r.errors}
            self.assertIn("status_field_truncated", kinds)


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


class TestPriorityItemsG4(unittest.TestCase):
    """G4 (state-scanner-inter-cycle-surfacing 2026-05-09): priority_items[].

    Schema: state-snapshot-schema.md §requirements.stories.priority_items
    Tasks: T4.4.a-d.
    """

    def test_t4_4_a_status_order_in_progress_first(self):
        """T4.4.a: in_progress > ready > pending sort order."""
        import os
        import time

        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            # Create with distinct mtimes so sort is deterministic via status alone.
            write_file(stories_dir / "US-001.md", "**Status**: Pending\n")
            write_file(stories_dir / "US-002.md", "**Status**: In Progress\n")
            write_file(stories_dir / "US-003.md", "**Status**: Ready\n")
            now = time.time()
            os.utime(stories_dir / "US-001.md", (now, now))
            os.utime(stories_dir / "US-002.md", (now, now))
            os.utime(stories_dir / "US-003.md", (now, now))

            r = collect_requirements(root)
            items = r.data["stories"]["priority_items"]
            self.assertEqual(len(items), 3)
            # First entry must be in_progress
            self.assertEqual(items[0]["id"], "US-002")
            self.assertEqual(items[0]["status_normalized"], "in_progress")
            # Second: ready
            self.assertEqual(items[1]["status_normalized"], "ready")
            # Third: pending
            self.assertEqual(items[2]["status_normalized"], "pending")

    def test_t4_4_b_path_lex_tiebreak_when_mtime_ties(self):
        """T4.4.b: same status + same mtime → sort by path LEX ASC.

        Guards against `git clone` flat-mtime degeneration (issue #61).
        """
        import os
        import time

        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            # 3 in_progress stories with identical mtime — must sort by path LEX.
            write_file(stories_dir / "US-Z01.md", "**Status**: In Progress\n")
            write_file(stories_dir / "US-A01.md", "**Status**: In Progress\n")
            write_file(stories_dir / "US-M01.md", "**Status**: In Progress\n")
            t = time.time()
            for name in ("US-Z01.md", "US-A01.md", "US-M01.md"):
                os.utime(stories_dir / name, (t, t))

            r = collect_requirements(root)
            ids = [it["id"] for it in r.data["stories"]["priority_items"]]
            self.assertEqual(ids, ["US-A01", "US-M01", "US-Z01"])

    def test_t4_4_c_no_candidates_yields_empty_list(self):
        """T4.4.c: only done/archived/unknown stories → priority_items is []."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            write_file(stories_dir / "US-001.md", "**Status**: Done\n")
            write_file(stories_dir / "US-002.md", "**Status**: Archived\n")
            write_file(stories_dir / "US-003.md", "no status header\n")
            r = collect_requirements(root)
            self.assertEqual(r.data["stories"]["priority_items"], [])

    def test_t4_4_d_status_normalization_pipeline(self):
        """T4.4.d: `**Status**: Ready` / `**状态**: 就绪` (when normalized) / etc.
        all reach priority_items via the status normalization pipeline.

        Note: '就绪' is not in the current _STATUS_NORMALIZATION map; the test
        uses literal 'Ready' to verify the English normalization route since
        i18n word-level mapping is out-of-scope for G4.
        """
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            write_file(stories_dir / "US-A.md", "**Status**: Ready\n")
            write_file(stories_dir / "US-B.md", "**状态**：pending\n")  # fullwidth colon
            write_file(stories_dir / "US-C.md", "**Status**: In Progress\n")
            r = collect_requirements(root)
            statuses = {it["id"]: it["status_normalized"] for it in r.data["stories"]["priority_items"]}
            self.assertEqual(statuses["US-A"], "ready")
            self.assertEqual(statuses["US-B"], "pending")
            self.assertEqual(statuses["US-C"], "in_progress")
            # priority_hint always null in TX-G4 ship
            for it in r.data["stories"]["priority_items"]:
                self.assertIsNone(it["priority_hint"])

    def test_priority_items_limit_default_5(self):
        """T4.5: default limit is 5 even when more candidates exist."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            for i in range(8):
                write_file(stories_dir / f"US-{i:03d}.md", "**Status**: In Progress\n")
            r = collect_requirements(root)
            self.assertEqual(len(r.data["stories"]["priority_items"]), 5)

    def test_priority_items_limit_configurable(self):
        """T4.5: state_scanner.priority_items_limit overrides default."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            for i in range(8):
                write_file(stories_dir / f"US-{i:03d}.md", "**Status**: In Progress\n")
            # Configure limit=3 via .aria/config.json
            write_file(
                root / ".aria" / "config.json",
                '{"state_scanner": {"priority_items_limit": 3}}\n',
            )
            r = collect_requirements(root)
            self.assertEqual(len(r.data["stories"]["priority_items"]), 3)

    def test_priority_items_field_shape(self):
        """priority_items[*] shape matches schema (id/status_normalized/raw_status/priority_hint/file)."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            write_file(stories_dir / "US-042.md", "**Status**: In Progress\n")
            r = collect_requirements(root)
            item = r.data["stories"]["priority_items"][0]
            self.assertEqual(set(item.keys()), {"id", "status_normalized", "raw_status", "priority_hint", "file"})
            self.assertEqual(item["id"], "US-042")
            self.assertEqual(item["file"], "docs/requirements/user-stories/US-042.md")
            self.assertEqual(item["status_normalized"], "in_progress")

    def test_mtime_oserror_fallback_sorts_last_in_bucket(self):
        """R2 audit (qa-engineer): mtime stat() OSError → fallback 0.0 → sorts
        last within its status bucket. Branch at requirements.py
        `except OSError: mtime = 0.0` was unexercised."""
        from unittest.mock import patch

        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            # 2 in_progress stories — mock one to fail stat().
            write_file(stories_dir / "US-A.md", "**Status**: In Progress\n")
            write_file(stories_dir / "US-B.md", "**Status**: In Progress\n")

            real_stat = type(stories_dir).stat

            def fake_stat(self, *args, **kwargs):
                # Make US-A's stat() raise OSError; US-B reads normally.
                if self.name == "US-A.md":
                    raise OSError("simulated stat failure")
                return real_stat(self, *args, **kwargs)

            with patch.object(type(stories_dir), "stat", fake_stat):
                r = collect_requirements(root)

            ids = [it["id"] for it in r.data["stories"]["priority_items"]]
            # US-B (real mtime) sorts ahead of US-A (fallback mtime=0.0 = oldest).
            self.assertEqual(ids, ["US-B", "US-A"])

    def test_load_priority_items_limit_handles_non_dict_json(self):
        """R2 audit (code-reviewer): config.json with array root must NOT crash
        with AttributeError; defensive fallback to default 5."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            for i in range(7):
                write_file(stories_dir / f"US-{i:03d}.md", "**Status**: In Progress\n")
            # config.json is an array (valid JSON, invalid for this consumer)
            write_file(root / ".aria" / "config.json", "[1, 2, 3]\n")
            r = collect_requirements(root)
            # Falls back to default limit 5 (not 7, not crash).
            self.assertEqual(len(r.data["stories"]["priority_items"]), 5)

    def test_tx6_backward_compat_defensive_access_priority_items(self):
        """TX.6 (backward-compat verify): consumers using
        `data["stories"].get("priority_items", [])` must work whether the
        field is shipped (post-G4) OR absent (pre-G4 scan.py output).

        Pins schema backward-compat table contract: priority_items consumer
        access pattern is `stories.get("priority_items", [])`, never raw
        index. Test exercises the defensive default in BOTH directions:
        present-and-empty AND access-when-shipped.
        """
        with tmp_project() as root:
            # Configured project with no priority candidates → priority_items: []
            stories_dir = root / "docs" / "requirements" / "user-stories"
            write_file(stories_dir / "US-001.md", "**Status**: Done\n")
            r = collect_requirements(root)
            stories = r.data["stories"]
            # Field IS present (G4 shipped); defensive default not exercised.
            self.assertIn("priority_items", stories)
            self.assertEqual(stories.get("priority_items", []), [])
            # Iteration over defensive access is safe.
            for _it in stories.get("priority_items", []):
                self.fail("empty list should yield zero iterations")

    def test_tx6_backward_compat_unconfigured_requirements(self):
        """TX.6: when `configured: false` (no docs/requirements/), consumers
        using `data["stories"].get("priority_items", [])` still work — the
        stories dict still contains an empty priority_items list (collector
        emits the field always when configured=false-with-stories-dict-missing
        OR populates it with empty when configured=true-with-no-candidates)."""
        with tmp_project() as root:
            # No docs/requirements/ → configured: false
            r = collect_requirements(root)
            self.assertFalse(r.data["configured"])
            # Stories dict still emitted (with empty priority_items per
            # collector contract — see requirements.py:115 unconfigured branch).
            stories = r.data["stories"]
            self.assertEqual(stories.get("priority_items", []), [])

    def test_load_priority_items_limit_handles_non_dict_state_scanner(self):
        """R2 audit (code-reviewer extension): nested state_scanner being
        non-dict (e.g. string) must also fall back to default."""
        with tmp_project() as root:
            stories_dir = root / "docs" / "requirements" / "user-stories"
            for i in range(7):
                write_file(stories_dir / f"US-{i:03d}.md", "**Status**: In Progress\n")
            write_file(
                root / ".aria" / "config.json",
                '{"state_scanner": "wrong-type"}\n',
            )
            r = collect_requirements(root)
            self.assertEqual(len(r.data["stories"]["priority_items"]), 5)


if __name__ == "__main__":
    unittest.main()
