#!/usr/bin/env python3
"""gate_result() yaml-only three-state datasource tests (aria-plugin #113).

Supersedes the v1.61.0 blanket-unverified fallback with precise per-spec verdicts:
SC-1 (residual enumeration incl. annotation half) / SC-2 (full-pass) / SC-2b
(scoped integrity axis) / SC-3a-e end-to-end gate response / SC-4 (dual-layer
byte-identical negative control).

Spec: openspec/changes/state-scanner-gate-yaml-datasource/proposal.md
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import gate_result  # noqa: E402

_UNPARSEABLE = "archive-safety-net-source-unparseable"
_INTEGRATION = "archive-safety-net-integration-claims-unverified"
_RETIRED_BLANKET = "archive-safety-net-source-unsupported"

_PROPOSAL = "# spec\n\n> **Status**: Approved\n\n## Why\ntest\n"


def _spec(root, spec_id: str, yaml_text: str, proposal: str = _PROPOSAL):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(spec_dir / "proposal.md", proposal)
    write_file(spec_dir / "detailed-tasks.yaml", yaml_text)
    return spec_dir


def _claims(result) -> set[str]:
    return {c["claim"] for c in result["unverified_claims"]}


class TestSC1ResidualEnumeration(unittest.TestCase):
    """SC-1: residuals precisely enumerated into d_payload.deferred_items."""

    def test_status_residuals_listed_with_exact_strings(self):
        yaml_text = (
            "tasks:\n"
            "  - id: TASK-001\n"
            "    title: done thing\n"
            "    status: done\n"
            "  - id: TASK-002\n"
            "    title: pending thing\n"
            "    status: pending\n"
            "  - id: TASK-003\n"
            "    title: deferred thing\n"
            "    status: deferred  # not in current cycle\n"
        )
        with tmp_project() as root:
            result = gate_result(_spec(root, "residual-spec", yaml_text))
            self.assertEqual(result["verdict"], "pass")  # residuals do NOT raise verdict
            self.assertNotIn(_RETIRED_BLANKET, _claims(result))
            self.assertIsNotNone(result["d_payload"])
            items = result["d_payload"]["deferred_items"]
            self.assertEqual(len(items), 2, items)
            by_parent = {i["parent_id"]: i for i in items}
            self.assertEqual(by_parent["TASK-002"]["reason"], "status=pending")
            # trailing `# comment` must NOT enter raw status (SC-1 exact string)
            self.assertEqual(by_parent["TASK-003"]["reason"], "status=deferred")
            self.assertEqual(
                by_parent["TASK-003"]["line"], "TASK-003: deferred thing [status=deferred]"
            )

    def test_annotation_residual_also_enters_deferred_items(self):
        # SC-1 extension (PP-R1 backend): the ∪ right-hand half — inline
        # carry-forward annotations in the yaml text must reach gate d_payload,
        # matching the tasks.md path's two-half aggregation.
        yaml_text = (
            "tasks:\n"
            "  - id: TASK-001\n"
            "    title: all done\n"
            "    status: done\n"
            "    notes: '[TODO: wire the follow-up]'\n"
        )
        with tmp_project() as root:
            result = gate_result(_spec(root, "annot-spec", yaml_text))
            self.assertIsNotNone(result["d_payload"])
            reasons = {i["reason"] for i in result["d_payload"]["deferred_items"]}
            self.assertIn("carry-forward annotation", reasons)

    def test_missing_status_counts_as_residual(self):
        yaml_text = "tasks:\n  - id: TASK-001\n    title: no status here\n"
        with tmp_project() as root:
            result = gate_result(_spec(root, "nostatus-spec", yaml_text))
            self.assertIsNotNone(result["d_payload"])
            items = result["d_payload"]["deferred_items"]
            self.assertEqual(items[0]["reason"], "status-missing")


class TestSC2FullPass(unittest.TestCase):
    """SC-2: residual-axis clean ∧ zero done-family integration titles → full pass."""

    def test_clean_spec_is_silent(self):
        yaml_text = (
            "tasks:\n"
            "  - id: TASK-001\n"
            "    title: write the parser\n"
            "    status: done\n"
            "  - id: TASK-002\n"
            "    title: add unit tests\n"
            "    status: completed\n"
        )
        with tmp_project() as root:
            result = gate_result(_spec(root, "clean-spec", yaml_text))
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["unverified_claims"], [])
            self.assertIsNone(result["d_payload"])  # no tracker, no blanket noise


class TestSC2bScopedIntegrityAxis(unittest.TestCase):
    """SC-2b: done-family integration titles → exactly one scoped claim + warn."""

    def test_done_integration_title_emits_scoped_claim(self):
        yaml_text = (
            "tasks:\n"
            "  - id: TASK-001\n"
            "    title: phase-d-closer integration (capture sub-step)\n"
            "    status: done\n"
        )
        with tmp_project() as root:
            result = gate_result(_spec(root, "integ-spec", yaml_text))
            self.assertEqual(result["verdict"], "warn")
            self.assertEqual(_claims(result), {_INTEGRATION})
            entry = result["unverified_claims"][0]
            self.assertIn("symbols", entry)
            self.assertIn("phase-d-closer integration", entry["reason"])
            self.assertIsNotNone(result["d_payload"])
            self.assertNotIn(_RETIRED_BLANKET, _claims(result))

    def test_pending_integration_title_does_not_double_report(self):
        # status filter (R3 tech-lead): a NON-done integration task is "unfinished",
        # not "an unverifiable completion claim" — residual axis owns it, no scoped claim.
        yaml_text = (
            "tasks:\n"
            "  - id: TASK-001\n"
            "    title: wire the collector integration\n"
            "    status: pending\n"
        )
        with tmp_project() as root:
            result = gate_result(_spec(root, "pending-integ-spec", yaml_text))
            self.assertNotIn(_INTEGRATION, _claims(result))
            self.assertEqual(result["verdict"], "pass")
            items = result["d_payload"]["deferred_items"]
            self.assertEqual(items[0]["reason"], "status=pending")

    def test_non_integration_titles_stay_clean(self):
        yaml_text = "tasks:\n  - id: TASK-001\n    title: rename a variable\n    status: done\n"
        with tmp_project() as root:
            result = gate_result(_spec(root, "plain-spec", yaml_text))
            self.assertEqual(result["unverified_claims"], [])


class TestSC3ParseFailGateResponse(unittest.TestCase):
    """SC-3a/b/c end-to-end (PP-R1 qa Minor-1): parse-fail → warn + -unparseable
    + non-None d_payload + soft_error, at the GATE layer (not just parser layer)."""

    def _assert_unparseable(self, result):
        self.assertEqual(result["verdict"], "warn")
        self.assertIn(_UNPARSEABLE, _claims(result))
        self.assertIsNotNone(result["d_payload"])
        self.assertTrue(result["soft_errors"])

    def test_markdown_fenced_pseudo_yaml(self):
        with tmp_project() as root:
            result = gate_result(_spec(root, "fence-spec", "# Doc\n```yaml\n- id: TASK-001\n```\n"))
            self._assert_unparseable(result)

    def test_no_tasks_block(self):
        with tmp_project() as root:
            result = gate_result(_spec(root, "notasks-spec", "metadata:\n  feature: x\n"))
            self._assert_unparseable(result)

    def test_zero_entries(self):
        with tmp_project() as root:
            result = gate_result(_spec(root, "zero-spec", "tasks:\n  # none\n"))
            self._assert_unparseable(result)

    def test_structural_inconsistency_falls_back_to_blanket(self):
        # SC-3e at gate layer: hidden entry → parse-fail → blanket (never silent pass)
        yaml_text = "tasks:\n  - id: TASK-001\n    status: done\n  - parent: 1.2\n    id: TASK-002\n"
        with tmp_project() as root:
            result = gate_result(_spec(root, "hidden-spec", yaml_text))
            self._assert_unparseable(result)


class TestSC4DualLayerNegControl(unittest.TestCase):
    """SC-4: tasks.md + yaml both present → tasks.md path, yaml status NOT read,
    no yaml-only claim of any kind (byte-identical to pre-change behaviour)."""

    def test_dual_layer_unaffected(self):
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "dual-spec"
            write_file(spec_dir / "proposal.md", _PROPOSAL)
            write_file(spec_dir / "tasks.md", "# tasks\n\n- [x] 1.1 finished\n- [ ] 1.2 open\n")
            # yaml statuses deliberately stale/all-pending (real dual-layer corpus shape)
            write_file(
                spec_dir / "detailed-tasks.yaml",
                "tasks:\n  - id: TASK-001\n    title: integration wiring\n    status: pending\n",
            )
            result = gate_result(spec_dir)
            claims = _claims(result)
            for tag in (_UNPARSEABLE, _INTEGRATION, _RETIRED_BLANKET):
                self.assertNotIn(tag, claims)

            # SC-4 (as narrowed by amendment A-5): assert the FULL d_payload
            # structure, not merely tag absence — a tag-absence-only assertion
            # would stay green even if the tasks.md path's payload silently
            # changed shape (pre-merge code-review I-1).
            self.assertEqual(result["verdict"], "pass")
            self.assertEqual(result["unverified_claims"], [])
            payload = result["d_payload"]
            self.assertIsNotNone(payload)
            self.assertEqual(payload["spec_id"], "dual-spec")
            self.assertEqual(payload["marker"], "<!-- archive-tracker:dual-spec -->")
            # deferred items come from the tasks.md unchecked box, NOT yaml status
            # (tasks.md path splits the "1.2" numbering into parent_id, line = body)
            self.assertEqual(
                [(i["parent_id"], i["line"], i["reason"]) for i in payload["deferred_items"]],
                [("1.2", "open", "unchecked")],
            )
            self.assertEqual(payload["unverified_claims"], [])
            # body: marker first (Step 7 search-before-create idempotency) and the
            # yaml's TASK-001 must not leak in
            self.assertTrue(payload["body"].startswith(payload["marker"]))
            self.assertIn("open (unchecked)", payload["body"])
            self.assertNotIn("TASK-001", payload["body"])
            # the one documented A-5 wording change lives here, and nowhere else
            self.assertIn("openspec-archive Step 7 归档提交后填入", payload["body"])


class TestFoldCrashFailsTowardWarn(unittest.TestCase):
    """Pre-merge silent-failure-hunter CRITICAL: when evaluating the yaml — the
    spec's ONLY completion datasource — crashes, the gate must fail toward warn,
    never toward a clean pass.

    `soft_errors` alone does not carry it: openspec-archive routes on `verdict`
    and gates the D auto-issue on `d_payload != null`; nothing consumes
    soft_errors. A `pass` here would be the #166 silent-false-green pattern
    recurring inside the change built to eliminate it.
    """

    def test_fold_crash_yields_warn_and_tracker(self):
        import spec_complete as sc  # noqa: E402

        yaml_text = "tasks:\n  - id: TASK-001\n    title: x\n    status: done\n"
        with tmp_project() as root:
            spec_dir = _spec(root, "crash-spec", yaml_text)
            original = sc._line_has_integration_keyword

            def boom(_line):
                raise RuntimeError("injected fold defect")

            sc._line_has_integration_keyword = boom
            try:
                result = gate_result(spec_dir)
            finally:
                sc._line_has_integration_keyword = original

            self.assertEqual(result["verdict"], "warn", result)
            self.assertIn(_UNPARSEABLE, _claims(result))
            self.assertIsNotNone(result["d_payload"])  # → D tracker fires headless
            self.assertTrue(result["warnings"])
            self.assertTrue(result["soft_errors"])


class TestRetiredBlanketClaim(unittest.TestCase):
    """The v1.61.0 blanket tag is fully retired — it must never appear again."""

    def test_blanket_tag_never_emitted(self):
        cases = {
            "clean": "tasks:\n  - id: T1\n    status: done\n",
            "residual": "tasks:\n  - id: T1\n    status: pending\n",
            "broken": "metadata:\n  x: 1\n",
        }
        with tmp_project() as root:
            for name, yaml_text in cases.items():
                result = gate_result(_spec(root, f"retired-{name}", yaml_text))
                self.assertNotIn(_RETIRED_BLANKET, _claims(result), name)


if __name__ == "__main__":
    unittest.main()
