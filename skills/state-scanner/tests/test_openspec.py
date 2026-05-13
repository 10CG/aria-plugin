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

    def test_i18n_fullwidth_colon_cn(self):
        """Spec state-scanner-i18n-status-regex: openspec collector also benefits."""
        self.assertEqual(_extract_status("**状态**：pending"), "pending")

    def test_i18n_inline_blockquote_multi_meta(self):
        """Pattern 6 propagates to openspec via shared _status module."""
        self.assertEqual(
            _extract_status("> **优先级**：P0 | **状态**：approved | **里程碑**：M3"),
            "approved",
        )

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


class TestStatusNormalizationIssue101Fix(unittest.TestCase):
    """Regression tests for Forgejo Aria #101 fix (2026-05-13).

    Bug 1: `done` token substring matched aggressively, shadowing `approved` /
           `pending` / etc. when those tokens appeared with "...Phase A done..." narratives.
    Bug 2: `Implemented` not in token dictionary → returned `unknown`.

    Fix: word-boundary regex matching (`\\b<token>\\b`) + add `implemented` token +
    reorder `approved` before `implemented` in priority chain.

    See: openspec/archive/2026-05-13-aria-issue-101-status-normalize/
    """

    # --- Bug 1+2 fix verification: 4 真实 #101 Status strings ---

    def test_issue101_docs_marketplace_adaptation(self):
        # Bug 1: "Approved ... Phase A done" → was "done", now "approved"
        self.assertEqual(
            _normalize_status(
                "Approved (Rev2 CONVERGED) — Phase A done, ready for Phase B"
            ),
            "approved",
        )

    def test_issue101_existing_data_migration(self):
        # Bug 2: "Implemented (...) — post-deploy 验证后归档" → was "unknown", now "implemented"
        self.assertEqual(
            _normalize_status(
                "Implemented (Phase B PR-A merged 2026-05-10) — post-deploy 验证后归档"
            ),
            "implemented",
        )

    def test_issue101_pricing_status_marketplace_redo(self):
        # Bug 2: same family, with "UAT PASS; post-monitoring 后归档" narrative
        self.assertEqual(
            _normalize_status(
                "Implemented (Phase B PR-A merged 2026-05-10) — UAT PASS; post-monitoring 后归档"
            ),
            "implemented",
        )

    def test_issue101_terms_of_service_and_attribution(self):
        # Bug 1: "DRAFT pending ... Phase B PR-A done" → was "done", now "pending"
        self.assertEqual(
            _normalize_status(
                "⏸ DRAFT pending lawyer review — Phase B PR-A done 2026-05-09"
            ),
            "pending",
        )

    # --- Shadow guards: word-boundary prevents substring false positives ---

    def test_shadow_inactive_not_active(self):
        # `inactive` contains `active` substring — word boundary prevents shadow
        self.assertEqual(_normalize_status("Inactive — superseded"), "unknown")

    def test_shadow_unimplemented_not_implemented(self):
        # `unimplemented` contains `implemented` substring — word boundary prevents shadow
        self.assertEqual(_normalize_status("Unimplemented stubs"), "unknown")

    def test_shadow_incomplete_not_complete(self):
        # `incomplete` contains `complete` substring — word boundary prevents shadow
        self.assertEqual(_normalize_status("Incomplete (missing sections)"), "unknown")

    def test_ordering_approved_before_implemented(self):
        # BA-M2: "Approved (Implemented by PR-A)" should → approved (gatekeeping state),
        # NOT implemented (post-merge state). approved-before-implemented in priority chain.
        self.assertEqual(
            _normalize_status("Approved (Implemented by PR-A)"), "approved"
        )

    # --- Positive regression: reorder didn't break single-token / multi-word ---

    def test_positive_regression_single_token_states(self):
        self.assertEqual(_normalize_status("Active"), "active")
        self.assertEqual(_normalize_status("Reviewed"), "reviewed")
        self.assertEqual(_normalize_status("Ready"), "ready")
        self.assertEqual(_normalize_status("Implemented"), "implemented")  # new state
        self.assertEqual(_normalize_status("Done"), "done")
        self.assertEqual(_normalize_status("Archived 2026-01-01"), "archived")

    def test_positive_regression_in_progress_with_done_shadow(self):
        # "In Progress (50% done)" — multi-word phrase wins, narrative "done" doesn't shadow
        self.assertEqual(
            _normalize_status("In Progress (50% done)"), "in_progress"
        )

    def test_positive_regression_ready_with_done_shadow(self):
        # "ready (Phase A done)" — single-token `ready` wins, narrative "done" doesn't shadow
        self.assertEqual(_normalize_status("ready (Phase A done)"), "ready")

    def test_implemented_does_not_trigger_pending_archive(self):
        # Implemented spec is "post-deploy verification pending", NOT ready to archive.
        # openspec collector's pending_archive only triggers on status=="done",
        # so this is verified indirectly — but explicit test guards the contract.
        self.assertEqual(_normalize_status("Implemented"), "implemented")
        self.assertNotEqual(_normalize_status("Implemented"), "done")

    def test_empty_string_is_unknown(self):
        self.assertEqual(_normalize_status(""), "unknown")


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
