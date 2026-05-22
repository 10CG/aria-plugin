"""Phase 1.6 OpenSpec + shared _status collector tests.

Covers D1/D2/D5 (intentional divergences from v2.9 prose: Approved/Reviewed/
Active/Deprecated/Archived preserved as distinct states, not collapsed).

Phase 1.6.1 carry-forward inventory tests (Spec
`state-scanner-inline-carry-forward-surfacing`, v1.23.0) at bottom.
"""

from __future__ import annotations

import unittest

from _helpers import make_openspec, tmp_project, write_file
from collectors._status import (
    _extract_status,
    _normalize_status,
    _status_field_overlong,
    _status_lifecycle_head,
)
from collectors.openspec import _extract_carry_forward_annotations, collect_openspec


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


class TestStatusNormalizationIssue73Fix(unittest.TestCase):
    """Regression suite for Aria #73 — transitional status mis-classification.

    Background: pre-v1.20.0 (before #101) `Implementation-Complete-Pending-Obs`
    normalized to `done` (substring shadow), triggering false-positive
    pending_archive recommendation. The v1.20.0 #101 fix incidentally moved
    `pending` family above `done` fallback, so the symptom shifted to `pending`
    — pending_archive no longer fired, but `requirements.py:56` priority_items
    filter (status ∈ {in_progress, ready, pending}) wrongly surfaced the spec
    as "待处理".

    v1.21.4 #73 fix adds a transitional family ahead of pending family, mapping
    `implementation-complete` / `implementation-done` phrases to `implemented`
    — the canonical lifecycle slot for "post-merge, awaiting verify/archive"
    per SKILL.md token dictionary. Aether 2026-05-04 real-world case:
    `migrate-docker-data-root-to-local-ssd` Spec with 24h observation window.
    """

    def test_issue73_implementation_complete_pending_obs(self):
        # Primary case from #73 body (Aether 2026-05-04)
        self.assertEqual(
            _normalize_status("Implementation-Complete-Pending-Obs"),
            "implemented",
        )

    def test_issue73_implementation_complete_with_narrative(self):
        # Full real-world form: phrase + date + commentary
        self.assertEqual(
            _normalize_status(
                "Implementation-Complete-Pending-Obs 2026-05-04 "
                "(Phase 1-5 全部 done, 24h obs window: 5/5 03:48 UTC PASS 后转 Complete)"
            ),
            "implemented",
        )

    def test_issue73_implementation_done_variant(self):
        # Alternate spelling — implementation-done same semantic
        self.assertEqual(
            _normalize_status("Implementation-Done (24h obs PASS)"),
            "implemented",
        )

    def test_issue73_does_not_trigger_pending(self):
        # Negative: must NOT fall into pending family despite containing
        # `pending` token (`pending-obs` word-boundary match)
        self.assertNotEqual(
            _normalize_status("Implementation-Complete-Pending-Obs"),
            "pending",
        )

    def test_issue73_does_not_trigger_done(self):
        # Negative: must NOT fall into done fallback (original #73 symptom)
        self.assertNotEqual(
            _normalize_status("Implementation-Complete-Pending-Obs"),
            "done",
        )

    def test_issue73_archived_still_wins(self):
        # Priority: archived (terminal) still takes precedence over transitional
        # — once a Spec is archived, the transitional history is irrelevant.
        self.assertEqual(
            _normalize_status(
                "Archived (was Implementation-Complete-Pending-Obs)"
            ),
            "archived",
        )

    def test_issue73_unimplemented_shadow_guard(self):
        # Negative: `unimplemented` doesn't match `implementation-complete`
        # (different prefix); the transitional family uses substring not
        # word-boundary, but the phrases are distinctive enough that
        # `unimplemented` doesn't contain either phrase.
        self.assertEqual(_normalize_status("Unimplemented"), "unknown")

    def test_issue73_phrase_anywhere_in_string(self):
        # Substring match — phrase can appear with surrounding text
        self.assertEqual(
            _normalize_status("Status: Implementation-Complete — awaiting D.2"),
            "implemented",
        )


