#!/usr/bin/env python3
"""Tests for lib/detailed_tasks.py — detailed-tasks.yaml parser SOT (aria-plugin #113).

Covers TASK-001 (slicer relocation) + TASK-002 (status extraction layer):
SC-3a/b/c/d/e/f, SC-5, SC-11, SC-14, SC-15, SC-16.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# `_helpers` puts scripts/ on sys.path; collectors._status pre-loads the
# collectors package (pre-existing spec_complete ↔ collectors/__init__ cycle).
# Deliberately NOT `from lib.detailed_tasks import ...`: the top-level name `lib`
# resolves to aria/skills/state-scanner/lib (a real package with __init__.py)
# under full-suite discovery, shadowing scripts/lib. Import the bare module
# (same convention as test_spec_complete.py:56-70) — and do NOT insert scripts/
# at position 0 here, which would shadow that top-level `lib` suite-wide.
from _helpers import tmp_project  # noqa: E402,F401
from collectors._status import _normalize_status  # noqa: E402,F401

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import detailed_tasks as dt  # noqa: E402


def _yaml(*tasks_lines: str, trailer: str = "") -> str:
    body = "tasks:\n" + "\n".join(tasks_lines)
    if trailer:
        body += "\n" + trailer
    return body + "\n"


class TestSlicerRelocation(unittest.TestCase):
    """TASK-001: _TASK_ID_LINE_RE + _split_task_blocks physically in lib, re-imported."""

    def test_slicer_symbols_present_in_lib(self):
        self.assertTrue(hasattr(dt, "_TASK_ID_LINE_RE"))
        self.assertTrue(hasattr(dt, "_split_task_blocks"))

    def test_spec_complete_reimports_from_detailed_tasks(self):
        # SC-9 boundary consistency (decision 8): spec_complete.py must NOT define
        # its own slicer — it re-imports from the relocated SOT. Assert module
        # origin + functional equivalence (robust to the codebase-wide dual
        # sys.path module-identity quirk that also affects carry_forward.py).
        import spec_complete as sc  # noqa: E402
        self.assertTrue(sc._split_task_blocks.__module__.endswith("detailed_tasks"))
        sample = "  - id: TASK-001\n    x: 1\n  - id: TASK-002\n    y: 2\n"
        self.assertEqual(sc._split_task_blocks(sample), dt._split_task_blocks(sample))
        self.assertEqual(sc._TASK_ID_LINE_RE.pattern, dt._TASK_ID_LINE_RE.pattern)

    def test_split_blocks_boundary_unchanged(self):
        text = "  - id: TASK-001\n    x: 1\n  - id: TASK-002\n    y: 2\n"
        blocks = dt._split_task_blocks(text)
        self.assertEqual([b[0] for b in blocks], ["TASK-001", "TASK-002"])


class TestBasicParse(unittest.TestCase):
    def test_status_and_title_extracted(self):
        text = _yaml(
            '  - id: TASK-001',
            '    title: "Add OTP column"',
            '    status: done',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"])
        self.assertEqual(len(r["tasks"]), 1)
        t = r["tasks"][0]
        self.assertEqual(t["id"], "TASK-001")
        self.assertEqual(t["raw_status"], "done")
        self.assertEqual(t["title"], "Add OTP column")

    def test_whitelist_done_and_completed(self):
        text = _yaml(
            '  - id: TASK-001',
            '    status: done',
            '  - id: TASK-002',
            '    status: completed',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"])
        self.assertTrue(all(dt.is_done_status(t["raw_status"]) for t in r["tasks"]))


class TestSC5FailClosed(unittest.TestCase):
    """SC-5: documented-but-unobserved values + unknown values → residual (not done)."""

    def test_blocked_in_progress_deferred_pending_not_done(self):
        for val in ("blocked", "in_progress", "deferred", "pending", "wontfix", "COMPLETE"):
            self.assertFalse(dt.is_done_status(val), f"{val!r} must not be done-family")

    def test_none_not_done(self):
        self.assertFalse(dt.is_done_status(None))


class TestSC3dEntryLevel(unittest.TestCase):
    """SC-3d: missing/empty status → residual (status-missing); missing id → parent_id None."""

    def test_missing_status_key(self):
        text = _yaml('  - id: TASK-001', '    title: foo')
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"])
        self.assertIsNone(r["tasks"][0]["raw_status"])

    def test_empty_status_value(self):
        text = _yaml('  - id: TASK-001', '    status:')
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"])
        self.assertIsNone(r["tasks"][0]["raw_status"])

    def test_empty_quoted_status(self):
        text = _yaml('  - id: TASK-001', '    status: ""')
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"])
        self.assertIsNone(r["tasks"][0]["raw_status"])


class TestSC3abcFileLevel(unittest.TestCase):
    """SC-3a/b/c: file-level parse_ok=False three states."""

    def test_no_tasks_block(self):
        r = dt.parse_detailed_tasks("metadata:\n  feature: x\n")
        self.assertFalse(r["parse_ok"])
        self.assertIn("tasks:", r["reason"])

    def test_zero_id_entries(self):
        r = dt.parse_detailed_tasks("tasks:\n  # nothing here\n")
        self.assertFalse(r["parse_ok"])

    def test_duplicate_tasks_block_fails_closed(self):
        # M-5: parsing only the first block would silently drop the second's
        # tasks while reporting parse_ok=True (hidden-entry class, invisible to
        # the per-block self-consistency count).
        text = (
            "tasks:\n  - id: TASK-001\n    status: done\n"
            "tasks:\n  - id: TASK-002\n    status: pending\n"
        )
        r = dt.parse_detailed_tasks(text)
        self.assertFalse(r["parse_ok"])
        self.assertIn("duplicat", r["reason"].lower())

    def test_markdown_fenced_pseudo_yaml(self):
        # superpowers-two-phase-review real shape: no top-level tasks:, ids in fences
        text = "# Doc\n```yaml\n- id: TASK-001\n```\n"
        r = dt.parse_detailed_tasks(text)
        self.assertFalse(r["parse_ok"])


class TestSC3eSelfConsistency(unittest.TestCase):
    """SC-3e: base-indent direct-item count != _TASK_ID_LINE_RE count → parse_ok=False."""

    def test_id_not_first_field(self):
        # `- parent: ...` then `id:` on a later line → the dash-item has no `id:`
        # directly after it, so _TASK_ID_LINE_RE misses it but it IS a base-indent
        # list item → count mismatch → parse_ok=False (residual-hiding guard).
        text = "tasks:\n  - id: TASK-001\n    status: done\n  - parent: 1.2\n    id: TASK-002\n"
        r = dt.parse_detailed_tasks(text)
        self.assertFalse(r["parse_ok"])
        self.assertIn("inconsist", r["reason"].lower())

    def test_stray_dash_item_without_id(self):
        text = "tasks:\n  - id: TASK-001\n    status: done\n  - some-stray-scalar\n"
        r = dt.parse_detailed_tasks(text)
        self.assertFalse(r["parse_ok"])

    def test_dash_id_split_is_handled_not_flagged(self):
        # `- \n  id: X` — the existing _TASK_ID_LINE_RE's `-\s*id:` spans the
        # newline, so this IS captured (status read normally); NOT a hidden entry.
        text = "tasks:\n  - id: TASK-001\n    status: done\n  -\n    id: TASK-002\n    status: pending\n"
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual({t["id"] for t in r["tasks"]}, {"TASK-001", "TASK-002"})


class TestSC3fNestedNegControl(unittest.TestCase):
    """SC-3f: (i) nested deliverables `- ` items + (ii) execution_order sibling key
    `- ` items MUST NOT inflate list-item count → parse_ok=True."""

    def test_nested_deliverables_not_counted(self):
        text = _yaml(
            '  - id: TASK-001',
            '    status: done',
            '    deliverables:',
            '      - foo.py',
            '      - bar.py',
            '    verification:',
            '      - "check A"',
            '      - "check B"',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual(len(r["tasks"]), 1)

    def test_execution_order_sibling_key_not_counted(self):
        # R4 golden-shape regression: execution_order is a 0-indent sibling of tasks:
        # whose block-style list items are at the SAME 2-space indent as `- id:`.
        text = _yaml(
            '  - id: TASK-001',
            '    status: done',
            '  - id: TASK-002',
            '    status: completed',
            trailer="execution_order:\n  - TASK-001\n  - TASK-002\n",
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual(len(r["tasks"]), 2)
        # execution_order's TASK-00X list items must NOT appear as parsed tasks
        self.assertEqual({t["id"] for t in r["tasks"]}, {"TASK-001", "TASK-002"})


class TestSC11CRLF(unittest.TestCase):
    """SC-11: CRLF line endings → status judged identical, no \\r residue."""

    def test_crlf_done_not_residual(self):
        text = "tasks:\r\n  - id: TASK-001\r\n    status: done\r\n"
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual(r["tasks"][0]["raw_status"], "done")
        self.assertTrue(dt.is_done_status(r["tasks"][0]["raw_status"]))

    def test_crlf_completed(self):
        text = "tasks:\r\n  - id: TASK-001\r\n    status: completed\r\n"
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["raw_status"], "completed")


class TestSC14NormalizationOrder(unittest.TestCase):
    """SC-14: strip \\r → quote-aware strip comment → strip → strip quotes."""

    def test_quoted_with_comment(self):
        text = _yaml('  - id: TASK-001', '    status: "done"  # rollout note')
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["raw_status"], "done")
        self.assertTrue(dt.is_done_status(r["tasks"][0]["raw_status"]))

    def test_deferred_with_trailing_comment(self):
        text = _yaml('  - id: TASK-001', '    status: deferred  # not in current cycle')
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["raw_status"], "deferred")

    def test_title_with_bare_hash_preserved(self):
        # title does NOT strip comments (may contain unquoted #)
        text = _yaml(
            '  - id: TASK-001',
            '    title: Rule #6 deterministic substitute',
            '    status: done',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertIn("#6", r["tasks"][0]["title"])

    def test_quoted_title_with_hash(self):
        text = _yaml(
            '  - id: TASK-001',
            '    title: "Rule #6 substitute (X)"',
            '    status: done',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["title"], "Rule #6 substitute (X)")


class TestSC15LastBlockBoundary(unittest.TestCase):
    """SC-15: last task followed by 0-indent top-level key containing status:-shaped
    substring → last task status extraction not polluted."""

    def test_trailing_summary_with_status_shaped_content(self):
        text = _yaml(
            '  - id: TASK-001',
            '    status: pending',
            trailer="summary:\n  note: status pending overall\n",
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual(len(r["tasks"]), 1)
        self.assertEqual(r["tasks"][0]["raw_status"], "pending")


class TestFieldColumnAnchoring(unittest.TestCase):
    """Pre-merge code-review I-4: a DEEPER-indented `status:` must not shadow the
    task's own field. Both shapes below previously yielded `done` for tasks that
    should count as residual (new false-green, the direction this change closes)."""

    def test_folded_scalar_status_line_does_not_shadow(self):
        text = _yaml(
            '  - id: TASK-001',
            '    title: x',
            '    notes: >',
            '      status: done',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertIsNone(r["tasks"][0]["raw_status"])  # → status-missing residual
        self.assertFalse(dt.is_done_status(r["tasks"][0]["raw_status"]))

    def test_nested_submapping_status_does_not_win(self):
        text = _yaml(
            '  - id: TASK-001',
            '    sub:',
            '      status: done',
            '    status: pending',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["raw_status"], "pending")

    def test_own_field_still_read_normally(self):
        text = _yaml('  - id: TASK-001', '    status: done', '    title: y')
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["raw_status"], "done")
        self.assertEqual(r["tasks"][0]["title"], "y")

    def test_nested_title_does_not_shadow(self):
        text = _yaml(
            '  - id: TASK-001',
            '    status: done',
            '    meta:',
            '      title: inner title',
            '    title: outer title',
        )
        r = dt.parse_detailed_tasks(text)
        self.assertEqual(r["tasks"][0]["title"], "outer title")


class TestSC16MetadataIsolation(unittest.TestCase):
    """SC-16: metadata.status (0-indent sibling before tasks:) not read as task status."""

    def test_metadata_status_isolated(self):
        text = (
            "metadata:\n"
            '  status: "A.3 complete — post_planning CONVERGED; ready for B.1"\n'
            "tasks:\n"
            "  - id: TASK-001\n"
            "    status: pending\n"
        )
        r = dt.parse_detailed_tasks(text)
        self.assertTrue(r["parse_ok"], r["reason"])
        self.assertEqual(len(r["tasks"]), 1)
        self.assertEqual(r["tasks"][0]["raw_status"], "pending")
        # the narrative metadata.status must not leak into any task
        self.assertNotIn("complete", (r["tasks"][0]["raw_status"] or ""))


if __name__ == "__main__":
    unittest.main()