class TestStatusExtractionRangeIssue50Fix(unittest.TestCase):
    """Regression suite for Forgejo aria-plugin #50 — `_status` lifecycle-head
    extraction range + `delivered`/`shipped` token dict extension.

    Bug 1: `_extract_status` returned the full single-line Status with no length
           cap; a `done`/`complete` token buried in a long mini-changelog Status
           shadowed the lifecycle head via `_normalize_status`'s fallback.
    Bug 2: `delivered` / `shipped` were missing from the token dictionary.

    Fix: `_status_lifecycle_head` truncates raw to the first documented separator
    (em-dash / en-dash / ASCII-hyphen-with-spaces / `;` / `；` / `。`) before
    classification; `delivered`/`shipped` added to the `implemented` branch.

    See: openspec/changes/state-scanner-status-extraction-range/
    """

    # --- Bug 1: lifecycle-head truncation ---

    def test_issue50_triage_case1_long_single_line(self):
        # triage case-1: header `delivered`, `done` buried in sub-task narrative
        # after the em-dash. Was `done` (WRONG), now `implemented`.
        raw = (
            "🟢 **Phase B Sprint 2 delivered** — archival blocked; "
            "(2) TASK-101 closed (PR #53, docs sync 标 done); "
            "blockers: live verify outstanding"
        )
        self.assertEqual(_normalize_status(raw), "implemented")
        self.assertNotEqual(_normalize_status(raw), "done")

    def test_issue50_em_dash_truncation(self):
        self.assertEqual(
            _normalize_status("Approved — Phase A done, ready for Phase B"),
            "approved",
        )

    def test_issue50_ascii_hyphen_with_spaces_truncation(self):
        # ` - ` (space-hyphen-space) is a tolerated separator; head `WIP` has no
        # token, the trailing `done` after the hyphen must not shadow.
        self.assertEqual(_normalize_status("WIP - 子任务 done"), "unknown")

    def test_issue50_semicolon_truncation(self):
        self.assertEqual(_normalize_status("Approved; Phase A done"), "approved")

    def test_issue50_fullwidth_period_truncation(self):
        self.assertEqual(_normalize_status("WIP。Phase A done"), "unknown")

    def test_issue50_ascii_period_not_a_separator(self):
        # ASCII `.` must NOT truncate — `v2.0` version strings stay intact.
        self.assertEqual(_normalize_status("v2.0 implemented"), "implemented")

    def test_issue50_73_phrase_across_separator(self):
        # NEW-IM-1: a #73 transitional phrase split by a separator loses the
        # phrase from the head — head `implementation` has no token → unknown.
        # Authoring a Status this way is a documented violation (SKILL.md);
        # this case pins the truncation-boundary behavior.
        self.assertEqual(_normalize_status("implementation — complete"), "unknown")

    # --- Bug 2: delivered / shipped token dict ---

    def test_issue50_delivered_token(self):
        self.assertEqual(_normalize_status("Phase B delivered"), "implemented")

    def test_issue50_shipped_token(self):
        self.assertEqual(_normalize_status("Shipped to prod"), "implemented")

    def test_issue50_delivered_case_insensitive(self):
        self.assertEqual(_normalize_status("DELIVERED"), "implemented")

    def test_issue50_shadow_undelivered(self):
        # word boundary: `undelivered` must NOT match `delivered`
        self.assertEqual(_normalize_status("undelivered work remaining"), "unknown")

    def test_issue50_shadow_preshipped(self):
        # word boundary: `preshipped` must NOT match `shipped`
        self.assertEqual(_normalize_status("preshipped artifacts"), "unknown")

    def test_issue50_ordering_approved_before_delivered(self):
        # approved still wins over the implemented-family (delivered)
        self.assertEqual(_normalize_status("Approved (delivered by PR)"), "approved")

    # --- Boundary cases for _status_lifecycle_head / _status_field_overlong ---

    def test_head_char_cap_boundary(self):
        # cap is strict `>`: exactly 200 → not truncated; 201 → truncated
        head_200, trunc_200 = _status_lifecycle_head("a" * 200)
        self.assertEqual(len(head_200), 200)
        self.assertFalse(trunc_200)
        head_201, trunc_201 = _status_lifecycle_head("a" * 201)
        self.assertEqual(len(head_201), 200)
        self.assertTrue(trunc_201)

    def test_head_separator_at_position_zero(self):
        head, trunc = _status_lifecycle_head(" — narrative only")
        self.assertEqual(head, "")
        self.assertFalse(trunc)
        self.assertEqual(_normalize_status(" — narrative only"), "unknown")

    def test_head_multiple_em_dashes_cuts_first(self):
        head, _ = _status_lifecycle_head("Approved — note1 — note2")
        self.assertEqual(head, "Approved")

    def test_head_separator_inside_parentheses(self):
        # `。` inside parens still truncates; head `In Progress (Phase 1` still
        # classifies via the `in progress` multi-word phrase. Behavior pinned.
        self.assertEqual(
            _normalize_status("In Progress (Phase 1。Phase 2)"), "in_progress"
        )

    def test_head_comma_is_not_a_separator(self):
        # comma must NOT truncate — `Approved, revised` keeps `approved`
        head, _ = _status_lifecycle_head("Approved, revised")
        self.assertEqual(head, "Approved, revised")
        self.assertEqual(_normalize_status("Approved, revised"), "approved")

    def test_head_none_safe(self):
        self.assertEqual(_status_lifecycle_head(None), ("", False))
        self.assertFalse(_status_field_overlong(None))

    def test_field_overlong_predicate(self):
        self.assertTrue(_status_field_overlong("z" * 250))
        self.assertFalse(_status_field_overlong("Approved"))
        # long string WITH an early separator → head is short → not overlong
        self.assertFalse(_status_field_overlong("Approved — " + "x" * 300))


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

    def test_issue50_overlong_status_emits_soft_error(self):
        # #50 e2e: a separator-less Status field over the char-cap emits a
        # `status_field_truncated` soft_error (aggregated into snapshot errors[]).
        with tmp_project() as root:
            make_openspec(root, [("big-spec", "x" * 250)])
            r = collect_openspec(root)
            kinds = {e["error"] for e in r.errors}
            self.assertIn("status_field_truncated", kinds)

    def test_issue50_raw_status_keeps_full_narrative(self):
        # #50 e2e: raw_status retains the COMPLETE Status text; only `status`
        # is derived from the truncated lifecycle head.
        long_status = "🟢 Phase B delivered — " + "narrative " * 30
        with tmp_project() as root:
            make_openspec(root, [("verbose-spec", long_status)])
            r = collect_openspec(root)
            item = r.data["changes"]["items"][0]
            self.assertEqual(item["raw_status"], long_status.strip())
            self.assertEqual(item["status"], "implemented")


class TestCarryForwardInventory(unittest.TestCase):
    """Phase 1.6.1 — inline carry-forward annotation surfacing in tasks.md.

    Spec: state-scanner-inline-carry-forward-surfacing (Approved R2 PASS_WITH_WARNINGS).
    16 cases: 9 core + 7 R1-audit gap fills.
    """

    # --- Helper-level (pattern correctness) ---

    def test_no_annotations_returns_zero_total(self):
        with tmp_project() as root:
            make_openspec(root, [("feature-a", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feature-a" / "tasks.md",
                "- [ ] task 1\n- [x] task 2\n",
            )
            r = collect_openspec(root)
            cf = r.data["carry_forward_inventory"]
            self.assertEqual(cf["total"], 0)
            self.assertEqual(cf["active_change_count"], 1)
            self.assertEqual(cf["by_change"], {})

    def test_single_carry_forward(self):
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "- [ ] task [carry-forward: detail]\n",
            )
            r = collect_openspec(root)
            cf = r.data["carry_forward_inventory"]
            self.assertEqual(cf["total"], 1)
            self.assertEqual(cf["by_change"]["feat"]["count"], 1)
            self.assertEqual(
                cf["by_change"]["feat"]["samples"], ["[carry-forward: detail]"]
            )

    def test_mixed_token_types(self):
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "[carry-forward: a] [TODO: b] [PASS-with-note: c] [defer] [known gap]\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 5)

    def test_hyphen_vs_space_variants(self):
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "[known gap] vs [known-gap] vs [deferred] vs [defer]\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 4)

    def test_multi_change_aggregation(self):
        with tmp_project() as root:
            make_openspec(root, [("a", "Draft"), ("b", "Draft")])
            write_file(
                root / "openspec" / "changes" / "a" / "tasks.md",
                "[carry-forward: 1] [TODO: 2] [defer]\n",
            )
            write_file(
                root / "openspec" / "changes" / "b" / "tasks.md",
                "[carry-forward: x] [carry-forward: y] [carry-forward: z]\n",
            )
            r = collect_openspec(root)
            cf = r.data["carry_forward_inventory"]
            self.assertEqual(cf["total"], 6)
            self.assertEqual(cf["active_change_count"], 2)
            self.assertEqual(set(cf["by_change"].keys()), {"a", "b"})
            self.assertEqual(cf["by_change"]["a"]["count"], 3)
            self.assertEqual(cf["by_change"]["b"]["count"], 3)

    def test_archive_excluded(self):
        with tmp_project() as root:
            make_openspec(root, [("active", "Draft")])
            write_file(
                root / "openspec" / "changes" / "active" / "tasks.md",
                "no annotations here\n",
            )
            # Create archive entry with annotation — must NOT be counted
            write_file(
                root / "openspec" / "archive" / "2026-04-01-old" / "tasks.md",
                "[carry-forward: should be excluded]\n",
            )
            write_file(
                root / "openspec" / "archive" / "2026-04-01-old" / "proposal.md",
                "# old\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 0)

    def test_multi_line_annotation_normalized(self):
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "[carry-forward:\n  long detail\n  spans lines]\n",
            )
            r = collect_openspec(root)
            samples = r.data["carry_forward_inventory"]["by_change"]["feat"]["samples"]
            # \n → space, multi-line collapsed
            self.assertIn("[carry-forward:", samples[0])
            self.assertNotIn("\n", samples[0])

    def test_substring_shadow_guard_token_extension(self):
        """[carry-forwarded-stuff] must NOT match (\\b blocks substring extension)."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "[carry-forwarded-detail] [carry-forwardish] [todone]\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 0)

    def test_first_3_samples_truncation(self):
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            # 5 annotations; long one to test 80-char trunc
            long_detail = "x" * 200
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                f"[carry-forward: 1] [carry-forward: {long_detail}] [TODO: 3] [defer] [TODO: 5]\n",
            )
            r = collect_openspec(root)
            entry = r.data["carry_forward_inventory"]["by_change"]["feat"]
            self.assertEqual(entry["count"], 5)
            self.assertEqual(len(entry["samples"]), 3)  # first 3 only
            # Long annotation truncated with trailing "..."
            self.assertTrue(entry["samples"][1].endswith("..."))
            self.assertLessEqual(len(entry["samples"][1]), 83)  # 80 + "..."

    # --- R1 audit gap fills ---

    def test_empty_tasks_md(self):
        """Empty (0-byte) tasks.md → count=0, change not in by_change."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(root / "openspec" / "changes" / "feat" / "tasks.md", "")
            r = collect_openspec(root)
            cf = r.data["carry_forward_inventory"]
            self.assertEqual(cf["total"], 0)
            self.assertEqual(cf["active_change_count"], 1)
            self.assertNotIn("feat", cf["by_change"])

    def test_missing_tasks_md(self):
        """Active change without tasks.md → silently skipped."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            # NO tasks.md created
            r = collect_openspec(root)
            cf = r.data["carry_forward_inventory"]
            self.assertEqual(cf["total"], 0)
            self.assertEqual(cf["active_change_count"], 1)
            self.assertNotIn("feat", cf["by_change"])

    def test_proposal_md_not_scanned(self):
        """Annotations in proposal.md NOT counted (scope: tasks.md only)."""
        with tmp_project() as root:
            # make_openspec writes proposal.md; we inject a carry-forward into it
            write_file(
                root / "openspec" / "changes" / "feat" / "proposal.md",
                "# feat\n\n> **Status**: Draft\n\n[carry-forward: in proposal not tasks]\n",
            )
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "- [ ] clean tasks\n",
            )
            (root / "openspec" / "archive").mkdir(parents=True, exist_ok=True)
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 0)

    def test_crlf_line_endings_normalized(self):
        """Windows CRLF (\\r\\n) inside multi-line annotation normalized to space."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            (root / "openspec" / "changes" / "feat" / "tasks.md").write_bytes(
                b"[carry-forward:\r\n  windows-detail\r\n  third-line]\r\n"
            )
            r = collect_openspec(root)
            samples = r.data["carry_forward_inventory"]["by_change"]["feat"]["samples"]
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 1)
            self.assertNotIn("\r", samples[0])
            self.assertNotIn("\n", samples[0])

    def test_nested_brackets_handled(self):
        """[[carry-forward: x]] → matches once (non-greedy stops at first ])."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "[[carry-forward: x]] outer\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 1)

    def test_archive_substring_in_path_not_matched(self):
        """Path with 'changes' substring in archive (e.g., archive/old-changes/) excluded."""
        with tmp_project() as root:
            make_openspec(root, [])  # empty changes/
            # Archive with 'changes' in subname — must NOT be glob-matched
            write_file(
                root / "openspec" / "archive" / "2026-04-01-old-changes-sub" / "tasks.md",
                "[carry-forward: archive substring trap]\n",
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 0)

    def test_code_block_and_html_comment_included(self):
        """INCLUDE annotations inside ``` code blocks ``` and <!-- HTML comments -->."""
        with tmp_project() as root:
            make_openspec(root, [("feat", "Draft")])
            write_file(
                root / "openspec" / "changes" / "feat" / "tasks.md",
                "```\n[carry-forward: in code block]\n```\n"
                "<!-- [TODO: in html comment] -->\n",
            )
            r = collect_openspec(root)
            # Both INCLUDE policy per §Change 2
            self.assertEqual(r.data["carry_forward_inventory"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
